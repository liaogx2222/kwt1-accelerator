# KWT-1 RTL v2：审查 R17 实施

固定 `INTEGER_NUMERICS_V1`，12 层、99 token、D=64、FFN=256、8×8 PE、20 个同步单口 4096×16 SRAM。生产入口 `kwt1_mmio`，原生入口 `kwt1_accel`。`rtl/v1` 与旧发布保持原样。数值公式、参数、全部舍入及饱和点不变。

从项目目录编译生产入口：

```powershell
iverilog -g2012 -s kwt1_mmio -o kwt1.vvp -f rtl/v2/files.f
```

## 调度与存储

Dense、QK、PV 在首拍同步读之后，每个使能周期同时消费上一读结果、发射 MAC 和预取下一归约值；末次 MAC 不越界预取。暂停时读输出保持，恢复时归约序号连续。Dense 六种矩阵均按输出通道块外层、token 块内层调度，八路系数跨 token 重用。O、FC2、QK、PV 都使用最多八个 token/query 行，尾块为三行；PV 保留低/高字节两 pass。

| 宏 | 数据与地址（每宏 16-bit word） |
|---|---|
| 0…7 W | 四个逻辑权重银行，每个拆为两个 4096 word 宏 |
| 8…11 A | 输入/LN1 从 0 起，Q/LN2 从 832 起，完整 context 从 1664 起，O/FC2 从 2496 起；每区 832 word |
| 12…15 B | K 从 0 起、V 从 832 起；后续复用为 FC1/GELU |
| 16…17 C | S32 系数分片；GELU LUT 在 1880…2007；8×99 个 S32 score 分片在 2048…2839 |
| 18…19 E | U32 exp LUT 分片；最低端零值由控制逻辑产生 |

这些区域按算子生存期复用。残差输入 A0 保留到 LN；LN1 后 FC1 覆盖 B 中 K/V，LN2 完成才逐地址交接到下一层输入。所有实际张量访问经过 20 个物理单口端口，装载、输入、核心、输出互斥拥有端口。

Softmax 每次加载 99 个 score 同步求 max，流水 RQ/exp 读取及求和，迭代得到倒数，再流水完成 exp×R、商×分母和精确余数校正/RNE。LN 的 gamma/beta 每次 LN 缓存一次；残差两乘先求和再唯一 RNE，平方、三段 RQ 分别成批流水，保持原 sqrt/div 依赖。GELU 临时复用已经死亡的 gamma 缓存存放 256 B LUT；LN2 开始重新加载系数。

声明状态包含 P[8×99]、lowPV[64]、残差、Softmax/LN 行、gamma/beta、PE、流水、装载/总线和所有控制寄存器；4 KiB 门禁统计这些状态，只排除宏数据阵列。`register_inventory.json` 提供逐信号清单。它是保守声明上界，不能当作标准单元面积。

2026-11-11 的相邻行 LN 调度在 PV 已退休后复用 `low_pv[64]`：低 16 位保存同一个 SRAM 字内后一行的两个残差操作数，位 23:16 保存前一行已完成的 S8 输出。后一行直接从缓存装入残差，完成后合并两行一次写回。最后的第 98 行保留原读改写以保持填充字节。每行算术请求、依赖、RNE 与饱和点不变，缓存必须在当前偶数行装入后才供奇数行消费。LN1、GELU、LN2 的旧缓存不能跨冷任务复用。保守寄存器声明仍为 30,459 bit / 3,808 B，私有 SRAM 为 160 KiB。

该版独立 A/B 入口为 `python scripts/validate_paired_ln.py --output testdata/<全新目录>`，覆盖原版 Git 重建、十二类完整冷任务、暂停与故障恢复、十二套参数及边界输入、缓存状态在途复位。服务器独立工程入口见 `flow/clean/README.md`，由 `scripts/export_clean_project.py` 导出；必须重新取得本版映射、门级和 PPA 证据。

## 算术契约

一套 32×32→64 共享乘法流水（四个 16×16 部分积）、一套 RNE、一个 64 拍除法/32 拍 isqrt。纯乘/RQ 同类请求可连续逐拍接受；RQ 延迟 4 拍。背压保持结果，reset 清除所有有效位。模式切换前先排空。

`kwt_math.op=4` 专用于配对残差：tag[0]=0 为第一乘，tag[0]=1 为第二乘；高七位为同一通道。两乘相加后只舍入一次，输出 tag 为通道号。每对产生一个响应，请求可每拍接受；调用者必须按相邻 A/B 配对提交并排空后切换模式。Softmax 和 LN 后续计算均由实际退休结果驱动。

## 单缓冲供参驱动

