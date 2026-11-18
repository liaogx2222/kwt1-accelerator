#include "Vreference_top.h"
#include "verilated.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr uint32_t ram_base=0xa0000000u, staging=0x26000u, host_base=0x10010000u;
enum class Fault { none, crc, cancel, bus, late, lost, range };
struct Range { unsigned start, words; int matrix; };

void check(bool pass, const char *message) {
    if (!pass) throw std::runtime_error(message);
}

std::vector<Range> plan(unsigned frame, Fault fault) {
    if (fault==Fault::range) return {{48,1,4}};
    if (frame==0) return {{48,4096,-1}};
    // Raw coefficient spans are explicit. The weights follow Q/K/V/O/FC1/FC2.
    return {{1232,776,-1},{6104,192,-1},{10392,192,-1},{11608,472,-1},
            {13104,128,-1},{14256,152,-1},{13232,1024,4},{10584,1024,2},
            {14408,1024,5},{12080,1024,3},{2008,4096,0},{6296,4096,1}};
}

struct Run {
    Vreference_top dut;
    std::array<uint8_t,524288> ram{};
    std::array<std::vector<uint32_t>,13> packets;
    std::vector<Range> ranges;
    Fault fault;
    unsigned interval, frame=0, placed=0, index=0, offset=0, issued=0, confirmed=0;
    uint64_t clocks=0, due=0, begin=0, retired=0, reads=0, aux=0, weights=0, writes=0;
    uint64_t frame_reads=0, response_due=0, quarantine_since=0;
    uint64_t staging_cycles=0, lease_cycles=0, lease_retired=0;
    uint32_t delayed_value=0;
    bool started=false, staged=false, range_active=false, released=false;
    bool delayed=false, cancel_next=false, saw_quarantine=false, done=false;

    Run(const std::string &elf, const std::string &root, unsigned rate, Fault injection)
        : fault(injection), interval(rate) {
        std::ifstream image(elf,std::ios::binary);
        check(bool(image),"missing firmware");
        std::vector<uint8_t> program((std::istreambuf_iterator<char>(image)),{});
        check(program.size()<0x20000,"firmware bounds");
        for(unsigned j=0;j<program.size();++j) ram[j]=program[j];
        for(unsigned j=0;j<13;++j) {
            char name[32];
            if(j==0) std::snprintf(name,sizeof(name),"common.bin.hex");
            else std::snprintf(name,sizeof(name),"layer_%02u.bin.hex",j-1);
            std::ifstream in(root+"/"+name);
            uint32_t word;
            while(in>>std::hex>>word) packets[j].push_back(word);
            check(packets[j].size()==(j==0?4144u:15432u),"fixture length");
        }
        if(fault==Fault::crc) packets[0].back()^=1;
        dut.rst_n=0; dut.hrv=0; dut.mrv=0;
        dut.lease_valid=0; dut.lease_base=ram_base+staging;
        dut.compute_en=0; dut.compute_we=0;
        for(unsigned j=0;j<8;++j) tick();
        dut.rst_n=1;
    }

    uint32_t word(uint32_t a) const {
        return uint32_t(ram[a])|uint32_t(ram[a+1])<<8|uint32_t(ram[a+2])<<16|uint32_t(ram[a+3])<<24;
    }
    void store(uint32_t a,uint32_t data,unsigned mask) {
        for(unsigned j=0;j<4;++j) if(mask>>j&1) ram[a+j]=data>>(8*j);
    }
    uint32_t expected_error() const {
        switch(fault) {
        case Fault::crc: return (4143u<<4)|7u;
        case Fault::cancel: return (100u<<4)|3u;
        case Fault::bus: return (100u<<4)|4u;
        case Fault::late: return 0x80000000u|(100u<<4)|8u;
        case Fault::range: return (48u<<4)|9u;
        default: return 0;
        }
    }
    uint32_t mailbox(bool read,uint32_t address,uint32_t value) {
        check((address&0xffff0000u)==host_base,"unknown peripheral address");
        unsigned reg=address&0xffff;
        if(read) {
            if(reg==12) return staged;
            if(reg==16) return frame+1;
            throw std::runtime_error("unknown mailbox read");
        }
        if(reg==8) {
            check(!started && value==frame && frame<13,"provider order");
            if(frame==0) {begin=clocks; retired=0;}
            started=true; released=false; due=clocks+1024+interval;
            placed=0; index=0; frame_reads=0; ranges=plan(frame,fault);
        } else if(reg==20) {
            check(staged && value==expected_error(),"firmware result or epoch");
            if(fault==Fault::late) {
                check(dut.reset_required && dut.lease_hold && saw_quarantine,"late fault released lease");
            } else {
                check(!dut.lease_hold && !dut.reset_required,"lease still held");
                dut.lease_valid=0;
            }
            if(fault==Fault::none) {
                uint64_t count=packets[frame].size();
                for(const auto &r:ranges) count+=r.words;
                check(index==ranges.size() && !range_active && frame_reads==count,"frame read conservation");
            } else {
                uint64_t count=(fault==Fault::crc || fault==Fault::range)?4144:101;
                check(frame_reads==count && aux==0 && weights==0,"fault exposed data");
            }
            staged=false; started=false; released=true; ++frame;
        } else if(reg==4) {
            check(released && value==expected_error(),"driver completion");
            done=true;
        } else {
            throw std::runtime_error("unexpected mailbox write "+std::to_string(reg)+" value "+std::to_string(value));
        }
        return 0;
    }

