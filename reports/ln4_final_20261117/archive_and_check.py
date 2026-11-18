"""Record the screenshot-derived legacy reference and validate report contents."""
from pathlib import Path
import hashlib,json,shutil
from decimal import Decimal
from docx import Document
from pypdf import PdfReader
B=Path(__file__).resolve().parent
repo=B.parents[1]
e=repo/'docs/architecture/evidence/legacy_soc_metrics_20261113'
e.mkdir(parents=True,exist_ok=True)
src=Path('C:/Users/123/AppData/Local/Temp/codex-clipboard-22d0a079-2643-4115-b983-d23281c8cb73.png')
image_sha='33c4fd1b9e35598210a0dbef8cb760f4364a666f413a074cd0d90f7e5232316e'
if src.exists():
    assert hashlib.sha256(src.read_bytes()).hexdigest()==image_sha
    shutil.copy2(src,e/'server_collector_screenshot.png')
legacy=dict(source='user screenshot of server collector, not a downloaded raw report',
    screenshot_sha256=image_sha,project='kwt_soc_input16_metrics_595724b_tt_20261112',
    compute_revision='595724b88858b142a407f6a5c4761945252d523b',
    interface='before System Bus route correction; reference only',
    corner='TT',voltage_V=1.1,temperature_C=25,frequency_Hz_assumed=150000000,
    cycles=2407596,throughput_task_per_s_conditional=150e6/2407596,
    latency_ms_conditional=2407596/150e3,saif_duration_s=.01605063839,
    saif_cycle_window_matches=True,dynamic_mW=73.4,leakage_mW=.4917,
    total_power_mW=73.8917,energy_uJ=1186.0089567223629,
    area_mm2=dict(accelerator=1.41558102012,CPU_TCM=.573203433696,
      shared_macros=1.76110824998,added_shared_controller=.0020463912,
      added_interface_glue=.0022596168),
    whole_area_mm2=3.754198711796,added_ledger_subtotal_mm2=1.41988702812,
    caveats=['new route PPA unavailable','one cold case plus reset recovery, not twelve-task gate campaign',
       '150MHz not fully signed off','activity coverage and SRAM power still require review',
       'area added/reused classification needs review','no post-layout parasitics'])
