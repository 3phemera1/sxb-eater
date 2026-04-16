#!/usr/bin/env python3
"""
bootstrap_flash.py - Flash EhBASIC to W65C02SXB without a chip programmer

Works on a FACTORY FRESH SXB (bank 0 empty, no WDC signature).
The SXB2 firmware enters host handshake mode in this state.

Strategy:
  For each 128-byte page of bank 0:
    1. Handshake with SXB2 firmware ($55/$AA -> $CC)
    2. CMD $07 (WRITE_MEM): upload [params(5) + code(60) + data(128)]
       to RAM at $0800 in one shot
    3. CMD $06 (EXEC_MEM): execute code at $0805
       Code reads params from $0800, data from $0841
       Programs the page into SST39SF010A flash
    4. Repeat for all 256 pages (32KB)

After flashing, reset the board - it will auto-boot to wozmon.

Requirements:
  pip install pyserial

Usage:
  python3 bootstrap_flash.py <port> <SXB_eater.bin>

  python3 bootstrap_flash.py /dev/cu.usbserial-A10MQ3SO build/SXB_eater.bin
"""

import sys
import time
import serial

# ── SST39SF010A constants ─────────────────────────────────────────────────────
# The SXB maps flash to CPU $8000-$FFFF (A15=1 selects flash).
# SST unlock addresses use only A0-A14:
#   chip $5555 with A15=1 -> CPU $D555  (in flash range, safe)
#   chip $2AAA with A15=1 -> CPU $AAAA  (in RAM range - will corrupt $AAAA!)
# We save/restore $AAAA around each operation.
UNLOCK1_ADDR = 0xD555   # CPU addr for SST unlock step 1
UNLOCK2_ADDR = 0xAAAA   # CPU addr for SST unlock step 2 (also RAM!)
UNLOCK1_DATA = 0xAA
UNLOCK2_DATA = 0x55
ERASE_SETUP  = 0x80
SECTOR_ERASE = 0x30
BYTE_PROGRAM = 0xA0
SECTOR_SIZE  = 0x1000   # 4KB

# ── RAM layout ────────────────────────────────────────────────────────────────
STUB_BASE   = 0x0800    # CMD $07 always writes here
PARAM_SRC   = 0x0800    # u16: source data address
PARAM_DST   = 0x0802    # u16: destination flash address
PARAM_FLAGS = 0x0804    # u8:  bit 0 = do sector erase first
CODE_START  = 0x0805    # executable code starts here
DATA_START  = 0x0841    # page data (128 bytes) starts here = CODE_START + 60

CODE_OFFSET = CODE_START - STUB_BASE   # = 5
DATA_OFFSET = DATA_START - STUB_BASE   # = 65

# ── SXB2 protocol ─────────────────────────────────────────────────────────────
CMD_READ  = 0x03
CMD_EXEC  = 0x06
CMD_WRITE = 0x07
MAGIC_ACK = 0xCC


