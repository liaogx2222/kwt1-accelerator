#ifndef KWT_PLATFORM_WORD_ACCESS_H
#define KWT_PLATFORM_WORD_ACCESS_H
#include <stdint.h>
#include <stddef.h>
#if !defined(__GNUC__) || __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error This measured path requires GCC-compatible may_alias and little endian
#endif
typedef uint32_t kwt_alias_word __attribute__((__may_alias__));
static inline int kwt_word_contract(const void *p,size_t size){
 return p && !((uintptr_t)p&3u) && size && !(size&3u);
}
/* Caller checked alignment/length before any access. The provider freezes
 * the backing bytes until release; GCC may_alias permits byte storage aliases.
 * The generic driver's byte helper remains the fallback implementation. */
static inline uint32_t kwt_packet_word(const uint8_t *p){return *(const kwt_alias_word *)p;}
#endif
