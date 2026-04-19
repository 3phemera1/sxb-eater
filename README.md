# SXB EhBASIC + Wozmon

MS BASIC and Wozmon for the [WDC W65C02SXB](https://wdc65xx.com/single-board-computers/w65c02sxb/)
development board, adapted from the [Ben Eater 6502 breadboard project](https://eater.net/6502).

## Overview

This project runs Microsoft BASIC and Wozmon directly from the W65C02SXB's
onboard flash ROM. The WDC SXB2 firmware (factory installed in bank 3) acts
as a bootloader, handling USB serial initialization before handing off to
our code — also in bank 3.

On power-up:
1. WDC SXB2 firmware wakes, drives the LED diamond pattern
2. Initializes VIA2 for USB serial (FT245 parallel FIFO)
3. Detects `WDC\x00` signature at `$8000` in bank 3 → hands off
4. Wozmon starts — type `A0A0R` to launch MS BASIC

## Hardware

- [WDC W65C02SXB](https://wdc65xx.com/single-board-computers/w65c02sxb/) development board
- SST39SF010A 128KB flash (socketed)
- USB cable (FT245 USB-parallel FIFO on board)
- No chip programmer needed for initial flash (see bootstrap script below)

## Flash Layout

The SST39SF010A is 128KB divided into four 32KB banks, selected via
VIA2 PCR (`$7FEC`). Bank 3 is the hardware default on reset.

| Bank | PCR  | File Offset | Contents |
|------|------|-------------|----------|
| 0    | `$CC` | `$00000`   | WDCMON (WDC's new monitor, optional) |
| 1    | `$CE` | `$08000`   | Empty — user code |
| 2    | `$EC` | `$10000`   | Empty — user code |
| 3    | `$EE` | `$18000`   | **EhBASIC + Wozmon (default boot)** |

Bank 3 is the boot bank (hardware default). Our code replaces the WDC SXB2
firmware in bank 3. The WDC init stubs are preserved and relocated within
bank 3 to free space after wozmon.

## Memory Map (bank 3)

```
$0000-$00FF  Zero page (MS BASIC + Wozmon variables)
$0100-$01FF  Hardware stack
$0200-$02FF  Wozmon input buffer
$0300-$03FF  MS BASIC input buffer
$0400-$7FFF  MS BASIC program RAM
$8000-$8006  WDC\x00 signature + JMP wozmon RESET
$8007-$F7FF  MS BASIC ROM
$F800-$F854  BIOS (VIA2 serial + CHRIN/CHROUT)
$F855-$F98F  Wozmon (including bank-switch B command)
$F996-$FAxx  WDC init stubs (relocated from SXB2)
$FFFA-$FFFF  Interrupt vectors (RESET=$F996)
```

## Requirements

### Build tools

- **cc65**: `brew install cc65`
- **Python 3** + **pyserial**: `pip install pyserial`
- **minipro** (optional, for chip programmer): `brew install minipro`

### Original firmware dump

A dump of the original SST39SF010A chip is required as `SXB_orig.bin`
in the repo root. The bootstrap script reads WDC init stubs from it.

```bash
minipro -p "SST39SF010A" -r SXB_orig.bin
```

`SXB_orig.bin` is gitignored — it contains WDC proprietary firmware.

## Building

```bash
git clone https://github.com/3phemera1/sxb-eater.git
cd sxb-eater
cp /path/to/SXB_orig.bin .

# Optional: place W65C02SXB.s28 (from WDC) for WDCMON in bank 0
cp /path/to/W65C02SXB.s28 docs/wdc_reference/

make
```

Produces `build/SXB_eater.bin` — the 128KB flash image.

## Flashing

### Initial flash (factory board — no programmer needed)

The bootstrap script programs all 4 banks over USB. It uploads a
self-contained 65C02 flash writer to RAM via the SXB2 host protocol,
executes it, and streams the full 128KB image.

```bash
# Board must be factory fresh (bank 0 empty = SXB2 enters host mode)
# Close any terminal program first
python3 tools/bootstrap_flash.py /dev/cu.usbserial-XXXXXXXX build/SXB_eater.bin
```

Takes ~15 seconds. Board resets to wozmon when done.

### Development iteration (wozmon already running)

After initial flash, use `reflash_bank3.py` to update bank 3 without
touching bank 0 (WDCMON). Talks directly to wozmon over serial — no
handshake protocol, no programmer.

```bash
make                  # rebuild
# Board must be at wozmon prompt (press reset if in BASIC)
python3 tools/reflash_bank3.py /dev/cu.usbserial-XXXXXXXX build/SXB_eater.bin
```

Takes ~8 seconds. Board resets to wozmon when done.

### Chip programmer

```bash
minipro -p "SST39SF010A" -w build/SXB_eater.bin
```

## Usage

Connect at **115200 8N1, no flow control**. After power cycle or reset,
wozmon starts (no visible prompt — see note below).

### Wozmon commands

| Command | Description |
|---------|-------------|
| `XXXXR` | Run code at hex address XXXX |
| `XXXX`  | Examine memory at XXXX |
| `XXXX: YY ZZ ...` | Write bytes to memory |
| `XXXX.YYYY` | Examine memory range |
| `B0` | Switch to bank 0 (WDCMON) |
| `B1` | Switch to bank 1 (user ROM) |
| `B2` | Switch to bank 2 (user ROM) |
| `B3` | Reload wozmon (bank 3) |

### Launching MS BASIC

```
A0A0R
```

Press Enter at both prompts (`MEMORY SIZE?` and `TERMINAL WIDTH?`).
Press the **reset button** to return to wozmon from BASIC.

### Terminal settings

Enable **"Add LF after CR"** in your terminal for correct BASIC output.
(CoolTerm: Receive → Add LF after CR)

> **Note on wozmon prompt:** The `\` prompt is sent on startup but may not
> appear in your terminal due to FT245 USB FIFO buffering — the byte is
> transmitted but held until the host sends data. Just start typing; wozmon
> is ready. The prompt will appear after your first keypress.

## How It Works

The WDC SXB2 firmware in bank 3 checks for `WDC\x00` at `$8000` (in bank 3)
after USB init. If found, it RTIs to `$8004`. We place `WDC\x00` at `$8000`
and `JMP wozmon_RESET` at `$8004`.

The WDC init stubs are extracted from `SXB_orig.bin`, patched, and relocated
to free space after wozmon in bank 3. The RESET vector points to the relocated
init stub so the full WDC sequence (LEDs, VIA2, USB) runs on every reset.
The sigchk stub selects bank 3 (PCR=`$EE`) before reading `$8000`, since
VIA2 PCR is cleared to 0 on hardware reset.

`tools/build_rom.py` handles all patching automatically.

`tools/bootstrap_flash.py` documents the complete SXB2 host protocol
(reverse engineered), including the `$55/$AA` → `$CC` handshake, CMD `$07`
WRITE_MEM, and CMD `$06` EXEC.

## Flash Your Own Code

Any 32KB binary can replace EhBASIC in bank 3. It must start with
`WDC\x00` at `$8000` and `JMP <entry>` at `$8004`.

```bash
# Reflash bank 3 only (wozmon must be running)
python3 tools/reflash_bank3.py <port> your_32k_image.bin

# Or reflash all banks (factory/clean state required)
python3 tools/bootstrap_flash.py <port> your_128k_image.bin
```

Banks 1 and 2 are empty and available for user code, accessible via
wozmon's `B1`/`B2` bank switch commands.

## Known Issues / TODO

- [ ] `\` prompt not visible on connect (FT245 buffering — type to flush)
- [ ] CR/LF: enable "Add LF after CR" in terminal
- [ ] S19/S28 record loader not yet in wozmon
- [ ] Register display not yet in wozmon
- [ ] `--from-wozmon` / WDCMON reflash path not yet working

## Attribution

- **MS BASIC** — Microsoft, 1977
- **[msbasic](https://github.com/keesL/msbasic)** by Kees van Oss
- **[Ben Eater](https://eater.net/6502)** — 6502 breadboard project
- **[Wozmon](https://www.sbprojects.net/projects/apple1/wozmon.php)** — Steve Wozniak
- **WDC SXB2 firmware / WDCMON** — Western Design Center (bootloader only, not distributed)

## License

MS BASIC is copyright Microsoft 1977. The ca65 port, wozmon, and surrounding
infrastructure are MIT licensed per their upstream repositories. SXB-specific
files (`bios/`, `tools/`, `cfg/sxb.cfg`, `Makefile`) are MIT licensed.
