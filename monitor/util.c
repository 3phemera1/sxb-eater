#include "util.h"

const char *parse_hex(const char *p, uint16_t *out)
{
    uint16_t val    = 0;
    uint8_t  digits = 0;
    char     c;

    while (1) {
        c = *p;
        if      (c >= '0' && c <= '9') val = (uint16_t)((val << 4) | (uint8_t)(c - '0'));
        else if (c >= 'A' && c <= 'F') val = (uint16_t)((val << 4) | (uint8_t)(c - 'A' + 10));
        else if (c >= 'a' && c <= 'f') val = (uint16_t)((val << 4) | (uint8_t)(c - 'a' + 10));
        else break;
        ++digits;
        ++p;
    }

    if (digits == 0)
        return 0;

    *out = val;
    return p;
}

const char *skip_spaces(const char *p)
{
    while (*p == ' ')
        ++p;
    return p;
}
