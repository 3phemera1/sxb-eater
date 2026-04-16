# SXB EhBASIC + Wozmon

MS BASIC and Wozmon for the WDC W65C02SXB development board.

Based on the [Ben Eater 6502 MS BASIC](https://github.com/dbuchwald/6502) project,
adapted for the W65C02SXB's FT245-based USB serial interface.

## Boot Sequence

The SXB ships with a "SXB2" firmware in flash bank 3 (the default boot bank).
Rather than replacing it, this project uses it as a bootloader:

1. SXB2 firmware runs on reset → drives the LED diamond pattern
2. Initializes VIA2 for USB serial
3. Waits for FT245 USB enumeration
4. Finds `WDC\x00` signature at `$8000` → RTIs to `$8004`
5. `$8004` jumps to wozmon RESET at `$F855`
6. Wozmon starts — type `A089R` to launch MS BASIC cold start

## Memory Map

```
$0000-$00FF  Zero page
$0100-$01FF  Stack
$0200-$02FF  Wozmon input buffer
$0300-$03FF  MS BASIC input buffer
$0400-$7FFF  MS BASIC RAM
$8000-$F7FF  MS BASIC ROM
$F800-$F954  Wozmon + BIOS
$F955-$FFF9  WDC init stubs (relocated)
$FFFA-$FFFF  Vectors
```

## Requirements

- [cc65](https://cc65.github.io/) (`brew install cc65`)
- Python 3
- [minipro](https://gitlab.com/DavidGriffith/minipro) for flashing
- Original SXB firmware dump as `SXB_orig.bin`

## Build

```bash
# Copy your original SXB firmware dump here
cp /path/to/your/SXB_dump.bin SXB_orig.bin

make
make flash   # if minipro is installed and chip is in programmer
```

## Usage

Connect at **115200 8N1**, no flow control.

On boot you'll see the WDC LED sequence, then wozmon's `\` prompt.

```
\              <- wozmon ready
A089R          <- jump to MS BASIC cold start
```

MS BASIC commands work normally. To return to wozmon, press NMI button.

## Known Issues

- `CHRIN` is polled (not interrupt-driven) — Ctrl+C during BASIC programs
  may not respond immediately
- CR/LF: set your terminal to add LF after CR for best results

## Flash Layout

The 128KB SST39SF010A is divided into four 32KB banks:

| Bank | Address | Contents |
|------|---------|----------|
| 0    | default boot | EhBASIC + Wozmon |
| 1    | fallback | Original WDC SXB2 firmware |
| 2    | empty | available |
| 3    | empty | available |
