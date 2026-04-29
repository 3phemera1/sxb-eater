#!/usr/bin/env python3
"""
dump_flash.py - Read the full 128KB SXB flash to a file (no flashing)

Wraps the same 65C02 flash-reader stub used by bootstrap_flash.py, but
without the interactive "save SXB_orig.bin" prompt or the writer step.
Useful for verifying the contents of the chip after a flash and for
diagnosing dump-tool bugs.

Board state requirements:
  * Factory SXB2 host mode (fresh chip with no WDC sig wiped),  OR
  * Wozmon running with NMI button available (handler bootstraps the
    same SXB2 host-mode protocol from RAM)

Usage:
  dump_flash.py <port> <out.bin>                 # single dump
  dump_flash.py <port> <out.bin> --twice         # dump twice + diff
  dump_flash.py <port> <out.bin> --base 0400     # relocate stub in RAM

Diagnostic tips:
  --twice
      Runs the dump twice in a row and reports a byte-level diff between
      the two passes.  If the chip itself is the source of any anomaly
      the two passes will be IDENTICAL.  If the dumper is unreliable,
      the two passes will diverge.

  --base XXXX  (hex, e.g. 0400 or 1000)
      Loads the reader stub at a different RAM address than the default
      $0800.  If the dump exhibits a small corrupted window at the start
      of bank 3 whose offset tracks --base (e.g. moves to $8400 when
      --base 0400 is used), bank 3's $8000+ region is being shadowed by
      RAM during the read — strongly indicating an SXB2 host-mode
      overlay or a flash CE# signalling bug rather than corrupt flash.

Exit codes:
  0  dump (and optional verify pass) completed successfully
  1  serial / handshake / protocol error
  2  --twice mode: second dump differs from first
"""

import argparse
import os
import sys
import time

try:
    import serial  # noqa: F401  (imported for clearer error if missing)
except ImportError:
    sys.exit("pyserial is required: pip install pyserial")

# Reuse the proven low-level helpers from the bootstrap script so we
# don't duplicate the 65C02 stub or the SXB2 protocol code.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap_flash as bf  # noqa: E402


TOTAL = 131072   # 4 banks × 32 KB


def dump_once(s, base, label=None):
    """
    Upload the reader stub at *base* and stream back exactly TOTAL bytes.
    Returns the bytes on success, raises RuntimeError on protocol error.
    """
    tag = f" [{label}]" if label else ""

    # Re-detect every pass: after a successful dump the SXB2 firmware is
    # back in its $55/$AA wait state, so a second pass needs the same
    # handshake the first pass did.
    state = bf.detect_board_state(s)
    if state == 'nmi':
        print(f"  Board not responding.  Press NMI now to arm the recovery"
              f" handler, then re-run.{tag}")
        raise RuntimeError("no SXB2 / NMI handshake")

    initial = (state == 'factory')
    if state == 'nmi_armed':
        # NMI handler answered $A5 → $01; subsequent CMDs use $A5 handshake.
        initial = False

    print(f"  Building reader stub (base = ${base:04X}){tag}...")
    reader = bf.build_flash_reader(base=base)
    print(f"    {len(reader)} bytes")

    print(f"  Uploading reader to ${base:04X}{tag}...")
    bf.sxb2_write_mem(s, reader, initial=initial, addr=base)

    print(f"  Executing reader{tag}...")
    s.reset_input_buffer()
    bf.sxb2_exec(s, base, initial=True)

    # Wait for 'R' (ready)
    s.timeout = 2.0
    r = s.read(1)
    if r != b'R':
        raise RuntimeError(f"expected 'R' from reader, got {r!r}")

    print(f"  Streaming {TOTAL} bytes{tag}...", end='', flush=True)
    s.timeout = 1.0
    out = bytearray()
    last_dot = 0
    t0 = time.time()
    while len(out) < TOTAL:
        chunk = s.read(TOTAL - len(out))
        if not chunk:
            print()
            raise RuntimeError(
                f"timeout after {len(out)} of {TOTAL} bytes")
        out.extend(chunk)
        while last_dot + 8192 <= len(out):
            print('.', end='', flush=True)
            last_dot += 8192
    elapsed = time.time() - t0
    print(f" done in {elapsed:.2f}s ({len(out)/1024/elapsed:.0f} KB/s)")

    # Wait for 'D'
    s.timeout = 1.0
    d = s.read(1)
    if d != b'D':
        print(f"  WARNING: expected 'D' tail marker, got {d!r}")

    # Reorder wire-order stream into canonical bank0..bank3 file layout.
    return bf.reorder_reader_stream(bytes(out))


