#include "stdio_eater.h"
#include "serial.h"
#include "via.h"

static void delay_ms(int ms) {
    // crude busy-wait loop for ms delay (tuned for 1MHz)
    volatile long i;
    while (ms-- > 0) {
        for (i = 0; i < 50; ++i) { __asm__("nop"); }
    }
}

void beep(int frequency_hz, int duration_ms) {
    uint16_t latch;
    if (frequency_hz <= 0) return;
    latch = (uint16_t)(4000000UL / frequency_hz - 2);
    via_t1_freerun(latch);
    delay_ms(duration_ms);
    via_t1_stop();
}

static void putchar(char c) { serial_putchar(c); }

static void puts(const char *s) { serial_puts(s); }

// Forward declaration for vsprintf
static int vsprintf(char *buf, const char *fmt, va_list ap);

// Minimal printf: supports %s %c %d %x %u
int printf(const char *fmt, ...) {
    va_list ap;
    int count;
    va_start(ap, fmt);
    count = vsprintf(0, fmt, ap);
    va_end(ap);
    return count;
}

// Minimal sprintf: supports %s %c %d %x %u
int sprintf(char *buf, const char *fmt, ...) {
    va_list ap;
    int count;
    va_start(ap, fmt);
    count = vsprintf(buf, fmt, ap);
    va_end(ap);
    return count;
}

// Internal: output to serial or buffer
static int vsprintf(char *buf, const char *fmt, va_list ap) {
    char tmp[17];
    int count;
    char *out = buf;
    count = 0;
    while (*fmt) {
        if (*fmt != '%') {
            if (buf) *out++ = *fmt; else putchar(*fmt);
            ++count; ++fmt; continue;
        }
        ++fmt;
        switch (*fmt) {
        case 's': {
            const char *s = va_arg(ap, const char *);
            while (*s) { if (buf) *out++ = *s; else putchar(*s); ++count; ++s; }
            break;
        }
        case 'c': {
            char c = (char)va_arg(ap, int);
            if (buf) *out++ = c; else putchar(c); ++count;
            break;
        }
        case 'd': {
            int v;
            int neg;
            unsigned u;
            int i;
            int start;
            int j;
            v = va_arg(ap, int);
            neg = v < 0;
            u = neg ? -v : v;
            i = 0;
            if (neg) tmp[i++] = '-';
            start = i;
            do { tmp[i++] = '0' + (u % 10); u /= 10; } while (u);
            for (j = i-1; j >= start; --j) { if (buf) *out++ = tmp[j]; else putchar(tmp[j]); ++count; }
            break;
        }
        case 'u': {
            unsigned u;
            int i;
            int j;
            u = va_arg(ap, unsigned);
            i = 0;
            do { tmp[i++] = '0' + (u % 10); u /= 10; } while (u);
            for (j = i-1; j >= 0; --j) { if (buf) *out++ = tmp[j]; else putchar(tmp[j]); ++count; }
            break;
        }
        case 'x': {
            unsigned u;
            int i;
            int j;
            u = va_arg(ap, unsigned);
            i = 0;
            do { tmp[i++] = "0123456789ABCDEF"[u % 16]; u /= 16; } while (u);
            for (j = i-1; j >= 0; --j) { if (buf) *out++ = tmp[j]; else putchar(tmp[j]); ++count; }
            break;
        }
        default:
            if (buf) *out++ = *fmt; else putchar(*fmt); ++count;
        }
        ++fmt;
    }
    if (buf) *out = 0;
    return count;
}

// Minimal scanf: only %s and %d, reads from serial
int scanf(const char *fmt, ...) {
    va_list ap;
    int count;
    va_start(ap, fmt);
    count = 0;
    while (*fmt) {
        if (*fmt == '%') {
            ++fmt;
            switch (*fmt) {
            case 'd': {
                int *ip = va_arg(ap, int *);
                char buf[12], *p = buf; char c;
                // Read number
                do { c = serial_getchar(); } while (c < '0' || c > '9');
                while (c >= '0' && c <= '9') {
                    serial_putchar(c); /* echo digit */
                    *p++ = c;
                    c = serial_getchar();
                }
                *p = 0; *ip = 0;
                for (p = buf; *p; ++p) *ip = *ip * 10 + (*p - '0');
                ++count;
                break;
            }
            case 's': {
                char *sp = va_arg(ap, char *);
                char c;
                do { c = serial_getchar(); } while (c == ' ' || c == '\n' || c == '\r');
                while (c != ' ' && c != '\n' && c != '\r') {
                    serial_putchar(c); /* echo char */
                    *sp++ = c;
                    c = serial_getchar();
                }
                *sp = 0;
                ++count;
                break;
            }
            }
        }
        ++fmt;
    }
    va_end(ap);
    return count;
}
