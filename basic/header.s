		.segment "HEADER"
.ifdef KBD
        jmp     LE68C
        .byte   $00,$13,$56
.endif
.ifdef AIM65
        jmp     COLD_START
        jmp     RESTART
        .word   AYINT,GIVAYF
.endif
.ifdef SYM1
        jmp     PR_WRITTEN_BY
.endif
.ifdef EATER
        jmp COLD_START
        ; 4-byte pad: build_rom.py overwrites $8000-$8006 with WDC\0 + JMP wozmon.
        ; Without this pad, TOKEN_ADDRESS_TABLE would start at $8003 and the FOR/END
        ; token handler entries would be clobbered, causing FOR to jump into wozmon.
        .byte $00,$00,$00,$00
.endif
