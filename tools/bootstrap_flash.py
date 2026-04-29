#!/usr/bin/env python3
"""
bootstrap_flash.py - Flash W65C02SXB without a chip programmer

Works on a FACTORY FRESH SXB (bank 3 = SXB2, banks 0-2 empty).
SXB2 enters host handshake mode when no WDC signature found.

Strategy:
  1. Detect board state (factory SXB2 vs. already-flashed SXB_eater)
  2. If factory: offer to extract and save bank 3 (original SXB2 firmware)
  3. Use SXB2 CMD $07 to upload a monolithic RAM flash writer (~246 bytes)
  4. Use SXB2 CMD $06 to execute the flash writer
  5. Flash writer receives the full 128KB image over serial (raw bytes)
  6. Flash writer programs all 4 banks sequentially
  7. Board resets when done

The flash writer runs entirely from RAM ($1000), so bank switching
during programming never kills the command loop.

Optional extraction: On first flash of a factory board, this script offers
to extract the full 128KB flash via a small 65C02 flash reader and save it
as SXB_orig.bin (suitable for use by build_rom.py)
(or custom filename). This allows future builds to include the WDC init
stubs (LED diamond, USB enumeration). The extraction only happens on factory
boards in SXB2 host mode — not on subsequent flashes or NMI recovery.

Final flash layout (from SXB_eater.bin):
  Bank 0: SXB2 recovery (or empty if no orig)
  Bank 1: empty
  Bank 2: empty
  Bank 3: EhBASIC+Wozmon  (default auto-boot)

Requirements:  pip install pyserial
Usage:
  python3 bootstrap_flash.py <port> <SXB_eater.bin>
"""

import sys
import time
import serial

# SXB2 protocol
CMD_EXEC    = 0x06
CMD_WRITE   = 0x07
MAGIC_ACK   = 0xCC

# VIA2 serial
VIA2_ORB  = 0x7FE0
VIA2_ORA  = 0x7FE1
VIA2_DDRB = 0x7FE2
VIA2_DDRA = 0x7FE3
VIA2_PCR  = 0x7FEC

# SST39SF010A unlock addresses (valid when any bank active)
UNLOCK1 = 0xD555
UNLOCK2 = 0xAAAA

# Bank PCR values
PCR = {0: 0xCC, 1: 0xCE, 2: 0xEC, 3: 0xEE}

# Wire order in which build_flash_reader() streams bank data back to the
# host.  The stub reads bank 3 BEFORE any PCR write to avoid a hardware
# aliasing artefact where the first ~160 bytes after a $EC→$EE transition
# return RAM at the stub's address instead of flash data.  Callers MUST
# reorder the received stream into canonical bank0..bank3 layout.
READER_STREAM_ORDER = (3, 0, 1, 2)


def reorder_reader_stream(stream):
    """
    Reorder bytes received from build_flash_reader() (wire order =
    READER_STREAM_ORDER) into the canonical bank0||bank1||bank2||bank3
    file layout that build_rom.py and every other consumer expects.
    """
    if len(stream) != 131072:
        raise ValueError(f"expected 131072 bytes, got {len(stream)}")
    out = bytearray(131072)
    for wire_idx, bank in enumerate(READER_STREAM_ORDER):
        src = wire_idx * 0x8000
        dst = bank * 0x8000
        out[dst:dst+0x8000] = stream[src:src+0x8000]
    return bytes(out)


# Flash writer base address in RAM
WRITER_BASE = 0x0800


