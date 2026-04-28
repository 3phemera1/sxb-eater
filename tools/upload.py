#!/usr/bin/env python3
"""
upload.py - Upload code to the SXB bank 1 C monitor over serial.

Supports two modes:

  Binary mode (.bin)
    Converts raw binary to the monitor's "ADDR: HH HH ..." store commands.
    --addr is required to set the load address.

  S-record mode (.s19 / .srec / .mot)
    Uses the monitor's 'L' command.  The monitor handles only S1/S9 records;
    ld65's default output is S1/S9, so no pre-processing is needed.

Usage:
  upload.py <port> <file.bin>  --addr XXXX [--run] [--baud N]
  upload.py <port> <file.s19>              [--run] [--baud N]

Options:
  port        Serial port, e.g. /dev/cu.usbserial-A10MQ3SO
  file        Binary (.bin) or S-record (.s19 / .srec / .mot) file
  --addr      Load address for binary mode (hex, no 0x prefix, e.g. 4000)
  --run       Execute after upload.
              Binary: JSR to --addr.
              S-record: JSR to the S9 entry address (requires non-zero S9 addr).
              After the JSR, the tool tees serial output to stdout so you can
              see program output without having to reattach a terminal.
              Exit with Ctrl+C, or use --tail-idle to auto-exit after N seconds
              of silence.
  --tail-idle Seconds of serial silence after which --run tail mode exits
              automatically (default: 0 = wait for Ctrl+C).
  --baud      Serial baud rate (default: 115200)

Examples:
  upload.py /dev/cu.usbserial-XXXX myapp.s19 --run
  upload.py /dev/cu.usbserial-XXXX myapp.bin --addr 4000 --run
  upload.py /dev/cu.usbserial-XXXX myapp.bin --addr 4000 --run --tail-idle 2
"""

import argparse
import os
import re
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial is required: pip install pyserial")

# ── Constants ────────────────────────────────────────────────────────────────

PROMPT       = b"monitor> "
BAUD_DEFAULT = 115200
BYTES_PER_LINE = 8      # bytes per store command in binary mode

# ── Serial helpers ───────────────────────────────────────────────────────────

def wait_for(ser, marker, timeout=10.0):
    """
    Read bytes from *ser* until *marker* is found in the accumulated buffer.
    Returns the full buffer on success, None on timeout.
    """
    buf = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chunk = ser.read(32)
        if chunk:
            buf += chunk
            if marker in buf:
                return buf
    return None


def drain(ser, quiet_for=0.2, max_wait=1.0):
    """Discard any pending input from *ser* until the line goes quiet."""
    deadline = time.monotonic() + max_wait
    last_rx  = time.monotonic()
    while time.monotonic() < deadline:
        chunk = ser.read(256)
        if chunk:
            last_rx = time.monotonic()
        elif time.monotonic() - last_rx >= quiet_for:
            return
        else:
            time.sleep(0.02)


def sync_prompt(ser, attempts=4, per_try_timeout=2.0):
    """
    Robustly synchronise with the monitor's prompt.

    Drains any boot-time garbage, then sends a bare CR and waits for the
    prompt.  Retries up to *attempts* times.  Returns True on success,
    False if the monitor never responded.
    """
    drain(ser)
    for i in range(attempts):
        ser.reset_input_buffer()
        ser.write(b"\r")
        if wait_for(ser, PROMPT, timeout=per_try_timeout) is not None:
            # Drain any extra prompt fragments queued behind the first one.
            drain(ser)
            return True
    return False


def send_cmd(ser, cmd, timeout=10.0):
    """
    Send *cmd* (str) followed by CR, then wait for the next monitor prompt.
    Returns the response bytes on success, raises TimeoutError on failure.
    """
    ser.write(cmd.encode("ascii") + b"\r")
    resp = wait_for(ser, PROMPT, timeout=timeout)
    if resp is None:
        raise TimeoutError(f"No prompt after command: {cmd!r}")
    return resp

# ── Binary upload ────────────────────────────────────────────────────────────

def upload_binary(ser, data, load_addr, run=False):
    """
    Upload *data* starting at *load_addr* using store-bytes commands.
    Waits for the monitor prompt after each command (safe for any FIFO size).
    """
    total = len(data)
    addr  = load_addr
    sent  = 0

    print(f"  Uploading {total} bytes to {load_addr:04X} ...")
    while sent < total:
        chunk     = data[sent : sent + BYTES_PER_LINE]
        hex_bytes = " ".join(f"{b:02X}" for b in chunk)
        send_cmd(ser, f"{addr:04X}: {hex_bytes}")
        sent += len(chunk)
        addr += len(chunk)
        pct = 100 * sent // total
        print(f"\r  {sent}/{total} bytes  ({pct}%)", end="", flush=True)

    print(f"\r  {total}/{total} bytes  (100%)")

    if run:
        print(f"  Jumping to {load_addr:04X} ...")
        ser.write(f"{load_addr:04X}R\r".encode("ascii"))

# ── S-record upload ──────────────────────────────────────────────────────────

