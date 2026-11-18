#!/bin/sh
# Prepare / compile / run the DC gate-level smoke for Verdi waveform debug.
#
# Run from anywhere; all paths come from environment variables.
#   export REPO=/<upload_dir>/server_signoff_20261106
#   export KWT_STDCELL_SIM_V=<PDK>/verilog/smic40_stdcells.v
#   export KWT_SRAM_SIM_V=<PDK>/sram/<macro>_behavior.v
#   export KWT_GATE_NETLIST=$REPO/signoff_out/dc_synth/mapped.v   # optional
#   export KWT_SIM=vcs          # vcs | iverilog
#   export KWT_DUMP=fsdb        # fsdb | vcd (iverilog forces vcd)
#   export KWT_GATE_SDF=$REPO/signoff_out/dc_synth/mapped.sdf     # optional
#   sh flow/verdi/run_verdi_gate.sh --prepare-only
#   sh flow/verdi/run_verdi_gate.sh
#
# The script never launches a GUI. It prints the verdi command at the end.
set -eu

PREPARE_ONLY=0
if [ "${1:-}" = "--prepare-only" ]; then PREPARE_ONLY=1; fi

: "${REPO:?set REPO to the extracted bundle root}"
: "${KWT_STDCELL_SIM_V:?set KWT_STDCELL_SIM_V to the AUTHORIZED standard-cell Verilog model}"
: "${KWT_SRAM_SIM_V:?set KWT_SRAM_SIM_V to the AUTHORIZED SRAM macro functional model}"

KT="$REPO/keyword-transformer"
OUT="$REPO/signoff_out/gate_sim"
NETLIST="${KWT_GATE_NETLIST:-$REPO/signoff_out/dc_synth/mapped.v}"
SDF="${KWT_GATE_SDF:-}"
TB="$KT/flow/verdi/tb_gate_mmio.sv"
SIM="${KWT_SIM:-vcs}"
DUMP="${KWT_DUMP:-fsdb}"
FL="$OUT/gate.files.f"

for f in "$KWT_STDCELL_SIM_V" "$KWT_SRAM_SIM_V" "$NETLIST" "$TB"; do
    if [ ! -f "$f" ]; then
        echo "ERROR required file missing: $f" >&2
        exit 2
    fi
done
if [ -n "$SDF" ] && [ ! -f "$SDF" ]; then
    echo "ERROR SDF missing: $SDF" >&2
    exit 2
fi

mkdir -p "$OUT"
{
    echo "+libext+.v"
    # Harmless for a DC netlist; helps if the platform model references a
    # generated profile header. Real mapped.v should not need any `include.
    echo "+incdir+$KT/rtl/v2/generated"
    echo "$KWT_STDCELL_SIM_V"
    echo "$KWT_SRAM_SIM_V"
    echo "$NETLIST"
    echo "$TB"
} > "$FL"
echo "WROTE $FL"

if [ "$SIM" = "iverilog" ]; then
    if [ "$DUMP" != "vcd" ]; then
        echo "NOTE iverilog has no Verdi FSDB PLI; forcing KWT_DUMP=vcd (then vcd2fsdb)"
        DUMP=vcd
    fi
fi
# VCS uses +define+NAME; iverilog uses -D NAME. Do NOT mix them: iverilog
# treats "+define+X" as a source filename and the preprocessor fails.
DEFS_VCS=""
DEFS_IV=""
if [ "$DUMP" = "fsdb" ]; then DEFS_VCS="$DEFS_VCS +define+FSDB"; fi
if [ "$DUMP" = "vcd" ];  then
    DEFS_VCS="$DEFS_VCS +define+VCD"
    DEFS_IV="$DEFS_IV -D VCD"
fi
if [ -n "$SDF" ]; then
    DEFS_VCS="$DEFS_VCS +define+SDF"
    DEFS_IV="$DEFS_IV -D SDF"
fi

RUNARGS=""
if [ -n "$SDF" ]; then RUNARGS="+sdf=$SDF"; fi

echo "SIM=$SIM DUMP=$DUMP SDF=${SDF:-none}"
echo "VCS_DEFS=$DEFS_VCS"
echo "IVERILOG_DEFS=$DEFS_IV"
if [ "$PREPARE_ONLY" -eq 1 ]; then
    echo "PREPARE_ONLY: stop before compiling."
    cat "$FL"
    exit 0
fi