def build_flash_writer():
    """
    Build monolithic 65C02 flash writer that runs from RAM at $1000.

    Protocol after exec:
      Board sends 'R' (ready)
      Host sends 131072 raw bytes (full 128KB image)
      Board programs all 4 banks sequentially
      Board sends 'D' (done) then resets

    Bank order: 0,1,2,3 — host sends them in that order.
    Each bank is 32768 bytes = 8 sectors of 4096 bytes.
    """
    code = bytearray()
    labels = {}
    fixups = []

    def b(*args): code.extend(args)
    def pc(): return WRITER_BASE + len(code)
    def label(name): labels[name] = len(code)

    def bne(name):
        fixups.append((len(code)+1, name, len(code)+2, 'rel'))
        b(0xD0, 0x00)
    def beq(name):
        fixups.append((len(code)+1, name, len(code)+2, 'rel'))
        b(0xF0, 0x00)
    def jmp(name):
        fixups.append((len(code)+1, name, None, 'abs'))
        b(0x4C, 0x00, 0x00)
    def jsr(name):
        fixups.append((len(code)+1, name, None, 'abs'))
        b(0x20, 0x00, 0x00)

    # ZP variables (avoid SXB2 ZP $02-$10)
    PTR_LO   = 0x20
    PTR_HI   = 0x21
    SECT_CNT = 0x22
    BC_LO    = 0x23
    BC_HI    = 0x24
    BANK_CNT = 0x25

    # ── Entry ──────────────────────────────────────────────────────────────
    label('start')
    b(0x78)                      # SEI
    b(0xA2, 0x00)                # LDX #0 (keep X=0 throughout)

    # VIA2 init
    b(0xA9, 0x0C); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xA9, 0x0C); b(0x8D, VIA2_DDRB&0xFF, VIA2_DDRB>>8)
    b(0x64, VIA2_DDRA&0xFF)                # STZ VIA2_DDRA (65C02)

    # Send 'R' ready signal
    b(0xA9, ord('R')); jsr('uart_tx')

    # Init bank counter
    b(0xA9, 0x00); b(0x85, BANK_CNT)

    # ── Bank loop ──────────────────────────────────────────────────────────
    label('bank_loop')

    # Select bank: load PCR from table[bank*2]
    b(0xA5, BANK_CNT); b(0x0A); b(0xAA)   # LDA bank, ASL, TAX
    b(0xBD, 0x00, 0x00)                    # LDA pcr_table,X (patch below)
    pcr_ref = len(code) - 2
    b(0x8D, VIA2_PCR&0xFF, VIA2_PCR>>8)
    b(0xA2, 0x00)                           # LDX #0 (restore X=0)

    # Init ptr = $8000, sect_cnt = 8
    b(0xA9, 0x00); b(0x85, PTR_LO)
    b(0xA9, 0x80); b(0x85, PTR_HI)
    b(0xA9, 0x08); b(0x85, SECT_CNT)

    # ── Sector loop ────────────────────────────────────────────────────────
    label('sector_loop')

    # Sector erase
    b(0xA9, 0xAA); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0x55); b(0x8D, UNLOCK2&0xFF, UNLOCK2>>8)
    b(0xA9, 0x80); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0xAA); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0x55); b(0x8D, UNLOCK2&0xFF, UNLOCK2>>8)
    b(0xA9, 0x30); b(0x81, PTR_LO)         # STA (PTR,X)

    # Poll DQ7 (erase: DQ7=0 until done, then DQ7=1)
    label('erase_poll')
    b(0xA1, PTR_LO)                         # LDA (PTR,X)
    b(0x29, 0x80)
    beq('erase_poll')

    # Init byte counter = 4096 ($1000)
    b(0xA9, 0x00); b(0x85, BC_LO)
    b(0xA9, 0x10); b(0x85, BC_HI)

    # ── Byte loop ──────────────────────────────────────────────────────────
    label('byte_loop')

    # Receive byte
    jsr('uart_rx')                          # returns byte in A

    # Byte program
    b(0xA8)                                 # TAY (save)
    b(0xA9, 0xAA); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0x55); b(0x8D, UNLOCK2&0xFF, UNLOCK2>>8)
    b(0xA9, 0xA0); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0x98)                                 # TYA (restore)
    b(0x81, PTR_LO)                         # STA (PTR,X)

    # 40us delay (320 cycles @ 8MHz)
    b(0xA9, 0x40)
    label('delay')
    b(0x3A)                                 # DEC A (65C02)
    bne('delay')

    # Advance pointer
    b(0xE6, PTR_LO)
    b(0xD0, 0x02)                           # BNE +2
    b(0xE6, PTR_HI)

    # Dec byte counter
    label('dec_bc')
    b(0xA5, BC_LO); b(0x3A); b(0x85, BC_LO)  # DEC BC_LO
    bne('byte_loop')
    b(0xA5, BC_HI); b(0x3A); b(0x85, BC_HI)  # DEC BC_HI
    bne('byte_loop')

    # Dec sector counter
    b(0xC6, SECT_CNT)
    bne('sector_loop')

    # Advance bank
    b(0xE6, BANK_CNT)
    b(0xA5, BANK_CNT); b(0xC9, 0x04)
    bne('bank_loop')

    # Done — send 'D', then jump directly to the wozmon entry point at $8004.
    # $8004 always holds "JMP wozmon_RESET" (placed there by build_rom.py).
    # We do NOT use JMP ($FFFC) here because on a warm software reset the RESET
    # vector points to the WDC init stubs, which assume a cold-boot VIA2 state
    # and glitch the FT245 USB connection, causing WAIT_TX_READY to hang.
    b(0xA9, ord('D')); jsr('uart_tx')
    b(0x4C, 0x04, 0x80)                    # JMP $8004  (-> wozmon_RESET, skip WDC stubs)

    # ── uart_tx ────────────────────────────────────────────────────────────
    label('uart_tx')
    b(0x48)
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    b(0x68); b(0x48)
    b(0x8D, VIA2_ORA&0xFF, VIA2_ORA>>8)
    label('tx_wait')
    b(0xA9, 0x01); b(0x2C, VIA2_ORB&0xFF, VIA2_ORB>>8)
    bne('tx_wait')
    b(0x2C, VIA2_ORB&0xFF, VIA2_ORB>>8)  # BIT VIA2_ORB (filter glitches)
    bne('tx_wait')
    # WR strobe: TSB bit 2
    b(0xAD, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x09, 0x04); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xA9, 0xFF); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    # TRB bit 2 (WR strobe low)
    b(0xAD, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x29, 0xFB); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    b(0x68); b(0x60)

    # ── uart_rx ────────────────────────────────────────────────────────────
    label('uart_rx')
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    label('rx_wait')
    b(0xA9, 0x02); b(0x2C, VIA2_ORB&0xFF, VIA2_ORB>>8)
    bne('rx_wait')
    b(0xAD, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x29, 0xF7); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xEA); b(0xEA)
    b(0xAD, VIA2_ORA&0xFF, VIA2_ORA>>8)
    b(0x48)
    b(0xAD, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x09, 0x08); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x68); b(0x60)

    # ── PCR table ──────────────────────────────────────────────────────────
    label('pcr_table')
    pcr_table_abs = WRITER_BASE + len(code)
    for bank in range(4):
        b(PCR[bank], PCR[bank])  # two copies each (for ASL*index trick)

    # Patch PCR table reference
    code[pcr_ref]   = pcr_table_abs & 0xFF
    code[pcr_ref+1] = pcr_table_abs >> 8

    # Resolve fixups
    for off, name, rel_base, kind in fixups:
        target_abs = WRITER_BASE + labels[name]
        if kind == 'abs':
            code[off]   = target_abs & 0xFF
            code[off+1] = target_abs >> 8
        else:
            code[off] = (target_abs - (WRITER_BASE + rel_base)) & 0xFF

    return bytes(code)


def open_port(port):
    s = serial.Serial(port, 115200, timeout=3)
    time.sleep(0.1)
    s.reset_input_buffer()
    return s


def _drain(s, max_total=0.3):
    """Discard any pending RX bytes. Bounded by max_total seconds."""
    saved = s.timeout
    s.timeout = 0.05
    deadline = time.time() + max_total
    try:
        while time.time() < deadline:
            chunk = s.read(64)
            if not chunk:
                break
    finally:
        s.timeout = saved


def wait_wozmon_ready(s, timeout=10.0):
    """
    Wait for wozmon to be actively servicing the FT245 RX FIFO.

    On cold boot wozmon spins in a 5s TXE-wait loop before printing the
    backslash prompt; during that window any bytes the host sends pile
    up unread in the FT245 host->device FIFO.  If the user presses NMI
    while a backlog exists, the handler ACKs the first $A5 it sees
    (good) but its strict 255-byte recv loop then consumes the leftover
    backlog as the writer's first bytes (bad -> 'no R from writer').

    Strategy: send $7F (DEL) every 200 ms.  Wozmon's CHRIN echoes each
    char it processes.  When echoes start arriving back, wozmon is
    online and draining the FIFO in real time; subsequent NMI press
    finds an empty FIFO and the handler's recv loop only sees the
    writer bytes we send.

    Returns True once at least one echo has been observed (and we then
    drain the resulting echo backlog).  Returns False on timeout.
    """
    deadline = time.time() + timeout
    saved = s.timeout
    s.timeout = 0.2
    s.reset_input_buffer()
    try:
        while time.time() < deadline:
            s.write(b'\x7f')
            s.flush()
            if s.read(1):
                # Wozmon is alive; let it catch up on any in-flight chars
                # we sent earlier, then drain its echoes.
                time.sleep(0.3)
                _drain(s, max_total=0.5)
                return True
    finally:
        s.timeout = saved
    return False


