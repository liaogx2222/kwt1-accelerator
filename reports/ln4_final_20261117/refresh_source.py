"""One-time migration of copied report sources; original report stays untouched."""
from pathlib import Path
import ast
B=Path(__file__).resolve().parent
def edit(n,pairs):
    p=B/n;s=p.read_text(encoding='utf-8')
    for a,b in pairs:
        assert a in s,(n,a[:65])
        s=s.replace(a,b)
    p.write_text(s,encoding='utf-8')
def retain(n,names):
    p=B/n;s=p.read_text(encoding='utf-8');lines=s.splitlines(keepends=True)
    for x in reversed(ast.parse(s).body):
        if isinstance(x,ast.FunctionDef) and x.name not in names:del lines[x.lineno-1:x.end_lineno]
    p.write_text(''.join(lines),encoding='utf-8')
retain('part1.py',{'cover','toc','ch1','ch2','ch3'})
retain('part2.py',{'ch4'})
retain('part4.py',{'appendix'})
(B/'part3.py').unlink()
edit('facts.py',[
 ('REV = "595724b"','REV = "SYSBUS v1 r3（计算595724b）"'),
 ('BRANCH = "codex/arch60-input16-20261112"','BRANCH = "codex/soc-joint-20261111"'),
 ('CYC_TASK = 2407590','CYC_TASK = 2783869'),
 ('# ---- SoC 统计（第一类） ----','# ---- 历史旧接口统计，禁止作为新总线实测使用 ----')])
edit('part1.py',[
 ('("队伍编号（必填）：", "")','("队伍编号（必填）：", "30022")'),
 ('("参赛队名（必填）：", "")','("参赛队名（必填）：", "uv")'),
 ('r = p.add_run("作 品 设 计 报 告")','p.style = "Title"\n    r = p.add_run("作品设计报告")'),
 ('"——面向端侧离线语音指令识别——"','"修正后 System Bus 集成与修正前参考结果"'),
 ('"周期预算已满足"','"尚未达到60任务/s"'),
 ('["加速器面积（含 20 宏）", "—", "≤ 2.25 mm²", "待服务器"]','["新增面积（全部新增逻辑与私有宏）", "", "≤2.25 mm²", "待服务器；旧版另列"]'),
 ('["150 MHz setup / hold", "—", "无负裕量", "待服务器"]','["150 MHz时序", "", "有效约束下满足", "待服务器"]'),
 ('["平均功耗 / 单任务能耗", "—", "—", "待服务器"]','["平均功耗 / 单任务能耗", "", "同配置同窗口", "待服务器；旧版另列"]'),
 ('"以及参赛队实现的 AI Engine。本设计的边界是：复用 E203 与固定总线，不修改 CPU 核；"','"以及参赛队实现的 AI Engine。复用 E203 运算核心与原总线译码，配置 NICE 并修改外层接入；"'),
 ('"共享 SRAM 控制器（kwt_soc_shared_sram）、NICE 块搬运控制器与仲裁器、以及 504 B 的固定启动 ROM。"','"共享 SRAM 控制器、NICE 块搬运、原总线入口三主仲裁器，以及504 B固定启动ROM。"'),
 ('"提供驱动、调度、NICE 指令提交；不改核"','"CPU核心复用，配置NICE与外层接线"'),
 ('"新增控制器 IP，64 个 16 bit 宏拼接，含 host 装载口"','"64个16 bit宏；仅原System Bus从口，无直写旁路"'),
 ('"SoC 顶层实例化 E203 子系统与加速器通路，二者通过 ICB 总线连接。CPU 的 sysmem 出口经一级地址译码后，"','"CPU、NICE与供包ICB请求统一进入原System Bus入口，再由原平台地址译码，"'),
 ('"把 0x1100_0000 起的访问送到加速器桥，把 0xA000_0000 起的访问送到共享 SRAM 控制器；"','"把0x1100_0000访问经SysPer送至加速器桥，把0xA000_0000访问经原sysmem送至共享SRAM；"'),
 ('"SoC 顶层与数据通路：CPU、NICE 块搬运、共享 SRAM 与加速器的连接关系"','"修正后接入原System Bus的供包 块读取与结果写回通路"'),
 ('["写回", "读共享 SRAM 输出到 DTCM/比较器", "结果写入共享 SRAM 0xa002_2000"]','["写回", "提交输出块指令并等待完成", "经原总线写入共享SRAM；台架比较，不代算"]'),
 ('"这一改动把 SoC 任务窗口从 9,735,884 拍降到 3,078,420 拍（−68.4%），"\n        "而加速器内部的计算拍数完全不变——它消除的是 CPU 逐字搬运的开销，不是计算量。"','"历史块搬运方案减少CPU逐字事务，但原尾端接入不能作为当前路径。新System Bus RTL完整窗口为2,783,869拍，历史局部收益不与新版混计。"'),
 ('"表项由标定集分段拟合"','"按冻结整数模型逐码生成"'),
 ('"RNE 舍入，总和归一到 1"','"冻结整数尺度归一与RNE"'),
 ('"不采用（精度余量更小）"','"不采用；不满足自设0.1 pp"'),
 ('"任务拍数增加 15,773 拍（+0.66%）。这一取舍在 60 任务/s 的周期预算内仍然成立，因此作为最终交付配置；"\n        "全 S8 版本保留为可回退对照。"','"历史旧接口实验增加15,773拍（+0.66%），不能移作新总线的单因素结果。S16为本轮冻结配置；全S8不满足0.1 pp，不能作为合格回退。官方600样本和统一性能任务到位后须复验。"'),
 ('color=ACCENT)','color=RGBColor(0, 0, 0))'),('color=GREY)','color=RGBColor(0, 0, 0))')])
