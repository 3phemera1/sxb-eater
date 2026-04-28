/*
 * main.c - Bank 1 C monitor for W65C02SXB
 *
 * This monitor provides wozmon-compatible memory examine/store/run commands
 * plus bank switching, accessible via the USB serial port.
 *
 * Commands
 * ────────
 *   AAAA           Examine byte at AAAA
 *   AAAA.BBBB      Examine range AAAA–BBBB (8 bytes per line)
 *   AAAA: HH ...   Store one or more bytes starting at AAAA
 *   AAAAR          Run code at AAAA (JSR; returns to monitor if code RTSs)
 *   L              Load Motorola S-records (S1/S9) from serial
 *   B0–B3          Switch to flash bank 0–3 (never returns for 0–2)
 *   ?              Show this help
 *
 * Hardware SDK headers (via.h, pia.h, acia.h) are included so user code
 * compiled into this bank can call those functions directly.
 */

#include <stdint.h>
#include <string.h>

#include "serial.h"
#include "util.h"
#include "srec.h"
#include "via.h"
#include "pia.h"
#include "acia.h"

/* ── Declarations for helpers in crt0.s ─────────────────────────────────── */

/* Write VIA2_PCR value in A then JMP $8000.  Never returns. */
void __fastcall__ do_bank_switch(uint8_t pcr_val);

/* ── Constants ───────────────────────────────────────────────────────────── */

#define LINE_BUF_SIZE  80

static const uint8_t bank_pcr[4] = { 0xCC, 0xCE, 0xEC, 0xEE };

/* ── State ───────────────────────────────────────────────────────────────── */

static char line[LINE_BUF_SIZE];

/* ── Helpers ─────────────────────────────────────────────────────────────── */

static void print_addr(uint16_t addr)
{
    serial_puthex16(addr);
    serial_putchar(':');
}

/*
 * examine_range — display memory bytes from start to end (inclusive).
 * Format:  AAAA: HH HH HH HH HH HH HH HH
 * 8 bytes per line, aligned to 8-byte boundaries.
 */
static void examine_range(uint16_t start, uint16_t end)
{
    volatile uint8_t *mem = (volatile uint8_t *)start;
    uint16_t addr = start;

    /* Print address header for the first (possibly partial) line */
    serial_putcrlf();
    print_addr(addr);

    while (1) {
        serial_putchar(' ');
        serial_puthex8(*mem);

        if (addr == end)
            break;

        ++addr;
        ++mem;

        /* New line on every 8-byte boundary */
        if ((addr & 7) == 0) {
            serial_putcrlf();
            print_addr(addr);
        }
    }
    serial_putcrlf();
}

/*
 * store_bytes — parse and write hex bytes from p into memory starting at addr.
 * Stops when no more hex digits are found.
 */
static void store_bytes(uint16_t addr, const char *p)
{
    uint16_t val;

    while (1) {
        p = skip_spaces(p);
        p = parse_hex(p, &val);
        if (!p)
            break;
        *((volatile uint8_t *)addr) = (uint8_t)val;
        ++addr;
    }
}

/*
 * run_at — call code at addr as a subroutine.
 * If the code ends with RTS, execution returns to the monitor.
 * If the code jumps away permanently, the monitor is not recovered.
 */
static void run_at(uint16_t addr)
{
    typedef void (*fn_t)(void);
    ((fn_t)addr)();
}

static void show_help(void)
{
    serial_puts("\r\nBank 1 C Monitor - commands:\r\n");
    serial_puts("  AAAA          examine byte at AAAA\r\n");
    serial_puts("  AAAA.BBBB     examine range AAAA to BBBB\r\n");
    serial_puts("  AAAA: HH ...  store bytes at AAAA\r\n");
    serial_puts("  AAAAR         run (JSR) at AAAA\r\n");
    serial_puts("  L             load Motorola S-records (S1/S9)\r\n");
    serial_puts("  B0-B3         switch to flash bank 0-3\r\n");
    serial_puts("  ?             this help\r\n");
    serial_puts("\r\nSDK available: via.h  pia.h  acia.h\r\n");
}

/* ── Line editor ─────────────────────────────────────────────────────────── */

/*
 * read_line — read one line from serial into the global `line` buffer.
 * Echoes characters, handles backspace.
 * Returns the number of characters in the line (0 for empty).
 */
static uint8_t read_line(void)
{
    uint8_t pos = 0;
    char    c;

    while (1) {
        c = serial_getchar();

        if (c == '\r') {
            serial_putcrlf();
            line[pos] = '\0';
            return pos;
        }

        if (c == '\n')
            continue;           /* swallow LF — handles \r\n terminal pairs */

        if ((c == '\b' || c == 0x7F) && pos > 0) {
            /* Backspace: erase last character on the terminal */
            serial_puts("\b \b");
            --pos;
            continue;
        }

        if (pos < LINE_BUF_SIZE - 1) {
            serial_putchar(c);          /* echo */
            line[pos++] = c;
        }
    }
}

/* ── Command processor ───────────────────────────────────────────────────── */

static void process_command(void)
{
    const char *p = line;
    uint16_t    addr1 = 0, addr2 = 0;
    char        c;

    p = skip_spaces(p);

    if (*p == '\0')
        return;

    c = *p;

    /* ── ? — help ──────────────────────────────────────────────────────── */
    if (c == '?') {
        show_help();
        return;
    }

    /* ── Bn — bank switch ──────────────────────────────────────────────── */
    if (c == 'B' || c == 'b') {
        char digit = *(p + 1);
        if (digit >= '0' && digit <= '3') {
            do_bank_switch(bank_pcr[(uint8_t)(digit - '0')]);
            /* never returns for banks 0–2; bank 3 resets the board */
        }
        return;
    }

    /* ── L — load S-records ─────────────────────────────────────────────── */
    if (c == 'L' || c == 'l') {
        uint16_t entry;
        if (srec_load(&entry) == 0 && entry != 0) {
            serial_puts("Entry: ");
            serial_puthex16(entry);
            serial_putcrlf();
        }
        return;
    }

    /* ── Hex address command ────────────────────────────────────────────── */
    p = parse_hex(p, &addr1);
    if (!p)
        return;

    c = *p;

    /* AAAA.BBBB — examine range */
    if (c == '.') {
        p = parse_hex(p + 1, &addr2);
        if (p)
            examine_range(addr1, addr2);
        return;
    }

    /* AAAA: HH ... — store bytes */
    if (c == ':') {
        store_bytes(addr1, p + 1);
        return;
    }

    /* AAAAR — run */
    if (c == 'R' || c == 'r') {
        run_at(addr1);
        return;
    }

    /* AAAA — examine single byte */
    examine_range(addr1, addr1);
}

/* ── Main ────────────────────────────────────────────────────────────────── */

void main(void)
{
    serial_puts("\r\n\r\nSXB Monitor  Bank 1  (C monitor)\r\n");
    serial_puts("Type ? for help\r\n");

    while (1) {
        serial_puts("\r\nmonitor> ");
        if (read_line() == 0)
            continue;
        process_command();
    }
}
