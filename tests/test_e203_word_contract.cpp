#include "word_access.h"
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
alignas(4) static uint8_t data[61728+4];
static void check(bool ok){if(!ok)throw std::runtime_error("word contract failure");}
int main(int argc,char**argv){
 try{
  check(argc==2);unsigned words=0;
  for(int layer=-1;layer<12;layer++){
   char name[80];if(layer<0)std::sprintf(name,"common.bin.hex");else std::sprintf(name,"layer_%02d.bin.hex",layer);
   std::string path=std::string(argv[1])+"/"+name;FILE*f=std::fopen(path.c_str(),"r");check(f!=nullptr);unsigned value,n=0;
   while(std::fscanf(f,"%x",&value)==1){check(n+4<=61728);for(int i=0;i<4;i++)data[n+i]=value>>(i*8);n+=4;}
   std::fclose(f);check(kwt_word_contract(data,n));
   for(unsigned i=0;i<n;i+=4){uint32_t v=uint32_t(data[i])|(uint32_t(data[i+1])<<8)|(uint32_t(data[i+2])<<16)|(uint32_t(data[i+3])<<24);check(kwt_packet_word(data+i)==v);words++;}
  }
  check(words==189328);
  check(!kwt_word_contract(nullptr,4));check(!kwt_word_contract(data,0));
  for(unsigned i=1;i<=3;i++)check(!kwt_word_contract(data+i,4));
  for(unsigned n:{1u,2u,3u,5u,61727u})check(!kwt_word_contract(data,n));
  for(uint32_t v:{0u,0xffffffffu,0x80000000u,0x12345678u}){for(int i=0;i<4;i++)data[i]=v>>(8*i);check(kwt_packet_word(data)==v);}
  std::printf("PASS aligned words=%u null/unaligned/length rejected, edge values\n",words);return 0;
 }catch(const std::exception&e){std::fprintf(stderr,"FAIL %s\n",e.what());return 1;}
}
