#pragma once
#include <array>
#include <cstdint>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

struct DenseScoreboard {
    std::vector<uint32_t> input;
    std::array<int32_t,4096> raw{};
    std::array<int8_t,4096> quantized{};
    unsigned loaded=0, raw_groups=0, rq_groups=0;
    uint64_t raw_codes=0, rq_codes=0, matrices=0, writes=0;
    uint64_t coeff_cycles=0, mac_cycles=0, rq_cycles=0, stall_cycles=0, saturations=0;
    bool running=false;

    static void require(bool condition,const char *message) {
        if(!condition) throw std::runtime_error(message);
    }
    void load(const std::string &root) {
        std::ifstream file(root+"/input_000.hex");
        uint32_t value;
        while(file>>std::hex>>value) input.push_back(value);
        require(input.size()==3168,"S16 fixture length");
    }
    static bool wide(unsigned frame,int matrix) {
        return frame==1&&(matrix==2||matrix==4||matrix==5);
    }
    static unsigned reduction(int matrix) {return matrix==1?256:64;}
    static unsigned columns(int matrix) {return matrix==0?256:64;}
    static int signed8(unsigned value) {return int(value&127)-int(value&128);}
    int value(unsigned frame,int matrix,unsigned row,unsigned k) const {
        if(wide(frame,matrix)) {
            unsigned offset=row*64+k;
            uint32_t v=(input[offset/2]>>(16*(offset%2)))&65535;
            return int(v&32767)-int(v&32768);
        }
        return int((frame*47+matrix*61+row*89+k*109+(row^k)*13)%255)-127;
    }
    static int weight(const std::vector<uint32_t> &packet,int matrix,unsigned k,unsigned col) {
        static constexpr unsigned starts[]={2008,6296,10584,12080,13232,14408};
        unsigned cols=columns(matrix), depth=reduction(matrix)*(cols/16);
        unsigned source=(col/8)*reduction(matrix)+k;
        uint32_t data=packet[starts[matrix]+((col%8)/2)*depth+source/2];
        return signed8(data>>(16*(source%2)+8*(col%2)));
    }
    int8_t requantize(int32_t value,int32_t multiplier,unsigned shift) {
        require(shift>=38&&shift<=48,"golden shift range");
        int64_t product=int64_t(value)*multiplier;
        uint64_t mag=product<0 ? uint64_t(-product) : uint64_t(product);
        uint64_t div=uint64_t(1)<<shift;
        uint64_t q=mag/div, remainder=mag%div;
        q+=(remainder>div/2 || (remainder==div/2 && (q&1)));
        if(q>127) {q=127; ++saturations;}
        return int8_t(product<0 ? -int(q) : int(q));
    }
    void expected(unsigned frame,int matrix,const std::vector<uint32_t> &packet) {
        static constexpr unsigned bs[]={1240,6104,0,11888,0,0};
        static constexpr unsigned ms[]={1496,6168,10456,11952,13104,14280};
        static constexpr unsigned ss[]={1752,6232,10520,12016,13168,14344};
        unsigned cols=columns(matrix);
        for(unsigned row=0;row<16;++row) for(unsigned col=0;col<cols;++col) {
            int64_t acc=bs[matrix]?int32_t(packet[bs[matrix]+col]):0;
            for(unsigned k=0;k<reduction(matrix);++k)
                acc+=value(frame,matrix,row,k)*weight(packet,matrix,k,col);
            require(acc>=INT32_MIN&&acc<=INT32_MAX,"golden signed accumulator overflow");
            raw[row*cols+col]=int32_t(acc);
            quantized[row*cols+col]=requantize(int32_t(acc),int32_t(packet[ms[matrix]+col]),packet[ss[matrix]+col]);
        }
    }
    template<class Model> void drive(Model &dut,unsigned frame,int matrix,uint64_t clocks) {
        dut.act_write=0; dut.dense_start=0;
        dut.dense_result_ready=clocks%9>=3;
        if(matrix<0||running) return;
        unsigned k=reduction(matrix), planes=wide(frame,matrix)?2:1;
        if(loaded<k*planes) {
            dut.act_write=1; dut.act_addr=loaded;
            for(unsigned j=0;j<4;++j) {
                uint32_t word=0;
                for(unsigned lane=0;lane<4;++lane) {
                    uint16_t a=uint16_t(value(frame,matrix,4*j+lane,loaded%k));
                    word|=uint32_t((a>>(8*(loaded/k)))&255)<<(8*lane);
                }
                dut.act_data[j]=word;
            }
        } else {
            dut.dense_start=1;
            dut.dense_wide=wide(frame,matrix);
        }
    }
    template<class Model> void observe(const Model &dut,unsigned frame,int matrix,const std::vector<uint32_t> &packet) {
        require(!dut.dense_error,"dense controller error");
        if(dut.act_write&&dut.act_ready) {++loaded; ++writes;}
        if(dut.dense_start&&dut.dense_ready) {
            require(matrix==dut.tile_id,"wrong matrix owner");
            running=true; expected(frame,matrix,packet);
        }
        if(dut.coeff_phase) ++coeff_cycles;
        if(dut.mac_phase) ++mac_cycles;
        if(dut.rq_phase) ++rq_cycles;
        if(dut.dense_valid&&!dut.dense_result_ready) ++stall_cycles;
        if(dut.raw_accept || (dut.dense_valid&&dut.dense_result_ready))
            require(running&&matrix>=0&&dut.lease_hold,"result outside active matrix lease");
        if(dut.raw_accept) {
            unsigned group=raw_groups++;
            require(dut.raw_tag==group,"raw tag order");
            unsigned col=16*(group/64)+group%16, row=4*((group%64)/16);
            for(unsigned lane=0;lane<4;++lane)
                require(dut.raw_data[lane]==uint32_t(raw[(row+lane)*columns(matrix)+col]),"dense accumulator mismatch");
            raw_codes+=4;
        }
        if(dut.dense_valid&&dut.dense_result_ready) {
            unsigned group=rq_groups++;
            require(dut.dense_tag==group,"RQ tag order");
            unsigned col=16*(group/64)+group%16, row=4*((group%64)/16);
            for(unsigned lane=0;lane<4;++lane)
                require(uint8_t(dut.dense_data>>(8*lane))==uint8_t(quantized[(row+lane)*columns(matrix)+col]),"dense RQ mismatch");
            rq_codes+=4;
        }
        if(dut.dense_done) {
            require(running&&raw_groups==columns(matrix)*4&&rq_groups==raw_groups,"matrix released early");
            ++matrices; loaded=0; raw_groups=0; rq_groups=0; running=false;
        }
    }
};
