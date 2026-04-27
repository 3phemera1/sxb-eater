#include "pia.h"

void pia_init(void)
{
    /* Select DDR access for both ports (CR bit 2 = 0) */
    *PIA_CRA = PIA_CR_DDR_ACCESS;
    *PIA_CRB = PIA_CR_DDR_ACCESS;

    /* Set both ports to all-inputs (DDR = 0x00) */
    *PIA_PA = 0x00;
    *PIA_PB = 0x00;

    /* Switch to data register access (CR bit 2 = 1) */
    *PIA_CRA = PIA_CR_DATA_ACCESS;
    *PIA_CRB = PIA_CR_DATA_ACCESS;
}

void __fastcall__ pia_set_ddra(uint8_t ddr)
{
    uint8_t cra = *PIA_CRA;
    *PIA_CRA = cra & ~PIA_CR_DATA_ACCESS;  /* select DDR */
    *PIA_PA  = ddr;
    *PIA_CRA = cra | PIA_CR_DATA_ACCESS;   /* back to data */
}

void __fastcall__ pia_set_ddrb(uint8_t ddr)
{
    uint8_t crb = *PIA_CRB;
    *PIA_CRB = crb & ~PIA_CR_DATA_ACCESS;
    *PIA_PB  = ddr;
    *PIA_CRB = crb | PIA_CR_DATA_ACCESS;
}

uint8_t pia_read_a(void)
{
    *PIA_CRA |= PIA_CR_DATA_ACCESS;
    return *PIA_PA;
}

uint8_t pia_read_b(void)
{
    *PIA_CRB |= PIA_CR_DATA_ACCESS;
    return *PIA_PB;
}

void __fastcall__ pia_write_a(uint8_t val)
{
    *PIA_CRA |= PIA_CR_DATA_ACCESS;
    *PIA_PA   = val;
}

void __fastcall__ pia_write_b(uint8_t val)
{
    *PIA_CRB |= PIA_CR_DATA_ACCESS;
    *PIA_PB   = val;
}
