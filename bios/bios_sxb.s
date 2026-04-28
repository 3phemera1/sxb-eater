; bios_sxb.s - WDC W65C02SXB BIOS for MS BASIC + Wozmon
; Replaces eater breadboard ACIA with WDC VIA2 USB serial
; VIA2 at $7FE0 connected to FTDI FT245 USB parallel FIFO

.setcpu "65C02"

.zeropage
                .org ZP_START0
READ_PTR:       .res 1
WRITE_PTR:      .res 1

.segment "INPUT_BUFFER"
INPUT_BUFFER:   .res $100

.segment "BIOS"

VIA2_ORB  = $7FE0
VIA2_ORA  = $7FE1
VIA2_DDRB = $7FE2
VIA2_DDRA = $7FE3
VIA2_ACR  = $7FEB
VIA2_PCR  = $7FEC
VIA2_IFR  = $7FED
VIA2_IER  = $7FEE

; VIA U3 (sound/GPIO) at $7FC0 — shares CPU IRQ line
VIA_U3_ACR = $7FCB
VIA_U3_IFR = $7FCD
VIA_U3_IER = $7FCE

; PIA (W65C21) at $7FA0 — shares CPU IRQ line
PIA_CRA    = $7FA1
PIA_CRB    = $7FA3

; Defines needed by wozmon - map ACIA symbols to VIA2 (writes ignored)
ACIA_CTRL = $EE        ; scratch ZP - writes ignored
ACIA_CMD  = $EF        ; scratch ZP - writes ignored

LOAD:
                rts

SAVE:
                rts

; INIT_BUFFER - initialize all I/O for USB serial
; Must fully initialize from power-on state (all regs may be undefined).
; VIA2, VIA U3, and PIA share the CPU IRQ line.  On cold boot, POR may
; leave IER/CRA/CRB in undefined states causing an IRQ storm.
INIT_BUFFER:
                ; --- Quiesce VIA U3 (sound/GPIO) on shared IRQ line ---
                lda     #$7F
                sta     VIA_U3_IER      ; disable all VIA U3 interrupts
                sta     VIA_U3_IFR      ; clear all VIA U3 flags
                stz     VIA_U3_ACR      ; no timer output, no latching
                ; --- Quiesce PIA on shared IRQ line ---
                stz     PIA_CRA         ; disable IRQA
                stz     PIA_CRB         ; disable IRQB
                ; --- VIA2 (USB serial) ---
                stz     VIA2_ACR        ; transparent port reads (no latching)
                                        ; A still $7F from above
                sta     VIA2_IER        ; disable all VIA2 interrupts
                sta     VIA2_IFR        ; clear all pending interrupt flags
                lda     #$0C
                sta     VIA2_ORB        ; WR+RD strobes high FIRST
                lda     #$0C
                sta     VIA2_DDRB       ; bits 2,3 = outputs
                stz     VIA2_DDRA       ; port A = input
                rts

; Input a character from USB serial.
; Blocks until a character is available.
; Returns character in A, carry set.
MONRDKEY:
CHRIN:
                stz     VIA2_DDRA       ; port A = input
RxWait:         lda     #$02
                bit     VIA2_ORB        ; test RX ready (bit 1)
                bne     RxWait          ; wait until clear
                lda     #$08
                trb     VIA2_ORB        ; RD strobe low
                nop
                nop
                lda     VIA2_ORA        ; read character
                pha                     ; save it
                lda     #$08
                tsb     VIA2_ORB        ; RD strobe high
                pla                     ; restore character
                jsr     CHROUT          ; echo
                sec                     ; carry set = char available
                rts

; Output a character (from A) to USB serial.
; Preserves all registers.
MONCOUT:
CHROUT:
                pha                     ; save character
                stz     VIA2_DDRA       ; tristate port A
                sta     VIA2_ORA        ; latch char into ORA
TxWait:         lda     #$01
                bit     VIA2_ORB        ; test TXE# (bit 0, active-low)
                bne     TxWait
                bit     VIA2_ORB        ; re-check: filter sub-cycle glitches
                bne     TxWait
                lda     #$04
                tsb     VIA2_ORB        ; WR strobe high
                lda     #$FF
                sta     VIA2_DDRA       ; drive port A (exact WDC sequence)
                nop
                nop
                lda     #$04
                trb     VIA2_ORB        ; WR strobe low
                stz     VIA2_DDRA       ; tristate port A again
                pla                     ; restore character
                rts

; IRQ handler - polled I/O, nothing to do
IRQ_HANDLER:
                rti


.segment "RESETVEC"
                .word   NMI_HANDLER     ; NMI vector -> bank 0 (WDCMON)
                .word   RESET           ; RESET vector
                .word   IRQ_HANDLER     ; IRQ vector


.segment "WOZMON"
.include "wozmon.s"

; NMI handler - minimal bootstrap: receive flash writer, execute it
; Protocol (from host):
;   1. Send $A5 (sync)
;   2. Send 255 bytes (flash writer code)
;   Board receives to $0800 and executes
.segment "CODE"
NMI_HANDLER:
                sei
                ldx     #$FF
                txs
                ; Init VIA2
                lda     #$0C
                sta     VIA2_ORB
                lda     #$0C
                sta     VIA2_DDRB
                stz     VIA2_DDRA

                ; Wait for $A5 sync
@sync_wait:     lda     #$02
@sync_poll:     bit     VIA2_ORB
                bne     @sync_poll
                lda     #$08
                trb     VIA2_ORB
                nop
                nop
                lda     VIA2_ORA
                pha
                lda     #$08
                tsb     VIA2_ORB
                pla
                cmp     #$A5
                bne     @sync_wait

                ; Send $01 ACK
                lda     #$FF
                sta     VIA2_DDRA
                lda     #$01
                sta     VIA2_ORA
                lda     #$01
@ack_poll:      bit     VIA2_ORB
                bne     @ack_poll
                lda     VIA2_ORB
                ora     #$04
                sta     VIA2_ORB
                nop
                nop
                lda     VIA2_ORB
                and     #$FB
                sta     VIA2_ORB
                stz     VIA2_DDRA

                ; Receive 255 bytes to $0800
                lda     #$00
                sta     $20             ; ZP ptr lo
                lda     #$08
                sta     $21             ; ZP ptr hi = $0800
                ldy     #$FF            ; 255 bytes
@recv_loop:     lda     #$02
@recv_poll:     bit     VIA2_ORB
                bne     @recv_poll
                lda     #$08
                trb     VIA2_ORB
                nop
                nop
                lda     VIA2_ORA
                pha
                lda     #$08
                tsb     VIA2_ORB
                pla
                sta     ($20)
                inc     $20
                dey
                bne     @recv_loop

                ; Execute at $0800
                jmp     $0800

NMI_STUB_END:
