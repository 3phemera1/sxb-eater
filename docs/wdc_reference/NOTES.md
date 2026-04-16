# SXB Hardware & Firmware Notes

Findings from reverse engineering the W65C02SXB board and its firmware.
Documented here to save future users the pain.

---

## Flash Chip: SST39SF010A

- 128KB (131072 bytes), organized as 4 × 32KB banks
- Banks selected via VIA1 port B (bank select LEDs show current bank)
- Default boot bank on reset: **Bank 3** (both FAMS/FA15 LEDs off)

| Bank | File Offset | CPU Address | Default Contents |
|------|-------------|-------------|-----------------|
| 0    | `$00000`    | `$8000-$FFFF` | User application |
| 1    | `$08000`    | `$8000-$FFFF` | Empty |
| 2    | `$10000`    | `$8000-$FFFF` | Empty |
| 3    | `$18000`    | `$8000-$FFFF` | WDC SXB2 firmware |

---

## WDC SXB2 Firmware (factory default in bank 3)

The factory firmware is **not** the WDCTools-compatible monitor most
documentation refers to. It is a custom bootloader called "SXB2" which
operates in two modes:

### Mode 1: Auto-boot (if `WDC\x00` found at `$8000`)

Full boot sequence:
1. Reset → `$F818`
2. VIA1 bank-select toggle sequence → drives LED diamond pattern
3. JSR `$F9C2` → VIA2 init (USB serial via FT245)
4. STA `$7FC2` = `$FF` (VIA1 DDRB outputs)
5. Loop calling JSR `$FA10` → polls FT245 USB enumeration
6. JSR `$F9A9` → checks `'WDC\x00'` at `$8000`
7. **If found** → RTI to `$8004` (auto-boot to user code)
8. **If not found** → fall through to host handshake mode

The `WDC\x00` signature check reads the **currently mapped bank**.
Since bank 3 is active on reset, it reads `$8000` in bank 3.
To auto-boot your own code, put `WDC\x00` at `$8000` and `JMP <entry>`
at `$8004` in your bank 3 image.

### Mode 2: Host handshake (no `WDC\x00` found)

Waits for host to send `$55 $AA` handshake, then accepts commands:

| CMD  | Name       | Description |
|------|------------|-------------|
| `$03` | READ_MEM  | Read from CPU address space |
| `$06` | EXEC_MEM  | Execute at address via RTI |
| `$07` | WRITE_MEM | Write to RAM — **ALWAYS writes to `$0800`, ignores address param!** |
| `$0C` | CHECK_WDC | Check `WDC\x00` signature at `$8000` |

**Critical:** CMD `$07` in SXB2 firmware does NOT write to flash.
It writes to RAM at `$0800` regardless of the address parameter.
This is different from WDCMON's CMD `$07` which actually writes flash.

### SXB2 Handshake Protocol

```
Host → Board: $55 $AA
Board → Host: $CC
Host → Board: <cmd byte>
[parameters and data follow per command]
```

CMD `$03` READ_MEM parameters (6 bytes):
```
addr_lo, addr_hi, bank, len_lo, len_hi, $00
```

CMD `$06` EXEC parameters (3 bytes):
```
addr_lo, addr_hi, bank
```

CMD `$07` WRITE_MEM parameters (6 bytes + data):
```
addr_lo, addr_hi, bank, len_lo, len_hi, $00, <data bytes>
```
Note: addr is ignored, data always goes to `$0800`.

---

## WDCMON v2.0.4.3 (W65C02SXB.s28)

WDC provides a separate monitor `W65C02SXB.s28` intended to be flashed
into bank 0. This is the monitor that WDCTools and `wdc_uploader_term.py`
are designed to work with.

**Key differences from SXB2:**
- Has `WDC\x00` at `$8000` → SXB2 will auto-boot to it
- Full flash read/write/erase commands (CMD `$07`/`$08`/`$09`)
- Register display and debug commands
- Proper memory write (CMD `$02`) that uses the address parameter

WDCMON command set:

