# -*- coding: utf-8 -*-
"""报告第一部分：封面、摘要、目录、第 1—3 章。"""
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx_kit import (Report, _set_run_font, HEI, SONG, KAI, MONO, ACCENT, GREY)
import facts as F


def cover(R: Report):
    d = R.doc
    R.spacer(30)
    for _ in range(2):
        R.spacer(10)
    p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("2026 年全国大学生嵌入式芯片与系统设计竞赛")
    _set_run_font(r, HEI, HEI, 15, bold=True, color=RGBColor(0, 0, 0))
    p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("芯片设计赛道")
    _set_run_font(r, HEI, HEI, 15, bold=True, color=RGBColor(0, 0, 0))
    R.spacer(26)
    p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.style = "Title"
    r = p.add_run("作品设计报告")
    _set_run_font(r, HEI, HEI, 34, bold=True, color=RGBColor(0, 0, 0))
    R.spacer(10)
    p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("KWT-1 十二层 Transformer 编码器整数推理加速器")
    _set_run_font(r, HEI, HEI, 15, bold=False, color=RGBColor(0, 0, 0))
    p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("System Bus SoC 集成与整数推理")
    _set_run_font(r, KAI, KAI, 12, color=RGBColor(0, 0, 0))
    R.spacer(60)

    items = [("作品名称（必填）：", "KWT-1 十二层 Transformer 编码器整数推理加速器"),
             ("队伍编号（必填）：", "30022"),
             ("参赛队名（必填）：", "uv")]
    t = d.add_table(rows=len(items), cols=2)
    t.autofit = False
    for i, (k, v) in enumerate(items):
        t.rows[i].cells[0].width = Cm(4.2)
        t.rows[i].cells[1].width = Cm(11.2)
        c0 = t.rows[i].cells[0]; c0.text = ""
        p0 = c0.paragraphs[0]; p0.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r0 = p0.add_run(k)
        _set_run_font(r0, SONG, SONG, 11.5)
        c1 = t.rows[i].cells[1]; c1.text = ""
        p1 = c1.paragraphs[0]; p1.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r1 = p1.add_run(v if v else "　")
        _set_run_font(r1, SONG, SONG, 11.5)
        pPr = p1._p.get_or_add_pPr()
        pbdr = OxmlElement('w:pBdr'); bt = OxmlElement('w:bottom')
        bt.set(qn('w:val'), 'single'); bt.set(qn('w:sz'), '6')
        bt.set(qn('w:space'), '1'); bt.set(qn('w:color'), '1F3B63')
        pbdr.append(bt); pPr.append(pbdr)
    R.spacer(40)
    p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("日期：" + F.DATE)
    _set_run_font(r, SONG, SONG, 12)




def toc(R: Report):
    R.plain_h1("目　录", new_page=True)
    R.toc()


