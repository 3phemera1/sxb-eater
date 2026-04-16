#!/usr/bin/env python3
"""
build_rom.py - Build W65C02SXB flash image from assembled EhBASIC binary

Usage: python3 build_rom.py <eater.bin> <SXB_orig.bin> <output.bin>

Patches the assembled binary to work with the WDC SXB2 firmware boot sequence:
  1. Adds WDC\x00 signature at $8000
  2. Adds JMP to wozmon RESET at $8004
  3. Relocates WDC init stubs to free space at $F958+
  4. Sets RESET vector to point to relocated init stub
  5. Builds 128KB flash image with correct bank layout
"""
import sys
import subprocess

def find_label(lbl_file, label):
    with open(lbl_file) as f:
        for line in f:
            if f'.{label}' in line:
                parts = line.strip().split()
                return int(parts[1], 16)
    return None

def build(basic_bin, lbl_file, orig_bin, output_bin):
    with open(orig_bin, 'rb') as f:
        orig = f.read()
    with open(basic_bin, 'rb') as f:
        basic = bytearray(f.read())

    wdc_bank = bytearray(orig[0x18000:0x20000])

    # Find wozmon RESET address
    wozmon_reset = find_label(lbl_file, 'RESET')
    if wozmon_reset is None:
        raise RuntimeError("Could not find RESET label in label file")
    print(f"Wozmon RESET at ${wozmon_reset:04x}")

    # Free space starts at $F958 (after wozmon ends at $F954)
    FREE_BASE = 0xF958

    # Extract WDC routines from original firmware
    def wdc(start, end):
        return bytearray(orig[0x18000+(start-0x8000):0x18000+(end-0x8000)])

    wdc_init   = wdc(0xF818, 0xF8A5)  # 141 bytes - main init
    wdc_via2   = wdc(0xF9C2, 0xF9D0)  # 14 bytes  - VIA2 init
    wdc_rxpoll = wdc(0xFA10, 0xFA1A)  # 10 bytes  - RX poll
    wdc_usbchk = wdc(0xFB99, 0xFB9F)  # 6 bytes   - USB check
    wdc_sigchk = wdc(0xF9A9, 0xF9C2)  # 25 bytes  - WDC sig check

    # Calculate addresses
    addr_init   = FREE_BASE
    addr_via2   = addr_init   + len(wdc_init)
    addr_rxpoll = addr_via2   + len(wdc_via2)
    addr_usbchk = addr_rxpoll + len(wdc_rxpoll)
    addr_sigchk = addr_usbchk + len(wdc_usbchk)
    total = addr_sigchk + len(wdc_sigchk) - FREE_BASE

    print(f"Stub layout:")
    print(f"  ${addr_init:04x}: WDC init        ({len(wdc_init)} bytes)")
    print(f"  ${addr_via2:04x}: VIA2 init       ({len(wdc_via2)} bytes)")
    print(f"  ${addr_rxpoll:04x}: RX poll         ({len(wdc_rxpoll)} bytes)")
    print(f"  ${addr_usbchk:04x}: USB check       ({len(wdc_usbchk)} bytes)")
    print(f"  ${addr_sigchk:04x}: WDC sig check   ({len(wdc_sigchk)} bytes)")
    print(f"  Total: {total} bytes")

    # Patch wdc_init: fix JSR/JMP targets and NOP out JSR $E87F
    def patch_abs(code, old_tgt, new_tgt, op=0x20):
        for i in range(len(code)-2):
            if code[i] == op:
                tgt = code[i+1] | (code[i+2]<<8)
                if tgt == old_tgt:
                    code[i+1] = new_tgt & 0xFF
                    code[i+2] = (new_tgt >> 8) & 0xFF
                    return True
        return False

    # NOP out JSR $E87F
    for i in range(len(wdc_init)-2):
        if wdc_init[i] == 0x20:
            tgt = wdc_init[i+1] | (wdc_init[i+2]<<8)
            if tgt == 0xE87F:
                wdc_init[i] = wdc_init[i+1] = wdc_init[i+2] = 0xEA
                print(f"  NOP'd JSR $E87F at init+{i}")

    patch_abs(wdc_init, 0xF9C2, addr_via2)
    patch_abs(wdc_init, 0xFA10, addr_rxpoll)

    # Patch PHA/PHA/JMP $FB99 -> JMP addr_usbchk with corrected return addr
    ret_addr = addr_init + (0xF8A6 - 0xF818)
    for i in range(len(wdc_init)-8):
        if (wdc_init[i]==0xA9 and wdc_init[i+2]==0x48 and
            wdc_init[i+3]==0xA9 and wdc_init[i+5]==0x48 and
            wdc_init[i+6]==0x4C):
            tgt = wdc_init[i+7] | (wdc_init[i+8]<<8)
            if tgt == 0xFB99:
                wdc_init[i+1] = (ret_addr >> 8) & 0xFF
                wdc_init[i+4] = ret_addr & 0xFF
                wdc_init[i+7] = addr_usbchk & 0xFF
                wdc_init[i+8] = (addr_usbchk >> 8) & 0xFF
                print(f"  Patched PHA/PHA/JMP: ret=${ret_addr:04x} jmp=${addr_usbchk:04x}")

    # Patch usbchk: JSR $F9A9 -> JSR addr_sigchk
    patch_abs(wdc_usbchk, 0xF9A9, addr_sigchk)

    # Write stubs into basic bank
    def write_stub(bank, cpu_addr, data):
        off = cpu_addr - 0x8000
        bank[off:off+len(data)] = data

    write_stub(basic, addr_init,   wdc_init)
    write_stub(basic, addr_via2,   wdc_via2)
    write_stub(basic, addr_rxpoll, wdc_rxpoll)
    write_stub(basic, addr_usbchk, wdc_usbchk)
    write_stub(basic, addr_sigchk, wdc_sigchk)

    # WDC signature + JMP wozmon RESET at $8000
    basic[0] = 0x57; basic[1] = 0x44; basic[2] = 0x43; basic[3] = 0x00
    basic[4] = 0x4C
    basic[5] = wozmon_reset & 0xFF
    basic[6] = (wozmon_reset >> 8) & 0xFF

    # RESET vector -> our relocated init
    basic[0x7FFC] = addr_init & 0xFF
    basic[0x7FFD] = (addr_init >> 8) & 0xFF

    # Verify
    nmi   = basic[0x7FFA] | (basic[0x7FFB]<<8)
    reset = basic[0x7FFC] | (basic[0x7FFD]<<8)
    irq   = basic[0x7FFE] | (basic[0x7FFF]<<8)
    print(f"\nPatched vectors:")
    print(f"  NMI:   ${nmi:04x}")
    print(f"  RESET: ${reset:04x}  (WDC init -> wozmon -> BASIC)")
    print(f"  IRQ:   ${irq:04x}")
    print(f"  $8000: {bytes(basic[0:7]).hex()}")

    # Build 128KB flash image
    # Bank 0: WDC firmware (fallback, selected via bank switch)
    # Bank 1: empty
    # Bank 2: empty
    # Bank 3: EhBASIC + wozmon (DEFAULT BOOT - both LEDs off)
    flash = bytearray(131072)
    flash[0x00000:0x08000] = wdc_bank
    flash[0x08000:0x10000] = bytes([0xFF] * 32768)
    flash[0x10000:0x18000] = bytes([0xFF] * 32768)
    flash[0x18000:0x20000] = basic

    with open(output_bin, 'wb') as f:
        f.write(flash)

    print(f"\nWrote {len(flash)} bytes to {output_bin}")
    print(f"Flash layout:")
    print(f"  Bank 0 ($00000): EhBASIC + Wozmon (auto-boots via WDC sig)")
    print(f"  Bank 1 ($08000): empty")
    print(f"  Bank 2 ($10000): empty")
    print(f"  Bank 3 ($18000): WDC SXB2 firmware (NEVER OVERWRITE)")
    print(f"\nTo flash: minipro -p SST39SF010A -w {output_bin}")

if __name__ == '__main__':
    if len(sys.argv) != 5:
        print(f"Usage: {sys.argv[0]} <eater.bin> <eater.lbl> <SXB_orig.bin> <output.bin>")
        sys.exit(1)
    build(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
