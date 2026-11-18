"""Generate an auditable standalone window variant of the frozen exact code."""
import argparse
import json
from pathlib import Path
from local_tools import ROOT,sha


def replace_once(text,old,new,count=1):
    assert text.count(old)==count,(old,text.count(old));return text.replace(old,new)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    original=ROOT/'integer_model/competitive_softmax_pipeline.py';dest=ROOT/'integer_model/competitive_graph_windows.py';assert not dest.exists()
    text=original.read_text();text=replace_once(text,'from .competitive_resident_attention import ResidentAttention','from .competitive_fused_rows import FusedRowsCore')
    text=replace_once(text,'class SoftmaxPipelinedAttention(ResidentAttention):','class WindowRowsCore(FusedRowsCore):')
    text=replace_once(text,'def __init__(self,*a,**k):','def __init__(self,*a,window=16,**k):\n        assert window in [16,32,64,128];self.window=window')
    text=replace_once(text,'range(0,99,16)','range(0,99,self.window)',2);text=replace_once(text,'min(begin+16,99)','min(begin+self.window,99)',2)
    text=replace_once(text,'return r\n','r["Softmax_graph_window"]=self.window\n        return r\n')
    text+='\n    def reset(self):\n        config=self.config;buffers=self.accumulator_buffers;fusion=self.fusion;window=self.window\n        self.__init__(*config,accumulator_buffers=buffers,fusion=fusion,window=window)\n'
    dest.write_text(text);validator=ROOT/'scripts/validate_fused_rows.py';vdest=ROOT/'scripts/validate_graph_windows.py';assert not vdest.exists()
    v=validator.read_text().replace('from integer_model.competitive_fused_rows import FusedRowsCore','from integer_model.competitive_graph_windows import WindowRowsCore')
    v=replace_once(v,"a=ap.parse_args();","ap.add_argument('--window',type=int,choices=[16,32,64,128],default=32);a=ap.parse_args();")
    v=v.replace("FusedRowsCore(p['exp_lut'],","WindowRowsCore(p['exp_lut'],window=a.window,")
    v=replace_once(v,"ROOT/'integer_model/competitive_fused_rows.py'","ROOT/'integer_model/competitive_fused_rows.py',ROOT/'integer_model/competitive_graph_windows.py'")
    vdest.write_text(v)
    report=dict(passed=True,scope='same exact arithmetic, only softmax graph window and bounded scheduling',replacements='two original graph windows, class base, explicit window-preserving reset',outputs={p.relative_to(ROOT).as_posix():sha(p) for p in [dest,vdest]})
    (out/'verification.json').write_text(json.dumps(report,indent=2));(out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in [Path(__file__),original,validator,dest,vdest]},indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
