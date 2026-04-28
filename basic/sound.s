.segment "CODE"
.ifdef EATER

VIA_T1CL = $7FC4    ; T1 counter/latch low  (write: latch low)
VIA_T1CH = $7FC5    ; T1 counter high        (write: starts timer, sets latch high)
VIA_ACR  = $7FCB    ; Auxiliary control register
VIA_DDRB = $7FC2    ; Port B data direction register
VIA_ORB  = $7FC0    ; Port B output register

; ---------------------------------------------------------------------------
; BEEP freq_hz, duration_ms
;
;   freq_hz    : tone frequency in Hz.  Range 62..32767.  0 = silence.
;                T1 latch = 4,000,000 / freq_hz - 2  (8 MHz clock)
;   duration_ms: duration in milliseconds, 0..65535.
;
; Both arguments are always required.  Illegal Quantity if freq 1..61.
; ---------------------------------------------------------------------------
BEEP:
    ; --- Parse arg 1: frequency in Hz → LINNUM ---
    jsr     FRMNUM
    jsr     GETADR

    ; Stash freq on the hardware stack; LINNUM will be overwritten parsing arg 2.
    lda     LINNUM
    pha
    lda     LINNUM+1
    pha

    ; --- Parse arg 2: duration in ms → LINNUM ---
    jsr     CHKCOM
    jsr     FRMNUM
    jsr     GETADR

    ; Save duration (STRNG1 safe now – no further BASIC parsing calls).
    lda     LINNUM
    sta     STRNG1
    lda     LINNUM+1
    sta     STRNG1+1

    ; --- Restore freq from stack → LINNUM ---
    pla
    sta     LINNUM+1
    pla
    sta     LINNUM

    ; --- freq = 0 → silent delay ---
    lda     LINNUM
    ora     LINNUM+1
    beq     @delay_only

    ; --- freq 1..61 → latch overflows 16-bit VIA timer, illegal ---
    lda     LINNUM+1
    bne     @freq_ok            ; freq >= 256, always in range
    lda     LINNUM
    cmp     #62
    bcs     @freq_ok
    jmp     GOIQ                ; freq 1..61 → Illegal Quantity
@freq_ok:

    ; --- Compute T1 latch = 4,000,000 / freq_hz using 24÷16 long division ---
    ;
    ; ZP layout (safe between parser calls):
    ;   Dividend (little-endian, shifted left each iter):
    ;     STRNG2   = d0 ($00, low byte of 4,000,000)
    ;     STRNG2+1 = d1 ($09, mid byte)
    ;     TEMP2    = d2 ($3D, high byte)
    ;   Remainder (16-bit):
    ;     FORPNT   = r0 (low)
    ;     FORPNT+1 = r1 (high)
    ;   Quotient (16-bit, result → VIA T1):
    ;     HIGHDS   = q0 (low → VIA_T1CL)
    ;     HIGHDS+1 = q1 (high → VIA_T1CH)
    ;   Divisor: LINNUM+1:LINNUM (freq_hz, unchanged)
    ;   Duration: STRNG1+1:STRNG1 (untouched during division)

    lda     #$00
    sta     STRNG2              ; d0 = $00
    sta     FORPNT              ; r0 = 0
    sta     FORPNT+1            ; r1 = 0
    sta     HIGHDS              ; q0 = 0
    sta     HIGHDS+1            ; q1 = 0
    lda     #$09
    sta     STRNG2+1            ; d1 = $09
    lda     #$3D
    sta     TEMP2               ; d2 = $3D

    ldx     #24
@div_loop:
    ; Shift 24-bit dividend left; MSB exits as carry into the remainder.
    asl     STRNG2
    rol     STRNG2+1
    rol     TEMP2
    rol     FORPNT              ; carry from dividend MSB enters remainder
    rol     FORPNT+1            ; carry set → 17-bit remainder ≥ 65536 ≥ divisor

    bcs     @div_sub            ; 17-bit overflow: always subtract

    ; 16-bit compare remainder vs divisor
    lda     FORPNT+1
    cmp     LINNUM+1
    bcc     @div_no_sub
    bne     @div_sub
    lda     FORPNT
    cmp     LINNUM
    bcc     @div_no_sub

@div_sub:
    sec
    lda     FORPNT
    sbc     LINNUM
    sta     FORPNT
    lda     FORPNT+1
    sbc     LINNUM+1
    sta     FORPNT+1
    sec                         ; quotient bit = 1
    bcs     @div_shift_q        ; always taken

@div_no_sub:
    clc                         ; quotient bit = 0

@div_shift_q:
    rol     HIGHDS
    rol     HIGHDS+1
    dex
    bne     @div_loop

    ; Subtract 2: latch = 4,000,000 / freq - 2
    sec
    lda     HIGHDS
    sbc     #2
    sta     HIGHDS
    bcs     @latch_ok
    dec     HIGHDS+1
@latch_ok:

    ; --- Start tone: PB7 output, T1 free-run, toggle on reload ---
    lda     VIA_DDRB
    ora     #$80
    sta     VIA_DDRB

    lda     HIGHDS
    sta     VIA_T1CL            ; latch low (write to T1C-L stores latch low)
    lda     HIGHDS+1
    sta     VIA_T1CH            ; latch high + start timer (transfers latch → counter)

    lda     VIA_ACR
    ora     #$C0                ; bits 7:6 = 11 → T1 free-run, PB7 toggle
    sta     VIA_ACR

@delay_only:
    ; --- 16-bit millisecond delay ---
    ; STRNG1+1:STRNG1 = remaining ms.  ~8016 cycles ≈ 1.002 ms/iteration at 8 MHz.
    lda     STRNG1
    ora     STRNG1+1
    beq     @stop_tone          ; duration 0 → skip delay, still stop tone

@ms_loop:
    ldy     #195                ; inner loop calibrated for ~7996 cycles ≈ 0.999 ms
@ms_inner:
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop                         ; 18 NOPs = 36 cycles per inner iteration
    dey
    bne     @ms_inner           ; inner total: 2 + 194×41 + 40 = 7996 cycles

    ; Decrement 16-bit ms counter (outer overhead ≈ 20 cycles → ~8016 total)
    lda     STRNG1
    bne     @dec_lo
    dec     STRNG1+1
@dec_lo:
    dec     STRNG1
    lda     STRNG1
    ora     STRNG1+1
    bne     @ms_loop

@stop_tone:
    ; Disable T1 free-run / PB7 toggle
    lda     VIA_ACR
    and     #$3F
    sta     VIA_ACR

    ; Drive PB7 low (silence the speaker)
    lda     VIA_ORB
    and     #$7F
    sta     VIA_ORB

    rts

.endif
