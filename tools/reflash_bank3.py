#!/usr/bin/env python3
"""
reflash_bank3.py - Reflash bank 3 (EhBASIC+Wozmon) via wozmon serial interface

No programmer needed. Talks directly to wozmon over USB serial.
Wozmon must be running (power cycle or reset to get '\\' prompt).

Usage:
  python3 reflash_bank3.py <port> <SXB_eater.bin>

  port:         e.g. /dev/cu.usbserial-A10MQ3SO
  SXB_eater.bin: built with 'make' (131072 bytes)
"""

import sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bootstrap_flash import build_flash_writer_for_bank, WRITER_BASE
import serial

BANK3_SIZE  = 32768
BYTES_PER_LINE = 8   # bytes per wozmon store line (keep short for reliability)


def open_port(port):
    s = serial.Serial(port, 115200, timeout=2)
    time.sleep(0.1)
    s.reset_input_buffer()
    return s


def woz_send_line(s, line, delay=0.05):
    """Send a line to wozmon and wait briefly."""
    s.write((line + '\r').encode())
    s.flush()
    time.sleep(delay)
    # drain any echo
    s.reset_input_buffer()


def woz_store(s, addr, data):
    """
    Store bytes into wozmon memory using the colon syntax:
    AAAA: xx xx xx xx ...
    """
    for offset in range(0, len(data), BYTES_PER_LINE):
        chunk = data[offset:offset+BYTES_PER_LINE]
        hex_bytes = ' '.join(f'{b:02X}' for b in chunk)
        line = f'{addr+offset:04X}:{hex_bytes}'
        woz_send_line(s, line, delay=0.08)
        print(f"\r  ${addr+offset:04X}: {hex_bytes}", end='', flush=True)
    print()


def reflash_bank3(port, image_path):
    print("=" * 55)
    print("  Bank 3 Reflasher via Wozmon")
    print("=" * 55)
    print()

    # Load image
    with open(image_path, 'rb') as f:
        full = f.read()

    if len(full) == 131072:
        bank3 = full[0x18000:0x20000]
        print(f"Loaded bank 3 from {image_path}")
    elif len(full) == 32768:
        bank3 = full
        print(f"Loaded 32KB image from {image_path}")
    else:
        print(f"ERROR: Expected 131072 or 32768 bytes, got {len(full)}")
        sys.exit(1)

    sig = bank3[0:4]
    reset = bank3[0x7FFC] | (bank3[0x7FFD] << 8)
    print(f"  $8000: {bank3[0:8].hex()}")
    print(f"  Sig: {'WDC sig OK' if sig==b'WDC\x00' else 'WARNING: no WDC sig'}")
    print(f"  RESET: ${reset:04x}")

    # Build flash writer for bank 3
    print()
    print("Building flash writer...")
    writer = build_flash_writer_for_bank(3)
    print(f"  {len(writer)} bytes at ${WRITER_BASE:04x}")

    # Open port
    print()
    print(f"Opening {port}...")
    s = open_port(port)

    print("Wozmon must be at '\\' prompt.")
    print("If in BASIC, press reset first.")
    input("Press Enter when wozmon '\\' prompt is visible...")

    # Wake up wozmon with a CR
    s.write(b'\r')
    s.flush()
    time.sleep(0.2)
    s.reset_input_buffer()

    # Upload flash writer to $0800 using wozmon store syntax
    print()
    print(f"Uploading flash writer ({len(writer)} bytes) to ${WRITER_BASE:04x}...")
    woz_store(s, WRITER_BASE, writer)
    print("  Upload complete")

    # Verify a few bytes were stored correctly
    # Read back using wozmon examine: just send the address
    print("Verifying first 4 bytes...")
    s.write(f'{WRITER_BASE:04X}\r'.encode())
    s.flush()
    time.sleep(0.3)
    verify_resp = s.read(50)
    print(f"  Wozmon response: {verify_resp.decode('ascii', errors='replace').strip()}")

    # Execute the flash writer
    # Wozmon: first send address to set XAML/XAMH, then 'R' to run
    print()
    print(f"Executing flash writer at ${WRITER_BASE:04x}...")
    s.write(f'{WRITER_BASE:04X}\r'.encode())
    s.flush()
    time.sleep(0.3)
    s.reset_input_buffer()
    s.write(b'R\r')
    s.flush()
    time.sleep(0.5)

    # Wait for 'R' ready signal
    print("Waiting for writer ready signal ('R')...")
    s.timeout = 5
    r = s.read(1)
    if r != b'R':
        # drain and check
        extra = s.read(10)
        print(f"ERROR: Expected 'R', got {r!r} + {extra!r}")
        print("  Flash writer may not have executed correctly")
        sys.exit(1)
    print("  Writer ready!")

    # Stream bank 3
    print()
    input(f"Press Enter to stream {BANK3_SIZE//1024}KB to bank 3 (Ctrl+C to abort)...")
    print()

    t0 = time.time()
    chunk = 256
    for i in range(0, BANK3_SIZE, chunk):
        pct = i * 100 // BANK3_SIZE
        print(f"\r  {pct:3d}%  ${0x8000+i:04x}  {i//1024}KB/{BANK3_SIZE//1024}KB",
              end='', flush=True)
        s.write(bank3[i:i+chunk])
        s.flush()

    elapsed = time.time() - t0
    print(f"\r  100%  {BANK3_SIZE//1024}KB sent in {elapsed:.1f}s{' '*20}")
    print()

    # Wait for 'D' done signal
    print("Waiting for completion ('D')...")
    s.timeout = 60
    d = s.read(1)
    if d == b'D':
        print(f"  Done! {time.time()-t0:.1f}s total")
    else:
        print(f"  WARNING: Expected 'D', got {d!r}")

    s.close()
    print()
    print("=" * 55)
    print("  Bank 3 reflashed! Board is resetting...")
    print("  Power cycle or press reset for wozmon prompt")
    print("=" * 55)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <port> <SXB_eater.bin>")
        sys.exit(1)
    reflash_bank3(sys.argv[1], sys.argv[2])
