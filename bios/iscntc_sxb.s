; ISCNTC - Check for Ctrl+C without blocking
; Called by MS BASIC main loop to check for break
; Returns with carry SET and A=#3 if Ctrl+C pressed
; Returns with carry CLEAR if no key or key != Ctrl+C
.segment "CODE"
ISCNTC:
                lda     #$02
                bit     VIA2_ORB        ; test RX ready (bit 1)
                bne     not_pressed     ; no char available -> return
                ; char available - read it non-blocking
                lda     #$08
                trb     VIA2_ORB        ; RD strobe low
                nop
                nop
                lda     VIA2_ORA        ; read character
                pha
                lda     #$08
                tsb     VIA2_ORB        ; RD strobe high
                pla
                cmp     #$03            ; Ctrl+C?
                beq     is_cntc
not_pressed:
                clc
                rts
is_cntc:
                ; fall through to STOP handler
