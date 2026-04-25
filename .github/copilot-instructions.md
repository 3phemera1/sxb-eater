# GitHub Copilot Instructions

## Project Overview

This is a retro computing project targeting the **WDC W65C02SXB single-board computer** (8-bit 65C02 CPU). It combines Microsoft BASIC (1977) and Wozmon (Steve Wozniak's monitor) into a single 128KB flash ROM image for the onboard SST39SF010A flash chip.

## Build Commands

**Prerequisites**: `cc65` suite (`ca65` assembler, `ld65` linker), Python 3, `pyserial`

```bash
make                  # produces build/SXB_eater.bin (131072 bytes, 4 × 32KB banks)
make clean            # remove build artifacts
make flash            # flash via chip programmer (requires minipro)
```

There is no test suite. To verify a build, flash and connect at **115200 8N1, no flow control**.

### Finding the BASIC cold-start address after a build

```bash
grep -i cold build/eater.lbl
```

Then at the wozmon prompt type e.g. `A0B9R` (address shifts with each build).

## Two-Stage Build Pipeline

1. `ca65` assembles all sources with `-D eater` and `ld65` links using `cfg/sxb.cfg`
2. `tools/build_rom.py` patches the 32KB result into a 128KB flash image:
   - Writes `WDC\x00` at bank offset `$0000` (CPU `$8000`) — required by SXB2 bootloader
   - Optionally extracts WDC init stubs from `SXB_orig.bin` and relocates them to free space after wozmon
   - Wipes the WDC signature from bank 0 so SXB2 permanently stays in host mode (NMI recovery)

If `SXB_orig.bin` is absent, `make` automatically runs `build_rom.py --no-orig` — boots directly to wozmon, no LED diamond.

## Flash Layout (128KB)

| Bank | File Offset | CPU Range    | Contents |
|------|-------------|--------------|----------|
| 0    | `$00000`    | `$8000–$FFFF`| SXB2 recovery (WDC sig wiped — always host mode) |
| 1    | `$08000`    | `$8000–$FFFF`| Empty (user code) |
| 2    | `$10000`    | `$8000–$FFFF`| Empty (user code) |
| 3    | `$18000`    | `$8000–$FFFF`| EhBASIC + Wozmon — **default boot** |

Bank 3 is the hardware default on reset. All banks map to the same CPU address range `$8000–$FFFF`; VIA2 PCR selects which bank is visible.

## Runtime Memory Map (Bank 3)

```
$0000–$00FF  Zero page (MS BASIC + Wozmon variables)
$0100–$01FF  Hardware stack
$0200–$02FF  Wozmon input buffer (IN / STACK2)
$0300–$03FF  MS BASIC input buffer
$0400–$7FFF  MS BASIC program RAM
$7FC0–$7FCF  VIA U3 (W65C22) — sound/GPIO; PB7=T1 square wave → audio
$7FE0–$7FEF  VIA2 U5 (W65C22) — USB serial (FT245 FIFO) + bank select
$8000–$8006  WDC\x00 signature + JMP wozmon RESET
$8007–$F7FF  MS BASIC ROM
$F800–$F854  BIOS (CHRIN/CHROUT via VIA2)
$F855–$F98F  Wozmon (+ Bn bank-switch command)
$F996–$FAxx  WDC init stubs (relocated from SXB2 factory firmware)
$FFFA–$FFFF  Vectors: NMI=NMI_HANDLER, RESET=$F996, IRQ=IRQ_HANDLER
```

## Key Source Files

| File | Role |
|------|------|
| `basic/msbasic.s` | Top-level include — assembles all ~68 MS BASIC modules |
| `basic/defines_eater.s` | SXB-specific constants (ZP layout, stack, RAM boundaries) |
| `basic/defines.s` | Platform dispatch: selects `defines_eater.s` when `-D eater` is passed |
| `basic/extra.s` | Platform dispatch for extras: includes `bios_sxb.s` + `keesl.s` under `EATER` |
| `bios/bios_sxb.s` | VIA2 USB FIFO driver (CHRIN/CHROUT) + NMI recovery handler |
| `wozmon/wozmon.s` | Wozmon monitor + `Bn` bank-switch commands |
| `cfg/sxb.cfg` | ld65 linker config: defines all segments and their CPU addresses |
| `tools/build_rom.py` | Patches `WDC\x00`, relocates WDC stubs, assembles 4-bank image |
| `tools/bootstrap_flash.py` | Full 128KB flash over USB (exploits SXB2 host mode) |
| `tools/reflash_bank3.py` | Fast dev-iteration flash: bank 3 only, talks to running wozmon |

## Platform Conditional Assembly

All platform-specific code is gated with `.ifdef EATER` (set by `-D eater` on the `ca65` command line). MS BASIC modules shared with other platforms (Apple, KIM-1, CBM, etc.) must not be modified without checking their `ifdef` guards. The `bios_sxb.s` file is included via `basic/extra.s`, not directly.

## Bank Switching

VIA2 PCR (`$7FEC`) drives flash chip address lines A15/A16 via CA2/CB2 outputs:

| PCR value | Bank |
|-----------|------|
| `$CC`     | 0    |
| `$CE`     | 1    |
| `$EC`     | 2    |
| `$EE`     | 3    |

Wozmon `B0`–`B3` commands write this register then `JMP $8000`. Any custom bank image must place `WDC\x00` at `$8000` followed by `JMP <entry>` at `$8004`.

## Serial I/O

Uses the FT245 USB parallel FIFO — **not** a UART/ACIA. The BIOS polls the VIA2 ORB status register with busy-wait loops (no serial interrupts). Ctrl+C is unresponsive during long-running BASIC programs. The `\` wozmon prompt may not appear on connect due to FT245 buffering — just start typing.

Terminal must have **"Add LF after CR"** enabled for correct BASIC output (e.g. CoolTerm: Receive → Add LF after CR).

## NMI Recovery

Pressing the NMI button while in any state triggers `NMI_HANDLER` (in bank 3 ROM, also in bank 0 recovery image). The handler:
1. Waits for `$A5` sync byte from the host, replies `$01` ACK
2. Receives exactly 255 bytes into RAM at `$0800` and executes them
3. That flash writer stub streams in the full 128KB image and reflashes all banks

Run with `bootstrap_flash.py` — bank 0's wiped signature ensures SXB2 host mode is always reachable.

## `build_rom.py` Internals

When `SXB_orig.bin` is present, the script:
- Extracts five WDC stub blobs from factory bank 3 (`$F818–$FA1A`, `$F9A9–$F9C2`, `$FB99–$FBA9`)
- Relocates them to `FREE_BASE` — the first byte after `DO_SWITCH` in wozmon
- Patches internal JSR targets and wipes a call to `$E87F` (WDC proprietary routine) with NOPs
- Prepends a 5-byte bank-3 select sequence to the sigchk stub (VIA2 PCR is `0` at reset)
- Writes the WDC init stub address into the RESET vector

When modifying wozmon or bios (which changes `DO_SWITCH`), verify stub relocation still fits before `$FFFA`.

## Audio (BEEP)

`BEEP <latch>, <duration>` drives VIA U3 T1 in free-run mode on PB7 (VIA header pin 24). Frequency formula: `latch = 4,000,000 / freq_hz - 2` (8 MHz clock ÷ 2).