`kwt1_run_provider(device, provider, input, output)` 按 common、layer0…11 顺序 acquire；PENDING 时有界轮询，可取消。唯一 lease 持有至末字银行写入排空且 CRC/有效槽发布，随后 release。错误时释放已取得的 lease、ABORT，并 cancel 未完成供数。单缓冲只需 61,728 B，不能让 13 包同时驻留目标共享区。read/write 回调必须完成整个总线响应并有自身超时；`poll_limit` 限定驱动轮询。

`sim_provider.cpp` 实际使用唯一 512 KiB 数组：input 0…6335，output 8192…14527，packet 16384…78111；固件预留 131072…262143，栈预留 507904…524287。已用数据 74,400 B，加固件 128 KiB 与栈 16 KiB 共 221,856 B。每次只从当前包文件写 staging，释放后毒化；检查 lease、层序和预留区哨兵。固件/栈是预算预留，尚无指定 E203 的链接镜像/栈高水位证明。

## MMIO 与复位

地址和原生接口沿用 [v1 接口说明](../v1/README.md)：参数/输入/输出数据口分别为 0x10/14/18，状态 0x04，START/ABORT 0x00；0x20…44 是实际任务/计算/银行访问/暂停计数。单笔在途响应稳定保持，最后输出响应消费后才 done/IRQ。软件 ABORT 保留该控制写应答并取消任务；外部 reset/abort 清除总线响应。SRAM 内容不复位，每个冷任务重装全部 13 包与输入。

`KWT_TECH_SRAM` 绑定外部 `kwt_tech_sram_4096x16`，要求与行为模型相同的同步读、读输出保持和写时不变语义。生产综合不包含 `kwt1_observed.sv`；该文件仅在测试中独立核对状态/算子账本。

## 统一复现

依赖锁 [requirements.lock](requirements.lock)。当前 host 为 Python 3.10.9、NumPy 1.26.2，Icarus 12.0 devel s20150603，Verilator 5.48.0 wheel，Zig 0.13.0，Yosys 0.69 git 9f75ca1f9。已发布证据包含工具文件 SHA256。

```powershell
python -m pip install --target tools/rtl_v1_python --no-deps verilator==5.48.0 ziglang==0.13.0
python -m pip install --target tools/rtl_v2_python yowasp-yosys==0.69.0.0.post1233 yowasp-runtime==1.96 wasmtime==47.0.1 click==8.5.0 platformdirs==4.12.4
$env:KWT_IVERILOG_BIN = 'E:/project/FPGAcompetition/RISCV_CPU/tools/iverilog/bin'
$env:KWT_RISCV_GCC = 'path/to/riscv32-unknown-elf-gcc.exe'
python scripts/validate_rtl_v2.py --stage all --output testdata/rtl_v2_repro
python scripts/validate_rtl_v2.py --stage check --output testdata/rtl_v2_repro
```

`all` 顺序执行 unit、24 层、7 类拒收/12 类复位、跨仿真器、v1 同配置两类参考、v2 三种配置各 12 类完整冷任务（压力含六次故障后完整恢复）、通用综合、综合网表数学回归及独立总验收。阶段可分别运行 `unit/layer/stress/cross/provider/baseline/synth/check`；`provider` 支持 `--mode always|stress|system --version v1|v2 --faults`。`--quick` 只用于调试，不能通过总验收。已发布目录拒绝执行覆盖性阶段；新复现请选择新目录。

配置独立保存，三个场景分别为无 core/mem 注入暂停、固定周期压力、系统供数/CPU 延迟假设。外层从输入到共享区传输开始，包含逐包异步到达、软件/总线装载、全计算和输出写回，到驱动读取 done 返回；RTL 内层从首个 frame/input 接受到最后输出响应确认。系统模式假设每 32 bit 供数 6 拍（150 MHz 下 100 MB/s）、每包初始 1024 拍、每次总线回调额外 4 拍。输入同样计 6 拍/word；所有配置最终读响应保持 20 拍。主机 C 执行不等于 E203 指令执行，不能将这些假设称为真实 E203 延迟。

通用综合用 20 个 SRAM 黑盒生成实际 `generic.v/json`，执行 `check -assert`，不启用会触发当前 WASM 栈限制的额外 SAT 资源共享优化。共享硬件本身已在 RTL 中显式实现。数学综合网表重跑 2592 数学向量；TB 同时运行原 RTL 的 640 迭代/PE/SRAM 测试，不能把迭代测试写成综合网表验证。没有完成整机门级等价或指定库时序/面积/能耗签核；`clock_template.sdc` 只是约束样例。

LN-E01 的固定 profile 局部质量例外保留原六处失败，RTL 零差异要求不变。SOURCE-E01 没有新历史线索，保持 OPEN。全部指标见最终发布 `testdata/rtl_v2/release/verification.json` 与架构 v1.8 实施报告。
