#include "Vkwt_soc_observed.h"
#include "verilated.h"
#include <cstdint>
#include <cstdio>
#include <deque>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>
static Vkwt_soc_observed *d;
static uint64_t ticks=0,retired=0,reads=0,writes=0,params=0,packets=0;
static uint32_t ack=0,last_p=0,last_m=0;static bool marker_pending=false,done=false,seen_id=false;
static bool firmware_error=false;
static unsigned outputs=0;static std::vector<uint32_t> expected,observed;
static void need(bool b,const char*s){if(!b)throw std::runtime_error(s);}
double sc_time_stamp(){return double(ticks*10);}
static bool tick(){
 d->clk=0;d->lfclk=((ticks*65536ULL)/150000000ULL)&1;d->eval();
 bool host=d->host_valid&&d->host_ready;
 if(d->rst_n){
  retired+=d->retired;
  if(d->prv&&d->prr){need(!d->perr,"CPU peripheral bus error");if(last_p==0x11000048){need(d->prd==0x4b575431,"CPU ID mismatch");seen_id=true;}}
  if(d->mrv&&d->mrr){need(!d->merr,"CPU memory bus error");if(marker_pending){done=true;marker_pending=false;}}
  if(d->pv&&d->pready){last_p=d->pa;if(d->pread)reads++;else{writes++;if(d->pa==0x11000008){packets++;std::printf("PACKET %llu frame=%u pc=%08x\n",(unsigned long long)packets,d->pw,d->pc);std::fflush(stdout);}if(d->pa==0x11000010)params++;}}
  if(d->mv&&d->mready){last_m=d->ma;if(!d->mread){
   if(d->ma==0xa0000004)ack=d->mw;
   if(d->ma>=0xa0022000&&d->ma<0xa00238c0){
    need(outputs<1584&&d->ma==0xa0022000+4*outputs,"CPU output order");
    need(outputs<expected.size()&&d->mw==expected[outputs],"CPU shared output mismatch");
    observed.push_back(d->mw);outputs++;
   }
   if(d->ma==0xa0000008&&d->mw==0x5a5)marker_pending=true;
   if(d->ma==0xa0000008&&d->mw==0xbad00000)firmware_error=true;
  }}
 }
 d->clk=1;d->eval();ticks++;return host;
}
static void reset(){
 d->host_valid=0;d->rst_n=0;for(int i=0;i<20000;i++)tick();
 ack=0;marker_pending=done=seen_id=firmware_error=false;last_p=last_m=0;outputs=0;
 d->rst_n=1;unsigned boot=0;while(!seen_id){tick();need(++boot<2000000,"SoC boot watchdog");}
}
static std::vector<uint32_t> words(const std::string &file){std::ifstream f(file);need(bool(f),"fixture missing");std::vector<uint32_t> v;uint32_t x;while(f>>std::hex>>x)v.push_back(x);return v;}
int main(int argc,char**argv){
 try{
  need(argc>=5,"usage: sim output fixture cases supply_period [reset]");
  Verilated::commandArgs(argc,argv);d=new Vkwt_soc_observed;
  std::string out=argv[1],fixture=argv[2],labels=argv[3];unsigned period=std::stoul(argv[4]);
  need(period>0,"supply period");reset();std::ofstream metrics(out+"/soc_metrics.txt");unsigned epoch=0;
  bool reset_pending=false,crc_pending=false;
  for(int i=5;i<argc;i++){reset_pending|=std::string(argv[i])=="+RESET_LN";crc_pending|=std::string(argv[i])=="+CRC_REJECT";}
  std::vector<int> cases;size_t pos=0;while(pos<labels.size()){size_t end=labels.find(',',pos);cases.push_back(std::stoi(labels.substr(pos,end-pos)));if(end==std::string::npos)break;pos=end+1;}
  for(unsigned at=0;at<cases.size();){int id=cases[at];bool restart=false;
   char name[64];std::sprintf(name,"/expected_%03d.hex",id);expected=words(fixture+name);
   need(expected.size()==1584,"golden word count");observed.clear();outputs=0;done=false;marker_pending=false;
   uint64_t begin=ticks,r0=retired,rd0=reads,wr0=writes,p0=params,pkt0=packets;
   std::deque<std::pair<uint32_t,uint32_t>> pending;
   auto enqueue=[&](uint32_t base,const std::vector<uint32_t>&data){for(unsigned i=0;i<data.size();i++)pending.push_back({base+i,data[i]});};
   auto common=words(fixture+"/common.bin.hex");if(crc_pending)common[16]^=1;enqueue(0x400,common);
   std::sprintf(name,"/input_%03d.hex",id);enqueue(0x8000,words(fixture+name));
   enqueue(0x9000,words(fixture+"/layer_00.bin.hex"));pending.push_back({0,epoch+1});
   unsigned next=1;uint64_t ready_at=ticks;unsigned host_words=0;
   while(!done){
    if(pending.empty()&&next<12&&ack==epoch+next){
     std::sprintf(name,"/layer_%02u.bin.hex",next);enqueue(0x9000,words(fixture+name));pending.push_back({0,epoch+next+1});next++;
    }
    d->host_valid=!pending.empty()&&ticks>=ready_at;
    if(d->host_valid){d->host_addr=pending.front().first;d->host_data=pending.front().second;}
    if(tick()){pending.pop_front();ready_at=ticks+period-1;host_words++;}
    if(firmware_error){
     need(crc_pending&&outputs==0&&params-p0==4144,"unexpected firmware error");
     std::printf("PASS SOC_CRC_REJECT cycles=%llu parameters=%llu\n",(unsigned long long)(ticks-begin),(unsigned long long)(params-p0));std::fflush(stdout);
     crc_pending=false;reset();epoch=0;restart=true;break;
    }
    if(reset_pending&&!crc_pending&&d->accel_state==51){
     need(outputs==0,"early output before LN reset");
     std::printf("SOC_RESET_IN_LN cycles=%llu state=51\n",(unsigned long long)(ticks-begin));std::fflush(stdout);
     reset_pending=false;reset();epoch=0;restart=true;break;
    }
    if((ticks-begin)%2000000==0){std::printf("PROGRESS ticks=%llu pc=%08x state=%u ack=%u packets=%llu\n",(unsigned long long)(ticks-begin),d->pc,d->accel_state,ack,(unsigned long long)(packets-pkt0));std::fflush(stdout);}
    need(ticks-begin<150000000,"SoC task watchdog");
   }
   if(restart)continue;
   d->host_valid=0;need(seen_id&&outputs==1584&&params-p0==189328&&packets-pkt0==13,"SoC task totals");
   need(next==12&&pending.empty()&&ack==epoch+12,"lease completion");
   auto elapsed=ticks-begin;
   std::sprintf(name,"/soc_observed_%03d.hex",id);std::ofstream saved(out+name);for(auto x:observed){char line[16];std::sprintf(line,"%08x",x);saved<<line<<"\n";}
   metrics<<id<<" "<<elapsed<<" "<<retired-r0<<" "<<reads-rd0<<" "<<writes-wr0<<" "<<params-p0<<" "<<packets-pkt0<<" "<<outputs<<" "<<host_words<<"\n";metrics.flush();
   std::printf("PASS SOC case=%d cycles=%llu retired=%llu params=%llu packets=13 output_words=1584\n",id,(unsigned long long)elapsed,(unsigned long long)(retired-r0),(unsigned long long)(params-p0));std::fflush(stdout);epoch+=16;at++;
  }
  d->final();delete d;return 0;
 }catch(const std::exception&e){std::fprintf(stderr,"FAIL SOC %s ticks=%llu pc=%08x state=%u ack=%u outputs=%u\n",e.what(),(unsigned long long)ticks,d?d->pc:0,d?d->accel_state:0,ack,outputs);return 1;}
}
