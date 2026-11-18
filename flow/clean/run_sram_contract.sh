#!/bin/bash
# Validate the actual vendor macro and RET1N binding before the long synth run.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
python3 flow/project.py check
MODEL=${KWT_SRAM_MODEL:-/storage1/admin_public_dir/SRAM_Lib_2025/RAMSP4096X16/verilog/RAMSP4096X16.v}
test -s "$MODEL"
OUT="$ROOT/build/sram_contract"
test ! -e "$OUT" || { echo "preserve existing $OUT"; exit 2; }
mkdir -p "$ROOT/build"
mkdir "$OUT"
sha256sum "$MODEL" rtl/integration/smic40/kwt_tech_sram_4096x16.sv flow/tb_sram_contract.sv > "$OUT/inputs.sha256"
(cd "$OUT" && vcs -full64 -sverilog -lca -timescale=1ns/1ps -top tb_sram_contract \
  "$MODEL" "$ROOT/rtl/integration/smic40/kwt_tech_sram_4096x16.sv" \
  "$ROOT/flow/tb_sram_contract.sv" -o simv -l compile.log)
"$OUT/simv" +notimingcheck +no_notifier > "$OUT/run.log" 2>&1
grep -q 'PASS KWT_SRAM_CONTRACT checks=5' "$OUT/run.log"
! grep -q 'FAIL' "$OUT/run.log"
cat "$OUT/run.log"
echo KWT_VENDOR_RET1N_CONTRACT_VERIFIED
