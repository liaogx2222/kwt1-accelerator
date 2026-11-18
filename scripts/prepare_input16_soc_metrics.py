"""Build full digital SoC measurement sources around the frozen input16 RTL."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REV='595724b88858b142a407f6a5c4761945252d523b'
MON={
 'pv':('','sysper_icb_cmd_valid'),'pr':('','sysper_icb_cmd_ready'),
 'pread':('','sysper_icb_cmd_read'),'pa':('[31:0]','sysper_icb_cmd_addr'),
 'pw':('[31:0]','sysper_icb_cmd_wdata'),'rv':('','sysper_icb_rsp_valid'),
 'rr':('','sysper_icb_rsp_ready'),'rerr':('','sysper_icb_rsp_err'),
 'rd':('[31:0]','sysper_icb_rsp_rdata'),'mv':('','sysmem_icb_cmd_valid'),
 'mr':('','sysmem_icb_cmd_ready'),'mread':('','sysmem_icb_cmd_read'),
 'ma':('[31:0]','sysmem_icb_cmd_addr'),'mw':('[31:0]','sysmem_icb_cmd_wdata'),
 'mrv':('','sysmem_icb_rsp_valid'),'mrr':('','sysmem_icb_rsp_ready'),
 'xv':('','phy_valid'),'xr':('','phy_ready'),'xread':('','phy_read'),
 'xa':('[31:0]','phy_addr'),'xw':('[31:0]','phy_wdata'),
 'bi':('','blk_sink_valid&&blk_sink_ready&&blk_sink_input'),
 'bp':('','blk_sink_valid&&blk_sink_ready&&!blk_sink_input')}


def sha(data):return hashlib.sha256(data).hexdigest()
def dump(value):return (json.dumps(value,indent=2,sort_keys=True)+'\n').encode()


def build():
    base=ROOT/'deliverables/soc_joint_resetguard_20261111/project'
    upstream=ROOT.parent/'arch60-input16'
    old=json.loads((base/'manifest.json').read_bytes())
    files={n:(base/n).read_bytes() for n in old['files'] if n.startswith('cpu/')}
    assert all(sha(d)==old['files'][n]['sha256'] for n,d in files.items())
    files={n:d for n,d in files.items() if Path(n).name!='e203_subsys_nice_core.v'}
    def blob(n):return subprocess.check_output(['git','show',REV+':'+n],cwd=upstream)
    for n in ['e203_cpu.v','e203_cpu_top.v','e203_subsys_main.v','e203_subsys_top.v']:
        target=next(x for x in files if Path(x).name==n)
        files[target]=blob('rtl/arch60_block/generated/'+n)
    ram=next(n for n in files if Path(n).name=='sirv_sim_ram.v')
    files[ram]=(ROOT/'flow/soc_metrics/sirv_sim_ram.v').read_bytes().replace(b'\r\n',b'\n')
    for n in ['kwt_nice_block.sv','kwt_cpu_nice_arbiter.sv']:
        files['soc/'+n]=blob('rtl/arch60_block/'+n)
    for n in ['kwt_soc_icb_bridge.sv','kwt_soc_shared_sram.sv']:
        files['soc/'+n]=blob('rtl/soc_joint/'+n)
    files['soc/kwt_soc_shared_sram.sv']=files['soc/kwt_soc_shared_sram.sv'].replace(b'kwt_sram_sp',b'soc_sram_sp')
    files['soc/soc_sram_sp.sv']=b'''module soc_sram_sp(input clk,en,we,input[11:0]addr,input[15:0]wdata,output[15:0]rdata);
 RAMSP4096X16 macro_cell(.Q(rdata),.CLK(clk),.CEN(~en),.GWEN(~(en&&we)),
 .WEN(en&&we?16'h0000:16'hffff),.A(addr),.D(wdata),.EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));
endmodule
'''
    files['soc/sirv_mrom_top.v']=blob('rtl/arch60_block/generated/sirv_mrom_top.v')
    soc=blob('rtl/arch60_block/generated/kwt_soc_joint.sv').decode()
    anchor='  input  wire [31:0] shmem_host_wdata\n);'
    assert soc.count(anchor)==1
    ports=''.join(',\n output wire %s mon_%s'%(width,n) for n,(width,_) in MON.items())
    soc=soc.replace(anchor,'  input  wire [31:0] shmem_host_wdata'+ports+'\n);')
    assignments='\n'.join(' assign mon_%s=%s;'%(n,expr) for n,(_,expr) in MON.items())+'\n'
    assert soc.count('endmodule')==1;soc=soc.replace('endmodule',assignments+'endmodule')
    files['soc/local_kwt_soc_joint.sv']=soc.encode()
    # The accepted DDC top was normalized to kwt1_mmio and already has
    # BLOCK_STREAM=1 elaborated. Do not re-parameterize a mapped DDC design.
    mapped_soc=soc.replace('kwt1_mmio #(.BLOCK_STREAM(1)) u_kwt1_mmio (','kwt1_mmio u_kwt1_mmio (')
    assert mapped_soc!=soc
    files['soc/kwt_soc_joint.sv']=mapped_soc.encode()
    # Only observability ports change: no neural arithmetic or CPU program edits.
    tb=(ROOT/'flow/soc_metrics/tb_soc_metrics.sv').read_text()
    oldtb=(ROOT/'rtl/soc_joint/tb_soc_joint.sv').read_text()
    start=oldtb.index('  kwt_soc_joint dut (');end=oldtb.index('\n  );',start)+len('\n  );')
    instance=oldtb[start:end]
    last='    .shmem_host_wdata            (host_wdata)'
    assert last in instance
    instance=instance.replace(last,last+''.join(',\n    .mon_%s(%s)'%(n,n) for n in MON))
    assert tb.count('\n DUT_INSTANCE\n')==1
    tb=tb.replace('\n DUT_INSTANCE\n','\n'+instance+'\n')
    tb=tb.replace(' wire host_ready;',' wire host_ready;reg bootrom_n=0;reg[31:0]gpioa=0,gpiob=0;\n wire hfxoscen,lfxoscen,accel_irq;wire[31:0]gpioa_o,gpioa_oe,gpiob_o,gpiob_oe;')
    files['flow/tb_soc_metrics.sv']=tb.encode()
    for n in ['common.tcl','dc.tcl','pt.tcl','constraints.sdc','project.py','run.py','collect.py']:
        files['flow/'+n]=(ROOT/'flow/soc_metrics'/n).read_bytes().replace(b'\r\n',b'\n')
    files['flow/sram_contract_ret1n.v']=(ROOT/'deliverables/reset_anchor_20261111/project/flow/sram_contract_ret1n.v').read_bytes()
    for n in ['common.bin.hex']+['layer_%02d.bin.hex'%i for i in range(12)]+['input_000.hex','expected_000.hex']:
        files['fixtures/'+n]=(upstream/'testdata/input16_fast/fixtures_final'/n).read_bytes()
    cpu=[n for n in files if n.startswith('cpu/')]
    soc_sources=cpu+['soc/'+n for n in ['kwt_nice_block.sv','kwt_cpu_nice_arbiter.sv','sirv_mrom_top.v',
        'kwt_soc_icb_bridge.sv','soc_sram_sp.sv','kwt_soc_shared_sram.sv','kwt_soc_joint.sv']]
    includes=sorted({str(Path(n).parent).replace('\\','/') for n in cpu})
    files['flow/includes.txt']=('\n'.join(includes)+'\n').encode()
    files['flow/soc_sources.txt']=('\n'.join(soc_sources)+'\n').encode()
    # Local verification has actual encoder RTL instead of the future DDC.
    accelerator=['rtl/micro/mul_pipe.sv','rtl/micro/rne_pipe.sv']+['rtl/v2/'+n for n in [
        'kwt_sram_sp.sv','kwt_mac_array.sv','kwt_iterative.sv','kwt_math.sv','kwt_packet_loader.sv',
        'kwt_layer_banked.sv','kwt1_accel.sv','kwt1_mmio.sv','generated/kwt_profile.svh']]+[
        'rtl/integration/smic40/kwt_tech_sram_4096x16.sv']
    for n in accelerator:files[n]=blob(n)
    local_sources=[n if n!='soc/kwt_soc_joint.sv' else 'soc/local_kwt_soc_joint.sv' for n in soc_sources]
    files['flow/local_sources.txt']=('\n'.join(local_sources+[n for n in accelerator if not n.endswith('.svh')])+ '\n').encode()
    manifest=dict(schema=1,RTL_revision=REV,scope='full digital reference SoC including all SRAM; analog and external devices excluded',
        source_SoC_reference='9f3e34f337f5d0a1236a285871ffa2032491617a',
        accelerator_directory='kwt_parallel_max_20261112_input16_595724b',
        expected_macros=dict(private=20,shared=64,ITCM=8,DTCM=8,total=100),
        CPU_configuration='same functional FPGA_SOURCE clock bypass; 64KiB ITCM and 64KiB DTCM, no ECC',
        TCM_contract='synchronous selected read, byte write mask; data on write/idle not consumed',
        task_window='first host word through CPU completion-store response',
        declared_operating_PVT=dict(corner='TT',voltage_V=1.1,temperature_C=25,frequency_Hz=150000000),
        optimization_corners=dict(frozen_accelerator='existing SS optimization; running job preserved',platform='TT'),
        comparison_contract='same declared TT libraries, clocks, I/O and wire-model conditions; source optimization histories recorded separately',
        work_in_progress=True,actual_server_run=False,files={n:sha(d) for n,d in sorted(files.items())})
    files['manifest.json']=dump(manifest)
    return files


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    assert not a.output.exists()
    for n,d in build().items():
        p=a.output/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(d)
    print('SOC_METRICS_REFERENCE_PREPARED '+str(a.output.resolve()))
