# SXB EhBASIC + Wozmon + Bank 1 C Monitor

MS BASIC, Wozmon, and a C-based hardware monitor for the [WDC W65C02SXB](https://wdc65xx.com/single-board-computers/w65c02sxb/)
development board, adapted from the [Ben Eater 6502 breadboard project](https://eater.net/6502).

## Overview

This project runs Microsoft BASIC, Wozmon, and a C-based hardware monitor
directly from the W65C02SXB's onboard flash ROM. The WDC SXB2 firmware
(factory installed in bank 3) acts as a bootloader, handling USB serial
initialization before handing off to our code — also in bank 3.

On power-up:
1. WDC SXB2 firmware wakes, drives the LED diamond pattern
2. Initializes VIA2 for USB serial (FT245 parallel FIFO)
3. Detects `WDC\x00` signature at `$8000` in bank 3 → hands off
4. Wozmon starts

## Hardware

- [WDC W65C02SXB](https://wdc65xx.com/single-board-computers/w65c02sxb/) development board
- SST39SF010A 128KB flash (socketed)
- USB cable (FT245 USB-parallel FIFO on board)
- No chip programmer needed for initial flash or recovery

## Flash Layout

The SST39SF010A is 128KB divided into four 32KB banks, selected via
VIA2 PCR (`$7FEC`). Bank 3 is the hardware default on reset.

| Bank | PCR   | File Offset | Contents |
|------|-------|-------------|----------|
| 0    | `$CC` | `$00000`    | SXB2 recovery image (WDC sig wiped) |
| 1    | `$CE` | `$08000`    | **Bank 1 C Monitor** |
| 2    | `$EC` | `$10000`    | Empty — user code |
| 3    | `$EE` | `$18000`    | **EhBASIC + Wozmon (default boot)** |

Bank 3 is the boot bank (hardware default). Our code replaces the WDC SXB2
firmware in bank 3. The WDC init stubs are preserved and relocated within
bank 3 to free space after wozmon.

Bank 0 contains the SXB2 firmware with its WDC signature wiped. This means
SXB2 always enters host mode when bank 0 is active — used for NMI recovery.
See [NMI Recovery](#nmi-recovery) below.

## Memory Map (bank 3)

```
$0000-$00FF  Zero page (MS BASIC + Wozmon variables)
$0100-$01FF  Hardware stack
$0200-$02FF  Wozmon input buffer
$0300-$03FF  MS BASIC input buffer
$0400-$7FFF  MS BASIC program RAM
$7FC0-$7FCF  VIA U3 (sound/GPIO: PB7=audio out, VIA header pin 24)
$7FE0-$7FEF  VIA2 U5 (USB serial + bank select via PCR at $7FEC)
$8000-$8006  WDC\x00 signature + JMP wozmon RESET
$8007-$F7FF  MS BASIC ROM
$F800-$F854  BIOS (VIA2 serial + CHRIN/CHROUT)
$F855-$F98F  Wozmon (including bank-switch B command)
$F996-$FAxx  WDC init stubs (relocated from SXB2)
$FFFA-$FFFF  Interrupt vectors (RESET=$F996, NMI=NMI_HANDLER)
```

## Requirements

### Build tools

- **cc65**: `brew install cc65`
- **Python 3** + **pyserial**: `pip install pyserial`
- **minipro** (optional, for chip programmer): `brew install minipro`

### Original firmware dump

A dump of the original SST39SF010A chip is required as `SXB_orig.bin`
in the repo root. `build_rom.py` extracts WDC init stubs from it.

```bash
minipro -p "SST39SF010A" -r SXB_orig.bin
```

`SXB_orig.bin` is gitignored — it contains WDC proprietary firmware.

If you don't have `SXB_orig.bin`, `make` automatically builds with
`--no-orig` — no LED diamond on boot, but everything else works.

## Building

```bash
git clone https://github.com/WW0K/sxb-eater.git
cd sxb-eater
cp /path/to/SXB_orig.bin .   # optional but recommended

make
```

Produces `build/SXB_eater.bin` — the 128KB flash image.

## Bank 1 C Monitor

Bank 1 holds a lightweight hardware monitor written in C (compiled with cc65)
and linked as a standalone 32KB ROM image. It provides the same wozmon-style
commands plus a small SDK for experimenting with the board's peripherals from C.

### Commands

| Command | Description |
|---------|-------------|
| `AAAA` | Examine byte at address `AAAA` |
| `AAAA.BBBB` | Examine memory range `AAAA`–`BBBB` (8 bytes/line) |
| `AAAA: HH ...` | Write one or more bytes to memory starting at `AAAA` |
| `AAAAR` | JSR to `AAAA`; returns to monitor prompt when code RTSs |
| `L` | Load Motorola S-records (S1/S9) from serial — see [Uploading Programs](#uploading-programs) |
| `B0`–`B3` | Switch to flash bank 0–3 (uses wozmon RAM trampoline) |
| `?` | Show help |

Switch to bank 1 from wozmon with the `B1` command. The monitor banner
(`SXB Monitor  Bank 1  (C monitor)`) appears and the `monitor>` prompt
is ready for input. Switch back to bank 3 (wozmon + BASIC) with `B3`.

### Hardware SDK headers

The monitor includes headers that can be reused by user code compiled into
bank 1:

| Header | Contents |
|--------|----------|
| `via.h` | VIA U3 (`$7FC0`) register macros + `via_t1_freerun(latch)`, `via_t2_oneshot(count)` |
| `pia.h` | PIA (`$BFC0`) register macros |
| `acia.h` | ACIA register macros (if an ACIA is wired to the expansion header) |
| `serial.h` / `serial.s` | Low-level VIA2 FT245 FIFO putchar/getchar (hand-written 65C02 assembly) |
| `util.h` | `parse_hex()`, `skip_spaces()`, `serial_puthex8/16()` |

### Building without the monitor

```bash
make NO_MONITOR=1     # bank 1 left as $FF
```

### Bank 1 source layout

```
monitor/
  main.c          Command processor and top-level monitor loop
  srec.c / srec.h Motorola S-record loader (L command)
  crt0.s          Startup: WDC sig, VIA2 init, cc65 runtime init, vectors
  serial.s        VIA2 FT245 FIFO serial I/O (hand-written assembly)
  via.c / via.h   VIA U3 driver + register SDK
  pia.c / pia.h   PIA driver + register SDK
  acia.c / acia.h ACIA driver + register SDK
  util.c / util.h Hex parsing and output helpers
  cfg/monitor.cfg ld65 linker config for the 32KB bank 1 image
```

The startup stub (`crt0.s`) places the `WDC\x00` signature at `$8000`,
initializes VIA2 for USB serial, runs the cc65 BSS-zero and data-copy
routines, then calls `main()`. Bank switching uses the RAM trampoline
left by wozmon at `$02FA` so the CPU safely fetches the JMP target from
RAM after the flash bank changes under it.

## Uploading Programs

The bank 1 C monitor can receive code over serial and run it directly from RAM.
`tools/upload.py` automates both the transfer and the optional run step.

### Quick start — Hello World

```bash
# Switch to bank 1 from wozmon (if not already there)
# At wozmon prompt:  B1

# Build and upload the included Hello World example
make
python3 tools/upload.py /dev/cu.usbserial-XXXXXXXX build/hello.bin --addr 4000 --run
```

You should see `Hello, World!` printed on the terminal, then the
`monitor>` prompt returns.

### `upload.py` reference

```
python3 tools/upload.py <port> <file> [options]

  port              Serial port, e.g. /dev/cu.usbserial-XXXX
  file              Binary (.bin) or S-record (.s19 / .srec / .mot)

  --addr XXXX       Load address for .bin files (hex, no 0x, e.g. 4000)
  --run             Execute after upload
  --baud N          Baud rate (default: 115200)
```

**Binary mode** (`.bin` + `--addr`)  
Converts the file to `ADDR: HH HH ...` store commands, waits for the
monitor prompt between each line. Safe for any FIFO size.

**S-record mode** (`.s19` / `.srec` / `.mot`)  
Sends the monitor's `L` command, then streams records one at a time,
waiting for a per-record ack. The monitor handles S0 (header), S1
(16-bit address data), S5 (record count), and S9 (end / entry address).
S2/S3/S7/S8 (24/32-bit variants) are rejected — `ld65` emits S1/S9 for
65C02 targets, so this is not a limitation in practice.

### Writing your own programs

User programs run in RAM at `$4000`–`$6CFF` under the bank 1 ROM.  The
`hello/` directory is a working template:

```
hello/
  hello.c           Your C source (include serial.h for I/O)
  crt0.s            Minimal startup: saves/restores monitor ZP state,
                    sets up cc65 stack, calls main(), RTSs to monitor
  cfg/hello.cfg     ld65 config: flat binary at $4000, C stack at $6D00
```

The `crt0.s` in `hello/` saves the monitor's cc65 zero-page state before
overwriting it, and restores it before returning.  This lets user code use
the full cc65 runtime (software stack, string functions, etc.) without
corrupting the monitor on return.

The `serial.s` driver from `monitor/` is linked into user programs at
build time, so `serial_putchar()`, `serial_puts()`, `serial_puthex8/16()`
and `serial_getchar()` are available at link time without depending on
the monitor's internal symbol addresses.

**RAM layout for user programs**

```
$0000–$001F  cc65 ZP (saved/restored by crt0.s)
$4000–$6CFF  User code, rodata, data, BSS  (~11.5 KB)
$6D00        C stack top (grows down, 512 bytes)
$6B00–$7AFF  (safe margin — monitor C stack lives at $7700–$7B00)
```

**Build your own program**

1. Copy `hello/` to a new directory (e.g. `myapp/`)
2. Edit `myapp/myapp.c` — use `serial_puts()` / `serial_putchar()` for output
3. Add a build rule to the Makefile modelled on the `hello` rules
4. `make && python3 tools/upload.py <port> build/myapp.bin --addr 4000 --run`

## Flashing

### Initial flash (factory board — no programmer needed)

On a factory-fresh board, bank 0 is empty and SXB2 automatically enters
host mode on boot. The bootstrap script exploits this to program the full
128KB image over USB.

```bash
# Close any terminal program first
python3 tools/bootstrap_flash.py /dev/cu.usbserial-XXXXXXXX build/SXB_eater.bin
```

Takes ~15 seconds. Board resets to wozmon when done.

> **After this initial flash**, bank 0 contains the SXB2 recovery image
> (signature wiped). The NMI button can trigger a full reflash at any time.
> You never need a chip programmer again.

### Development iteration (wozmon already running)

After initial flash, use `reflash_bank3.py` to update bank 3 only.
Talks directly to wozmon over serial — no handshake protocol.

```bash
make                  # rebuild
# Board must be at wozmon prompt (press reset if in BASIC)
python3 tools/reflash_bank3.py /dev/cu.usbserial-XXXXXXXX build/SXB_eater.bin
```

Takes ~8 seconds. Board resets to wozmon when done.

### NMI Recovery

If bank 3 is broken (bad flash, locked up code), press the **NMI button**
to trigger a full 4-bank reflash from any state:

```bash
python3 tools/bootstrap_flash.py /dev/cu.usbserial-XXXXXXXX build/SXB_eater.bin
# When prompted, press the NMI button on the board
```

How it works:

1. NMI fires → NMI handler (in bank 3 ROM) initializes VIA2 serial
2. Waits for `$A5` sync byte from host, replies with `$01` ACK
3. Receives 255-byte flash writer into RAM at `$0800`, executes it
4. Flash writer programs all 4 banks from the streamed 128KB image
5. Board resets — even a completely broken bank 3 is recovered

If bank 3 itself is so broken that the NMI handler can't run, a chip
programmer is required as a last resort:

```bash
minipro -p "SST39SF010A" -w build/SXB_eater.bin
```

## Usage

Connect at **115200 8N1, no flow control**. After power cycle or reset,
wozmon starts.

### Wozmon commands

| Command | Description |
|---------|-------------|
| `XXXXR` | Run code at hex address XXXX |
| `XXXX`  | Examine memory at XXXX |
| `XXXX: YY ZZ ...` | Write bytes to memory |
| `XXXX.YYYY` | Examine memory range |
| `B0` | Switch to bank 0 (SXB2 recovery — board goes silent) |
| `B1` | Switch to bank 1 (user ROM) |
| `B2` | Switch to bank 2 (user ROM) |
| `B3` | Reload wozmon (bank 3) |

### Launching MS BASIC

Check the current cold start address:

```bash
grep -i cold build/eater.lbl
```

Then at the wozmon prompt type e.g. `A0B9R` (address varies with builds).
Press Enter at both prompts (`MEMORY SIZE?` and `TERMINAL WIDTH?`).
Press the **reset button** to return to wozmon from BASIC.

### Terminal settings

Enable **"Add LF after CR"** in your terminal for correct BASIC output.
(CoolTerm: Receive → Add LF after CR)

> **Note on wozmon prompt:** The `\` prompt is sent on startup but may not
> appear immediately due to FT245 USB FIFO buffering. Just start typing —
> wozmon is ready. The prompt will appear after your first keypress.

## Peripheral Map

```
$7FC0-$7FCF  VIA U3 (W65C22) — sound/GPIO
  PB7 (VIA header pin 24): T1 square wave output → LM386 audio amplifier
  ACR=$7FCB, T1CL=$7FC4, T1CH=$7FC5, DDRB=$7FC2
  Frequency: latch = 4,000,000/freq_hz - 2  (8MHz clock)
  BEEP syntax: BEEP <latch>, <duration>

$7FE0-$7FEF  VIA2 U5 (W65C22) — USB serial + bank select
  FT245 data bus on port A, strobes on port B
  PCR ($7FEC): $CC=bank0, $CE=bank1, $EC=bank2, $EE=bank3
```

## How It Works

The WDC SXB2 firmware in bank 3 checks for `WDC\x00` at `$8000` after
USB init. If found, it RTIs to `$8004` — our `JMP wozmon_RESET`.

The WDC init stubs are extracted from `SXB_orig.bin`, patched, and
relocated to free space after wozmon in bank 3. The RESET vector points
to the relocated init stub so the full WDC sequence (LEDs, VIA2, USB)
runs on every reset. The sigchk stub selects bank 3 (PCR=`$EE`) before
reading `$8000`, since VIA2 PCR is cleared to 0 on hardware reset.

Bank 0 contains SXB2 firmware with WDC signature wiped (`$FF`). SXB2
only enters host mode when it cannot find a valid WDC signature — so
bank 0 is permanently in host mode, available for NMI recovery.

`tools/build_rom.py` handles all patching automatically.

## Flash Your Own Code

Any 32KB binary can replace EhBASIC in bank 3. It must start with
`WDC\x00` at `$8000` and `JMP <entry>` at `$8004`.

```bash
# Reflash bank 3 only (wozmon must be running)
python3 tools/reflash_bank3.py <port> your_32k_image.bin

# Or full reflash via NMI recovery
python3 tools/bootstrap_flash.py <port> your_128k_image.bin
# (press NMI when prompted)
```

Banks 1 and 2 are empty and available for user code, accessible via
wozmon's `B1`/`B2` bank switch commands.

## Known Issues / TODO

- [ ] `\` prompt not visible on connect (FT245 buffering — type to flush)
- [ ] CR/LF: enable "Add LF after CR" in terminal
- [ ] Register display not yet in wozmon
- [ ] Bank 1 monitor: no line history / up-arrow recall

## Attribution

- **MS BASIC** — Microsoft, 1977
- **[msbasic](https://github.com/keesL/msbasic)** by Kees van Oss
- **[Ben Eater](https://eater.net/6502)** — 6502 breadboard project
- **[Wozmon](https://www.sbprojects.net/projects/apple1/wozmon.php)** — Steve Wozniak
- **WDC SXB2 firmware** — Western Design Center (bootloader + recovery image, not distributed)

## License

MS BASIC is copyright Microsoft 1977. The ca65 port, wozmon, and surrounding
infrastructure are MIT licensed per their upstream repositories. SXB-specific
files (`bios/`, `tools/`, `cfg/sxb.cfg`, `Makefile`) are MIT licensed.