def build_stub_code():
    """
    Build 60-byte 65C02 flash programming stub.

    Runs at $0805. Reads params from $0800-$0804.
    Data to program is at $0841 (DATA_START).

    Layout:
      $0800: src_lo, src_hi   (source data addr, always $0841)
      $0802: dst_lo, dst_hi   (destination flash addr)
      $0804: flags            (bit 0 = do sector erase)
      $0805: <code>           (this stub)
      $0841: <128 bytes data>
    """
    code = bytearray()

    def b(*args):
        code.extend(args)

    # Save $AAAA (will be clobbered by SST unlock)
    b(0xAD, 0xAA, 0xAA)     # LDA $AAAA
    b(0x48)                  # PHA

    # Check flags bit 0: do sector erase?
    b(0xAD, 0x04, 0x08)     # LDA $0804
    b(0x4A)                  # LSR A
    b(0x90, 0x1A)            # BCC skip_erase  (+26)

    # ── Sector erase ──────────────────────────────────────────────────────────
    # $AA->$D555, $55->$AAAA, $80->$D555, $AA->$D555, $55->$AAAA, $30->(dst)
    b(0xA9, UNLOCK1_DATA)
    b(0x8D, UNLOCK1_ADDR & 0xFF, UNLOCK1_ADDR >> 8)  # STA $D555
    b(0xA9, UNLOCK2_DATA)
    b(0x8D, UNLOCK2_ADDR & 0xFF, UNLOCK2_ADDR >> 8)  # STA $AAAA
    b(0xA9, ERASE_SETUP)
    b(0x8D, UNLOCK1_ADDR & 0xFF, UNLOCK1_ADDR >> 8)  # STA $D555
    b(0xA9, UNLOCK1_DATA)
    b(0x8D, UNLOCK1_ADDR & 0xFF, UNLOCK1_ADDR >> 8)  # STA $D555
    b(0xA9, UNLOCK2_DATA)
    b(0x8D, UNLOCK2_ADDR & 0xFF, UNLOCK2_ADDR >> 8)  # STA $AAAA
    b(0xA9, SECTOR_ERASE)
    b(0x8D, 0x02, 0x08)     # STA ($0802) -- sector address lo from param
    # Poll bit 7 of dst until set (erase complete)
    # erase_poll: LDA (dst), AND #$80, BEQ erase_poll
    b(0xAD, 0x02, 0x08)     # LDA $0802 (dst_lo)
    b(0x85, 0xFE)            # STA $FE   (tmp ptr lo)
    b(0xAD, 0x03, 0x08)     # LDA $0803 (dst_hi)
    b(0x85, 0xFF)            # STA $FF   (tmp ptr hi)
    # erase_poll:
    b(0xB1, 0xFE)            # LDA ($FE),Y   Y=0 from init below
    b(0x29, 0x80)            # AND #$80
    b(0xF0, 0xFB)            # BEQ erase_poll  (-5)
    # skip_erase:

    # ── Byte program loop ─────────────────────────────────────────────────────
    # Set up pointers: $FC/$FD = DATA_START ($0841), $FE/$FF = dst
    b(0xA9, DATA_START & 0xFF)
    b(0x85, 0xFC)            # STA $FC
    b(0xA9, DATA_START >> 8)
    b(0x85, 0xFD)            # STA $FD
    b(0xAD, 0x02, 0x08)     # LDA $0802
    b(0x85, 0xFE)            # STA $FE
    b(0xAD, 0x03, 0x08)     # LDA $0803
    b(0x85, 0xFF)            # STA $FF
    b(0xA0, 0x00)            # LDY #0

    # byte_loop:
    # Unlock + program
    b(0xA9, UNLOCK1_DATA)
    b(0x8D, UNLOCK1_ADDR & 0xFF, UNLOCK1_ADDR >> 8)
    b(0xA9, UNLOCK2_DATA)
    b(0x8D, UNLOCK2_ADDR & 0xFF, UNLOCK2_ADDR >> 8)
    b(0xA9, BYTE_PROGRAM)
    b(0x8D, UNLOCK1_ADDR & 0xFF, UNLOCK1_ADDR >> 8)
    b(0xB1, 0xFC)            # LDA ($FC),Y  (src byte)
    b(0x91, 0xFE)            # STA ($FE),Y  (write to flash)
    # Poll: CMP ($FE),Y until bit 7 matches written bit 7
    b(0xD1, 0xFE)            # CMP ($FE),Y
    b(0x29, 0x80)            # AND #$80     (bit 7 only)
    b(0xF0, 0xFB)            # BEQ poll (-5) -- bit 7 inverted during program
    b(0xC8)                  # INY
    b(0xC0, 0x80)            # CPY #128
    b(0xD0, 0xE3)            # BNE byte_loop (-29)

    # Restore $AAAA
    b(0x68)                  # PLA
    b(0x8D, UNLOCK2_ADDR & 0xFF, UNLOCK2_ADDR >> 8)  # STA $AAAA

    b(0x60)                  # RTS

    size = len(code)
    max_size = DATA_OFFSET - CODE_OFFSET   # = 60 bytes
    print(f"  Stub code: {size} bytes (max {max_size})")
    if size > max_size:
        raise RuntimeError(f"Stub too large: {size} > {max_size} bytes!")

    # Pad to exactly max_size
    code.extend([0xEA] * (max_size - size))
    return bytes(code)


def build_upload_block(stub_code, dst_addr, page_data, do_erase):
    """
    Build the 193-byte block uploaded via CMD $07 each page.
    Layout: params(5) + code(60) + data(128)
    """
    assert len(stub_code) == 60
    assert len(page_data) == 128

    flags = 0x01 if do_erase else 0x00
    params = bytes([
        DATA_START & 0xFF,   # src_lo  ($0841)
        DATA_START >> 8,     # src_hi
        dst_addr & 0xFF,     # dst_lo
        dst_addr >> 8,       # dst_hi
        flags,               # flags
    ])
    return params + stub_code + page_data


def open_port(port):
    s = serial.Serial(port, 115200, timeout=2)
    time.sleep(0.1)
    s.reset_input_buffer()
    return s


def handshake(s):
    for attempt in range(5):
        s.reset_input_buffer()
        s.write(bytes([0x55, 0xAA]))
        s.flush()
        time.sleep(0.05)
        resp = s.read(1)
        if resp == bytes([MAGIC_ACK]):
            return True
        time.sleep(0.2)
    return False


def write_mem(s, data):
    """CMD $07: write data to RAM at $0800."""
    length = len(data)
    if not handshake(s):
        raise RuntimeError("Handshake failed")
    header = bytes([
        CMD_WRITE,
        0x00, 0x08, 0x00,        # addr $0800 (ignored, always writes here)
        length & 0xFF, (length >> 8) & 0xFF, 0x00
    ])
    s.write(header)
    s.write(data)
    s.flush()
    time.sleep(0.05)


