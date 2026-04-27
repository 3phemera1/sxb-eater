#!/usr/bin/env python3
"""
build_rom.py - Build W65C02SXB flash image from assembled EhBASIC binary

Usage:
  # Normal (requires SXB_orig.bin chip dump):
  python3 build_rom.py <eater.bin> <eater.lbl> <SXB_orig.bin> <output.bin>

  # No programmer needed (skips WDC init stubs):
  python3 build_rom.py <eater.bin> <eater.lbl> --no-orig <output.bin>

With --no-orig:
  - No SXB_orig.bin required
  - WDC init stubs are omitted (no LED diamond sequence)
  - RESET vector points directly to wozmon
  - Board boots directly to wozmon prompt
  - USB serial works via our own INIT_BUFFER in bios_sxb.s
  - Bank 0 is empty ($FF)
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

def build_no_orig(basic_bin, lbl_file, output_bin, wdcmon_s28=None, monitor_bin=None):
    """
    Build flash image without SXB_orig.bin.
    Skips WDC init stubs - RESET vector points directly to wozmon RESET.
    No LED diamond sequence on boot. USB serial still works via INIT_BUFFER.
    """
    with open(basic_bin, 'rb') as f:
        basic = bytearray(f.read())

    wozmon_reset = find_label(lbl_file, 'RESET')
    if wozmon_reset is None:
        raise RuntimeError("Could not find RESET label in label file")
    print(f"Wozmon RESET at ${wozmon_reset:04x}")

    # WDC signature + JMP wozmon RESET at $8000
    basic[0] = 0x57; basic[1] = 0x44; basic[2] = 0x43; basic[3] = 0x00
    basic[4] = 0x4C
    basic[5] = wozmon_reset & 0xFF
    basic[6] = (wozmon_reset >> 8) & 0xFF

    # RESET vector -> wozmon RESET directly (no WDC init stubs)
    basic[0x7FFC] = wozmon_reset & 0xFF
    basic[0x7FFD] = (wozmon_reset >> 8) & 0xFF

    nmi   = basic[0x7FFA] | (basic[0x7FFB]<<8)
    reset = basic[0x7FFC] | (basic[0x7FFD]<<8)
    irq   = basic[0x7FFE] | (basic[0x7FFF]<<8)
    print(f"\nPatched vectors (no-orig mode):")
    print(f"  NMI:   ${nmi:04x}")
    print(f"  RESET: ${reset:04x}  (direct to wozmon - no LED diamond)")
    print(f"  IRQ:   ${irq:04x}")
    print(f"  $8000: {bytes(basic[0:7]).hex()}")

    flash = bytearray(131072)
    if wdcmon_s28:
        flash[0x00000:0x08000] = load_s28(wdcmon_s28)
        print(f"  Bank 0: WDCMON from {wdcmon_s28}")
    else:
        flash[0x00000:0x08000] = bytes([0xFF] * 32768)
        print(f"  Bank 0: empty ($FF)")
    if monitor_bin:
        with open(monitor_bin, 'rb') as f:
            mon = f.read()
        flash[0x08000:0x10000] = mon
        print(f"  Bank 1: C monitor from {monitor_bin}")
    else:
        flash[0x08000:0x10000] = bytes([0xFF] * 32768)
        print(f"  Bank 1: empty ($FF)")
    flash[0x10000:0x18000] = bytes([0xFF] * 32768)
    flash[0x18000:0x20000] = basic

    with open(output_bin, 'wb') as f:
        f.write(flash)

    print(f"\nWrote {len(flash)} bytes to {output_bin}")
    print(f"Flash layout (no-orig mode):")
    print(f"  Bank 0 ($00000): {'WDCMON' if wdcmon_s28 else 'empty'}")
    print(f"  Bank 1 ($08000): {'C monitor' if monitor_bin else 'empty'}")
    print(f"  Bank 2 ($10000): empty")
    print(f"  Bank 3 ($18000): EhBASIC + Wozmon (direct boot, no LED diamond)")
    print(f"\nNote: --no-orig skips WDC init stubs.")
    print(f"  No LED diamond on boot. Wozmon starts immediately after reset.")
    print(f"\nTo flash: python3 tools/bootstrap_flash.py <port> {output_bin}")


def build(basic_bin, lbl_file, orig_bin, output_bin, wdcmon_s28=None, monitor_bin=None):
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

    # Free space starts after wozmon code ends.
    do_switch = find_label(lbl_file, 'DO_SWITCH')
    if do_switch is None:
        raise RuntimeError("Could not find DO_SWITCH label - is wozmon built?")
    FREE_BASE = do_switch + 6
    if FREE_BASE + 200 > 0xFFFA:
        raise RuntimeError(f"No room for stubs: FREE_BASE=${FREE_BASE:04x}, need 200 bytes before $FFFA")
    print(f"Wozmon DO_SWITCH at ${do_switch:04x}, FREE_BASE=${FREE_BASE:04x}")

    def wdc(start, end):
        return bytearray(orig[0x18000+(start-0x8000):0x18000+(end-0x8000)])

    wdc_init   = wdc(0xF818, 0xF8A5)
    wdc_via2   = wdc(0xF9C2, 0xF9D0)
    wdc_rxpoll = wdc(0xFA10, 0xFA1A)
    wdc_usbchk = wdc(0xFB99, 0xFBA9)
    wdc_sigchk = wdc(0xF9A9, 0xF9C2)

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

    def patch_abs(code, old_tgt, new_tgt, op=0x20):
        for i in range(len(code)-2):
            if code[i] == op:
                tgt = code[i+1] | (code[i+2]<<8)
                if tgt == old_tgt:
                    code[i+1] = new_tgt & 0xFF
                    code[i+2] = (new_tgt >> 8) & 0xFF
                    return True
        return False

    i = 0
    while i < len(wdc_init)-2:
        op = wdc_init[i]
        if op == 0x20:
            tgt = wdc_init[i+1] | (wdc_init[i+2]<<8)
            if tgt == 0xE87F:
                wdc_init[i] = wdc_init[i+1] = wdc_init[i+2] = 0xEA
                print(f"  NOP'd JSR $E87F at init+{i}")
            i += 3
        elif op in (0x4C, 0x6C, 0x7C):
            i += 3
        elif op in (0x00, 0x08, 0x18, 0x1A, 0x28, 0x38, 0x3A, 0x40, 0x48,
                    0x58, 0x5A, 0x60, 0x68, 0x78, 0x7A, 0x88, 0x8A, 0x98,
                    0x9A, 0xA8, 0xAA, 0xB8, 0xBA, 0xC8, 0xCA, 0xD8, 0xDA,
                    0xEA, 0xF8, 0xFA):
            i += 1
        elif op in (0x10, 0x20, 0x30, 0x50, 0x70, 0x90, 0xB0, 0xD0, 0xF0,
                    0x24, 0x25, 0x26, 0x27, 0x34, 0x35, 0x36, 0x37,
                    0x44, 0x45, 0x46, 0x47, 0x54, 0x55, 0x56, 0x57,
                    0x64, 0x65, 0x66, 0x67, 0x74, 0x75, 0x76, 0x77,
                    0x84, 0x85, 0x86, 0x87, 0x94, 0x95, 0x96, 0x97,
                    0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7,
                    0xB1, 0xB2, 0xB4, 0xB5, 0xB6, 0xB7,
                    0xC0, 0xC1, 0xC4, 0xC5, 0xC6, 0xC7,
                    0xD1, 0xD2, 0xD4, 0xD5, 0xD6, 0xD7,
                    0xE0, 0xE1, 0xE4, 0xE5, 0xE6, 0xE7,
                    0xF1, 0xF2, 0xF4, 0xF5, 0xF6, 0xF7):
            i += 2
        else:
            i += 3

    patch_abs(wdc_init, 0xF9C2, addr_via2)
    patch_abs(wdc_init, 0xFA10, addr_rxpoll)

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

    patch_abs(wdc_usbchk, 0xF9A9, addr_sigchk)

    bank3_select = bytearray([
        0xA9, 0xEE,
        0x8D, 0xEC, 0x7F,
    ])
    wdc_sigchk = bank3_select + wdc_sigchk[:-5]
    print(f"  Sigchk patched to select bank 3 before sig read")

    def write_stub(bank, cpu_addr, data):
        off = cpu_addr - 0x8000
        bank[off:off+len(data)] = data

    write_stub(basic, addr_init,   wdc_init)
    write_stub(basic, addr_via2,   wdc_via2)
    write_stub(basic, addr_rxpoll, wdc_rxpoll)
    write_stub(basic, addr_usbchk, wdc_usbchk)
    write_stub(basic, addr_sigchk, wdc_sigchk)

    basic[0] = 0x57; basic[1] = 0x44; basic[2] = 0x43; basic[3] = 0x00
    basic[4] = 0x4C
    basic[5] = wozmon_reset & 0xFF
    basic[6] = (wozmon_reset >> 8) & 0xFF

    basic[0x7FFC] = addr_init & 0xFF
    basic[0x7FFD] = (addr_init >> 8) & 0xFF

    nmi   = basic[0x7FFA] | (basic[0x7FFB]<<8)
    reset = basic[0x7FFC] | (basic[0x7FFD]<<8)
    irq   = basic[0x7FFE] | (basic[0x7FFF]<<8)
    print(f"\nPatched vectors:")
    print(f"  NMI:   ${nmi:04x}")
    print(f"  RESET: ${reset:04x}  (WDC init -> wozmon -> BASIC)")
    print(f"  IRQ:   ${irq:04x}")
    print(f"  $8000: {bytes(basic[0:7]).hex()}")

    flash = bytearray(131072)
    # Bank 0 = SXB2 firmware (full, from SXB_orig.bin bank 3)
    # Overlay WDCMON s28 patch on top if present
    flash[0x00000:0x08000] = wdc_bank
    if wdcmon_s28:
        s28_data = load_s28(wdcmon_s28)
        for i, b in enumerate(s28_data):
            if b != 0xFF:
                flash[i] = b
        print(f"  Bank 0: SXB2 + WDCMON overlay from {wdcmon_s28}")
    else:
        print(f"  Bank 0: SXB2 firmware (from SXB_orig.bin)")
    # Wipe WDC signature from bank 0 so SXB2 always enters host mode
    # (used as permanent recovery via NMI button)
    flash[0] = 0xFF; flash[1] = 0xFF; flash[2] = 0xFF; flash[3] = 0xFF
    print(f"  Bank 0: WDC sig wiped -> SXB2 always in host mode (NMI recovery)")
    if monitor_bin:
        with open(monitor_bin, 'rb') as f:
            mon = f.read()
        flash[0x08000:0x10000] = mon
        print(f"  Bank 1: C monitor from {monitor_bin}")
    else:
        flash[0x08000:0x10000] = bytes([0xFF] * 32768)
        print(f"  Bank 1: empty ($FF)")
    flash[0x10000:0x18000] = bytes([0xFF] * 32768)
    flash[0x18000:0x20000] = basic

    with open(output_bin, 'wb') as f:
        f.write(flash)

    print(f"\nWrote {len(flash)} bytes to {output_bin}")
    print(f"Flash layout:")
    print(f"  Bank 0 ($00000): {'WDCMON' if wdcmon_s28 else 'WDC SXB2 fallback'}")
    print(f"  Bank 1 ($08000): {'C monitor' if monitor_bin else 'empty'}")
    print(f"  Bank 2 ($10000): empty")
    print(f"  Bank 3 ($18000): EhBASIC + Wozmon (auto-boot)")
    print(f"\nTo flash: python3 tools/bootstrap_flash.py <port> {output_bin}")


def load_s28(path):
    image = bytearray([0xFF] * 32768)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('S2'):
                cnt  = int(line[2:4], 16)
                addr = int(line[4:10], 16)
                data = bytes.fromhex(line[10:10+(cnt-4)*2])
                if addr >= 0x8000:
                    off = addr - 0x8000
                    image[off:off+len(data)] = data
    return bytes(image)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(
        description='Build W65C02SXB flash image from assembled EhBASIC binary')
    p.add_argument('basic_bin')
    p.add_argument('lbl_file')
    p.add_argument('orig_bin', nargs='?',
                   help='SXB_orig.bin chip dump (omit with --no-orig)')
    p.add_argument('output_bin')
    p.add_argument('--wdcmon', help='W65C02SXB.s28 for bank 0')
    p.add_argument('--monitor', help='32 KB monitor.bin to embed in bank 1')
    p.add_argument('--no-orig', action='store_true',
                   help='Skip WDC init stubs (no SXB_orig.bin needed). '
                        'Board boots directly to wozmon, no LED diamond.')
    args = p.parse_args()

    if args.no_orig:
        if args.orig_bin and args.orig_bin != args.output_bin:
            pass
        build_no_orig(args.basic_bin, args.lbl_file, args.output_bin,
                      wdcmon_s28=args.wdcmon, monitor_bin=args.monitor)
    else:
        if args.orig_bin is None:
            p.error("orig_bin is required unless --no-orig is specified")
        build(args.basic_bin, args.lbl_file, args.orig_bin, args.output_bin,
              wdcmon_s28=args.wdcmon, monitor_bin=args.monitor)
