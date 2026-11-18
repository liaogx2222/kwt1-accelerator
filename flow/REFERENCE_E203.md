# E203 reference system: build, replay and migration

This is the supplied Hummingbirdv2 E203 at commit
`9f3e34f337f5d0a1236a285871ffa2032491617a`, with its Apache-2.0
license and upstream source headers retained. The upstream CPU is unchanged.
Actual RV32 machine code executes the current `rtl/integration/driver/kwt1.c`
against the frozen `rtl/v2/kwt1_mmio.sv`. The host does not call the driver or
calculate encoder results for the device. Expected outputs stay in the host
scoreboard. No ISS is used.

## Build and full-project independent check

From the full `keyword-transformer` project, with Python 3.10+:

```text
python scripts/validate_reference_system.py --stage all --output testdata/reference_e203/new_run
```

The entry builds the ELF, map, raw image and shared model, then launches three
four-class groups and one fault/recovery group. Each group has its own CPU/model
and 512 KiB RAM. Within a group the same objects execute consecutive jobs without
recreation. Four processes shorten host runtime without changing simulated
cycles. The independent gate rederives all 12 outputs from frozen integer
parameters and Validation inputs, checks saved integer outputs, then compares
88,704 observed codes (76,032 class codes plus 12,672 recovery codes).

Use `--stage build`, `run` or `check` to separate expensive work. The checker
needs the original project's NumPy integer reference/inputs; build and CPU replay
use Python's standard library only. A new output directory is required for
published evidence. Old integration/generic gate regressions are checked by
hash, not rerun on each edit.

Set `KWT_E203_REPO` if the supplied CPU checkout is not the sibling
`e203_hbirdv2` directory. Tools are discovered from PATH or environment:
`KWT_RISCV_GCC`, `KWT_VERILATOR`, `VERILATOR_ROOT`, `KWT_CXX`,
`KWT_IVERILOG`, `KWT_VVP` and `KWT_YOSYS`. An explicit `--tools` JSON
configuration is supported; `flow/tools.example.json` illustrates the keys.
Windows local fallbacks are convenience paths and are not Linux requirements.
The recorded tool versions/hashes describe the tested Windows environment;
Linux execution remains pending until actually performed.

## Standalone exported package

The exporter includes upstream CPU sources/license, production RTL, current
driver, startup/linker/firmware, reference adapter, scripts, 13 packet fixtures,
12 class fixtures, firmware images/maps, observed outputs and provenance.
It excludes training/audio data, executable host tools and foundry libraries.

```text
python scripts/export_reference_system.py --evidence testdata/reference_e203/parallel_20261103 --output deliverables/e203_reference_20261103
```

From that exported directory:

```text
python scripts/reference_package.py --stage verify
python scripts/reference_package.py --stage all --output runs/new_replay
```

The package entry sets the CPU source path and rebuilds/reruns the reference.
Its standalone check compares against manifest-bound frozen host goldens. The
original full-project independent integer recomputation is archived in
`evidence/verification.json`; it is not falsely claimed to run without the
original integer dataset. The copied original evidence/source manifests retain
their original bytes and describe the full-project release; the package's
outer `manifest.json` is authoritative for the files actually included.

## Memory, bus and timing contract

| Region | Address / reservation | Ownership |
|---|---|---|
| Firmware/static | `0xa0000000`, below `0xa0020000` | CPU startup, code and small data |
| Input | `0xa0020000`, 6336 B | host writes; CPU reads |
| Output | `0xa0022000`, 6336 B | CPU writes; host checks after driver return |
| One packet staging | `0xa0024000`, max 61728 B | host writes before acquire succeeds; CPU reads until release |
| Stack | `0xa007c000..0xa0080000`, 16 KiB | CPU, monitored SP bounds/high-water |
| Accelerator MMIO | `0x10000000` | PPI ICB through reference adapter |
| Host mailbox | `0x10010000` | platform provider, fault sideband and result reporting |

The whole external RAM is 512 KiB. The linker asserts no image/input/packet/stack
overlap. CPU stores into code, input or packet staging are rejected by the host
memory model. Source supplies input/packet words every six reference clocks,
plus 1024 initial clocks per packet. Host writes arbitrate ahead of CPU memory
commands on a single RAM port. No complete 13-packet set is placed in target RAM.
After release, packet staging is poisoned; the next layer must acquire anew.

