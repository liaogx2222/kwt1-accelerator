// Host-only validation. All parameter/input data enter the public stream ports.
#include "Vkwt1_accel.h"
#include "Vkwt1_accel___024root.h"
#include "verilated.h"
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <stdexcept>
static Vkwt1_accel d;
static uint64_t cycle_count=0;static std::string root;static bool single,permit_error=false;
double sc_time_stamp(){return double(cycle_count*10);}
static void require(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
struct Events {bool frame,cfg,input,start,out;uint32_t data;bool last;};
static Events tick(){
 d.clk=0;d.core_enable=cycle_count%11!=0&&cycle_count%17!=0;d.mem_enable=cycle_count%7!=0;d.eval();
 Events e={bool(d.frame_ready),bool(d.cfg_ready),bool(d.input_ready),bool(d.start_ready),bool(d.output_valid&&d.output_ready),d.output_data,bool(d.output_last)};
 d.clk=1;d.eval();++cycle_count;
 if(cycle_count%1000000==0){std::printf("PROGRESS %llu layer=%u state=%u\n",(unsigned long long)cycle_count,d.current_layer,d.debug_state);std::fflush(stdout);}
 require(permit_error||!d.error,"accelerator error");return e;
}
static std::vector<uint32_t> words(const std::string &name){
 std::ifstream f(root+"/"+name);require(bool(f),"missing hex file");std::vector<uint32_t> v;uint32_t x;while(f>>std::hex>>x)v.push_back(x);return v;
}
static uint16_t bank(int n,int address){
 #define BANK(N) case N:return d.rootp->kwt1_accel__DOT__banks__DOT__bank__BRA__##N##__KET____DOT__ram__DOT__mem[address];
 switch(n){BANK(8) BANK(9) BANK(10) BANK(11) BANK(12) BANK(13) BANK(14) BANK(15)}
 #undef BANK
 throw std::runtime_error("debug bank");
}
static void tap(const char *name,int group,int base,int width,bool channel_layout=false){
 auto v=words(std::string(name)+".hex");int errors=0;
 for(int t=0;t<99;t++)for(int c=0;c<width;c++){
  int n=channel_layout?group+(c%8)/2:group+(t%8)/2;
  int address=base+(channel_layout?t*(width/8)+c/8:(t/8)*width+c);
  int shift=8*(channel_layout?c%2:t%2);uint8_t got=bank(n,address)>>shift,expected=v[(t*width+c)/4]>>(8*((t*width+c)%4));
  if(got!=expected){if(errors<4)std::printf("TAP %s t=%d c=%d got=%d expected=%d\n",name,t,c,(int)(int8_t)got,(int)(int8_t)expected);errors++;}
 }
 std::printf("TAP %s mismatches=%d\n",name,errors);std::fflush(stdout);require(errors==0,"intermediate mismatch");
}
static void reset(){
 d.__SYM__abort=1;d.frame_valid=d.cfg_valid=d.input_valid=d.start_valid=d.result_ack=0;d.output_ready=0;
 for(int k=0;k<3;k++)tick();d.rst_n=1;d.__SYM__abort=0;
 for(int k=0;k<10;k++)tick();
 require(!d.done&&!d.busy&&!d.output_valid&&!d.common_valid&&!d.input_loaded&&!d.layer_valid&&d.task_cycles==0,"reset stale state");
}
static void packet(bool common,int layer,int bad=0,int limit=0){
 char file[64];if(common)std::sprintf(file,"common.bin.hex");else std::sprintf(file,"layer_%02d.bin.hex",layer);
 auto v=words(file);d.frame_common=common;d.frame_layer=layer;d.frame_valid=1;
 while(!tick().frame){}d.frame_valid=0;
 size_t count=limit?size_t(limit):v.size();
 for(size_t k=0;k<count;k++){d.cfg_valid=1;d.cfg_data=v[k]^(((bad==1&&k+1==count)||(bad==2&&k==0)||(bad==3&&k==31))?1:0);d.cfg_last=k+1==count;while(!tick().cfg){}}
 d.cfg_valid=0;d.cfg_last=0;for(int k=0;k<8;k++)tick();
}
static void input(int id){
 char name[64];std::sprintf(name,"input_%03d.hex",id);auto v=words(name);require(v.size()==1584,"input length");
 for(size_t k=0;k<v.size();k++){d.input_valid=1;d.input_data=v[k];d.input_last=k+1==v.size();while(!tick().input){}}
 d.input_valid=0;d.input_last=0;while(!d.input_loaded)tick();
}
static void launch(){d.start_valid=1;require(tick().start,"start not ready");d.start_valid=0;}
static void stress(){
 permit_error=true;
 for(int bad=1;bad<=4;bad++){packet(true,0,bad==4?0:bad,bad==4?25:0);require(d.error&&!d.start_ready,"bad packet accepted");reset();}
 for(int bad=0;bad<2;bad++){d.input_valid=1;d.input_data=bad?0:128;d.input_last=bad;while(!tick().input){}d.input_valid=0;for(int k=0;k<3;k++)tick();require(d.error,"bad input accepted");reset();}
 d.frame_valid=1;d.frame_common=0;d.frame_layer=12;while(!tick().frame){}d.frame_valid=0;require(d.error,"bad layer accepted");reset();
 permit_error=false;
 // Abort at header/directory/payload, and in an incomplete input pair.
 auto v=words("common.bin.hex");
 for(int part=0;part<3;part++){
  d.frame_valid=1;d.frame_common=1;d.frame_layer=0;while(!tick().frame){}d.frame_valid=0;
  for(int k=0;k<(part==0?5:part==1?20:200);k++){d.cfg_valid=1;d.cfg_last=0;d.cfg_data=v[k];while(!tick().cfg){}}
  reset();for(int k=0;k<100;k++){tick();require(!d.common_valid&&!d.layer_valid&&!d.output_valid&&!d.done,"packet ghost after reset");}
 }
 d.input_valid=1;d.input_last=0;d.input_data=0x01020304;for(int k=0;k<10;k++)while(!tick().input){}reset();
 // Real task aborts during MAC, iterative DIV, SQRT, held output, final ACK.
 for(int scenario=0;scenario<5;scenario++){
  packet(true,0);packet(false,0);input(0);launch();uint64_t watchdog=0;d.output_ready=0;
  while(true){
   tick();auto *r=d.rootp;bool hit=scenario==0?d.debug_state==7:scenario==1?(d.debug_state==93&&!r->kwt1_accel__DOT__core__DOT__iter_sqrt):scenario==2?(d.debug_state==93&&r->kwt1_accel__DOT__core__DOT__iter_sqrt):d.output_valid;
   if(hit)break;require(++watchdog<5000000,"reset scenario timeout");
  }
  if(scenario==4){size_t received=0;while(received<1584){d.output_ready=1;auto e=tick();if(e.out)received++;}require(d.awaiting_ack&&d.busy&&!d.done,"final ack state");}
  for(int k=0;k<(scenario<3?12:20);k++)tick();reset();for(int k=0;k<100;k++){tick();require(!d.output_valid&&!d.done&&!d.busy,"execution ghost after reset");}
 }
 std::puts("STRESS PASS rejected=7 packet_resets=3 input_resets=1 execution_resets=5");
}
int main(int argc,char **argv){
 try{
  require(argc>=3,"usage sim root single");root=argv[1];single=std::stoi(argv[2])!=0;Verilated::commandArgs(argc,argv);
  std::ifstream cases(root+"/cases.txt");std::ofstream metrics(root+"/native_metrics.txt");int id,profile,count=0;
  reset();bool stressed=argc>3&&std::string(argv[3])=="stress";if(stressed)stress();
  while(cases>>id>>profile){
   packet(true,0);packet(false,profile);input(id);
   launch();
   char name[64];std::sprintf(name,"expected_%03d.hex",id);auto expected=words(name);std::sprintf(name,"observed_%03d.hex",id);std::ofstream observed(root+"/"+name);
   size_t pos=0;uint64_t watchdog=0;bool held=false;uint32_t held_data=0;int debug_stage=0;
   while(pos<1584){
    if(!single&&d.need_parameters)packet(false,d.current_layer);
    d.output_ready=cycle_count%9>1;
    d.clk=0;d.eval();if(held)require(d.output_valid&&d.output_data==held_data,"held output changed");
    held=d.output_valid&&!d.output_ready;held_data=d.output_data;
    auto e=tick();if(e.out){
     char line[16];std::sprintf(line,"%08x",e.data);observed<<line<<"\n";
     if(e.data!=expected[pos]){std::fprintf(stderr,"MISMATCH case=%d profile=%d word=%u got=%08x expected=%08x\n",id,profile,(unsigned)pos,e.data,expected[pos]);throw std::runtime_error("output mismatch");}
     require(e.last==(pos==1583),"TLAST");pos++;
    }
    if(single&&id==0){
     int kind=d.rootp->kwt1_accel__DOT__core__DOT__kind;
     if(debug_stage==0&&kind==3){tap("q_projection",8,832,64);tap("k_projection",12,0,64);tap("v_projection",12,832,64,true);debug_stage=1;}
     if(debug_stage==1&&kind==4){tap("layernorm1_output",8,0,64);debug_stage=2;}
     if(debug_stage==2&&kind==5){tap("gelu_output",12,0,256);debug_stage=3;}
    }
    require(++watchdog<100000000,"watchdog");
   }
   for(int k=0;k<20;k++){tick();require(d.busy&&!d.done&&d.awaiting_ack,"early completion");}
   d.result_ack=1;tick();d.result_ack=0;require(d.done&&!d.busy,"missing completion");auto freeze=d.task_cycles;for(int k=0;k<10;k++)tick();require(d.task_cycles==freeze,"counter after done");
   std::printf("CASE %d profile=%d cycles=%llu compute=%llu reads=%llu writes=%llu PASS\n",id,profile,(unsigned long long)d.task_cycles,(unsigned long long)d.compute_cycles,(unsigned long long)d.read_words,(unsigned long long)d.write_words);
   metrics<<id<<" "<<profile<<" "<<d.task_cycles<<" "<<d.compute_cycles<<" "<<d.read_words<<" "<<d.write_words<<" "<<d.stall_cycles<<"\n";metrics.flush();std::fflush(stdout);count++;reset();if(stressed)break;
  }
  std::printf("PASS cases=%d codes=%d\n",count,count*6336);d.final();return 0;
 }catch(const std::exception &e){std::fprintf(stderr,"FAIL %s at cycle %llu state=%u error=%u\n",e.what(),(unsigned long long)cycle_count,d.debug_state,d.error_code);return 1;}
}