def sxb2_handshake(s, initial=False, attempts=None):
    """
    initial=True  (factory mode): send $55/$AA, wait for $CC ACK
    initial=False (NMI mode):     send $A5, wait for $01 ACK
    """
    saved_timeout = s.timeout
    try:
        if not initial:
            # NMI mode: send $A5, wait for $01
            n = 60 if attempts is None else attempts
            s.timeout = 0.3
            for _ in range(n):
                s.write(bytes([0xA5]))
                s.flush()
                resp = s.read(1)
                if resp == b'\x01':
                    return True
            return False
        else:
            # Factory SXB2 mode: $55/$AA -> $CC
            # SXB2 responds in <1ms; use a short timeout so probing
            # against a non-SXB2 board (NMI mode) doesn't take 30s.
            n = 30 if attempts is None else attempts
            s.timeout = 0.10
            for _ in range(n):
                s.reset_input_buffer()
                s.write(bytes([0x55, 0xAA]))
                s.flush()
                resp = s.read(1)
                if resp == bytes([MAGIC_ACK]):
                    return True
            return False
    finally:
        s.timeout = saved_timeout


def detect_board_state(s):
    """
    Probe board to decide which handshake to use.
    Returns one of:
      'factory'   - SXB2 host mode answers $55/$AA with $CC
      'nmi_armed' - user already pressed NMI; handler answered $A5 with $01
      'nmi'       - no response; caller must instruct user to press NMI

    The probe is non-destructive: $55/$AA into a running wozmon just
    lands as garbage in its input buffer (no $CC reply); $A5 likewise.

    Total worst-case probe time is ~1.5s (vs ~30s previously) so users
    don't sit waiting if they pressed NMI early or are about to.
    """
    # 1) Check if user already pressed NMI (handler is sitting in @sync_wait
    #    waiting for $A5; sending $A5 produces an immediate $01 ACK).
    saved = s.timeout
    s.timeout = 0.3
    try:
        s.reset_input_buffer()
        s.write(bytes([0xA5]))
        s.flush()
        if s.read(1) == b'\x01':
            return 'nmi_armed'
    finally:
        s.timeout = saved

    # 2) Try SXB2 factory host mode (fast: ~10 * 100ms = 1s max).
    if sxb2_handshake(s, initial=True, attempts=10):
        return 'factory'

    # 3) Nothing answered — wozmon must be running; NMI press required.
    return 'nmi'


def sxb2_write_mem(s, data, initial=False, addr=WRITER_BASE):
    """Upload *data* to RAM at *addr* via SXB2 CMD $07 (default $0800)."""
    if not sxb2_handshake(s, initial=initial):
        raise RuntimeError("SXB2 handshake failed")
    n = len(data)
    s.write(bytes([CMD_WRITE, addr & 0xFF, (addr >> 8) & 0xFF, 0x00,
                   n & 0xFF, (n >> 8) & 0xFF, 0x00]))
    s.write(data)
    s.flush()
    time.sleep(0.05 + n * 0.0001)


def sxb2_exec(s, addr, initial=True):
    """Execute at addr via SXB2 CMD $06.

    The SXB2 factory firmware re-enters its $55/$AA -> $CC handshake state
    after every completed command, so EXEC (like WRITE) needs initial=True
    when chained after a CMD_WRITE in factory bootstrap mode.
    """
    if not sxb2_handshake(s, initial=initial):
        raise RuntimeError("SXB2 handshake failed")
    s.write(bytes([CMD_EXEC, addr & 0xFF, (addr >> 8) & 0xFF, 0x00]))
    s.flush()


def sxb2_upload(s, data, addr, initial=False):
    """Upload data to RAM and execute. Returns True on success, False on error."""
    try:
        sxb2_write_mem(s, data, initial=initial)
        sxb2_exec(s, addr, initial=True)
        return True
    except Exception as e:
        print(f"    Upload/exec error: {e}")
        return False


def sxb2_cmd_exec(s, addr):
    """Execute at addr and return True on success, False on error."""
    try:
        sxb2_exec(s, addr, initial=True)
        return True
    except Exception as e:
        print(f"    Exec error: {e}")
        return False


def nmi_upload_and_arm(s, writer, already_armed=False, max_attempts=4):
    """
    Robust NMI-mode upload of the 255-byte writer. Retries the entire
    handshake+upload cycle if 'R' is not received (e.g., user pressed
    NMI again mid-upload, restarting the bank-0 NMI handler).

    Returns True if writer is running and has sent 'R', else False.

    Protocol per attempt:
      1. Drain stale RX (clears stray $01 ACKs from extra NMI presses).
      2. (Re)handshake: send $A5 until $01 ACK seen.
      3. Drain again (extra $A5/ACK pairs from racing).
      4. Send 255-byte padded writer.
      5. Read 'R' with bounded timeout. If we get $01, that's another
         NMI press -- retry from step 1. If timeout, the user probably
         hasn't pressed NMI yet; retry.
    """
    assert len(writer) <= 255, f"Writer too large: {len(writer)}"
    padded = (writer + bytes(255))[:255]

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            print(f"  Attempt {attempt}/{max_attempts}: re-arming NMI handler...")

        # 1) Drain any stale ACKs / NMI bytes in flight
        _drain(s, max_total=0.3)

        # 2) Handshake (skip on first iteration if caller already saw $01)
        if attempt == 1 and already_armed:
            print("  NMI handler already armed (detected during probe).")
        else:
            if attempt == 1:
                print("  Press the NMI button on the board now...")
            if not sxb2_handshake(s, initial=False,
                                  attempts=60 if attempt == 1 else 20):
                if attempt == max_attempts:
                    return False
                continue
            print("  Handshake OK!")

        # 3) Drain leftover ACKs (e.g., user pressed NMI multiple times,
        #    or our handshake loop sent more $A5 than needed)
        _drain(s, max_total=0.2)

        # 4) Send writer
        print(f"  Uploading {len(writer)} bytes to ${WRITER_BASE:04x}...")
        s.write(padded)
        s.flush()

        # 5) Wait for 'R' from the writer
        saved = s.timeout
        s.timeout = 2.0
        try:
            r = s.read(1)
        finally:
            s.timeout = saved

        if r == b'R':
            return True
        if r == b'\x01':
            # Extra NMI press re-armed the handler mid-upload; the writer
            # bytes were eaten by @sync_wait. Retry whole cycle.
            print("  Got stray $01 ACK (likely a second NMI press). Retrying.")
            continue
        if r == b'':
            print("  No 'R' from writer; will retry handshake+upload.")
            continue
        print(f"  Unexpected byte {r!r}; will retry.")
        continue

    return False


