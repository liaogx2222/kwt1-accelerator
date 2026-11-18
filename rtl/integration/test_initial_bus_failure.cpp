#include "driver/kwt1.h"
#include <array>
#include <cassert>
#include <cstdio>
struct Mock { bool broken=true,bad_id=false;unsigned accesses=0,acquires=0,releases=0,cancels=0; } m;
static int read(void *,uint32_t a,uint32_t *v){m.accesses++;if(m.broken)return KWT1_IO;*v=a==4?(1u<<9):m.bad_id?0:0x4b575431;return 0;}
static int write(void *,uint32_t,uint32_t){m.accesses++;return m.broken?KWT1_IO:0;}
static int acquire(void *,int,kwt1_packet *){m.acquires++;return KWT1_PENDING;}
static void release(void *,const kwt1_packet *){m.releases++;}
static void cancel(void *){m.cancels++;}
int main(){
 kwt1_device d={nullptr,read,write,8,nullptr,nullptr,64,0,0,0};kwt1_provider p={nullptr,acquire,release,cancel};
 std::array<int8_t,6336> in{},out{};
 assert(kwt1_run_provider(&d,&p,in.data(),out.data())==KWT1_RESET_REQUIRED);
 assert(d.last_error==KWT1_IO&&d.abort_error==KWT1_IO&&d.recovery_required&&m.acquires==0&&m.releases==0&&m.cancels==1);
 auto accesses=m.accesses;
 assert(kwt1_abort(&d)==KWT1_RESET_REQUIRED);
 assert(kwt1_run_provider(&d,&p,in.data(),out.data())==KWT1_RESET_REQUIRED&&m.accesses==accesses&&m.cancels==1);
 m.broken=false;m.bad_id=true;assert(kwt1_after_hard_reset(&d)==KWT1_RESET_REQUIRED&&d.recovery_required);
 m.bad_id=false;assert(kwt1_after_hard_reset(&d)==0&&!d.recovery_required&&!d.last_error&&!d.abort_error);
 assert(kwt1_abort(&d)==0);
 std::puts("PASS INITIAL BUS persistent-error/quarantine/no-new-I-O/wrong-ID/reset-confirmed");
}
