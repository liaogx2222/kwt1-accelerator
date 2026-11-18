"""Check new/partial/mutated staging; no actual server process launched."""
import argparse
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);a=ap.parse_args()
    out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    source=ROOT/'deliverables/soc_parallel_cold_power_20261112_v3'
    loader=(source/'PASTE_INSTALL.py').read_text();assert max(len(line.encode()) for line in loader.splitlines())<=1000;results={}
    for case in ['fresh','partial_valid','modified_stage']:
        root=out/case;root.mkdir();(root/'flow').mkdir()
        (root/'flow/tb_soc_metrics.sv').write_text('$toggle_report(saif_filename,')
        stage=root/'review_tools/early_cold_loader_v1'
        if case!='fresh':
            stage.mkdir(parents=True)
            name='patch_soc_saif_string.py'
            (stage/name).write_bytes((source/name).read_text().encode() if case=='partial_valid' else b'changed')
        code=loader.replace('/path/to/project/kwt_soc_input16_metrics_595724b_tt_20261112',root.as_posix())
        calls=[]
        with patch('subprocess.check_call',side_effect=lambda command:calls.append(command)):
            try:exec(compile(code,'tested_loader','exec'),{});success=True
            except AssertionError:success=False
        assert success==(case!='modified_stage'),case
        if success:
            assert len(calls)==1 and calls[0][-1].endswith('start_soc_early_cold_power.py')
            for name in ['patch_soc_saif_string.py','start_soc_early_cold_power.py','soc_saif_patch_spec.json']:
                assert (stage/name).read_bytes()==(source/name).read_text().encode()
        else:assert not calls
        results[case]=dict(passed=True,install_success=success,process_launches_mocked=len(calls))
    (out/'summary.json').write_text(json.dumps(dict(passed=True,actual_server_execution=False,cases=results),indent=2)+'\n')
    print('RESUME_LOADER_MOCK_PASS',len(results))


if __name__=='__main__':main()
