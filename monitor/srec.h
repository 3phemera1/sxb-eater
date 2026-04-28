#ifndef SREC_H
#define SREC_H

/*
 * srec.h - Motorola S-record loader for the bank 1 C monitor
 *
 * Supports S0 (header, ignored), S1 (16-bit address data), S5 (count, ignored),
 * S9 (end-of-file / entry address).  S2/S3/S7/S8 are rejected — ld65 emits
 * only S1/S9, which is sufficient for all 65C02 targets.
 *
 * Protocol (over serial):
 *   Monitor prints  "Ready for SREC (S9 to end):\r\n"
 *   For each S0/S1/S5 record:  monitor prints ".\r\n"
 *   On S9 end record:          monitor prints "\r\nOK\r\n", returns 0
 *   On any parse/checksum err: monitor prints "\r\n?\r\n", returns 1
 */

#include <stdint.h>

/*
 * srec_load — receive and apply an S-record stream from the serial port.
 *
 * Reads lines until an S9 end record is seen (or an error occurs).
 * Writes S1 data directly to the target 65C02 address space.
 * Verifies the one's-complement checksum on every record.
 *
 * entry_out  set to the S9 entry-point address (0 if S9 carries no entry).
 *
 * Returns 0 on success, 1 on error.
 */
uint8_t srec_load(uint16_t *entry_out);

#endif /* SREC_H */
