#include "kwt1.h"
/* RV32 build-only layout checks, not a linker image or stack high-water test. */
typedef char device_context_is_40_bytes[sizeof(kwt1_device)==40?1:-1];
typedef char provider_context_is_16_bytes[sizeof(kwt1_provider)==16?1:-1];
typedef char packet_descriptor_is_8_bytes[sizeof(kwt1_packet)==8?1:-1];