def ch1(R: Report):
    R.h1("1　作品概述", new_page=True)
    R.h2("1.1　任务定义")
    R.p("赛题要求以 ARM 公开的 KWT-1 预训练权重为唯一模型来源，在 E203 硬件框架上完成十二层 Transformer "
        "编码器的加速器设计、SoC 集成、驱动开发与逻辑综合，并在统一评测集上给出精度、吞吐量、功耗与面积。"
        "一次“任务”定义为：完成一次十二层编码器推理，并把 99×64 的最终输出全部写回；"
        "计时从输入与参数开始装载起，到结果全部写回止，任务开始前清空任务数据与参数缓存，"
        "参数装载、总线等待与 E203 调度时间全部计入。")
    R.p("模型结构固定为：12 层、序列长度 99、特征维数 64、单头注意力（头维 64）、"
        "前馈网络 64→256→64、GELU 激活、PostNorm 结构。编码器输出经统一软件分类头得到12类结果，分类头不计入硬件任务。")

    R.h2("1.2　设计约束")
    R.table(
        ["约束项", "取值", "对设计的影响"],
        [["工艺与频率", "SMIC 40 nm，150 MHz（6.666667 ns）", "统一时序目标，决定周期预算"],
         ["面积上限", "2.25 mm²（新增部分）", "加速器+接口+私有 SRAM 宏合计；复用 CPU 与共享 SRAM 单列"],
         ["私有 SRAM", "仅限 16 bit×128/1024/4096 宏自行拼接", "决定存储组织必须按宏粒度bank划分"],
         ["系统共享 SRAM", "512 KiB，固定平台", "整模型参数 757,312 B 无法常驻，必须分层装载"],
         ["外部存储", "不增设 DDR 或外部存储控制器", "排除权重预取到片外、大缓冲等方案"],
         ["精度门槛", "相对浮点Top-1准确率下降≤2 pp", "决定定点位宽与非线性近似精度"],
         ["吞吐量口径", "任务数 / 总运行时间，含装载与调度", "装载开销必须与计算重叠"],
         ["功耗口径", "同一计时窗口的 SAIF/VCD，含 CPU/互连/SRAM", "活动信息须覆盖映射网表"]],
        widths=[3.4, 6.4, 6.4], size=9, cap="赛题硬约束与本设计的应对")

    R.h2("1.3　主要成果").paragraph_format.page_break_before = True
    R.p("表 2 汇总本设计（System Bus v1 r3，计算提交 595724b）的实测结果与达标情况。")
    R.table(
        ["指标", "本设计", "门槛 / 预算", "状态"],
        [["分类精度（验证集 4,445 样本）", "97.75%（4,345）", "相对浮点下降≤2 pp", "达标"],
         ["RTL 与黄金模型一致性", "76,032 码零差异", "逐字节一致", "达标"],
         ["单任务拍数（真实 E203 全子系统）", F.f0(F.CYC_TASK) + " 拍", "—", "实测"],
         ["吞吐量 @150 MHz", F.f2(F.TPS_150) + " 任务/s", "—", "按 150 MHz 折算"],
         ["私有 SRAM", "20 宏 / 160 KiB", "仅指定宏", "达标"],
         ["共享 SRAM", "64 宏 / 512 KiB", "固定平台", "达标（含复用）"],
         ["声明顺序状态", F.f0(F.STATE_BYTES) + " B", "4 KiB参考预算", "超 30 B"],
         ["新增面积（全部新增逻辑与私有宏）", "小计1.420359；上界1.987325 mm²", "≤2.25 mm²", "综合级面积满足"],
         ["150 MHz时序", "见7.3节", "6.666667 ns", "存在负裕量"],
         ["平均功耗 / 单任务能耗", "见 8.2 节", "同配置同窗口", "服务器 PT"]],
        widths=[5.6, 5.2, 3.4, 2.8], size=9, cap="主要成果与达标情况",
        aligns=['left', 'center', 'center', 'center'])

    R.h2("1.4　报告组织")
    R.p("第 2 章给出系统总体架构与地址空间；第 3 章说明整数数值格式与非线性近似；"
        "第 4 章展开加速器微架构，包括 20 宏存储组织、8×16 阵列、四路整数流水线、直接写回与晚期预取；"
        "第 5 章说明 SoC 集成、共享 SRAM 仲裁、NICE 块搬运与固定 ROM 启动；第 6 章给出验证方法与结果；"
        "第 7、8 章给出综合面积、时序与任务功耗及其服务器报告来源；第 9 章做任务窗口分解与目标差距分析；"
        "第 10 章归纳设计特点与版本沿革；第 11 章给出证据与来源；附录给出寄存器映射、地址划分与参数包格式。")


