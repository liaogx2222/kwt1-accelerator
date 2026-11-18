#!/bin/bash
# From tcsh: bash flow/run_vcs.sh 0
set -euo pipefail
cd "$(dirname "$0")/.."
CASE=${1:-0}
[[ "$CASE" =~ ^[0-9]+$ ]] && (( CASE < 12 )) || exit 2
python3 flow/project.py check
OUT="build/case$CASE"
test ! -e "$OUT" || { echo "preserve existing $OUT"; exit 2; }
mkdir -p "$OUT" build/rtl
sha256sum manifest.json > "$OUT/source.sha256"
if [[ ! -x build/rtl/simv ]]; then
  python3 flow/project.py filelist build/rtl/absolute.f
  (cd build/rtl && vcs -full64 -sverilog -lca -timescale=1ns/1ps \
    +define+FPGA_SOURCE +define+KWT_SIM +define+DISABLE_SV_ASSERTION \
    -f absolute.f -top tb_soc_joint -o simv -l compile.log)
  sha256sum manifest.json > build/rtl/source.sha256
else
  cmp "$OUT/source.sha256" build/rtl/source.sha256
fi
build/rtl/simv +CASE="$CASE" +FIXTURES=fixtures +ROMHEX=firmware/bootrom.hex \
  > "$OUT/run.log" 2>&1
grep -q "RESULT: PASS case=" "$OUT/run.log"
! grep -qE 'RESULT: FAIL|%Fatal|Fatal:|MISMATCH' "$OUT/run.log"
grep -E 'RESULT: PASS|SOC_METRICS' "$OUT/run.log"
echo "SOC_VCS_CASE_VERIFIED $CASE"
