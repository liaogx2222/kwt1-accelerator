// Host-only observer for the frozen, already-generated reference model.
// Included after sim_e203.cpp's globals; never drives a DUT or host signal.
#include "Vreference_top___024root.h"
static uint32_t observed_ir_pc=0;
static bool observed_ir_known=false;
static uint64_t profile_cycles=0,profile_retired=0,profile_phase[6]={};
static uint64_t profile_ram_read[7]={},profile_ram_write[7]={};
static uint64_t profile_host_reads[64]={},profile_host_writes[64]={};
static uint64_t profile_pc_cycles[4096]={},profile_pc_retired[4096]={};
static uint64_t profile_stalls[3]={};
static unsigned profile_region(uint32_t address){
 uint32_t a=address-kRamBase;
 if(a<0x2000)return 0;
 if(a>=kInputOffset&&a<kInputOffset+6336)return 2;
 if(a>=kOutputOffset&&a<kOutputOffset+6336)return 3;
 if(a>=kPacketOffset&&a<kPacketOffset+61728)return 4;
 if(a>=kStackOffset&&a<kRamBytes)return 5;
 if(a<kInputOffset)return 1;
 return 6;
}
static void profile_tick(bool mtake,bool hrq,uint32_t ma,bool mread,uint32_t ha,bool hread){
 const auto *r=d.rootp;
 const uint32_t ir=r->reference_top__DOT__cpu__DOT__u_e203_cpu__DOT__u_e203_core__DOT__ifu_o_ir;
 if(d.rst_n&&d.retired){
  require(observed_ir_known&&observed_ir_pc>=kRamBase&&observed_ir_pc<kRamBase+0x2000,"observer retired PC range");
  unsigned o=observed_ir_pc-kRamBase;
  uint32_t instruction=uint32_t(ram[o])|(uint32_t(ram[o+1])<<8)|(uint32_t(ram[o+2])<<16)|(uint32_t(ram[o+3])<<24);
  uint32_t mask=(instruction&3)==3?0xffffffffu:0xffffu;
  require((ir&mask)==(instruction&mask),"observer IR/PC mismatch");
 }
 // Exactly the existing begin_clock .. end_clock window, before the edge.
 if(active&&rc_event==999){
  profile_cycles++;
  unsigned state=r->reference_top__DOT__accel__DOT__accel__DOT__state;
  unsigned phase=!input_ready?0:(requested!=-2&&!leased)?1:leased?2:
                 (state==1||state==2)?3:(state>=4&&state<=7)?4:5;
  profile_phase[phase]++;
  if(observed_ir_known){
   unsigned index=(observed_ir_pc-kRamBase)/2;
   require(index<4096,"observer cycle PC range");
   profile_pc_cycles[index]++;
   if(d.retired)profile_pc_retired[index]++;
  }
  if(d.retired)profile_retired++;
  if(mtake)(mread?profile_ram_read:profile_ram_write)[profile_region(ma)]++;
  if(hrq){unsigned index=(ha&255)/4;(hread?profile_host_reads:profile_host_writes)[index]++;}
  if(d.mv&&!d.mr)profile_stalls[0]++;
  if(d.hv&&!d.hr)profile_stalls[1]++;
  if(source_port)profile_stalls[2]++;
 }
 // inspect_pc is the fetch PC, not a retire PC. Shadow it when a new IR is
 // accepted, then use the previous shadow on the current retiring edge.
 if(!d.rst_n)observed_ir_known=false;
 else if(r->reference_top__DOT__cpu__DOT__u_e203_cpu__DOT__u_e203_core__DOT__u_e203_ifu__DOT__u_e203_ifu_ifetch__DOT__ir_valid_set){
  observed_ir_pc=d.pc;observed_ir_known=true;
 }
}
static void profile_finish(){
 require(ji==0,"observer currently expects one normal task");
 require(profile_cycles==end_clock-begin_clock,"observer outer-cycle conservation");
 require(profile_retired==end_retired-begin_retired,"observer retirement conservation");
 uint64_t sum=0;for(auto n:profile_phase)sum+=n;require(sum==profile_cycles,"observer phase conservation");
 std::ofstream f(root+"/profile_counts.txt");
 f<<"cycles "<<profile_cycles<<"\nretired "<<profile_retired<<"\n";
 for(unsigned i=0;i<6;i++)f<<"phase "<<i<<" "<<profile_phase[i]<<"\n";
 for(unsigned i=0;i<7;i++)f<<"ram "<<i<<" "<<profile_ram_read[i]<<" "<<profile_ram_write[i]<<"\n";
 for(unsigned i=0;i<64;i++)if(profile_host_reads[i]||profile_host_writes[i])f<<"host "<<i*4<<" "<<profile_host_reads[i]<<" "<<profile_host_writes[i]<<"\n";
 for(unsigned i=0;i<3;i++)f<<"event "<<i<<" "<<profile_stalls[i]<<"\n";
 for(unsigned i=0;i<4096;i++)if(profile_pc_cycles[i]||profile_pc_retired[i])f<<"pc "<<kRamBase+i*2<<" "<<profile_pc_cycles[i]<<" "<<profile_pc_retired[i]<<"\n";
}
