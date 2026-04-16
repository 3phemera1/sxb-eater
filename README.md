# SXB EhBASIC + Wozmon

MS BASIC and Wozmon for the [WDC W65C02SXB](https://wdc65xx.com/single-board-computers/w65c02sxb/) development board, adapted from the [Ben Eater 6502 breadboard project](https://eater.net/6502).

## Overview

This project runs Microsoft BASIC and Wozmon directly from the W65C02SXB's onboard flash ROM, using the factory WDC SXB2 firmware as a bootloader to handle USB serial initialization. No host computer is required after flashing — just plug in and go.

On power-up:
1. WDC SXB2 firmware runs → drives the LED diamond pattern
2. Initializes VIA2 for USB serial (FT245 parallel FIFO)
3. Waits for USB enumeration
4. Detects the `WDC\x00` signature at `$8000` → hands off to our code
5. Wozmon starts — type `A089R` to launch MS BASIC

## Hardware

- [WDC W65C02SXB](https://wdc65xx.com/single-board-computers/w65c02sxb/) development board
- SST39SF010A 128KB flash (socketed on the board)
- TL866/T48 or compatible EEPROM programmer (e.g. minipro)
- USB cable (board connects via onboard FT245 USB chip)

## Memory Map

```
$0000-$00FF  Zero page (MS BASIC + Wozmon variables)
$0100-$01FF  Hardware stack
$0200-$02FF  Wozmon input buffer / MS BASIC line buffer
$0300-$03FF  MS BASIC input buffer
$0400-$7FFF  MS BASIC program and variable RAM
$8000-$F7FF  MS BASIC ROM
$F800-$F816  BIOS stub jump table + SXB2 signature
$F818-$F854  WDC init sequence (VIA1/VIA2/USB)
$F855-$F957  Wozmon
$F958-$FFE9  WDC init stubs (relocated)
$FFFA-$FFFF  Interrupt vectors
```

## Flash Layout

The SST39SF010A is 128KB divided into four 32KB banks. The WDC SXB2
firmware selects bank 3 on reset (both FAMS/FA15 LEDs off = default).

| Bank | File Offset | Contents |
|------|-------------|----------|
| 0    | `$00000`    | Original WDC SXB2 firmware (fallback) |
| 1    | `$08000`    | Empty (`$FF`) |
| 2    | `$10000`    | Empty (`$FF`) |
| 3    | `$18000`    | **EhBASIC + Wozmon (default boot)** |

## Requirements

### Build tools

- **cc65** assembler/linker suite
  ```bash
  brew install cc65
  ```
- **Python 3** (for `build_rom.py` ROM patcher)
- **minipro** for flashing
  ```bash
  brew install minipro
  # or: https://gitlab.com/DavidGriffith/minipro
  ```

### Original WDC firmware dump

You need a dump of the original SST39SF010A from your SXB board. Pull the chip and read it with minipro:

```bash
minipro -p "SST39SF010A" -r SXB_orig.bin
```

Place `SXB_orig.bin` in the root of this repo. It is gitignored and never committed — it contains WDC proprietary firmware.

## Building

```bash
git clone https://github.com/yourname/sxb-eater.git
cd sxb-eater

# Place your firmware dump here (see above)
cp /path/to/SXB_orig.bin .

make
```

This produces `build/SXB_eater.bin` — the 128KB flash image ready to program.

## Flashing

Pull the SST39SF010A from the SXB socket and program it:

```bash
make flash
# or manually:
minipro -p "SST39SF010A" -w build/SXB_eater.bin
```

Reseat the chip and connect via USB at **115200 8N1, no flow control**.

## Usage

On boot you will see the WDC LED diamond sequence, then the wozmon prompt:

```
\
```

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

You will see:
```
WRITTEN BY WEILAND & GATES
MEMORY SIZE?
TERMINAL WIDTH?

OK
```

Press Enter for both prompts to accept defaults.

### MS BASIC quick reference

```basic
PRINT "HELLO, WORLD!"
10 FOR I=1 TO 10
20 PRINT I
30 NEXT I
RUN
LIST
NEW
```

To return to wozmon from BASIC, press the **NMI** button on the board.

## How It Works

The WDC SXB2 firmware that ships on the board checks for a `WDC\x00`
signature at `$8000` after completing its USB initialization sequence.
If found, it executes an RTI to `$8004`.

This project places `WDC\x00` at `$8000` followed by a `JMP` to wozmon's
RESET entry point at `$8004`. The WDC init code (VIA1/VIA2 setup, USB
enumeration wait) is copied to free space at `$F958` and the RESET vector
is pointed there, so the full WDC init sequence runs on every reset before
handing off to wozmon.

The `tools/build_rom.py` script handles all of this patching automatically
as part of the build.

## Known Issues / TODO

- [ ] `CHRIN` is polled, not interrupt-driven — Ctrl+C during running BASIC
      programs may not respond immediately
- [ ] CR/LF: some terminals need "add LF after CR" enabled for correct display
- [ ] S19 record loading not yet implemented in wozmon (planned)
- [ ] Register display command for wozmon (planned)

## Attribution

- **MS BASIC** — Microsoft, 1977
- **[msbasic](https://github.com/keesL/msbasic)** by Kees van Oss — cross-platform
  MS BASIC port for 6502 systems, providing the ca65 source and multi-target
  build system this project is based on
- **[Ben Eater](https://eater.net/6502)** — Ben Eater's 6502 breadboard computer
  series and associated [eater variant](https://github.com/dbuchwald/6502) of
  msbasic provided the foundation and inspiration for this project
- **[Wozmon](https://www.sbprojects.net/projects/apple1/wozmon.php)** — Steve Wozniak's
  original Apple 1 monitor, included in the msbasic eater variant
- **WDC SXB2 firmware** — Western Design Center; used as a bootloader only,
  not distributed. Dump your own chip with minipro.

## License

MS BASIC source is copyright Microsoft 1977. The ca65 port, wozmon, and
surrounding infrastructure are MIT licensed per their respective upstream
repositories. SXB-specific files (`bios/bios_sxb.s`, `tools/build_rom.py`,
`cfg/sxb.cfg`, `Makefile`) are released under MIT license.