def build_flash_reader(base=None):
    """
    Build a small 65C02 flash reader that streams the full 128KB of flash
    (all four 32KB banks) over serial.  Runs from RAM at *base* (default
    WRITER_BASE = $0800).  *base* is exposed so the dump tool can relocate
    the stub to test for RAM-aliasing artefacts when bank 3 is selected.

    For each bank the reader writes the matching VIA2 PCR value to swap the
    flash A15/A16 lines, then streams CPU $8000-$FFFF.  Banks are sent in
    order 0,1,2,3 so the resulting file is a drop-in for build_rom.py
    (which slices bank 3 from offset $18000).

    Protocol:
      1. Sends 'R' (ready)
      2. Streams exactly 131072 bytes in WIRE ORDER bank3 || bank0 || bank1 || bank2
         (bank 3 first, with no preceding PCR write — see READER_STREAM_ORDER
         and the "Bank 3 first" comment block below for why).  Callers MUST
         reorder the stream into the canonical bank0..bank3 layout before
         saving — see reorder_reader_stream().
      3. Restores PCR to $EE (bank 3 visible) so RTS lands back in the
         SXB2 host-mode firmware that originally JSR'd us.
      4. Sends 'D' (done) and RTS
    """
    if base is None:
        base = WRITER_BASE
    code = bytearray()
    labels = {}
    fixups = []

    def b(*args): code.extend(args)
    def label(name): labels[name] = len(code)
    def bne(name):
        fixups.append((len(code)+1, name, len(code)+2, 'rel'))
        b(0xD0, 0x00)
    def jsr(name):
        fixups.append((len(code)+1, name, None, 'abs'))
        b(0x20, 0x00, 0x00)

    PTR_LO   = 0x20
    PTR_HI   = 0x21
    CNT_LO   = 0x22
    CNT_HI   = 0x23
    VIA2_ORB_ADDR  = VIA2_ORB & 0xFF
    VIA2_ORB_PAGE  = VIA2_ORB >> 8
    VIA2_ORA_ADDR  = VIA2_ORA & 0xFF
    VIA2_DDRA_ADDR = VIA2_DDRA & 0xFF
    VIA2_DDRB_ADDR = VIA2_DDRB & 0xFF

    label('start')
    b(0x78)                      # SEI
    b(0xA2, 0x00)                # LDX #0
    b(0xA0, 0x00)                # LDY #0  (required for LDA (zp) on stock 6502; harmless on 65C02)

    # ── VIA2 init (mirror build_flash_writer) ──
    # Idle WR (bit 2) and RD (bit 3) HIGH on ORB before flipping DDRB to output,
    # so we don't glitch a strobe on the FT245. Then make port A an input until
    # the tx routine drives it.
    b(0xA9, 0x0C); b(0x8D, VIA2_ORB_ADDR,  VIA2_ORB_PAGE)  # STA VIA2_ORB  = $0C
    b(0xA9, 0x0C); b(0x8D, VIA2_DDRB_ADDR, VIA2_ORB_PAGE)  # STA VIA2_DDRB = $0C (WR,RD outputs)
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA_ADDR, VIA2_ORB_PAGE)  # STA VIA2_DDRA = $00 (input)

    # Send 'R' ready
    b(0xA9, ord('R'))
    jsr('tx')

    # ── Bank 3 first, with NO PCR write ──
    # When SXB2 host mode JSR'd into our stub via CMD_EXEC, bank 3 was
    # already selected (SXB2 firmware itself lives there).  On this board
    # an explicit PCR write to $EE before the bank-3 read causes the
    # first ~160 bytes read from $8000 to mirror the stub's RAM region
    # ($0800-$089F) instead of returning flash contents.  Symptom is
    # 100% reproducible across passes, and the corrupted bytes are a
    # byte-for-byte copy of the reader stub.  Reading bank 3 BEFORE any
    # PCR transition sidesteps the issue completely.
    jsr('read_bank')

    # ── Then banks 0, 1, 2 with explicit PCR writes ──
    # PCR drives flash A15/A16 via VIA2 CA2/CB2 outputs.  The PCR values
    # come from the project-wide PCR{} table at the top of this file.
    # Bank-switching INTO 0/1/2 has not exhibited the aliasing artefact.
    for bank in (0, 1, 2):
        b(0xA9, PCR[bank])                              # LDA #pcr_val
        b(0x8D, VIA2_PCR & 0xFF, VIA2_PCR >> 8)         # STA VIA2_PCR
        jsr('read_bank')

    # Restore PCR to bank 3 so RTS lands back in the original SXB2 host-mode
    # firmware (which lives in bank 3 ROM and called us via sxb2_exec).
    b(0xA9, PCR[3])
    b(0x8D, VIA2_PCR & 0xFF, VIA2_PCR >> 8)

    # Send 'D' done
    b(0xA9, ord('D'))
    jsr('tx')
    b(0x60)                            # RTS

    # ── read_bank: stream $8000-$FFFF (32KB) of currently-visible bank ──
    label('read_bank')

    # ── Flash software reset before reading ──
    # The SST39SF010A enters several extended modes (Software-ID,
    # sector-erase-suspend, byte-program-busy) in which reads return
    # chip-internal status instead of flash contents.  SXB2's
    # CMD_WRITE/CMD_EXEC handoff appears to leave the chip in such a
    # mode for bank 3 specifically (symptom: first len(stub) bytes of
    # the bank-3 read return the stub's RAM region byte-for-byte,
    # 100% reproducible across passes, scaling exactly with stub size).
    # The Reset command — write $F0 to any address with the chip
    # selected — exits any extended mode unconditionally.  Cheap and
    # idempotent: a no-op when the chip is already in normal read mode.
    b(0xA9, 0xF0)                      # LDA #$F0
    b(0x8D, 0x00, 0x80)                # STA $8000  (flash reset)

    # 256 dummy reads to let the reset propagate and absorb any residual
    # stale-bus state.  ~1ms; harmless if not needed.
    b(0xA2, 0x00)                      # LDX #0
    label('warmup_loop')
    b(0xBD, 0x00, 0x80)                # LDA $8000,X
    b(0xCA)                            # DEX
    bne('warmup_loop')                 # 256 iterations

    b(0xA9, 0x00); b(0x85, PTR_LO)     # LDA #$00; STA PTR_LO
    b(0xA9, 0x80); b(0x85, PTR_HI)     # LDA #$80; STA PTR_HI
    b(0xA9, 0x00); b(0x85, CNT_LO)     # LDA #$00; STA CNT_LO  (32768 = $8000)
    b(0xA9, 0x80); b(0x85, CNT_HI)     # LDA #$80; STA CNT_HI

    label('read_loop')
    # Read byte at (PTR_LO,PTR_HI) using 65C02 indirect-zp ($B2)
    b(0xB2, PTR_LO)                    # LDA (PTR_LO)
    jsr('tx')

    # Increment pointer
    b(0xE6, PTR_LO)                    # INC PTR_LO
    b(0xD0, 0x03)                      # BNE +3
    b(0xE6, PTR_HI)                    # INC PTR_HI
    b(0xEA)                            # NOP

    # Decrement 16-bit counter (only DEC CNT_HI when CNT_LO underflows to 0).
    # BNE must skip past LDA CNT_HI (2) + DEC A (1) + STA CNT_HI (2) = 5 bytes.
    b(0xA5, CNT_LO); b(0x3A)           # LDA CNT_LO; DEC
    b(0x85, CNT_LO)                    # STA CNT_LO
    b(0xD0, 0x05)                      # BNE +5  (skip the dec-HI block)
    b(0xA5, CNT_HI); b(0x3A)           # LDA CNT_HI; DEC
    b(0x85, CNT_HI)                    # STA CNT_HI

    # If count != 0, loop
    b(0xA5, CNT_LO); b(0x05, CNT_HI)   # LDA CNT_LO; ORA CNT_HI
    bne('read_loop')

    b(0x60)                            # RTS
    
    # ── uart_tx (copied from build_flash_writer) ──
    label('tx')
    b(0x48)                            # PHA
    b(0xA9, 0x00)
    b(0x8D, VIA2_DDRA_ADDR, VIA2_ORB_PAGE)  # STA VIA2_DDRA
    b(0x68)                            # PLA
    b(0x48)                            # PHA
    b(0x8D, VIA2_ORA_ADDR, VIA2_ORB_PAGE)   # STA VIA2_ORA
    label('tx_wait')
    b(0xA9, 0x01)
    b(0x2C, VIA2_ORB_ADDR, VIA2_ORB_PAGE)   # BIT VIA2_ORB
    bne('tx_wait')
    b(0x2C, VIA2_ORB_ADDR, VIA2_ORB_PAGE)   # BIT VIA2_ORB (filter glitches)
    bne('tx_wait')
    b(0xA9, 0xFF)
    b(0x8D, VIA2_DDRA_ADDR, VIA2_ORB_PAGE)  # STA VIA2_DDRA
    b(0xA9, 0x04)
    b(0x0C, VIA2_ORB_ADDR, VIA2_ORB_PAGE)   # TSB VIA2_ORB
    b(0xA9, 0x04)
    b(0x1C, VIA2_ORB_ADDR, VIA2_ORB_PAGE)   # TRB VIA2_ORB
    b(0xA9, 0x00)
    b(0x8D, VIA2_DDRA_ADDR, VIA2_ORB_PAGE)  # STA VIA2_DDRA
    b(0x68)                            # PLA
    b(0x60)                            # RTS
    
    # Apply fixups
    for off, name, rel_base, kind in fixups:
        target_abs = base + labels[name]
        if kind == 'abs':
            code[off]   = target_abs & 0xFF
            code[off+1] = target_abs >> 8
        else:
            code[off] = (target_abs - (base + rel_base)) & 0xFF

    return bytes(code)


