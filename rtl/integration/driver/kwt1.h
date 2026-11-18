#ifndef KWT1_H
#define KWT1_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Callbacks finish the entire response and bound their own wait. Return 0,
 * KWT1_IO, KWT1_TIMEOUT or KWT1_CANCELLED. An uncertain/accepted transaction
 * must be drained by the transport or cleared by external hardware reset.
 */
typedef int (*kwt1_read32)(void *, uint32_t offset, uint32_t *value);
typedef int (*kwt1_write32)(void *, uint32_t offset, uint32_t value);
typedef struct {void *opaque; kwt1_read32 read; kwt1_write32 write; uint32_t poll_limit;
 int (*cancelled)(void *);void (*idle)(void *,uint32_t cycles);
 uint32_t poll_backoff;
 int recovery_required,last_error,abort_error;} kwt1_device;
typedef struct {const uint8_t *data; size_t size;} kwt1_packet;
enum {KWT1_OK=0,KWT1_PENDING=1,KWT1_IO=-1,KWT1_TIMEOUT=-2,KWT1_HARDWARE=-3,KWT1_ARGUMENT=-4,KWT1_CANCELLED=-5,KWT1_SUPPLY=-6,KWT1_RESET_REQUIRED=-7};
/* acquire(-1)=common, acquire(0..11)=layer. Same request may return PENDING.
 * A successful lease remains valid until release. At most ONE lease exists.
 * cancel discards pending asynchronous supply after timeout/abort/error.
 * Backing buffer needs only 61728 bytes; thirteen resident arrays are unnecessary.
 */
typedef struct {void *opaque;int (*acquire)(void *,int,kwt1_packet *);
 void (*release)(void *,const kwt1_packet *);void (*cancel)(void *);} kwt1_provider;
int kwt1_run_provider(kwt1_device *,kwt1_provider *,const int8_t input[6336],int8_t output[6336]);
int kwt1_abort(kwt1_device *);
/* Only call AFTER integrator asserts physical reset and discards old bus
 * transactions. Verifies empty STATUS and ID, then clears quarantine.
 * A successful callback abort/STATUS is a confirmed software abort; failed
 * cleanup returns RESET_REQUIRED, preserving last_error and abort_error.
 */
int kwt1_after_hard_reset(kwt1_device *);
#ifdef __cplusplus
}
#endif
#endif
