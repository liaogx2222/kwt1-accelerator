#pragma once
#include <cstdint>
#include <cstdio>
#include <stdexcept>

struct CompactLN2DrainProbe {
    uint64_t words=0,reads=0,a_vectors=0,stalls=0,linked_qkv=0;
    unsigned held_index=0;
    uint64_t held_data=0;
    bool held=false;

    static void check(bool valid,const char *message) {
        if(!valid)throw std::runtime_error(message);
    }

    static unsigned s_address(unsigned word) {
        if(word>=768)return 768+((word-768)%3)*8+(word-768)/3;
        return (word/128)*128+(word%16)*8+(word/16)%8;
    }

    template<class Model,class Codes>
    void observe(const Model &dut,unsigned frame,const Codes &expected) {
        if(dut.drain_busy||dut.probe_forward_write)
            check(dut.lease_hold,"forwarding lost its producing lease");
        if(dut.probe_drain_read) {
            check(dut.drain_busy&&dut.probe_s_read==15&&!dut.probe_s_write,"forward S physical read");
            ++reads;
        }
        if(held)check(dut.drain_valid&&dut.drain_index==held_index&&dut.drain_data==held_data,
                      "forward S changed stalled response");
        const bool ready=dut.drain_ready&&dut.forward_ready;
        held=dut.drain_valid&&!ready;
        if(held) {
            ++stalls;
            check(!dut.probe_s_read&&!dut.probe_s_write,"forward S accessed under stall");
            held_index=dut.drain_index;
            held_data=dut.drain_data;
        }
        if(dut.drain_valid&&ready) {
            const unsigned index=words%792;
            check(frame==1+words/792&&dut.drain_index==index&&dut.drain_last==(index==791),"forward S index or last");
            uint64_t packed=0;
            for(unsigned b=0;b<8;++b)packed|=uint64_t(uint8_t(expected[8*s_address(index)+b]))<<(8*b);
            check(dut.drain_data==packed,"forward physical S payload");
            ++words;
        }
        if(dut.probe_forward_write) {
            const unsigned index=a_vectors%448;
            check(frame==1+a_vectors/448&&dut.probe_forward_index==index&&dut.probe_a_write==255,
                  "forward A address or write mask");
            for(unsigned lane=0;lane<16;++lane) {
                const unsigned row=(index/64)*16+lane;
                const uint8_t value=row<99?uint8_t(expected[row*64+index%64]):0;
                check(uint8_t(dut.probe_forward_data[lane/4]>>(8*(lane%4)))==value,"forward A payload or padding");
            }
            ++a_vectors;
        }
        if(dut.dense_start&&dut.dense_ready&&dut.require_forward&&(dut.tile_id==2||dut.tile_id==4||dut.tile_id==5)) {
            check(dut.forward_available&&!dut.act_write,"next Q/K/V used fixture input");
            ++linked_qkv;
        }
        check(reads>=words&&reads<=words+1,"forward S outstanding count");
    }

    void report() const {
        check(words==9504&&reads==words&&a_vectors==5376&&linked_qkv==33&&!held,"forward totals");
        std::printf("PASS FORWARD words=%llu reads=%llu a_vectors=%llu linked_qkv=%llu stalls=%llu\n",
                    (unsigned long long)words,(unsigned long long)reads,(unsigned long long)a_vectors,
                    (unsigned long long)linked_qkv,(unsigned long long)stalls);
    }
};