def extract_full_flash(s, prompt_filename='SXB_orig.bin'):
    """
    Upload and execute a flash reader to extract the full 128KB of flash
    (all 4 banks) from the board.  Returns the 131072 bytes, or None if
    the user declines or an error occurs.  Also prompts to save to file.

    Layout of the returned bytes matches what build_rom.py expects:
      $00000-$07FFF  bank 0
      $08000-$0FFFF  bank 1
      $10000-$17FFF  bank 2
      $18000-$1FFFF  bank 3  (factory SXB2 firmware on a fresh board)
    """
    print()
    print("─" * 55)
    print("Factory board detected. Bank 3 contains original SXB2 firmware.")
    print("─" * 55)
    print()
    print("Would you like to save a backup of the full 128KB flash?")
    print("(Recommended for future builds without a chip reader)")
    print()

    # Prompt with suggested filename
    response = input(f"Save to file [{prompt_filename}]? (y/n): ").strip().lower()
    if response not in ('y', 'yes', ''):
        print("Skipping backup.")
        return None

    # Get filename
    filename = input(f"Filename [{prompt_filename}]: ").strip()
    if not filename:
        filename = prompt_filename

    # Check if file exists
    import os
    if os.path.exists(filename):
        response = input(f"{filename} exists. Overwrite? (y/n): ").strip().lower()
        if response not in ('y', 'yes'):
            print("Skipping backup.")
            return None

    print()
    print("Building flash reader...")
    reader = build_flash_reader()
    print(f"  {len(reader)} bytes at ${WRITER_BASE:04x}")

    print("Uploading flash reader...")
    try:
        sxb2_write_mem(s, reader, initial=True)
    except Exception as e:
        print(f"  ERROR: upload failed: {e}")
        return None
    print("  Upload OK")

    print("Executing flash reader...")
    s.reset_input_buffer()
    try:
        sxb2_exec(s, WRITER_BASE, initial=True)
    except Exception as e:
        print(f"  ERROR: exec failed: {e}")
        return None

    # Wait for 'R' (ready)
    s.timeout = 2.0
    resp = s.read(1)
    if resp != b'R':
        print(f"  ERROR: expected 'R', got {resp!r}")
        return None

    TOTAL = 131072  # 4 banks × 32KB
    print(f"  Receiving full flash... (128KB)", end='', flush=True)
    flash = bytearray()
    s.timeout = 0.5

    # Read exactly 131072 bytes
    last_dot_at = 0
    while len(flash) < TOTAL:
        chunk = s.read(TOTAL - len(flash))
        if not chunk:
            print(f"\n  ERROR: timeout after {len(flash)} bytes")
            return None
        flash.extend(chunk)
        # One dot per 8KB so the user sees progress across all 4 banks
        while last_dot_at + 8192 <= len(flash):
            print('.', end='', flush=True)
            last_dot_at += 8192

    # Wait for 'D' (done)
    resp = s.read(1)
    if resp != b'D':
        print(f"\n  WARNING: expected 'D', got {resp!r}")

    print(f"\n  Received {len(flash)} bytes")

    # Reorder wire-order stream (READER_STREAM_ORDER = bank3,0,1,2) into
    # canonical bank0||bank1||bank2||bank3 layout that build_rom.py wants.
    flash = reorder_reader_stream(bytes(flash))

    # Save to file
    print(f"Saving to {filename}...")
    with open(filename, 'wb') as f:
        f.write(flash)
    print(f"  Saved {len(flash)} bytes")

    return bytes(flash)


