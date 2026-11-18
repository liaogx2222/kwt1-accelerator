# KWT-1 第一版完整银行化 RTL

日期：2026-10-22。固定 `INTEGER_NUMERICS_V1`，99 token、D=64、FFN=256、12 层、单头 PostNorm。生产入口为 `kwt1_mmio`；原生流入口为 `kwt1_accel`，默认 `SINGLE_LAYER=0`。`SINGLE_LAYER=1` 仅供单层验证。

本版实现全部编码器算子、20 个同步单口 SRAM、真实参数流、12 层控制和最终输出。没有在 DUT 内预置参数张量、输入或 golden 输出。指定 E203 总线、工艺 SRAM 及物理实现需在平台确定后绑定；本目录提供完整的平台无关接口和行为 SRAM 实现。

## 编译与模块

从项目 `keyword-transformer` 目录编译：

```powershell
iverilog -g2012 -s kwt1_mmio -o kwt1.vvp -f rtl/v1/files.f
```

| 模块 | 实现 |
|---|---|
| kwt1_mmio | 单笔在途 32 bit 请求/响应、保持响应、IRQ、最终总线确认 |
| kwt1_accel | 冷任务、输入配对装载、13 包层序、12 层、6336 B 输出、计数器 |
| kwt_packet_loader | 固定 ABI 头/长度/层号、CRC32、valid/ready、银行写入排空 |
| kwt_layer_banked | Q/K/V、QK、Softmax、PV 双 pass、O、两次残差/LN、FC1/GELU/FC2 |
| kwt_mac8x8 | 64 个 S32 累加器，S8×S8 或 U8×S8，尾部掩码 |
| kwt_math | 一套共享 32×32→64 乘法流水和 RNE 流水；mul/RQ 同类批次 II=1 |
| kwt_iterative | U64 除法 64 拍、isqrt 32 拍，响应保持和复位清除 |
| kwt_banks / kwt_sram_sp | 20×4096×16 同步单口宏边界，无 SRAM 内容复位 |

`mul_pipe` 由四个 16×16 部分积构成，共享宽乘法以外只有 64 个 PE 乘法。动态地址乘数已改为固定移位。`generated/kwt_profile.svh` 仅包含固定 ABI 布局、头和 CRC；通过统一入口从 13 个现有包生成。

`kwt_math` 的调用契约是同类请求批次，在改变 raw/RQ/direct-RNE 模式前排空响应；层控制器负责遵守。无背压时 mul/RQ/direct-RNE 的接受吞吐分别均为一拍一项，消费者在请求接受后第 3/4/1 拍边沿消费结果。除法和开方各自只允许一笔在途，不宣称 II=1。

## SRAM 与暂存

| 物理宏 | 内容 |
|---|---|
| 0…7 | 四个权重逻辑银行，每个拆为两个 4096 word 宏 |
| 8…11 | A：输入/LN1，以及偏移 832 的 Q/LN2 输出 |
| 12…15 | B：K、V，随后复用为 FC1/GELU |
| 16…17 | C：分片 32 bit 系数及 GELU LUT |
| 18…19 | E：分片 U32 指数 LUT；末端零值由控制逻辑生成 |

所有宏在使能上升沿采样读地址，读输出保持到下次读；写入不改变读输出。装载器、输入、核心及输出互斥拥有端口。层间逐地址同步搬移输出至输入，之后才允许装载下一层参数。输入最后半对的无效字节写零。

`KWT_TECH_SRAM` 选择外部 `kwt_tech_sram_4096x16(clk,en,we,addr,wdata,rdata)` 包装，宏必须符合上述时序。未定义时使用可综合的行为存储数组；`KWT_SIM` 仅用于毒化初值和可选调试 trace，不用于综合。

展开生产顶层统计全部时序状态为 14701 bit，向上取整 1838 B，小于 4 KiB；仅排除 20 个 SRAM 数据阵列。该上界含输入配对缓冲、残差、Softmax 行、PV 两 pass 中间结果、LN 在途值、PE、流水、总线和控制寄存器。它是声明位数，不等同工艺映射面积。

## 原生流顺序

1. `abort` 清除有效位/在途事务/计数器，SRAM 内容保持。
2. `frame_valid/ready` 建立 common 帧；流入 4144 个 32 bit 字，最后一字 `cfg_last=1`。
3. 建立 layer0 帧，流入 15432 字；输入流入 1584 字，末字 `input_last=1`。三者允许合法交错，但同一拍银行只有一方持有。
4. `start_valid/ready` 启动。`need_parameters` 置位后按 `current_layer` 装载 layer1…11。
5. 消费全部 1584 个输出字，最后一字 `output_last=1`。`output_data` 在背压中保持。
6. `awaiting_ack` 期间仍 busy；外部最终响应确认 `result_ack` 后才 done。下一冷任务必须 abort 并完整重载。

