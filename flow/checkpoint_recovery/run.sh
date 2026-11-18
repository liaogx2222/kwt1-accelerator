#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 recovery/verify.py check-input
python3 flow/project.py preflight
exec /eda/synopsys/dc/dc_2022.03-SP5-5/bin/dc_shell -f recovery/export_initial.tcl -output_log_file build/recovery_dc.log