    void verify_tile(const Range &r,unsigned row) {
        unsigned reduction=r.matrix==1?256:64;
        unsigned depth=r.words/4;
        for(unsigned bank=0;bank<8;++bank) {
            unsigned slot=((row/reduction)*2+bank/4)*reduction+row%reduction;
            uint32_t expected=packets[frame][r.start+(bank%4)*depth+slot/2]>>(16*(slot%2));
            uint32_t value=dut.tile_data[bank/2]>>(16*(bank%2));
            check(uint16_t(expected)==uint16_t(value),"weight SRAM mismatch");
        }
        weights+=8;
    }

    void tick() {
        ++clocks;
        if(started&&!staged) ++staging_cycles;
        bool host_write=started&&!staged&&clocks>=due;
        if(host_write) {
            store(staging+4*placed,packets[frame][placed],15);
            ++writes; ++placed; due+=interval;
            if(placed==packets[frame].size()) {
                staged=true; dut.lease_valid=1; dut.lease_words=placed; dut.lease_epoch=frame+1;
            }
        }
        if(delayed && fault==Fault::late && clocks>=response_due) {
            dut.mrv=1; dut.mrd=delayed_value; delayed=false;
        }
        const Range *r=started&&index<ranges.size()?&ranges[index]:nullptr;
        dut.cancel=cancel_next;
        cancel_next=false;
        dut.bank_available=clocks%11!=0;
        dut.range_valid=staged&&r&&!range_active;
        dut.range_start=r?r->start:0; dut.range_words=r?r->words:0; dut.range_weight=r&&r->matrix>=0;
        dut.finish_frame=staged&&!r;
        dut.aux_ready=clocks%7>1;
        const bool tile=r&&range_active&&r->matrix>=0;
        dut.tile_read=tile&&issued<r->words/4;
        dut.tile_addr=issued;
        dut.tile_done=tile&&confirmed==r->words/4;
        dut.clk=0; dut.eval();
        dut.mr=!host_write&&!delayed&&(!dut.mrv||dut.mrr);
        dut.hr=!dut.hrv||dut.hrr;
        dut.eval();

        bool mem_take=dut.mv&&dut.mr, host_take=dut.hv&&dut.hr;
        bool mem_rsp=dut.mrv&&dut.mrr, host_rsp=dut.hrv&&dut.hrr;
        uint32_t ma=dut.ma, mw=dut.mw, ha=dut.ha, hw=dut.hw;
        unsigned mmask=dut.mmask;
        bool mem_read=dut.mread, host_read=dut.hread;
        if(begin&&dut.retired) ++retired;
        if(dut.lease_hold) {
            ++lease_cycles;
            if(dut.retired) ++lease_retired;
        }
        if(dut.reset_required) {
            check(dut.lease_hold && !dut.aux_valid && !dut.tile_valid,"quarantine visibility");
            if(!saw_quarantine) quarantine_since=clocks;
            saw_quarantine=true;
        }
        if(dut.range_valid&&dut.range_ready) {
            range_active=true; offset=0; issued=0; confirmed=0;
        }
        if(dut.aux_valid&&dut.aux_ready) {
            check(range_active&&r&&r->matrix<0&&dut.lease_hold,"aux outside verified range");
            check(dut.aux_index==r->start+offset && dut.aux_data==packets[frame][r->start+offset],"raw auxiliary mismatch");
            check(bool(dut.aux_last)==(offset+1==r->words),"aux range boundary");
            ++aux;
            if(++offset==r->words) {++index; range_active=false;}
        }
        if(dut.tile_response) {
            check(tile&&dut.tile_valid&&dut.tile_id==r->matrix&&dut.lease_hold,"tile outside ownership");
            check(bool(dut.tile_deep)==(r->matrix<2),"tile length");
            verify_tile(*r,confirmed++);
        }
        if(dut.tile_read&&dut.tile_ready) ++issued;
        if(dut.tile_done) {++index; range_active=false;}
        dut.clk=1; dut.eval();
        if(mem_rsp) {dut.mrv=0; dut.mem_rsp_err=0;}
        if(host_rsp) dut.hrv=0;
        if(mem_take) {
            check(ma>=ram_base && ma-ram_base<ram.size(),"shared SRAM address");
            unsigned a=(ma-ram_base)&~3u;
            if(a>=staging&&a<staging+65536) {
                check(mem_read && staged && dut.lease_hold && (a-staging)/4<packets[frame].size(),"shared staging lease");
                ++reads; ++frame_reads;
                if(frame_reads==101) {
                    if(fault==Fault::cancel) cancel_next=true;
                    if(fault==Fault::bus) dut.mem_rsp_err=1;
                    if(fault==Fault::late||fault==Fault::lost) {
                        delayed=true; delayed_value=word(a); response_due=clocks+190;
                    }
                }
            }
            if(mem_read) dut.mrd=word(a);
            else {
                check(a>=0x2000 && (a<staging || a>=staging+65536),"CPU wrote immutable region");
                store(a,mw,mmask);
            }
            if(!delayed) dut.mrv=1;
        }
        if(host_take) {
            dut.hrd=mailbox(host_read,ha,hw);
            dut.hrv=1;
        }
    }