if [ "$SIM" = "iverilog" ]; then
    IVERILOG="${KWT_IVERILOG:-iverilog}"
    VVP="${KWT_VVP:-vvp}"
    if [ -n "$SDF" ]; then
        echo "NOTE iverilog omits \$sdf_annotate (no specify blocks): SDF timing is NOT"
        echo "NOTE simulated on this route. Use VCS/Xcelium/Questa for timing annotation."
    fi
    # Do NOT pipe through tee: in POSIX sh `set -e` does not see a failure in
    # the first stage of a pipeline, and the script would report success after
    # a broken compile. Redirect to a log and check the status explicitly.
    if ! ( cd "$OUT" && "$IVERILOG" -g2012 -s tb_gate_mmio -o gate.vvp \
              $DEFS_IV -f gate.files.f ) > "$OUT/compile.log" 2>&1; then
        cat "$OUT/compile.log"
        echo "ERROR iverilog compile failed" >&2
        exit 2
    fi
    cat "$OUT/compile.log"
    if ! ( cd "$OUT" && "$VVP" gate.vvp $RUNARGS ) > "$OUT/sim.log" 2>&1; then
        cat "$OUT/sim.log"
        echo "ERROR gate simulation failed" >&2
        exit 2
    fi
    cat "$OUT/sim.log"
    grep -q 'PASS KWT_GATE_SIM' "$OUT/sim.log" || {
        echo "ERROR simulation produced no PASS marker" >&2; exit 2; }
    if [ ! -s "$OUT/gate.vcd" ]; then
        echo "ERROR gate.vcd missing or empty" >&2; exit 2
    fi
    if command -v vcd2fsdb >/dev/null 2>&1; then
        ( cd "$OUT" && vcd2fsdb gate.vcd gate.fsdb ) || \
            echo "WARN vcd2fsdb failed; open gate.vcd with a converter"
    else
        echo "NOTE vcd2fsdb not on PATH: run \$VERDI_HOME/bin/vcd2fsdb gate.vcd gate.fsdb"
    fi
    echo "OPEN WAVEFORM:"
    echo "  verdi -sv -f $FL -top tb_gate_mmio -ssf $OUT/gate.fsdb &"
    exit 0
fi

# ---- VCS + Verdi KDB route -------------------------------------------------
VCS="${KWT_VCS:-vcs}"
PLI=""
if [ "$DUMP" = "fsdb" ]; then
    if [ -n "${VERDI_HOME:-}" ]; then
        NOVAS_TAB="$VERDI_HOME/share/PLI/VCS/LINUX64/novas.tab"
        PLI_A="$VERDI_HOME/share/PLI/VCS/LINUX64/pli.a"
        if [ -f "$NOVAS_TAB" ] && [ -f "$PLI_A" ]; then
            PLI="-P $NOVAS_TAB $PLI_A"
        else
            echo "WARN Verdi PLI not found under $VERDI_HOME/share/PLI/VCS/LINUX64" >&2
            echo "WARN find novas.tab + pli.a for your VCS arch and set PLI manually" >&2
        fi
    else
        echo "WARN VERDI_HOME unset; FSDB dumping needs the Verdi PLI" >&2
    fi
fi

# Zero-delay functional sim skips specify blocks; keep them when SDF is used.
TIMING_ARGS=""
if [ -z "$SDF" ]; then TIMING_ARGS="+nospecify +notimingcheck"; fi

if ! ( cd "$OUT" && "$VCS" -full64 -sverilog -debug_access+all -kdb -lca \
          -f gate.files.f $DEFS_VCS $TIMING_ARGS $PLI \
          -top tb_gate_mmio -l compile.log -o simv ) > "$OUT/vcs_compile_console.log" 2>&1; then
    cat "$OUT/vcs_compile_console.log"
    echo "ERROR vcs compile failed" >&2
    exit 2
fi
cat "$OUT/vcs_compile_console.log"
if ! ( cd "$OUT" && ./simv $RUNARGS -l sim.log ) > "$OUT/vcs_sim_console.log" 2>&1; then
    cat "$OUT/vcs_sim_console.log"
    echo "ERROR gate simulation failed" >&2
    exit 2
fi
cat "$OUT/vcs_sim_console.log"
grep -q 'PASS KWT_GATE_SIM' "$OUT/sim.log" || {
    echo "ERROR simulation produced no PASS marker in sim.log" >&2; exit 2; }
if [ "$DUMP" = "fsdb" ] && [ ! -s "$OUT/gate.fsdb" ]; then
    echo "ERROR gate.fsdb missing or empty: check the Verdi PLI binding" >&2
    exit 2
fi

echo "OPEN WAVEFORM (needs X11 / VNC / ssh -X on the server):"
echo "  cd $OUT && verdi -dbdir simv.daidir -ssf gate.fsdb &"
echo "If KDB is unavailable, fall back to:"
echo "  verdi -sv -f $FL -top tb_gate_mmio -ssf gate.fsdb &"