# Backward-compat alias for any external caller that imported the old name.
extract_bank3 = extract_full_flash


def bootstrap(port, image_path, mode='auto'):
    print("=" * 55)
    print("  SXB Bootstrap Flasher")
    print("=" * 55)
    print()

    print(f"Loading {image_path}...")
    with open(image_path, 'rb') as f:
        image = f.read()
    if len(image) != 131072:
        print(f"ERROR: Expected 131072 bytes, got {len(image)}")
        sys.exit(1)

    print(f"  {len(image)} bytes")
    for bank in range(4):
        base = bank * 0x8000
        sig = image[base:base+4]
        reset = image[base+0x7FFC] | (image[base+0x7FFD]<<8)
        print(f"  Bank {bank}: {image[base:base+8].hex()}  RESET=${reset:04x}", end='')
        if sig == b'WDC\x00':
            jmp = image[base+5] | (image[base+6]<<8)
            print(f"  JMP ${jmp:04x}", end='')
        print()

    print()
    print("Building flash writer...")
    writer = build_flash_writer()
    print(f"  {len(writer)} bytes at ${WRITER_BASE:04x}")

    print()
    print(f"Opening {port}...")
    s = open_port(port)

    # Probe the BOARD STATE (not the image) to decide protocol.
    # - Factory SXB_orig.bin loaded:  SXB2 host mode answers $55/$AA -> $CC
    # - Already flashed SXB_eater:    no response; user must press NMI
    # - User pressed NMI early:       handler already armed; ACKs $A5 -> $01
    if mode == 'auto':
        print("Probing board state...")
        state = detect_board_state(s)
        print(f"  Detected: {state} mode")
    else:
        state = mode
        print(f"Forced mode: {state}")

    nmi_mode = state in ('nmi', 'nmi_armed')
    already_armed = (state == 'nmi_armed')

    if nmi_mode:
        print()
        if already_armed:
            print("NMI handler already responded (early press detected).")
        else:
            print("Board is not in SXB2 host mode.")
            # CRITICAL: wait until wozmon is actively servicing the FT245 RX
            # FIFO before letting the user press NMI.  On cold boot wozmon
            # spins ~5s in WAIT_TX_READY and any handshake bytes we send
            # accumulate in the FT245 host->device FIFO; if NMI fires while
            # the backlog exists, the handler's recv loop consumes the
            # leftover bytes as the writer's first bytes and corruption
            # results in 'no R from writer'.
            print()
            print("Waiting for wozmon to come online (cold-boot USB"
                  " enumeration may take a few seconds)...")
            if wait_wozmon_ready(s, timeout=10.0):
                print("  Wozmon is responsive — FT245 RX FIFO is being drained.")
            else:
                print("  Warning: no echo from wozmon within 10s; proceeding"
                      " anyway. If NMI handshake fails, power-cycle the board"
                      " and rerun.")
        print()
        print("Uploading flash writer to RAM (with auto-retry)...")
        if not nmi_upload_and_arm(s, writer, already_armed=already_armed):
            print("ERROR: Could not arm NMI handler + upload writer.")
            print("  - Make sure no other program is using the serial port.")
            print("  - Press NMI exactly ONCE when prompted, then wait.")
            print("  - If wozmon is running but unresponsive, power-cycle"
                  " the board, wait for the wozmon prompt to appear, then"
                  " rerun this script.")
            sys.exit(1)
        print("  Writer ready!")
    else:
        # Factory handshake already succeeded during probe; redo for clean state
        if mode != 'auto':
            print("Waiting for SXB2 handshake...")
            if not sxb2_handshake(s, initial=True):
                print("ERROR: No SXB2 response.")
                sys.exit(1)
        print("  Handshake OK!")
        print()
        
        # Offer to dump the entire 128KB flash (factory firmware) on first
        # flash only.  build_rom.py wants a 128KB image; the dump matches.
        extract_full_flash(s, prompt_filename='SXB_orig.bin')
        
        print()
        print("Uploading flash writer to RAM...")
        assert len(writer) <= 512, f"Writer too large: {len(writer)}"
        print(f"  Uploading {len(writer)} bytes to ${WRITER_BASE:04x}...")
        sxb2_write_mem(s, writer, initial=True)
        print("  Upload complete")
        print("Executing flash writer...")
        sxb2_exec(s, WRITER_BASE)
        time.sleep(0.5)
        # Wait for 'R' (ready)
        print("Waiting for writer ready signal ('R')...")
        r = s.read(1)
        if r != b'R':
            print(f"ERROR: Expected 'R', got {r!r}")
            sys.exit(1)
        print("  Writer ready!")

    print()
    total = len(image)
    print(f"Sending {total} bytes...")
    print(f"  Bank order: 0,1,2,3")
    print(f"  ~{total*10//115200 + total//256*25//1000 + 8}s estimated")
    print()

    input("Press Enter to begin (Ctrl+C to abort)...")
    print()

    t0 = time.time()
    chunk = 256
    for i in range(0, total, chunk):
        bank = i // 0x8000
        offset = i % 0x8000
        addr = 0x8000 + offset
        pct = i * 100 // total
        print(f"\r  {pct:3d}%  bank {bank}  ${addr:04x}  {i//1024:3d}KB/{total//1024}KB",
              end='', flush=True)
        s.write(image[i:i+chunk])
        s.flush()
        # Small throttle to avoid overwhelming the board
        # Board programs at ~40us/byte, 256 bytes = ~10ms
        # Serial at 115200 = 256 bytes in ~22ms - serial is the bottleneck
        # No extra delay needed

    elapsed = time.time() - t0
    print(f"\r  100%  {total//1024}KB sent in {elapsed:.1f}s{' '*20}")
    print()

    # Wait for 'D' (done)
    print("Waiting for completion signal ('D')...")
    s.timeout = 120  # give it time to finish programming
    d = s.read(1)
    total_elapsed = time.time() - t0
    if d == b'D':
        print(f"  Done! Total time: {total_elapsed:.1f}s")
    else:
        print(f"  WARNING: Expected 'D', got {d!r}")

    s.close()
    print()
    print("=" * 55)
    print("  Flash complete! Board is resetting...")
    print()
    print("  Boot: LED diamond -> wozmon '\\' prompt")
    print("  A0B9R  -> MS BASIC (check lbl file to be sure)")
    print("  B0     -> WDCMON (if you have SXB_ORIG.bin)")
    print("  B1/B2  -> user ROM")
    print("  B3     -> reload wozmon")
    print("=" * 55)


