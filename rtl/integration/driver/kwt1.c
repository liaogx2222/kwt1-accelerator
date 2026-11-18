#include "kwt1.h"

static uint32_t le32(const uint8_t *p) {
 return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);
}
static int bus_error(int rc) {
 return rc==KWT1_TIMEOUT||rc==KWT1_CANCELLED?rc:KWT1_IO;
}
static int cancelled(kwt1_device *d) {
 return d->cancelled&&d->cancelled(d->opaque);
}
static void backoff(kwt1_device *d) {
 if(d->idle)d->idle(d->opaque,d->poll_backoff);
}
static int wait_status(kwt1_device *d,uint32_t mask,uint32_t *status) {
 uint32_t n,s;int rc;
 for(n=0;n<d->poll_limit;n++) {
  if(cancelled(d))return KWT1_CANCELLED;
  rc=d->read(d->opaque,4,&s);if(rc)return bus_error(rc);
  if(s&4)return KWT1_HARDWARE;
  if((s&mask)==mask){if(status)*status=s;return KWT1_OK;}
  backoff(d);
 }
 return KWT1_TIMEOUT;
}
static int put(kwt1_device *d,uint32_t reg,uint32_t value) {
 int rc;if(cancelled(d))return KWT1_CANCELLED;
 rc=d->write(d->opaque,reg,value);return rc?bus_error(rc):KWT1_OK;
}
/* Recovery must ignore the driver's cancellation token. The platform's
 * callback must permit recovery traffic, or fail so we quarantine safely. */
static int abort_confirm(kwt1_device *d) {
 uint32_t s;int rc=d->write(d->opaque,0,2);
 if(rc)return bus_error(rc);
 rc=d->read(d->opaque,4,&s);if(rc)return bus_error(rc);
 return (s&255)||!(s&(1u<<9))?KWT1_HARDWARE:KWT1_OK;
}
int kwt1_abort(kwt1_device *d) {
 int rc;if(!d||!d->read||!d->write)return KWT1_ARGUMENT;
 if(d->recovery_required)return KWT1_RESET_REQUIRED;
 rc=abort_confirm(d);d->abort_error=rc;d->recovery_required=rc!=0;
 return rc?KWT1_RESET_REQUIRED:KWT1_OK;
}
int kwt1_after_hard_reset(kwt1_device *d) {
 uint32_t s,id;int rc;
 if(!d||!d->read||!d->write)return KWT1_ARGUMENT;
 rc=d->read(d->opaque,4,&s);
 if(!rc)rc=d->read(d->opaque,72,&id);
 if(rc||(s&255)||!(s&(1u<<9))||id!=0x4b575431u){d->recovery_required=1;return KWT1_RESET_REQUIRED;}
 d->recovery_required=d->last_error=d->abort_error=0;return KWT1_OK;
}
static int packet(kwt1_device *d,const kwt1_packet *p,uint32_t frame) {
 size_t k;int rc;
 if((rc=wait_status(d,1u<<9,0)))return rc;
 if((rc=put(d,8,frame)))return rc;
 for(k=0;k<p->size;k+=4) {
  /* DATA request is held until cfg_ready. No per-word STATUS read. */
  if(k+4==p->size&&(rc=put(d,12,1)))return rc;
  if((rc=put(d,16,le32(p->data+k))))return rc;
 }
 return KWT1_OK;
}
static int supply(kwt1_device *d,kwt1_provider *provider,int layer) {
 kwt1_packet p={0,0};uint32_t n;int rc;
 for(n=0;n<d->poll_limit;n++) {
  if(cancelled(d))return KWT1_CANCELLED;
  rc=provider->acquire(provider->opaque,layer,&p);
  if(rc==KWT1_PENDING){backoff(d);continue;}
  if(rc)return KWT1_SUPPLY;
  if(!p.data||p.size!=(layer<0?16576u:61728u)) {
   provider->release(provider->opaque,&p);return KWT1_ARGUMENT;
  }
  rc=packet(d,&p,layer<0?256u:(uint32_t)layer);
  /* Always wait for drain + CRC publication before releasing the lease. */
  if(!rc)rc=wait_status(d,layer<0?(1u<<3):(1u<<5),0);
  provider->release(provider->opaque,&p);return rc;
 }
 return KWT1_TIMEOUT;
}
static int execute(kwt1_device *d,kwt1_provider *provider,const int8_t input[6336],int8_t output[6336]) {
 size_t k;unsigned l;uint32_t s,w;int rc;
 for(k=0;k<6336;k++)if(input[k]==-128)return KWT1_ARGUMENT;
 if((rc=abort_confirm(d)))return rc;
 if((rc=supply(d,provider,-1)))return rc;
 if((rc=supply(d,provider,0)))return rc;
 for(k=0;k<6336;k+=4) {
  if(k+4==6336&&(rc=put(d,12,1)))return rc;
  if((rc=put(d,20,le32((const uint8_t *)input+k))))return rc;
 }
 if((rc=wait_status(d,1u<<8,0)))return rc;
 if((rc=put(d,0,1)))return rc;
 for(l=1;l<12;l++) {
  if((rc=wait_status(d,1u<<6,&s)))return rc;
  if(((s>>16)&15)!=l)return KWT1_HARDWARE;
  if((rc=supply(d,provider,(int)l)))return rc;
 }
 if((rc=wait_status(d,1u<<12,0)))return rc;
 for(k=0;k<6336;k+=4) {
  if(cancelled(d))return KWT1_CANCELLED;
  rc=d->read(d->opaque,24,&w);if(rc)return bus_error(rc);
  output[k]=(int8_t)w;output[k+1]=(int8_t)(w>>8);output[k+2]=(int8_t)(w>>16);output[k+3]=(int8_t)(w>>24);
 }
 return wait_status(d,2,0);
}
int kwt1_run_provider(kwt1_device *d,kwt1_provider *provider,const int8_t input[6336],int8_t output[6336]) {
 int rc,cleanup;
 if(!d||!d->read||!d->write||!d->poll_limit||!provider||!provider->acquire||!provider->release||!provider->cancel||!input||!output)return KWT1_ARGUMENT;
 if(d->recovery_required)return KWT1_RESET_REQUIRED;
 rc=execute(d,provider,input,output);d->last_error=rc;d->abort_error=0;
 if(!rc)return KWT1_OK;
 cleanup=abort_confirm(d);provider->cancel(provider->opaque);d->abort_error=cleanup;
 if(cleanup){d->recovery_required=1;return KWT1_RESET_REQUIRED;}
 return rc;
}
