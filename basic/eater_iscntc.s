; ISCNTC - Non-blocking Ctrl+C check for WDC SXB
; Called by MS BASIC main loop to check for break
; Returns carry SET if Ctrl+C, carry CLEAR otherwise
ISCNTC:
                lda     #$02
                bit     VIA2_ORB        ; test RX ready (bit 1, RXF#)
                bne     not_pressed     ; bit set = no char available
                ; char available - read it (RD strobe low)
                lda     VIA2_ORB
                and     #$F7            ; clear bit 3 (RD strobe low)
                sta     VIA2_ORB
                nop
                nop
                lda     VIA2_ORA        ; read character
                pha
                lda     VIA2_ORB
                ora     #$08            ; set bit 3 (RD strobe high)
                sta     VIA2_ORB
                pla
                cmp     #$03            ; Ctrl+C?
                beq     is_cntc
not_pressed:
                clc
                rts
is_cntc:
                ; fall through to STOP handler in flow1.s