def reflash_bank(port, image_path, bank, s=None):
    """Reflash a single bank. Useful for development iteration."""
    print("=" * 55)
    print(f"  Reflash Bank {bank}")
    print("=" * 55)
    print()

    with open(image_path, 'rb') as f:
        full = f.read()

    if len(full) == 131072:
        bank_image = full[bank*0x8000:(bank+1)*0x8000]
    elif len(full) == 32768 and bank == 3:
        bank_image = full
    else:
        print(f"ERROR: Expected 131072 bytes or 32768 bytes for bank 3")
        sys.exit(1)

    print(f"  Bank {bank}: {bank_image[0:8].hex()}")

    # Build single-bank image: pad others with $FF
    image = bytearray([0xFF] * 131072)
    image[bank*0x8000:(bank+1)*0x8000] = bank_image

    # Build writer that only programs target bank
    writer = build_flash_writer_single_bank(bank)
    print(f"  Writer: {len(writer)} bytes at ${WRITER_BASE:04x}")

    print()
    if s is None:
        print(f"Opening {port}...")
        s = open_port(port)
    print("Waiting for handshake...")
    if not sxb2_handshake(s, initial=True):
        print("ERROR: No response. Make sure board is in WDCMON mode (B0 from wozmon).")
        sys.exit(1)
    print("  Handshake OK!")

    sxb2_write_mem(s, writer, initial=True)
    sxb2_exec(s, WRITER_BASE)
    time.sleep(0.5)

    r = s.read(1)
    if r != b'R':
        print(f"ERROR: Expected 'R', got {r!r}")
        sys.exit(1)
    print("  Writer ready!")

    input("Press Enter to begin (Ctrl+C to abort)...")
    t0 = time.time()
    chunk = 256
    for i in range(0, 32768, chunk):
        pct = i * 100 // 32768
        print(f"\r  {pct:3d}%  ${0x8000+i:04x}", end='', flush=True)
        s.write(bank_image[i:i+chunk])
        s.flush()
    elapsed = time.time() - t0
    print(f"\r  100%  done in {elapsed:.1f}s{' '*20}")

    s.timeout = 60
    d = s.read(1)
    if d == b'D':
        print(f"  Done!")
    else:
        print(f"  WARNING: Expected 'D', got {d!r}")

    s.close()
    print()
    print("=" * 55)
    print(f"  Bank {bank} reflashed! Board resetting...")
    print("=" * 55)


def build_flash_writer_single_bank(target_bank):
    """Flash writer that programs only one bank (32KB = 8 sectors)."""
    # Same as build_flash_writer but bank loop replaced with single bank
    # Reuse build_flash_writer with a wrapper that sends 32KB for target bank
    # and $FF for all others - but actually simpler to just patch the image.
    # The full writer already handles this correctly - we send the full 128KB
    # image with only target bank populated, others filled with $FF.
    # $FF pages skip programming (already erased state).
    # Actually we need a writer that only erases/programs target bank.
    # Simplest: use the full writer but send only 32KB for the target bank
    # by using a single-bank variant.
    # For now just use the full writer - caller sends 32KB repeated as needed.
    # Actually: build_flash_writer programs all 4 banks sequentially.
    # We need one that jumps directly to the target bank.
    return build_flash_writer_for_bank(target_bank)


