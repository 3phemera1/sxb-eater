#ifndef ACIA_H
#define ACIA_H

/*
 * acia.h - ACIA U4 (W65C51, CS4B_ACIA) SDK for W65C02SXB bank 1 monitor
 *
 * The W65C51 ACIA is at base address $7F80.  It provides a traditional
 * UART-style serial port separate from the USB FIFO (VIA2).
 *
 * Register map:
 *   $7F80  Data register (read = RX, write = TX)
 *   $7F81  Status register (read-only)
 *   $7F82  Command register
 *   $7F83  Control register
 *
 * Note: W65C51 has a silicon bug — the TX-empty status bit in the status
 * register is unreliable.  acia_putchar() uses a short delay loop as a
 * workaround (the standard practice for this chip).
 */

#include <stdint.h>

/* ── Register addresses ──────────────────────────────────────────────────── */
#define ACIA_DATA    ((volatile uint8_t *)0x7F80)  /* TX/RX data              */
#define ACIA_STATUS  ((volatile uint8_t *)0x7F81)  /* Status (read-only)      */
#define ACIA_CMD     ((volatile uint8_t *)0x7F82)  /* Command register        */
#define ACIA_CTRL    ((volatile uint8_t *)0x7F83)  /* Control register        */

/* ── Status register bits ────────────────────────────────────────────────── */
#define ACIA_ST_IRQ     0x80    /* Interrupt flag                          */
#define ACIA_ST_DSR     0x40    /* Data Set Ready                          */
#define ACIA_ST_DCD     0x20    /* Data Carrier Detect                     */
#define ACIA_ST_TDRE    0x10    /* TX data register empty (unreliable!)    */
#define ACIA_ST_RDRF    0x08    /* RX data register full                   */
#define ACIA_ST_OVRN    0x04    /* Overrun error                           */
#define ACIA_ST_FE      0x02    /* Framing error                           */
#define ACIA_ST_PE      0x01    /* Parity error                            */

/* ── Preset control register values ─────────────────────────────────────── */
/* Baud rate + word length (CTRL register):
 *   Bits 0-3: baud  0001=50, 0010=75, 0011=110, 0100=135, 0101=150,
 *                   0110=300, 0111=600, 1000=1200, 1001=1800, 1010=2400,
 *                   1011=3600, 1100=4800, 1101=7200, 1110=9600, 1111=19200
 *   Bits 5-6: word  00=8, 01=7, 10=6, 11=5 bits
 *   Bit  7:   stop  0=1 stop, 1=2 stop (or 1.5 for 5-bit words)
 */
#define ACIA_CTRL_9600_8N1   0x1E   /* 9600 baud, 8 bits, no parity, 1 stop */
#define ACIA_CTRL_19200_8N1  0x1F   /* 19200 baud, 8 bits, no parity, 1 stop*/

/* Command register: DTR active, RTS high, no echo, no parity, TX/RX enabled */
#define ACIA_CMD_NO_PARITY   0x02   /* DTR low, RTS high, no echo, no parity */

/* ── API ─────────────────────────────────────────────────────────────────── */

/*
 * acia_init(ctrl, cmd) — initialise the ACIA.
 *
 * Example for 9600 8N1:
 *   acia_init(ACIA_CTRL_9600_8N1, ACIA_CMD_NO_PARITY);
 *
 * A software reset is performed first (read status + read data).
 */
void acia_init(uint8_t ctrl, uint8_t cmd);

/*
 * acia_putchar(c) — transmit one character.
 *
 * Due to the W65C51 TX-empty bug, this uses a fixed delay loop instead of
 * polling TDRE.  The loop is calibrated for 8 MHz / 9600 baud.  If you
 * change baud rate via acia_init(), adjust the delay or use the status
 * polling variant acia_putchar_poll() if your silicon revision is known good.
 */
void __fastcall__ acia_putchar(char c);

/*
 * acia_getchar() — receive one character (blocks until RDRF set).
 * Returns the received byte in A.
 */
char acia_getchar(void);

/* Raw status register read */
#define acia_status()    (*ACIA_STATUS)

/* Non-zero if TX register is empty (may be unreliable on some revisions) */
#define acia_tx_ready()  (*ACIA_STATUS & ACIA_ST_TDRE)

/* Non-zero if RX data register is full */
#define acia_rx_ready()  (*ACIA_STATUS & ACIA_ST_RDRF)

#endif /* ACIA_H */