def upload_srec(ser, lines, run=False):
    """
    Upload S-records using the monitor's 'L' command.

    Protocol:
      Host sends     'L\\r'
      Monitor echoes  'L' then prints "Ready for SREC (S9 to end):\\r\\n"
      For each record  host sends line + '\\r\\n',  monitor replies ".\\r\\n"
      On S9           monitor replies "\\r\\nOK\\r\\n" then returns to prompt
    """
    # Filter to only non-empty S-record lines so we don't send blank lines.
    records = [ln.strip() for ln in lines if ln.strip().startswith("S")]
    if not records:
        raise ValueError("No S-record lines found in file")

    # Initiate load mode.
    ser.write(b"L\r")
    resp = wait_for(ser, b"Ready", timeout=5.0)
    if resp is None:
        raise TimeoutError("Monitor did not respond to 'L' command (no 'Ready' seen)")

    total   = len(records)
    entry   = 0

    print(f"  Sending {total} S-records ...")
    for i, rec in enumerate(records):
        ser.write(rec.encode("ascii") + b"\r\n")

        # Wait for per-record ack '.' or final 'OK'
        resp = wait_for(ser, b"\n", timeout=5.0)
        if resp is None:
            raise TimeoutError(f"No ack for record {i+1}: {rec}")
        if b"?" in resp:
            raise ValueError(f"Monitor rejected record {i+1}: {rec}")

        print(f"\r  {i+1}/{total} records", end="", flush=True)

        # 'OK' marks the end (S9 was processed)
        if b"OK" in resp:
            # Extract entry address from trailing "Entry: XXXX" if present
            # (printed after srec_load returns, before the prompt)
            result = wait_for(ser, PROMPT, timeout=5.0)
            if result:
                m = re.search(rb"Entry:\s+([0-9A-Fa-f]{4})", result)
                if m:
                    entry = int(m.group(1), 16)
            break

    print()

    if run:
        if entry == 0:
            print("  Warning: S9 entry address is 0 or absent — cannot auto-run.")
            return
        print(f"  Jumping to {entry:04X} ...")
        ser.write(f"{entry:04X}R\r".encode("ascii"))


# ── Tail mode (after --run) ──────────────────────────────────────────────────

def tail_output(ser, idle_timeout=0.0):
    """
    Stream bytes from *ser* to stdout until Ctrl+C (or until *idle_timeout*
    seconds of silence have elapsed, if idle_timeout > 0).

    Used after --run so the user can see fast programs that would otherwise
    finish before a separate terminal could be reattached.
    """
    if idle_timeout > 0:
        banner = f"── Program output (auto-exit after {idle_timeout}s idle) ──"
    else:
        banner = "── Program output (Ctrl+C to exit) ──"
    print(banner)
    sys.stdout.flush()

    last_rx = time.monotonic()
    try:
        while True:
            chunk = ser.read(256)
            if chunk:
                # Pass bytes through verbatim; let the terminal handle CR/LF.
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                last_rx = time.monotonic()
            elif idle_timeout > 0 and (time.monotonic() - last_rx) >= idle_timeout:
                break
            else:
                time.sleep(0.02)
    except KeyboardInterrupt:
        pass

    # Ensure we end on a fresh line for the closing banner.
    sys.stdout.buffer.write(b"\n")
    sys.stdout.flush()
    print("── End of output ──")

# ── Main ─────────────────────────────────────────────────────────────────────

SREC_EXTENSIONS = {".s19", ".srec", ".mot", ".s28"}


def main():
    ap = argparse.ArgumentParser(
        description="Upload code to the SXB bank 1 C monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("port", help="Serial port (e.g. /dev/cu.usbserial-XXXX)")
    ap.add_argument("file", help="File to upload (.bin or .s19/.srec/.mot)")
    ap.add_argument("--addr", help="Load address for .bin files (hex, e.g. 4000)")
    ap.add_argument("--run",  action="store_true", help="Execute after upload")
    ap.add_argument("--tail-idle", type=float, default=0.0, metavar="SECS",
                    help="Auto-exit --run tail mode after SECS of serial "
                         "silence (default: 0 = wait for Ctrl+C)")
    ap.add_argument("--baud", type=int, default=BAUD_DEFAULT,
                    help=f"Baud rate (default: {BAUD_DEFAULT})")
    args = ap.parse_args()

    ext     = os.path.splitext(args.file)[1].lower()
    is_srec = ext in SREC_EXTENSIONS

    if not is_srec and not args.addr:
        ap.error("--addr is required for binary files (e.g. --addr 4000)")

    with open(args.file, "rb") as fh:
        raw = fh.read()

    print(f"Connecting to {args.port} at {args.baud} baud ...")
    ser = serial.Serial(args.port, args.baud, timeout=0.1)
    time.sleep(0.5)     # let the FT245 enumerate

    # Synchronise with the monitor before sending any commands.  If the
    # prompt never appears, abort: silently proceeding causes the first
    # store command to race with whatever state the monitor is in, and
    # its bytes get eaten — corrupting the loaded image (issue observed
    # in the field: first 8 bytes at the load address came up as garbage).
    if not sync_prompt(ser):
        print("Error: monitor did not respond with a prompt.\n"
              "  - Is the board powered on and at the C monitor?\n"
              "  - Is another program (e.g. CoolTerm) holding the port?\n"
              "  - Try pressing RESET, then re-run upload.py.",
              file=sys.stderr)
        ser.close()
        sys.exit(1)
    print("  Monitor ready.")

    try:
        if is_srec:
            lines = raw.decode("ascii", errors="replace").splitlines()
            print(f"  File: {args.file}  ({len(raw)} bytes, S-record)")
            upload_srec(ser, lines, run=args.run)
        else:
            load_addr = int(args.addr, 16)
            print(f"  File: {args.file}  ({len(raw)} bytes, binary)")
            upload_binary(ser, raw, load_addr, run=args.run)
    except (TimeoutError, ValueError) as exc:
        print(f"\nUpload failed: {exc}", file=sys.stderr)
        ser.close()
        sys.exit(1)

    if args.run:
        tail_output(ser, idle_timeout=args.tail_idle)

    ser.close()
    print("Done.")


if __name__ == "__main__":
    main()