def report_diff(a, b):
    """Print a per-bank summary of differences and contiguous diff runs."""
    if a == b:
        print("  PASSES MATCH — both dumps are byte-for-byte identical.")
        return True

    diffs = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
    print(f"  PASSES DIFFER — {len(diffs)} byte(s) different.")

    # Per-bank summary
    for bank in range(4):
        base = bank * 0x8000
        end  = base + 0x8000
        n = sum(1 for i in diffs if base <= i < end)
        if n:
            print(f"    Bank {bank}: {n} differing bytes")

    # Contiguous runs (first 16 only)
    runs = []
    s = p = diffs[0]
    for i in diffs[1:]:
        if i == p + 1:
            p = i
        else:
            runs.append((s, p)); s = p = i
    runs.append((s, p))
    print(f"  Diff runs (first 16 of {len(runs)}):")
    for s_, e_ in runs[:16]:
        bank = s_ // 0x8000
        cpu  = 0x8000 + (s_ & 0x7FFF)
        print(f"    file ${s_:05X}-${e_:05X}  ({e_-s_+1} bytes)  "
              f"bank {bank} CPU ${cpu:04X}")
    return False


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('port', help='Serial port (e.g. /dev/cu.usbserial-XXXX)')
    ap.add_argument('outfile', help='Output file for the 128KB dump')
    ap.add_argument('--twice', action='store_true',
                    help='Dump twice and diff (diagnostic; writes <outfile> '
                         'and <outfile>.2nd)')
    ap.add_argument('--base', default='0800',
                    help='Hex RAM base address for the reader stub '
                         '(default: 0800).  Useful for diagnosing bank-3 '
                         'RAM-aliasing artefacts.')
    args = ap.parse_args()

    try:
        base = int(args.base, 16)
    except ValueError:
        ap.error(f"--base must be hex (got {args.base!r})")
    if not (0x0200 <= base <= 0x7E00):
        ap.error(f"--base ${base:04X} outside safe RAM range $0200-$7E00")

    print("=" * 55)
    print("  SXB Flash Dumper")
    print("=" * 55)
    print(f"  Port:      {args.port}")
    print(f"  Output:    {args.outfile}")
    print(f"  Stub base: ${base:04X}")
    print(f"  Mode:      {'verify (dump twice)' if args.twice else 'single dump'}")
    print()

    print(f"Opening {args.port}...")
    s = bf.open_port(args.port)

    try:
        first = dump_once(s, base, label='pass 1' if args.twice else None)
    except RuntimeError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        s.close()
        sys.exit(1)

    print(f"Saving {len(first)} bytes to {args.outfile}...")
    with open(args.outfile, 'wb') as f:
        f.write(first)

    rc = 0
    if args.twice:
        print()
        print("─── Verify pass ───")
        try:
            second = dump_once(s, base, label='pass 2')
        except RuntimeError as e:
            print(f"\nERROR on second pass: {e}", file=sys.stderr)
            s.close()
            sys.exit(1)

        second_path = args.outfile + '.2nd'
        print(f"Saving {len(second)} bytes to {second_path}...")
        with open(second_path, 'wb') as f:
            f.write(second)

        print()
        print("─── Diff ───")
        if not report_diff(first, second):
            rc = 2

    s.close()
    print()
    print("Done.")
    sys.exit(rc)


if __name__ == '__main__':
    main()
