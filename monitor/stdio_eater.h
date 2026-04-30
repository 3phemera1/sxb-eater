#ifndef STDIO_EATER_H
#define STDIO_EATER_H

#include <stdarg.h>
#include <stdint.h>

// Print formatted output to serial
int printf(const char *fmt, ...);
int sprintf(char *buf, const char *fmt, ...);
int scanf(const char *fmt, ...);

// Beep on VIA U3 PB7
void beep(int frequency_hz, int duration_ms);

#endif // STDIO_EATER_H
