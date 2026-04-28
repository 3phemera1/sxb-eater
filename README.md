# SXB EhBASIC + Wozmon + Bank 1 C Monitor

MS BASIC, Wozmon, and a C-based hardware monitor for the [WDC W65C02SXB](https://wdc65xx.com/single-board-computers/w65c02sxb/)
development board, adapted from the [Ben Eater 6502 breadboard project](https://eater.net/6502).

## Overview

This project runs Microsoft BASIC, Wozmon, and a C-based hardware monitor
directly from the W65C02SXB's onboard flash ROM.

**Before flashing this firmware:**
The factory WDC SXB2 bootloader lives in bank 3 (the default boot bank).
On power-up, SXB2 drives the LED diamond pattern and initializes USB serial.

**After flashing this firmware:**
Bank 3 is completely replaced with our EhBASIC + Wozmon image. We extract
the WDC initialization stubs from the factory firmware (via `SXB_orig.bin`)
and relocate them into free space at the end of bank 3, so the LED diamond
and USB setup still run on cold boot before Wozmon starts.

Boot sequence after flash:
1. Hardware reset → WDC init stubs run (LED diamond, VIA2 USB init)
2. Stubs detect `WDC\x00` signature at `$8000` → hand off to our code
3. Wozmon prompt appears

## Hardware

- [WDC W65C02SXB](https://wdc65xx.com/single-board-computers/w65c02sxb/) development board
- SST39SF010A 128KB flash (socketed)
- USB cable (FT245 USB-parallel FIFO on board)
- No chip programmer needed for initial flash or recovery

## Flash Layout

The SST39SF010A is 128KB divided into four 32KB banks, selected via
VIA2 PCR (`$7FEC`). Bank 3 is the hardware default on reset.

### Flash States Through the Lifecycle

**Table 1: Factory Default (fresh board from WDC)**

| Bank | Contents |
|------|----------|
| 0    | Empty ($FF) |
| 1    | Empty ($FF) |
| 2    | Empty ($FF) |
| 3    | SXB2 bootloader (WDC\x00 signature at $8000, LED diamond, USB init) |

---

**Table 2a: After Flashing (no `SXB_orig.bin`, using `--no-orig`)**

Fastest build when you don't have a chip reader. LED diamond is skipped, but
everything else works. NMI recovery uses wozmon's own handler.

| Bank | Contents |
|------|----------|
| 0    | Empty ($FF) — no recovery firmware |
| 1    | Empty ($FF) — user space |
| 2    | Empty ($FF) — user space |
| 3    | EhBASIC + Wozmon + NMI handler; **no** WDC init stubs (direct boot) |

---

**Table 2b: After Flashing (with `SXB_orig.bin`, normal mode)**

Preserves LED diamond on cold boot and SXB2 host-mode recovery firmware.
WDC stubs extracted from `SXB_orig.bin`, patched, and relocated into bank 3
after wozmon. Bank 0's SXB2 has signature wiped to force permanent host mode.

| Bank | Contents |
|------|----------|
| 0    | SXB2 firmware (complete, signature **wiped** to force host mode) |
| 1    | Empty ($FF) — user space |
| 2    | Empty ($FF) — user space |
| 3    | EhBASIC + Wozmon + **WDC init stubs** (relocated) + NMI handler |

---

**Table 3: After Flashing with Bank 1 C Monitor (normal mode)**

Same as Table 2b, but bank 1 is occupied.

| Bank | Contents |
|------|----------|
| 0    | SXB2 firmware (complete, signature wiped) |
| 1    | **C Monitor** (32KB standalone ROM) |
| 2    | Empty ($FF) — user space |
| 3    | EhBASIC + Wozmon + WDC init stubs + NMI handler |

---

**Table 4: After Uploading `hello.bin` to Bank 1 Monitor (no flash change)**

When you use `upload.py` to load code into the Bank 1 C Monitor, only RAM
changes — no flash reprogramming occurs.

| Bank | Contents |
|------|----------|
| 0    | (unchanged) SXB2 firmware (complete, signature wiped) |
| 1    | (unchanged) C Monitor |
| 2    | (unchanged) Empty ($FF) |
| 3    | (unchanged) EhBASIC + Wozmon + WDC init stubs + NMI handler |
| RAM  | **$4000–$6CFF now contains `hello.bin` code** (temporary, until power cycle) |

---

### Key Points

- **Does `SXB_orig.bin` matter?** It's **optional**. It only buys you:
  - LED diamond sequence on cold boot (cosmetic)
  - SXB2 host-mode firmware in bank 0 (redundant backup for recovery)
  
  **Without it**: Bank 0 is empty, no LED diamond, but you still have full NMI
  recovery via wozmon's own handler (in bank 3). Everything else is identical.

- **Bank 0 after flash**: Always has SXB2 (complete firmware) with the signature
  wiped. If `SXB_orig.bin` is missing, bank 0 is left empty ($FF). Either way,
  NMI recovery works.

### Bank 3 — Our Code Replaces SXB2

The factory WDC SXB2 firmware is **completely replaced** in bank 3 by our
EhBASIC + Wozmon image.

- **With `SXB_orig.bin`**: We extract the five WDC initialization routines,
  patch their addresses, and relocate them into bank 3 after wozmon. This
  preserves the LED diamond sequence and USB setup on cold boot.

- **Without `SXB_orig.bin`** (`--no-orig`): No WDC stubs — RESET vector points
  directly to wozmon. Board boots instantly to wozmon prompt with no LED sequence.

### Bank 0 — Recovery / NMI Mode

- **With `SXB_orig.bin`**: Bank 0 contains a **complete copy** of the factory
  SXB2 firmware (all stubs). The WDC signature is intentionally wiped so SXB2
  always enters **host mode** (waits for reflash commands over serial).

- **Without `SXB_orig.bin`**: Bank 0 is left empty ($FF). NMI recovery relies
  entirely on wozmon's own NMI handler (in bank 3 ROM).

Both modes support emergency reflash via NMI button. The difference is whether
the classic SXB2 host-mode protocol or wozmon's simpler NMI handler is used.

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

A dump of the original SST39SF010A chip is **optional but recommended** as
`SXB_orig.bin` in the repo root. It allows us to extract and relocate the
WDC SXB2 initialization stubs (LED diamond, VIA2 setup, USB enumeration).

**To obtain `SXB_orig.bin`:**

**Best method: Automatic extraction during first flash**  
When you flash a **factory-fresh board** for the first time, `bootstrap_flash.py`
automatically detects the original SXB2 firmware and offers to extract it:

```bash
python3 tools/bootstrap_flash.py /dev/cu.usbserial-XXXXX build/SXB_eater.bin
# Output includes:
#   "Factory board detected. Bank 3 contains original SXB2 firmware."
#   "Would you like to save a backup of bank 3? (y/n): "
```

Just answer `y` and follow the prompts. The script uploads a small flash reader
to RAM, extracts bank 3 (32KB), and saves it as `SXB_orig.bin` (or custom filename).
This only happens on the first flash of a factory board — not on NMI recovery
or subsequent reflashes.

**Alternative method: Chip programmer**  
If you have a **chip programmer** (minipro):
```bash
minipro -p "SST39SF010A" -r SXB_orig.bin
```

**If you don't extract or provide `SXB_orig.bin`:**  
Build with `make` (or `make NO_MONITOR=1`). If `SXB_orig.bin` is missing,
the build automatically uses `--no-orig` mode:
```bash
make                  # builds without SXB_orig.bin
```

Everything works without it; you just skip the LED diamond and SXB2 host-mode
backup recovery. Wozmon's built-in NMI handler still provides full emergency
recovery.

**Note**: `SXB_orig.bin` is gitignored — it contains WDC proprietary firmware.

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
# 1. Build (top-level `make` builds SXB_eater.bin AND build/hello.bin)
make

# 2. Switch the board to the bank 1 C monitor.
#    At the wozmon `\` prompt, type:  B1
#    The banner "SXB Monitor  Bank 1  (C monitor)" appears, followed by `monitor> `.

# 3. Close your terminal program (only one process can hold the serial port),
#    then upload + run hello.bin:
python3 tools/upload.py /dev/cu.usbserial-XXXXXXXX build/hello.bin --addr 4000 --run
```

Expected session output:

```
Connecting to /dev/cu.usbserial-XXXXXXXX at 115200 baud ...
  Monitor ready.
  File: build/hello.bin  (123 bytes, binary)
  Uploading 123 bytes to 4000 ...
  123/123 bytes  (100%)
  Jumping to 4000 ...
── Program output (Ctrl+C to exit) ──
Hello, World!
Enter your name: Zach
you entered Zach
monitor>
```

Press **Ctrl+C** to detach from the tail stream, or pass
`--tail-idle 2` to auto-exit after 2 s of silence.

### `upload.py` reference

```
python3 tools/upload.py <port> <file> [options]

  port              Serial port, e.g. /dev/cu.usbserial-XXXX
  file              Binary (.bin) or S-record (.s19 / .srec / .mot / .s28)

  --addr XXXX       Load address for .bin files (hex, no 0x, e.g. 4000)
  --run             Execute after upload, then tee serial output to stdout
                    until Ctrl+C (or --tail-idle expires)
  --tail-idle SECS  Auto-exit --run tail mode after SECS of serial silence
                    (default: 0 = wait for Ctrl+C)
  --baud N          Baud rate (default: 115200)
```

**Binary mode** (`.bin` + `--addr`)  
Converts the file to `ADDR: HH HH ...` store commands, waits for the
monitor prompt between each line. Safe for any FIFO size. With `--run`,
issues `ADDRR` to JSR into the loaded image.

**S-record mode** (`.s19` / `.srec` / `.mot` / `.s28`)  
Sends the monitor's `L` command, then streams records one at a time,
waiting for a per-record ack. The monitor handles S0 (header), S1
(16-bit address data), S5 (record count), and S9 (end / entry address).
S2/S3/S7/S8 (24/32-bit variants) are rejected — `ld65` emits S1/S9 for
65C02 targets, so this is not a limitation in practice. With `--run`,
the tool jumps to the entry address from the S9 record.

### Writing your own programs

User programs run from RAM at `$4000`–`$6CFF` while the bank 1 C monitor
stays resident in ROM. The `hello/` directory is a complete, working
template — the simplest path is to edit it in place, or copy it to a new
directory and add a parallel build rule.

#### Template layout

```
hello/
  hello.c           User C source. Includes "serial.h" for I/O.
  crt0.s            Minimal startup: saves the monitor's cc65 ZP state,
                    runs zerobss/copydata, sets up the user C stack at
                    $6D00, calls main(), restores monitor ZP, RTSs back
                    to the monitor's `R` command.
  cfg/hello.cfg     ld65 config: flat binary at $4000, C stack at $6D00.
```

The shared `monitor/serial.s` driver is linked into the user binary, so
no symbols from the monitor ROM need to be resolved at runtime — your
program is fully position-independent of the bank 1 ROM build.

#### Available runtime APIs

Headers in `monitor/` are on the include path (`-I monitor`) when building
hello, so any of the following can be `#include`d from user code:

| Header | Functions / macros |
|--------|--------------------|
| `serial.h` | `serial_putchar(c)`, `serial_puts(s)`, `serial_getchar()`, `serial_puthex8(b)`, `serial_puthex16(w)` |
| `via.h`    | VIA U3 register macros (`VIA_DDRB`, `VIA_T1CL`, …) + `via_t1_freerun(latch)`, `via_t2_oneshot(count)` |
| `pia.h`    | PIA register macros (`PIA_PRA`, `PIA_CRA`, …) |
| `acia.h`   | ACIA register macros (only useful if an ACIA is wired to the expansion header) |
| `util.h`   | `parse_hex()`, `skip_spaces()`, plus the `serial_puthex*` helpers |

Plus the cc65 standard library subset — `string.h`, `stdint.h`, `ctype.h`,
basic `stdio.h` formatting (no file I/O). The user C stack is 512 bytes
(`$6B00`–`$6CFF`), so keep recursion and large stack-allocated arrays
modest.

#### RAM layout for user programs

```
$0000–$001F  cc65 ZP (saved on entry, restored on return by crt0.s)
$4000–$6CFF  User code, rodata, data, BSS  (~11.5 KB)
$6B00–$6CFF  User C stack (grows down from $6D00, 512 bytes)
$7700–$7AFF  Monitor's own C stack — keep your code/data below this
```

#### Iterating on `hello.c`

The fastest workflow is to edit `hello/hello.c` in place:

```bash
$EDITOR hello/hello.c
make hello                                 # rebuilds just build/hello.bin
python3 tools/upload.py /dev/cu.usbserial-XXXXXXXX \
        build/hello.bin --addr 4000 --run --tail-idle 2
```

`make hello` is a fast incremental build — no need to rebuild the full
flash image. Repeat the upload after each edit; the monitor stays resident
so the board does not need to be reset between runs.

#### Cloning hello as a new project

```bash
cp -R hello myapp
mv myapp/hello.c myapp/myapp.c
$EDITOR myapp/myapp.c                      # write your program
```

Then add a parallel build rule to the top-level `Makefile` — copy the
`# ── Hello World example ──` block (the `HELLO_DIR`, `$(BUILD)/hello/*`
and `$(BUILD)/hello.bin` rules) and substitute `myapp` for `hello`
throughout. Add `$(BUILD)/myapp.bin` to the `all:` target if you want it
built by default. Finally:

```bash
make myapp
python3 tools/upload.py /dev/cu.usbserial-XXXXXXXX \
        build/myapp.bin --addr 4000 --run
```

#### Returning to the monitor

`main()` returning normally restores the monitor's zero page and RTSs
back to the `monitor>` prompt. If your program loops forever, press the
**reset button** (returns to wozmon) and then `B1` to re-enter the
monitor.

## Flashing

### Initial flash (factory board — no programmer needed)

On a factory-fresh board, bank 3 contains the factory SXB2 bootloader, which
automatically enters host mode on boot and waits for reflash commands over USB
serial. The bootstrap script exploits this to program the full 128KB image.

```bash
# Close any terminal program first
python3 tools/bootstrap_flash.py /dev/cu.usbserial-XXXXXXXX build/SXB_eater.bin
```

Takes ~15 seconds. Board resets to wozmon when done.

After this flash:
- **Bank 3** is replaced with our EhBASIC + Wozmon image (WDC stubs relocated inside)
- **Bank 0** receives a copy of SXB2 with signature wiped (for emergency recovery)
- You never need a chip programmer again — NMI button provides full recovery

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

**Factory state:**
The factory-installed SXB2 firmware (from `SXB_orig.bin` bank 3) is a 32KB
bootloader that wakes on reset, drives the LED diamond, initializes VIA2,
and looks for a `WDC\x00` signature at `$8000` to detect a user program.

**After flashing our firmware:**
Bank 3 is **completely replaced** with our EhBASIC + Wozmon + WDC stubs
image. We extract the five WDC init routines from the factory dump,
patch their internal JSR targets to reflect their new addresses, and relocate
them to free space after wozmon (starting at `WOZMON_END`). The RESET vector
points to the relocated init stub, so on every cold boot:

1. Relocated WDC init runs (LED diamond, VIA2 setup, USB enumeration)
2. Relocated sigchk routine checks for `WDC\x00` at `$8000`
3. If found, sigchk hands off to `$8004` (JMP wozmon_RESET)
4. Wozmon prompt appears

Bank 0 contains the original SXB2 firmware **with WDC signature wiped** to
ensure it always enters host mode. This is used only for NMI recovery — when
the NMI button is pressed, the NMI handler loads a flash writer stub into RAM
and accepts a complete 128KB image over serial.

Warm reset paths (wozmon `B` commands, bootstrap flash writer) bypass the
RESET vector by jumping directly to `$8004`, so the WDC stubs only run on
true cold boot, avoiding unnecessary LED sequences during development.

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
