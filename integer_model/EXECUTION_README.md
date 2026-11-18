# R1/R2 执行模型

冻结整数golden见同目录历史`README.md`；本文件对应新增的值驱动调度、真实参数包、暂存分析和算术RTL功能验证。数值profile仍为INTEGER_NUMERICS_V1。

工作目录为`keyword-transformer`，CPython 3.10.9、NumPy 1.26.2，锁见`requirements-r1r2.lock`。RTL验证另需Icarus 12.0；工具脚本支持明确指定路径，不要求安装新依赖。

```powershell
# 使用新目录完整复现；已有发布证据不要原地覆盖。
python scripts/run_r1r2_evidence.py --stage all --output testdata/r1r2/reproduce
# 相同算术和时钟，生存期改为磁盘区间+周期数组扫描：
python scripts/run_r1r2_low_memory.py --stage all --output testdata/r1r2/reproduce_compact
# 检查已有完整证据并生成hash清单：
python scripts/run_r1r2_evidence.py --stage check --output testdata/r1r2/release
```

可用`--stage`拆分snapshot、unit、baseline、full_boundary、stream、packet_baseline、cache、gelu2、gelu8、packet_optimized、rtl、audit、check。完整复现需要执行全部阶段；独立首末层优化不等于组合连续12层。

- `event_arithmetic.py`：issue/ready、实际退休结果、数据依赖、位宽和生存期。
- `executable_layer.py`：全部计算使用事件结果和实际SRAM读值，golden只做外部断言。旧银行模型的固定4096属性不参与新验收。
- `execution_banks.py`：四个权重逻辑银行（各两个宏扩深）及A/B/C/E，共20个物理单口宏的保守调度；支持真实A槽地址切换。
- `packet_stream.py`：13个既有包、32-bit valid/ready、8项写队列、在线固定profile检查与CRC；SHA在主机离线检查。
- `register_contract.py`：显式396B控制/接口常驻布局，另加实测数据/在途峰值；不把未实现的整机RTL当已测面积。
- `rtl/micro`：共享宽算术单请求功能微原型，不能用它宣称II=1或150MHz已通过。

当前验收结果在`testdata/r1r2/release/verification.json`；详细范围、周期假设及限制见`docs/architecture/R1_R2_EXECUTION_REPORT.md`。SOURCE-E01继续开放，没有新历史线索不再重建旧训练来源。
