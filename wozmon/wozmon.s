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

BANK_TRAMPOLINE = $02FA         ; 6-byte RAM trampoline: STA $7FEC ; JMP $8004
PCR_BANK0       = $CC           ; bank 0 (WDCMON)
PCR_BANK1       = $C4           ; bank 1 (user)  CA2=low CB2=low CA1edge=0 CB1=high?
PCR_BANK2       = $4C           ; bank 2 (user)
PCR_BANK3       = $EE           ; bank 3 (wozmon/EhBASIC - this bank)

; Bank select PCR values (VIA2 CA2/CB2 drive A15/A16):
;   PCR=$CC -> CA2=out-LOW,  CB2=out-LOW  -> A16=0, A15=0 -> bank 0
;   PCR=$EE -> CA2=out-HIGH, CB2=out-HIGH -> A16=1, A15=1 -> bank 3
;
; For banks 1 and 2 we need A16=0,A15=1 and A16=1,A15=0:
;   CA2 bits 3:1, CB2 bits 7:5
;   Bank 1: A15=1, A16=0 -> CA2=HIGH($0E), CB2=LOW($C0) -> PCR=$CE
;   Bank 2: A15=0, A16=1 -> CA2=LOW($0C),  CB2=HIGH($E0) -> PCR=$EC
PCR_BANK1_VAL   = $CE
PCR_BANK2_VAL   = $EC

RESET:
                ; Dirty reset circuit workaround removed (not needed on SXB)
                CLD
                LDA     #$EE
                STA     VIA2_PCR        ; CA2/CB2 = output HIGH → lock bank 3
                LDX     #$FF
                TXS                     ; init stack pointer
                JSR     INIT_BUFFER
                ; Clear stale input buffer to prevent replay after reset
                LDA     #$0D
                STA     IN
;                JSR     LCDINIT         ; LCD init using lcd.s
                CLI
                LDA     #$1F            ; 8-N-1, 19200 bps
                STA     ACIA_CTRL
                LDY     #$89            ; No parity, no echo, rx interrupts
                STY     ACIA_CMD

                ; Init bank-switch RAM trampoline: STA $7FEC ; JMP $8004
                ; DO_SWITCH jumps here with A = target PCR value.
                ; Runs from RAM so the JMP $8004 executes from the new bank safely.
                LDA     #$8D
                STA     BANK_TRAMPOLINE
                LDA     #<VIA2_PCR
                STA     BANK_TRAMPOLINE+1
                LDA     #>VIA2_PCR
                STA     BANK_TRAMPOLINE+2
                LDA     #$4C
                STA     BANK_TRAMPOLINE+3
                LDA     #$04
                STA     BANK_TRAMPOLINE+4
                LDA     #$80
                STA     BANK_TRAMPOLINE+5

                LDX     #$FF
DELAY_OUT:
                LDY     #$FF
DELAY_IN:
                DEY
                BNE     DELAY_IN
                DEX
                BNE     DELAY_OUT
                ; Wait for FT245 TX FIFO ready (TXE# = bit 0 of VIA2_ORB, active-low).
                ; On cold power-up the FT245 needs USB enumeration (1-3s typical)
                ; before TXE# goes low.  CHROUT blocks unboundedly on TXE#, so we
                ; must wait here long enough for enumeration to finish.
                ; 48 passes × ~106ms ≈ ~5s at 8 MHz — covers worst-case enumeration.
                ; On warm restart (B3) TXE# is already low so this exits immediately.
                LDA     #$30            ; pass counter (ACIA_CTRL = ZP scratch)
                STA     ACIA_CTRL
WAIT_TX_PASS:
                LDX     #$FF
WAIT_TX_OUTER:
                LDY     #$FF
WAIT_TX_INNER:
                LDA     #$01
                BIT     VIA2_ORB        ; test TXE# (bit 0)
                BEQ     WAIT_TX_DONE    ; TXE# low — proceed
                DEY
                BNE     WAIT_TX_INNER
                DEX
                BNE     WAIT_TX_OUTER
                DEC     ACIA_CTRL
                BNE     WAIT_TX_PASS    ; more passes remaining
                ; Timed out after ~850ms — proceed anyway; CHROUT will block when needed
WAIT_TX_DONE:
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
                CMP     #$42            ; 'B' - bank switch command
                BNE     :+
                JMP     BANKSWITCH
:
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
                BEQ     NXTPRNT         ; on 8-byte boundary: print new address line
                BNE     PRDATA          ; not on boundary: print next byte directly

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

; ── Bank switch command ──────────────────────────────────────────────────────
; Syntax: Bn  where n = 0, 1, 2, or 3
; B0 -> jump to bank 0 (WDCMON)
; B1 -> jump to bank 1 (user ROM)
; B2 -> jump to bank 2 (user ROM)
; B3 -> jump to bank 3 (reload wozmon/EhBASIC)
;
; Sets VIA2 PCR ($7FEC) to select the target bank then JMPs to $8000.
; The target ROM must have valid code at $8000.
; -----------------------------------------------------------------------------
BANKSWITCH:
                INY                     ; advance past 'B' to digit
                LDA     IN,Y            ; get bank digit
                CMP     #$30            ; '0'
                BEQ     BANK0
                CMP     #$31            ; '1'
                BEQ     BANK1
                CMP     #$32            ; '2'
                BEQ     BANK2
                CMP     #$33            ; '3'
                BEQ     BANK3
                JMP     ESCAPE          ; invalid digit -> prompt

BANK0:          LDA     #PCR_BANK0
                BNE     DO_SWITCH       ; always taken
BANK1:          LDA     #PCR_BANK1_VAL
                BNE     DO_SWITCH
BANK2:          LDA     #PCR_BANK2_VAL
DO_SWITCH:
                ; A = target PCR value.  Jump to RAM trampoline which does
                ; STA $7FEC (bank switch) then JMP $8004, both from RAM so
                ; the JMP fetch is unaffected by the bank change.
                JMP     BANK_TRAMPOLINE
BANK3:          LDA     #PCR_BANK3
                STA     VIA2_PCR        ; select bank 3
                JMP     RESET           ; restart wozmon (direct, avoids $8000 WDC sig bytes)
WOZMON_END:
