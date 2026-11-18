#pragma once
#include "compact_dense_scoreboard.hpp"

struct Dense99Scoreboard : DenseScoreboard {
    std::vector<int32_t> expected_raw;
    std::vector<int8_t> expected_rq;
    uint64_t scratch_writes=0,copy_reads=0,copy_writes=0,copy_cycles=0,masked=0;

    static bool spilled(unsigned frame,int matrix) {return wide(frame,matrix)||matrix==1;}
    static unsigned vectors(unsigned frame,int matrix) {return reduction(matrix)*(wide(frame,matrix)?2:1);}

    uint8_t byte(unsigned frame,int matrix,unsigned group,unsigned vector,unsigned lane) const {
        unsigned k=reduction(matrix), row=group*16+lane;
        // Poison padded activations to make accidental publication detectable.
        uint16_t a=row<99 ? uint16_t(value(frame,matrix,row,vector%k)) : 0xa57f;
        return uint8_t(a>>(8*(vector/k)));
    }

    void expected99(unsigned frame,int matrix,const std::vector<uint32_t> &packet) {
        static constexpr unsigned bs[]={1240,6104,0,11888,0,0};
        static constexpr unsigned ms[]={1496,6168,10456,11952,13104,14280};
        static constexpr unsigned ss[]={1752,6232,10520,12016,13168,14344};
        unsigned cols=columns(matrix);
        expected_raw.resize(99*cols);
        expected_rq.resize(99*cols);
        for(unsigned row=0;row<99;++row) for(unsigned col=0;col<cols;++col) {
            int64_t acc=bs[matrix]?int32_t(packet[bs[matrix]+col]):0;
            for(unsigned k=0;k<reduction(matrix);++k)
                acc+=value(frame,matrix,row,k)*weight(packet,matrix,k,col);
            require(acc>=INT32_MIN&&acc<=INT32_MAX,"99-row signed accumulator overflow");
            expected_raw[row*cols+col]=int32_t(acc);
            expected_rq[row*cols+col]=requantize(int32_t(acc),int32_t(packet[ms[matrix]+col]),packet[ss[matrix]+col]);
        }
    }

    template<class Model> void drive(Model &dut,unsigned frame,int matrix,uint64_t clocks) {
        dut.act_write=0; dut.dense_start=0;
        dut.scratch_en=0; dut.scratch_we=0;
        dut.dense_result_ready=clocks%9>=3;
        if(matrix<0||running) return;
        unsigned count=vectors(frame,matrix);
        bool spill=spilled(frame,matrix);
        if(loaded==7*count*(spill?2:1)) {
            dut.dense_start=1; dut.dense_wide=wide(frame,matrix);
        } else if(spill) {
            dut.scratch_en=15; dut.scratch_we=15;
            dut.scratch_addr=uint64_t(loaded)*0x001001001001ull;
            unsigned vector=loaded/2, lane0=8*(loaded%2);
            uint64_t data=0;
            for(unsigned lane=0;lane<8;++lane)
                data|=uint64_t(byte(frame,matrix,vector/count,vector%count,lane0+lane))<<(8*lane);
            dut.scratch_wdata=data;
        } else {
            dut.act_write=1; dut.act_addr=loaded;
            for(unsigned j=0;j<4;++j) {
                uint32_t data=0;
                for(unsigned lane=0;lane<4;++lane)
                    data|=uint32_t(byte(frame,matrix,loaded/count,loaded%count,4*j+lane))<<(8*lane);
                dut.act_data[j]=data;
            }
        }
    }

    static unsigned verify_tag(unsigned ordinal,unsigned tag,unsigned mask) {
        unsigned col_tile=ordinal/400, within=ordinal%400;
        unsigned group=within/64, sub=within%64;
        require(tag==((group<<10)|(col_tile<<6)|sub),"99-row result tag order");
        require(mask==(group==6?7u:15u),"99-row tail mask");
        return group*16+4*(sub/16);
    }

    template<class Model> void observe(const Model &dut,unsigned frame,int matrix,const std::vector<uint32_t> &packet) {
        require(!dut.dense_error,"99-row dense controller error");
        if(dut.act_write&&dut.act_ready) {++loaded; ++writes;}
        if(dut.scratch_en&&dut.scratch_ready) {++loaded; ++scratch_writes;}
        if(dut.dense_start&&dut.dense_ready) {
            require(matrix==dut.tile_id,"99-row wrong matrix owner");
            running=true; expected99(frame,matrix,packet);
        }
        if(dut.coeff_phase) ++coeff_cycles;
        if(dut.mac_phase) ++mac_cycles;
        if(dut.rq_phase) ++rq_cycles;
        if(dut.copy_phase) ++copy_cycles;
        if(dut.copy_read) ++copy_reads;
        if(dut.copy_write) ++copy_writes;
        if(dut.dense_valid&&!dut.dense_result_ready) ++stall_cycles;
        if(dut.raw_accept || (dut.dense_valid&&dut.dense_result_ready))
            require(running&&matrix>=0&&dut.lease_hold,"99-row result outside matrix lease");
        if(dut.raw_accept) {
            unsigned group=raw_groups++;
            unsigned row=verify_tag(group,dut.raw_tag,dut.raw_mask);
            unsigned col=(group/400)*16+(group%16);
            for(unsigned lane=0;lane<4;++lane) if(dut.raw_mask>>lane&1) {
                require(dut.raw_data[lane]==uint32_t(expected_raw[(row+lane)*columns(matrix)+col]),"99-row raw mismatch");
                ++raw_codes;
            }
        }
        if(dut.dense_valid&&dut.dense_result_ready) {
            unsigned group=rq_groups++;
            unsigned row=verify_tag(group,dut.dense_tag,dut.dense_mask);
            unsigned col=(group/400)*16+(group%16);
            for(unsigned lane=0;lane<4;++lane) if(dut.dense_mask>>lane&1) {
                require(uint8_t(dut.dense_data>>(8*lane))==uint8_t(expected_rq[(row+lane)*columns(matrix)+col]),"99-row RQ mismatch");
                ++rq_codes;
            } else ++masked;
        }
        if(dut.dense_done) {
            require(running&&raw_groups==(columns(matrix)/16)*400&&rq_groups==raw_groups,"99-row matrix released early");
            ++matrices; loaded=0; raw_groups=0; rq_groups=0; running=false;
        }
    }
};
