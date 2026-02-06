#!/bin/bash
# AutoNav Charge Indicator - PCB Diagnostics Launcher
# Double-click this file in Finder or run from terminal.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
DIAG_SCRIPT="$SCRIPT_DIR/pcb_diagnostics.py"

# Activate virtual environment and run
source "$VENV_DIR/bin/activate"
python3 "$DIAG_SCRIPT"
STATUS=$?

echo ""
echo "Press any key to close..."
read -n 1 -s
exit $STATUS
