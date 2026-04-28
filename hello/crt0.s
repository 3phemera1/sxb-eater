; crt0.s - Minimal startup for user programs run from RAM under the C monitor
;
; When the monitor's 'AAAAAR' command JSRs to user code, the monitor's own
; cc65 runtime is still active — it holds live values in the cc65 zero-page
; area ($00–$1F: sp, sreg, ptr1–ptr4, tmp1–tmp4, regbank).  Overwriting those
; without saving them corrupts the monitor on return.
;
; This crt0:
;   1. Saves the monitor's cc65 ZP state ($00–$1F, 32 bytes) into BSS
;   2. Initialises the user program's own sp and clears BSS / copies DATA
;   3. Calls main()
;   4. Restores the monitor's cc65 ZP state
;   5. RTSs back to the monitor
;
; User C stack grows downward from __STACKSTART__ ($6D00), safely below the
; monitor's own C stack range ($7700–$7AFF).

.setcpu "65C02"

.importzp   sp                      ; cc65 software stack pointer ($00/$01)
.import     _main
.import     zerobss, copydata
.import     __STACKSTART__

.export     __STARTUP__ : absolute = 1

CC65_ZP_BYTES = 32                  ; $00–$1F — full cc65 ZP save area

; ── STARTUP ──────────────────────────────────────────────────────────────────
.segment "STARTUP"

_start:
    ; Zero BSS and copy initialised DATA FIRST.  These routines only touch
    ; scratch ZP (ptr1/tmp1), not sp, so the monitor's sp is preserved for
    ; the save step below.  Doing this before the save also avoids zerobss
    ; wiping the saved_zp buffer (it lives in BSS).
    jsr     zerobss
    jsr     copydata

    ; Save monitor's cc65 ZP variables (sp is still the monitor's at this
    ; point; ptr1/tmp1 may have been clobbered above but they are scratch).
    ldx     #CC65_ZP_BYTES - 1
save_loop:
    lda     $00,x
    sta     saved_zp,x
    dex
    bpl     save_loop

    ; Set up user program's cc65 software stack
    lda     #<__STACKSTART__
    sta     sp
    lda     #>__STACKSTART__
    sta     sp+1

    ; Run the user program
    jsr     _main

    ; Restore monitor's cc65 ZP variables before returning
    ldx     #CC65_ZP_BYTES - 1
restore_loop:
    lda     saved_zp,x
    sta     $00,x
    dex
    bpl     restore_loop

    rts                             ; return to monitor's run_at() caller

; ── BSS ──────────────────────────────────────────────────────────────────────
.segment "BSS"

saved_zp: .res CC65_ZP_BYTES        ; 32-byte save area for monitor ZP state
