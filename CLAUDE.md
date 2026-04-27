# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a retro computing project for the **WDC W65C02SXB single-board computer** (8-bit 6502 CPU). It combines Microsoft BASIC (1977) with Wozmon (Steve Wozniak's monitor) into a single ROM image that runs from onboard 128KB flash (SST39SF010A).

## Build

**Prerequisites**: cc65 suite (ca65, ld65, cc65 compiler), Python 3, GNU Make

```bash
make                  # produces build/SXB_eater.bin with bank 1 C monitor
make NO_MONITOR=1     # omit bank 1 C monitor (bank 1 left as $FF)
```

The build pipeline is three-stage:
1. `make` assembles bank 3 (EhBASIC + wozmon + bios) with ca65 → ld65
2. `make` compiles + assembles the bank 1 C monitor with cc65 → ca65 → ld65
3. `tools/build_rom.py` patches the result: extracts WDC firmware stubs from `SXB_orig.bin` (optional factory dump), writes `WDC\x00` signature at each bank's $8000, and assembles the final 4-bank image

If `SXB_orig.bin` is absent, build proceeds with `--no-orig` (boots without WDC LED diamond sequence).

## Flashing

```bash
# Initial flash (factory-fresh board, exploits SXB2 host mode — no programmer needed)
python3 tools/bootstrap_flash.py /dev/cu.usbserial-XXXXX build/SXB_eater.bin

# Development iteration (board already running this firmware)
python3 tools/reflash_bank3.py /dev/cu.usbserial-XXXXX build/SXB_eater.bin

# Emergency recovery (press NMI button first if bank 3 is broken, then run bootstrap)
python3 tools/bootstrap_flash.py /dev/cu.usbserial-XXXXX build/SXB_eater.bin
```

Connect at **115200 8N1** for serial interaction with Wozmon/BASIC.

## Architecture

### Flash Layout (128KB, 4 × 32KB banks)

| Bank | Address Range | Contents |
|------|---------------|----------|
| 0 | $00000–$07FFF | SXB2 firmware recovery (WDC sig wiped — triggers NMI reflash mode) |
| 1 | $08000–$0FFFF | Empty (user code) |
| 2 | $10000–$17FFF | Empty (user code) |
| 3 | $18000–$1FFFF | EhBASIC + Wozmon — **default boot bank** |

### Memory Map (Bank 3, at runtime)

```
$0000–$01FF  Zero page (BASIC/Wozmon vars) + hardware stack
$0200–$02FF  Wozmon input buffer      (STACK2 = $0200)
$0300–$03FF  MS BASIC input buffer
$0400–$7FFF  MS BASIC program RAM
$7FC0–$7FCF  VIA U3 (sound/GPIO)
$7FE0–$7FEF  VIA2 U5 (USB serial + bank select via PCR at $7FEC)
$8000–$8006  WDC\x00 signature + JMP wozmon_RESET
$8007–$F7FF  MS BASIC ROM
$F800–$F854  BIOS (VIA2 serial CHRIN/CHROUT)
$F855–$F98F  Wozmon (+ Bn bank-switch command)
$F996–$FAxx  WDC init stubs (relocated from factory firmware)
$FFFA–$FFFF  Vectors: RESET=$F996, NMI=NMI_HANDLER, IRQ=IRQ_HANDLER
```

### Boot Chain

Hardware reset → WDC SXB2 firmware in bank 3 → checks for `WDC\x00` at $8000 → RTI to $8004 (JMP wozmon_RESET) → WDC init stubs run (LED sequence, VIA2 init, USB enumeration) → Wozmon prompt.

### Key Source Components

- **`basic/msbasic.s`** — master include for all MS BASIC modules (~68 `.s` files). The `basic/defines_eater.s` file holds SXB-specific constants (stack size, RAM layout).
- **`bios/bios_sxb.s`** — VIA2 USB FIFO driver (CHRIN/CHROUT, no ACIA); also holds the NMI handler that bootstraps an emergency flash writer into RAM.
- **`wozmon/wozmon.s`** — Wozmon monitor with added `Bn` bank-switch commands (writes to VIA2_PCR $7FEC to drive flash address lines A15/A16).
- **`cfg/sxb.cfg`** — ld65 linker config defining all memory segments and their addresses.
- **`tools/build_rom.py`** — Python script that patches WDC stubs into the final binary; must be understood before changing the flash layout.
- **`tools/bootstrap_flash.py`** — exploits the SXB2 host-mode protocol to flash without an external programmer.

### Bank Switching

Wozmon `B0`–`B3` commands write to VIA2 PCR ($7FEC). The PCR outputs drive flash chip address lines A15/A16, selecting which 32KB bank is visible at $8000–$FFFF. Each bank needs a valid `WDC\x00` signature at its $8000 to be treated as a boot target.

### Serial I/O

All serial communication uses the FT245 USB parallel FIFO (not a traditional UART). The BIOS polls the VIA2 status register — there are no serial interrupts. This means Ctrl+C is unresponsive during long-running BASIC programs.

### NMI Recovery

If bank 3 is corrupted, pressing the NMI button triggers `NMI_HANDLER` in bank 0. This loads a ~255-byte flash writer stub into RAM and uses it to accept a fresh 128KB image over serial, allowing full recovery without a programmer.
