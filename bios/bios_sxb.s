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

; Defines needed by wozmon - map ACIA symbols to VIA2 (writes ignored)
ACIA_CTRL = $EE        ; scratch ZP - writes ignored
ACIA_CMD  = $EF        ; scratch ZP - writes ignored

LOAD:
                rts

SAVE:
                rts

; INIT_BUFFER - initialize VIA2 for USB serial
; Exact sequence from WDC firmware $F9C2
INIT_BUFFER:
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
                sta     VIA2_ORA        ; write char to data bus
TxWait:         lda     #$01
                bit     VIA2_ORB        ; test TX ready (bit 0)
                bne     TxWait          ; wait until clear
                lda     #$04
                tsb     VIA2_ORB        ; WR strobe high
                lda     #$FF
                sta     VIA2_DDRA       ; drive port A as output
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

.include "wozmon.s"

.segment "RESETVEC"
                .word   $0F00           ; NMI vector
                .word   RESET           ; RESET vector
                .word   IRQ_HANDLER     ; IRQ vector