E203 uses its original configuration, `FPGA_SOURCE` clock implementation,
external system-memory boot and single-outstanding 32-bit ICB endpoints.
The configured 64 KiB ITCM and 64 KiB DTCM remain in the CPU RTL but are unused;
they are not counted as available shared RAM and no area claim removes them.
Instruction/data fetches traverse the external memory interface. Command
acceptance produces a response on the next simulated clock, with ready/valid
backpressure and shared-port host contention. This reference is intentionally
identified; the final SoC's memory latencies, cache/TCM usage and arbitration
must replace these assumptions.

The ICB adapter converts a peripheral failure into a mailbox sideband return
code read by the firmware callbacks; CPU `rsp_err` is tied low. This is a
reference callback policy, not final E203 trap/error semantics. Its timeout
threshold 64 expires after 65 stalled sampling edges. Sustained response hold
also blocks recovery ABORT, forcing RESET_REQUIRED isolation. The CPU verifies
that public run/abort APIs reject quarantined use, requests accelerator-only
hard reset and confirms STATUS/ID before the next full cold task. The CPU and
shared RAM are not recreated for this recovery.

Global `rst_n` resets CPU/adapter/accelerator. Host accelerator reset preserves
the host mailbox response, and accelerator SRAM data are not cleared. IRQ is
wired to E203 `ext_irq_a`; firmware polls and does not enable interrupt service.
Interrupt-service functionality is therefore not claimed.

The outer clock window starts before the first source input word and ends at
the firmware's driver-return marker, after all packet loads, computation,
output stores and done acknowledgement. Firmware `mcycle/minstret` deltas cover
the driver call; a separate RTL retirement monitor also counts instructions.
CPU RAM read/write transactions and accelerator task/compute counters are
separate. After the last completion mailbox write, 32 clocks drain its response.
These are actual cycles of this E203 RTL reference, not timing of the designated
competition SoC or evidence that any implementation meets 150 MHz.

## Local stages and technology boundary

```text
python scripts/run_local_flow.py --stage lint --output runs/local/lint
python scripts/run_local_flow.py --stage unit --output runs/local/unit
python scripts/run_local_flow.py --stage protocol --output runs/local/protocol
python scripts/run_local_flow.py --stage synth --output runs/local/synth
python scripts/run_local_flow.py --stage check --output runs/local --encoder testdata/reference_e203/new_run
python scripts/check_technology.py --config flow/targets/smic40.binding.pending.json
```

The aggregate check in the full project requires all five stages including
encoder; absent stages return nonzero. The standalone package uses
`reference_package.py --stage check` for its encoder gate. Native Yosys supports
external output paths; YoWASP outputs must remain beneath the project's mapped
working directory. SRAM synthesis defines `KWT_TECH_SRAM` and checks exactly
20 external 4096x16 boundaries with no residual behavioral memories.

The SMIC40 template intentionally fails with exit 2 until authorized library,
PVT, pin/units/area data and all I/O/reset/clock constraints are bound. Directed
negative tests reject wrong top, missing macro, changed macro latency, missing
port constraints, blanket exceptions and source drift. Tcl files are binding
skeletons, not mapped synthesis/STA results. No SMIC40 area, timing or energy
signoff is present.

## Differences requiring final platform acceptance

| Reference choice | Final platform work |
|---|---|
| Supplied public E203 commit/configuration | confirm designated SoC/configuration and license/source revision |
| External boot `0xa0000000`, unused TCM | official boot map, image placement and actual memory timing |
| PPI ICB and sideband callback errors | actual bus adapter, ordering, error/trap and bounded timeout policy |
| Host mailbox/provider, six-clock word supply | organizer loader protocol, bandwidth, ownership and cancellation |
| Accelerator-only host reset | designated reset domain, isolation and cancellation of pending transactions |
| IRQ connected, polling firmware | interrupt number/polarity and separate ISR validation if used |
| Functional synchronous SRAM | authorized macro pin mapping, read/hold/write semantics and timing model |
| Reference cycle/instruction ledger | official timing boundary, measured platform cycles and same-netlist power |

Freeze remains 8x8, 20 macros, INTEGER_NUMERICS_V1. The first actual-machine-code
measurement is about 88.82 million outer clocks, far above the internal nine
million target for this configuration. Profile software and instruction/data
movement before considering any arithmetic/array changes. Final 150 MHz,
2.25 mm2 and energy acceptance still require the actual library/platform.
LN-E01 remains the approved local quality exception; SOURCE-E01 remains OPEN.
