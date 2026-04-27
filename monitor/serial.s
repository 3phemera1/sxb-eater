; serial.s - VIA2 USB FIFO driver for W65C02SXB bank 1 monitor
;
; All functions use cc65 __fastcall__ calling convention:
;   - Single byte argument comes in A register
;   - 16-bit pointer argument comes in A (lo) / X (hi)
;   - Return value in A (byte) or A/X (16-bit)
;
; The strobe sequences must match the WDC firmware exactly (reverse-
; engineered and documented in docs/wdc_reference/NOTES.md).

.setcpu "65C02"

VIA2_ORB  = $7FE0           ; strobe / status bits
VIA2_ORA  = $7FE1           ; data bus to/from FT245
VIA2_DDRB = $7FE2           ; direction register B
VIA2_DDRA = $7FE3           ; direction register A

; VIA2_ORB bit masks
RX_READY  = $02             ; bit 1: clear = data available
TX_READY  = $01             ; bit 0: clear = ready to send
RD_STROBE = $08             ; bit 3: RD strobe (high = idle)
WR_STROBE = $04             ; bit 2: WR strobe (high = write)

.importzp   ptr1            ; cc65 ZP temp pointer (used by serial_puts)

.export _serial_init
.export _serial_putchar
.export _serial_getchar
.export _serial_puts
.export _serial_putcrlf
.export _serial_puthex8
.export _serial_puthex16

.segment "CODE"

; ── serial_init() ────────────────────────────────────────────────────────────
; Initialise VIA2 for USB FIFO.  Called by crt0 before main(); exposed so
; user code can re-init if needed.
_serial_init:
    lda     #$0C
    sta     VIA2_ORB                ; WR+RD strobes high first
    lda     #$0C
    sta     VIA2_DDRB               ; bits 2,3 = outputs
    stz     VIA2_DDRA               ; port A = input
    rts

; ── serial_putchar(char c) ───────────────────────────────────────────────────
; Transmit one character.  c arrives in A (fastcall).
; Preserves all registers except A (destroyed by VIA2 reads).
_serial_putchar:
    pha                             ; save character
    stz     VIA2_DDRA               ; tristate port A
    sta     VIA2_ORA                ; latch char onto bus
TxWait:
    lda     #TX_READY
    bit     VIA2_ORB                ; test TX ready (bit 0)
    bne     TxWait                  ; wait until clear
    lda     #WR_STROBE
    tsb     VIA2_ORB                ; WR strobe high
    lda     #$FF
    sta     VIA2_DDRA               ; drive port A outputs
    nop
    nop
    lda     #WR_STROBE
    trb     VIA2_ORB                ; WR strobe low
    stz     VIA2_DDRA               ; tristate port A
    pla                             ; restore character
    rts

; ── serial_getchar() ─────────────────────────────────────────────────────────
; Receive one character (blocks until available).  No echo.
; Returns character in A.
_serial_getchar:
    stz     VIA2_DDRA               ; port A = input
RxWait:
    lda     #RX_READY
    bit     VIA2_ORB                ; test RX ready (bit 1)
    bne     RxWait                  ; wait until clear
    lda     #RD_STROBE
    trb     VIA2_ORB                ; RD strobe low
    nop
    nop
    lda     VIA2_ORA                ; read character
    pha                             ; save it
    lda     #RD_STROBE
    tsb     VIA2_ORB                ; RD strobe high
    pla                             ; restore character
    rts                             ; character in A

; ── serial_putcrlf() ─────────────────────────────────────────────────────────
; Print CR + LF.
_serial_putcrlf:
    lda     #$0D
    jsr     _serial_putchar
    lda     #$0A
    jmp     _serial_putchar         ; tail call

; ── serial_puts(const char *s) ───────────────────────────────────────────────
; Print NUL-terminated string.  Pointer arrives in A (lo) / X (hi).
_serial_puts:
    sta     ptr1                    ; store lo
    stx     ptr1+1                  ; store hi
    ldy     #0
@loop:
    lda     (ptr1),y
    beq     @done
    jsr     _serial_putchar
    iny
    bne     @loop
    inc     ptr1+1                  ; handle strings > 255 bytes
    bra     @loop
@done:
    rts

; ── serial_puthex8(uint8_t val) ──────────────────────────────────────────────
; Print val as two uppercase hex digits.  val arrives in A (fastcall).
_serial_puthex8:
    pha                             ; save full byte
    lsr                             ; shift high nibble down
    lsr
    lsr
    lsr
    jsr     @prhex_nib              ; print high nibble
    pla                             ; restore full byte
    ; fall through to print low nibble
@prhex_nib:
    and     #$0F
    ora     #'0'
    cmp     #'9'+1
    bcc     @emit
    adc     #6                      ; 'A'–'F' ('9'+1+6+carry = 'A'+offset)
@emit:
    jmp     _serial_putchar         ; tail call

; ── serial_puthex16(uint16_t val) ────────────────────────────────────────────
; Print val as four uppercase hex digits (high byte first).
; val arrives in A (lo) / X (hi) via fastcall.
_serial_puthex16:
    pha                             ; save lo byte
    txa                             ; A = hi byte
    jsr     _serial_puthex8         ; print hi byte
    pla                             ; restore lo byte
    jmp     _serial_puthex8         ; print lo byte (tail call)
