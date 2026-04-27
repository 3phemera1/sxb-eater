#ifndef VIA_H
#define VIA_H

/*
 * via.h - VIA U3 (W65C22, CS6B_VIA) SDK for W65C02SXB bank 1 monitor
 *
 * VIA U3 is the user-accessible W65C22 at base address $7FC0.
 * It is NOT the USB serial VIA (that is VIA2 U5 at $7FE0, handled in serial.h).
 *
 * Common use: T1 free-running square wave on PB7 (VIA header pin 24)
 * drives the onboard LM386 audio amplifier.
 *
 * Frequency formula: latch = 4,000,000 / freq_hz - 2  (8 MHz clock ÷ 2)
 */

#include <stdint.h>

/* ── Register addresses ──────────────────────────────────────────────────── */
#define VIA_ORB     ((volatile uint8_t *)0x7FC0)  /* Port B output register     */
#define VIA_ORA     ((volatile uint8_t *)0x7FC1)  /* Port A output register     */
#define VIA_DDRB    ((volatile uint8_t *)0x7FC2)  /* Port B direction register  */
#define VIA_DDRA    ((volatile uint8_t *)0x7FC3)  /* Port A direction register  */
#define VIA_T1CL    ((volatile uint8_t *)0x7FC4)  /* T1 counter low             */
#define VIA_T1CH    ((volatile uint8_t *)0x7FC5)  /* T1 counter high            */
#define VIA_T1LL    ((volatile uint8_t *)0x7FC6)  /* T1 latch low               */
#define VIA_T1LH    ((volatile uint8_t *)0x7FC7)  /* T1 latch high              */
#define VIA_T2CL    ((volatile uint8_t *)0x7FC8)  /* T2 counter/latch low       */
#define VIA_T2CH    ((volatile uint8_t *)0x7FC9)  /* T2 counter high            */
#define VIA_SR      ((volatile uint8_t *)0x7FCA)  /* Shift register             */
#define VIA_ACR     ((volatile uint8_t *)0x7FCB)  /* Auxiliary control register */
#define VIA_PCR     ((volatile uint8_t *)0x7FCC)  /* Peripheral control register*/
#define VIA_IFR     ((volatile uint8_t *)0x7FCD)  /* Interrupt flag register    */
#define VIA_IER     ((volatile uint8_t *)0x7FCE)  /* Interrupt enable register  */
#define VIA_ORAnh   ((volatile uint8_t *)0x7FCF)  /* Port A (no handshake)      */

/* ── ACR bit fields ──────────────────────────────────────────────────────── */
#define VIA_ACR_T1_ONESHOT   0x00   /* T1 one-shot (default)              */
#define VIA_ACR_T1_FREERUN   0x40   /* T1 free-run (continuous square wave)*/
#define VIA_ACR_PB7_T1       0x80   /* PB7 controlled by T1 output        */

/* ── IER/IFR bit masks ───────────────────────────────────────────────────── */
#define VIA_IRQ_T1  0x40
#define VIA_IRQ_T2  0x20
#define VIA_IRQ_SET 0x80            /* set bit in IER to enable an IRQ    */

/* ── Direct register access ─────────────────────────────────────────────── */

/* Read / write any VIA register by address */
#define via_read(reg)        (*(volatile uint8_t *)(reg))
#define via_write(reg, val)  (*(volatile uint8_t *)(reg) = (val))

/* ── Port direction ──────────────────────────────────────────────────────── */

/* Set Port A data-direction register (1=output, 0=input per bit) */
#define via_set_ddra(ddr)  (*VIA_DDRA = (ddr))

/* Set Port B data-direction register */
#define via_set_ddrb(ddr)  (*VIA_DDRB = (ddr))

/* ── Port read / write ───────────────────────────────────────────────────── */
#define via_read_a()        (*VIA_ORA)
#define via_read_b()        (*VIA_ORB)
#define via_write_a(val)    (*VIA_ORA = (val))
#define via_write_b(val)    (*VIA_ORB = (val))

/* ── Timer 1 ─────────────────────────────────────────────────────────────── */

/*
 * via_t1_freerun(latch) — start T1 continuous square wave on PB7.
 *
 * latch = 4,000,000 / freq_hz - 2   (for 8 MHz system clock)
 *
 * Enables PB7 as output, sets ACR for free-run + PB7 output, loads latch.
 * Writing the high byte starts the counter.
 */
void via_t1_freerun(uint16_t latch);

/* via_t1_stop() — stop T1 and tri-state PB7 */
void via_t1_stop(void);

/* ── Timer 2 ─────────────────────────────────────────────────────────────── */

/*
 * via_t2_oneshot(count) — start T2 one-shot countdown.
 *
 * Fires T2 interrupt (IFR bit 5) after `count` clock cycles.
 * Caller is responsible for handling the IRQ or polling VIA_IFR.
 */
void via_t2_oneshot(uint16_t count);

#endif /* VIA_H */
