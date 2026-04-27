#include "acia.h"

void acia_init(uint8_t ctrl, uint8_t cmd)
{
    /* Software reset: read status then data register */
    (void)*ACIA_STATUS;
    (void)*ACIA_DATA;

    *ACIA_CTRL = ctrl;
    *ACIA_CMD  = cmd;
}

void __fastcall__ acia_putchar(char c)
{
    /*
     * W65C51 silicon bug: TDRE (TX-data-register-empty) flag in the status
     * register is unreliable.  Use a fixed delay loop sized for the slowest
     * supported baud rate (9600).  One character period at 9600 8N1 is
     * ~1.04 ms ≈ 8300 cycles at 8 MHz.  The inner loop here is ~10 cycles,
     * so 900 iterations ≈ 9000 cycles — safely longer than one character.
     */
    volatile uint16_t delay;
    *ACIA_DATA = c;
    for (delay = 900; delay != 0; --delay)
        ;
}

char acia_getchar(void)
{
    while (!acia_rx_ready())
        ;
    return (char)*ACIA_DATA;
}
