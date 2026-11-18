// Host-only observer. No DUT input is assigned here.
#include "Vreference_top___024root.h"
static uint32_t shadow_pc=0;static bool shadow_known=false;
static uint64_t win_cycles[2]={},win_retired[2]={},phase_cycles[6]={};
static uint64_t win_reads[2][7]={},win_writes[2][7]={},win_pc_cycles[2][8192]={},win_pc_retired[2][8192]={};
static uint64_t before_reads=0,before_writes=0,verified_words=0,lease_word=0;
static uint64_t source_blocked[2]={},host_port[2]={};
static uint64_t first_itcm_cycle=0;static unsigned itcm_image_bytes=0;
struct TailRead {uint64_t cycle;uint32_t address,pc;};static std::vector<TailRead> tail_reads;
static unsigned region(uint32_t a){
 a-=kRamBase;
 if(a<0x2000)return 0;
 if(a>=kInputOffset&&a<kInputOffset+6336)return 2;
 if(a>=kOutputOffset&&a<kOutputOffset+6336)return 3;
 if(a>=kPacketOffset&&a<kPacketOffset+61728)return 4;
 if(a>=kStackOffset&&a<kRamBytes)return 5;
 if(a<kInputOffset)return 1;return 6;
}
static unsigned pc_index(uint32_t pc){
 if(pc>=kRamBase&&pc<kRamBase+0x2000)return (pc-kRamBase)/2;
 require(pc>=0x80000000u&&pc<0x80002000u,"observed PC outside linked code");return 4096+(pc-0x80000000u)/2;
}
static void observe_tick(bool mtake,bool hrq,uint32_t ma,bool mread,uint32_t ha,bool hread){
 const auto*r=d.rootp;
 if(d.rst_n&&d.retired){
  require(shadow_known,"unknown retiring PC");unsigned o;
  if(shadow_pc>=0x80000000u&&shadow_pc<0x80002000u){o=0x1000+shadow_pc-0x80000000u;if(!first_itcm_cycle)first_itcm_cycle=clocks;}
  else{o=shadow_pc-kRamBase;require(o<0x2000,"retired external PC range");}
  uint32_t instruction=uint32_t(ram[o])|(uint32_t(ram[o+1])<<8)|(uint32_t(ram[o+2])<<16)|(uint32_t(ram[o+3])<<24);
  uint32_t mask=(instruction&3)==3?~0u:65535u;
  require((r->reference_top__DOT__cpu__DOT__u_e203_cpu__DOT__u_e203_core__DOT__ifu_o_ir&mask)==(instruction&mask),"IR/source-image PC mismatch");
 }
 // Check the value of EVERY accepted DATA word against its leased host packet.
 if(r->reference_top__DOT__bridge__DOT__state==1&&r->reference_top__DOT__ar&&
    !r->reference_top__DOT__bridge__DOT__read&&(r->reference_top__DOT__bridge__DOT__addr&65535)==16){
  require(leased&&lease_word+4<=packet.size(),"DATA without valid lease");
  uint32_t v=uint32_t(packet[lease_word])|(uint32_t(packet[lease_word+1])<<8)|(uint32_t(packet[lease_word+2])<<16)|(uint32_t(packet[lease_word+3])<<24);
  require(r->reference_top__DOT__bridge__DOT__data==v,"DATA word differs from canonical packet");lease_word+=4;verified_words++;
 }
 if(hrq&&!hread&&(ha&65535)==20){
#ifdef FACTOR_REJECT
  require(lease_word==0,"rejected contract sent DATA");
#else
  require(lease_word==packet.size(),"release before complete packet");
#endif
  lease_word=0;
 }
 if(!active){if(mtake){if(mread)before_reads++;else before_writes++;}}
 else{
  unsigned w=rc_event==999?0:1;win_cycles[w]++;if(d.retired)win_retired[w]++;
  if(shadow_known){unsigned index=pc_index(shadow_pc);win_pc_cycles[w][index]++;if(d.retired)win_pc_retired[w][index]++;}
  if(!w){unsigned s=r->reference_top__DOT__accel__DOT__accel__DOT__state;
   unsigned p=!input_ready?0:(requested!=-2&&!leased)?1:leased?2:(s==1||s==2)?3:(s>=4&&s<=7)?4:5;phase_cycles[p]++;
  }
  if(mtake){(mread?win_reads:win_writes)[w][region(ma)]++;if(w&&mread)tail_reads.push_back({clocks,ma,shadow_pc});}
  if(d.mv&&!d.mr)source_blocked[w]++;if(source_port)host_port[w]++;
 }
 if(!d.rst_n)shadow_known=false;
 else if(r->reference_top__DOT__cpu__DOT__u_e203_cpu__DOT__u_e203_core__DOT__u_e203_ifu__DOT__u_e203_ifu_ifetch__DOT__ir_valid_set){shadow_pc=d.pc;shadow_known=true;}
}
static void observe_finish(){
 require(ji==0,"single-factor observer requires one task per run");
 require(win_cycles[0]==end_clock-begin_clock&&win_retired[0]==end_retired-begin_retired,"main clock/retirement window");
 require(win_cycles[1]==clocks-end_clock&&win_retired[1]==retired-end_retired,"report tail window");
 uint64_t n=0;for(auto v:phase_cycles)n+=v;require(n==win_cycles[0],"phase conservation");
 n=0;for(unsigned w=0;w<2;w++)for(unsigned k=0;k<7;k++)n+=win_reads[w][k];require(n==ram_reads-begin_reads,"read-window conservation");
 n=0;for(unsigned w=0;w<2;w++)for(unsigned k=0;k<7;k++)n+=win_writes[w][k];require(n==ram_writes-begin_writes,"write-window conservation");
 std::ofstream f(root+"/window_counts.txt");
 f<<"boundaries "<<begin_clock<<" "<<end_clock<<" "<<clocks<<"\n";
 f<<"boot "<<begin_clock-8<<" "<<before_reads<<" "<<before_writes<<" "<<first_itcm_cycle<<"\n";
 f<<"words "<<verified_words<<"\n";
 for(unsigned w=0;w<2;w++){
  f<<"window "<<w<<" "<<win_cycles[w]<<" "<<win_retired[w]<<"\n";
  for(unsigned k=0;k<7;k++)f<<"ram "<<w<<" "<<k<<" "<<win_reads[w][k]<<" "<<win_writes[w][k]<<"\n";
  for(unsigned i=0;i<8192;i++)if(win_pc_cycles[w][i]||win_pc_retired[w][i])f<<"pc "<<w<<" "<<(i<4096?kRamBase+i*2:0x80000000u+(i-4096)*2)<<" "<<win_pc_cycles[w][i]<<" "<<win_pc_retired[w][i]<<"\n";
 }
 for(unsigned i=0;i<6;i++)f<<"phase "<<i<<" "<<phase_cycles[i]<<"\n";
 for(auto r:tail_reads)f<<"tail_read "<<r.cycle<<" "<<r.address<<" "<<r.pc<<"\n";
}
