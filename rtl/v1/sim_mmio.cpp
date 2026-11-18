// Bus master and the shipped C driver exercise the production 12-layer RTL.
#include "Vkwt1_mmio.h"
#include "verilated.h"
#include "driver/kwt1.h"
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>
#include <stdexcept>
static Vkwt1_mmio d;static uint64_t ticks=0,transactions=0;static size_t output_reads=0;
double sc_time_stamp(){return double(ticks*10);}
static void require(bool b,const char *s){if(!b)throw std::runtime_error(s);}
static bool tick(){
 d.clk=0;d.core_enable=ticks%11!=0&&ticks%17!=0;d.mem_enable=ticks%7!=0;d.eval();bool ready=d.req_ready;
 d.clk=1;d.eval();ticks++;return ready;
}
static int transact(bool write,uint32_t addr,uint32_t data,uint32_t *out,unsigned strobe=15){
 d.req_valid=1;d.req_write=write;d.req_addr=addr;d.req_wdata=data;d.req_wstrb=strobe;d.resp_ready=0;
 unsigned watchdog=0;while(!tick())require(++watchdog<1000000,"request timeout");d.req_valid=0;
 while(!d.resp_valid){tick();require(++watchdog<1000000,"response timeout");}
 auto r=d.resp_rdata;auto e=d.resp_error;
 bool final_read=!write&&addr==24&&++output_reads==1584;
 unsigned hold=final_read?20:(transactions%17==0?5:0);
 for(unsigned k=0;k<hold;k++){tick();require(d.resp_valid&&d.resp_rdata==r&&d.resp_error==e,"bus held response changed");if(final_read)require(!d.irq,"completion before last bus response acknowledgement");}
 d.resp_ready=1;tick();d.resp_ready=0;transactions++;if(out)*out=r;return e?-1:0;
}
static int read32(void *,uint32_t addr,uint32_t *data){return transact(false,addr,0,data);}
static int write32(void *,uint32_t addr,uint32_t data){return transact(true,addr,data,nullptr);}
static void reset(){
 d.abort_hw=1;d.req_valid=d.resp_ready=0;for(int k=0;k<3;k++)tick();d.rst_n=1;d.abort_hw=0;for(int k=0;k<5;k++)tick();
 uint32_t s;require(!read32(nullptr,4,&s)&&(s&511)==0&&(s&512)!=0,"reset status");output_reads=0;
}
static std::vector<uint32_t> words(const std::string &name){std::ifstream f(name);require(bool(f),"missing hex");std::vector<uint32_t> v;uint32_t x;while(f>>std::hex>>x)v.push_back(x);return v;}
static std::vector<uint8_t> bytes(const std::vector<uint32_t> &v){std::vector<uint8_t> b;for(auto w:v)for(int k=0;k<4;k++)b.push_back(w>>(8*k));return b;}
static uint64_t counter(uint32_t address){uint32_t lo,hi;require(!read32(nullptr,address,&lo)&&!read32(nullptr,address+4,&hi),"counter read");return lo|uint64_t(hi)<<32;}
int main(int argc,char **argv){
 try{
  require(argc==2,"usage sim_mmio root");Verilated::commandArgs(argc,argv);std::string root=argv[1];reset();
  require(transact(false,3,0,nullptr)!=0,"unaligned read accepted");require(transact(true,12,1,nullptr,3)!=0,"partial write accepted");require(transact(false,0x100,0,nullptr)!=0,"bad address accepted");
  // Reset a held bus response: no ghost response or transaction survives.
  d.req_valid=1;d.req_write=0;d.req_addr=72;d.req_wstrb=15;while(!tick()){}d.req_valid=0;require(d.resp_valid,"missing held response");reset();require(!d.resp_valid,"response survives reset");
  // Mid-packet abort; reset does not clear SRAM and cold reload overwrites it.
  require(!write32(nullptr,8,256),"frame");require(!write32(nullptr,16,0x12345678),"partial packet");require(!write32(nullptr,0,2),"software abort");
  std::vector<std::vector<uint8_t>> storage;kwt1_packet p[13];
  for(int l=0;l<13;l++){char file[64];if(l==0)std::sprintf(file,"common.bin.hex");else std::sprintf(file,"layer_%02d.bin.hex",l-1);storage.push_back(bytes(words(root+"/"+file)));}
  for(int l=0;l<13;l++)p[l]={storage[l].data(),storage[l].size()};
  kwt1_device device={nullptr,read32,write32,10000000};
  std::ifstream cases(root+"/cases.txt");std::ofstream metrics(root+"/mmio_metrics.txt");int id,profile,count=0;
  while(cases>>id>>profile){
   char file[64];std::sprintf(file,"input_%03d.hex",id);auto input=bytes(words(root+"/"+file));std::sprintf(file,"expected_%03d.hex",id);auto expected=bytes(words(root+"/"+file));std::vector<int8_t> output(6336);
   output_reads=0;int rc=kwt1_run(&device,p,(const int8_t *)input.data(),output.data());
   if(rc){uint32_t status=0,detail=0;read32(nullptr,4,&status);read32(nullptr,28,&detail);std::fprintf(stderr,"driver rc=%d status=%08x detail=%08x\n",rc,status,detail);}
   require(rc==0,"C driver task failed");require(d.irq,"missing completion IRQ");
   for(size_t k=0;k<6336;k++)if(uint8_t(output[k])!=expected[k]){std::fprintf(stderr,"MISMATCH case=%d code=%u got=%d expected=%d\n",id,(unsigned)k,output[k],(int8_t)expected[k]);throw std::runtime_error("output mismatch");}
   std::sprintf(file,"mmio_observed_%03d.hex",id);std::ofstream f(root+"/"+file);
   for(int k=0;k<6336;k+=4){char line[16];uint32_t w=uint8_t(output[k])|(uint32_t(uint8_t(output[k+1]))<<8)|(uint32_t(uint8_t(output[k+2]))<<16)|(uint32_t(uint8_t(output[k+3]))<<24);std::sprintf(line,"%08x",w);f<<line<<"\n";}
   auto cycles=counter(32),compute=counter(40),reads=counter(48),writes=counter(56),stalls=counter(64);
   metrics<<id<<" "<<cycles<<" "<<compute<<" "<<reads<<" "<<writes<<" "<<stalls<<"\n";metrics.flush();
   std::printf("CASE %d cycles=%llu compute=%llu reads=%llu writes=%llu PASS\n",id,(unsigned long long)cycles,(unsigned long long)compute,(unsigned long long)reads,(unsigned long long)writes);std::fflush(stdout);count++;
  }
  std::printf("PASS MMIO C-driver cases=%d codes=%d transactions=%llu\n",count,count*6336,(unsigned long long)transactions);return 0;
 }catch(const std::exception &e){std::fprintf(stderr,"FAIL %s tick=%llu\n",e.what(),(unsigned long long)ticks);return 1;}
}
