#pragma once
#include <cstdint>
#include <stdexcept>
#include <vector>

struct CompactLN2Golden {
    std::vector<int16_t> residual;
    std::vector<int8_t> output;
    std::vector<int32_t> sum;
    std::vector<uint64_t> squares,root,inverse;
    uint64_t residual_count=0,stats_count=0,output_count=0,writes=0;
    uint64_t capture_cycles=0,ln_cycles=0,stalls=0;
    bool held=false;
    unsigned held_row=0,held_col=0,held_value=0;

    static void check(bool condition,const char *what) {
        if(!condition)throw std::runtime_error(what);
    }
    static int64_t rne(int64_t x,uint64_t d) {
        uint64_t a=x<0?uint64_t(-x):uint64_t(x);
        uint64_t q=a/d,r=a%d;
        q+=(r>d-r || (r==d-r&&(q&1)));
        return x<0?-int64_t(q):int64_t(q);
    }
    static uint64_t isqrt(uint64_t a) {
        uint64_t low=0,high=uint64_t(1)<<32;
        while(low+1<high) {
            uint64_t mid=(low+high)/2;
            if(mid*mid<=a)low=mid;else high=mid;
        }
        return low;
    }
    static int32_t clamp(int64_t x,int32_t max) {
        return x>max?max:x<-max?-max:int32_t(x);
    }
    template<class Score> void prepare(unsigned frame,const std::vector<uint32_t> &packet,
                                       const std::vector<int8_t> &fc2,const Score &dense) {
        check(fc2.size()==6336,"LN2 FC2 input size");
        residual.resize(6336);output.resize(6336);sum.resize(99);squares.resize(99);
        root.resize(99);inverse.resize(99);
        auto m0=int32_t(packet[14264]),m1=int32_t(packet[14266]),m=int32_t(packet[11880]);
        uint64_t epsilon=packet[11812]|uint64_t(packet[11813])<<32;
        uint64_t dr=uint64_t(1)<<packet[14268],dy=uint64_t(1)<<packet[11884];
        for(unsigned row=0;row<99;++row) {
            sum[row]=0;squares[row]=0;
            for(unsigned c=0;c<64;++c) {
                unsigned i=row*64+c;
                auto x=clamp(rne(int64_t(dense.value(frame,0,row,c))*m0+int64_t(fc2[i])*m1,dr),32767);
                residual[i]=int16_t(x);sum[row]+=x;squares[row]+=int64_t(x)*x;
            }
            uint64_t h=((64*squares[row]-int64_t(sum[row])*sum[row])<<16)+epsilon;
            root[row]=isqrt(h);inverse[row]=rne(int64_t(1)<<40,root[row]);
            for(unsigned c=0;c<64;++c) {
                unsigned i=row*64+c;
                int64_t n=rne((64*int64_t(residual[i])-sum[row])*int64_t(inverse[row]),uint64_t(1)<<18);
                int64_t a=rne(n*int32_t(packet[11816+c]),uint64_t(1)<<14)+int32_t(packet[11748+c]);
                output[i]=int8_t(clamp(rne(a*m,dy),127));
            }
        }
    }
    template<class Model> void observe(const Model &dut) {
        if(dut.capture_phase)++capture_cycles;
        if(dut.ln_phase)++ln_cycles;
        if(held)check(dut.ln_valid&&dut.ln_row==held_row&&dut.ln_index==held_col&&dut.ln_data==held_value,
                      "LN2 changed stalled payload");
        held=dut.ln_valid&&!dut.ln_ready;
        if(held) {++stalls;held_row=dut.ln_row;held_col=dut.ln_index;held_value=dut.ln_data;}
        if(dut.ln_res_valid) {
            unsigned i=dut.ln_row*64+dut.ln_res_index;
            check(i==residual_count%6336&&dut.ln_res_data==uint16_t(residual[i]),"residual code or order");
            ++residual_count;
        }
        if(dut.ln_stats_valid) {
            unsigned row=dut.ln_row;
            check(row==stats_count%99 && dut.ln_sum==(uint32_t(sum[row])&0x3fffff) &&
                  dut.ln_squares==squares[row]&&dut.ln_root==root[row]&&dut.ln_inverse==inverse[row],
                  "LN2 row statistics or reciprocal");
            ++stats_count;
        }
        bool fire=dut.ln_valid&&dut.ln_ready;
        check(bool(dut.ln_write)==(fire&&dut.ln_index%8==7),"LN2 S write handshake");
        if(fire) {
            unsigned i=dut.ln_row*64+dut.ln_index;
            check(i==output_count%6336&&dut.ln_data==uint8_t(output[i]),"LN2 code or order");
            if(dut.ln_write) {
                uint64_t packed=0;
                for(unsigned j=0;j<8;++j) packed|=uint64_t(uint8_t(output[i-7+j]))<<(8*j);
                check(dut.ln_s_addr==i/8&&dut.ln_s_wdata==packed,"LN2 S address or payload");
                ++writes;
            }
            ++output_count;
        }
    }
};