edit('part2.py',[
 ('"每 64 字为一行；两个 token 拼一字，因此 16 个 token 只需 8 个银行各 64 字。"\n        "这样一拍读 8 个银行就能取到 16 个 token 的同一通道，"\n        "正好喂满 8×16 阵列的行方向；写回时两个 token 的结果也天然拼成一字，不需要额外的打包缓冲。"','"打包用于压缩激活存储；调度器按token与通道选取所需半字。阵列有8个查询行、16个输出列，写回按布局拼字，不把16个打包token误当成16个阵列行。"'),
 ('["FC1", "104×64×256", "13,312", "K=256，权重占 1,024 起"]','["FC1", "104×256×64", "13,312", "N=256、K=64；权重基址1024"]'),
 ('["FC2", "104×256×64", "13,312", "N=256，16 个列块"]','["FC2", "104×64×256", "13,312", "N=64、K=256；4个输出列块"]'),
 ('"实测每任务 11 个预取帧、291,720 个与计算重叠的装载写拍、143,842 个仲裁停顿拍。"','"计算母版曾记录11个预取帧、291,720个重叠写拍和143,842个停顿拍。这是历史旧接口观察值，不当作新System Bus的分阶段实测。"'),
 ('"直接写回前后的调度对比"','"历史计算窗口的直接写回对比"'),
 ('"声明状态超出 4 KiB 的 30 B 来自四路 tag、预取槽位与 NICE 结果寄存器。"','"该状态口径为冻结加速器与块通路，不含新增总线仲裁器及CPU整机。4,126 B比内部4 KiB预算多30 B；全SoC资源另按映射账本记入。"')])
edit('part4.py',[
 ('["0xa008_0000 起", "栈（预留 16 KiB）", "—", "高水位远小于预留"]','["0x9000_0000 起", "DTCM", "64 KiB", "平台TCM；不属于共享区，不供DMA绕行"]'),
 ('"99×64 INT8，CPU 经 NICE 读出"','"99×64 INT8；NICE经原System Bus写回"'),
 ('"CPU 与 host 的同步点"','"CPU与供包主设备经原总线同步"')])
edit('docx_kit.py',[
 ('color="8EA9C1"','color="D9D9D9"'),
 ('h.font.color.rgb = ACCENT','h.font.color.rgb = RGBColor(0, 0, 0)'),
 ('bold=True, color=ACCENT)','bold=True, color=RGBColor(0, 0, 0))'),
 ('8.5, color=GREY)','8.5, color=RGBColor(0, 0, 0))'),
 ("        self._rule(par, '1F3B63', 8)\n",''),
 ('        t = self.doc.add_table(rows=1, cols=1)\n','        return self.p(text, indent=False, size=size)\n        t = self.doc.add_table(rows=1, cols=1)\n'),
 ('            if ri < len(t.rows) - 1:','            if ri == 0:'),
 ('                c.text = ""\n                if row_fills','                c.text = ""\n                from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT\n                c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER\n                if row_fills')])
edit('build.py',[
 ('import part3','import current'),
 ('"KWT1_作品设计报告_2026_最新RTL.docx"','"30022_uv_KWT1_作品设计报告_SystemBus修正版.docx"'),
 ('part1.abstract(R)','current.abstract(R)'),
 ('part2.ch5(R)','current.ch5(R)'),('part2.ch6(R)','current.ch6(R)'),
 ('part3.ch7(R)','current.ch7(R)'),('part3.ch8(R)','current.ch8(R)'),('part3.ch9(R)','current.ch9(R)'),
 ('part4.ch10(R)','current.ch10(R)'),('part4.ch11(R)','current.ch11(R)'),('part4.ch12(R)','current.ch12(R)')])
print('REPORT_SOURCE_REFRESHED')
