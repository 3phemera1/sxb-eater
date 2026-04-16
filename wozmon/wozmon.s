.setcpu "65C02"
.segment "WOZMON"

XAML            = $24
XAMH            = $25
STL             = $26
STH             = $27
L               = $28
H               = $29
YSAV            = $2A
MODE            = $2B

IN              = $0200

RESET:
                ; Dirty reset circuit workaround removed (not needed on SXB)
                CLD
                JSR     INIT_BUFFER
;                JSR     LCDINIT         ; LCD init using lcd.s
                CLI
                LDA     #$1F            ; 8-N-1, 19200 bps
                STA     ACIA_CTRL
                LDY     #$89            ; No parity, no echo, rx interrupts
                STY     ACIA_CMD

                LDX     #$FF
DELAY_OUT:
                LDY     #$FF
DELAY_IN:
                DEY
                BNE     DELAY_IN
                DEX
                BNE     DELAY_OUT
                JMP     ESCAPE

NOTCR:
                CMP     #$08
                BEQ     BACKSPACE
                CMP     #$1B
                BEQ     ESCAPE
                INY
                BPL     NEXTCHAR

ESCAPE:
                LDA     #$5C            ; "\"
                JSR     CHROUT

GETLINE:
                LDA     #$0D
                JSR     CHROUT
                LDA     #$0A
                JSR     CHROUT

                LDY     #$01
BACKSPACE:      DEY
                BMI     GETLINE

NEXTCHAR:
                JSR     CHRIN
                BCC     NEXTCHAR
                STA     IN,Y
                CMP     #$0D
                BNE     NOTCR

                LDY     #$FF
                LDA     #$00
                TAX
SETBLOCK:
                ASL
SETSTOR:
                ASL
SETMODE:
                STA     MODE
BLSKIP:
                INY
NEXTITEM:
                LDA     IN,Y
                CMP     #$0D
                BEQ     GETLINE
                CMP     #$2E
                BCC     BLSKIP
                BEQ     SETBLOCK
                CMP     #$3A
                BEQ     SETSTOR
                CMP     #$52
                BEQ     RUNPROG
                STX     L
                STX     H
                STY     YSAV

NEXTHEX:
                LDA     IN,Y
                EOR     #$30
                CMP     #$0A
                BCC     DIG
                ADC     #$88
                CMP     #$FA
                BCC     NOTHEX
DIG:
                ASL
                ASL
                ASL
                ASL
                LDX     #$04
HEXSHIFT:
                ASL
                ROL     L
                ROL     H
                DEX
                BNE     HEXSHIFT
                INY
                BNE     NEXTHEX

NOTHEX:
                CPY     YSAV
                BEQ     ESCAPE
                BIT     MODE
                BVC     NOTSTOR
                LDA     L
                STA     (STL,X)
                INC     STL
                BNE     NEXTITEM
                INC     STH
TONEXTITEM:     JMP     NEXTITEM

RUNPROG:
                JMP     (XAML)

NOTSTOR:
                BMI     XAMNEXT
                LDX     #$02
SETADR:         LDA     L-1,X
                STA     STL-1,X
                STA     XAML-1,X
                DEX
                BNE     SETADR

NXTPRNT:
                BNE     PRDATA
                LDA     #$0D
                JSR     CHROUT
                LDA     #$0A
                JSR     CHROUT
                LDA     XAMH
                JSR     PRBYTE
                LDA     XAML
                JSR     PRBYTE
                LDA     #$3A
                JSR     CHROUT

PRDATA:
                LDA     #$20
                JSR     CHROUT
                LDA     (XAML,X)
                JSR     PRBYTE
XAMNEXT:        STX     MODE
                LDA     XAML
                CMP     L
                LDA     XAMH
                SBC     H
                BCS     TONEXTITEM
                INC     XAML
                BNE     MOD8CHK
                INC     XAMH

MOD8CHK:
                LDA     XAML
                AND     #$07
                BPL     NXTPRNT

PRBYTE:
                PHA
                LSR
                LSR
                LSR
                LSR
                JSR     PRHEX
                PLA

PRHEX:
                AND     #$0F
                ORA     #$30
                CMP     #$3A
                BCC     ECHO
                ADC     #$06

ECHO:
                JSR     CHROUT          ; route through CHROUT -> serial + LCD
                RTS
