#ifndef KWT1_H
#define KWT1_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Callbacks complete the whole bus response; return zero on success. */
typedef int (*kwt1_read32)(void *, uint32_t offset, uint32_t *value);
typedef int (*kwt1_write32)(void *, uint32_t offset, uint32_t value);
typedef struct {void *opaque; kwt1_read32 read; kwt1_write32 write; uint32_t poll_limit;} kwt1_device;
typedef struct {const uint8_t *data; size_t size;} kwt1_packet;
enum {KWT1_OK=0,KWT1_IO=-1,KWT1_TIMEOUT=-2,KWT1_HARDWARE=-3,KWT1_ARGUMENT=-4};
/* Cold task: common+12 canonical packets, 99x64 S8 input/output. No CPU math. */
int kwt1_run(kwt1_device *,const kwt1_packet packets[13],const int8_t input[6336],int8_t output[6336]);
int kwt1_abort(kwt1_device *);
#ifdef __cplusplus
}
#endif
#endif
