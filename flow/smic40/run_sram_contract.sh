#!/bin/sh
# =============================================================================
# run_sram_contract.sh -- compile the SMIC40 SRAM adapter + the AUTHORIZED vendor
# model with VCS and prove the three frozen contract booleans.
#
# Run from <REPO>/keyword-transformer (the directory that holds flow/ and rtl/).
#
# Required:
#   KWT_SRAM_SIM_V   vendor Verilog model, e.g.
#                    /storage1/admin_public_dir/SRAM_Lib_2025/RAMSP4096X16/verilog/RAMSP4096X16.v
#   KWT_SRAM_WRAPPER rtl/integration/smic40/kwt_tech_sram_4096x16.sv
# Optional:
#   KWT_OUT          output root (default ../signoff_out)
#   KWT_TB           testbench path (default flow/smic40/tb_sram_contract.sv)
#   KWT_SIM_DEFINES  overrides the compile-time branch of the wrapper.
#                    Default is "+define+KWT_SIM_POSITIONAL", which is the ONLY
#                    form VCS Q-2020.03-SP2 accepts against this vendor model.
#                    Set it to empty to reproduce the named-binding failure.
#
# Exit 0 only when the log contains "PASS KWT_SRAM_CONTRACT".
#
# NOTE (2026-11-07): this script used to pass `-Mdir "$WORK/simv.daidir"`.
# VCS Q-2020.03-SP2 on RServer06 rejects the space-separated form -- it reports
# "The option '-Mdir' requires a value" and then treats the directory as a
# source file ("Source file ... cannot be opened"). Instead of guessing at
# `-Mdir=<dir>`, we simply cd into the work directory so VCS puts simv.daidir
# and csrc where we want them. Fewer options, fewer version differences.
# =============================================================================
set -u

: "${KWT_SRAM_SIM_V:?set KWT_SRAM_SIM_V to the authorized RAMSP4096X16 Verilog model}"
: "${KWT_SRAM_WRAPPER:?set KWT_SRAM_WRAPPER to rtl/integration/smic40/kwt_tech_sram_4096x16.sv}"

OUT=${KWT_OUT:-../signoff_out}
TB=${KWT_TB:-flow/smic40/tb_sram_contract.sv}
WORK="$OUT/sram_contract"

case "$KWT_SRAM_SIM_V" in
    *tech_sram_model.sv)
        echo "ERROR: KWT_SRAM_SIM_V points at the behavioral array model; that is not the macro" >&2
        exit 2 ;;
esac

for f in "$KWT_SRAM_SIM_V" "$KWT_SRAM_WRAPPER" "$TB"; do
    if [ ! -s "$f" ]; then
        echo "ERROR: missing or empty input: $f" >&2
        exit 2
    fi
done

abspath() {
    case "$1" in
        /*) printf '%s\n' "$1" ;;
        *)  printf '%s\n' "$(cd "$(dirname "$1")" && pwd)/$(basename "$1")" ;;
    esac
}

ABS_V=$(abspath "$KWT_SRAM_SIM_V")
ABS_W=$(abspath "$KWT_SRAM_WRAPPER")
ABS_TB=$(abspath "$TB")

mkdir -p "$WORK" || exit 2
cd "$WORK" || exit 2

echo "== vendor model port list =="
grep -nE '^[[:space:]]*(module|input|output|inout)' "$ABS_V" | head -40

echo "== compile in $WORK =="
# SETTLED 2026-11-07 (PASS KWT_SRAM_CONTRACT checks=5 observed on RServer06).
#
# The macro has exactly TEN ports:
#     Q, CLK, CEN, WEN, A, D, EMA, EMAW, GWEN, RETIN
# established by asking the elaborator, not by grepping the ifdef tree:
#     vcs ... +define+KWT_SIM_NO_RETIN +lint=TFIPC-L ...   (9 connections)
#     -> "only 9 port connection(s) in the instance.
#         Input port 'RETIN' is not connected."
# Exactly one unconnected port => ten ports, RETIN is the tenth.
# VDDCE / VDDPE / VSSE are NOT ports of this macro; naming them produces three
# Error-[UPIME] plus a misleading "too few port connections" warning.
#
# The remaining oddity is a TOOL defect, not a design defect: VCS Q-2020.03-SP2
# rejects the NAMED connection `.RETIN` against this model ("Port RETIN is not
# defined") even though the declaration on line 483 is clean ASCII (od -c) and
# the same port is listed as unconnected when we omit it. POSITIONAL binding
# compiles cleanly. So the simulation build uses positional, i.e.
#     +define+KWT_SIM_POSITIONAL
# The default (named) branch in the wrapper is what dc_shell sees, where RETIN
# comes from the .lib and binds normally.
#
# Do NOT switch synthesis to positional: .lib and .v port ORDER may differ, and
# a positional mismatch connects wrong pins silently instead of erroring out.
SIM_DEFINES=${KWT_SIM_DEFINES-+define+KWT_SIM_POSITIONAL}
echo "sim_defines=[$SIM_DEFINES]"
vcs -full64 -sverilog $SIM_DEFINES -o simv "$ABS_V" "$ABS_W" "$ABS_TB" -l compile.log
rc=$?
echo "compile_exit=$rc"
if [ "$rc" -ne 0 ]; then
    echo "ERROR: VCS compile failed, see $WORK/compile.log" >&2
    exit 2
fi

echo "== run =="
./simv -l run.log
rc=$?
echo "sim_exit=$rc"

grep -E '^(ok|FAIL) |PASS KWT_SRAM_CONTRACT|FAIL KWT_SRAM_CONTRACT' run.log

if ! grep -q 'PASS KWT_SRAM_CONTRACT' run.log; then
    echo "ERROR: contract not proven; do NOT use this macro for signoff numbers" >&2
    exit 2
fi

echo "SRAM_CONTRACT_OK"
