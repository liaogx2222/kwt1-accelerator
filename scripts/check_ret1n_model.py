"""Compile/run the explicit RET1N wrapper/model contract; vendor test remains separate."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import run_soc_joint as runner

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    out = a.output.resolve()
    if out.exists():
        raise ValueError('fresh output required')
    out.mkdir(parents=True)
    tb = (ROOT/'flow/smic40/tb_sram_contract.sv').read_text()
    tb = tb.replace('module tb_sram_contract;', 'module tb_soc_joint;')
    tb = tb.replace('    integer errors = 0;', '''    reg bad_cen=1;
    wire [15:0] bad_q;
    initial if ($test$plusargs("BAD_RET1N")) bad_cen=0;
    RAMSP4096X16 invalid_mode_probe(.Q(bad_q),.CLK(clk),.CEN(bad_cen),
      .WEN(16'hffff),.A(12'd0),.D(16'd0),.EMA(3'b010),.EMAW(2'b00),
      .GWEN(1'b1),.RET1N(1'b0));
    integer errors = 0;''')
    bench = out/'tb_ret1n.sv'
    bench.write_text(tb)
    sources = [ROOT/'rtl/integration/smic40/kwt_tech_sram_4096x16.sv',
               ROOT/'flow/review/ramsp4096x16_ret1n.v', bench]
    runner.sources = lambda: sources
    exe = runner.build(out)
    p = subprocess.run([str(exe)], cwd=out, capture_output=True, text=True)
    (out/'normal.log').write_text(p.stdout+p.stderr)
    assert p.returncode == 0 and 'PASS KWT_SRAM_CONTRACT checks=5' in p.stdout, p.stdout+p.stderr
    zero = subprocess.run([str(exe), '+KWT_SRAM_INIT_ZERO'], cwd=out, capture_output=True, text=True)
    (out/'zero_init.log').write_text(zero.stdout+zero.stderr)
    assert zero.returncode == 0 and 'PASS KWT_SRAM_CONTRACT checks=5' in zero.stdout
    n = subprocess.run([str(exe), '+BAD_RET1N'], cwd=out, capture_output=True, text=True)
    (out/'bad_ret1n.log').write_text(n.stdout+n.stderr)
    assert n.returncode != 0 and 'KWT_SRAM_RET1N_NORMAL_MODE_REQUIRED' in n.stdout+n.stderr
    result = dict(passed=True, normal_access_contract_checks=5, low_RET1N_rejected=True,
                  zero_initialization_contract_checks=5, four_state_X_behavior_executed=False,
                  actual_RET1N_port_binding_compiled=True, vendor_macro_executed=False,
                  formal_retention_low_mode_supported=False,
                  source_sha256={str(s): hashlib.sha256(s.read_bytes()).hexdigest() for s in sources})
    (out/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'source_sha256'}, indent=2))


if __name__ == '__main__':
    main()
