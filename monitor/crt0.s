; crt0.s - Bank 1 C monitor startup for W65C02SXB
;
; Responsibilities:
;   1. Place WDC\x00 signature + JMP at $8000 (ROMHDR segment)
;   2. Init VIA2 for USB serial (same sequence as bios_sxb.s)
;   3. USB enumeration delay (~500 ms)
;   4. Init cc65 C software stack pointer (sp ZP variable)
;   5. Zero BSS, copy initialized DATA from ROM to RAM
;   6. Call C main()
;   7. Provide NMI / IRQ handlers and reset vectors
;   8. Provide do_bank_switch() helper called from main.c

.setcpu "65C02"

; ── cc65 ZP imports ──────────────────────────────────────────────────────────
.importzp   sp              ; cc65 software stack pointer ($0000–$0001)

; ── cc65 runtime imports ─────────────────────────────────────────────────────
.import     zerobss         ; zero the BSS segment
.import     copydata        ; copy initialized DATA from ROM to RAM

; ── C entry point ────────────────────────────────────────────────────────────
.import     _main

; ── Linker-defined symbol for C software stack top ───────────────────────────
.import     __STACKSTART__

; ── Export startup symbol so none.lib's crt0 is NOT pulled from the library ─
.export     __STARTUP__ : absolute = 1

; ── Hardware addresses ───────────────────────────────────────────────────────
VIA2_ORB  = $7FE0
VIA2_DDRB = $7FE2
VIA2_DDRA = $7FE3
VIA2_PCR  = $7FEC

; RAM trampoline initialized by wozmon RESET: STA $7FEC ; JMP $8004
; Must be in RAM so the JMP fetch after the bank switch reads from RAM, not ROM.
BANK_TRAMPOLINE = $02FA

; ── ROMHDR segment: WDC\x00 signature + JMP entry (must be at $8000) ────────
.segment "ROMHDR"
    .byte   $57,$44,$43,$00         ; 'W','D','C',$00 — SXB2 auto-boot signature
    jmp     _start                  ; $8004: JMP to startup code

; ── STARTUP segment: hardware init, C runtime init, call main ────────────────
.segment "STARTUP"

_start:
    cld                             ; clear decimal mode
    ldx     #$FF
    txs                             ; hardware stack → $01FF

    ; Init VIA2 for USB FIFO (matches INIT_BUFFER in bios_sxb.s)
    lda     #$0C
    sta     VIA2_ORB                ; WR+RD strobes high first
    lda     #$0C
    sta     VIA2_DDRB               ; bits 2,3 = outputs
    stz     VIA2_DDRA               ; port A = input

    ; USB enumeration delay — two passes of ~250 ms each (~500 ms total)
    ldx     #$FF
delay1_outer:
    ldy     #$FF
delay1_inner:
    dey
    bne     delay1_inner
    dex
    bne     delay1_outer

    ldx     #$FF
delay2_outer:
    ldy     #$FF
delay2_inner:
    dey
    bne     delay2_inner
    dex
    bne     delay2_outer

    ; Init cc65 software stack pointer to top of C stack (__STACKSTART__)
    lda     #<__STACKSTART__
    sta     sp
    lda     #>__STACKSTART__
    sta     sp+1

    ; Zero BSS segment
    jsr     zerobss

    ; Copy initialized DATA from ROM load address to RAM run address
    jsr     copydata

    ; Call C main() — should never return
    jsr     _main

    ; If main() returns, hang
hang:
    jmp     hang

; ── do_bank_switch — C-callable (fastcall): switches flash bank
;
;   void __fastcall__ do_bank_switch(uint8_t pcr_val);
;
;   pcr_val arrives in A register (cc65 fastcall single-byte param).
;   Writes VIA2_PCR then jumps (not JSR) to $8000 in the new bank.
;   Never returns.
; ─────────────────────────────────────────────────────────────────────────────
.export _do_bank_switch
_do_bank_switch:
    ; A = target PCR value (fastcall).
    ; Jump to RAM trampoline (initialized by wozmon RESET) which does
    ;   STA $7FEC   (select bank)
    ;   JMP $8004   (enter new bank, fetched from RAM — safe after bank switch)
    jmp     BANK_TRAMPOLINE

; ── NMI and IRQ handlers (trivial — polled I/O only) ────────────────────────
.segment "CODE"

.export _nmi_handler
.export _irq_handler

_nmi_handler:
    rti

_irq_handler:
    rti

; ── Reset vectors ($FFFA–$FFFF) ──────────────────────────────────────────────
.segment "RESETVEC"
    .word   _nmi_handler            ; $FFFA NMI
    .word   _start                  ; $FFFC RESET
    .word   _irq_handler            ; $FFFE IRQ/BRK
