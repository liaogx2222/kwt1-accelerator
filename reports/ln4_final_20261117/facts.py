# -*- coding: utf-8 -*-
"""当前总线周期取自新完整SV台架RTL；计算参数来自冻结595724b。
历史观察量不代表新总线的分阶段实测。物理指标一律标注服务器报告来源。
"""

REV = "LN4 合并版（optimization chain 7a79105）"
BRANCH = "codex/soc-joint-20261111"
DATE = "2026 年 11 月 17 日"

# ---- 实测周期（12 类完整网络，逐类相同） ----
# 2026-11-17 实测：Verilator RTL 全 SoC，case 0 冷任务，host_gap=4。
# 门级 TB 的 host_write 内含 repeat(4)，两者 host 供包节拍一致，故与门级同口径。
CYC_TASK = 2256857
CYC_COMPUTE = 1469112          # 加速器 RUN/KICK 周期（accel.compute_cycles）
CYC_NONCOMPUTE = CYC_TASK - CYC_COMPUTE
F_CLK = 150e6

MS_TASK = CYC_TASK / F_CLK * 1e3
TPS_150 = F_CLK / CYC_TASK
CLK_60 = CYC_TASK * 60
CLK_75 = 150e6 / 75
CLK_100 = 150e6 / 100

# ---- 工作量 ----
MAC_LAUNCH = 672672
MAC_LAUNCH_LAYER = 56056
BYTE_MAC = 80974080
ARRAY_FLOOR = BYTE_MAC / 128.0            # 128 PE
ARRAY_EFF = BYTE_MAC / (MAC_LAUNCH * 128.0)
MATH_REQ = 2027916
MATH_RET = 1875852
MATH_FLOOR = MATH_RET / 4.0
SERIAL_FLOOR = ARRAY_FLOOR + MATH_FLOOR
TPS_FLOOR = F_CLK / SERIAL_FLOOR

# ---- 数据规模 ----
PARAM_WORDS = 189328
PARAM_BYTES = PARAM_WORDS * 4
PACKETS = 13
COMMON_WORDS = 4144
LAYER_WORDS = 15432
IN_WORDS = 3168
IN_BYTES = IN_WORDS * 4
OUT_WORDS = 1584
OUT_BYTES = OUT_WORDS * 4

# ---- 历史旧接口统计，禁止作为新总线实测使用 ----
RETIRED = 315537
NICE_INSTR = 15
SYSPER_RD = 41461
SYSPER_RD_NEXT = 41462
SYSPER_WR = 15
SH_RD = 197756
SH_RD_NEXT = 197755
SH_WR = 1597
HOST_WR = 192508

# ---- 预取 ----
PF_FRAMES = 11
PF_WRITE = 291720
PF_STALL = 143842

# ---- 资源 ----
PRIV_MACROS = 20
PRIV_KIB = 160
SHARED_MACROS = 64
SHARED_KIB = 512
STATE_BITS = 33004
STATE_BYTES = 4126
STATE_BUDGET = 4096
MULT_INST = 144
ROM_BYTES = 504
ROM_INSTR = 126
ROM_SPACE = 4096

# ---- 精度 ----
ACC_N = 4445
ACC_FP32 = 4348
ACC_INT = 4345
ACC_FP32_PCT = ACC_FP32 / ACC_N * 100
ACC_INT_PCT = ACC_INT / ACC_N * 100
ACC_DROP = ACC_FP32_PCT - ACC_INT_PCT

# ---- 版本演进（实际 E203 完整子系统，12 类一致） ----
EVOLVE = [
    ("8×8 + 逐字 PIO", "d280774", "64 PE、20 宏、CPU 逐字搬运", 11943687),
    ("8×16 标量", "018032d", "128 PE、权重/激活 8+8 银行重排", 9735884),
    ("8×16 + 四路", "a1381d7", "四路精确整数流水；SoC 受 PIO 限制", 9735884),
    ("NICE 块搬运", "421ed4a", "15 条有界 NICE 指令，共享单口仲裁", 3078420),
    ("晚期预取", "a691cc7", "20 宏内预取 + 精确调度收紧", 2470147),
    ("直接写回", "693ffde", "dense 结果直写激活银行，取消 D_STORE", 2391817),
    ("S16 输入档", "595724b", "首层 S16 输入、S8 内部、W8", 2407590),
]

# ---- 本机参考分区（Nangate45 / Yosys，仅相对参考，不是 SMIC40 签核） ----
LOCAL_AREA = [
    ("8×8 PE 阵列（隔离）", "0.077167", "8×8 参考"),
    ("8×16 PE 阵列（隔离）", "0.154310", "本设计阵列规模"),
    ("16×16 PE 阵列（隔离）", "0.306983", "未采用"),
    ("单路 kwt_math 分区", "0.014612", "四路之一"),
    ("另三路数学分区（估）", "0.043837", "不含新增 mux/控制"),
    ("迭代除法/开方分区", "0.006062", "含精确 restoring"),
    ("NICE 块控制器分区", "0.002191", "168 个 DFFR"),
    ("共享口仲裁分区", "0.000179", "4 个 DFFR"),
    ("固定 ROM（单独映射）", "0.000601", "4 KiB 可寻址"),
]


def pct(a, b):
    return a / b * 100.0


def f0(x):
    return "{:,.0f}".format(x)


def f1(x):
    return "{:,.1f}".format(x)


def f2(x):
    return "{:,.2f}".format(x)


def f3(x):
    return "{:,.3f}".format(x)
