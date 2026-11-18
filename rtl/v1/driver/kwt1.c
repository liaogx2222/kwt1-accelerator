#include "kwt1.h"
static uint32_t le32(const uint8_t *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static int wait_status(kwt1_device *d,uint32_t mask,uint32_t *status){
 uint32_t n,s;
 for(n=0;n<d->poll_limit;n++){
  if(d->read(d->opaque,4,&s))return KWT1_IO;
  if(s&4)return KWT1_HARDWARE;
  if((s&mask)==mask){if(status)*status=s;return 0;}
 }
 return KWT1_TIMEOUT;
}
static int put(kwt1_device *d,uint32_t reg,uint32_t value){return d->write(d->opaque,reg,value)?KWT1_IO:0;}
int kwt1_abort(kwt1_device *d){if(!d||!d->read||!d->write)return KWT1_ARGUMENT;return put(d,0,2);}
static int packet(kwt1_device *d,const kwt1_packet *p,uint32_t frame){
 size_t k;int rc;
 if((rc=wait_status(d,1u<<9,0)))return rc;
 if((rc=put(d,8,frame)))return rc;
 for(k=0;k<p->size;k+=4){
  if((rc=wait_status(d,1u<<10,0)))return rc;
  if(k+4==p->size&&(rc=put(d,12,1)))return rc;
  if((rc=put(d,16,le32(p->data+k))))return rc;
 }
 return 0;
}
int kwt1_run(kwt1_device *d,const kwt1_packet p[13],const int8_t input[6336],int8_t output[6336]){
 size_t k;unsigned l;uint32_t s,w;int rc;
 if(!d||!d->read||!d->write||!d->poll_limit||!p||!input||!output)return KWT1_ARGUMENT;
 for(l=0;l<13;l++)if(!p[l].data||p[l].size!=(l?61728u:16576u))return KWT1_ARGUMENT;
 for(k=0;k<6336;k++)if(input[k]==-128)return KWT1_ARGUMENT;
 if((rc=kwt1_abort(d)))return rc;
 if((rc=packet(d,p,256)))return rc;
 if((rc=packet(d,p+1,0)))return rc;
 for(k=0;k<6336;k+=4){
  if((rc=wait_status(d,1u<<11,0)))return rc;
  if(k+4==6336&&(rc=put(d,12,1)))return rc;
  if((rc=put(d,20,le32((const uint8_t *)input+k))))return rc;
 }
 if((rc=wait_status(d,1u<<8,0)))return rc;
 if((rc=put(d,0,1)))return rc;
 for(l=1;l<12;l++){
  if((rc=wait_status(d,1u<<6,&s)))return rc;
  if(((s>>16)&15)!=l)return KWT1_HARDWARE;
  if((rc=packet(d,p+l+1,l)))return rc;
 }
 for(k=0;k<6336;k+=4){
  if((rc=wait_status(d,1u<<12,0)))return rc;
  if(d->read(d->opaque,24,&w))return KWT1_IO;
  output[k]=(int8_t)w;output[k+1]=(int8_t)(w>>8);output[k+2]=(int8_t)(w>>16);output[k+3]=(int8_t)(w>>24);
 }
 return wait_status(d,2,0);
}
