#pragma once
#include <array>
#include <cstdio>
#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

struct CompactQKVResidentProbe {
    static constexpr unsigned VECTORS=1292,COMMANDS=1293;
    std::array<std::vector<int8_t>,3> expected;
    unsigned issued=0,received=0;
    uint64_t words=0,codes=0,errors=0,stalls=0,turnovers=0,owned_cycles=0;
    bool held=false;

    static void check(bool condition,const char *message) {
        if(!condition)throw std::runtime_error(message);
    }

    static std::pair<unsigned,unsigned> command(unsigned ordinal) {
        if(ordinal==VECTORS)return {3,511};
        const unsigned permuted=(ordinal*37+19)%VECTORS;
        return permuted<896?std::make_pair(permuted/448,permuted%448):std::make_pair(2u,permuted-896);
    }

    template<class Model> void drive(Model &dut,uint64_t clocks) {
        const auto [matrix,index]=command(issued);
        dut.qkv_read=issued<COMMANDS;
        dut.qkv_matrix=matrix;
        dut.qkv_index=index;
        dut.qkv_response_ready=clocks%11>=4;
        dut.qkv_release=received==COMMANDS;
    }

    template<class Model> void observe(const Model &dut,const std::vector<int8_t> &golden) {
        const unsigned matrix=dut.tile_id;
        if(dut.dense_start&&dut.dense_ready&&(matrix==2||matrix==4||matrix==5)) {
            check(golden.size()==6336,"Q/K/V golden size");
            expected[matrix==4?0:matrix==2?1:2]=golden;
        }
        if(dut.qkv_available) {
            ++owned_cycles;
            check(dut.lease_hold&&!dut.scratch_ready&&!dut.range_ready,"Q/K/V S ownership lost");
        }
        const bool req=dut.qkv_read&&dut.qkv_read_ready;
        if(req) {
            check(issued<COMMANDS,"extra Q/K/V command");
            if(issued==VECTORS)check(!dut.probe_s_read,"invalid Q/K/V command read a bank");
            ++issued;
        }
        if(held)check(dut.qkv_response_valid,"dropped stalled Q/K/V response");
        held=dut.qkv_response_valid&&!dut.qkv_response_ready;
        if(dut.qkv_response_valid) {
            check(received<issued,"unmatched Q/K/V response");
            const auto [slot,index]=command(received);
            const unsigned valid=slot==3?0:slot!=2&&index>=384?3:16;
            check(dut.qkv_response_mask==((1u<<valid)-1)&&bool(dut.qkv_response_error)==(slot==3),
                  "Q/K/V response mask or error");
            for(unsigned lane=0;lane<16;++lane) {
                unsigned offset=slot==2?(index/4)*64+(index%4)*16+lane:
                                        ((index/64)*16+lane)*64+index%64;
                const uint8_t value=lane<valid?uint8_t(expected[slot][offset]):0;
                const uint8_t actual=uint8_t(dut.qkv_response_data[lane/4]>>(8*(lane%4)));
                if(actual!=value) {
                    std::fprintf(stderr,"Q/K/V SRAM frame=%llu slot=%u index=%u lane=%u got=%u expected=%u\n",
                                 (unsigned long long)(words/VECTORS+1),slot,index,lane,actual,value);
                    check(false,"Q/K/V SRAM readback mismatch");
                }
            }
            if(held) {
                ++stalls;
                check(!dut.probe_s_read&&!dut.probe_s_write,"S accessed during Q/K/V response stall");
            } else {
                if(req)++turnovers;
                ++received;
                if(slot==3)++errors;
                else {++words;codes+=valid;}
            }
        }
        if(dut.qkv_release&&dut.qkv_available) {
            check(issued==COMMANDS&&received==COMMANDS,"early Q/K/V release");
            issued=received=0;
        }
    }

    void report() const {
        check(words==15504&&codes==228096&&errors==12&&issued==0&&received==0&&turnovers>0&&stalls>0,
              "Q/K/V resident totals");
        std::printf("PASS RESIDENT vectors=%llu codes=%llu rejected=%llu stalls=%llu turnovers=%llu owned=%llu\n",
                    (unsigned long long)words,(unsigned long long)codes,(unsigned long long)errors,
                    (unsigned long long)stalls,(unsigned long long)turnovers,(unsigned long long)owned_cycles);
    }
};
