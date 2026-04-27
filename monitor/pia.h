#ifndef PIA_H
#define PIA_H

/*
 * pia.h - PIA U2 (W65C21, CS5B_PIA) SDK for W65C02SXB bank 1 monitor
 *
 * The W65C21 PIA is at base address $7FA0.  It has two 8-bit I/O ports
 * (A and B), each with a data-direction register shared with the output
 * register (selected by bit 2 of the control register).
 *
 * Register map:
 *   $7FA0  CRA.2=0 → DDRA   CRA.2=1 → ORA/IRA
 *   $7FA1  Control Register A (CRA)
 *   $7FA2  CRB.2=0 → DDRB   CRB.2=1 → ORB/IRB
 *   $7FA3  Control Register B (CRB)
 */

#include <stdint.h>

/* ── Register addresses ──────────────────────────────────────────────────── */
#define PIA_PA      ((volatile uint8_t *)0x7FA0)  /* Port A data / DDR-A        */
#define PIA_CRA     ((volatile uint8_t *)0x7FA1)  /* Control Register A         */
#define PIA_PB      ((volatile uint8_t *)0x7FA2)  /* Port B data / DDR-B        */
#define PIA_CRB     ((volatile uint8_t *)0x7FA3)  /* Control Register B         */

/* ── Control register bit fields ────────────────────────────────────────────*/
#define PIA_CR_DDR_ACCESS  0x00     /* CR bit 2 = 0: PA/PB accesses DDR  */
#define PIA_CR_DATA_ACCESS 0x04     /* CR bit 2 = 1: PA/PB accesses data */

/* IRQ flag bits in CRA/CRB (read-only) */
#define PIA_CR_IRQ1 0x80
#define PIA_CR_IRQ2 0x40

/* ── Initialise ──────────────────────────────────────────────────────────── */

/*
 * pia_init() — reset both ports to all-inputs with data access enabled.
 * Call once before using any other PIA functions.
 */
void pia_init(void);

/* ── Port direction ──────────────────────────────────────────────────────── */

/* Set Port A DDR (1=output, 0=input per bit) */
void __fastcall__ pia_set_ddra(uint8_t ddr);

/* Set Port B DDR */
void __fastcall__ pia_set_ddrb(uint8_t ddr);

/* ── Port read / write ───────────────────────────────────────────────────── */

/* Read Port A (ensures CRA selects data register) */
uint8_t pia_read_a(void);

/* Read Port B */
uint8_t pia_read_b(void);

/* Write Port A */
void __fastcall__ pia_write_a(uint8_t val);

/* Write Port B */
void __fastcall__ pia_write_b(uint8_t val);

/* ── Control register access ─────────────────────────────────────────────── */
#define pia_read_cra()          (*PIA_CRA)
#define pia_read_crb()          (*PIA_CRB)
#define pia_write_cra(val)      (*PIA_CRA = (val))
#define pia_write_crb(val)      (*PIA_CRB = (val))

#endif /* PIA_H */