def ch2(R: Report):
    R.h1("2　系统总体架构", new_page=True)
    R.h2("2.1　平台框架与设计边界")
    R.p("平台由四部分组成：E203 RISC-V 处理器及其 ITCM/DTCM、系统总线与外设、512 KiB 系统共享 SRAM、"
        "以及参赛队实现的 AI Engine。复用 E203 运算核心与原总线译码，配置 NICE 并修改外层接入；"
        "新增部分为加速器内核、20 个私有 SRAM 宏、ICB 到加速器的桥（kwt_soc_icb_bridge）、"
        "共享 SRAM 控制器、NICE 块搬运、原总线入口三主仲裁器，以及504 B固定启动ROM。")
    R.table(
        ["组成部分", "归属", "本设计的工作"],
        [["E203 处理器 + ITCM/DTCM（各 64 KiB）", "组委会平台（复用）", "CPU核心复用，配置NICE与外层接线"],
         ["系统总线与外设（SysPer 0x1100_0000）", "组委会平台（复用）", "挂接 AI Engine 的 MMIO 从口"],
         ["512 KiB 共享 SRAM", "组委会平台（固定）", "64个16 bit宏；仅原System Bus从口，无直写旁路"],
         ["AI Engine（加速器）", "本设计", "内核 + 20 个私有宏 + MMIO 封装"],
         ["启动 ROM", "本设计（4 KiB 可寻址）", "126 条指令、504 B 的调度固件，NOP 填充"],
         ["分类头", "统一软件", "不在硬件任务内"]],
        widths=[5.6, 3.8, 7.0], size=9, cap="平台组成与本设计边界")

    R.h2("2.2　SoC 顶层与地址空间")
    R.p("CPU、NICE与供包ICB请求统一进入原System Bus入口，再由原平台地址译码，"
        "把0x1100_0000访问经SysPer送至加速器桥，把0xA000_0000访问经原sysmem送至共享SRAM；"
        "其余地址按平台原有映射处理。加速器桥把 ICB 的单笔读写转换成 kwt1_mmio 的 32 bit 请求/响应，"
        "并保证“响应稳定保持至被取走”的语义，使 CPU 可以按普通 load/store 访问加速器。")
    R.table(
        ["地址区间", "目标", "说明"],
        [["0x0800_0000", "ITCM（64 KiB）", "本设计不使用；固件在 ROM 中执行"],
         ["0x9000_0000", "DTCM（64 KiB）", "调试与栈；任务数据全部在共享 SRAM"],
         ["0x1100_0000", "加速器 MMIO", "kwt1_mmio，寄存器见附录 A"],
         ["0xA000_0000 – 0xA007_FFFF", "512 KiB 共享 SRAM", "mailbox、参数、输入、输出，见附录 B"],
         ["0x1000 起", "复位 ROM（4 KiB 可寻址）", "126 条指令；未用字填 NOP"],
         ["其他", "平台外设", "不参与本任务"]],
        widths=[4.8, 4.4, 7.2], size=9, cap="SoC 地址映射")
    R.figure("fig_soc.png", 15.4, "本设计接入原 System Bus 的供包、块读取与结果写回通路")

    R.h2("2.3　CPU 与加速器的分工：从逐字 PIO 到有界块搬运")
    R.p("分工遵循赛题“必做计算不得由处理器软件代算”的要求，CPU 只做控制与搬移，不做任何模型运算。"
        "逐字 PIO 需要 189,328 次 store，会占满整个任务窗口；本设计改用 CPU 拥有的有界 NICE 多周期指令："
        "一条指令描述“从共享 SRAM 某地址搬 N 个字到加速器”，"
        "由硬件完成地址递增与握手，CPU 在指令完成前保留包租约，不存在指令结束仍在后台搬运的情况。")
    R.table(
        ["职责", "CPU（E203）", "加速器"],
        [["控制", "解析 mailbox 序列号；提交 NICE 指令；轮询 done/error；置完成标记",
          "维护 13 包租约、层号、need_parameters/layer_valid 握手"],
         ["参数搬运", "15 条 NICE 指令（13 包 + 输入 + 输出）", "经共享 SRAM 单口读取，写入私有bank"],
         ["计算", "不参与", "Q/K/V/O、QKᵀ、Softmax、PV、残差、LN、FC1、GELU、FC2"],
         ["写回", "提交输出块指令并等待完成", "经原总线写入共享SRAM；台架比较，不代算"]],
        widths=[2.6, 7.0, 6.8], size=9, cap="CPU 与加速器的职责划分")
    R.p("有界块搬运把 189,328 次逐字事务压缩为 15 条指令；System Bus 统一接入后，完整任务窗口为 2,256,857 拍。")

    R.h2("2.4　数据通路总览")
    R.table(
        ["阶段", "数据规模", "输入来源", "输出去向"],
        [["输入装载", "99×64 S16（3,168 字）", "共享 SRAM 0xa004_0000", "激活bank 8–15 的 2688–3519"],
         ["Q/K/V 投影", "99×64 → 99×192", "当前层输入 + 权重；首层S16", "Q 448、K 896、V 1344"],
         ["QKᵀ + Softmax", "99×99", "Q、K", "概率（16 bit，低 PV 暂存）"],
         ["PV 双pass", "99×99 × 99×64", "U16概率低/高字节、V", "context 1792"],
         ["O 输出投影", "99×64", "context + O权重", "O 输出2240"],
         ["残差 1 + LayerNorm 1", "99×64", "O输出 + 当前层输入残差", "归一化行缓存（base 0）"],
         ["FC1 + GELU", "99×64 → 99×256", "行缓存 + 权重bank", "复用 Q 区 448（1,792 字/bank）"],
         ["FC2 + 残差2 + LN2", "99×256 → 99×64", "FC1/GELU、权重、LN1残差", "FC2为2240；LN2为448，再交接下层或输出"]],
        widths=[3.6, 4.6, 4.2, 4.2], size=9, cap="单层编码器的数据流与bank基址")


