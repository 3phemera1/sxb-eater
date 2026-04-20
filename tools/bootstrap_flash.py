#!/usr/bin/env python3
"""
bootstrap_flash.py - Flash W65C02SXB without a chip programmer

Works on a FACTORY FRESH SXB (bank 3 = SXB2, banks 0-2 empty).
SXB2 enters host handshake mode when no WDC signature found.

Strategy:
  1. Use SXB2 CMD $07 to upload a monolithic RAM flash writer (~246 bytes)
  2. Use SXB2 CMD $06 to execute the flash writer
  3. Flash writer receives the full 128KB image over serial (raw bytes)
  4. Flash writer programs all 4 banks sequentially
  5. Board resets when done

The flash writer runs entirely from RAM ($1000), so bank switching
during programming never kills the command loop.

Final flash layout (from SXB_eater.bin):
  Bank 0: WDCMON           (accessible via wozmon B0 command)
  Bank 1: empty
  Bank 2: empty
  Bank 3: EhBASIC+Wozmon  (default auto-boot)

Requirements:  pip install pyserial
Usage:
  python3 bootstrap_flash.py <port> <SXB_eater.bin>
"""

import sys
import time
import serial

# SXB2 protocol
CMD_EXEC    = 0x06
CMD_WRITE   = 0x07
MAGIC_ACK   = 0xCC

# VIA2 serial
VIA2_ORB  = 0x7FE0
VIA2_ORA  = 0x7FE1
VIA2_DDRB = 0x7FE2
VIA2_DDRA = 0x7FE3
VIA2_PCR  = 0x7FEC

# SST39SF010A unlock addresses (valid when any bank active)
UNLOCK1 = 0xD555
UNLOCK2 = 0xAAAA

# Bank PCR values
PCR = {0: 0xCC, 1: 0xCE, 2: 0xEC, 3: 0xEE}

# Flash writer base address in RAM
WRITER_BASE = 0x0800


