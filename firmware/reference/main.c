#include "kwt1.h"
#define ACC ((volatile uint32_t *)0x10000000u)
#define HOST ((volatile uint32_t *)0x10010000u)
extern int8_t __input[],__output[];extern uint8_t __packet[];
static int requested=-2;
static uint32_t hread(unsigned byte){return HOST[byte/4];}
static void hwrite(unsigned byte,uint32_t v){HOST[byte/4]=v;}
static int read32(void *ctx,uint32_t off,uint32_t *v){(void)ctx;*v=ACC[off/4];return (int)hread(32);}
static int write32(void *ctx,uint32_t off,uint32_t v){(void)ctx;ACC[off/4]=v;return (int)hread(32);}
static int cancelled(void *ctx){(void)ctx;return 0;}
static void idle(void *ctx,uint32_t cycles){(void)ctx;uint32_t t=hread(36);while((uint32_t)(hread(36)-t)<cycles)__asm__ volatile("nop");}
static int acquire(void *ctx,int layer,kwt1_packet *p){
 (void)ctx;if(requested==-2){hwrite(8,(uint32_t)layer);requested=layer;}
 if(requested!=layer)return -1;
 uint32_t status=hread(12);if(status==0)return KWT1_PENDING;if(status!=1)return -1;
 p->data=__packet;p->size=hread(16);return 0;
}
static void release(void *ctx,const kwt1_packet *p){(void)ctx;(void)p;hwrite(20,1);requested=-2;}
static void cancel(void *ctx){(void)ctx;hwrite(24,1);requested=-2;}
static uint64_t cycle(void){uint32_t lo,hi,hi2;do{__asm__ volatile("csrr %0,0xb80":"=r"(hi));__asm__ volatile("csrr %0,0xb00":"=r"(lo));__asm__ volatile("csrr %0,0xb80":"=r"(hi2));}while(hi!=hi2);return ((uint64_t)hi<<32)|lo;}
static uint64_t instret(void){uint32_t lo,hi;__asm__ volatile("csrr %0,0xb82":"=r"(hi));__asm__ volatile("csrr %0,0xb02":"=r"(lo));return ((uint64_t)hi<<32)|lo;}
static void publish64(unsigned off,uint64_t v){hwrite(off,(uint32_t)v);hwrite(off+4,(uint32_t)(v>>32));}
int main(void){
 kwt1_device d={0,read32,write32,2000000,cancelled,idle,64,0,0,0};kwt1_provider p={0,acquire,release,cancel};
 hwrite(76,sizeof(d));
#ifdef BOOT_SMOKE
 uint32_t id;if(read32(0,72,&id)||id!=0x4b575431u)hwrite(68,0xe003);
 hwrite(64,1);for(;;){}
#endif
 for(;;){
  uint32_t next=hread(0);if(next==0xffffffffu)break;if(!next){idle(0,64);continue;}
  uint64_t c0=cycle(),i0=instret();
  int rc=kwt1_run_provider(&d,&p,__input,__output);
  hwrite(28,(uint32_t)rc);publish64(80,cycle()-c0);publish64(88,instret()-i0);
  hwrite(40,(uint32_t)d.last_error);hwrite(44,(uint32_t)d.abort_error);
  if(rc==KWT1_RESET_REQUIRED){
   if(kwt1_run_provider(&d,&p,__input,__output)!=KWT1_RESET_REQUIRED||kwt1_abort(&d)!=KWT1_RESET_REQUIRED){hwrite(68,0xe001);for(;;){}}
   hwrite(48,1);if(kwt1_after_hard_reset(&d)){hwrite(68,0xe002);for(;;){}}
  }
  for(unsigned n=0;n<8;n++)hwrite(112+n*4,ACC[8+n]);
  hwrite(4,(uint32_t)rc);
 }
 hwrite(64,1);for(;;){}
}
