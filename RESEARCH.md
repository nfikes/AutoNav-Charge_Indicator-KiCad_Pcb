# RESEARCH.md

Grep-friendly dump of what Claude has learned about this repository. Append short, keyword-rich lines so future lookups (`grep`) hit. Claude is allowed to update this file.

## Notes

battery: charge target 29.0V (CC-CV); BMS overvoltage 29.2V; BMS undervoltage 20.0V; overcurrent 27.5A — Programming/docs/ina226_fuel_gauge_ros2_plan.md:68-72
battery: current sensing — INA226 shunt 10 mOhm (R4); BQ34Z100-R2 sense shunt 5 mOhm (R26, low-side) — Programming/scripts/pcb_diagnostics.py:15-16
battery: discharge sessions Apr 1–4 2026 — idle 1.19A, suspended spinning 1.87A/2.37A, forward motion 2.5A — Programming/empirical_results/session_notes.md
battery: LiFePO4 flat plateau 3330–3280 mV/cell (70–30% SOC); voltage unreliable for SOC 20–80%, coulombs primary — Programming/docs/ina226_fuel_gauge_ros2_plan.md:127-136
battery: pack internal resistance ~254 mOhm at high SOC, drops to ~171 mOhm at low SOC observed in discharge — Programming/empirical_results/session_notes.md:12-31
battery: pack voltage range 20–30V nominal; BMS cutoff ~22.5V (2815 mV/cell); full charge ~29V (3625 mV/cell) — README.md:187-199
battery: Rev4+ voltage divider R27=200kΩ / R22=6.49kΩ, ratio 31.82, keeps BAT pin <1V at 30V pack — README.md:115-119
battery: target pack is Renogy RBT2425LFP — LiFePO4 8S, 25.6V nominal, 25Ah rated, ~20.5Ah usable before 20V cutoff — Programming/scripts/bq_program_battery.py:1-10
battery: usable capacity measured 20.476 Ah (82% of 25Ah rated) via full 4-session discharge — Programming/empirical_results/session_notes.md:42-46

ci: no .github/workflows, .gitlab-ci.yml, .travis.yml, or any CI config present — confirmed via find

dataflow: bq_program_battery.py writes design capacity 25000mAh, 8S, voltage-divider ratio to BQ34Z100-R2 flash — Programming/scripts/bq_program_battery.py:1-30
dataflow: bq_program_chemistry.py writes LiFePO4 R_a resistance tables + voltage calibration to BQ data flash — Programming/scripts/bq_program_chemistry.py:1-40
dataflow: ina226_discharge_log.py logs V/I from INA226 to discharge_log_YYYYMMDD_HHMMSS.csv for SOC calibration — Programming/scripts/ina226_discharge_log.py:1-12
dataflow: ina226_fuel_gauge.py continuously monitors bus V + shunt I, computes coulomb-counted SOC with Peukert correction — Programming/scripts/ina226_fuel_gauge.py:1-30
dataflow: pcb_diagnostics.py reads INA226 + BQ34Z100-R2 over I2C, reports voltage/current/temperature — Programming/scripts/pcb_diagnostics.py:1-15
dataflow: plot_discharge.py reads CSV from empirical_results/, applies IR compensation, emits voltage-vs-SOC scatter — Programming/scripts/plot_discharge.py:1-5

datasheet: Renogy RBT2425LFP Battery Datasheet — README.md:342
datasheet: Renogy RBT2425LFP User Manual — README.md:344
datasheet: TI BQ34Z100-R2 Technical Reference Manual (sluuco5) — Programming/scripts/pcb_diagnostics.py:9
datasheet: TI INA226 datasheet — Programming/scripts/pcb_diagnostics.py:8

deps: aardvark-api-macos-arm64-v6.00 vendored alongside scripts as .so bindings — Programming/scripts/hw_common.py:8
deps: no requirements.txt, no pyproject.toml, no setup.py at repo root or under Programming/
deps: numpy, matplotlib, csv, struct, time, threading used by hw_common.py and friends — Programming/scripts/hw_common.py:8
deps: PIL (Pillow) used in Image Analysis GUI — Programming/Image Analysis/calibration_gui.py:10

doc: Programming/docs/ contains BQ34Z100-R2_full_test_log.md (commissioning history) and ina226_fuel_gauge_ros2_plan.md

domain: Charge Indicator is the battery state-of-charge board for the AutoNav robot, using INA226 V/I/P sensing — README.md:1-33
domain: coulomb counting = integrating current over time to track SOC — Programming/docs/ina226_fuel_gauge_ros2_plan.md:78-94
domain: design evolved from simple LED threshold indicator to instrumentation-grade monitor with TI power-management ICs — README.md:3-8
domain: Peukert correction = capacity reduction at higher discharge rate; LFP exponent ~1.05 at 5A reference — Programming/docs/ina226_fuel_gauge_ros2_plan.md:73-74
domain: SOC = state of charge, battery capacity remaining as % or decimal — Programming/docs/ina226_fuel_gauge_ros2_plan.md:149-174

