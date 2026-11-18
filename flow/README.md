# Local development and later SMIC40 binding

2026-11-04: [Nangate45 reference mapping](NANGATE45_REFERENCE.md) now provides
a separate public 45nm research target. Its library and results never bind or
sign off the SMIC40 target. Original unit/protocol stages have also run in the
existing Ubuntu WSL; full Linux E203 system replay remains pending.

2026-11-03 update: the supplied E203 RTL now executes the linked candidate
driver in the independent reference layer. See [REFERENCE_E203.md](REFERENCE_E203.md)
for actual firmware/shared-memory/timing contracts, grouped regression,
standalone replay and migration differences. The measured external-memory
reference is about 88.82 million clocks per cold task, so the old callback
budget must not be used as an E203 performance guarantee. Production RTL and
the integration driver remain frozen. Linux and real SMIC40 signoff are pending.

The accelerator hardware stays in `rtl/v2`, and the current driver is
`rtl/integration/driver`. Do not mix its extended context/header with the old
driver. This flow deliberately contains no foundry cell names or library data.

## Export and local smoke

From the repository root, use Python 3 and a new output directory:

```text
python scripts/prepare_local_port.py --output deliverables/local_port_20261103
```

The exporter verifies the completed integration release, source bindings and
13 canonical packet hashes. It copies relative-path production sources, the
current driver, interface tests and frozen development fixtures. It does not
copy the dataset, training environment, host executables, commercial tools or
proprietary libraries. `manifest.json` binds every exported file.

From the exported directory, with Icarus available on PATH:

```text
iverilog -g2012 -s kwt1_mmio -o smoke.vvp -f rtl/v2/files.f
iverilog -g2012 -s tb_sram -o sram.vvp rtl/v2/kwt_sram_sp.sv rtl/integration/tb_sram.sv
vvp sram.vvp
iverilog -g2012 -s tb_mmio -o mmio.vvp rtl/v2/kwt1_mmio.sv rtl/integration/tb_mmio.sv
vvp mmio.vvp
```

The MMIO protocol test uses a controllable accelerator endpoint. It does not
replace a full encoder test. Expected fixture outputs belong to the host
scoreboard only, never accelerator ROM. These commands are compile/protocol
smoke checks, not CPU execution, full synthesis or physical signoff. The bundle
is a compact porting start point; the repository remains the full regression
environment.

## Target binding

```text
python scripts/prepare_local_port.py --check-target flow/targets/smic40.pending.json
```

The unbound template intentionally exits with code 2 and lists missing files
and fields. Populate a separate local target configuration once authorized
SMIC40 libraries/macros become available. A presence check never proves the
correct PVT, macro behavior, area or timing. Do not substitute a different
technology's results and label them SMIC40. Do not guess voltage/corners or
scale gate counts into square millimeters.

Only the technology wrapper, library/constraint configuration, tool invocation,
and platform bus/firmware binding should change on migration. SRAM data remain
20 single-port 4096x16 macros with the existing synchronous read/hold contract.
If the actual macro cannot implement that contract without architectural
changes, reopen scheduling/latency and equivalence review explicitly.

The next local milestone is a CPU-executed reference system, not another host
callback cycle assumption: 512 KiB shared memory, a replaceable bus adapter,
13-packet streaming, actual RV32 driver code, output writeback, reset and IRQ.
Use an identified local/reference CPU if available; it is not the designated
competition SoC. Track all differences for migration. Physical mapping and
final 150 MHz/area/power checks remain separate.