| CMD  | Name          | Description |
|------|---------------|-------------|
| `$00` | SYNC         | Handshake |
| `$01` | ECHO         | Echo bytes back |
| `$02` | WRITE_MEM    | Write to RAM at specified address |
| `$03` | READ_MEM     | Read from RAM |
| `$04` | GET_INFO     | Board info |
| `$05` | EXEC_DEBUG   | Execute with debug/register capture |
| `$06` | EXEC_MEM     | Execute at address |
| `$07` | WRITE_FLASH  | Write to flash bank 0 |
| `$08` | READ_FLASH   | Read from flash |
| `$09` | CLEAR_FLASH  | Erase flash sector |
| `$0A` | CHECK_FLASH  | Verify flash |
| `$0B` | EXEC_FLASH   | Execute from flash (`JMP $0000`) |
| `$0C` | BOARD_INFO   | Board identification |
| `$0D` | UPDATE       | Firmware update |

WDCMON uses the **same `$55/$AA/$CC` handshake** as SXB2 but with the
extended command set above.

---

## VIA2 / FT245 USB Serial

The FT245 USB parallel FIFO is connected to VIA2:

| Register | Address | Function |
|----------|---------|----------|
| VIA2_ORB | `$7FE0` | Strobe/status bits |
| VIA2_ORA | `$7FE1` | Data bus to/from FT245 |
| VIA2_DDRB| `$7FE2` | Direction register B |
| VIA2_DDRA| `$7FE3` | Direction register A |

VIA2_ORB bits:
- Bit 0: TX ready (clear = ready to send)
- Bit 1: RX ready (clear = data available)
- Bit 2: WR strobe (high = write to FT245)
- Bit 3: RD strobe (high = idle, low = reading)

**Init sequence** (must match WDC firmware exactly):
```
STA $7FE0 = $0C    ; WR+RD strobes high first
STA $7FE2 = $0C    ; DDRB: bits 2,3 = outputs
STZ $7FE3          ; DDRA: port A = input
```

**TX sequence:**
```
STZ VIA2_DDRA          ; tristate port A
STA char, VIA2_ORA     ; write char to bus
wait bit 0 VIA2_ORB    ; wait TX ready
SET bit 2 VIA2_ORB     ; WR strobe high
STA VIA2_DDRA = $FF    ; drive port A
NOP NOP
CLR bit 2 VIA2_ORB     ; WR strobe low
STZ VIA2_DDRA          ; tristate port A
```

**RX sequence:**
```
STZ VIA2_DDRA          ; port A = input
wait bit 1 VIA2_ORB    ; wait RX ready
CLR bit 3 VIA2_ORB     ; RD strobe low
NOP NOP
LDA VIA2_ORA           ; read char
SET bit 3 VIA2_ORB     ; RD strobe high
```

---

## Bootstrap: Flashing Without a Programmer

A fresh SXB has no `WDC\x00` signature in bank 0. The SXB2 firmware
enters host handshake mode and waits. The `tools/bootstrap_flash.py`
script exploits this to write a self-flashing stub to RAM via CMD `$07`,
then executes it to program EhBASIC into bank 0 — no chip pull required.

See `tools/bootstrap_flash.py` and the Bootstrap section of the README.

---

## Bank Switching

The SST39SF010A bank is selected by VIA1:

| LED State | Bank | Contents |
|-----------|------|----------|
| Both off  | 3    | WDC SXB2 (default boot) |
| One on    | 2    | Empty |
| One on    | 1    | Empty |
| Both on   | 0    | EhBASIC + Wozmon |

Bank switching requires the VIA1 ROR sequence from WDC firmware.
This is not yet implemented in wozmon/BIOS.

---

## Known Issues / TODO

- [ ] `CHRIN` is polled — Ctrl+C unresponsive during BASIC programs
- [ ] No CR+LF auto-add — some terminals need "add LF after CR"
- [ ] No S19/S28 record loader in wozmon
- [ ] No register display in wozmon
- [ ] Bank switch command not implemented
- [ ] IRQ-driven receive buffer not implemented