empirical: discharge log naming — discharge_log_YYYYMMDD_HHMMSS.csv tracks V/I over time with load conditions — Programming/empirical_results/
empirical: empirical_results/ina226_YYYYMMDD_HHMMSS/ folders hold ROS2 topic CSVs (cols ROS2_Clock/Topic_Name/Data_Keys/Values) — Programming/empirical_results/ina226_20260427_184214/
empirical: outputs/ groups INA226 CSV snapshots by I2C sampling rate (50Hz, 396Hz, 455Hz, 549Hz, 559Hz, 568Hz) — Programming/outputs/

entrypoint: ina226_monitor.command launches ina226_monitor.py (user-facing GUI monitor) — Programming/Runable Commands/ina226_monitor.command:1-3
entrypoint: run_diagnostics.command launches pcb_diagnostics.py (full I2C read + validation) — Programming/Runable Commands/run_diagnostics.command:1-6
entrypoint: shell launchers invoke /opt/homebrew/bin/python3.14 directly — no venv — Programming/Runable Commands/run_diagnostics.command:5

gitignore: Aardvark .so/.dll binaries ARE tracked; KiCad backup zips ARE tracked (11 zips) — Charge_Indicator/Charge_Indicator-backups/
gitignore: minimal — only .claude/settings.local.json is ignored — .gitignore:1-2

gui: ina226_monitor.py — tkinter rolling oscilloscope plot, ~500Hz sample, 20Hz display, logs CSV to outputs/ — Programming/scripts/ina226_monitor.py:1-9
gui: Image Analysis/annotate_metal_shaving_risk.py overlays pad positions, 0603 bridging circles, multi-net shorts on PCB image — Programming/Image Analysis/annotate_metal_shaving_risk.py:1-6

hardware: shunt resistors — R4 = 10mΩ (WSL1206R0100JEA) for INA226; R26 = 5mΩ (WSL25125L000FEA) low-side for BQ — Programming/scripts/pcb_diagnostics.py:22-25
hardware: thermistor Murata NCP18XH103D03RB (10kΩ NTC, B=3434K) on BQ34Z100-R2 — Programming/scripts/pcb_diagnostics.py:31-33

hwtool: INA226 (U3) at I2C 0x40 in script code; BQ34Z100-R2 (U1) at 0x55 — Programming/scripts/pcb_diagnostics.py:1-8
hwtool: multimeter referenced for manual BAT-pin voltage check — Programming/scripts/bq_recover.py
hwtool: Total Phase Aardvark I2C adapter v6.00 (arm64-macos) is the host I2C bridge — Programming/scripts/hw_common.py:8

ic: 74HC164 — LED shift register driving SOC threshold indicator states — README.md:73
ic: BQ34Z100-R2 (U1) — TI fuel gauge, I2C 0x55, 5V REGIN, provides 2.5V REG25 LDO output — Programming/docs/BQ34Z100-R2_full_test_log.md:76-78
ic: BQ34Z100-R2 abs-max with VOLTSEL=1 — BAT pin must be <1V; Rev 4+ divider satisfies this at 30V pack — README.md:115-119
ic: INA226 (U3) — TI precision V/I/P monitor, 500V HBM ESD; address per README.md:69 vs script code differs (see flag below)
ic: SGM61410 (U2) — buck converter for 5V rail; FB pin abs max 5.5V; failed on R2 from feedback-divider short — README.md:305-323
ic: TLV271CW5-7 (U6) — unity-gain buffer op-amp on voltage divider into BQ BAT pin; input max VDD+0.2V — Programming/docs/BQ34Z100-R2_full_test_log.md:71-74
ic: TPS7A2033 (U5) — 3.3V LDO from 5V; only 1.5V margin to 6.5V abs max, vulnerable to overvoltage — Programming/Image Analysis/PCB_Design_Guidelines.md:34-35

image: pad_circles_check.png — PCB pad analysis viz, part of metal-shaving risk workflow — Programming/Image Analysis/pad_circles_check.png
image: R3_metal_shaving_risk_analysis.png — annotated PCB highlighting 37 critical/high-severity debris risk zones — Programming/Image Analysis/R3_metal_shaving_risk_analysis.png

kicad: backups in Charge_Indicator-backups/ — 11 timestamped .zip files spanning 2026-03-19 to 2026-04-29
kicad: Charge_Indicator.kicad_pcb version 20241229, generator 9.0 (KiCad 9.0) — Charge_Indicator/Charge_Indicator.kicad_pcb:1-3
kicad: Charge_Indicator.kicad_pro is the project file (JSON, KiCad 8/9, schema 9.0 dated 2025-01-14) — Charge_Indicator/Charge_Indicator.kicad_pro:1-2
kicad: project_libraries/ holds custom symbols for BQ34Z100-R2, INA226, LM393, SGM61410XN6G, SN74HC164, TLV74033 — Charge_Indicator/project_libraries

layout: Charge_Indicator/ — main KiCad project + backups + BOM sheets + REV1–3 output folders + project_libraries/
layout: Programming/ — scripts/ (~40 .py), empirical_results/, outputs/, Image Analysis/, docs/, Runable Commands/
layout: top-level — Charge_Indicator/, Programming/, Datasheets/, README.md, plus the framework files (CLAUDE/BEHAVIOR/RESEARCH)