def build_flash_writer_for_bank(target_bank):
    """
    Flash writer for a single bank. Same as build_flash_writer but
    only programs the target bank. Receives 32768 raw bytes.
    
    SST39SF010A unlock addresses ($D555/$AAAA) are physical addresses
    that only map correctly when bank 0 is active (PCR=$CC).
    For any target bank, we switch to bank 0 for unlocks, then back
    to target bank for the actual erase/program command.
    """
    VIA2_ORB  = 0x7FE0
    VIA2_ORA  = 0x7FE1
    VIA2_DDRB = 0x7FE2
    VIA2_DDRA = 0x7FE3
    VIA2_PCR  = 0x7FEC
    UNLOCK1   = 0xD555   # valid when bank 0 active
    UNLOCK2   = 0xAAAA   # valid when bank 0 active
    PCR_BANK0 = PCR[0]   # always use bank 0 for unlock sequences
    PCR_VAL   = PCR[target_bank]

    PTR_LO   = 0x20
    PTR_HI   = 0x21
    SECT_CNT = 0x22
    BC_LO    = 0x23
    BC_HI    = 0x24

    code = bytearray()
    labels = {}
    fixups = []

    def b(*args): code.extend(args)
    def label(name): labels[name] = len(code)
    def beq(name):
        fixups.append((len(code)+1, name, len(code)+2, 'rel'))
        b(0xF0, 0x00)
    def bne(name):
        fixups.append((len(code)+1, name, len(code)+2, 'rel'))
        b(0xD0, 0x00)
    def jsr(name):
        fixups.append((len(code)+1, name, None, 'abs'))
        b(0x20, 0x00, 0x00)

    label('start')
    b(0x78); b(0xD8); b(0xA2, 0x00)

    # VIA2 init
    b(0xA9, 0x0C); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xA9, 0x0C); b(0x8D, VIA2_DDRB&0xFF, VIA2_DDRB>>8)
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)

    # Send 'R'
    b(0xA9, ord('R')); jsr('uart_tx')

    # Select bank
    b(0xA9, PCR_VAL); b(0x8D, VIA2_PCR&0xFF, VIA2_PCR>>8)
    b(0xA2, 0x00)

    # ptr=$8000, sect_cnt=8
    b(0xA9, 0x00); b(0x85, PTR_LO)
    b(0xA9, 0x80); b(0x85, PTR_HI)
    b(0xA9, 0x08); b(0x85, SECT_CNT)

    label('sector_loop')
    # Unlock: switch to bank 0 for correct $D555/$AAAA mapping
    b(0xA9, PCR_BANK0); b(0x8D, VIA2_PCR&0xFF, VIA2_PCR>>8)
    b(0xA9, 0xAA); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0x55); b(0x8D, UNLOCK2&0xFF, UNLOCK2>>8)
    b(0xA9, 0x80); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0xAA); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0x55); b(0x8D, UNLOCK2&0xFF, UNLOCK2>>8)
    # Switch to target bank for erase command
    b(0xA9, PCR_VAL); b(0x8D, VIA2_PCR&0xFF, VIA2_PCR>>8)
    b(0xA2, 0x00)                # restore X=0
    b(0xA9, 0x30); b(0x81, PTR_LO)

    label('erase_poll')
    b(0xA1, PTR_LO); b(0x29, 0x80); beq('erase_poll')

    b(0xA9, 0x00); b(0x85, BC_LO)
    b(0xA9, 0x10); b(0x85, BC_HI)

    label('byte_loop')
    jsr('uart_rx')
    b(0xA8)
    # Unlock: switch to bank 0 for correct $D555/$AAAA mapping
    b(0xA9, PCR_BANK0); b(0x8D, VIA2_PCR&0xFF, VIA2_PCR>>8)
    b(0xA9, 0xAA); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    b(0xA9, 0x55); b(0x8D, UNLOCK2&0xFF, UNLOCK2>>8)
    b(0xA9, 0xA0); b(0x8D, UNLOCK1&0xFF, UNLOCK1>>8)
    # Switch to target bank for byte program
    b(0xA9, PCR_VAL); b(0x8D, VIA2_PCR&0xFF, VIA2_PCR>>8)
    b(0xA2, 0x00)                # restore X=0
    b(0x98); b(0x81, PTR_LO)

    b(0xA9, 0x40)
    label('delay')
    b(0x3A); bne('delay')

    b(0xE6, PTR_LO); b(0xD0, 0x03); b(0xE6, PTR_HI); b(0xEA)

    b(0xA5, BC_LO); b(0x3A); b(0x85, BC_LO); bne('byte_loop')
    b(0xA5, BC_HI); b(0x3A); b(0x85, BC_HI); bne('byte_loop')
    b(0xC6, SECT_CNT); bne('sector_loop')

    b(0xA9, ord('D')); jsr('uart_tx')
    b(0x4C, 0x04, 0x80)                    # JMP $8004  (-> wozmon_RESET, skip WDC stubs)

    # uart_tx/rx copied from build_flash_writer
    label('uart_tx')
    b(0x48)
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    b(0x68); b(0x48)
    b(0x8D, VIA2_ORA&0xFF, VIA2_ORA>>8)
    label('tx_wait')
    b(0xA9, 0x01); b(0x2C, VIA2_ORB&0xFF, VIA2_ORB>>8)
    bne('tx_wait')
    b(0xA9, 0xFF); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    b(0xA9, 0x04); b(0x0C, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xEA); b(0xEA)
    b(0xA9, 0x04); b(0x1C, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    b(0x68); b(0x60)

    label('uart_rx')
    b(0xA9, 0x00); b(0x8D, VIA2_DDRA&0xFF, VIA2_DDRA>>8)
    label('rx_wait')
    b(0xA9, 0x02); b(0x2C, VIA2_ORB&0xFF, VIA2_ORB>>8)
    bne('rx_wait')
    b(0xAD, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x29, 0xF7); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0xEA); b(0xEA)
    b(0xAD, VIA2_ORA&0xFF, VIA2_ORA>>8)
    b(0x48)
    b(0xAD, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x09, 0x08); b(0x8D, VIA2_ORB&0xFF, VIA2_ORB>>8)
    b(0x68); b(0x60)

    for off, name, rel_base, kind in fixups:
        target_abs = WRITER_BASE + labels[name]
        if kind == 'abs':
            code[off]   = target_abs & 0xFF
            code[off+1] = target_abs >> 8
        else:
            code[off] = (target_abs - (WRITER_BASE + rel_base)) & 0xFF

    return bytes(code)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(
        description='Bootstrap or reflash W65C02SXB')
    p.add_argument('port', help='Serial port')
    p.add_argument('image', help='SXB_eater.bin (131072 bytes)')
    p.add_argument('--mode', choices=['auto', 'factory', 'nmi'], default='auto',
                   help='Board state: auto-detect (default), factory (SXB2 host '
                        'mode after fresh SXB_orig.bin), or nmi (already running '
                        'SXB_eater wozmon - requires NMI button press)')
    p.add_argument('--bank', type=int, choices=[0,1,2,3],
                   help='Reflash single bank only (requires WDCMON in bank 0)')
    p.add_argument('--from-wozmon', action='store_true',
                   help='Send B0 to wozmon first to switch to WDCMON')
    args = p.parse_args()

    if args.bank is not None:
        if args.from_wozmon:
            print(f"Opening {args.port}...")
            s = open_port(args.port)
            print("Sending B0 to wozmon...")
            s.write(b'B0\r')
            s.flush()
            time.sleep(0.3)
            s.reset_input_buffer()
            reflash_bank(args.port, args.image, args.bank, s=s)
        else:
            reflash_bank(args.port, args.image, args.bank)
    else:
        bootstrap(args.port, args.image, mode=args.mode)