def build_flash_writer():
    """
    Build monolithic 65C02 flash writer that runs from RAM at $1000.

    Protocol after exec:
      Board sends 'R' (ready)
      Host sends 131072 raw bytes (full 128KB image)
      Board programs all 4 banks sequentially
      Board sends 'D' (done) then resets

    Bank order: 0,1,2,3 — host sends them in that order.
    Each bank is 32768 bytes = 8 sectors of 4096 bytes.
    """
    code = bytearray()
    labels = {}
    fixups = []

    def b(*args): code.extend(args)
    def pc(): return WRITER_BASE + len(code)
    def label(name): labels[name] = len(code)

    def bne(name):
        fixups.append((len(code)+1, name, len(code)+2, 'rel'))
        b(0xD0, 0x00)
    def beq(name):
        fixups.append((len(code)+1, name, len(code)+2, 'rel'))
        b(0xF0, 0x00)
    def jmp(name):
        fixups.append((len(code)+1, name, None, 'abs'))
        b(0x4C, 0x00, 0x00)
    def jsr(name):
        fixups.append((len(code)+1, name, None, 'abs'))
        b(0x20, 0x00, 0x00)

    # ZP variables (avoid SXB2 ZP $02-$10)
    PTR_LO   = 0x20
    PTR_HI   = 0x21
    SECT_CNT = 0x22
    BC_LO    = 0x23
    BC_HI    = 0x24
    BANK_CNT = 0x25

    # ── Entry ──────────────────────────────────────────────────────────────
    label('start')
    b(0x78)                      # SEI
    b(0xD8)                      # CLD
    b(0xA2, 0x00)                # LDX #0 (keep X=0 throughout)

    # VIA2 init
    b(0xA9, 0x0C); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xA9, 0x0C); b(0x8D, VIA2_DDRB&0xFF, VIA2_DDRB>>8)
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)

    # Send 'R' ready signal
    b(0xA9, ord('R')); jsr('uart_tx')

    # Init bank counter
    b(0xA9, 0x00); b(0x85, BANK_CNT)

    # ── Bank loop ──────────────────────────────────────────────────────────
    label('bank_loop')

    # Select bank: load PCR from table[bank*2]
    b(0xA5, BANK_CNT); b(0x0A); b(0xAA)   # LDA bank, ASL, TAX
    b(0xBD, 0x00, 0x00)                    # LDA pcr_table,X (patch below)
    pcr_ref = len(code) - 2
    b(0x8D, VIA2_PCR&0xFF, VIA2_PCR>>8)
    b(0xA2, 0x00)                           # LDX #0 (restore X=0)

    # Init ptr = $8000, sect_cnt = 8
    b(0xA9, 0x00); b(0x85, PTR_LO)
    b(0xA9, 0x80); b(0x85, PTR_HI)
    b(0xA9, 0x08); b(0x85, SECT_CNT)

    # ── Sector loop ────────────────────────────────────────────────────────
    label('sector_loop')

    # Sector erase
    b(0xA9, 0xAA); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0x55); b(0x8D, UNLOCK2&0xFF, UNLOCK2>>8)
    b(0xA9, 0x80); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0xAA); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0x55); b(0x8D, UNLOCK2&0xFF, UNLOCK2>>8)
    b(0xA9, 0x30); b(0x81, PTR_LO)         # STA (PTR,X)

    # Poll DQ7 (erase: DQ7=0 until done, then DQ7=1)
    label('erase_poll')
    b(0xA1, PTR_LO)                         # LDA (PTR,X)
    b(0x29, 0x80)
    beq('erase_poll')

    # Init byte counter = 4096 ($1000)
    b(0xA9, 0x00); b(0x85, BC_LO)
    b(0xA9, 0x10); b(0x85, BC_HI)

    # ── Byte loop ──────────────────────────────────────────────────────────
    label('byte_loop')

    # Receive byte
    jsr('uart_rx')                          # returns byte in A

    # Byte program
    b(0xA8)                                 # TAY (save)
    b(0xA9, 0xAA); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0x55); b(0x8D, UNLOCK2&0xFF, UNLOCK2>>8)
    b(0xA9, 0xA0); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0x98)                                 # TYA (restore)
    b(0x81, PTR_LO)                         # STA (PTR,X)

    # 40us delay (320 cycles @ 8MHz)
    b(0xA9, 0x40)
    label('delay')
    b(0x3A)                                 # DEC A (65C02)
    bne('delay')

    # Advance pointer
    b(0xE6, PTR_LO)
    b(0xD0, 0x03)                           # BNE +3
    b(0xE6, PTR_HI)
    b(0xEA)                                 # NOP (branch target padding)

    # Dec byte counter
    label('dec_bc')
    b(0xA5, BC_LO); b(0x3A); b(0x85, BC_LO)  # DEC BC_LO
    bne('byte_loop')
    b(0xA5, BC_HI); b(0x3A); b(0x85, BC_HI)  # DEC BC_HI
    bne('byte_loop')

    # Dec sector counter
    b(0xC6, SECT_CNT)
    bne('sector_loop')

    # Advance bank
    b(0xE6, BANK_CNT)
    b(0xA5, BANK_CNT); b(0xC9, 0x04)
    bne('bank_loop')

    # Done — send 'D', reset
    b(0xA9, ord('D')); jsr('uart_tx')
    b(0x6C, 0xFC, 0xFF)                    # JMP ($FFFC) reset

    # ── uart_tx ────────────────────────────────────────────────────────────
    label('uart_tx')
    b(0x48)
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    b(0x68); b(0x48)
    b(0x8D, VIA2_ORA&0xFF, VIA2_ORA>>8)
    label('tx_wait')
    b(0xA9, 0x01); b(0x2C, VIA2_ORB&0xFF, VIA2_ORB>>8)
    bne('tx_wait')
    b(0xAD, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x09, 0x04); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xA9, 0xFF); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    b(0xEA); b(0xEA)
    b(0xAD, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x29, 0xFB); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    b(0x68); b(0x60)

    # ── uart_rx ────────────────────────────────────────────────────────────
    label('uart_rx')
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    label('rx_wait')
    b(0xA9, 0x02); b(0x2C, VIA2_ORB&0xFF, VIA2_ORB>>8)
    bne('rx_wait')
    b(0xAD, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x29, 0xF7); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xEA); b(0xEA)
    b(0xAD, VIA2_ORA&0xFF, VIA2_ORA>>8)
    b(0x48)
    b(0xAD, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x09, 0x08); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x68); b(0x60)

    # ── PCR table ──────────────────────────────────────────────────────────
    label('pcr_table')
    pcr_table_abs = WRITER_BASE + len(code)
    for bank in range(4):
        b(PCR[bank], PCR[bank])  # two copies each (for ASL*index trick)

    # Patch PCR table reference
    code[pcr_ref]   = pcr_table_abs & 0xFF
    code[pcr_ref+1] = pcr_table_abs >> 8

    # Resolve fixups
    for off, name, rel_base, kind in fixups:
        target_abs = WRITER_BASE + labels[name]
        if kind == 'abs':
            code[off]   = target_abs & 0xFF
            code[off+1] = target_abs >> 8
        else:
            code[off] = (target_abs - (WRITER_BASE + rel_base)) & 0xFF

    return bytes(code)


