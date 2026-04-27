#ifndef UTIL_H
#define UTIL_H

/*
 * util.h - Hex parse/display helpers for the bank 1 monitor
 */

#include <stdint.h>

/*
 * parse_hex(p, out) — parse a hex string at *p into *out.
 *
 * Reads uppercase and lowercase hex digits.  Stops at the first non-hex
 * character.  Returns a pointer to that stopping character, or NULL if no
 * hex digits were found at all.
 *
 * *out is only modified when the return value is non-NULL.
 */
const char *parse_hex(const char *p, uint16_t *out);

/*
 * skip_spaces(p) — advance p past any ASCII space characters.
 * Returns the updated pointer (may be unchanged if *p is not a space).
 */
const char *skip_spaces(const char *p);

#endif /* UTIL_H */
