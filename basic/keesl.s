.segment "CODE"
.ifdef EATER

	; TODO make this better. It works, but it is far from elegant.

CLS:
  pha

  lda #$1B
  jsr MONCOUT

  lda #'['
  jsr MONCOUT

  lda #'2'
  jsr MONCOUT

  lda #'J'
  jsr MONCOUT

  pla
  rts
.endif
