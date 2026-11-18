"""Build and validate the complete banked RTL v1. No golden values in DUT ROM."""
import argparse,hashlib,json,subprocess,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from validate_kwt1_r2 import artifacts
from integer_model.hw_abi import HEADER,ENTRY
from validate_layer_rtl import hexwords

def generate():
    packets,p=artifacts();folder=ROOT/'rtl/v1/generated';folder.mkdir(parents=True,exist_ok=True)
    cb={};offset=0
    for name in sorted(p):
        if not name.startswith('l00_') or name.endswith(('_w','_gelu_lut','_q_b','_k_b','_v_b')):continue
        cb[name[4:]]=offset;offset+=p[name].nbytes//4
    wb={};off=0
    for name in ['q','k','v','o','fc1','fc2']:
        wb[name]=off;k,n=p['l00_'+name+'_w'].shape;off+=k*(n//8)
    text=['// Generated solely from fixed ABI metadata and packet headers.\n']
    for name,val in cb.items():text.append(f'localparam integer CB_{name.upper()}={val};\n')
    for name,val in wb.items():text.append(f'localparam integer WB_{name.upper()}={val};\n')
    text.append('function automatic [31:0] profile_header(input integer common_flag,input integer lid,input integer index);\nbegin\n if(common_flag)case(index)\n')
    for i in range(16):text.append(f'{i}:profile_header=32\'h{int.from_bytes(packets["common.bin"][i*4:i*4+4],"little"):08x};\n')
    text.append('default:profile_header=0;endcase\n else case(lid*16+index)\n')
    for layer in range(12):
        for i in range(16):text.append(f'{layer*16+i}:profile_header=32\'h{int.from_bytes(packets[f"layer_{layer:02d}.bin"][i*4:i*4+4],"little"):08x};\n')
    text.append('default:profile_header=0;endcase\nend\nendfunction\n')
    text.append('function automatic [17:0] packet_location(input integer common_flag,input integer byte_position,input integer halfword);\ninteger pos,logical_address,logical_bank;begin\npacket_location=0;pos=byte_position;logical_address=0;logical_bank=0;\n')
    for common,name in [(True,'common.bin'),(False,'layer_00.bin')]:
        data=packets[name];header=HEADER.unpack(data[:64]);text.append('if(common_flag)begin\n' if common else 'else begin\n')
        for i in range(header[4]):
            e=ENTRY.unpack(data[64+i*128:64+(i+1)*128]);key=e[0].rstrip(b'\0').decode();start=64+header[5]+e[8];length=e[9]
            text.append(f'if(pos>={start} && pos<{start+length})begin\n')
            if common:text.append(f'logical_bank=18+halfword;logical_address=(pos-{start})/4;\n')
            elif key.endswith('_w'):
                k,n=p[key].shape;per=k*n//4
                text.append(f'logical_address={wb[key[4:-2]]}+((pos-{start})%{per})/2+halfword;logical_bank=2*((pos-{start})/{per})+(logical_address/4096);\n')
            elif key.endswith('_gelu_lut'):text.append(f'logical_bank=16;logical_address=1880+(pos-{start})/2+halfword;\n')
            else:text.append(f'logical_bank=16+halfword;logical_address={cb[key[4:]]}+(pos-{start})/4;\n')
            text.append("packet_location={1'b1,logical_bank[4:0],logical_address[11:0]};end\n")
        text.append('end\n')
    text.append('end endfunction\n');path=folder/'kwt_profile.svh';path.write_text(''.join(text),encoding='ascii')
    (folder/'profile.json').write_text(json.dumps(dict(profile='INTEGER_NUMERICS_V1',parameters_sha256=hashlib.sha256((ROOT/'testdata/integer_v1/params/parameters.npz').read_bytes()).hexdigest(),
        coefficient_words=offset,weight_words_per_logical_bank=off,packets={k:hashlib.sha256(v).hexdigest() for k,v in packets.items()},ROM_contains='headers/CRC/layout only; no tensor data or expected outputs'),indent=2),encoding='utf-8')
    return packets,p

def run(cmd,out):
    proc=subprocess.run(cmd,capture_output=True,text=True)
    with (out/'tools.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(dict(command=cmd,exit=proc.returncode,stdout=proc.stdout,stderr=proc.stderr))+'\n')
    if proc.returncode:raise RuntimeError(proc.stdout+proc.stderr)
    print(proc.stdout,flush=True);return proc.stdout

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['generate','unit','layer','full','mmio','stress','cross','all','check'],default='generate');ap.add_argument('--output',type=Path,default=ROOT/'testdata/rtl_v1/release');ap.add_argument('--quick',action='store_true');ap.add_argument('--icarus',action='store_true');a=ap.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
    if a.stage=='all' and a.quick:raise ValueError('--quick is only supported for individual debug stages')
    if a.stage not in ['check','generate'] and (a.output/'verification.json').exists() and json.loads((a.output/'verification.json').read_text()).get('passed'):
        raise ValueError('released evidence exists; choose a fresh --output directory')
    generate()
    if a.stage=='generate':print('ABI metadata ROM generated',flush=True);return
    import runpy
    sys.argv=['rtl_v1_validation.py',a.stage,'--output',str(a.output)]+(['--quick'] if a.quick else [])+(['--icarus'] if a.icarus else [])
    runpy.run_path(str(ROOT/'scripts/rtl_v1_validation.py'),run_name='__main__')
if __name__=='__main__':main()
