#ifndef SERIAL_H
#define SERIAL_H

/*
 * serial.h - VIA2 USB FIFO serial I/O for W65C02SXB bank 1 monitor
 *
 * The FT245 USB parallel FIFO is connected to VIA2 U5 (CS7B/VIA2TIDE) at
 * $7FE0.  All functions are implemented in serial.s as cc65-compatible
 * assembly so the critical MMIO strobe sequences are exact.
 *
 * serial_putchar / serial_getchar use __fastcall__ — the single byte
 * argument / return value lives in the A register, avoiding software-stack
 * overhead on the hot path.
 */

#include <stdint.h>

/* Initialise VIA2 for USB FIFO (call once at startup, already done by crt0) */
void serial_init(void);

/* Transmit one character (blocks until TX ready) */
void __fastcall__ serial_putchar(char c);

/* Receive one character (blocks until RX ready, no echo) */
char serial_getchar(void);

/* Print a NUL-terminated string */
void __fastcall__ serial_puts(const char *s);

/* Print CR + LF */
void serial_putcrlf(void);

/* Print val as two uppercase hex digits */
void __fastcall__ serial_puthex8(uint8_t val);

/* Print val as four uppercase hex digits (high byte first) */
void __fastcall__ serial_puthex16(uint16_t val);

#endif /* SERIAL_H */