def ch3(R: Report):
    R.h1("3　数值格式与算法映射", new_page=True)
    R.h2("3.1　分层定点格式")
    R.p("全部计算采用定点整数，契约代号 INTEGER_NUMERICS_V1 的 S16 输入档。张量在存储与搬运中为 INT8，"
        "首层输入为 INT16；乘加累加器为 INT32，归一化与 Softmax 的中间量为定点 Q 格式，"
        "缩放因子按通道或按行给定。权重量化为 INT8（对称、按输出通道一个 scale）。")
    R.table(
        ["数据类型", "位宽", "用途", "缩放与舍入"],
        [["首层输入", "INT16", "99×64 输入张量", "对称范围[-32767,32767]；张量级scale"],
         ["激活（存储）", "INT8", "层间传递、输出", "张量级scale，对称饱和到[-127,127]"],
         ["权重", "INT8", "Q/K/V/O/FC1/FC2 六类矩阵", "输出通道级 scale"],
         ["乘加操作数 A", "17 bit 有符号", "8×16 阵列行操作数", "S16 符号扩展，或 S8 符号扩展"],
         ["乘积 / 累加", "25 bit / 32 bit", "8×16 输出驻留阵列", "不截断，只在写回时缩放"],
         ["归一化中间量", "64 bit归约；Q14/Q20", "LN归约、Q14归一化与Q20仿射", "epsilon采用冻结Q16编码；RNE"],
         ["概率", "U16，0…65535", "Softmax 输出；real=P/65535", "独立RNE，不强制行和精确65535"],
         ["残差", "INT24", "残差相加与平方", "相加后单次 RNE，末级饱和到 INT8"]],
        widths=[3.6, 3.4, 5.2, 5.0], size=9, cap="分层定点格式（S16 输入档）")

    R.h2("3.2　舍入与饱和")
    R.p("所有需要降低位宽的节点统一使用 RNE（round to nearest, ties to even），在移位前判断溢出、"
        "在输出端饱和到目标位宽。残差通路的两路乘加先求和、后只舍入一次，避免两次舍入引入偏差；"
        "LayerNorm 的平方与三段倒数分别成批流水，保持原有的开方/除法依赖关系。")
    R.p("S16 输入档把首层残差从16 bit扩到24 bit：第0层注意力后残差读取2688起的16 bit输入区，与O输出对齐相加后再执行LN1，保持PostNorm顺序；"
        "残差缓存由 64 个 16 bit 字扩为 64 个 24 bit 字（复用概率暂存的 256…383 半字与配对 LN 的 low_pv 高位），"
        "归一化输出仍饱和回 8 bit。四路流水线在残差阶段每路先完成两个乘积再执行一次 RNE，舍入位置不变。")

    R.h2("3.3　非线性的整数实现")
    R.table(
        ["算子", "实现方式", "存储开销", "误差控制"],
        [["GELU", "256 项 INT8 查表，两拍完成读/查表/写", "复用已死亡的 γ 缓存 256 B", "按冻结整数模型逐码生成"],
         ["Softmax", "减行最大值后 exp 查表（4,096 项 U32），radix-4 迭代求倒数，商乘分母并做余数校正",
          "C 组 2 个宏存 exp 表", "最大值先行保证不溢出"],
         ["LayerNorm", "两趟求和得均值与方差，一次 32 拍 isqrt 与一次短常数倒数，再分三趟做仿射",
          "γ/β 每次 LN 缓存一次（复用概率区）", "方差加 ε 后开方，RNE 后处理负值"],
         ["除法/开方", "共享一套精确 restoring 迭代单元；2^40 用 21 拍、2^47 用 24 拍短路径",
          "无额外存储", "余数比较决定末位进位"]],
        widths=[2.6, 7.2, 3.6, 3.6], size=9, cap="非线性算子的整数实现")
    R.p("把 exp、γ/β 与 GELU 表压进“已死亡”的算子存储区，是面积能够收敛的关键："
        "概率在 LN1/GELU/LN2 之前即失效，其前 256 个半字被 64 个 γ 与 64 个 β 复用；"
        "codes 在量化输出写入 SRAM 后失效，被 64 个残差半字复用。这两处复用共减少 5,120 bit 声明状态，"
        "且不改变任何数值路径。")

    R.h2("3.4　精度结果")
    R.p("用官方权重与官方预处理流程，在验证划分 4,445 个样本上比较浮点参考与整数模型的分类结果：")
    R.table(
        ["配置", "正确数", "Top-1", "相对浮点下降", "结论"],
        [["浮点参考（FP32）", F.f0(F.ACC_FP32), F.f2(F.ACC_FP32_PCT) + "%", "—", "基准"],
         ["最新候选（S16 首层输入）", F.f0(F.ACC_INT), F.f2(F.ACC_INT_PCT) + "%",
          F.f3(F.ACC_DROP) + " pp", "满足精度要求"],
         ["对照：全 S8 输入", "4,338", "97.59%", "0.225 pp", "对照配置"]],
        widths=[5.4, 2.6, 2.6, 3.2, 4.4], size=9, cap="验证集精度对比（4,445 样本）")
    R.p("S16 首层输入使精度从 97.59% 回到 97.75%，代价是输入量由 1,584 字增至 3,168 字。"
        "验证集为 4,445 个样本，权重、预处理与分类头均与官方评测一致。")
