/*
 * hello.c - Hello World example for the bank 1 C monitor
 *
 * This program is loaded into RAM by the C monitor's 'L' command and
 * executed with the 'AAAAAR' command.  It uses the same serial I/O layer
 * as the monitor itself (serial.s, shared at build time).
 *
 * Build:  make hello           → build/hello.bin  (load address $4000)
 * Upload: python3 tools/upload.py <port> build/hello.bin --addr 4000 --run
 */

#include "serial.h"
#include <stdint.h>

void main(void) {
  char foo[25];
  int i = 0;
  serial_puts("Hello, World!\r\n");
  serial_puts("Enter your name: ");
  for (i = 0; i < 24;) {
    char c = serial_getchar();
    if (c == '\r' || c == '\n') {
      /* Skip stray CR/LF left in the FIFO from the monitor's "4000R<Enter>"
       * dispatch (terminal sends \r\n; monitor consumes \r and returns
       * before the \n arrives). Only treat CR/LF as end-of-input once we've
       * actually received some characters. */
      if (i == 0)
        continue;
      break;
    }
    serial_putchar(c); /* echo */
    foo[i++] = c;
  }
  foo[i] = 0;
  serial_puts("\r\nyou entered ");
  serial_puts(foo);
  serial_puts("\r\n");
}
