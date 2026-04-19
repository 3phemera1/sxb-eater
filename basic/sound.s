.segment "CODE"
.ifdef EATER

VIA_T1CL = $7FC4    ; T1 counter/latch low
VIA_T1CH = $7FC5    ; T1 counter high (writing starts timer)
VIA_T1LL = $7FC6    ; T1 latch low
VIA_T1LH = $7FC7    ; T1 latch high
VIA_ACR  = $7FCB    ; Auxiliary control register
VIA_DDRB = $7FC2    ; Port B DDR

BEEP:
    jsr     FRMEVL
    jsr     MKINT

    ; Check if parameter is zero
    lda     FAC+4
    ora     FAC+3
    beq     @silent

    ; Make PB7 an output
    lda     VIA_DDRB
    ora     #$80
    sta     VIA_DDRB

    ; Load T1 latch with frequency value
    lda     FAC+4
    sta     VIA_T1CL
    lda     FAC+3
    sta     VIA_T1CH

    ; ACR: T1 free-run, PB7 toggled
    lda     VIA_ACR
    ora     #$C0
    sta     VIA_ACR

    jmp     @delay

@silent:
@delay:
    jsr     CHKCOM
    jsr     GETBYT
    cpx     #0
    beq     @done

@delay1:
    ldy     #$ff
@delay2:
    nop
    nop
    dey
    bne     @delay2
    dex
    bne     @delay1

    ; Stop square wave
    lda     VIA_ACR
    and     #$3F
    sta     VIA_ACR
    lda     $7FC0
    and     #$7F
    sta     $7FC0

@done:
    rts

.endif
