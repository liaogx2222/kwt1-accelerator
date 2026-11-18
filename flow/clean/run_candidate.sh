#!/bin/bash
# Fresh-project sequence: actual vendor contract first, then synthesis.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 flow/project.py check
python3 flow/project.py preflight
bash flow/run_sram_contract.sh
exec /eda/synopsys/dc/dc_2022.03-SP5-5/bin/dc_shell -f flow/dc.tcl -output_log_file build/dc.log
