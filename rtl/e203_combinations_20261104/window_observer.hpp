// Host-only multi-task observer. Never drives DUT inputs or writes TCM storage.
#include "Vreference_top___024root.h"
static uint32_t shadow_pc=0;static bool shadow_known=false;
static uint64_t cycles_w[2]={},retired_w[2]={},phases[6]={},reads_w[2][7]={},writes_w[2][7]={};
static uint64_t pc_cycles_w[2][8192]={},pc_retired_w[2][8192]={};
static uint64_t unscoped_reads=0,unscoped_writes=0,last_finish_clock=8,pre_cycles=0,pre_reads=0,pre_writes=0;
static uint64_t verified_words=0,lease_bytes=0,first_itcm_clock=0,reset_requests=0;
struct TailEvent {uint64_t cycle;uint32_t address,pc;};static std::vector<TailEvent> tail_events;
static unsigned region(uint32_t address){
 uint32_t a=address-kRamBase;
 if(a<0x2000)return 0;if(a>=kInputOffset&&a<kInputOffset+6336)return 2;
 if(a>=kOutputOffset&&a<kOutputOffset+6336)return 3;
 if(a>=kPacketOffset&&a<kPacketOffset+61728)return 4;
 if(a>=kStackOffset&&a<kRamBytes)return 5;
 return a<kInputOffset?1:6;
}
static unsigned pc_index(uint32_t pc){
 if(pc>=kRamBase&&pc<kRamBase+0x2000)return (pc-kRamBase)/2;
 require(pc>=0x80000000u&&pc<0x80002000u,"observed PC outside image");return 4096+(pc-0x80000000u)/2;
}
static void observe_begin(){
 for(auto&v:cycles_w)v=0;for(auto&v:retired_w)v=0;for(auto&v:phases)v=0;
 for(unsigned w=0;w<2;w++){
  for(unsigned k=0;k<7;k++)reads_w[w][k]=writes_w[w][k]=0;
  for(unsigned k=0;k<8192;k++)pc_cycles_w[w][k]=pc_retired_w[w][k]=0;
 }
 require(lease_bytes==0,"old lease counter");verified_words=0;reset_requests=0;tail_events.clear();
 pre_cycles=begin_clock-last_finish_clock;pre_reads=unscoped_reads;pre_writes=unscoped_writes;unscoped_reads=unscoped_writes=0;
}
static void observe_tick(bool mtake,bool hrq,uint32_t ma,bool mread,uint32_t ha,bool hread){
 const auto*r=d.rootp;
 if(d.rst_n&&d.retired){
  require(shadow_known,"retirement without PC");unsigned off;
  if(shadow_pc>=0x80000000u&&shadow_pc<0x80002000u){off=0x1000+shadow_pc-0x80000000u;if(!first_itcm_clock)first_itcm_clock=clocks;}
  else{off=shadow_pc-kRamBase;require(off<0x2000,"external code range");}
  uint32_t instruction=uint32_t(ram[off])|(uint32_t(ram[off+1])<<8)|(uint32_t(ram[off+2])<<16)|(uint32_t(ram[off+3])<<24);
  uint32_t mask=(instruction&3)==3?~0u:65535u;
  require((r->reference_top__DOT__cpu__DOT__u_e203_cpu__DOT__u_e203_core__DOT__ifu_o_ir&mask)==(instruction&mask),"retired IR differs from load image");
 }
 if(r->reference_top__DOT__bridge__DOT__state==1&&r->reference_top__DOT__ar&&!r->reference_top__DOT__bridge__DOT__read&&(r->reference_top__DOT__bridge__DOT__addr&65535)==16){
  require(leased&&lease_bytes+4<=packet.size(),"DATA without lease");
  uint32_t value=uint32_t(packet[lease_bytes])|(uint32_t(packet[lease_bytes+1])<<8)|(uint32_t(packet[lease_bytes+2])<<16)|(uint32_t(packet[lease_bytes+3])<<24);
  require(value==r->reference_top__DOT__bridge__DOT__data,"DATA word mismatch");lease_bytes+=4;verified_words++;
 }
 if(hrq&&!hread&&(ha&65535)==20){require(lease_bytes==packet.size()||(int32_t(d.bus_rc)!=0&&lease_bytes<packet.size()),"early release without error");lease_bytes=0;}
 if(!active){if(mtake)(mread?unscoped_reads:unscoped_writes)++;}
 else{
  unsigned w=rc_event==999?0:1;cycles_w[w]++;if(d.retired)retired_w[w]++;
  if(shadow_known){unsigned index=pc_index(shadow_pc);pc_cycles_w[w][index]++;if(d.retired)pc_retired_w[w][index]++;}
  if(w==0){unsigned s=r->reference_top__DOT__accel__DOT__accel__DOT__state;
   unsigned p=!input_ready?0:(requested!=-2&&!leased)?1:leased?2:(s==1||s==2)?3:(s>=4&&s<=7)?4:5;phases[p]++;
  }
  if(mtake){(mread?reads_w:writes_w)[w][region(ma)]++;if(w&&mread)tail_events.push_back({clocks,ma,shadow_pc});}
  if(hrq&&!hread&&(ha&65535)==48)reset_requests++;
 }
 if(!d.rst_n)shadow_known=false;
 else if(r->reference_top__DOT__cpu__DOT__u_e203_cpu__DOT__u_e203_core__DOT__u_e203_ifu__DOT__u_e203_ifu_ifetch__DOT__ir_valid_set){shadow_pc=d.pc;shadow_known=true;}
}
static void observe_finish(){
 require(cycles_w[0]==end_clock-begin_clock&&retired_w[0]==end_retired-begin_retired,"main window conservation");
 require(cycles_w[1]==clocks-end_clock&&retired_w[1]==retired-end_retired,"tail window conservation");
 uint64_t n=0;for(auto v:phases)n+=v;require(n==cycles_w[0],"phase conservation");
 n=0;for(auto&w:reads_w)for(auto v:w)n+=v;require(n==ram_reads-begin_reads,"RAM read conservation");
 n=0;for(auto&w:writes_w)for(auto v:w)n+=v;require(n==ram_writes-begin_writes,"RAM write conservation");
 require(verified_words==d.parameter_words-start_params,"accepted DATA count");
 char filename[64];std::sprintf(filename,"window_job_%02u.txt",unsigned(ji));std::ofstream f(root+"/"+filename);
 f<<"boundaries "<<begin_clock<<" "<<end_clock<<" "<<clocks<<"\n";
 f<<"pre_job "<<pre_cycles<<" "<<pre_reads<<" "<<pre_writes<<" "<<first_itcm_clock<<"\n";
 f<<"words "<<verified_words<<"\nerrors "<<last_error<<" "<<abort_error<<" "<<reset_requests<<"\n";
 for(unsigned w=0;w<2;w++){
  f<<"window "<<w<<" "<<cycles_w[w]<<" "<<retired_w[w]<<"\n";
  for(unsigned k=0;k<7;k++)f<<"ram "<<w<<" "<<k<<" "<<reads_w[w][k]<<" "<<writes_w[w][k]<<"\n";
  for(unsigned k=0;k<8192;k++)if(pc_cycles_w[w][k]||pc_retired_w[w][k])f<<"pc "<<w<<" "<<(k<4096?kRamBase+k*2:0x80000000u+(k-4096)*2)<<" "<<pc_cycles_w[w][k]<<" "<<pc_retired_w[w][k]<<"\n";
 }
 for(unsigned k=0;k<6;k++)f<<"phase "<<k<<" "<<phases[k]<<"\n";
 for(auto v:tail_events)f<<"tail_read "<<v.cycle<<" "<<v.address<<" "<<v.pc<<"\n";
 last_finish_clock=clocks;
}