    void run() {
        while(!done) {
            tick();
            check(clocks<8000000,"CPU watchdog");
            if(fault==Fault::lost && saw_quarantine && clocks>quarantine_since+48) {
                check(delayed && frame_reads==101 && dut.lease_hold && !aux && !weights,"missing-response isolation");
                dut.rst_n=0; dut.mrv=0; dut.hrv=0;
                tick();
                check(!dut.lease_hold && !dut.reset_required,"hard reset isolation");
                return;
            }
        }
        if(fault==Fault::none) {
            check(frame==13 && reads==363824 && writes==189328 && aux==27040 && weights==294912,"task count");
            std::printf("PASS NORMAL cycles=%llu retired=%llu staging_cycles=%llu lease_cycles=%llu lease_retired=%llu reads=%llu aux=%llu weights=%llu writes=%llu frames=%u\n",
                (unsigned long long)(clocks-begin),(unsigned long long)retired,(unsigned long long)staging_cycles,
                (unsigned long long)lease_cycles,(unsigned long long)lease_retired,(unsigned long long)reads,
                (unsigned long long)aux,(unsigned long long)weights,(unsigned long long)writes,frame);
        } else check(frame==1,"fault advanced to next frame");
    }

    void recover_same_model() {
        check(fault==Fault::lost && !dut.rst_n,"expected reset after permanent response loss");
        fault=Fault::none;
        frame=0; placed=0; index=0; offset=0; issued=0; confirmed=0;
        clocks=0; due=0; begin=0; retired=0; reads=0; aux=0; weights=0; writes=0;
        frame_reads=0; response_due=0; quarantine_since=0;
        staging_cycles=0; lease_cycles=0; lease_retired=0;
        started=false; staged=false; range_active=false; released=false;
        delayed=false; cancel_next=false; saw_quarantine=false; done=false;
        dut.lease_valid=0; dut.mem_rsp_err=0;
        for(unsigned j=0;j<8;++j) tick();
        dut.rst_n=1;
        run();
    }
};
}

int main(int argc,char **argv) {
    try {
        check(argc==5,"usage: firmware fixtures cycles-per-word normal|faults");
        Verilated::commandArgs(argc,argv);
        unsigned rate=std::stoul(argv[3]);
        check(rate==3||rate==6||rate==12,"unsupported staging rate");
        if(std::string(argv[4])=="faults") {
            for(Fault fault:{Fault::crc,Fault::cancel,Fault::bus,Fault::late,Fault::lost,Fault::range}) {
                Run session(argv[1],argv[2],rate,fault);
                session.run();
                std::printf("PASS fault=%u reads=%llu cycles=%llu\n",unsigned(fault),
                            (unsigned long long)session.reads,(unsigned long long)session.clocks);
                if(fault==Fault::lost) session.recover_same_model();
            }
            std::puts("PASS FAULTS CRC cancel source-error late permanent illegal-range cold-recovery");
        } else {
            Run session(argv[1],argv[2],rate,Fault::none);
            session.run();
        }
        return 0;
    } catch(const std::exception &e) {
        std::fprintf(stderr,"FAIL %s\n",e.what());
        return 1;
    }
}
