# Public 45nm reference mapping

This is a **non-manufacturable Nangate45 reference**, independent of the SMIC40
binding templates. No result from this flow is an SMIC40 area, frequency or
power result. The frozen RTL and integer profile are unchanged.

Completed native run: `testdata/nangate45_reference/native_compat_20261104`.
It contains 310005 standard cells (29942 flip-flops), totaling 475862.296 um2
(0.475862296 mm2) in Nangate45, plus 20 unknown-area SRAM macro boundaries.
ABC reports 6036.41 ps for its combinational mapping model with no wireload;
this is not setup/hold STA or a 150 MHz pass. CPU and the external ICB bridge
are outside the mapped top. The first full reference mapping took about 913 s.

The fetched inputs are pinned to OpenROAD-flow-scripts commit
`c9ac73efc603ec3b830caecd7874b1419c1b7d41`; retain the upstream LICENSE, copyright
headers and provenance files under `third_party/nangate45_reference`.

## Reproduce

From the project root, with Python 3 and native Yosys/ABC on PATH:

```text
python3 scripts/run_nangate45_reference.py --native --output testdata/nangate45_reference/new_mapping
python3 scripts/check_nangate45_math.py --output testdata/nangate45_reference/new_math
python3 scripts/check_nangate45_result.py --mapping testdata/nangate45_reference/new_mapping --math testdata/nangate45_reference/new_math --output testdata/nangate45_reference/new_review
```

The mapping entry verifies the
generic result's source and evidence hashes before using it; the default input
is `testdata/local_flow_20261103/final2/synth`. To regenerate that input, run the
existing local `synth` stage and pass its directory with `--generic`.

All three commands require a fresh output directory. The independent result
checker additionally compiles the full mapped top, compares used-cell Liberty
and LEF area, and verifies that old-frontend conversion changed only metadata.
Its original-generic comparison currently uses the default `final2/synth`
baseline; adapt that review input explicitly if selecting a different baseline.
The completed review is `testdata/nangate45_reference/review_20261104` and passed.
It is compile/structure/area evidence, not a complete task simulation.

Library acquisition from scratch is `python scripts/fetch_nangate45_reference.py`
(network access required). It refuses an existing destination. It fetches the
four primary files; the additional LEF and its provenance in this workspace are
for independent dimensional area checking, not required by the mapper.

The native run uses Yosys 0.33 and the library's own dont_use attributes. The
newer YoWASP version additionally supports the ORFS AOI211/OAI211 congestion
exclusions. These are different mapping configurations, not a controlled A/B
performance comparison. The first whole-design YoWASP attempt was stopped after
slow ABC optimization; its partial logs remain in `initial_20261103` and are not
successful synthesis evidence.

Yosys 0.33 cannot read 0.69's `$scopeinfo` metadata cells. The native entry
creates a separate `generic_compat.json` after checking these cells have no
ports or connections, removes only that metadata, and records the count. All
hardware cells and the original generic release remain unchanged. The first
native compatibility failure is retained in `native_20261104`; completed runs
use a new directory.

## Scope

- Top is `kwt1_mmio`: accelerator plus its generic MMIO interface, excluding CPU
  and the external reference ICB bridge. The mapped netlist retains exactly 20
  `kwt_tech_sram_4096x16` macro instances.
- Standard-cell area comes from actual counts and Liberty areas, cross-checked
  against Yosys stat. SRAM area and the complete total remain unknown.
- The Liberty is typical, 1.10 V, 25 C. ABC's 6667 ps target and pin-load model
  guide mapping only. They do not prove 150 MHz, setup/hold coverage or WNS/TNS.
- The arithmetic regression maps **only kwt_math**. Its 2592 math vectors,
  backpressure and reset checks use functional models generated from the same
  Liberty. Iterative, PE and SRAM units in that test remain RTL. It is not a
  whole-design equivalence proof or SDF timing simulation.
- The upstream filler `FILLCELL_X2` has differing Liberty/LEF areas. Retain the
  discrepancy and verify it is absent from logical mapping before treating the
  selected cells' area sum as a physical area reference.
- Undefined constants may be concretized by ABC. Preserve the log and complete
  mapped functional/equivalence checks before promoting the netlist to a
  hardware verification baseline.

The next gates are full mapped-netlist task/reset regression, standard-cell
timing analysis with explicit missing-SRAM coverage, and eventual re-mapping
against the authorized SMIC40 standard-cell and macro libraries. Do not create
fake SRAM timing/area files to make those gates pass.
