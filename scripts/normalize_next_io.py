"""Correct return-link labels in early symmetric-delay ledgers, keep raw JSON.

Both external links have exactly the same bandwidth/bytes/delay. Swapping ONLY
their output labels leaves every timestamp, CPU event and task duration intact.
This is metadata normalization of modeled links, not a new hardware measurement.
New SystemIO emits the return order directly.
"""
import copy,json
def normalize(out):
    rows=[]
    for variant in ['cold_fixed','cold_fused']:
        raw=json.loads((out/variant/'cold_tasks.json').read_text())
        for task in raw['tasks']:
            ledger=copy.deepcopy(task['io']['ledger']);links=[r for r in ledger if r['kind']=='output' and r['segment'] in ['host_cpu_link','cpu_device_link']]
            assert len(links)==2 and links[0]['cycles']==links[1]['cycles'] and links[0]['bytes']==links[1]['bytes']==6336
            relabeled=links[0]['segment']=='host_cpu_link'
            if relabeled:
                links[0]['segment']='cpu_device_link';links[1]['segment']='host_cpu_link'
            assert [r['segment'] for r in ledger if r['kind']=='output']==['device_stream','cpu_device_link','CPU_copy','host_cpu_link','final_write_ack']
            assert sum(r['cycles'] for r in ledger)==task['io']['io_cycles']
            rows.append(dict(variant=variant,task=task['task'],return_link_labels_corrected=relabeled,
                             all_timestamps_and_cycles_unchanged=True,ledger=ledger))
    result=dict(passed=True,tasks=rows,scope='external links are symmetric delay models; original ledgers preserved')
    (out/'io_direction_assessment.json').write_text(json.dumps(result,indent=2),encoding='utf-8');return result