def open_port(port):
    s = serial.Serial(port, 115200, timeout=3)
    time.sleep(0.1)
    s.reset_input_buffer()
    return s


def sxb2_handshake(s, initial=False):
    """
    initial=True  (factory mode): send $55/$AA, wait for $CC ACK
    initial=False (NMI mode):     send $A5, wait for $01 ACK
    """
    if not initial:
        # NMI mode: send $A5, wait for $01
        # Don't reset_input_buffer - $01 may arrive any time after NMI press
        for _ in range(60):
            s.write(bytes([0xA5]))
            s.flush()
            time.sleep(0.3)
            resp = s.read(2)
            if resp and resp[0] == 0x01:
                return True
        return False
    else:
        # Factory SXB2 mode: $55/$AA -> $CC
        for _ in range(30):
            s.reset_input_buffer()
            s.write(bytes([0x55, 0xAA]))
            s.flush()
            time.sleep(0.05)
            resp = s.read(1)
            if resp == bytes([MAGIC_ACK]):
                return True
            time.sleep(0.1)
        return False


def sxb2_write_mem(s, data, initial=False):
    """Upload data to RAM at $0800 via SXB2 CMD $07."""
    if not sxb2_handshake(s, initial=initial):
        raise RuntimeError("SXB2 handshake failed")
    n = len(data)
    s.write(bytes([CMD_WRITE, 0x00, 0x08, 0x00,
                   n & 0xFF, (n >> 8) & 0xFF, 0x00]))
    s.write(data)
    s.flush()
    time.sleep(0.05 + n * 0.0001)


def sxb2_exec(s, addr):
    """Execute at addr via SXB2 CMD $06."""
    if not sxb2_handshake(s, initial=False):
        raise RuntimeError("SXB2 handshake failed")
    s.write(bytes([CMD_EXEC, addr & 0xFF, (addr >> 8) & 0xFF, 0x00]))
    s.flush()


def upload_writer(s, writer, nmi_mode=False):
    """Upload flash writer to RAM.
    nmi_mode=True:  after $01 ACK, send 255 bytes, board executes at $0800
    nmi_mode=False: factory CMD $07 protocol to $0800
    """
    if nmi_mode:
        assert len(writer) <= 255, f"Writer too large: {len(writer)}"
        padded = (writer + bytes(255))[:255]
        print(f"  Uploading {len(writer)} bytes to $0800 (NMI mode)...")
        s.write(padded)
        s.flush()
        time.sleep(0.05 + 255 * 0.0001)
    else:
        assert len(writer) <= 512, f"Writer too large: {len(writer)}"
        print(f"  Uploading {len(writer)} bytes to ${WRITER_BASE:04x}...")
        sxb2_write_mem(s, writer, initial=False)


