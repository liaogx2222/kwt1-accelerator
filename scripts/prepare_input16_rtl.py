"""Isolated complete 8x8 RTL port for the validated S16-first-input profile."""
import argparse
import hashlib
import inspect
import json
import shutil
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_rtl_v1 as old_generator
from integer_model.hw_abi import pack,unpack,HEADER,ENTRY


def change(text,old,new,count=1):
    assert text.count(old)==count,(old,text.count(old));return text.replace(old,new)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();dest=ROOT/'rtl/input16';assert not out.exists() and not dest.exists();out.mkdir(parents=True);dest.mkdir();v2=ROOT/'rtl/v2'
    files={n:(v2/n).read_text() for n in ['kwt1_accel.sv','kwt_layer_banked.sv','kwt_mac8x8.sv','kwt_iterative.sv','kwt_math.sv','kwt_packet_loader.sv','kwt_sram_sp.sv','kwt_tech_sram_blackbox.sv','kwt1_mmio.sv']}
    t=files['kwt1_accel.sv'];t=change(t,'pair_buffer[0:127]','pair_buffer[0:255]');t=change(t,'reg [12:0] input_bytes','reg [13:0] input_bytes')
    t=change(t,'bank_wdata[ob_bank*16+:16]={pair_index==49?8\'d0:pair_buffer[64+input_ch],pair_buffer[input_ch]};',
        "bank_wdata[ob_bank*16+:16]={pair_index==49?8'd0:pair_buffer[128+2*input_ch],pair_buffer[2*input_ch]};\n    bank_en[ob_bank+4]=1;bank_we[ob_bank+4]=1;bank_addr[(ob_bank+4)*12+:12]=1664+ob_addr;\n    bank_wdata[(ob_bank+4)*16+:16]={pair_index==49?8'd0:pair_buffer[129+2*input_ch],pair_buffer[2*input_ch+1]};")
    t=change(t,'input_data[7:0]==128||input_data[15:8]==128||input_data[23:16]==128||input_data[31:24]==128',
        "input_data[15:0]==16'h8000||input_data[31:16]==16'h8000||(SINGLE_LAYER&&current_layer!=0&&($signed(input_data[15:0])>127||$signed(input_data[15:0])< -127||$signed(input_data[31:16])>127||$signed(input_data[31:16])< -127))")
    t=change(t,'input_bytes==6332','input_bytes==12668');t=change(t,'pair_index==49?15:31','pair_index==49?31:63');files['kwt1_accel.sv']=t
    t=files['kwt_mac8x8.sv'];t=change(t,'input wire [63:0] a,b','input wire [127:0] a,input wire [63:0] b')
    t=change(t,"wire signed [8:0] av=unsigned_a?$signed({1'b0,a[r*8+:8]}):$signed({a[r*8+7],a[r*8+:8]});", "wire signed [16:0] av=unsigned_a?$signed({1'b0,a[r*16+:16]}):$signed({a[r*16+15],a[r*16+:16]});")
    t=change(t,'wire signed [16:0] product','wire signed [24:0] product');files['kwt_mac8x8.sv']=t
    t=files['kwt_layer_banked.sv'];t=change(t,'reg signed [15:0] residual[0:63]','reg signed [23:0] residual[0:63]');t=change(t,'reg [7:0] residual_x','reg [15:0] residual_x')
    t=change(t,'reg [63:0] mac_a,mac_b','reg [127:0] mac_a;reg [63:0] mac_b')
    t=change(t,"logical_ma=sent[0]?$signed(residual[sent/2][15:8]):$signed(residual[sent/2][7:0]);", "logical_ma=sent[0]?$signed(residual[sent/2][23:16]):$signed(residual[sent/2][15:0]);")
    t=change(t,'mem_en[source_group+j]=1;mem_addr[(source_group+j)*12+:12]=source_base+((token/8)<<(kind==5?8:6))+read_red;',
        'mem_en[source_group+j]=1;mem_addr[(source_group+j)*12+:12]=source_base+((token/8)<<(kind==5?8:6))+read_red;\n    if(layer==0&&kind<3)begin mem_en[12+j]=1;mem_addr[(12+j)*12+:12]=1664+(token/8)*64+read_red;end')
    t=change(t,'mem_addr[bank_index*12+:12]=(row_token/8)*64+ch+(state==N_LOAD_A?2496:state==N_LOAD_B?1:0);',
        'mem_addr[bank_index*12+:12]=(row_token/8)*64+ch+(state==N_LOAD_A?2496:state==N_LOAD_B?1:0);\n    if(layer==0&&!norm2&&state!=N_LOAD_A)begin mem_en[bank_index+4]=1;mem_addr[(bank_index+4)*12+:12]=1664+(row_token/8)*64+ch+(state==N_LOAD_B);end')
    t=change(t,'for(integer z=0;z<4;z=z+1)begin mac_a[z*16+:16]=mem_rdata[(source_group+z)*16+:16];mac_b[z*16+:16]=mem_rdata[(2*z+((wb+((oc/8)<<(kind==5?8:6))+red)/4096))*16+:16];end',
        "for(integer z=0;z<8;z=z+1)mac_a[z*16+:16]=(layer==0&&kind<3)?{byte_at(mem_rdata,12+z/2,z%2),byte_at(mem_rdata,source_group+z/2,z%2)}:$signed(byte_at(mem_rdata,source_group+z/2,z%2));\n   for(integer z=0;z<4;z=z+1)mac_b[z*16+:16]=mem_rdata[(2*z+((wb+((oc/8)<<(kind==5?8:6))+red)/4096))*16+:16];")
    t=change(t,'for(integer z=0;z<4;z=z+1)begin mac_a[z*16+:16]=mem_rdata[(8+z)*16+:16];mac_b[z*16+:16]=mem_rdata[(12+z)*16+:16];end',
        'for(integer z=0;z<8;z=z+1)mac_a[z*16+:16]=$signed(byte_at(mem_rdata,8+z/2,z%2));for(integer z=0;z<4;z=z+1)mac_b[z*16+:16]=mem_rdata[(12+z)*16+:16];')
    t=change(t,'mac_a[z*8+:8]=probabilities[z*99+red]>>(plane?8:0);', "mac_a[z*16+:16]=plane?{8'd0,probabilities[z*99+red][15:8]}:{8'd0,probabilities[z*99+red][7:0]};")
    t=change(t,'residual_x<=$signed(mem_rdata[(8+(row_token%8)/2)*16+8*(row_token%2)+:8]);',
        'residual_x<=(layer==0&&!norm2)?{byte_at(mem_rdata,12+(row_token%8)/2,row_token%2),byte_at(mem_rdata,8+(row_token%8)/2,row_token%2)}:$signed(byte_at(mem_rdata,8+(row_token%8)/2,row_token%2));')
    t=change(t,'residual[math_tag]<=math_result[15:0]',"residual[math_tag]<={{8{math_result[15]}},math_result[15:0]}")
    t=change(t,'{{48{residual[sent][15]}},residual[sent]}','{{48{residual[sent][15]}},residual[sent][15:0]}');files['kwt_layer_banked.sv']=t
    files['kwt1_mmio.sv']=change(files['kwt1_mmio.sv'],"32'h4b575431","32'h4b575432")
    for name,text in files.items():(dest/name).write_text('// Experimental S16-first-input complete 8x8 baseline. Not the 16x16 model.\n'+text)
    cpp=(v2/'sim_accel.cpp').read_text();cpp=change(cpp,'v.size()==1584,"input length"','v.size()==3168,"input length"');cpp=change(cpp,'d.input_data=bad?0:128','d.input_data=bad?0:0x8000');(dest/'sim_accel.cpp').write_text(cpp)
    candidate=ROOT/'testdata/accuracy_point1_20261104/input16_only';p=dict(np.load(candidate/'run/params/parameters.npz'));profile=sha(candidate/'run/params/parameters.npz')
    schema={n:dict(shape=list(v.shape),dtype=v.dtype.str,sha256=hashlib.sha256(v.tobytes()).hexdigest()) for n,v in p.items()}
    packets={'common.bin':pack(p,profile)};packets.update({f'layer_{i:02d}.bin':pack(p,profile,i) for i in range(12)})
    for name,data in packets.items():
        layer=None if name=='common.bin' else int(name[6:8]);recovered=unpack(data,profile,schema,layer)
        assert all(np.array_equal(v,p[n]) for n,v in recovered.items());(out/name).write_bytes(data)
    source=inspect.getsource(old_generator.generate).replace("ROOT/'rtl/v1/generated'","ROOT/'rtl/input16/generated'").replace("ROOT/'testdata/integer_v1/params/parameters.npz'","ROOT/'testdata/accuracy_point1_20261104/input16_only/run/params/parameters.npz'").replace('INTEGER_NUMERICS_V1','INPUT16_V1')
    (out/'executed_header_generator.py').write_text(source);namespace=dict(ROOT=ROOT,artifacts=lambda:(packets,p),HEADER=HEADER,ENTRY=ENTRY,json=json,hashlib=hashlib)
    exec(compile(source,str(out/'executed_header_generator.py'),'exec'),namespace);namespace['generate']()
    sources=[Path(__file__),Path(old_generator.__file__),candidate/'run/params/parameters.npz',*[v2/n for n in files],v2/'sim_accel.cpp',*dest.glob('*.*'),*dest.glob('generated/*')]
    report=dict(passed=True,precision='S16 first input/S8 internal/W8',complete_encoder_RTL_written=True,RTL_validated=False,array='8x8 signed16x8 products, unchanged 32bit accumulators',
        SRAM=dict(macros=20,geometry='4096x16',bytes=163840),input_bytes=12672,output_bytes=6336,profile_sha256=profile,
        first_input_layout='low byte plane A[0:831], high byte plane B[1664:2495]; preserves input through LN1',packets=13,packets_roundtrip_checked=True,
        separation='complete 8x8 integration candidate; never inherits 16x16 core cycles or 64KiB geometry',MMIO_ID='0x4b575432')
    (out/'verification.json').write_text(json.dumps(report,indent=2));(out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2));(out/'manifest.json').write_text(json.dumps({s.name:sha(s) for s in out.iterdir() if s.is_file()},indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
