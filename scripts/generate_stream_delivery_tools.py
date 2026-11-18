"""Construct reviewable static campaign tools from the accepted score4 harness."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PARENT='5b3deec31c8e34d8e1484ae794fb1912ce4c8986';REV='d8fe71081eb893b3c8394dc1d9c3a0ea1aa129ff'
def change(s,old,new):
    assert old in s,old;return s.replace(old,new)
def write(name,s):
    p=ROOT/'scripts'/name;assert not p.exists();p.write_text(s)
if __name__=='__main__':
    s=(ROOT/'scripts/validate_score4_round.py').read_text()
    for old,new in [
        ("PARENT='9476619b7c85d8b5806744478a3419d8e5965015'",'PARENT='+repr(PARENT)),
        ("REV='4a163f7abe5043e4cfb269f7a8d71d12291e7535'",'REV='+repr(REV)),
        ("RESETS=[('store_reset',15),('tail_reset',16),('read_reset',17)]","RESETS=[('max_capture_reset',18),('stream_tail_reset',19),('alias_reset',20)]"),
        ('prepare_score4.py','prepare_softmax_stream.py'),('targeted_v2','targeted'),("'--stall-kind','score'","'--stall-kind','stream'"),
        ('calculate_score4_ceiling.py','calculate_stream_ceiling.py'),('ceiling_v2','ceiling'),
        ('evidence/dense_overlap_20261115/candidate/cold0_gap4/summary.json','evidence/score4_20261115/candidate/cold0/summary.json'),
        ('rtl/score4_opt/','rtl/softmax_stream/'),('Score_stalls','Stream_stalls'),
        ('PASS LOCAL_SCORE_STALL mac_cycles=17 held_requant_cycles=11','PASS LOCAL_STREAM_STALL score_exp_cycles=17 alias_result_cycles=11'),
        ('profile[3]==(1865760 if baseline else 1762432 if stall else 1762404)','profile[3]==(1762404 if baseline else 1644820 if stall else 1644792)'),
        ('[2294607,1865760,7615408,1239000]','[2281457,1762404,7615408,1239000]'),
        ('[2281457,1762404,7615408,1239000]\n    phase=', '[2271587,1644792,7615408,1239000]\n    phase='),
        ('delta=={18:-103356}','delta=={70:-117612}'),("bound['necessary_serial_cycles']==1377888","bound['necessary_serial_cycles']==1260276"),
        ("bound['iterative_SHA256']","bound['base_iterative_SHA256']"),('codex/score4-opt-20261115','codex/softmax-stream-20261115'),
        ('task_cycles_saved=13150,latency_reduction_percent=100*13150/2294607,compute_cycles_saved=103356','task_cycles_saved=9870,latency_reduction_percent=100*9870/2281457,compute_cycles_saved=117612'),
        ('noncompute_wait_added=90206','noncompute_wait_added=107742'),('shared_case0_read_write_change=[3508,0]','shared_case0_read_write_change=[3994,0]'),
        ('parent_tasks_s=150000000/2294607,candidate_tasks_s=150000000/2281457,goal120_achieved=False','parent_tasks_s=150000000/2281457,candidate_tasks_s=150000000/2271587,goal100_achieved=False'),
        ('necessary_serial_cycles=1377888','necessary_serial_cycles=1260276'),('150000000/1377888','150000000/1260276'),
        ('point=0,crc=False,stall=False,baseline=False):','point=0,crc=False,stall=False,baseline=False,gap=4):'),
        ("and '+HOST_GAP=4' in cmd","and ('+HOST_GAP='+str(gap)) in cmd"),('[4,192496,1584,2]','[gap,192496,1584,2]'),
        ('PASS SCORE4 RELEASE COLLECTION','PASS STREAM RELEASE COLLECTION')]:s=change(s,old,new)
    s=change(s,"    for name,point in RESETS:run('check_pv16_soc.py','--project',p,'--model',exe,'--output',out/name,'--host-gap','4','--recovery','--reset-point',point)","""    for name,point in RESETS:run('check_pv16_soc.py','--project',p,'--model',exe,'--output',out/name,'--host-gap','4','--recovery','--reset-point',point)
    run('check_stream_max.py','--output',out/'max_unit')
    run('check_pv16_consumers.py','--project',out/'candidate/project','--output',out/'consumers')
    for label,proj,model in [('parent','baseline/project','baseline/cold0/model/sim.exe'),('stream','candidate/project','candidate/cold0/model/sim.exe')]:
        run('check_pv16_soc.py','--project',out/proj,'--model',out/model,'--output',out/('profiles/gap0_'+label),'--host-gap','0','--cases','0','--jobs','1')""")
    s=change(s,'    for name,point in RESETS:soc(name,point=point)',"""    for name,point in RESETS:soc(name,point=point)
    fastb=soc('profiles/gap0_parent',baseline=True,gap=0);fastc=soc('profiles/gap0_stream',gap=0)
    unit=read(out/'max_unit/summary.json');assert unit['passed'] and unit['four_state'] and unit['source_SHA256']==cm['files'][CORE] and unit['integer_max_vectors']==8354 and unit['unknown_old_first_tests']==2
    assert all(sha(out/'max_unit'/n)==h for n,h in unit['files'].items())
    consumers=read(out/'consumers/summary.json');assert consumers['passed'] and consumers['four_state'] and consumers['math_results']==4152 and consumers['iterative_vectors']==821
    for filename,h in consumers['source_sha256'].items():
        p=Path(filename);assert sha(p)==h
        if p.name!='tb_consumers.sv':assert cm['files'][p.relative_to(cp).as_posix()]==h""")
    s=change(s,'        evidence=evidence,full_network_cold_classes=12',"        separate_gap0_profile=dict(parent=fastb['cases'][0],candidate=fastc['cases'][0],same_original_interface=True,only_one_class=True,counts_not_mixed_with_default_gain=True),\n        evidence=evidence,full_network_cold_classes=12")
    s=change(s,'compiler_versions=compiler,area_mm2=None', 'max_unit_four_state=unit,actual_math_iter_unit_four_state=consumers,target_tasks_s=100,compiler_versions=compiler,area_mm2=None')
    write('validate_softmax_stream.py',s)
    s=(ROOT/'scripts/export_score4.py').read_text()
    for old,new in [('9476619b7c85d8b5806744478a3419d8e5965015',PARENT),('4a163f7abe5043e4cfb269f7a8d71d12291e7535',REV),
                    ('rtl/score4_opt/','rtl/softmax_stream/'),('rtl/dense_overlap/','rtl/score4_opt/'),('score4_rtl_only','softmax_stream_rtl_only'),('SCORE4 RTL ARCHIVE','STREAM RTL ARCHIVE')]:s=change(s,old,new)
    write('export_softmax_stream.py',s)
    s=(ROOT/'scripts/freeze_score4.py').read_text()
    s=change(s,"['inventory','ceiling_v2']","['inventory','ceiling','max_unit','consumers']")
    s=change(s,"p.suffix=='.log'","p.suffix in ['.log','.hex','.txt','.sv']")
    start=s.index("    for n in ['case_00/run.log'");end=s.index("    for n in ['manifest.json'",start);s=s[:start]+s[end:]
    s=change(s,'deliverables/score4_20261115','deliverables/softmax_stream_20261115')
    write('freeze_softmax_stream.py',s)
