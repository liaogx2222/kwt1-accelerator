"""Independent Q&A-compliant System Bus candidate, frozen arithmetic reused."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import prepare_input16_soc_metrics as base
ROOT=Path(__file__).resolve().parents[1]
REV=base.REV


def once(s,old,new):
    assert s.count(old)==1,(old[:100],s.count(old))
    return s.replace(old,new)


def build():
    f=base.build()
    # All three masters traverse the unmodified original System Bus decoder.
    host_ports=''' input wire load_cmd_valid,output wire load_cmd_ready,
 input wire [31:0] load_cmd_addr,load_cmd_wdata,
 output wire load_rsp_valid,input wire load_rsp_ready,
 output wire [31:0] load_rsp_rdata,output wire load_rsp_error,
'''
    host_connections=''' .load_cmd_valid(load_cmd_valid),.load_cmd_ready(load_cmd_ready),
 .load_cmd_addr(load_cmd_addr),.load_cmd_wdata(load_cmd_wdata),
 .load_rsp_valid(load_rsp_valid),.load_rsp_ready(load_rsp_ready),
 .load_rsp_rdata(load_rsp_rdata),.load_rsp_error(load_rsp_error),
'''
    names={Path(n).name:n for n in f if n.startswith('cpu/')}
    memory_ports=[('blk_mem_valid',''),('blk_mem_ready',''),('blk_mem_addr','[31:0]'),
      ('blk_mem_read',''),('blk_mem_wdata','[31:0]'),('blk_rsp_valid',''),
      ('blk_rsp_ready',''),('blk_rsp_data','[31:0]'),('blk_rsp_error','')]
    for name,opening,child in [
      ('e203_subsys_top.v','module e203_subsys_top(\n','  e203_subsys_main  u_e203_subsys_main(\n'),
      ('e203_subsys_main.v','module e203_subsys_main(\n',None)]:
        s=f[names[name]].decode();s=once(s,opening,opening+host_ports)
        if child:s=once(s,child,child+host_connections)
        for port,width in memory_ports:
            s,n=re.subn(r'^\s*(?:input|output) wire[^\n]*\b'+port+r',\n','',s,flags=re.M)
            assert n==1,port
            if child:s=once(s,'    .%s(%s),\n'%(port,port),'')
        if name=='e203_subsys_main.v':
            endports=re.search(r'\n\s*\);\s*\n',s).end()
            s=s[:endports]+''.join(' wire %s %s;\n'%(w,n) for n,w in memory_ports)+s[endports:]
            anchor='e203_subsys_mems u_e203_subsys_mems('
            begin=s.index(anchor);end=s.index('\n  );',begin)+len('\n  );')
            original=s[begin:end]
            new=original
            for n in ['cmd_valid','cmd_ready','cmd_addr','cmd_read','cmd_wdata','cmd_wmask','rsp_valid','rsp_ready','rsp_err','rsp_rdata']:
                new=once(new,'('+('mem_icb_'+n), '('+('bus_icb_'+n))
            arb=''' wire bus_icb_cmd_valid,bus_icb_cmd_ready,bus_icb_cmd_read;
 wire [31:0] bus_icb_cmd_addr,bus_icb_cmd_wdata,bus_icb_rsp_rdata;
 wire [3:0] bus_icb_cmd_wmask;
 wire bus_icb_rsp_valid,bus_icb_rsp_ready,bus_icb_rsp_err;
 wire [2:0] sys_ready,sys_rvalid,sys_rerror;wire [95:0] sys_rdata;
 assign mem_icb_cmd_ready=sys_ready[0];assign blk_mem_ready=sys_ready[1];assign load_cmd_ready=sys_ready[2];
 assign mem_icb_rsp_valid=sys_rvalid[0];assign blk_rsp_valid=sys_rvalid[1];assign load_rsp_valid=sys_rvalid[2];
 assign mem_icb_rsp_rdata=sys_rdata[31:0];assign blk_rsp_data=sys_rdata[63:32];assign load_rsp_rdata=sys_rdata[95:64];
 assign mem_icb_rsp_err=sys_rerror[0];assign blk_rsp_error=sys_rerror[1];assign load_rsp_error=sys_rerror[2];
 kwt_sysbus_arbiter3 system_bus_masters(
  .clk(hfclk),.rst_n(bus_rst_n),
  .cmd_valid({load_cmd_valid,blk_mem_valid,mem_icb_cmd_valid}),.cmd_ready(sys_ready),
  .cmd_addr({load_cmd_addr,blk_mem_addr,mem_icb_cmd_addr}),
  .cmd_wdata({load_cmd_wdata,blk_mem_wdata,mem_icb_cmd_wdata}),
  .cmd_read({1'b0,blk_mem_read,mem_icb_cmd_read}),.cmd_wmask({4'hf,4'hf,mem_icb_cmd_wmask}),
  .rsp_valid(sys_rvalid),.rsp_ready({load_rsp_ready,blk_rsp_ready,mem_icb_rsp_ready}),
  .rsp_rdata(sys_rdata),.rsp_error(sys_rerror),
  .bus_valid(bus_icb_cmd_valid),.bus_ready(bus_icb_cmd_ready),
  .bus_addr(bus_icb_cmd_addr),.bus_wdata(bus_icb_cmd_wdata),
  .bus_read(bus_icb_cmd_read),.bus_wmask(bus_icb_cmd_wmask),
  .bus_rsp_valid(bus_icb_rsp_valid),.bus_rsp_ready(bus_icb_rsp_ready),
  .bus_rsp_rdata(bus_icb_rsp_rdata),.bus_rsp_error(bus_icb_rsp_err));
'''
            s=s[:begin]+arb+new+s[end:]
        f[names[name]]=s.encode()
    arb='soc/kwt_sysbus_arbiter3.sv';f[arb]=(ROOT/'rtl/sysbus_v1/kwt_sysbus_arbiter3.sv').read_bytes()
    # Delete the SRAM-private loader port. Only the original ICB slave remains.
    n='soc/kwt_soc_shared_sram.sv';s=f[n].decode()
    start=s.index('  // ---- platform loader port');end=s.index('\n);',start)
    s=s[:start]+s[end:];s=once(s,'output wire [DW-1:0] rsp_rdata,','output wire [DW-1:0] rsp_rdata')
    s=once(s,'  assign host_ready = rst_n && !rmw;\n','')
    s=once(s,'rst_n && !host_en && !rmw','rst_n && !rmw')
    start=s.index('    end else if (host_en && host_ready) begin');end=s.index('    end else if (accept) begin',start)
    s=s[:start]+s[end:];f[n]=s.encode()
    for n in ['soc/local_kwt_soc_joint.sv','soc/kwt_soc_joint.sv']:
        s=f[n].decode()
        wire=''' wire load_cmd_valid,load_cmd_ready,load_rsp_valid,load_rsp_ready,load_rsp_error;
 wire [31:0] load_cmd_addr,load_cmd_wdata,load_rsp_rdata;
 reg load_pending;
 assign load_cmd_valid=kwt_rst_n&&shmem_host_en&&!load_pending;
 assign load_cmd_addr=32'ha0000000+{13'd0,shmem_host_addr,2'b00};
 assign load_cmd_wdata=shmem_host_wdata;
 assign load_rsp_ready=kwt_rst_n;
 assign shmem_host_ready=kwt_rst_n&&load_pending&&load_rsp_valid;
 always @(posedge hfextclk or negedge kwt_rst_n)begin
  if(!kwt_rst_n)load_pending<=0;
  else begin
   if(load_cmd_valid&&load_cmd_ready)load_pending<=1;
   if(load_rsp_valid&&load_rsp_ready)load_pending<=0;
  end
 end
'''
        s=once(s,' e203_subsys_top u_e203_subsys_top(\n',wire+' e203_subsys_top u_e203_subsys_top(\n'+host_connections)
        for port,width in memory_ports:s=once(s,'    .%s(%s),\n'%(port,port),'')
        start=s.index(' kwt_cpu_nice_arbiter cpu_nice_arbiter(');end=s.index('  kwt_soc_shared_sram #(',start)
        aliases=''' assign phy_valid=sysmem_icb_cmd_valid;assign sysmem_icb_cmd_ready=phy_ready;
 assign phy_addr=sysmem_icb_cmd_addr;assign phy_read=sysmem_icb_cmd_read;
 assign phy_wdata=sysmem_icb_cmd_wdata;assign phy_wmask=sysmem_icb_cmd_wmask;
 assign sysmem_icb_rsp_valid=phy_rsp_valid;assign phy_rsp_ready=sysmem_icb_rsp_ready;
 assign sysmem_icb_rsp_rdata=phy_rsp_data;assign sysmem_icb_rsp_err=phy_rsp_error;
'''
        s=s[:start]+aliases+s[end:]
        s=once(s,'.rsp_rdata (phy_rsp_data),','.rsp_rdata (phy_rsp_data)')
        start=s.index('    .host_en    (shmem_host_en');end=s.index('\n  );',start)
        s=s[:start]+s[end:]
        f[n]=s.encode()
    # DC retains original HDL-reference aliases even after rename_design on a
    # loaded DDC. Give the TWO CHANGED wrappers genuinely new HDL names.
    # Instance names, ports, connections, clocks and all logic remain identical.
    for name in ['e203_subsys_main.v','e203_subsys_top.v']:
        n=names[name];s=f[n].decode()
        old='e203_subsys_main' if name=='e203_subsys_main.v' else 'e203_subsys_top'
        s=once(s,'module '+old+'(','module sysbus_'+old+'(')
        if name=='e203_subsys_top.v':
            s=once(s,'  e203_subsys_main  u_e203_subsys_main(',
                      '  sysbus_e203_subsys_main  u_e203_subsys_main(')
        f[n]=s.encode()
    for n in ['soc/local_kwt_soc_joint.sv','soc/kwt_soc_joint.sv']:
        s=f[n].decode()
        f[n]=once(s,' e203_subsys_top u_e203_subsys_top(',
                    ' sysbus_e203_subsys_top u_e203_subsys_top(').encode()
    for n in ['flow/soc_sources.txt','flow/local_sources.txt']:
        s=f[n].decode();s=s.replace('soc/kwt_cpu_nice_arbiter.sv\n','')
        # The unused upstream chip top references the old subsystem type.
        # The candidate has its own top; do not elaborate that obsolete entry.
        s=''.join(line+'\n' for line in s.splitlines() if Path(line).name!='e203_soc_top.v')
        f[n]=(arb+'\n'+s).encode()
    # Export all 12 inputs for the official-style arbitrary-case entry point.
    for i in range(12):
        for prefix in ['input','expected']:
            n='fixtures/%s_%03d.hex'%(prefix,i)
            f[n]=(ROOT.parent/'arch60-input16/testdata/input16_fast/fixtures_final'/Path(n).name).read_bytes()
    for n in ['soc/kwt_cpu_nice_arbiter.sv']:f.pop(n,None)
    # Live gate arithmetic is untouched; monitors retain original names.
    m=json.loads(f['manifest.json']);m.update(integration_revision='SYSBUS_V1',work_in_progress=True,
        bus_route='CPU, NICE and loader -> original e203_subsys_mems -> original 32-bit sysmem ICB -> shared SRAM',
        dedicated_SRAM_loader_port=False,backend_SRAM_arbiter=False,arithmetic_changed=False)
    m['files']={n:hashlib.sha256(d).hexdigest() for n,d in sorted(f.items()) if n!='manifest.json'}
    f['manifest.json']=(json.dumps(m,indent=2)+'\n').encode()
    return f


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    assert not a.output.exists(),'PRESERVE_CANDIDATE'
    for n,d in build().items():
        target=a.output/n;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(d)
    print('SYSBUS_CANDIDATE_PREPARED '+str(a.output.resolve()))
