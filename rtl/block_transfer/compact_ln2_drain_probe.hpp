#pragma once
#include <cstdint>
#include <cstdio>
#include <stdexcept>

struct CompactLN2DrainProbe {
    uint64_t words=0,reads=0,busy=0,stalls=0,turnovers=0;
    unsigned held_index=0;
    uint64_t held_data=0;
    bool held=false;

    static void check(bool valid,const char *message) {
        if(!valid)throw std::runtime_error(message);
    }

    template<class Model,class Codes>
    void observe(const Model &dut,unsigned frame,const Codes &expected) {
        if(dut.drain_busy) {
            ++busy;
            check(dut.lease_hold&&!dut.scratch_ready,"S drain lost ownership");
        }
        if(dut.probe_drain_read) {
            check(dut.drain_busy&&dut.probe_s_read==15&&!dut.probe_s_write,"S drain physical access");
            ++reads;
        }
        if(held)check(dut.drain_valid&&dut.drain_index==held_index&&dut.drain_data==held_data,
                      "S drain changed stalled response");
        held=dut.drain_valid&&!dut.drain_ready;
        if(held) {
            ++stalls;
            check(!dut.probe_drain_read&&!dut.probe_s_read&&!dut.probe_s_write,"S read or write under stall");
            held_index=dut.drain_index;
            held_data=dut.drain_data;
        }
        if(dut.drain_valid&&dut.drain_ready) {
            const unsigned index=words%792;
            check(frame==1+words/792&&dut.drain_index==index&&dut.drain_last==(index==791),"S drain index or last");
            check(dut.drain_busy&&expected.size()==6336,"S drain invalid result");
            uint64_t packed=0;
            for(unsigned b=0;b<8;++b)packed|=uint64_t(uint8_t(expected[8*index+b]))<<(8*b);
            check(dut.drain_data==packed,"LN2 physical S readback differs");
            if(dut.probe_drain_read)++turnovers;
            ++words;
        }
        check(reads>=words&&reads<=words+1,"S drain outstanding count");
    }

    void report() const {
        check(words==9504&&reads==words&&turnovers==9492&&!held,"S drain transaction totals");
        std::printf("PASS DRAIN words=%llu codes=%llu reads=%llu busy=%llu stalls=%llu turnovers=%llu\n",
                    (unsigned long long)words,(unsigned long long)(words*8),(unsigned long long)reads,
                    (unsigned long long)busy,(unsigned long long)stalls,(unsigned long long)turnovers);
    }
};
