/*
 * srec.c - Motorola S-record loader for the bank 1 C monitor
 *
 * Supported record types:
 *   S0  header      — ignored, acknowledged with '.'
 *   S1  data (16-bit address) — written to target address space
 *   S5  record count — ignored
 *   S9  end / entry (16-bit) — terminates load, returns entry address
 *
 * S2/S3/S7/S8 (24/32-bit address variants) are rejected: ld65 only emits
 * S1/S9 for 65C02 targets, and silently truncating 24/32-bit addresses to
 * 16 bits would write to wrong locations.
 *
 * Checksum: one's complement of the 8-bit sum of all bytes from byte_count
 * through the last data/address byte (standard Motorola SREC definition).
 */

#include <stdint.h>
#include "serial.h"
#include "srec.h"

/* ── Private constants ───────────────────────────────────────────────────── */

#define SREC_BUF_SIZE 128   /* max line length; ld65 S1 records top out at ~74 */

/* ── Private state ───────────────────────────────────────────────────────── */

static char rbuf[SREC_BUF_SIZE];

/* ── Private helpers ─────────────────────────────────────────────────────── */

/*
 * hexnib — convert one ASCII hex character to its 4-bit value.
 * Returns -1 for non-hex input.
 */
static int8_t hexnib(char c)
{
    if (c >= '0' && c <= '9') return (int8_t)(c - '0');
    if (c >= 'A' && c <= 'F') return (int8_t)(c - 'A' + 10);
    if (c >= 'a' && c <= 'f') return (int8_t)(c - 'a' + 10);
    return -1;
}

/*
 * parse_byte — read exactly two hex characters from *p into *out.
 * Returns a pointer past the two characters, or NULL on failure.
 */
static const char *parse_byte(const char *p, uint8_t *out)
{
    int8_t hi = hexnib(*p);
    int8_t lo = hexnib(*(p + 1));
    if (hi < 0 || lo < 0)
        return 0;
    *out = (uint8_t)((hi << 4) | lo);
    return p + 2;
}

/*
 * read_srec_line — read one non-empty line into rbuf without echoing.
 * Blocks until a CR or LF-terminated non-empty line is received.
 * Silently discards lines that exceed SREC_BUF_SIZE-1 characters.
 */
static void read_srec_line(void)
{
    uint8_t pos;
    char    c;

    for (;;) {
        pos = 0;

        /* Accumulate characters until end-of-line */
        while (1) {
            c = serial_getchar();
            if (c == '\r' || c == '\n')
                break;
            if (pos < SREC_BUF_SIZE - 1)
                rbuf[pos++] = c;
        }

        if (pos > 0) {
            rbuf[pos] = '\0';
            return;
        }
        /* Empty line — keep waiting */
    }
}

/* ── Public API ──────────────────────────────────────────────────────────── */

uint8_t srec_load(uint16_t *entry_out)
{
    const char      *p;
    uint8_t          byte_count, b, i, sum;
    uint16_t         addr;
    volatile uint8_t *mem;

    *entry_out = 0;
    serial_puts("Ready for SREC (S9 to end):\r\n");

    for (;;) {
        read_srec_line();
        p = rbuf;

        /* Every SREC line must start with 'S' */
        if (*p != 'S')
            goto bad;
        ++p;

        /* ── Dispatch on record type ──────────────────────────────────── */
        switch (*p++) {

        /* ── S0: header record — ignore payload, ack ── */
        case '0':
            serial_puts(".\r\n");
            continue;

        /* ── S5: record-count — ignore ── */
        case '5':
            continue;

        /* ── S9: end-of-file / entry address ── */
        case '9': {
            /* S9NNAAAACCCC  — byte_count covers 2 addr bytes + 1 checksum */
            p = parse_byte(p, &byte_count);
            if (!p) goto bad;
            sum = byte_count;

            addr = 0;
            for (i = 0; i < 2; i++) {
                p = parse_byte(p, &b);
                if (!p) goto bad;
                sum += b;
                addr = (uint16_t)((addr << 8) | b);
            }

            p = parse_byte(p, &b);
            if (!p || (uint8_t)(~sum) != b) goto bad;

            *entry_out = addr;
            serial_puts("\r\nOK\r\n");
            return 0;
        }

        /* ── S1: 16-bit address data record ── */
        case '1': {
            uint8_t data_len;

            p = parse_byte(p, &byte_count);
            if (!p) goto bad;
            sum = byte_count;

            /* 2 address bytes */
            addr = 0;
            for (i = 0; i < 2; i++) {
                p = parse_byte(p, &b);
                if (!p) goto bad;
                sum += b;
                addr = (uint16_t)((addr << 8) | b);
            }

            /* data_len = byte_count - 2 addr bytes - 1 checksum byte */
            data_len = byte_count - 3;
            mem = (volatile uint8_t *)addr;
            for (i = 0; i < data_len; i++) {
                p = parse_byte(p, &b);
                if (!p) goto bad;
                sum += b;
                *mem++ = b;
            }

            p = parse_byte(p, &b);
            if (!p || (uint8_t)(~sum) != b) goto bad;

            serial_puts(".\r\n");
            continue;
        }

        /* ── S2/S3/S7/S8: 24/32-bit address variants — unsupported ── */
        default:
            goto bad;
        }

bad:
        serial_puts("\r\n?\r\n");
        return 1;
    }
}
