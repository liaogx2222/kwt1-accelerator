# Nangate45参考STA执行与迁移边界

2026-11-04。本文绑定实际`kwt1_mmio`标准单元映射，记录可复现的部分时序分析及未覆盖项；不构成完整150MHz签核。

| 项目 | 实际绑定 |
|---|---|
| 工具 | OpenSTA 2.0.17，Ubuntu jammy官方固定包，工作区解包后在Ubuntu24.04 WSL执行；系统未安装 |
| 库 | Nangate45 typical 1.10V/25°C；Liberty SHA256 `8d540a4d4cf6d09d27c87ad067857a9c0c2eeb023ab7a56e058cd3113db4e9b1` |
| 网表 | 原完整mapped JSON仅重新序列化为`-simple-lhs`，所有cell/port/net对象不变；310005标准单元与20宏 |
| 时钟 | 6.666667ns理想时钟，零不确定度参考假设，无CTS/寄生 |
| 运行常量 | 外部rst_n=1、abort_hw=0、core_enable=1、mem_enable=1；基线保留内部软件ABORT路径 |
| setup汇总 | 全29942个DFF的D端点，每端点一条最坏寄存器来源路径；Q/QN共59884个起点 |
| 未覆盖 | 宏时序/负载，外部I/O延迟/驱动/负载，复位与ABORT转换、恢复/移除，stall模式、时钟树/不确定度/RC和其他PVT |

工具包/二进制hash及许可证位置见[有效基线记录](../testdata/nangate45_reference/sta_valid_20261104/summary.json)。参考TCL为[nangate45_reference_sta.tcl](nangate45_reference_sta.tcl)。旧版工具会将部分Verilog拼接左端报错，即使进程返回0也不得接纳；runner同时检查错误行和结束标记。最初失败记录另留，不能使用其输出作为时序结果。

| 分析 | WNS/ns | TNS/ns | 负D端点 | 解释 |
|---|---:|---:|---:|---|
| 原映射运行参考 | −31.45647 | −146299.028906 | 5156 | task_rst_n 4794扇出，单BUF_X1负载超库上限约210倍，严重外推；不能倒算Fmax |
| 原映射稳态诊断 | −0.03760059 | −0.08813617 | 3 | 额外固定内部sw_abort Q=0，仅用于分离根因 |
| 缓冲树诊断变体，同基线约束 | −0.03760059 | −0.08813617 | 3 | 保留软件ABORT路径；插入321个BUF_X1、3级、树内扇出≤16，原cell投影不变；未作为生产网表接纳 |

第三行的映射变体增加256.158µm²、无新增触发器、仍20宏。它消除本次setup汇总中的高扇出根因，剩余关键路径从乘法结果bit2到RNE结果bit63；全局最大转换/最大电容和物理可实现性仍需后续全面检查。该变体没有完整任务功能回归，不能继承原网表的功能通过。

`check_setup`列出75个输入位无input delay、36个输出位无output delay、36个未约束端点。输入常量也可能被旧工具列入警告。宏结构可达7032个D端点仅是组合结构上界，既不是宏已约束的证明，也不是实际敏化时序路径数量。`all_registers -data_pins`在此工具版本包含RN/SN，不能将其恢复检查混入D-only setup TNS。

按项目根`keyword-transformer`运行，输出目录必须是新目录：

```text
python scripts/fetch_opensta_reference.py
wsl -d Ubuntu-24.04 -- dpkg-deb -x /mnt/e/project/ChipCompetition/keyword-transformer/tools/opensta_reference/opensta_jammy_amd64.deb /mnt/e/project/ChipCompetition/keyword-transformer/tools/opensta_reference/root
python scripts/run_nangate45_sta.py --output testdata/nangate45_reference/new_sta --netlist testdata/nangate45_reference/sta_compat_20261104/mapped_simple.v
python scripts/run_nangate45_sta.py --output testdata/nangate45_reference/new_buffered_sta --netlist testdata/nangate45_reference/reset_buffer_diagnostic_v2_20261104/mapped_buffered.v
```

工具包文件名和下载SHA以[下载脚本](../scripts/fetch_opensta_reference.py)及其provenance为准。迁移到指定平台后，必须替换实际库角、SRAM Liberty/LEF及wrapper、I/O约束、reset模式与RC/时钟假设，重做功能/STA/面积和活动功耗；不能按45/40比例缩放。
