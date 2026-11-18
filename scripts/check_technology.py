"""Fail closed before technology synthesis/STA; no libraries are invented."""
import argparse
import json
import re
from pathlib import Path
from local_tools import ROOT, sha


def ports():
    text=re.sub(r'//[^\n]*|/\*.*?\*/','',(ROOT/'rtl/v2/kwt1_mmio.sv').read_text(),flags=re.S)
    header=text.split(');',1)[0].split('(',1)[1]
    result={}
    for direction,group in re.findall(r'\b(input|output)\s+(.*?)(?=\binput\b|\boutput\b|$)',header,re.S):
        group=re.sub(r'\[[^]]+\]|\b(wire|reg|signed)\b','',group)
        for name in re.findall(r'\b[a-zA-Z_]\w*\b',group):result[name]=direction
    return result


def check(config):
    cfg=json.loads(config.read_text());errors=[];missing=[]
    def need(value,name):
        if value is None or value=='' or value==[] or value=={}:missing.append(name);return False
        return True
    def file(value,name):
        if not need(value,name):return None
        p=Path(value);p=p if p.is_absolute() else config.parent/p
        if not p.is_file():errors.append(name+': missing file '+str(value));return None
        return p
    if cfg.get('top')!='kwt1_mmio':errors.append('top must be frozen kwt1_mmio')
    macro=cfg.get('sram',{})
    for key,value in [('instances',20),('depth',4096),('width',16),('boundary_module','kwt_tech_sram_4096x16'),('read_latency_cycles',1),('read_output_holds',True),('write_preserves_read_output',True)]:
        if macro.get(key)!=value:errors.append(f'sram.{key}: frozen contract requires {value}')
    wrapper=file(macro.get('wrapper_rtl'),'sram.wrapper_rtl')
    if wrapper and not re.search(r'\bmodule\s+kwt_tech_sram_4096x16\b',wrapper.read_text()):errors.append('wrapper does not define macro boundary module')
    need(macro.get('physical_cell'),'sram.physical_cell');need(macro.get('source'),'sram.source')
    if need(macro.get('area_per_instance_um2'),'sram.area_per_instance_um2') and macro['area_per_instance_um2']<=0:errors.append('macro area must be positive')
    pins=macro.get('pin_map',{})
    for pin in ['clk','en','we','addr','wdata','rdata']:need(pins.get(pin),'sram.pin_map.'+pin)
    for pin,value in pins.items():
        if not isinstance(value,dict) or not value.get('physical_pin') or not value.get('polarity'):errors.append('pin mapping needs physical_pin and documented polarity: '+pin)
    models=macro.get('behavior_models',[]);need(models,'sram.behavior_models')
    for i,value in enumerate(models):file(value,f'sram.behavior_models[{i}]')
    corners=cfg.get('corners',[]);need(corners,'corners')
    for i,corner in enumerate(corners):
        prefix=f'corners[{i}]'
        for key in ['name','process','voltage_v','temperature_c','time_unit','capacitance_unit','source']:need(corner.get(key),prefix+'.'+key)
        for key in ['standard_cell_liberty','sram_liberty']:
            libs=corner.get(key,[]);need(libs,prefix+'.'+key)
            for j,value in enumerate(libs):file(value,f'{prefix}.{key}[{j}]')
    clock=cfg.get('clock',{})
    if clock.get('port')!='clk' or abs(clock.get('period_ns',0)-6.666667)>1e-6:errors.append('clock must be clk at target 6.666667 ns')
    for key in ['uncertainty_ns','source']:need(clock.get(key),'clock.'+key)
    io=cfg.get('io',{});need(io.get('source'),'io.source');need(io.get('reset_constraints'),'io.reset_constraints')
    inputs=io.get('input_delay_ns',{});outputs=io.get('output_delay_ns',{})
    for name,direction in ports().items():
        if name in ['clk','rst_n']:continue
        delays=inputs if direction=='input' else outputs
        if name not in delays:missing.append(f'io.{direction}_delay_ns.{name}')
        elif not isinstance(delays[name],(int,float)) or delays[name]<=0:errors.append('I/O delay must be positive and sourced: '+name)
    for exception in cfg.get('exceptions',[]):
        if not exception.get('source') or not exception.get('reason'):errors.append('Timing exception requires source and reason')
        if exception.get('scope') in ['all','clock_domain']:errors.append('Whole-domain false paths prohibited')
    sdc=file(cfg.get('constraints_sdc'),'constraints_sdc')
    if sdc:
        text=sdc.read_text()
        if not re.search(r'create_clock.*6\.66666',text):errors.append('SDC lacks 150 MHz clock')
        for command in ['set_input_delay','set_output_delay','set_clock_uncertainty']:
            if command not in text:errors.append('SDC missing '+command)
        if re.search(r'set_false_path.*\[(?:all_inputs|all_outputs|all_clocks)',text):errors.append('SDC broad false-path exception rejected')
    # Frozen source drift must be rejected even with a complete target document.
    base=ROOT/'testdata/rtl_v2/release/source_manifest.json'
    if not base.exists():base=ROOT/'bindings/hardware_sources.json'
    if not base.exists():errors.append('frozen hardware source binding missing')
    else:
        for name,digest in json.loads(base.read_text()).items():
            path=ROOT/name.replace('\\','/')
            if not path.is_file() or sha(path)!=digest:errors.append('source drift: '+name)
    result=dict(target=cfg.get('target'),preflight_passed=not(errors or missing),missing=missing,errors=errors,ports=ports(),physical_signoff=False,scope='configuration/source/constraint screening only; library semantics and STA still require designated EDA and review')
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--config',type=Path,required=True);ap.add_argument('--output',type=Path);a=ap.parse_args();r=check(a.config.resolve());text=json.dumps(r,indent=2)
    if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text)
    print(text);raise SystemExit(0 if r['preflight_passed'] else 2)
