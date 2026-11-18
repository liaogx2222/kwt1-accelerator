# -*- coding: utf-8 -*-
# bootstrap_kwt1_chip.py -- create the normalised delivery tree for kwt1
# Runs on RServer06 (python3.6). Idempotent: safe to re-run.
import os, io, shutil

ROOT = "/home/2026contest/server6/s6_43usr/Desktop/project"
REPO = ROOT + "/server_signoff_20261106/keyword-transformer"
OUT  = ROOT + "/out"
DST  = ROOT + "/kwt1_chip"
PDK  = ROOT + "/pdk_extract/SMIC40/S40/smic"
LIBD = ROOT + "/lib_smic40"

def mk(d):
    p = os.path.join(DST, d)
    if not os.path.isdir(p):
        os.makedirs(p)

def cp(src, dst):
    t = os.path.join(DST, dst)
    if not os.path.isfile(src):
        print("MISS %s" % src)
        return False
    shutil.copy2(src, t)
    print("C %9d %s" % (os.path.getsize(t), dst))
    return True

def wr(dst, text):
    t = os.path.join(DST, dst)
    with io.open(t, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("W %9d %s" % (len(text.encode("utf-8")), dst))

# ---------------------------------------------------------------- directories
for d in ["rtl/accel", "rtl/accel/generated", "rtl/accel/tech/smic40",
          "rtl/soc", "tb", "sim", "sim/gate",
          "syn/accel/main", "syn/accel/script", "syn/accel/lib",
          "syn/accel/db", "syn/accel/log", "syn/accel/mapped",
          "syn/accel/netlist", "syn/accel/report", "syn/accel/work",
          "syn/soc", "sta", "sta/report", "wave", "doc", "scripts"]:
    mk(d)

# ---------------------------------------------------------------- RTL sources
RTL = [
    ("rtl/micro/mul_pipe.sv",                         "rtl/accel/mul_pipe.sv"),
    ("rtl/micro/rne_pipe.sv",                         "rtl/accel/rne_pipe.sv"),
    ("rtl/v2/kwt_sram_sp.sv",                         "rtl/accel/kwt_sram_sp.sv"),
    ("rtl/v2/kwt_mac8x8.sv",                          "rtl/accel/kwt_mac8x8.sv"),
    ("rtl/v2/kwt_iterative.sv",                       "rtl/accel/kwt_iterative.sv"),
    ("rtl/v2/kwt_math.sv",                            "rtl/accel/kwt_math.sv"),
    ("rtl/v2/kwt_packet_loader.sv",                   "rtl/accel/kwt_packet_loader.sv"),
    ("rtl/v2/kwt_layer_banked.sv",                    "rtl/accel/kwt_layer_banked.sv"),
    ("rtl/v2/kwt1_accel.sv",                          "rtl/accel/kwt1_accel.sv"),
    ("rtl/v2/kwt1_mmio.sv",                           "rtl/accel/kwt1_mmio.sv"),
    ("rtl/v2/generated/kwt_profile.svh",              "rtl/accel/generated/kwt_profile.svh"),
    ("rtl/integration/smic40/kwt_tech_sram_4096x16.sv","rtl/accel/tech/smic40/kwt_tech_sram_4096x16.sv"),
]
for s, d in RTL:
    cp(REPO + "/" + s, d)

cp(OUT + "/gate_sim/tb_gate_tasks_v5.sv", "tb/tb_gate_tasks.sv")
cp(REPO + "/flow/targets/smic40.server.sdc", "syn/accel/script/constraints.sdc")
cp(OUT + "/dc_synth8/mapped.v", "syn/accel/netlist/kwt1_mmio.v")
cp(OUT + "/gate_sim/ramsp_a5a5.v", "sim/gate/ramsp4096x16.v")

# ---------------------------------------------------------------- lib symlinks
LIBS = [
    (PDK + "/SCC40NLL_VHSC40_HVT_V0.1/SCC40NLL_VHSC40_HVT_V0p1/liberty/1.1v/scc40nll_vhsc40_hvt_ss_v0p99_125c_basic.db",
     "syn/accel/lib/scc40_hvt_ss.db"),
    (PDK + "/SCC40NLL_VHSC40_LVT_V0.1/SCC40NLL_VHSC40_LVT_V0p1/liberty/1.1v/scc40nll_vhsc40_lvt_ss_v0p99_125c_basic.db",
     "syn/accel/lib/scc40_lvt_ss.db"),
    (PDK + "/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/liberty/1.1v/scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db",
     "syn/accel/lib/scc40_rvt_ss.db"),
    (LIBD + "/RAMSP4096X16_ss_0p99v_0p99v_125c.db",
     "syn/accel/lib/ramsp4096x16_ss.db"),
]
for src, dst in LIBS:
    t = os.path.join(DST, dst)
    if os.path.islink(t) or os.path.isfile(t):
        os.remove(t)
    if os.path.isfile(src):
        os.symlink(src, t)
        print("L %s -> %s" % (dst, src))
    else:
        print("MISS_LIB %s" % src)

# ---------------------------------------------------------------- sim filelists
wr("sim/filelist.f", """// kwt1_mmio RTL simulation (behavioural SRAM, no vendor macro)
// order: include dir -> leaves -> top -> testbench
+incdir+../rtl/accel/generated
+define+KWT_SIM
../rtl/accel/mul_pipe.sv
../rtl/accel/rne_pipe.sv
../rtl/accel/kwt_sram_sp.sv
../rtl/accel/kwt_mac8x8.sv
../rtl/accel/kwt_iterative.sv
../rtl/accel/kwt_math.sv
../rtl/accel/kwt_packet_loader.sv
../rtl/accel/kwt_layer_banked.sv
../rtl/accel/kwt1_accel.sv
../rtl/accel/kwt1_mmio.sv
../tb/tb_gate_tasks.sv
""")

wr("sim/run.sh", """#!/bin/bash
# RTL simulation. Sim time for one full task is minutes, not hours.
set -e
cd "$(dirname "$0")"
vcs -full64 -sverilog +v2k -timescale=1ns/1ps -error+50 \\
    +notimingcheck +no_notifier \\
    -f filelist.f -o simv_rtl
./simv_rtl "$@"
""")

wr("sim/gate/filelist.f", """// kwt1_mmio gate-level simulation
// standard-cell models + vendor SRAM model + mapped netlist + tb
+define+INITIALIZE_MEMORY
/home/2026contest/server6/s6_43usr/Desktop/project/pdk_extract/SMIC40/S40/smic/SCC40NLL_VHSC40_HVT_V0.1/SCC40NLL_VHSC40_HVT_V0p1/verilog/scc40nll_vhsc40_hvt.v
/home/2026contest/server6/s6_43usr/Desktop/project/pdk_extract/SMIC40/S40/smic/SCC40NLL_VHSC40_LVT_V0.1/SCC40NLL_VHSC40_LVT_V0p1/verilog/scc40nll_vhsc40_lvt.v
/home/2026contest/server6/s6_43usr/Desktop/project/pdk_extract/SMIC40/S40/smic/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/verilog/scc40nll_vhsc40_rvt.v
../ramsp4096x16.v
../../syn/accel/netlist/kwt1_mmio.v
../../tb/tb_gate_tasks.sv
""")

wr("sim/gate/run_gate.sh", """#!/bin/bash
# Gate-level run. +notimingcheck +no_notifier are MANDATORY:
# without SDF the specify blocks fire on every clock edge and the cell
# notifiers drive X onto the outputs (looks exactly like an RTL bug).
set -e
cd "$(dirname "$0")"
vcs -full64 -sverilog +v2k -timescale=1ns/1ps -error+50 \\
    +notimingcheck +no_notifier +define+INITIALIZE_MEMORY \\
    -f filelist.f -o simv_gate
./simv_gate "$@"
""")

# ---------------------------------------------------------------- DC scripts
wr("syn/accel/script/setup_lib.tcl", """# setup_lib.tcl -- target/link library and search path for SMIC40 ss corner
# Called from main/syn_top.tcl. Absolute paths: the symlinks in ../lib are
# for human browsing, not for the tool (DC resolves them but a broken link
# would silently drop a library, so we point at the real files).

set PDK  /home/2026contest/server6/s6_43usr/Desktop/project/pdk_extract/SMIC40/S40/smic
set LIBD /home/2026contest/server6/s6_43usr/Desktop/project/lib_smic40

set target_library [list \\
  $PDK/SCC40NLL_VHSC40_HVT_V0.1/SCC40NLL_VHSC40_HVT_V0p1/liberty/1.1v/scc40nll_vhsc40_hvt_ss_v0p99_125c_basic.db \\
  $PDK/SCC40NLL_VHSC40_LVT_V0.1/SCC40NLL_VHSC40_LVT_V0p1/liberty/1.1v/scc40nll_vhsc40_lvt_ss_v0p99_125c_basic.db \\
  $PDK/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/liberty/1.1v/scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db \\
  $LIBD/RAMSP4096X16_ss_0p99v_0p99v_125c.db]

set link_library [concat "*" $target_library]
puts "SETUP_LIB target=[llength $target_library] link=[llength $link_library]"
""")

wr("syn/accel/main/syn_top.tcl", """# =============================================================================
# syn_top.tcl -- kwt1_mmio synthesis, SMIC40 ss_0p99v_125c, 150 MHz
# -----------------------------------------------------------------------------
# Derived from out/dc_synth8.tcl (the netlist that signed off: 0.965 mm2,
# PT ss-corner setup 0 violations, gate case 0 mismatches=0/1584).
#
# INVOKE (from kwt1_chip/syn/accel):
#   dc_shell -f main/syn_top.tcl -output_log_file log/dc_shell.log
#
# TWO GUARDS, both fatal by design:
#   1. exactly 20 RAMSP4096X16 macro instances after link
#   2. zero GTECH / SELECT_OP cells after compile_ultra
# A netlist that fails either is not a signoff netlist -- dc_synth7 proved it.
# =============================================================================
set_app_var sh_enable_page_mode false

set HERE   [file dirname [file normalize [info script]]]
set SYN    [file dirname $HERE]
set ROOT   [file dirname [file dirname $SYN]]
set RTL    $ROOT/rtl/accel
set TOP    kwt1_mmio

source $SYN/script/setup_lib.tcl
set search_path [concat [list . $RTL $RTL/generated] $search_path]

foreach d {db log mapped netlist report work} {
    file mkdir $SYN/$d
}
define_design_lib WORK -path $SYN/work

set rtl_files [list \\
    $RTL/tech/smic40/kwt_tech_sram_4096x16.sv \\
    $RTL/mul_pipe.sv \\
    $RTL/rne_pipe.sv \\
    $RTL/kwt_sram_sp.sv \\
    $RTL/kwt_mac8x8.sv \\
    $RTL/kwt_iterative.sv \\
    $RTL/kwt_math.sv \\
    $RTL/kwt_packet_loader.sv \\
    $RTL/kwt_layer_banked.sv \\
    $RTL/kwt1_accel.sv \\
    $RTL/kwt1_mmio.sv]
foreach f $rtl_files { if {![file isfile $f]} { error "RTL source not found: $f" } }

analyze -format sverilog -define KWT_TECH_SRAM -lib WORK $rtl_files
elaborate $TOP -lib WORK
current_design $TOP
link

# ---- guard 1: macro binding ------------------------------------------------
set macro_cells [get_cells -hierarchical -filter "ref_name =~ *RAMSP4096X16*" -quiet]
set macro_count [sizeof_collection $macro_cells]
puts "KWT_MACRO_INSTANCES $macro_count"
if {$macro_count != 20} {
    error "expected exactly 20 SRAM macro instances, found $macro_count"
}
# ONLY the macro instances are dont_touch. Never the wrapper design:
# that is what left dc_synth7 with GTECH cells inside macro_cell.
set_dont_touch $macro_cells

read_sdc $SYN/script/constraints.sdc
redirect -file $SYN/report/check_design.rpt { check_design -summary }

compile_ultra -no_autoungroup

# ---- guard 2: no generic logic may survive ---------------------------------
set n_gtech [sizeof_collection [get_cells -hierarchical -filter "ref_name =~ GTECH*" -quiet]]
set n_sel   [sizeof_collection [get_cells -hierarchical -filter "ref_name =~ SELECT_OP*" -quiet]]
puts "KWT_GTECH_CELLS $n_gtech"
puts "KWT_SELECT_OP_CELLS $n_sel"
if {$n_gtech != 0 || $n_sel != 0} {
    error "unmapped generic logic survived ($n_gtech GTECH + $n_sel SELECT_OP); netlist is not signoff quality"
}

redirect -file $SYN/report/area.rpt         { report_area -hierarchy }
redirect -file $SYN/report/cell.rpt         { report_cell -nosplit }
redirect -file $SYN/report/timing_setup.rpt { report_timing -delay_type max -max_paths 20 -nworst 1 -nosplit }
redirect -file $SYN/report/timing_hold.rpt  { report_timing -delay_type min -max_paths 20 -nworst 1 -nosplit }
redirect -file $SYN/report/constraints.rpt  { report_constraint -all_violators -verbose }

change_names -rules verilog -hierarchy
write -format ddc     -hierarchy -output $SYN/db/kwt1_mmio.ddc
write -format verilog -hierarchy -output $SYN/netlist/kwt1_mmio.v
if {[catch {write_sdc -nosplit -output $SYN/mapped/kwt1_mmio.sdc} msg]} {
    write_sdc -nosplit $SYN/mapped/kwt1_mmio.sdc
}

set mapped_macro [sizeof_collection [get_cells -hierarchical -filter "ref_name =~ *RAMSP4096X16*" -quiet]]
puts "KWT_MAPPED_MACRO_INSTANCES $mapped_macro"
if {$mapped_macro != 20} {
    error "mapped netlist lost SRAM macro instances; area/timing invalid"
}
puts "KWT_SYN_FINISHED"
exit
""")

wr("syn/accel/.synopsys_dc.setup", """# Read automatically when dc_shell starts in this directory.
source [file join [file dirname [info script]] script setup_lib.tcl]
set search_path [concat [list . ../../rtl/accel ../../rtl/accel/generated] $search_path]
""")

wr(".synopsys_dc.setup", """# Project-root copy. dc_shell only reads the setup file from its START
# directory (or $HOME), so the effective one for synthesis is
# syn/accel/.synopsys_dc.setup -- start dc_shell there.
source [file join [file dirname [file normalize [info script]]] syn accel script setup_lib.tcl]
""")

# ---------------------------------------------------------------- PT script
# Preferred source: the kwt1_chip edition, which already resolves every path
# from its own location. The pt_signoff8 rewrite below is the fallback for
# checkouts that predate that file.
src_pt = REPO + "/flow/smic40/pt_signoff_kwt1_chip.tcl"
if os.path.isfile(src_pt):
    cp(src_pt, "sta/pt_signoff.tcl")
else:
    src_pt = REPO + "/flow/smic40/pt_signoff8.tcl"
if os.path.isfile(src_pt) and not os.path.isfile(os.path.join(DST, "sta/pt_signoff.tcl")):
    with io.open(src_pt, "r", encoding="utf-8") as f:
        t = f.read()
    t = t.replace(
        "set NETLIST /home/2026contest/server6/s6_43usr/Desktop/project/out/dc_synth8/mapped.v",
        "set ROOT [file dirname [file dirname [file normalize [info script]]]]\nset NETLIST $ROOT/syn/accel/netlist/kwt1_mmio.v")
    t = t.replace(
        "set SDC     /home/2026contest/server6/s6_43usr/Desktop/project/server_signoff_20261106/keyword-transformer/flow/targets/smic40.server.sdc",
        "set SDC     $ROOT/syn/accel/script/constraints.sdc")
    t = t.replace(
        "set SAIF    /home/2026contest/server6/s6_43usr/Desktop/project/out/gate_sim/kwt1_gate_c0.saif",
        "set SAIF    $ROOT/sim/gate/kwt1_gate_c0.saif")
    t = t.replace(
        "set OUT     /home/2026contest/server6/s6_43usr/Desktop/project/out/pt_signoff8",
        "set OUT     $ROOT/sta/report")
    t = t.replace(
        "set PDK     /home/2026contest/server6/s6_43usr/Desktop/project/pdk_extract/SMIC40/S40/smic",
        "set PDK     /home/2026contest/server6/s6_43usr/Desktop/project/pdk_extract/SMIC40/S40/smic")
    t = t.replace("read_saif $SAIF -strip_path tb_gate_tasks/dut",
                  "read_saif $SAIF -strip_path tb_gate_tasks/dut")
    wr("sta/pt_signoff.tcl", t)
else:
    print("MISS_PT %s" % src_pt)

# ---------------------------------------------------------------- README
wr("README.md", u"""# kwt1_chip

keyword-transformer 加速器（KWT-1）的规范化工程目录。SMIC 40nm LL，
150 MHz，12 层 encoder，单任务 6,141,048 拍 / 40.94 ms。

## 两个顶层，别混

| 顶层 | 位置 | 状态 |
|---|---|---|
| `kwt1_mmio` | `rtl/accel/` | **签核基线**。面积 0.965 mm²、PT ss 角 setup 0 违例、门级 12 用例 `mismatches=0 of 1584` |
| `soc_top` | `rtl/soc/` | **待集成**。赛题要求接入 E203（原文第 25、146–148 行），见 `doc/INTEGRATION_TODO.md` |

赛题的面积上限 2.25 mm² 是对**加速器**说的，所以 `rtl/accel` 的 0.965 mm²
可以直接作为合规证据；SoC 顶层只影响“集成 20 分”。

## 目录

```
rtl/accel/          可综合 RTL（kwt1_mmio 为顶层）
  tech/smic40/      SRAM 宏 wrapper（kwt_tech_sram_4096x16）
  generated/        kwt_profile.svh（`include，必须最先可见）
rtl/soc/            SoC 集成层，当前为空
tb/                 tb_gate_tasks.sv（v5，支持 +CASE=n）
sim/                RTL 仿真：filelist.f + run.sh
sim/gate/           门级仿真：标准单元模型 + 厂商 SRAM 模型 + 网表
syn/accel/          DC 综合
  main/syn_top.tcl  主流程
  script/setup_lib.tcl / constraints.sdc
  lib/              4 个 .db 软链接（ss 角，仅供浏览）
  db/ log/ mapped/ netlist/ report/ work/
sta/                PT 三 corner STA + 功耗（pt_signoff.tcl）
wave/               波形（.fsdb/.vpd，默认不产生）
doc/                集成待办与说明
```

## 怎么跑

**RTL 仿真**（分钟级）：
```csh
cd kwt1_chip/sim ; ./run.sh +CASE=0
```

**门级仿真**（单 case 约 2.1 小时，6.14M 周期）：
```csh
cd kwt1_chip/sim/gate ; ./run_gate.sh +CASE=0
```
`+notimingcheck +no_notifier` 是**必须**的：没有 SDF 时时序检查每个沿都违例，
厂商单元的 notifier 会把输出打成 X，症状和 RTL bug 一模一样。

**综合**：
```csh
cd kwt1_chip/syn/accel ; dc_shell -f main/syn_top.tcl -output_log_file log/dc_shell.log
```
两道 fatal 守卫：宏实例 = 20、`GTECH|SELECT_OP` = 0。

**STA + 功耗**：
```csh
cd kwt1_chip/sta ; pt_shell -f pt_signoff.tcl -output_log_file pt.log
```
功耗只在 tt corner、且 `sim/gate/kwt1_gate_c0.saif` 存在时才出。

## 与 keyword-transformer 的关系

本目录是从 `keyword-transformer/rtl/v2` + `flow/smic40` 复制出来的**交付视图**，
不是真源。RTL 改动仍应在 `keyword-transformer/rtl/v2` 做，然后重新跑
`flow/smic40/bootstrap_kwt1_chip.py` 同步。真源与交付视图不一致时，以真源为准。
""")

wr("doc/INTEGRATION_TODO.md", u"""# SoC 集成待办（集成 20 分）

## 赛题原文要求

- 第 25 行：完成加速器的 **SoC 集成、驱动开发与功能验证**
- 第 146–148 行：将第 1—2 项设计**接入 E203**，完成驱动、数据交换、
  启动与完成状态管理，并**通过 SoC 仿真验证**

## 现状

| 项 | 状态 |
|---|---|
| 加速器 RTL（`kwt1_mmio`） | 完成，签核基线 |
| MMIO 寄存器接口 | 完成（req/resp 四相握手 + status/done/err） |
| ICB 从设备 wrapper | **未做**。`kwt1_mmio` 现在是自定义 req/resp，不是 ICB |
| E203 侧接入 | **未做** |
| 驱动（`kwt1.c`） | 已有参考实现，跑在 RTL 仿真里，未在 E203 上跑 |
| SoC 级仿真 | **未做** |

## 待做清单（按依赖顺序）

1. **ICB 从设备 wrapper**：把 `req_valid/req_ready/req_write/req_addr/req_wdata/`
   `req_wstrb/resp_valid/resp_ready/resp_rdata/resp_error` 映射到 E203 的 ICB 协议
   （`icb_cmd_*` / `icb_rsp_*`）。地址译码给 `kwt1_mmio` 一个基址。
2. **SoC 顶层**：`rtl/soc/soc_top.sv`，例化 E203 子系统 + wrapper + 加速器，
   时钟复位统一，中断接入 E203 的 `irq`。
3. **地址映射文档**：`doc/ADDRESS_MAP.md`，写清 0x00/0x04/0x08/0x0C/0x10/0x14/0x18/0x1C/0x20/0x24
   各寄存器的偏移与语义。
4. **SoC 仿真**：E203 跑 `kwt1.c`，走 ICB 写参数、start、轮询 done、读 1584 输出，
   比对 expected。
5. **SoC 级综合**（可选）：面积会远超 2.25 mm²，赛题的面积上限只针对加速器，
   所以 SoC 级综合只作为集成完成度的证据，不参与面积评分。

## 风险

- E203 的 ICB 时序与 `kwt1_mmio` 的四相握手不是一一对应，wrapper 里要处理
  命令/响应的流水与背压；建议先写一个 `tb_icb_bridge.sv` 单独验证 wrapper。
- E203 参考工程在 `e203_hbirdv2/`，其仿真环境（Verilator/VCS）需要先跑通一次
  hello world，再挂加速器。
""")

# ---------------------------------------------------------------- status
n_files = 0
n_bytes = 0
for base, dirs, files in os.walk(DST):
    for fn in files:
        p = os.path.join(base, fn)
        n_files += 1
        try:
            n_bytes += os.path.getsize(p)
        except OSError:
            pass
print("DONE files=%d bytes=%d" % (n_files, n_bytes))
