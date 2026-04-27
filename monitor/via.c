#include "via.h"

void via_t1_freerun(uint16_t latch)
{
    /* Enable PB7 as output */
    *VIA_DDRB |= 0x80;

    /* ACR: T1 free-run mode + PB7 controlled by T1 */
    *VIA_ACR = (*VIA_ACR & 0x3F) | VIA_ACR_T1_FREERUN | VIA_ACR_PB7_T1;

    /* Load latch — writing T1CH starts the counter */
    *VIA_T1LL = (uint8_t)(latch & 0xFF);
    *VIA_T1CH = (uint8_t)(latch >> 8);
}

void via_t1_stop(void)
{
    /* One-shot mode + no PB7 output disables the square wave */
    *VIA_ACR &= ~(VIA_ACR_T1_FREERUN | VIA_ACR_PB7_T1);

    /* Tri-state PB7 */
    *VIA_DDRB &= ~0x80;
}

void via_t2_oneshot(uint16_t count)
{
    /* Write low byte first, then high byte starts the countdown */
    *VIA_T2CL = (uint8_t)(count & 0xFF);
    *VIA_T2CH = (uint8_t)(count >> 8);
}
