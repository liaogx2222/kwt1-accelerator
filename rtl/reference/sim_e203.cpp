#include "Vreference_top.h"
#include "verilated.h"
#include <array>
#include <vector>
#include <fstream>
#include <string>
#include <stdexcept>
#include <algorithm>
#include <cstdio>
#include <cstdint>
static Vreference_top d;
static uint64_t clocks=0,retired=0;static std::string root;
static constexpr uint32_t kRamBase=0xa0000000u,kRamBytes=524288,kInputOffset=0x20000,kOutputOffset=0x22000,kPacketOffset=0x24000,kStackOffset=0x7c000;
static std::array<uint8_t,kRamBytes> ram;
static bool done=false,armed_sp=false,source_port=false;static uint32_t min_sp=kRamBase+kRamBytes;static int reset_left=0;
static uint64_t ram_reads=0,ram_writes=0,host_words=0;
static void require(bool ok,const std::string &why){if(!ok)throw std::runtime_error(why);}
double sc_time_stamp(){return double(clocks*10);}
static std::vector<uint8_t> hex(const std::string &name){std::ifstream f(root+"/"+name);require(bool(f),"missing "+name);std::vector<uint8_t> b;uint32_t w;while(f>>std::hex>>w)for(int i=0;i<4;i++)b.push_back(w>>(8*i));return b;}
struct Job {int label,fault;};static std::vector<Job> jobs;static size_t ji=0;static bool active=false,input_ready=false,leased=false;
static std::vector<uint8_t> input,expected,packet;static size_t input_pos=0,packet_pos=0;
static uint64_t input_due=0,packet_due=0,begin_clock=0,begin_retired=0,end_clock=0,end_retired=0,begin_reads=0,begin_writes=0;
static uint32_t start_params=0,acquires=0,releases=0,cancels=0,peak=0,sizeof_device=0;static int layer_next=-1,requested=-2;
static int rc_event=999,last_error=0,abort_error=0;static bool fault_active=false;
static uint32_t cpu_counters[4]={},acc_counters[8]={};static std::ofstream metrics;
static uint32_t word(uint32_t off){require(off+4<=kRamBytes,"RAM bounds");return uint32_t(ram[off])|(uint32_t(ram[off+1])<<8)|(uint32_t(ram[off+2])<<16)|(uint32_t(ram[off+3])<<24);}
static void store(uint32_t off,uint32_t value,unsigned mask){require(off+4<=kRamBytes,"RAM store bounds");for(int i=0;i<4;i++)if(mask>>i&1)ram[off+i]=value>>(8*i);}
static void begin_job(){
 require(!leased&&requested==-2,"old provider state across job");require(ji<jobs.size(),"job overrun");char file[64];
 std::sprintf(file,"input_%03d.hex",jobs[ji].label);input=hex(file);std::sprintf(file,"expected_%03d.hex",jobs[ji].label);expected=hex(file);
 require(input.size()==6336&&expected.size()==6336,"tensor length");std::fill(ram.begin()+kOutputOffset,ram.begin()+kOutputOffset+6336,0x80);
 input_pos=0;input_due=clocks+6;input_ready=false;active=true;fault_active=jobs[ji].fault!=0;
 begin_clock=clocks;begin_retired=retired;begin_reads=ram_reads;begin_writes=ram_writes;start_params=d.parameter_words;
 acquires=releases=cancels=peak=0;layer_next=-1;rc_event=999;last_error=abort_error=0;end_clock=end_retired=0;
 std::printf("JOB %u label=%d fault=%d BEGIN\n",unsigned(ji),jobs[ji].label,jobs[ji].fault);std::fflush(stdout);
}
static void arrivals(){
 source_port=false;
 if(active&&!input_ready&&clocks>=input_due){store(kInputOffset+input_pos,uint32_t(input[input_pos])|(uint32_t(input[input_pos+1])<<8)|(uint32_t(input[input_pos+2])<<16)|(uint32_t(input[input_pos+3])<<24),15);input_pos+=4;host_words++;source_port=true;input_due+=6;if(input_pos==input.size())input_ready=true;}
 else if(requested!=-2&&!leased&&packet_pos<packet.size()&&clocks>=packet_due){store(kPacketOffset+packet_pos,uint32_t(packet[packet_pos])|(uint32_t(packet[packet_pos+1])<<8)|(uint32_t(packet[packet_pos+2])<<16)|(uint32_t(packet[packet_pos+3])<<24),15);packet_pos+=4;host_words++;source_port=true;packet_due+=6;if(packet_pos==packet.size()){leased=true;acquires++;peak=std::max(peak,unsigned(packet.size()));}}
}
static void finish_job(int rc){
 int expected_rc=jobs[ji].fault==1?-3:jobs[ji].fault==2?-7:0;
 require(rc==expected_rc&&rc_event==expected_rc,"unexpected firmware result");require(!leased&&requested==-2,"leaked packet ownership");
 uint32_t params=d.parameter_words-start_params;
 if(!rc){
  require(acquires==13&&releases==13&&params==189328&&peak==61728,"cold flow counts");
  for(size_t i=0;i<6336;i++)require(ram[kOutputOffset+i]==expected[i],"output code mismatch "+std::to_string(i));
  char file[64];std::sprintf(file,"cpu_observed_job_%02u.hex",unsigned(ji));std::ofstream f(root+"/"+file);
  for(unsigned i=0;i<6336;i+=4){char s[16];std::sprintf(s,"%08x",word(kOutputOffset+i));f<<s<<"\n";}
  require(acc_counters[2]==5058532&&acc_counters[3]==0,"encoder compute counter");
 }else if(rc==-7)require(last_error==-2&&abort_error==-2,"lost timeout/cleanup errors");
 else require(last_error==-3&&abort_error==0,"CRC cleanup");
 metrics<<ji<<" "<<jobs[ji].label<<" "<<jobs[ji].fault<<" "<<rc<<" "<<end_clock-begin_clock<<" "<<end_retired-begin_retired<<" "<<cpu_counters[0]<<" "<<cpu_counters[2]<<" "<<params<<" "<<acquires<<" "<<releases<<" "<<cancels<<" "<<peak<<" "<<kRamBase+kRamBytes-min_sp<<" "<<acc_counters[0]<<" "<<acc_counters[2]<<" "<<ram_reads-begin_reads<<" "<<ram_writes-begin_writes<<"\n";metrics.flush();
 std::printf("JOB %u PASS rc=%d outer=%llu retired=%llu stack=%u\n",unsigned(ji),rc,(unsigned long long)(end_clock-begin_clock),(unsigned long long)(end_retired-begin_retired),kRamBase+kRamBytes-min_sp);std::fflush(stdout);
 active=false;input_ready=false;fault_active=false;ji++;
}
static uint32_t host_read(uint32_t off){
 switch(off){
  case 0:if(ji==jobs.size())return 0xffffffffu;if(!active)begin_job();return input_ready?1:0;
  case 12:return leased?1:0;
  case 16:return packet.size();
  case 32:return uint32_t(d.bus_rc);
  case 36:return uint32_t(clocks);
  default:throw std::runtime_error("invalid host read "+std::to_string(off));
 }
}
static void host_write(uint32_t off,uint32_t value){
 if(off>=80&&off<=92){cpu_counters[(off-80)/4]=value;return;}
 if(off>=112&&off<144){acc_counters[(off-112)/4]=value;return;}
 switch(off){
  case 8:{
   require(active&&input_ready&&!leased&&requested==-2&&int32_t(value)==layer_next,"provider request order/ownership");requested=int32_t(value);
   if(requested==-1)packet=hex("common.bin.hex");else{char file[64];std::sprintf(file,"layer_%02d.bin.hex",requested);packet=hex(file);}
   require(packet.size()==(requested<0?16576u:61728u),"packet length");if(fault_active&&jobs[ji].fault==1&&requested==0)packet.back()^=1;
   packet_pos=0;packet_due=clocks+1024+6;break;
  }
  case 20:require(leased,"release without lease");leased=false;releases++;requested=-2;layer_next++;packet.clear();std::fill(ram.begin()+kPacketOffset,ram.begin()+kPacketOffset+61728,0xa5);break;
  case 24:require(!leased,"cancel leaked lease");cancels++;requested=-2;packet.clear();break;
  case 28:rc_event=int32_t(value);end_clock=clocks;end_retired=retired;break;
  case 40:last_error=int32_t(value);break;
  case 44:abort_error=int32_t(value);break;
  case 48:require(rc_event==-7,"unexpected hard reset");reset_left=4;fault_active=false;break;
  case 4:finish_job(int32_t(value));break;
  case 64:require(ji==jobs.size(),"firmware exited early");done=true;break;
  case 68:throw std::runtime_error("firmware trap/panic "+std::to_string(value)+" pc="+std::to_string(d.pc));
  case 72:throw std::runtime_error("trap mepc "+std::to_string(value));
  case 76:sizeof_device=value;require(value==40,"firmware ABI context");break;
  default:throw std::runtime_error("invalid host write "+std::to_string(off));
 }
}
static void tick(){
 arrivals();d.accel_abort=reset_left>0;if(reset_left)reset_left--;
 d.drop_response=active&&fault_active&&jobs[ji].fault==2&&d.parameter_words-start_params>=64;
 d.mr=!source_port&&(!d.mrv||d.mrr);d.hr=!d.hrv||d.hrr;
 d.clk=0;d.eval();
 // Re-evaluate ready after combinational CPU response readiness settles.
 d.mr=!source_port&&(!d.mrv||d.mrr);d.hr=!d.hrv||d.hrr;d.eval();
 bool mtake=d.mv&&d.mr,hert=d.hrv&&d.hrr,hrq=d.hv&&d.hr,mert=d.mrv&&d.mrr;
 uint32_t ma=d.ma,mw=d.mw,ha=d.ha,hw=d.hw;unsigned mask=d.mmask,hm=d.hm;bool mread=d.mread,hread=d.hread;
 if(d.retired)retired++;
 uint32_t sp=d.sp;if(sp>=kRamBase+kStackOffset&&sp<=kRamBase+kRamBytes){armed_sp=true;min_sp=std::min(min_sp,sp);}else if(armed_sp)require(false,"stack pointer out of reservation");
 d.clk=1;d.eval();clocks++;
 if(mert)d.mrv=0;if(hert)d.hrv=0;
 if(mtake){require(ma>=kRamBase&&uint64_t(ma)<uint64_t(kRamBase)+kRamBytes,"CPU RAM address "+std::to_string(ma));uint32_t a=(ma-kRamBase)&~3u;
  if(mread){d.mrd=word(a);ram_reads++;}else{require(a>=0x2000&&(a<kInputOffset||(a>=kOutputOffset&&a<kOutputOffset+6336)||a>=kStackOffset),"CPU wrote code or host-owned staging");store(a,mw,mask);ram_writes++;}d.mrv=1;
 }
 if(hrq){require((ha&0xffff0000u)==0x10010000u,"host address");if(hread)d.hrd=host_read(ha&65535);else{require(hm==15,"partial mailbox write");host_write(ha&65535,hw);d.hrd=0;}d.hrv=1;}
 if(clocks%10000000==0){std::printf("PROGRESS cycles=%llu pc=%08x job=%u retired=%llu\n",(unsigned long long)clocks,unsigned(d.pc),unsigned(ji),(unsigned long long)retired);std::fflush(stdout);}
}
int main(int argc,char **argv){
 try{
  require(argc>=2,"root argument");root=argv[1];std::string mode=argc>2?argv[2]:"full";bool smoke=mode=="smoke",quick=mode=="quick"||mode=="batch",faults=mode=="faults";
  Verilated::commandArgs(argc,argv);std::fill(ram.begin(),ram.end(),0xa5);
  std::ifstream f(root+"/firmware.bin",std::ios::binary);require(bool(f),"firmware image");std::vector<uint8_t> bin((std::istreambuf_iterator<char>(f)),{});require(bin.size()<0x20000,"firmware size");std::copy(bin.begin(),bin.end(),ram.begin());
  if(!smoke){
   if(!quick){jobs.push_back({0,1});jobs.push_back({0,0});jobs.push_back({0,2});jobs.push_back({0,0});}
   if(!faults){std::ifstream cases(root+"/cases.txt");int id,profile;while(cases>>id>>profile)jobs.push_back({id,0});}
  }
  metrics.open(root+"/cpu_metrics.txt");d.rst_n=0;for(int i=0;i<8;i++)tick();d.rst_n=1;
  while(!done){tick();require(clocks<3000000000ull,"reference watchdog");}
  // Finish the final mailbox response before declaring the firmware complete.
  for(int i=0;i<32;i++)tick();require(!d.hrv&&!d.hv,"final mailbox response not consumed");
  require(sizeof_device==40,"firmware did not execute ABI marker");
  std::printf("PASS E203 jobs=%u cycles=%llu retired=%llu min_sp=%08x stack_highwater=%u host_words=%llu\n",unsigned(ji),(unsigned long long)clocks,(unsigned long long)retired,min_sp,kRamBase+kRamBytes-min_sp,(unsigned long long)host_words);return 0;
 }catch(const std::exception &e){std::fprintf(stderr,"FAIL %s cycle=%llu pc=%08x job=%u\n",e.what(),(unsigned long long)clocks,unsigned(d.pc),unsigned(ji));return 1;}
}

