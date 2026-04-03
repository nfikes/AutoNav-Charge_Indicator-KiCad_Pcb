"""Plot voltage vs SOC scatter from discharge CSV data.
IR compensated + session stitching with transient trimming."""
import csv
import matplotlib.pyplot as plt
import numpy as np
import os

# IR compensation: 254 mOhm total path resistance
# Measured: 26,238 mV under 1.19A -> 26,540 mV rested OCV = 302 mV / 1.19A
R_PATH_OHM = 0.254

# Session 2 starts at CSV row 728 (0-indexed from data, after header)
SESSION2_START_ROW = 727  # 0-indexed
TRANSIENT_TRIM = 60  # trim first 60 samples (~2.5 min) of session 2 transients

# Load CSV
results_dir = os.path.join(os.path.dirname(__file__), "..", "empirical_results")
csv_path = os.path.join(results_dir, "discharge_log_20260401_175518.csv")

rows = []
with open(csv_path) as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

# Split into sessions and compute OCV
def compute_ocv(row):
    v_mv = float(row["bus_voltage_mV"])
    i_ma = float(row["current_mA"])
    return v_mv + abs(i_ma) / 1000.0 * R_PATH_OHM * 1000.0

# Session 1: all rows before session 2
s1 = rows[:SESSION2_START_ROW]
# Session 2: trim transients at start
s2 = rows[SESSION2_START_ROW + TRANSIENT_TRIM:]

# Get last stable OCV of session 1 (average last 30 samples)
s1_tail_ocv = np.mean([compute_ocv(r) for r in s1[-30:]])
# Get first stable OCV of session 2 (average first 30 samples after trim)
s2_head_ocv = np.mean([compute_ocv(r) for r in s2[:30]])

# Offset to align session 2 to session 1
offset_mv = s1_tail_ocv - s2_head_ocv
print(f"Session 1 tail OCV: {s1_tail_ocv:.1f} mV")
print(f"Session 2 head OCV: {s2_head_ocv:.1f} mV")
print(f"Stitching offset: {offset_mv:.1f} mV")

# Build stitched OCV curve
soc_stitched = []
ocv_stitched = []

for r in s1:
    soc_stitched.append(float(r["soc_pct"]))
    ocv_stitched.append(compute_ocv(r) / 1000.0)

for r in s2:
    soc_stitched.append(float(r["soc_pct"]))
    ocv_stitched.append((compute_ocv(r) + offset_mv) / 1000.0)

# Also build raw under-load for comparison
soc_all = [float(r["soc_pct"]) for r in rows]
v_raw_all = [float(r["bus_voltage_mV"]) / 1000.0 for r in rows]

fig, ax = plt.subplots(figsize=(10, 6))
ax.scatter(soc_stitched, ocv_stitched, s=4, alpha=0.6, color="steelblue")
ax.set_xlabel("SOC (%)")
ax.set_ylabel("Pack Voltage (V)")
ax.set_title("Battery A Discharge — OCV vs SOC (Renogy RBT2425LFP)")
ax.invert_xaxis()
ax.grid(True, alpha=0.3)
fig.tight_layout()

plot_path = os.path.join(results_dir, "voltage_vs_soc.png")
fig.savefig(plot_path, dpi=150)
print(f"Plot saved: {plot_path}")
