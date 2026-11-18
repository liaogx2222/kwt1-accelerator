# E203 完整 SoC 联调工程

本工程验证完整 `e203_subsys_top`（核心、TCM、PPI/ICB、CLINT/PLIC、AON 和外设）、512 KiB 系统共享 SRAM、ICB 桥、整数 v1 / 8×8 / 20 私有宏加速器。测试模式显式使用 `FPGA_SOURCE`：E203 门控单元旁路，PLL 使用上游直通模型。该模式用于逻辑联调，不能作为 ASIC 门控、PLL、时序或功耗签核。

CPU 从 0x1000 的 1K×32 启动 ROM 执行固件，经 0x11000000 真实 sysper 访问加速器。平台只通过 host valid/ready 向共享 SRAM 供数；测试台不执行编码器算术、不替 CPU 装载加速器，也不注入输出。

| 地址 | 内容 |
|---|---|
| 0xa0000000 / +4 / +8 | 平台序号 / CPU 租约释放确认 / CPU 完成或错误标记 |
| 0xa0001000 | common，16,576 B |
| 0xa0020000 | 输入，6,336 B |
| 0xa0022000 | CPU 输出，6,336 B |
| 0xa0024000 | 单层租约，61,728 B；CRC/有效槽确认后才允许覆盖 |

任务序号按 16 递增，固件支持同一 CPU 对象连续冷任务。状态/供数轮询有有界预算，检测到硬件错误时 ABORT 并发布 0xbad00000；总线永久无响应仍需要平台 watchdog/整机复位，不能靠卡在 LW/SW 上的 CPU 自行恢复。

本机入口：`python scripts/run_soc_joint.py --output testdata/<fresh> --native --cases 0,1`；增加 `--crc-reject --reset-ln` 验证拒收与 LN 在途整机复位恢复。接口定向入口为 `--unit`。原生仿真为无延迟逻辑模型；`tb_soc_joint.sv` 提供 VCS 事件仿真交叉检查，含真实共享 SRAM 输出比较。

服务器新目录中的步骤：

```csh
python3 flow/project.py import-cpu /tmp/e203chk/e203_hbirdv2-master/rtl/e203
python3 flow/project.py import-accelerator /home/2026contest/server6/s6_43usr/Desktop/project/kwt_v2_ln_4dc49f7_20261111
python3 flow/project.py import-fixtures /home/2026contest/server6/s6_43usr/Desktop/project/server_signoff_20261106/keyword-transformer/deliverables/local_port_20261103/fixtures
python3 flow/project.py check
bash flow/run_vcs.sh 0
```

若 /tmp 副本不存在，可核对旧 `kwt1_chip/rtl/e203`；导入器会验证每个 CPU 文件的 LF 归一 SHA256，失败即停止。原厂 ROM 两文件不导入，唯一实际编译的 `sirv_mrom_top` 来自本工程，避免过去改错 ROM 文件的问题。归档用 `FPGA_SOURCE`，不修改厂商 CPU 源码。

最小传输包省略 CPU、加速器 RTL 和固定样本，通过上述三个只读导入命令在新目录补齐；不会修改正在综合的加速器工程。仅在 `SOC_PROJECT_VERIFIED` 后运行 VCS。完整包与最小包均由 `scripts/export_soc_joint.py` 生成，传输分段先验证 SHA256 再落盘，可重复执行。

共享 SRAM 使用同一同步单口宏合同，512 KiB 对应额外 64 个 4096×16 宏；加上加速器私有 20 宏为 84 宏，不包含 CPU TCM/ROM 的后续工艺绑定。完整面积台账必须分别列 CPU/外设/互连、TCM/ROM、私有存储、共享存储；另列按赛题口径计费的面积，不遗漏任何实际系统组成。功耗必须覆盖全部活动组件。当前 SoC 映射面积、150 MHz 时序、SoC 功耗和能耗均未测。

HF 功能刺激以 150 MHz 为换算假设，LF 为 32.768 kHz；原生模型使用相位累加产生 LF。供数每六个 HF 周期一个 32-bit 字，相当于假设 150 MHz 下 100 MB/s。主窗口从首个 host 写入请求开始，包含输入、13 包、实际 CPU 取指/调度/搬运、全部计算、输出写回，到 CPU 完成标记的共享 SRAM 响应消费。上电到 ID 可见的启动准备另计，报告读取尾段不混入窗口。
