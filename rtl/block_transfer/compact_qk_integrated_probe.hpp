#pragma once
#include <array>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <vector>

struct CompactQKIntegratedProbe {
    std::array<std::vector<int8_t>,2> qk;
    uint64_t tiles=0,codes=0,beats=0,stalls=0,owned=0;
    unsigned accepted=0;
    bool held=false;

    static void check(bool valid,const char *message) {
        if(!valid)throw std::runtime_error(message);
    }

    template<class Model> void observe(const Model &dut,const std::vector<int8_t> &expected) {
        if(dut.dense_start&&dut.dense_ready&&(dut.tile_id==4||dut.tile_id==2)) {
            check(expected.size()==6336,"missing Q/K golden");
            qk[dut.tile_id==4?0:1]=expected;
        }
        if(dut.qkv_available) {
            ++owned;
            check(dut.lease_hold&&!dut.scratch_ready&&!dut.range_ready&&!dut.dense_ready&&!dut.raw_accept,
                  "QK lost MAC or bank ownership");
        }
        if(held)check(dut.qk_score_valid,"stalled QK score dropped");
        held=dut.qk_score_valid&&!dut.qk_score_ready;
        const unsigned query_group=(tiles%49)/7,key_group=tiles%7;
        const unsigned rows=query_group==6?3:16,cols=key_group==6?3:16;
        if(dut.qk_score_valid) {
            const unsigned row=(accepted/cols)*4,col=accepted%cols;
            check(dut.qkv_available&&row<rows&&dut.qk_query==query_group&&dut.qk_key==key_group&&
                  dut.qk_row==row&&dut.qk_col==col&&dut.qk_mask==(rows==3?7:15),"QK score tag or tail");
            for(unsigned lane=0;lane<4&&row+lane<rows;++lane) {
                int32_t dot=0;
                for(unsigned c=0;c<64;++c)
                    dot+=qk[0][(query_group*16+row+lane)*64+c]*qk[1][(key_group*16+col)*64+c];
                check(dut.qk_scores[lane]==uint32_t(dot),"shared MAC QK dot-product mismatch");
            }
            if(held)++stalls;
            else {++accepted;++beats;codes+=rows==3?3:4;}
        }
        if(dut.qk_tile_done) {
            check(accepted==((rows+3)/4)*cols&&!held,"premature shared MAC tile release");
            ++tiles;accepted=0;
        }
    }

    void report() const {
        check(tiles==588&&codes==117612&&beats==29700&&stalls>0&&!held,"integrated QK totals");
        std::printf("PASS SHARED_QK tiles=%llu codes=%llu beats=%llu stalls=%llu owned=%llu\n",
                    (unsigned long long)tiles,(unsigned long long)codes,(unsigned long long)beats,
                    (unsigned long long)stalls,(unsigned long long)owned);
    }
};