def bootstrap(port, image_path):
    print("=" * 55)
    print("  SXB Bootstrap Flasher")
    print("=" * 55)
    print()

    print(f"Loading {image_path}...")
    with open(image_path, 'rb') as f:
        image = f.read()
    if len(image) != 131072:
        print(f"ERROR: Expected 131072 bytes, got {len(image)}")
        sys.exit(1)

    print(f"  {len(image)} bytes")
    for bank in range(4):
        base = bank * 0x8000
        sig = image[base:base+4]
        reset = image[base+0x7FFC] | (image[base+0x7FFD]<<8)
        print(f"  Bank {bank}: {image[base:base+8].hex()}  RESET=${reset:04x}", end='')
        if sig == b'WDC\x00':
            jmp = image[base+5] | (image[base+6]<<8)
            print(f"  JMP ${jmp:04x}", end='')
        print()

    print()
    print("Building flash writer...")
    writer = build_flash_writer()
    print(f"  {len(writer)} bytes at ${WRITER_BASE:04x}")

    print()
    print(f"Opening {port}...")
    s = open_port(port)

    # NMI mode: bank 0 has SXB2 with wiped sig
    nmi_mode = (image[0] == 0xFF and image[4] == 0x4C)

    if nmi_mode:
        print("Waiting for NMI handshake...")
        print("  (Press NMI button on board)")
        if not sxb2_handshake(s, initial=False):
            print("ERROR: No NMI response.")
            sys.exit(1)
    else:
        print("Waiting for SXB2 handshake...")
        print("  (Board must be in host mode - bank 0 empty)")
        if not sxb2_handshake(s, initial=True):
            print("ERROR: No SXB2 response.")
            sys.exit(1)
    print("  Handshake OK!")

    print()
    print("Uploading flash writer to RAM...")
    upload_writer(s, writer, nmi_mode=nmi_mode)
    print("  Upload complete")

    if not nmi_mode:
        print("Executing flash writer...")
        sxb2_exec(s, WRITER_BASE)
        time.sleep(0.5)
    else:
        time.sleep(0.3)

    # Wait for 'R' (ready)
    print("Waiting for writer ready signal ('R')...")
    r = s.read(1)
    if r != b'R':
        print(f"ERROR: Expected 'R', got {r!r}")
        sys.exit(1)
    print("  Writer ready!")

    print()
    total = len(image)
    print(f"Sending {total} bytes...")
    print(f"  Bank order: 0,1,2,3")
    print(f"  ~{total*10//115200 + total//256*25//1000 + 8}s estimated")
    print()

    input("Press Enter to begin (Ctrl+C to abort)...")
    print()

    t0 = time.time()
    chunk = 256
    for i in range(0, total, chunk):
        bank = i // 0x8000
        offset = i % 0x8000
        addr = 0x8000 + offset
        pct = i * 100 // total
        print(f"\r  {pct:3d}%  bank {bank}  ${addr:04x}  {i//1024:3d}KB/{total//1024}KB",
              end='', flush=True)
        s.write(image[i:i+chunk])
        s.flush()
        # Small throttle to avoid overwhelming the board
        # Board programs at ~40us/byte, 256 bytes = ~10ms
        # Serial at 115200 = 256 bytes in ~22ms - serial is the bottleneck
        # No extra delay needed

    elapsed = time.time() - t0
    print(f"\r  100%  {total//1024}KB sent in {elapsed:.1f}s{' '*20}")
    print()

    # Wait for 'D' (done)
    print("Waiting for completion signal ('D')...")
    s.timeout = 120  # give it time to finish programming
    d = s.read(1)
    total_elapsed = time.time() - t0
    if d == b'D':
        print(f"  Done! Total time: {total_elapsed:.1f}s")
    else:
        print(f"  WARNING: Expected 'D', got {d!r}")

    s.close()
    print()
    print("=" * 55)
    print("  Flash complete! Board is resetting...")
    print()
    print("  Boot: LED diamond -> wozmon '\\' prompt")
    print("  A0B9R  -> MS BASIC (check lbl file to be sure)")
    print("  B0     -> WDCMON (if you have SXB_ORIG.bin)")
    print("  B1/B2  -> user ROM")
    print("  B3     -> reload wozmon")
    print("=" * 55)


def reflash_bank(port, image_path, bank, s=None):
    """Reflash a single bank. Useful for development iteration."""
    print("=" * 55)
    print(f"  Reflash Bank {bank}")
    print("=" * 55)
    print()

    with open(image_path, 'rb') as f:
        full = f.read()

    if len(full) == 131072:
        bank_image = full[bank*0x8000:(bank+1)*0x8000]
    elif len(full) == 32768 and bank == 3:
        bank_image = full
    else:
        print(f"ERROR: Expected 131072 bytes or 32768 bytes for bank 3")
        sys.exit(1)

    print(f"  Bank {bank}: {bank_image[0:8].hex()}")

    # Build single-bank image: pad others with $FF
    image = bytearray([0xFF] * 131072)
    image[bank*0x8000:(bank+1)*0x8000] = bank_image

    # Build writer that only programs target bank
    writer = build_flash_writer_single_bank(bank)
    print(f"  Writer: {len(writer)} bytes at ${WRITER_BASE:04x}")

    print()
    if s is None:
        print(f"Opening {port}...")
        s = open_port(port)
    print("Waiting for handshake...")
    if not sxb2_handshake(s, initial=True):
        print("ERROR: No response. Make sure board is in WDCMON mode (B0 from wozmon).")
        sys.exit(1)
    print("  Handshake OK!")

    sxb2_write_mem(s, writer, initial=True)
    sxb2_exec(s, WRITER_BASE)
    time.sleep(0.5)

    r = s.read(1)
    if r != b'R':
        print(f"ERROR: Expected 'R', got {r!r}")
        sys.exit(1)
    print("  Writer ready!")

    input("Press Enter to begin (Ctrl+C to abort)...")
    t0 = time.time()
    chunk = 256
    for i in range(0, 32768, chunk):
        pct = i * 100 // 32768
        print(f"\r  {pct:3d}%  ${0x8000+i:04x}", end='', flush=True)
        s.write(bank_image[i:i+chunk])
        s.flush()
    elapsed = time.time() - t0
    print(f"\r  100%  done in {elapsed:.1f}s{' '*20}")

    s.timeout = 60
    d = s.read(1)
    if d == b'D':
        print(f"  Done!")
    else:
        print(f"  WARNING: Expected 'D', got {d!r}")

    s.close()
    print()
    print("=" * 55)
    print(f"  Bank {bank} reflashed! Board resetting...")
    print("=" * 55)


