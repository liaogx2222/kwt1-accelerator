"""Run the existing full-SoC campaign with explicit RET1N macro contract models.

This is binary logic simulation, not vendor-macro or mapped timing validation.
"""
import argparse
import json
from pathlib import Path
import sys
import run_soc_joint as runner


if __name__ == '__main__':
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--model', type=Path)
    a, _ = ap.parse_known_args()
    if '--unit' in sys.argv:
        raise ValueError('full subsystem only')
    if '--native' not in sys.argv:
        sys.argv.append('--native')
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    header = out/'enable_ret1n_technology.vh'
    header.write_text('`define KWT_TECH_SRAM\n')
    original = runner.sources()
    wrapper = runner.ROOT/'rtl/integration/smic40/kwt_tech_sram_4096x16.sv'
    model = runner.ROOT/'flow/review/ramsp4096x16_ret1n.v'
    if a.model:
        bound = json.loads((a.model.resolve().parent/'sources.json').read_text())
        if str(wrapper) not in bound or str(model) not in bound:
            raise ValueError('expected a model compiled with the RET1N technology contract')
    runner.sources = lambda: [header]+original+[wrapper, model]
    runner.main()
