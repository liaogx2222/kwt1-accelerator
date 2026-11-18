# P0/P1 performance comparison contract

All variants use the frozen E203 model objects, accelerator/profile and host
word-arrival/ready timing. Published sources and prior evidence remain immutable.
Each measured process runs one complete class-0 cold task. These experiments
are inputs to the first architecture review; they do not approve a combination.

Three timestamps delimit two windows:

- B0: the host accepts the first job query and schedules the input, before its
  first word arrives. This is the existing `begin_clock`.
- B1: the host accepts the firmware's driver-return marker at HOST[28]. Every
  output byte store and the final done read precede this event. This is the
  existing `end_clock`. The main window is [B0, B1).
- B2: the host accepts job report completion at HOST[4]. The report tail is
  [B1, B2). Firmware CSR-counter/error/accelerator-counter reporting belongs
  here. For an error case, quarantine/reset confirmation also belongs here
  and must be identified separately from normal reporting.

The observer samples immediately before the active clock edge and records
events accepted on that edge. B0/B1/B2 retain the old harness's post-edge clock
numbering. Conservation assertions enforce main cycles=B1-B0, tail cycles=B2-B1,
and main+tail RAM events=the original counters through `finish_job()`. The six
main phases are mutually exclusive and must sum exactly to B1-B0. CPU/accelerator
overlap remains separately reported. A 32-clock final response drain is outside
these per-job windows and remains part of process completion.

The old 114-read difference is retained as report-tail events, with each address
and shadow IR PC saved. It is never silently added to main latency or attributed
to parameter loading. Old 18-column metrics are preserved as legacy observations.
The original profiler and this observer independently reproduce the baseline.

P1-A changes only the platform's `cancelled` function pointer to null. This
platform has no cancellation producer; the generic driver still supports it.
P1-B changes only the parameter packet word loader in a separate generated
driver copy. The generic byte loader remains unchanged for input/general use.
The packet contract is non-null, 4-byte aligned, positive size divisible by four,
little endian and a stable provider lease; GCC-compatible `may_alias` handles
byte storage aliasing. Invalid alignment is rejected before any DATA transfer.
Length/schema checks and cleanup remain the generic driver's original behavior.

P1-C retains the callback and byte packet path and relocates code to the original
CPU's configured ITCM. External reset/startup copies the linked image from shared
RAM with actual CPU loads/stores and executes FENCE.I. No host directly initializes
TCM storage. Report both B0-B1 and startup+B0-B1; retain the source image in the
512KiB shared budget and list the CPU's 64KiB TCM as reference-only platform
capacity requiring confirmation. ELF/map/segment validation and matching retired
IR bytes demonstrate what was installed and executed.

Counters distinguish external RAM address regions; a code-address count is not
claimed as an exact IFU channel counter. TCM retired-PC counts and external-code
traffic describe the changed fetch path; all architectural timing conclusions
remain specific to this identified E203 configuration.
