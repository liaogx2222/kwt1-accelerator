# RTL v2 通用网表、驱动与接口收尾

本目录只新增候选驱动和验证设施，生产RTL继续使用 `rtl/v2/files.f`，不增PE、算术通道或SRAM，不更改整数v1、13包、模型或golden。接入时使用 [INTERFACE_CONTRACT.md](INTERFACE_CONTRACT.md)；旧发布在 `testdata/rtl_v2/release` 保留。

候选驱动用硬件ready代替逐字STATUS前探，参数DATA仍为189328字；CRC/层序/最终done保留，计算等待64拍backoff。回调有独立超时/取消；清理ABORT失败将device隔离，只有集成层硬复位并调用确认函数后才允许新任务。C API上下文扩展，必须使用同版头文件并首次整体清零。

固定预算矩阵（所有完整输出零差异，频率只是换算假设）：

| 额外CPU拍/事务 | 供数带宽@150MHz | 原驱动外层拍 | 候选外层拍 | 候选≤9M |
|---:|---:|---:|---:|---|
| 4 | 100MB/s | 8540216 | 7381184 | 是 |
| 4 | 50MB/s | 9685665 | 8526968 | 是 |
| 8 | 100MB/s | 10070833 | 8147017 | 是 |
| 8 | 50MB/s | 11216308 | 9292465 | 否 |
| 16 | 100MB/s | 13150983 | 9686855 | 否 |
| 16 | 50MB/s | 14296546 | 10831959 | 否 |

这些配置逐项重跑，不用固定事务数外推。输入6336 B供到共享区、13包逐包延迟与流量、装载、计算、输出和最终确认均在外层窗口。候选idle回调计请求的64拍及一次额外CPU回调成本；idle与硬件计算有重叠，不能再相加。真实E203指令/互连、官方供数和最终时序/面积/能耗尚待资料。

## 复现

依赖沿用冻结 `rtl/v2/requirements.lock`，没有安装新依赖；使用既有Icarus、Verilator、Zig、YoWASP及RV32 GCC。环境变量 `KWT_IVERILOG_BIN`、`KWT_RISCV_GCC` 与v2一致。

```powershell
python scripts/validate_integration.py --stage all --output testdata/integration_repro
python scripts/validate_integration.py --stage check --output testdata/integration_repro
```

可分别运行 `protocols/software/drivers/budget/gate`，`--quick`仅用于单项开发，不能总验收。`check-software`只核验G2/G3，明确不代表G1完成。已发布目录拒绝覆盖性阶段。

`gate`使用现有完整generic.v，接20个同契约SRAM模型，不用原RTL代替综合网表算子。执行完整12层任务、LN N_PASS在途硬复位和完整冷恢复，检查完整6336码、最后响应ACK、实际接受/应答守恒。它是动态门级回归，不是全输入形式等价，编译/运行明显慢于RTL；生成代码/对象缓存不列作发布源码。

`equivalence.ys`和`run_equivalence.py`是补充分区等价路径，外部SRAM抽成共享读输入并观察全部命令输出；求解器资源预算为64MiB WASM栈/128MiB工作线程栈。没有修改工具包。只有全部义务通过才能声明形式证明；未收敛或失败项必须保留，不能用局部证明代替整机动态验收。

证据在新 `testdata/integration_v1/release`。正式结论看 `verification.json`；`software_verification.json`、候选及legacy各配置目录、`budget.json`、protocols和gate分别明确自己的范围。新增来源、工具、旧32源码/434发布与历史链均由独立checker核验。

完成G1–G3后冻结8×8/20宏/INTEGER_NUMERICS_V1。待指定平台/宏/库后只做绑定及重新签核；LN-E01局部例外、六处历史失败与SOURCE-E01 OPEN保持。
