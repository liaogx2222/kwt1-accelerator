# 独立服务器工程

由 `scripts/export_clean_project.py --output <全新目录>` 生成。只携带本版生产 RTL、固定样本和本目录流程，不携带 PDK、旧网表、旧 SAIF 或编译缓存。先运行本机回归并提交版本，再导出。

**2026-11-11 RET1N/复位分发候选。** RET1N含数字1，技术包装正常模式显式接1。原RETIN/九脚判断已被实际映射VCS错误纠正，当前使用十端口功能合同，接入异常即报错。DC新增SS/FF min-library关联、set_fix_hold和复位扇出锥32/0.400ns分发规则；原时钟/I/O/复位时序约束不放宽。候选须重新取得真实库/门级功能/三角时序，不继承旧网表结果。

服务器默认 csh。解包到一个新的工程目录后，在该目录执行：

```csh
python3 flow/project.py check
setenv KWT_PDK_ROOT /home/2026contest/server6/s6_43usr/Desktop/project/pdk_extract/SMIC40/S40/smic
setenv KWT_SRAM_DB_DIR /home/2026contest/server6/s6_43usr/Desktop/project/lib_smic40
python3 flow/project.py preflight
mkdir -p build
bash flow/run_sram_contract.sh
dc_shell -f flow/dc.tcl -output_log_file build/dc.log
bash flow/run_gate.sh 0
/eda/synopsys/prime/prime_2022.03-SP5-1/bin/pt_shell -f flow/pt.tcl > build/pt.log
```

`run_gate.sh` 显式通过 bash 执行，不需要改变默认登录 shell。一次运行一个 case，目录已存在时拒绝覆盖。先验收 case 0，再跑 1…11。编译启用 `-lca`，无 SDF 的功能仿真使用 `+notimingcheck +no_notifier`。门级 SRAM 使用明确的十端口RET1N正常模式功能合同；实际厂商模型先通过run_sram_contract验证。功能模型不等同于厂商宏时序模型，时序来自绑定的真实Liberty。

`preflight` 必须输出 `KWT_LIBRARY_PREFLIGHT_OK files=12`，确认两个环境变量以及三角共 12 个非空库文件存在；这不替代 DC/PT 对库内容的真实读取。DC/PT 用单个外层 Tcl catch 包住全流程，以防 DC 的 `-f` 读取器在顶层 error 后继续执行。缺变量或分析/链接/综合失败时返回失败状态；`attest-dc` 额外拒绝 GTECH/SELECT_OP 和非 20 宏的网表。

DC/PT 内的 Python 子进程经 `/usr/bin/env -u LD_LIBRARY_PATH -u LD_PRELOAD -u PYTHONHOME -u PYTHONPATH` 启动，避免继承工具私有库搜索设置。此处理不修改 DC/PT 自身环境。默认主机解释器为 `/usr/bin/python3`；可在启动工具前通过 `setenv KWT_HOST_PYTHON <已验证的绝对路径>` 指定。若日志出现 Python 动态符号查找失败，先核对主机解释器与干净子环境，保留失败日志后重跑。

启用功耗分析前，检查门级 `inputs.sha256` 与 PT 网表一致、SAIF 非空，并审查 `activity_tt.rpt` 的实际标注覆盖。再设置 `KWT_GATE_SAIF` 为该 case 的 SAIF 路径。PT 的功耗报告只对应加速器（含私有宏能被库建模的部分），不能填入 SoC 总功耗。CPU、互连、共享 SRAM 仍需集成后的同窗活动与库模型。

`constraints.sdc` 继承已登记的 pre-layout 假设，全部 max/min、未约束端点、覆盖和禁用弧需审查。没有 SPEF/CTS，不能把 setup 通过当作完整时序签核。DC 的 Total cell area 已包含宏，禁止再次叠加。20 个 4096×16 宏合计 160 KiB。

VNC 传输时只上传本工程源文件，禁止覆盖旧工程。可使用导出包旁的 `transfer/` 分段：每行命令把 zlib/base64 内容追加到独立文件，最后还原归档。每段均有 SHA256；在解包前核对归档的字节数和 SHA256，解包后再执行 `project.py check`。命令中的 `0/O`、`1/l/I`、下划线、负号和大小写必须由清晰截图核对。本文不要求 FTP 或 SSH。

使用源码小包时，在新的空目录接收分段，核对还原的 `source.tar.gz` 后执行 `tar xzf source.tar.gz`。固定输入可从旧工程按哈希导入：

```csh
python3 flow/project.py import-fixtures /home/2026contest/server6/s6_43usr/Desktop/project/server_signoff_20261106/keyword-transformer/deliverables/local_port_20261103/fixtures
```

这一步只复用已经冻结的输入数据；不会读取旧的 WORK、网表、SAIF 或工具缓存。导入前验证所有文件，目标同名文件哈希不一致时拒绝覆盖。源码包必须先落到一个全新的目录，避免混入历史分段文件。

当前包顶层为 `kwt1_mmio`，只是完整 SoC 的一个分区。`full_soc_area_mm2`、`soc_power_mW`、`soc_energy_uJ` 没有同配置证据时保持空值。新工程必须重新取得映射、门级冷任务、在途取消/复位恢复证据，原版结果仅作对照。

PT初次STA写build/pt；后续绑定新网表的SAIF时设置KWT_PT_RUN=pt_power1，保留初次时序报告。PT area_*.rpt保存report_qor，完成标记只表示流程完成，所有负路径和未测试项仍须审查。
