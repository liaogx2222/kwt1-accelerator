#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <vector>

struct CompactSoftmaxIntegratedProbe {
    std::array<std::array<int32_t,99>,16> scores{};
    std::array<uint16_t,99> indices{},probabilities{};
    uint64_t rows=0,codes=0,b_codes=0,queries=0,stalls=0,b_reads=0,b_writes=0;
    bool held=false;

    static void check(bool ok,const char *message) {
        if(!ok)throw std::runtime_error(message);
    }

    static uint64_t rne(uint64_t n,uint64_t d) {
        const uint64_t q=n/d,r=n%d;
        return q+(r>d-r||(r==d-r&&(q&1)));
    }

    template<class Model> void observe(const Model &dut,const std::vector<uint32_t> &packet,
                                       const std::vector<uint32_t> &common) {
        b_reads+=__builtin_popcount(dut.probe_b_read);
        b_writes+=__builtin_popcount(dut.probe_b_write);
        if(dut.qk_score_valid&&dut.qk_score_ready) {
            const unsigned key=dut.qk_key*16+dut.qk_col;
            for(unsigned lane=0;lane<4;++lane)if(dut.qk_mask>>lane&1)
                scores[dut.qk_row+lane][key]=int32_t(dut.qk_scores[lane]);
        }
        if(dut.probe_sm_score_fire) {
            const auto &row=scores[dut.sm_row];
            const unsigned col=b_codes%99;
            check(int32_t(dut.probe_sm_score)==row[col],"physical B score mismatch");
            if(col==0) {
                const int32_t maximum=*std::max_element(row.begin(),row.end());
                const uint64_t divisor=uint64_t(1)<<packet[14276];
                uint64_t denominator=0;
                std::array<uint32_t,99> exp{};
                for(unsigned k=0;k<99;++k) {
                    const uint64_t mag=uint64_t(int64_t(maximum)-row[k])*packet[14272];
                    indices[k]=std::min<uint64_t>(4096,rne(mag,divisor));
                    exp[k]=indices[k]==4096?0:common[48+indices[k]];
                    denominator+=exp[k];
                }
                for(unsigned k=0;k<99;++k)probabilities[k]=rne(uint64_t(exp[k])*65535,denominator);
            }
            ++b_codes;
        }
        if(dut.probe_exp_fire) {
            check(dut.probe_exp_index==indices[queries%99],"Softmax exp index mismatch");
            ++queries;
        }
        if(held)check(dut.sm_prob_valid,"stalled probability dropped");
        held=dut.sm_prob_valid&&!dut.sm_prob_ready;
        if(dut.sm_prob_valid) {
            const unsigned row=rows%99;
            check(dut.qkv_available&&dut.qk_query==row/16&&dut.sm_row==row%16&&
                  dut.sm_index==codes%99&&dut.sm_prob==probabilities[codes%99],"Softmax probability mismatch");
            if(held)++stalls;
            else {++codes;if(codes%99==0)++rows;}
        }
    }

    void report() const {
        check(rows==1188&&codes==117612&&queries==codes&&b_codes==codes&&b_reads==2*codes&&b_writes==2*codes&&
              stalls>0&&!held,"integrated Softmax totals");
        std::printf("PASS E203_SOFTMAX rows=%llu codes=%llu indices=%llu b_codes=%llu b_reads=%llu b_writes=%llu stalls=%llu\n",
                    (unsigned long long)rows,(unsigned long long)codes,(unsigned long long)queries,
                    (unsigned long long)b_codes,(unsigned long long)b_reads,(unsigned long long)b_writes,
                    (unsigned long long)stalls);
    }
};
