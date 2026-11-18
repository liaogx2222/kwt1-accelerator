#include "Vkwt1_mmio.h"
#include "verilated.h"
#ifdef LEGACY_DRIVER
#include "../v2/driver/kwt1.h"
#else
#include "driver/kwt1.h"
#endif
#include <array>
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>
#include <stdexcept>
static Vkwt1_mmio d;static uint64_t ticks=0,epoch=0,transactions=0,tx_epoch=0;static size_t output_reads=0;
static std::string root,mode;static unsigned cpu_cost=0,supply_cost=0,supply_latency=0;
static bool fault_tests=false;static int injection=0;static size_t cfg_writes=0;
static bool freeze_memory=false,wedged=false,abort_broken=false,confirm_broken=false,cancel_seen=false,cleanup_mode=false;
static uint64_t accepted=0,responded=0,abandoned=0,status_reads=0,payload_status=0,param_words=0,input_words=0,result_words=0,request_wait=0,response_wait=0,idle_cycles=0,idle_calls=0;
static bool payload=false,last_data=false;static unsigned blocked_wait=0;
static std::ofstream faults_log;
// Entire target shared SRAM, including declared firmware/stack reservations.
static std::array<uint8_t,512*1024> shared;
static const size_t IN_BASE=0,OUT_BASE=8192,BUFFER=16384,CAPACITY=61728;
static const size_t FIRMWARE=131072,FIRMWARE_SIZE=131072,STACK=507904,STACK_SIZE=16384;
double sc_time_stamp(){return double(ticks*10);}
static void require(bool b,const char *s){if(!b)throw std::runtime_error(s);}
static bool tick(){
 auto t=ticks-epoch;d.clk=0;d.core_enable=mode!="stress"||(t%11!=0&&t%17!=0);d.mem_enable=!freeze_memory&&(mode!="stress"||t%7!=0);d.eval();bool ready=d.req_ready;
 d.clk=1;d.eval();ticks++;return ready;
}
static int transact(bool write,uint32_t addr,uint32_t data,uint32_t *out,unsigned strobe=15){
 bool abort_write=write&&addr==0&&data==2;
 if(abort_write)cleanup_mode=true;
 if(wedged||(abort_write&&abort_broken)){for(int k=0;k<32;k++)tick();return injection==12?-1:-2;}
 if(!write&&addr==4&&confirm_broken&&cleanup_mode){confirm_broken=false;return -1;}
 d.req_valid=1;d.req_write=write;d.req_addr=addr;d.req_wdata=data;d.req_wstrb=strobe;d.resp_ready=0;
 unsigned watchdog=0;bool injecting_data=write&&addr==16&&cfg_writes==64;
 if(injecting_data&&(injection==9||injection==14))freeze_memory=true;
 while(!tick()){
  request_wait++;watchdog++;
  if(injecting_data&&injection==9&&watchdog==8){d.req_valid=0;freeze_memory=false;cancel_seen=true;blocked_wait=watchdog;return -5;}
  if(watchdog==(injection==14?32u:1000000u)){d.req_valid=0;freeze_memory=false;blocked_wait=watchdog;return -2;}
 }
 accepted++;d.req_valid=0;watchdog=0;
 if(injecting_data&&injection==7){
  for(int k=0;k<32;k++){tick();response_wait++;}wedged=true;abandoned++;return -2;
 }
 if(injecting_data&&injection==10){
  for(int k=0;k<8;k++){tick();response_wait++;}
  require(d.resp_valid,"cancel accepted response must drain");d.resp_ready=1;tick();d.resp_ready=0;responded++;cancel_seen=true;blocked_wait=8;return -5;
 }
 while(!d.resp_valid){tick();response_wait++;if(++watchdog==1000000){abandoned++;return -2;}}
 auto r=d.resp_rdata;auto e=d.resp_error;
 bool final_read=!write&&addr==24&&++output_reads==1584;
 unsigned hold=final_read?20:mode=="stress"&&(transactions-tx_epoch)%17==0?5:0;
 for(unsigned k=0;k<hold;k++){tick();require(d.resp_valid&&d.resp_rdata==r&&d.resp_error==e,"held bus response changed");if(final_read)require(!d.irq,"completion before final response ACK");}
 d.resp_ready=1;tick();d.resp_ready=0;responded++;transactions++;for(unsigned k=0;k<cpu_cost;k++)tick();
 if(write&&addr==8)payload=true;
 if(write&&addr==12)last_data=data==1;
 if(write&&addr==16){param_words++;if(last_data){payload=false;last_data=false;}}
 if(write&&addr==20){input_words++;last_data=false;}
 if(abort_write){payload=false;last_data=false;}
 if(!write&&addr==4){status_reads++;if(payload)payload_status++;cleanup_mode=false;}
 if(!write&&addr==24)result_words++;
 if(injecting_data&&injection==11)e=1;
 if(injecting_data&&injection==12){e=1;wedged=true;}
 if(out)*out=r;return e?-1:0;
}
static int read32(void *,uint32_t a,uint32_t *v){return transact(false,a,0,v);}
static int write32(void *,uint32_t a,uint32_t v){
 if(a==16)cfg_writes++;
 if(a==16&&cfg_writes==64&&(injection==5||injection==8||injection==13)){abort_broken=injection==8;confirm_broken=injection==13;return -1;}
 return transact(true,a,v,nullptr);
}
static int cancelled(void *){return injection==4&&ticks-epoch>300000;}
#ifdef LEGACY_DRIVER
static void idle(void *){idle_calls++;for(unsigned k=0;k<1+cpu_cost;k++){tick();idle_cycles++;}}
#else
static void idle(void *,uint32_t cycles){idle_calls++;for(unsigned k=0;k<cycles+cpu_cost;k++){tick();idle_cycles++;}}
#endif
static void reset(){d.abort_hw=1;d.req_valid=d.resp_ready=0;for(int k=0;k<3;k++)tick();d.rst_n=1;d.abort_hw=0;for(int k=0;k<5;k++)tick();output_reads=0;}
static std::vector<uint32_t> words(const std::string &name){std::ifstream f(name);require(bool(f),"missing hex");std::vector<uint32_t> v;uint32_t x;while(f>>std::hex>>x)v.push_back(x);return v;}
static std::vector<uint8_t> bytes(const std::vector<uint32_t> &v){std::vector<uint8_t> b;for(auto w:v)for(int k=0;k<4;k++)b.push_back(w>>(8*k));return b;}
struct Provider{
 int pending=-2,next=-1;bool leased=false;uint64_t ready_at=0;unsigned acquired=0,released=0,cancelled=0,peak=0,polls=0;
 void begin(){require(!leased,"lease across cold task");pending=-2;next=-1;polls=0;}
} provider;
static int acquire(void *,int layer,kwt1_packet *p){
 require(!provider.leased,"two packets resident at once");require(layer==provider.next,"provider layer order");provider.polls++;
 if(injection==1)return KWT1_PENDING;
 if(injection==2&&layer==3)return -1;
 if(provider.pending==-2){provider.pending=layer;provider.ready_at=ticks+supply_latency+uint64_t(layer<0?4144:15432)*supply_cost;}
 require(provider.pending==layer,"asynchronous request changed");if(ticks<provider.ready_at)return KWT1_PENDING;
 char file[64];if(layer<0)std::sprintf(file,"common.bin.hex");else std::sprintf(file,"layer_%02d.bin.hex",layer);
 // Only this packet enters the single target buffer. No resident p[13].
 std::ifstream f(root+"/"+file);require(bool(f),"missing packet file");uint32_t w;size_t size=0;
 while(f>>std::hex>>w){require(size+4<=CAPACITY,"provider overflows shared buffer");for(int z=0;z<4;z++)shared[BUFFER+size++]=w>>(8*z);}
 require(size==(layer<0?16576u:61728u),"canonical packet length");
 if(injection==3&&layer==0)shared[BUFFER+size-1]^=1;
 provider.leased=true;provider.acquired++;provider.peak=std::max(provider.peak,unsigned(size));
 p->data=shared.data()+BUFFER;p->size=injection==6?size-4:size;return 0;
}
static void release(void *,const kwt1_packet *p){
 require(provider.leased&&p->data==shared.data()+BUFFER,"invalid/double release");provider.leased=false;provider.released++;provider.pending=-2;provider.next++;
 std::fill(shared.begin()+BUFFER,shared.begin()+BUFFER+CAPACITY,0xa5);
}
static void cancel_supply(void *){require(!provider.leased,"lease not released on error");provider.pending=-2;provider.cancelled++;}
static uint64_t counter(uint32_t a){uint32_t lo,hi;require(!read32(nullptr,a,&lo)&&!read32(nullptr,a+4,&hi),"counter read");return lo|uint64_t(hi)<<32;}
static int task(kwt1_device &device,kwt1_provider &supply,int id,std::ofstream &metrics,bool save){
 char file[64];std::sprintf(file,"input_%03d.hex",id);auto input=bytes(words(root+"/"+file));std::sprintf(file,"expected_%03d.hex",id);auto expected=bytes(words(root+"/"+file));
 require(input.size()==6336&&expected.size()==6336,"tensor length");
 provider.begin();unsigned start_acquired=provider.acquired,start_released=provider.released;output_reads=0;cfg_writes=0;epoch=ticks;tx_epoch=transactions;uint64_t tx0=transactions;
 accepted=responded=abandoned=status_reads=payload_status=param_words=input_words=result_words=request_wait=response_wait=idle_cycles=idle_calls=0;payload=last_data=false;blocked_wait=0;
 // Include source-to-shared input arrival in the same outer window as packets.
 // Host fixture/golden storage belongs to the testbench, not the target SRAM.
 for(size_t k=0;k<6336;k+=4){for(unsigned c=0;c<supply_cost;c++)tick();for(int z=0;z<4;z++)shared[IN_BASE+k+z]=input[k+z];}
 std::fill(shared.begin()+OUT_BASE,shared.begin()+OUT_BASE+6336,0x80);
 int rc=kwt1_run_provider(&device,&supply,(int8_t *)shared.data()+IN_BASE,(int8_t *)shared.data()+OUT_BASE);uint64_t outer=ticks-epoch;
 require(!provider.leased,"leaked lease");
 if(rc)return rc;
 require(accepted==responded&&abandoned==0,"normal accepted/response mismatch");require(param_words==189328&&input_words==1584&&result_words==1584,"missing/duplicated DATA words");
 require(provider.acquired-start_acquired==13&&provider.released-start_released==13&&provider.next==12,"cold packet sequence/count");require(d.irq,"completion IRQ");
 for(size_t k=0;k<6336;k++)if(shared[OUT_BASE+k]!=expected[k]){std::fprintf(stderr,"MISMATCH id=%d code=%u got=%d expected=%d\n",id,unsigned(k),(int8_t)shared[OUT_BASE+k],(int8_t)expected[k]);throw std::runtime_error("output mismatch");}
 uint64_t tx_end=transactions;auto cycles=counter(32),compute=counter(40),reads=counter(48),writes=counter(56),stalls=counter(64);
 if(save){
  std::sprintf(file,"provider_observed_%03d.hex",id);std::ofstream f(root+"/"+file);
  for(int k=0;k<6336;k+=4){char line[16];uint32_t w=0;for(int z=0;z<4;z++)w|=uint32_t(shared[OUT_BASE+k+z])<<(8*z);std::sprintf(line,"%08x",w);f<<line<<"\n";}
  metrics<<id<<" "<<cycles<<" "<<compute<<" "<<reads<<" "<<writes<<" "<<stalls<<" "<<outer<<" "<<tx_end-tx0<<" "<<provider.acquired-start_acquired<<" "<<provider.peak<<" "<<provider.polls<<" "<<status_reads<<" "<<payload_status<<" "<<param_words<<" "<<input_words<<" "<<result_words<<" "<<request_wait<<" "<<response_wait<<" "<<idle_cycles<<" "<<idle_calls<<"\n";metrics.flush();
 }
 std::printf("CASE %d mode=%s cycles=%llu outer=%llu MAC-compute=%llu reads=%llu writes=%llu PASS\n",id,mode.c_str(),(unsigned long long)cycles,(unsigned long long)outer,(unsigned long long)compute,(unsigned long long)reads,(unsigned long long)writes);std::fflush(stdout);return 0;
}
int main(int argc,char **argv){
 try{
  require(argc>=3,"usage sim root mode cpu supply_beat supply_latency faults");Verilated::commandArgs(argc,argv);root=argv[1];mode=argv[2];cpu_cost=argc>3?std::stoul(argv[3]):0;supply_cost=argc>4?std::stoul(argv[4]):0;supply_latency=argc>5?std::stoul(argv[5]):0;fault_tests=argc>6&&std::string(argv[6])=="faults";
  require(BUFFER+CAPACITY<=FIRMWARE&&FIRMWARE+FIRMWARE_SIZE<=STACK&&STACK+STACK_SIZE<=shared.size(),"512KiB memory map");
  std::fill(shared.begin(),shared.end(),0xcc);reset();
  require(transact(false,3,0,nullptr)!=0,"unaligned read accepted");require(transact(true,12,1,nullptr,3)!=0,"partial write accepted");require(transact(false,0x100,0,nullptr)!=0,"bad address accepted");
  kwt1_device device={nullptr,read32,write32,10000000,cancelled,idle
#ifndef LEGACY_DRIVER
   ,64,0,0,0
#endif
  };kwt1_provider supply={nullptr,acquire,release,cancel_supply};std::ofstream metrics(root+"/provider_metrics.txt");
  if(fault_tests){
   faults_log.open(root+"/faults.txt");
   for(int fault=1;fault<=
#ifdef LEGACY_DRIVER
   6
#else
   14
#endif
   ;fault++){
    wedged=abort_broken=confirm_broken=cancel_seen=freeze_memory=cleanup_mode=false;
    injection=fault;auto cancels=provider.cancelled;device.poll_limit=fault==1?8:10000000;int rc=task(device,supply,0,metrics,false);
    int expected=fault==1||fault==14?KWT1_TIMEOUT:fault==2?KWT1_SUPPLY:fault==3?KWT1_HARDWARE:fault==4||fault==9||fault==10?KWT1_CANCELLED:fault==6?KWT1_ARGUMENT:KWT1_IO;
#ifndef LEGACY_DRIVER
    bool quarantined=fault==7||fault==8||fault==12||fault==13;
    if(quarantined){
     expected=KWT1_RESET_REQUIRED;require(device.recovery_required,"missing quarantine");
     int cause=fault==7?KWT1_TIMEOUT:KWT1_IO;require(device.last_error==cause&&device.abort_error!=0,"lost original or cleanup error");
     auto before_tx=transactions;auto before_acquire=provider.acquired;require(kwt1_run_provider(&device,&supply,(int8_t *)shared.data()+IN_BASE,(int8_t *)shared.data()+OUT_BASE)==KWT1_RESET_REQUIRED,"new task escaped quarantine");require(kwt1_abort(&device)==KWT1_RESET_REQUIRED,"software abort escaped hard-reset quarantine");require(transactions==before_tx&&provider.acquired==before_acquire,"blocked task performed I/O");
     if(fault==8)require(kwt1_after_hard_reset(&device)==KWT1_RESET_REQUIRED&&device.recovery_required,"partial loader incorrectly confirmed as empty");
    }
    if(fault==9||fault==10||fault==14)require(blocked_wait>0,"missing callback wait injection");
#endif
    faults_log<<fault<<" "<<rc<<" "<<blocked_wait<<" "<<abandoned;
#ifndef LEGACY_DRIVER
    faults_log<<" "<<device.last_error<<" "<<device.abort_error<<" "<<device.recovery_required;
#endif
    faults_log<<"\n";faults_log.flush();
    require(rc==expected,"provider failure result");require(provider.cancelled==cancels+1,"missing cancellation");injection=0;device.poll_limit=10000000;
    wedged=abort_broken=confirm_broken=cancel_seen=freeze_memory=cleanup_mode=false;
#ifndef LEGACY_DRIVER
    if(quarantined){reset();require(kwt1_after_hard_reset(&device)==0&&!device.recovery_required,"physical reset confirmation");}
#endif
    require(task(device,supply,0,metrics,false)==0,"cold recovery after provider fault");
   }
   std::puts("PROVIDER FAULTS PASS bounded cleanup, quarantine and full cold recoveries");
  }
  std::ifstream cases(root+"/cases.txt");int id,profile,count=0;
  while(cases>>id>>profile){require(task(device,supply,id,metrics,true)==0,"provider cold task");count++;}
  for(size_t k=FIRMWARE;k<FIRMWARE+FIRMWARE_SIZE;k++)require(shared[k]==0xcc,"firmware region corrupted");for(size_t k=STACK;k<STACK+STACK_SIZE;k++)require(shared[k]==0xcc,"stack region corrupted");
  std::printf("PASS PROVIDER cases=%d codes=%d peak_packet_bytes=%u shared_bytes=%u firmware_reserve=%u stack_reserve=%u\n",count,count*6336,provider.peak,unsigned(shared.size()),unsigned(FIRMWARE_SIZE),unsigned(STACK_SIZE));return 0;
 }catch(const std::exception &e){std::fprintf(stderr,"FAIL %s ticks=%llu mode=%s injection=%d\n",e.what(),(unsigned long long)ticks,mode.c_str(),injection);return 1;}
}
