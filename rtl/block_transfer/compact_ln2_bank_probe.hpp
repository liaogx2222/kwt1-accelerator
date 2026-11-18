#pragma once
#include <cstdio>
#include <cstdint>
#include <stdexcept>

struct CompactLN2BankProbe {
    uint64_t a_reads=0,s_reads=0,a_writes=0,s_writes=0;
    uint64_t capture_reads=0,fc2_reads=0,skip_reads=0,captures=0,pairs=0;

    static void check(bool valid,const char *message) {
        if(!valid)throw std::runtime_error(message);
    }

    template<class Model> void observe(const Model &dut) {
        const unsigned a=dut.probe_a_read,s=dut.probe_s_read;
        a_reads+=__builtin_popcount(a);
        s_reads+=__builtin_popcount(s);
        a_writes+=__builtin_popcount(dut.probe_a_write);
        s_writes+=__builtin_popcount(dut.probe_s_write);
        if(dut.probe_capture) {
            const bool tail=captures%448>=384;
            check(a==(dut.probe_narrow&&tail?3u:255u),"LN2 capture read mask");
            capture_reads+=__builtin_popcount(a);
            ++captures;
        }
        if(dut.probe_pair) {
            const unsigned row=dut.ln_row;
            check(row<99&&row==pairs/64%99,"LN2 pair read order");
            const unsigned a_bank=(row%16)/2,s_bank=row>=96?2+(row-96)/2:(row%8)/2;
            check(a==(dut.probe_narrow?1u<<a_bank:row>=96?3u:255u),"LN2 FC2 read mask");
            check(s==(dut.probe_narrow?1u<<s_bank:15u),"LN2 skip read mask");
            fc2_reads+=__builtin_popcount(a);
            skip_reads+=__builtin_popcount(s);
            ++pairs;
        }
    }

    void report() const {
        check(captures==5376&&pairs==76032,"LN2 read request totals");
        std::printf("PASS BANKS a_reads=%llu s_reads=%llu a_writes=%llu s_writes=%llu capture_reads=%llu "
                    "fc2_reads=%llu skip_reads=%llu\n",
                    (unsigned long long)a_reads,(unsigned long long)s_reads,
                    (unsigned long long)a_writes,(unsigned long long)s_writes,
                    (unsigned long long)capture_reads,(unsigned long long)fc2_reads,(unsigned long long)skip_reads);
    }
};
