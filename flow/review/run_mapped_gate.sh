#!/bin/bash
# External validation entry: production sources, manifest and netlist stay fixed.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
CASE=${1:-0}
[[ "$CASE" =~ ^([0-9]|10|11)$ ]] || { echo 'CASE must be 0..11'; exit 2; }
python3 flow/project.py check-dc
: "${KWT_PDK_ROOT:?set KWT_PDK_ROOT}"
BASE="$ROOT/build/mapped_gate_v1"
MODEL="$BASE/model"
OUT="$BASE/c$CASE"
test ! -e "$OUT" || { echo "preserve existing $OUT"; exit 2; }
MODELS=()
for VT in HVT LVT RVT; do
  LOW=${VT,,}
  FILE="$KWT_PDK_ROOT/SCC40NLL_VHSC40_${VT}_V0.1/SCC40NLL_VHSC40_${VT}_V0p1/verilog/scc40nll_vhsc40_${LOW}.v"
  test -s "$FILE"
  MODELS+=("$FILE")
done
mkdir -p "$BASE"
mkdir "$OUT"
# Keep the relative netlist entry required by the frozen check-saif contract.
sha256sum build/dc/mapped.v flow/tb_gate_tasks.sv flow/sram_contract_9pin.v \
  manifest.json review_tools/run_mapped_gate.sh "${MODELS[@]}" > "$OUT/inputs.sha256"
if [[ -e "$MODEL" ]]; then
  test -f "$MODEL/ready" || { echo 'preserve incomplete model cache'; exit 2; }
  cmp "$OUT/inputs.sha256" "$MODEL/inputs.sha256"
  sha256sum -c "$MODEL/simv.sha256"
else
  mkdir "$MODEL"
  (cd "$MODEL" && vcs -full64 -sverilog -lca -timescale=1ns/1ps +define+KWT_SAIF \
    -top tb_gate_tasks "${MODELS[@]}" "$ROOT/flow/sram_contract_9pin.v" \
    "$ROOT/build/dc/mapped.v" "$ROOT/flow/tb_gate_tasks.sv" -o simv -l compile.log)
  test -x "$MODEL/simv"
  cp "$OUT/inputs.sha256" "$MODEL/inputs.sha256"
  sha256sum "$MODEL/simv" > "$MODEL/simv.sha256"
  echo MAPPED_GATE_MODEL_READY > "$MODEL/ready"
fi
"$MODEL/simv" +CASE="$CASE" +FIXTURES="$ROOT/fixtures" +SAIF_DIR="$OUT" \
  +notimingcheck +no_notifier > "$OUT/run.log" 2>&1
grep -q "PASS KWT_GATE_TASK case=$CASE " "$OUT/run.log"
grep -q 'KWT_OUTPUT mismatches=0 of 1584' "$OUT/run.log"
! grep -qE 'FAIL|BUS_ERR|TIMEOUT|X_ENTER|HW_ERROR' "$OUT/run.log"
test -s "$OUT/kwt1_gate_c$CASE.saif"
python3 flow/project.py check-saif "$OUT/kwt1_gate_c$CASE.saif"
grep -E 'KWT_OUTPUT|PASS KWT_GATE_TASK|KWT_SAIF_WRITTEN' "$OUT/run.log"
echo "KWT_MAPPED_GATE_VERIFIED case=$CASE"
