# KWT-1：面向关键词识别的整数 Transformer 加速器

KWT-1 是一颗面向关键词识别（Keyword Spotting）的整数 Transformer 推理加速器，含 RISC-V（E203）子系统、共享 SRAM 与自定义 MMIO 加速器。本仓库是该设计的完整工程：RTL、位精确整数模型、验证台架、综合/时序脚本与最终设计报告。

工程派生自 ARM 官方 [Keyword Transformer](https://github.com/ARM-software/keyword-transformer)（Apache 2.0），沿用其模型与训练流程；加速器、总线与整机集成部分为本项目新增。上游 README 保留于 [`README_upstream.md`](README_upstream.md)。

本设计面向 2026 年全国大学生嵌入式芯片与系统设计竞赛芯片设计赛道。

---

## 1. 结果

以下为 **LN4 版本**在 150 MHz 目标频率下的折算值。周期数取自 RTL 全 SoC 仿真（Verilator 5.48），host 供包节拍与门级台架一致（gap = 4），两者口径相同。

| 指标 | 数值 |
|---|---|
| 每任务拍数 | 2,256,857 |
| 吞吐量 @150 MHz | 66.4641 task/s |
| 单任务延迟 @150 MHz | 15.0457 ms |
| 达成 60 task/s 所需时钟 | 135.41 MHz |
| 整数模型精度（4,445 样本） | 97.7503 % |
| 相对浮点精度下降 | 0.0675 pp |

**资源与面积**

| 项 | 数值 |
|---|---|
| 共享 SRAM | 512 KiB（单一从接口，无片外存储） |
| 加速器私有宏 | 20 个 / 160 KiB |
| MAC 阵列 | 8×16 = 128 PE，有效字节利用率 94.0 % |
| 新增面积分账小计 | 1.420359 mm² |
| 新增面积上界 | 1.987325 mm²（预算 2.25 mm²，余量 0.262675） |
| 完整数字 SoC 单元与宏面积 | 3.748433 mm² |

### 已知限制

以下三点如实披露，不作修饰：

1. **150 MHz 时序尚未收敛。** r3 布局布线后 TT 角 recovery WNS −0.78 ns、TNS −65.91 ns，hfclk setup WNS −0.76 ns，hold WNS −0.19 ns。上表吞吐量是**按目标频率折算值**，不是已签核频率下的实测吞吐。
2. **本版本未取得功耗数据。** 受提交时间限制，r3 的功耗报告未及产出，报告中功耗一节标注为未取得，不沿用旧版本数值。
3. **状态存储超出 4 KiB 预算。** 运行时状态共 33,004 bit = 4,126 B，比 4,096 B 预算多 30 B，已在报告中说明。

---

## 2. 设计概要

**数据格式。** 首层输入 S16，内部激活 S8，权重 W8。全部整数运算，无浮点单元。

**阵列。** 8×16 权重驻留型 MAC 阵列，128 个 PE。权重与激活各 8 个银行重排，配合 token 两两打包，16 token 只需 8 个银行各 64 字。

**存储。** 20 个私有宏（8 权重 + 8 激活 + 4 系数）共 160 KiB；64 个共享宏构成 512 KiB 共享 SRAM，仅保留单一从接口，不设私有旁路端口。片外无 DDR、无外部存储控制器。

**搬运。** NICE 有界块搬运把 189,328 次逐字 store 压缩为 15 条指令，供包、块读取与结果写回全部收进原 32 bit System Bus。

**软件接口。** 加速器 MMIO ID `0x4B575431`；共享 SRAM 映射为 `a000_0000` mailbox、`a000_1000` common、`a002_0000` input、`a002_2000` output、`a002_4000` 单层 lease。

### 优化链

`rtl/` 下按优化阶段保留各版本实现，末端为 LN4：

| 阶段 | 提交 | 主要改动 | 每任务拍数 |
|---|---|---|---|
| 8×8 + 逐字 PIO | d280774 | 64 PE、20 宏、CPU 逐字搬运 | 11,943,687 |
| 8×16 标量 | 018032d | 128 PE、8+8 银行重排 | 9,735,884 |
| 8×16 + 四路 | a1381d7 | 四路精确整数流水 | 9,735,884 |
| NICE 块搬运 | 421ed4a | 15 条有界 NICE 指令 | 3,078,420 |
| 晚期预取 | a691cc7 | 20 宏内预取 + 调度收紧 | 2,470,147 |
| 直接写回 | 693ffde | dense 结果直写激活银行 | 2,391,817 |
| S16 输入档 | 595724b | 首层 S16、内部 S8、W8 | 2,407,590 |
| System Bus v1 | e8f547f | 统一接入 32 bit 总线 | 2,783,869 |
| **LN4** | 本版 | LayerNorm 四路配对调度 | **2,256,857** |

System Bus 一版相对 S16 输入档多 376,273 拍（+15.63%），代价换来平台侧不新增私有读写端口与旁路；LN4 在此基础上前进 527,012 拍（−18.93%）。

> 这一 −18.93% 属于**整条优化链**的累计成果，不能全部归因于 LN4。单独看，LN4 相对其父版本（iter_fast，热启动 2,257,646 拍）仅省 8,370 拍（0.37%）。

---

## 3. 仓库结构

```
rtl/                  RTL 源码，按优化阶段分子目录
  v2/                 整机集成层（kwt1_accel / kwt1_mmio / kwt_layer_banked）
  ln4_opt/            LN4 版本层实现（当前采用）
  sysbus_v1/          System Bus v1 版本
  ...                 其余历史阶段
flow/                 仿真台架、综合与 STA 脚本
  soc_metrics/        门级指标采集 TB
sim/soc/              仿真文件列表（files.f）
tb/                   顶层测试台
integer_model/        位精确整数模型（Python）
firmware/             加速器驱动
scripts/              工程组装、验证、检查脚本
deliverables/         复现基座：sysbus_v1_20261113_v2/project
manifest/             各批次发布清单与哈希
reports/              最终设计报告（DOCX + PDF）与可复现的生成脚本
kws_streaming/        上游训练代码（Google kws_streaming，Apache 2.0）
tests/                单元测试
```

`reports/` 下的报告不是手写文档：`facts.py` 是唯一数字源，`part1.py`–`part4.py` 生成正文，`build.py` 出 DOCX，`export_pdf.py`（Word COM）出 PDF。改一处数字即可全篇联动。

---

## 4. 复现

### 依赖

- Python 3.11+，`pip install -r requirements.txt`
- Verilator 5.48（`verilator_bin.exe`）
- zig（作为 C++ 编译器驱动）
- 生成 PDF 需 Windows + Microsoft Word（`pywin32`）

Verilator 与 zig 不随仓库分发，请放到 `tools/rtl_v1_python/`：

```
tools/rtl_v1_python/verilator/bin/verilator_bin.exe
tools/rtl_v1_python/ziglang/zig.exe
```

### 跑一个任务

```bash
# 1) 按优化链逐级组装工程，最终替换为 LN4 层实现
python scripts/prepare_ln4.py --output /path/to/project

# 2) 编译并运行 case 0，host 供包 gap = 4
python scripts/check_pv16_soc.py \
  --project /path/to/project \
  --output  /path/to/cold0 \
  --cases 0 --jobs 1 --host-gap 4
```

`check_pv16_soc.py` 首次调用会用 Verilator 把整机编译成 `sim.exe`（约 8–9 分钟），随后逐 case 运行并与 `project/fixtures/expected_XXX.hex` 逐字比对。通过时打印：

```
SOC_GATE_METRICS cycles=2256860 params=189328 input_words=3168 output_words=1584 host_words=192508
LOCAL_TASK_PROFILE legacy_cycles=2256857 issue_cycles=2256860 compute_cycles=1469112
PASS SOC_INPUT16_GATE case=0 words=1584 mismatches=0
```

报告采用 `legacy_cycles`（首个 `host_en && host_ready` 握手至完成标记响应），与门级 TB 的 `cycles` 严格同源。

### 数据集

训练与量化标定所需的 Google Speech Commands v2（`data2/`，10.5 万条 wav）不随仓库分发，需按 [`README_upstream.md`](README_upstream.md) 自行下载。RTL 仿真的 fixtures 已包含在 `deliverables/sysbus_v1_20261113_v2/project` 中，跑仿真不需要数据集。

### 重新生成报告

```bash
cd reports/ln4_final_20261117
python build.py          # 出 DOCX
python export_pdf.py     # 出 PDF（需 Word）
```

---

## 5. 来源与许可

- 上游：[ARM-software/keyword-transformer](https://github.com/ARM-software/keyword-transformer)，Apache License 2.0，见 `LICENSE.txt`
- 上游论文：A. Berg, M. O'Connor, M. Tairum Cruz, *Keyword Transformer: A Self-Attention Model for Keyword Spotting*, Interspeech 2021
- `kws_streaming/` 为 Google [kws_streaming](https://github.com/GoogleCloudPlatform/kws_streaming) 的副本，Apache License 2.0
- 本项目新增：加速器 RTL（`rtl/v2`、`rtl/ln4_opt` 等）、System Bus 集成、整数模型、验证与综合流程、设计报告。新增部分同样以 Apache License 2.0 发布。

按 Apache 2.0 §4(b)，被修改的上游文件均在文件头或对应目录 README 中标注改动；原文版权声明与许可条款保留不变。
