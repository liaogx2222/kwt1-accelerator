# 任务边界、流水、融合与单层功能RTL（2026-10-21）

固定数值仍为INTEGER_NUMERICS_V1，参数和runtime.py保持原hash。新证据写入
`testdata/next_stage_v1`，不覆盖`testdata/r1r2/release`。

在keyword-transformer目录，用发布解释器CPython3.10.9、NumPy1.26.2运行：

完整顺序复现：`& D:/anaconda/python.exe scripts/validate_next_stage.py --stage all --output testdata/next_stage_replay`。
全流程拒绝覆盖已通过的发布目录，重复复现时选择新的output。
分阶段复现如下：

```powershell
& D:/anaconda/python.exe scripts/validate_next_stage.py --stage reset
& D:/anaconda/python.exe scripts/validate_next_stage.py --stage io --output testdata/next_stage_v1/io_final
& D:/anaconda/python.exe scripts/validate_next_stage.py --stage pipeline --output testdata/next_stage_v1/pipeline_final
& D:/anaconda/python.exe scripts/validate_next_stage.py --stage cold --output testdata/next_stage_v1/cold_fixed
& D:/anaconda/python.exe scripts/validate_next_stage.py --stage schedule --output testdata/next_stage_v1/fused
& D:/anaconda/python.exe scripts/validate_next_stage.py --stage banks --output testdata/next_stage_v1/banks_final
& D:/anaconda/python.exe scripts/validate_next_stage.py --stage cold --fused --output testdata/next_stage_v1/cold_fused
& D:/anaconda/python.exe scripts/validate_next_stage.py --stage audit
& D:/anaconda/python.exe scripts/validate_next_stage.py --stage layer --output testdata/next_stage_v1/layer_final
& D:/anaconda/python.exe scripts/validate_next_stage.py --stage control --output testdata/next_stage_v1/control_final
& D:/anaconda/python.exe scripts/validate_next_stage.py --stage check
```

`--quick`只供调试；check拒绝quick或缺项。长测试逐层或逐例写检查点，未写最终
summary不代表通过。Icarus/vvp默认使用本机RISCV_CPU/tools/iverilog/bin，锁定文件
及SHA随验收保存。`--stage layer`覆盖12个profile/class配对；若需144组合，直接运行
`scripts/validate_layer_rtl.py --matrix --output <新目录>`，不将12例报告为144例。

PacketStream.reset同时取消帧完成谓词、FIFO、所有有效位、层序和A物理映射。SRAM
保持脏内容。TaskBanks租约和SystemIO任务epoch禁止旧任务在reset后消费结果、写银行
或继续外部传输。冷任务复用同一PacketStream与ExecutionBanks，每次全部重新装13包。

SystemIO窗口从common第一段传输前到最终主机写回应答，参数757312B，输入/输出各
6336B。三段32bit链路串行收费；外部两段和CPU为显式延迟模型，设备端是真实握手、CRC
和SRAM。每段beat间隔600/MBps拍，CPU每word4拍+每frame500拍，最终ack1拍。
这不是指定平台总线实测，不隐藏免费输入或最终写回。

mul_pipe是真实3级部分积流水，RNE1级，RQ串接4级，II1；elastic ready允许填充空槽，
backpressure保持结果/tag。迭代div64/sqrt32共用服务器，首步在接收边沿执行，响应
消费时可接受下一请求；与模型延迟对齐。未把迭代单元宣称为II1。

FusedLayer保持8×8 PE、一个宽乘法lane、一个RNE和ALU；依赖图每unit每拍最多发射
一条，结果仍在退休时计算。Dense bias从真实系数读入PE初值；RQ跨独立lane交错，
Softmax常量移位融合，LN保持原RNE次数/位置。显式保留全部固定流水/迭代寄存器，
`register_assessment.json`覆盖早期只计在途状态的预算，动态lifetimes不改写。

kwt_layer.sv直接接收真实common/layer包和输入，包头与固定profile ROM比较、滚动
CRC校验；实际整数Dense/QK/Softmax/PV/O/残差/LN/FC/GELU产生输出。TB的expected
文件只用于scoreboard，DUT不读取答案。Dense为8×8阵列，Attention按单查询行控制。
它使用行为多阵列内存；20单口宏映射、端口仲裁、整层周期与融合模型等价、SoC及
指定库PPA仍是后续工作。不能拿该功能原型的周期替代银行调度模型的性能数字。