所有源在 valid 且未 ready 时保持负载稳定。`core_enable` 和 `mem_enable` 可独立暂停；已经进入算术流水的值在内部保持有效，消费依赖不提前。CRC、头、长度、非法输入码 -128 或层序错误锁存 fault，需 abort 后重载；坏包不发布有效槽。

## 通用 MMIO

请求：`req_valid/ready, req_write, req_addr[31:0], req_wdata[31:0], req_wstrb[3:0]`；响应：`resp_valid/ready, resp_rdata[31:0], resp_error`。地址为相对字节偏移，只支持对齐访问与完整字写入。一笔响应未消费时不接受第二笔；消费与下一请求可在同一拍发生。

| 偏移 | 访问 | 定义 |
|---|---|---|
| 0x00 | W | bit0 START，bit1 ABORT（优先） |
| 0x04 | R | 状态，见下文 |
| 0x08 | W | FRAME：bit8 common，bit3:0 层号 |
| 0x0c | W | 下一次 PARAM/INPUT DATA 的 LAST，0 或 1；DATA 接受后清零 |
| 0x10 | W | PARAM DATA，必要时通过 ready 背压 |
| 0x14 | W | INPUT DATA，必要时通过 ready 背压 |
| 0x18 | R | OUTPUT DATA；最后一个读响应消费后才向核心确认 |
| 0x1c | R | bit7:0 错误码，bit15:8 调试状态 |
| 0x20/24 | R | task_cycles，低/高 32 bit |
| 0x28/2c | R | compute_cycles |
| 0x30/34 | R | 实际 SRAM 读取 word 数 |
| 0x38/3c | R | 实际 SRAM 写入 word 数 |
| 0x40/44 | R | 核心因 enable 暂停的周期 |
| 0x48 | R | ID = 0x4b575431 |

STATUS bit0 busy、1 done、2 error、3 common_valid、4 input_loaded、5 layer_valid、6 need_parameters、7 awaiting_ack、8 start_ready、9 frame_ready、10 cfg_ready、11 input_ready、12 output_valid、19:16 current_layer。错误码：1 层序/层号，2 头/长度/CRC，3 非法输入 -128，4 输入长度，5 算术错误。非法总线地址、未对齐或部分写产生总线响应错误。

`irq = done || error`。外部 `rst_n` 及 `abort_hw` 清除总线在途响应；软件 ABORT 保留本次控制写应答并取消加速器事务。集成时同步释放外部复位。

[C 驱动](driver/kwt1.c) 使用完成整个读写响应的回调。`kwt1_run` 冷装载全部 13 包、输入，等待逐层请求，读取输出并检查完成；CPU 不执行编码器数学。回调处理平台总线错误，`poll_limit` 限定轮询次数。

## 复现

依赖见 [requirements.lock](requirements.lock)。Windows 本项目验证使用 Python 3.10.9、NumPy 1.26.2、Verilator wheel 5.48.0、Zig 0.13.0 和 Icarus 12.0 devel。将 Verilator/Zig 安装到项目工具目录：

```powershell
python -m pip install --target tools/rtl_v1_python --no-deps verilator==5.48.0 ziglang==0.13.0
$env:KWT_IVERILOG_BIN = 'E:/project/FPGAcompetition/RISCV_CPU/tools/iverilog/bin'
python scripts/validate_rtl_v1.py --stage all --output testdata/rtl_v1_repro
```

`all` 包含单元、24 层普通/边界、两个完整冷任务、C 驱动、错误/复位、跨仿真器和总证据核验。`check` 重算保存结果、验证源码/输入/历史发布 hash、检查综合入口编译与静态位数，输出 `verification.json`。`--quick` 仅适用于单项调试；快速结果不能通过总验收。阶段还可单独选择 `unit/layer/full/mmio/stress/cross`。

完整任务实测约 3635 万周期；MMIO/C 驱动约 3710 万周期，假设 150 MHz 约 247.36 ms，未达到 60 ms。该窗口包含参数、输入、逐层交接、CPU 轮询、输出与最终读响应确认；没有指定平台的外部内存/互连延迟。`clock_template.sdc` 是目标约束样例，150 MHz 仍需指定库时序验证。

数值 profile、NPZ、manifest、golden 和历史证据保持。LN-E01 延续固定局部例外，原六项质量失败保留；SOURCE-E01 继续 OPEN。
