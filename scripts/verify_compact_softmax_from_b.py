"""Drive the accepted Softmax row kernel from physical B score storage."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from local_tools import ROOT, sha
from run_input16_e203_block import replace_once


def bench(source):
    edits=[
        ('    reg [31:0] scores[', '''    reg bstart=0,btail=0,bsv=0,bclose=0,brelease=0,brv=0,bpr=0;
    reg [1:0] bquad=0;
    reg [6:0] bkey=0,brkey=0;
    reg [3:0] bmask=0,brow=0;
    reg [127:0] bdata=0;
    wire bstart_ready,bsready,bavailable,berror,brready,bpv;
    wire signed [31:0] bscore;
    wire [7:0] b_en,b_we;
    wire [9:0] b_addr;
    wire [127:0] b_in,b_out;
    kwt_compact_qk_score_store score_store(clk,rst_n,clear,bstart,btail,bstart_ready,bsv,bsready,bquad,bkey,bmask,
        bdata,bclose,brelease,bavailable,berror,brv,brready,brow,brkey,bpv,bpr,bscore,b_en,b_we,b_addr,b_in,b_out);
    for(genvar i=0;i<8;i=i+1)begin:b_bank
        kwt_small_sp mem(clk,b_en[i],b_we[i],b_addr,b_in[16*i+:16],b_out[16*i+:16]);
    end

    reg [31:0] scores['''),
        ('    task automatic row(', '''    task automatic publish(input integer first,input bit tail);
        begin
            if(!bstart_ready)$fatal(1,"B score group not idle");
            bstart=1;btail=tail;tick();bstart=0;
            for(integer quad=0;quad<(tail?1:4);quad=quad+1)
                for(integer key=0;key<99;key=key+1)begin
                    bsv=1;bquad=2'(quad);bkey=7'(key);bmask=tail?7:15;
                    for(integer lane=0;lane<4;lane=lane+1)
                        bdata[32*lane+:32]=scores[(first+quad*4+lane)*99+key];
                    #1;
                    if(!bsready||berror)$fatal(1,"B score rejected");
                    tick();
                end
            bsv=0;bclose=1;tick();bclose=0;
            if(!bavailable||berror)$fatal(1,"B score not published");
        end
    endtask
    task automatic release_b;
        begin brv=0;bpr=0;brelease=1;tick();brelease=0;end
    endtask

    task automatic row('''),
        ('integer sent,queries,received,elapsed;', 'integer sent,queries,received,elapsed,requested;'),
        ('elapsed=1;held=0;', 'elapsed=1;held=0;requested=0;'),
        ('                sv=sent<99&&elapsed%9!=0;\n                if(sv)score=scores[row_id*99+sent];',
         '''                brv=requested<99;brow=4'(row_id%16);brkey=7'(requested%99);
                sv=bpv&&elapsed%9!=0;score=bscore;bpr=sr&&elapsed%9!=0;'''),
        ('                if(sv&&sr)++sent;',
         '''                if(berror||!bavailable)$fatal(1,"lost B score ownership");
                if(brv&&brready)++requested;
                if(sv&&sr)begin
                    if(score!==scores[row_id*99+sent])$fatal(1,"B score mismatched before Softmax");
                    ++sent;
                end'''),
        ('tick();clear=0;#1;', 'tick();clear=0;brv=0;bpr=0;#1;'),
        ('sent!=99||!start_ready','sent!=99||requested!=99||!start_ready'),
        ('        tick();rst_n=1;', '        tick();rst_n=1;#1;'),
        ('        for(integer i=0;i<ROWS;i=i+1)row(i,0);\n        row(0,1);\n        load_cache();row(0,0);',
         '''        for(integer group_id=0;group_id<ROWS/16;group_id=group_id+1)begin
            publish(group_id*16,0);
            for(integer row_id=0;row_id<16;row_id=row_id+1)row(group_id*16+row_id,0);
            release_b();
        end
        publish(0,1);row(0,1);
        load_cache();publish(0,1);row(0,0);release_b();'''),
        ('PASS softmax rows=', 'PASS B softmax rows='),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve();out.mkdir(parents=True)
    evidence=ROOT/'testdata/input16_rtl_20261105'
    fixture=evidence/'p4_compact_softmax_row_v1'
    compact=evidence/'p4_compact_softmax_storage_v2'
    score=evidence/'p4_compact_qk_score_store_v3'
    for folder in (fixture,compact,score):
        manifest=json.loads((folder/'manifest.json').read_text())
        for name,digest in manifest.items():
            assert sha(folder/name)==digest,name
    rtl=ROOT/'rtl/block_transfer';trim=ROOT/'rtl/input16_trim2'
    template=rtl/'tb_compact_softmax_row.sv'
    test=out/template.name
    test.write_text(bench(template.read_text()))
    sources=[test,compact/'kwt_compact_softmax_row.sv',rtl/'kwt_compact_qk_score_store.sv',
             rtl/'kwt_compact_exp_cache.sv',trim/'kwt_iterative.sv',trim/'kwt_sram_sp.sv']
    def rel(path):
        return path.relative_to(ROOT).as_posix()
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def run(command,log):
        result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                              capture_output=True,text=True)
        text=result.stdout+result.stderr
        (out/log).write_text(text)
        assert result.returncode==0,(log,text[-2000:])
        return text
    run(f'iverilog -g2012 -DKWT_SIM -s tb_compact_softmax_row -o {rel(out/"test.vvp")} '
        +' '.join(rel(p) for p in sources),'build.log')
    text=run(f'vvp {rel(out/"test.vvp")} +root={rel(fixture)}','simulation.log')
    match=re.search(r'PASS B softmax rows=97 probabilities=9603 exp_indices=9603 cycles=(\d+) max_row=(\d+) stalls=(\d+) cancel=1',text)
    assert match,text
    inputs=[Path(__file__),template,*sources,*[d/'manifest.json' for d in (fixture,compact,score)]]
    report=dict(passed=True,rows=97,profiles=12,score_codes=9603,probability_codes=9603,mismatches=0,
                cycles=int(match[1]),max_row=int(match[2]),stalls=int(match[3]),integrated_E203=False,
                scope='standalone physical B score SRAM to one-array Softmax and actual exp SRAM',
                source_sha256={rel(p):sha(p) for p in inputs})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(text,end='')


if __name__=='__main__':
    main()