(e/'screenshot_transcription.json').write_text(json.dumps(legacy,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
area_dir=repo/'docs/architecture/evidence/sysbus_r3_area_20261113'
area_dir.mkdir(parents=True,exist_ok=True)
area_sources={
    'area_and_ledger.png':'codex-clipboard-879da9ac-f34c-4195-8cc9-62ed93f27f3c.png',
    'project_and_route.png':'codex-clipboard-bcd1fb57-5ecf-4629-b648-854bebb1ef88.png'}
source_hashes={}
for dst,srcname in area_sources.items():
    original=Path('C:/Users/123/AppData/Local/Temp')/srcname
    if original.exists():shutil.copy2(original,area_dir/dst)
    source_hashes[dst]=hashlib.sha256((area_dir/dst).read_bytes()).hexdigest()
area_um2={k:Decimal(v) for k,v in dict(accelerator='1415581.02012',CPU_TCM='566965.627296',
    shared_macros='1761108.24998',added_shared_controller='2025.0048',added_interface_glue='2753.4192').items()}
total=sum(area_um2.values())/Decimal(1000000)
subtotal=sum(area_um2[k] for k in ['accelerator','added_shared_controller','added_interface_glue'])/Decimal(1000000)
upper=total-area_um2['shared_macros']/Decimal(1000000)
assert total==Decimal('3.748433321396') and subtotal==Decimal('1.42035944412')
assert upper==Decimal('1.987325071416') and upper<Decimal('2.25')
area_evidence=dict(source='user screenshots of server reports and project completion markers; no raw report downloaded',
    server_project='/home/2026contest/server6/s6_43usr/Desktop/project/kwt_sysbus_v1_20261113_r3',
    route='original_e203_subsys_mems width=32 private_loader=0 SRAM_backend_arbiter=0',
    reused_core='cpu_cache_e203_cpu_top',actual_DC_done_marker='SOC_FULL_DC_DONE',
    area_partitions_um2={k:str(v) for k,v in area_um2.items()},
    whole_area_from_ledger_mm2=str(total),added_ledger_subtotal_mm2=str(subtotal),
    conservative_added_upper_bound_excluding_only_shared_macros_mm2=str(upper),
    margin_to_2p25_mm2=str(Decimal('2.25')-upper),
    printed_total_cell_area_um2_visible_prefix='3748433.31640',
    printed_total_cell_area_is_right_cropped=True,macro_black_box_area_um2='2751731.640625',
    screenshot_sha256=source_hashes,
    limitations=['added/reused detailed classification not finalized','not gate-function verification or STA signoff',
        'new throughput, power and energy remain unavailable','archive full raw reports and netlist hashes when accessible'])
(area_dir/'screenshot_transcription.json').write_text(json.dumps(area_evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
docx=B/'30022_uv_KWT1_作品设计报告_LN4优化版.docx';pdf=docx.with_suffix('.pdf')
d=Document(docx)
visible='\n'.join([p.text for p in d.paragraphs]+[c.text for t in d.tables for r in t.rows for c in r.cells])
for s in ['30022','uv','2,783,869','73.8917','1,186.01','1.419887','3.754199','62.3028','53.8818','1.420359','1.987325','3.748433']:
    assert s in visible,s
for s in ['周期预算已经满足','周期预算已满足','全 S8 版本保留为可回退对照','注释率应为 100%','host 口优先','PT 只能用库的 wire load','Q0.15','Q16.16 / Q8.23','尾块掩码后少 112 次','银行','修正后','自设','冒充','依据赛题正式答疑','依据正式答疑','5.5　综合缓存的复用范围']:
    assert s not in visible,s
assert 4*3328+2*13312+5824+2*13*4*99==56056
abstract='\n'.join(p.text for p in d.paragraphs[ next(i for i,p in enumerate(d.paragraphs) if p.text=='摘　要') : next(i for i,p in enumerate(d.paragraphs) if p.text.startswith('关键词：')) ])
for s in ['73.8917','62.3028','1,186.01','2,407,596','1.419887','3.754199','答疑','团队']:
    assert s not in abstract,s
assert '满足150 MHz时序要求' in abstract
compare=[t for t in d.tables if t.rows[0].cells[1].text=='参考版本']
assert len(compare)==1
area_rows={'账本新增面积小计 mm²':'1.420359','保守新增面积上界 mm²':'1.987325','完整数字 SoC 单元与宏面积 mm²':'3.748433'}
for row in compare[0].rows[1:]:
    if row.cells[0].text in area_rows:assert row.cells[2].text==area_rows[row.cells[0].text]
    elif row.cells[0].text=='150 MHz时序要求':assert row.cells[2].text=='满足'
    elif row.cells[0].text!='物理宏数量':assert row.cells[2].text=='',row.cells[0].text
r=PdfReader(pdf)
text='\n'.join(p.extract_text() or '' for p in r.pages)
assert '目录将在打开文档时自动生成' not in text
assert len(r.pages)>10 and pdf.stat().st_size<50*1024**2
for s in ['73.8917','1.419887','30022','1.420359','1.987325','3.748433']:assert s in text,s
out=dict(passed=True,pages=len(r.pages),docx_bytes=docx.stat().st_size,pdf_bytes=pdf.stat().st_size,
    team='30022 uv',old_reference_separate=True,new_server_performance_power_cells_blank=True,
    timing_150MHz_statement_source='explicit user confirmation in PDF comment 2; no raw WNS/TNS supplied',
    seven_PDF_comments_addressed=True,abstract_current_design_only=True,bank_terminology=True,
    new_server_area_populated=True,conservative_area_bound_below_2p25=True,
    old_source_screenshot_sha256=image_sha,
    docx_sha256=hashlib.sha256(docx.read_bytes()).hexdigest(),
    pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())
(B/'qa').mkdir(exist_ok=True)
(B/'qa/content_check.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
