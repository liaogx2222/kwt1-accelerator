"""Measured/model axes kept separate; power/SoC area are deliberately null."""
import argparse
import csv
import json
from pathlib import Path
from local_tools import ROOT,sha

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);base=ROOT/'testdata/resident_core_20261105'
    def read(folder):return json.loads((base/folder/'verification.json').read_text())
    baseline=read('core_two_cold')['cases'][0];single=read('model_single_acc')['metrics'];wide=read('model_lanes8')['metrics']
    initial_map=read('nangate_structural_v2');shared_map=read('nangate_shared');single_map=read('nangate_single')
    rows=[]
    for name,m,lanes,buffers,area in [('compact',single,4,1,single_map['standard_cell_area_mm2']),('balanced',baseline,4,2,shared_map['standard_cell_area_mm2']),('faster',wide,8,2,None)]:
        rows.append(dict(candidate=name,PE_rows=16,PE_cols=16,vector_lanes=lanes,accumulator_buffers=buffers,core_model_cycles=m['cycles'],
            model_peak_register_bytes=m['total_register_peak_bytes'],private_SRAM_bytes=65536,SRAM_reads=m['SRAM_reads'],SRAM_writes=m['SRAM_writes'],
            mapped_arithmetic_partition_area_mm2=area,full_SoC_area_mm2=None,power_mW=None,energy_uJ=None,
            model_state_is_lifetime_peak_not_complete_RTL_register_count=True,precision_profile='same S16-input/W8/S8 internal, RNE/LUT formulas unchanged'))
    def frontier(data,x,y):
        return [r['candidate'] for r in data if not any(s[x]<=r[x] and s[y]<=r[y] and (s[x]<r[x] or s[y]<r[y]) for s in data)]
    report=dict(passed=True,accuracy_hard_limit_drop_pp=0.1,other_metrics='tradeoff; user figures are reference examples, not all mandatory thresholds',
        candidates=rows,model_cycle_state_frontier=frontier(rows,'core_model_cycles','model_peak_register_bytes'),
        model_cycle_partition_area_frontier=frontier([r for r in rows if r['mapped_arithmetic_partition_area_mm2'] is not None],'core_model_cycles','mapped_arithmetic_partition_area_mm2'),
        structural_to_shared_partition_area_reduction_percent=100*(1-shared_map['standard_cell_area_mm2']/initial_map['standard_cell_area_mm2']),
        single_vs_shared_partition_area_reduction_percent=100*(1-single_map['standard_cell_area_mm2']/shared_map['standard_cell_area_mm2']),
        single_vs_dual_cycle_increase_percent=100*(single['cycles']/baseline['cycles']-1),wide_vs_four_cycle_reduction_percent=100*(1-wide['cycles']/baseline['cycles']),
        energy_frontier_measured=False,scope='cycle axes are same-profile full-core MODEL; physical area is MAC+RQ partition only, excluding SRAM/nonlinear/controller/SoC; no power inferred')
    (out/'comparison.json').write_text(json.dumps(report,indent=2))
    with (out/'comparison.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(12.5,5.2));colors=['#167d8d','#d78b24','#745ab4']
    for row,color in zip(rows,colors):
        x=row['core_model_cycles']/1e6;y=row['model_peak_register_bytes']/1024
        axes[0].scatter(x,y,s=85,color=color,zorder=3);axes[0].annotate(f"{row['vector_lanes']} lanes / {row['accumulator_buffers']} buffers",(x,y),xytext=(8,8),textcoords='offset points',fontsize=9)
        if row['mapped_arithmetic_partition_area_mm2'] is not None:
            axes[1].scatter(x,row['mapped_arithmetic_partition_area_mm2'],s=85,color=color,zorder=3)
            axes[1].annotate(row['candidate'],(x,row['mapped_arithmetic_partition_area_mm2']),xytext=(7,7),textcoords='offset points',fontsize=9)
    axes[0].set(xlabel='Core MODEL cycles (million)',ylabel='Peak MODEL register allocation (KiB)',title='Same numerical profile; lower-left preferred')
    axes[0].set_xlim(1.78,2.40);axes[0].set_ylim(2.65,3.65)
    axes[1].scatter(baseline['cycles']/1e6,initial_map['standard_cell_area_mm2'],s=85,marker='x',color='#777777',zorder=3)
    axes[1].annotate('initial dual-buffer coding',(baseline['cycles']/1e6,initial_map['standard_cell_area_mm2']),xytext=(7,6),textcoords='offset points',fontsize=8)
    axes[1].set(xlabel='Core MODEL cycles (million)',ylabel='Nangate45 PARTITION std-cell area (mm2)',title='MAC + RQ only; 8-lane area unmeasured')
    axes[1].set_xlim(1.95,2.40);axes[1].set_ylim(.28,.48)
    for ax in axes:ax.grid(True,alpha=.2)
    fig.suptitle('Architecture alternatives: measured and model scopes remain separate',fontsize=12)
    fig.text(.5,.015,'No full-SoC / SRAM area or power measurement. Model register lifetimes are not a synthesized register-budget signoff.',ha='center',fontsize=8,color='#555555')
    fig.tight_layout(rect=(0,.06,1,.93));fig.savefig(out/'tradeoffs.png',dpi=160);fig.savefig(out/'tradeoffs.svg');plt.close(fig)
    sources=[Path(__file__),ROOT.parent/'docs/architecture/DESIGN_TRADEOFF_POLICY_20261105.json']+[base/n/'verification.json' for n in ['core_two_cold','model_single_acc','model_lanes8','nangate_structural_v2','nangate_shared','nangate_single']]
    import os
    (out/'source_bindings.json').write_text(json.dumps({os.path.relpath(p,ROOT).replace('\\','/'):sha(p) for p in sources},indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