def exec_mem(s, addr):
    """CMD $06: execute at address."""
    if not handshake(s):
        raise RuntimeError("Handshake failed")
    s.write(bytes([CMD_EXEC, addr & 0xFF, (addr >> 8) & 0xFF, 0x00]))
    s.flush()
    time.sleep(0.05)


def read_mem(s, addr, length):
    """CMD $03: read from address."""
    if not handshake(s):
        raise RuntimeError("Handshake failed")
    s.write(bytes([
        CMD_READ,
        addr & 0xFF, (addr >> 8) & 0xFF, 0x00,
        length & 0xFF, (length >> 8) & 0xFF, 0x00
    ]))
    s.flush()
    time.sleep(0.05)
    return s.read(length)


def bootstrap(port, image_path):
    print("=" * 55)
    print("  SXB EhBASIC Bootstrap Flasher")
    print("=" * 55)
    print()

    print(f"Loading {image_path}...")
    with open(image_path, 'rb') as f:
        flash_image = f.read()
    bank0 = flash_image[0x00000:0x08000]
    print(f"  Bank 0: {len(bank0)} bytes")
    print(f"  Signature at $8000: {bank0[0:4].hex()} ", end='')
    if bank0[0:4] == b'WDC\x00':
        print("(WDC\\x00 - will auto-boot after flash)")
    else:
        print("WARNING: missing WDC\\x00 signature!")

    print()
    print("Building flash stub...")
    stub_code = build_stub_code()

    print()
    print(f"Opening {port}...")
    s = open_port(port)

    print("Waiting for SXB2 handshake...")
    print("  (Board must be in host mode - bank 0 empty, no WDC signature)")
    if not handshake(s):
        print()
        print("ERROR: No response from SXB2 firmware.")
        print("  Possible causes:")
        print("  - Board not powered on")
        print("  - Bank 0 already has WDC\\x00 (board auto-booted, not in host mode)")
        print("  - Another terminal (CoolTerm etc) has the port open")
        print("  - Wrong serial port")
        sys.exit(1)
    print("  Handshake OK!")

    PAGE_SIZE  = 128
    num_pages  = len(bank0) // PAGE_SIZE  # 256 pages for 32KB
    num_sectors = len(bank0) // SECTOR_SIZE  # 8 sectors of 4KB

    print()
    print(f"Flashing {num_pages} pages ({num_sectors} sectors)...")
    print(f"  Each sector erase: ~25ms, each page program: ~2ms")
    print(f"  Estimated time: ~{(num_sectors * 25 + num_pages * 3) // 1000 + 1}s")
    print()

    input("Press Enter to begin (Ctrl+C to abort)...")
    print()

    start_time = time.time()
    errors = 0

    for page in range(num_pages):
        src_offset = page * PAGE_SIZE
        dst_addr   = 0x8000 + src_offset
        page_data  = bank0[src_offset:src_offset + PAGE_SIZE]
        do_erase   = (src_offset % SECTOR_SIZE) == 0

        sector_str = f" [ERASE sector {src_offset // SECTOR_SIZE}]" if do_erase else ""
        print(f"\r  Page {page+1:3d}/{num_pages} ${dst_addr:04x}{sector_str:30s}",
              end='', flush=True)

        # Build and upload block
        block = build_upload_block(stub_code, dst_addr, page_data, do_erase)
        write_mem(s, block)

        # Execute stub at CODE_START
        exec_mem(s, CODE_START)

        # Wait for completion (erase takes longer)
        wait = 0.030 if do_erase else 0.005
        time.sleep(wait)

    elapsed = time.time() - start_time
    print(f"\r  {num_pages} pages complete in {elapsed:.1f}s{' ' * 30}")
    print()

    # Verify first 64 bytes
    print("Verifying first 64 bytes...")
    readback = read_mem(s, 0x8000, 64)
    expected = bank0[:64]
    if readback == expected:
        print("  Verify OK!")
    else:
        print("  MISMATCH!")
        for i in range(64):
            if i < len(readback) and readback[i] != expected[i]:
                print(f"    ${0x8000+i:04x}: expected {expected[i]:02x}, got {readback[i]:02x}")
        errors += 1

    s.close()
    print()

    if errors == 0:
        print("=" * 55)
        print("  SUCCESS! EhBASIC flashed to bank 0.")
        print()
        print("  Power cycle or reset the board.")
        print("  You should see the LED diamond sequence,")
        print("  then the wozmon '\\' prompt.")
        print("  Type A089R to launch MS BASIC.")
        print("=" * 55)
    else:
        print("Flashing completed with errors. Check connections and retry.")
        sys.exit(1)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <port> <SXB_eater.bin>")
        print()
        print("  port:         serial port (e.g. /dev/cu.usbserial-A10MQ3SO)")
        print("  SXB_eater.bin: flash image from 'make'")
        print()
        print("Board must be in host mode (factory state, bank 0 empty).")
        sys.exit(1)
    bootstrap(sys.argv[1], sys.argv[2])
