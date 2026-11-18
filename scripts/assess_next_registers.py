"""Add always-present physical iterative registers, preserving raw lifetimes."""
import json
from pathlib import Path
from integer_model.pipeline_contract import PIPELINE_STORAGE_BYTES,ITERATIVE_STORAGE_BYTES
from integer_model.register_contract import static_layout
def assess(out):
    fixed=static_layout()['bytes']+PIPELINE_STORAGE_BYTES+ITERATIVE_STORAGE_BYTES;rows=[]
    for folder in sorted((out/'fused').glob('*_*')):
        if not (folder/'summary.json').exists():continue
        source=json.loads((folder/'summary.json').read_text());dynamic=source['liveness']['peak_bytes']
        rows.append(dict(case=str(folder.relative_to(out)),dynamic=dynamic,physical_and_control=fixed,total=dynamic+fixed,passed=dynamic+fixed<=4096))
    for folder in ['cold_fixed','cold_fused']:
        document=json.loads((out/folder/'cold_tasks.json').read_text())
        for task in document['tasks']:
            for layer in task['layers']:
                reg=layer['register_budget'];dynamic=reg.get('data_peak',reg.get('data_and_inflight_peak_bytes'))
                # Both variants connect the same physical arithmetic pools;
                # conservative double counting of live result/operand intervals.
                rows.append(dict(case=f'{folder}/task_{task["task"]}/layer_{layer["layer"]}',dynamic=dynamic,physical_and_control=fixed,total=dynamic+fixed,passed=dynamic+fixed<=4096))
    # Old whole-layer coefficient cache peaked3588B; plus all physical pools
    # would exceed4KiB. It remains a timing/numeric control, not proposed RTL cap.
    result=dict(fused_passed=all(r['passed'] for r in rows if not r['case'].startswith('cold_fixed')),
                control_bytes=static_layout()['bytes'],RQ_pool_bytes=PIPELINE_STORAGE_BYTES,iterative_pool_bytes=ITERATIVE_STORAGE_BYTES,
                static_total=fixed,rows=rows,raw_lifetimes_unchanged=True,
                note='physical pools always reserved; live in-flight values additionally counted; old cache control may exceed 4KiB')
    (out/'register_assessment.json').write_text(json.dumps(result,indent=2),encoding='utf-8');return result
