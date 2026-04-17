# SXB EhBASIC + Wozmon

MS BASIC and Wozmon for the [WDC W65C02SXB](https://wdc65xx.com/single-board-computers/w65c02sxb/)
development board, adapted from the [Ben Eater 6502 breadboard project](https://eater.net/6502).

## Overview

This project runs Microsoft BASIC and Wozmon directly from the W65C02SXB's
onboard flash ROM. The factory WDC SXB2 firmware acts as a bootloader,
handling USB serial initialization before handing off to wozmon.

On power-up:
1. WDC SXB2 firmware runs → drives the LED diamond pattern
2. Initializes VIA2 for USB serial (FT245 parallel FIFO)
3. Waits for USB enumeration
4. Detects `WDC\x00` signature at `$8000` → hands off to our code
5. Wozmon starts — type `A089R` to launch MS BASIC

## Hardware

- [WDC W65C02SXB](https://wdc65xx.com/single-board-computers/w65c02sxb/) development board
- SST39SF010A 128KB flash (socketed on the board)
- USB cable (board connects via onboard FT245 USB chip)
- For initial flash: TL866/T48 or compatible EEPROM programmer (minipro)
  — **or** use the bootstrap script (no programmer needed, see below)

## Memory Map

```
$0000-$00FF  Zero page (MS BASIC + Wozmon variables)
$0100-$01FF  Hardware stack
$0200-$02FF  Wozmon input buffer / MS BASIC line buffer
$0300-$03FF  MS BASIC input buffer
$0400-$7FFF  MS BASIC program and variable RAM
$8000-$F7FF  MS BASIC ROM
$F800-$F816  BIOS jump table + SXB2 signature
$F818-$F854  WDC init sequence (copied from SXB2)
$F855-$F957  Wozmon
$F958-$FFF9  WDC init stubs (relocated to free space)
$FFFA-$FFFF  Interrupt vectors
```

## Flash Layout

The SST39SF010A is 128KB divided into four 32KB banks.
The WDC SXB2 firmware runs on reset from **bank 3** (hardware default).
It checks for a `WDC\x00` signature in **bank 0** and auto-boots there.

| Bank | File Offset | Contents |
|------|-------------|----------|
| 0    | `$00000`    | **EhBASIC + Wozmon (auto-boots here)** |
| 1    | `$08000`    | Empty — available for user code |
| 2    | `$10000`    | Empty — available for user code |
| 3    | `$18000`    | WDC SXB2 firmware — **NEVER OVERWRITE** |

## Requirements

### Build tools

- **cc65** assembler/linker suite: `brew install cc65`
- **Python 3**
- **pyserial** (for bootstrap script): `pip install pyserial`
- **minipro** (optional): `brew install minipro`

### Original WDC firmware dump

You need a dump of the original SST39SF010A from your board.
Pull the chip and read it with minipro:

```bash
minipro -p "SST39SF010A" -r SXB_orig.bin
```

Place `SXB_orig.bin` in the repo root. It is gitignored — it contains WDC
proprietary firmware that this project uses only as a bootloader.

## Building

```bash
git clone https://github.com/yourname/sxb-eater.git
cd sxb-eater
cp /path/to/SXB_orig.bin .
make
```

Produces `build/SXB_eater.bin` — the 128KB flash image.

## Flashing

### Option A: Bootstrap script (no chip programmer needed)

If your board is factory fresh (bank 0 empty), the SXB2 firmware enters
host handshake mode on boot. The bootstrap script exploits this to program
EhBASIC directly over USB without pulling the chip.

**Important:** The SXB2 firmware's CMD `$07` (WRITE_MEM) always writes to
RAM at `$0800` — it does NOT write to flash directly. The bootstrap script
works around this by uploading a self-contained flash programming stub
(params + 65C02 code + data) to RAM each page, then executing it. The stub
performs the SST39SF010A byte-program sequence directly.

```bash
# Do NOT open CoolTerm or any terminal first
python3 tools/bootstrap_flash.py /dev/cu.usbserial-XXXXXXXX build/SXB_eater.bin
```

After success, power cycle — board auto-boots to wozmon.

> **Note:** Once bank 0 has a `WDC\x00` signature the board auto-boots and
> will NOT enter host mode. Use Option B to reflash after that point.

### Option B: Chip programmer

```bash
make flash
# or:
minipro -p "SST39SF010A" -w build/SXB_eater.bin
```

## Usage

Connect at **115200 8N1, no flow control**. On boot you see the WDC LED
diamond sequence, then wozmon's `\` prompt.

### Wozmon commands

| Command | Description |
|---------|-------------|
| `XXXXR` | Run code at hex address XXXX |
| `XXXX`  | Examine memory at XXXX |
| `XXXX: YY ZZ ...` | Write bytes to memory |
| `XXXX.YYYY` | Examine memory range |

### Launching MS BASIC

```
A089R
```

Press Enter at both prompts (`MEMORY SIZE?` and `TERMINAL WIDTH?`).

To return to wozmon from BASIC, press the **NMI** button.

### Terminal settings

Enable **"Add LF after CR"** in your terminal for correct BASIC output
(CoolTerm: Receive → Add LF after CR).

## How It Works

The WDC SXB2 firmware checks for `WDC\x00` at `$8000` after USB init.
If found, it RTIs to `$8004`. We place `WDC\x00` at `$8000` and
`JMP $F855` (wozmon RESET) at `$8004`. The WDC init code is copied to
free space at `$F958` and the RESET vector points there, ensuring the
full WDC init (LEDs, VIA2, USB enumeration) runs on every reset.

`tools/build_rom.py` handles all patching automatically.

See `docs/wdc_reference/NOTES.md` for complete protocol documentation
including the full SXB2 reverse engineering findings.

## Known Issues / TODO

- [ ] `CHRIN` is polled — Ctrl+C during BASIC programs may not respond
- [ ] CR/LF: enable "Add LF after CR" in terminal for correct display
- [ ] Bootstrap script needs real-hardware testing
- [ ] S19/S28 record loader not yet in wozmon
- [ ] Register display not yet in wozmon
- [ ] Bank switch command not yet implemented

## Attribution

- **MS BASIC** — Microsoft, 1977
- **[msbasic](https://github.com/keesL/msbasic)** by Kees van Oss — cross-platform
  MS BASIC port for 6502 systems using ca65; the build system and source
  this project is directly based on
- **[Ben Eater](https://eater.net/6502)** — Ben Eater's 6502 breadboard computer
  series provided the foundation and inspiration; the `eater` target in
  msbasic originates from his project
- **[Wozmon](https://www.sbprojects.net/projects/apple1/wozmon.php)** — Steve
  Wozniak's original Apple 1 monitor
- **[wdc_uploader_term.py](tools/wdc_uploader_term.py)** — MIT licensed,
  by ECNX Developments; provided by WDC as reference implementation
- **WDC SXB2 firmware** and **WDCMON** — Western Design Center; used as
  bootloader only, not distributed. Dump your own chip with minipro.

## License

MS BASIC source is copyright Microsoft 1977. The ca65 port, wozmon, and
surrounding infrastructure are MIT licensed per their respective upstream
repositories. SXB-specific files (`bios/bios_sxb.s`, `tools/build_rom.py`,
`tools/bootstrap_flash.py`, `cfg/sxb.cfg`, `Makefile`) are MIT licensed.

## Flashing Your Own Code

The bootstrap script and build pipeline are not limited to EhBASIC. Any
32KB binary image can be flashed to bank 0. The only requirement is that
it begins with the `WDC\x00` signature and a `JMP <entry>` at `$8004` so
the SXB2 bootloader can hand off to it after USB initialization.

```bash
# Flash any 32KB bank 0 image
python3 tools/bootstrap_flash.py <port> your_image.bin

# Or with minipro (builds a full 128KB image preserving bank 3):
python3 tools/build_rom.py your_code.bin your_code.lbl SXB_orig.bin your_flash.bin
minipro -p "SST39SF010A" -w your_flash.bin
```

`build_rom.py` expects a label file for the `RESET` symbol. If your code
doesn't use ca65/ld65, you can patch the `WDC\x00` signature, `JMP`, and
RESET vector manually — see `docs/wdc_reference/NOTES.md` for the exact
layout required.