module: Image Analysis/ also contains calibration_gui.py and pad_bbox_gui.py for PCB image coordinate mapping — Programming/Image Analysis

output: BOM exists as CSV (REV1) and .numbers (REV2) — Charge_Indicator/BOM and Order Sheet/
output: Gerbers/drill/job files in Project Output Files REV[123]/ — Charge_Indicator/Project Output Files REV3/
output: no automated Gerber/BOM pipeline — manual KiCad export assumed

pcb: Charge_Indicator.kicad_pcb is ~37MB UTF-8; SMT layout uses 0603/0805/1210 packages — Charge_Indicator/Charge_Indicator.kicad_pcb:1

revision: backups span 2026-03-19 → 2026-04-29; output folders REV1–3 each have Gerber/drill archives
revision: Rev3 is recent stable (commit 8bfdbf8 "Fabrication files for REV3"); Rev2 board declared dead from metal-shaving damage — README.md:267-337

safety: bare boards must not deploy on robots without enclosure — protective housing required to prevent metallic debris shorts — README.md:333-334
safety: INA226 SCL abs max is VS+0.3V (3.6V at 3.3V supply); existing 5.6V zeners (D8/D9) clamp above threshold — recommend 3.3V TVS — Programming/Image Analysis/PCB_Design_Guidelines.md:48-52
safety: metal shavings on R2 caused cascading INA226 latch-up (SCL→GND ~5Ω short) and SGM61410 feedback-network damage — README.md:280-336
safety: risk zone #12 — SGM61410 U2 FB pin (5.5V abs max) adjacent to VIN (BAT+); confirmed failure on R2 — Programming/Image Analysis/R3_Risk_Zone_Key.md:16
safety: risk zone #8 — INA226 U3 has 12 internal pad-pair shorts within 0603 reach incl. SCL→GND and BAT+→GND — Programming/Image Analysis/R3_Risk_Zone_Key.md:12
safety: Rev2/3 failure mode (VOLTSEL=1 with 3.8V on BAT) destroyed 3 BQ34Z100-R2 ADCs; Rev4+ divider 31.82:1 eliminates this — README.md:201-205

schematic: Charge_Indicator.kicad_sch — INA226 V/I monitor, BQ34Z100-R2 gauge, SGM61410 buck, TLV74033 LDO, SN74HC164 shift reg, LED indicators — Charge_Indicator/Charge_Indicator.kicad_sch:1

script: bq_comm_test.py — reads BQ SBS regs, verifies VOLTSEL=1 and RSNS=LOW post-Rev4 — Programming/scripts/bq_comm_test.py:1-15
script: bq_fix_vdivider.py — Ralim-method VD recalibration (newVD = actual/reported × current) — Programming/scripts/bq_fix_vdivider.py:1-6
script: bq_fresh_chip.py — staged bringup probe → reset → rsns-fix → cc-calib → vd-calib — Programming/scripts/bq_fresh_chip.py:1-11
script: bq_kitchen_sink.py — comprehensive BQ recovery + VD/cell-combo investigation — Programming/scripts/bq_kitchen_sink.py:1-12
script: bq_led_test.py — drives LED outputs on P1/P2 via MOSFET in BQ firmware — Programming/scripts/bq_led_test.py:1-10
script: bq_recover.py — analog-lockup recovery: SHUTDOWN → CAL_MODE → IT_ENABLE toggle + RESET — Programming/scripts/bq_recover.py:1-20
script: bq_restore_factory.py — restores Pack Config 0x41D9 (VOLTSEL=1, RSNS=HIGH) + CC defaults — Programming/scripts/bq_restore_factory.py:1-13
script: hw_common.py — central Aardvark I2C init, registers, unseal keys, constants for all BQ/INA scripts — Programming/scripts/hw_common.py:1-80
script: i2c_scan.py — full bus scan 0x03–0x77, lists known devices + raw scan results — Programming/scripts/i2c_scan.py:1-2
script: ina226_comm_test.py — quick MFG/Die ID + config register read; pass/fail summary — Programming/scripts/ina226_comm_test.py:1-4

upstream: Bowser and Shogi are AutoNav robot instances — R2 board was transferred from Bowser to Shogi — README.md:268-278
upstream: Charge Indicator board feeds the AutoNav_25-26 ROS2 stack — Programming/docs/ina226_fuel_gauge_ros2_plan.md:10-11
upstream: Jetson runs autonav_electrical_publisher at 10Hz publish, 300Hz internal coulomb integration — Programming/docs/ina226_fuel_gauge_ros2_plan.md:233-244
upstream: ROS2 node autonav_electrical_publisher consumes INA226 + BQ for battery state — Programming/docs/ina226_fuel_gauge_ros2_plan.md:1-11

## Conflicts surfaced by /populate-research

- INA226 I2C address: README.md:69 says 0x45; pcb_diagnostics.py says 0x40. Likely a 7-bit-vs-strap discrepancy — verify against the schematic before trusting either.