def build_flash_writer_single_bank(target_bank):
    """Flash writer that programs only one bank (32KB = 8 sectors)."""
    # Same as build_flash_writer but bank loop replaced with single bank
    # Reuse build_flash_writer with a wrapper that sends 32KB for target bank
    # and $FF for all others - but actually simpler to just patch the image.
    # The full writer already handles this correctly - we send the full 128KB
    # image with only target bank populated, others filled with $FF.
    # $FF pages skip programming (already erased state).
    # Actually we need a writer that only erases/programs target bank.
    # Simplest: use the full writer but send only 32KB for the target bank
    # by using a single-bank variant.
    # For now just use the full writer - caller sends 32KB repeated as needed.
    # Actually: build_flash_writer programs all 4 banks sequentially.
    # We need one that jumps directly to the target bank.
    return build_flash_writer_for_bank(target_bank)


def build_flash_writer_for_bank(target_bank):
    """
    Flash writer for a single bank. Same as build_flash_writer but
    only programs the target bank. Receives 32768 raw bytes.
    
    SST39SF010A unlock addresses ($D555/$AAAA) are physical addresses
    that only map correctly when bank 0 is active (PCR=$CC).
    For any target bank, we switch to bank 0 for unlocks, then back
    to target bank for the actual erase/program command.
    """
    VIA2_ORB  = 0x7FE0
    VIA2_ORA  = 0x7FE1
    VIA2_DDRB = 0x7FE2
    VIA2_DDRA = 0x7FE3
    VIA2_PCR  = 0x7FEC
    UNLOCK1   = 0xD555   # valid when bank 0 active
    UNLOCK2   = 0xAAAA   # valid when bank 0 active
    PCR_BANK0 = PCR[0]   # always use bank 0 for unlock sequences
    PCR_VAL   = PCR[target_bank]

    PTR_LO   = 0x20
    PTR_HI   = 0x21
    SECT_CNT = 0x22
    BC_LO    = 0x23
    BC_HI    = 0x24

    code = bytearray()
    labels = {}
    fixups = []

    def b(*args): code.extend(args)
    def label(name): labels[name] = len(code)
    def beq(name):
        fixups.append((len(code)+1, name, len(code)+2, 'rel'))
        b(0xF0, 0x00)
    def bne(name):
        fixups.append((len(code)+1, name, len(code)+2, 'rel'))
        b(0xD0, 0x00)
    def jsr(name):
        fixups.append((len(code)+1, name, None, 'abs'))
        b(0x20, 0x00, 0x00)

    label('start')
    b(0x78); b(0xD8); b(0xA2, 0x00)

    # VIA2 init
    b(0xA9, 0x0C); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xA9, 0x0C); b(0x8D, VIA2_DDRB&0xFF, VIA2_DDRB>>8)
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)

    # Send 'R'
    b(0xA9, ord('R')); jsr('uart_tx')

    # Select bank
    b(0xA9, PCR_VAL); b(0x8D, VIA2_PCR&0xFF, VIA2_PCR>>8)
    b(0xA2, 0x00)

    # ptr=$8000, sect_cnt=8
    b(0xA9, 0x00); b(0x85, PTR_LO)
    b(0xA9, 0x80); b(0x85, PTR_HI)
    b(0xA9, 0x08); b(0x85, SECT_CNT)

    label('sector_loop')
    # Unlock: switch to bank 0 for correct $D555/$AAAA mapping
    b(0xA9, PCR_BANK0); b(0x8D, VIA2_PCR&0xFF, VIA2_PCR>>8)
    b(0xA9, 0xAA); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0x55); b(0x8D, UNLOCK2&0xFF, UNLOCK2>>8)
    b(0xA9, 0x80); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0xAA); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0x55); b(0x8D, UNLOCK2&0xFF, UNLOCK2>>8)
    # Switch to target bank for erase command
    b(0xA9, PCR_VAL); b(0x8D, VIA2_PCR&0xFF, VIA2_PCR>>8)
    b(0xA2, 0x00)                # restore X=0
    b(0xA9, 0x30); b(0x81, PTR_LO)

    label('erase_poll')
    b(0xA1, PTR_LO); b(0x29, 0x80); beq('erase_poll')

    b(0xA9, 0x00); b(0x85, BC_LO)
    b(0xA9, 0x10); b(0x85, BC_HI)

    label('byte_loop')
    jsr('uart_rx')
    b(0xA8)
    # Unlock: switch to bank 0 for correct $D555/$AAAA mapping
    b(0xA9, PCR_BANK0); b(0x8D, VIA2_PCR&0xFF, VIA2_PCR>>8)
    b(0xA9, 0xAA); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0x55); b(0x8D, UNLOCK2&0xFF, UNLOCK2>>8)
    b(0xA9, 0xA0); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    # Switch to target bank for byte program
    b(0xA9, PCR_VAL); b(0x8D, VIA2_PCR&0xFF, VIA2_PCR>>8)
    b(0xA2, 0x00)                # restore X=0
    b(0x98); b(0x81, PTR_LO)

    b(0xA9, 0x40)
    label('delay')
    b(0x3A); bne('delay')

    b(0xE6, PTR_LO); b(0xD0, 0x03); b(0xE6, PTR_HI); b(0xEA)

    b(0xA5, BC_LO); b(0x3A); b(0x85, BC_LO); bne('byte_loop')
    b(0xA5, BC_HI); b(0x3A); b(0x85, BC_HI); bne('byte_loop')
    b(0xC6, SECT_CNT); bne('sector_loop')

    b(0xA9, ord('D')); jsr('uart_tx')
    b(0x6C, 0xFC, 0xFF)

    # uart_tx/rx copied from build_flash_writer
    label('uart_tx')
    b(0x48)
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    b(0x68); b(0x48)
    b(0x8D, VIA2_ORA&0xFF, VIA2_ORA>>8)
    label('tx_wait')
    b(0xA9, 0x01); b(0x2C, VIA2_ORB&0xFF, VIA2_ORB>>8)
    bne('tx_wait')
    b(0xA9, 0xFF); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    b(0xA9, 0x04); b(0x0C, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xEA); b(0xEA)
    b(0xA9, 0x04); b(0x1C, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    b(0x68); b(0x60)

    label('uart_rx')
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    label('rx_wait')
    b(0xA9, 0x02); b(0x2C, VIA2_ORB&0xFF, VIA2_ORB>>8)
    bne('rx_wait')
    b(0xAD, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x29, 0xF7); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xEA); b(0xEA)
    b(0xAD, VIA2_ORA&0xFF, VIA2_ORA>>8)
    b(0x48)
    b(0xAD, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x09, 0x08); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x68); b(0x60)

    for off, name, rel_base, kind in fixups:
        target_abs = WRITER_BASE + labels[name]
        if kind == 'abs':
            code[off]   = target_abs & 0xFF
            code[off+1] = target_abs >> 8
        else:
            code[off] = (target_abs - (WRITER_BASE + rel_base)) & 0xFF

    return bytes(code)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(
        description='Bootstrap or reflash W65C02SXB')
    p.add_argument('port', help='Serial port')
    p.add_argument('image', help='SXB_eater.bin (131072 bytes)')
    p.add_argument('--bank', type=int, choices=[0,1,2,3],
                   help='Reflash single bank only (requires WDCMON in bank 0)')
    p.add_argument('--from-wozmon', action='store_true',
                   help='Send B0 to wozmon first to switch to WDCMON')
    args = p.parse_args()

    if args.bank is not None:
        if args.from_wozmon:
            print(f"Opening {args.port}...")
            s = open_port(args.port)
            print("Sending B0 to wozmon...")
            s.write(b'B0\r')
            s.flush()
            time.sleep(0.3)
            s.reset_input_buffer()
            reflash_bank(args.port, args.image, args.bank, s=s)
        else:
            reflash_bank(args.port, args.image, args.bank)
    else:
        bootstrap(args.port, args.image)
