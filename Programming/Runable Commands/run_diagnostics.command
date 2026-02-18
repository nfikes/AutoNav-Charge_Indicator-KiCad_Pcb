#!/bin/bash
# AutoNav Charge Indicator - PCB Diagnostics Launcher
# Double-click this file in Finder or run from terminal.

cd "$(dirname "$0")/../scripts"
/opt/homebrew/bin/python3.14 pcb_diagnostics.py
STATUS=$?

echo ""
echo "Press any key to close..."
read -n 1 -s
exit $STATUS
