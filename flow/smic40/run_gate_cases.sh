#!/bin/bash
# run_gate_cases.sh -- gate-level batch runner for KWT-1 signoff
#   cases 1..11 (case 0 already verified separately with the same binary)
#   concurrency = min(nproc, 12); one log per case: c<N>.log
#   summary: run_status.txt   verdicts: printed at the end
GS=/home/2026contest/server6/s6_43usr/Desktop/project/out/gate_sim
cd "$GS" || { echo "NO_GS $GS"; exit 1; }
N=$(nproc); [ "$N" -gt 12 ] && N=12
echo "cores=$(nproc) concurrency=$N start=$(date +%H:%M:%S)"
: > run_status.txt
for n in $(seq 1 11); do
  while [ "$(jobs -r | wc -l)" -ge "$N" ]; do sleep 10; done
  ( ./simv_v5 +CASE=$n > "c$n.log" 2>&1; echo "case $n exit=$? end=$(date +%H:%M:%S)" >> run_status.txt ) &
  echo "launched case $n  $(date +%H:%M:%S)"
done
wait
echo "ALL_CASES_DONE $(date +%H:%M:%S)"
cat run_status.txt
grep -H "KWT_OUTPUT\|PASS KWT\|FAIL KWT" c*.log 2>/dev/null
