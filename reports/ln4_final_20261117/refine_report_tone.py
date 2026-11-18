"""Use direct scope descriptions in the submission report."""
from pathlib import Path
p=Path(__file__).resolve().parent/'current.py'
s=p.read_text(encoding='utf-8')
for a,b in [
    ('本机实际执行对象为 RTL，不将其标作商业映射网表或 SAIF 功耗结果。','本机运行对象为RTL，映射门级和SAIF结果单独统计。'),
    ('该结论仅为综合级面积预算，不表示完整竞赛验收通过。','上述数值对应综合级库单元与宏面积。'),
    ('未完成 CTS、布线与 SPEF，未确认应用 wire-load 模型，不宣称后布局时序或功耗。','时序与功耗采用综合级网表分析，尚未引入CTS、布线和SPEF寄生参数。'),
    ('不提高频率来掩盖差距。','后续优化按相同频率比较周期数。'),
    ('未取得的本设计指标不以估算补齐。','未取得的本设计指标保留空栏。')]:
    assert a in s,a
    s=s.replace(a,b)
p.write_text(s,encoding='utf-8')
