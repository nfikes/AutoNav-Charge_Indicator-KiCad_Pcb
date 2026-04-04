"""Plot voltage vs SOC scatter from discharge CSV data.
IR compensated + multi-session stitching with per-session transient trimming."""
import csv
import matplotlib.pyplot as plt
import numpy as np
import os

# IR compensation: 254 mOhm total path resistance
# Measured: 26,238 mV under 1.19A -> 26,540 mV rested OCV = 302 mV / 1.19A
R_PATH_OHM = 0.254

# Usable capacity: empirically measured 20.476 Ah before BMS cutoff
# (81.9% of 25 Ah rated — BMS cuts off at ~22.5V / 2815 mV per cell)
USABLE_CAPACITY_AH = 20.476
CELLS_SERIES = 8

# Session boundaries and trim durations (tuned from settling analysis)
# Rest periods: S1->S2 ~21h, S2->S3 ~18.5h (both overnight, full diffusion recovery)
SESSIONS = [
    # (start_row, trim_samples, label)
    (0,    0,   "S1: 04/01 idle 0.1Hz"),        # Session 1 — no trim needed
    (727,  120, "S2: 04/02 motors 0.4Hz"),       # ~5 min settle (120 × 2.5s)
    (3621, 400, "S3: 04/03 motors 0.4Hz"),       # ~15 min settle (400 × 2.5s)
    (12249, 30, "S4: 04/04 motors 0.4Hz"),        # short rest, less trim needed
]

# Load CSV
results_dir = os.path.join(os.path.dirname(__file__), "..", "empirical_results")
csv_path = os.path.join(results_dir, "discharge_log_20260401_175518.csv")

rows = []
with open(csv_path) as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

print(f"Total rows: {len(rows)}")


def compute_ocv(row):
    v_mv = float(row["bus_voltage_mV"])
    i_ma = float(row["current_mA"])
    return v_mv + abs(i_ma) / 1000.0 * R_PATH_OHM * 1000.0


# Build session slices
session_data = []
for i, (start, trim, label) in enumerate(SESSIONS):
    end = SESSIONS[i + 1][0] if i + 1 < len(SESSIONS) else len(rows)
    raw = rows[start:end]
    trimmed = raw[trim:]
    session_data.append((raw, trimmed, label))

# Stitch with per-session offsets, track trimmed points separately
soc_stitched = []
ocv_stitched = []
soc_trimmed = []
ocv_trimmed = []
cumulative_offset = 0.0

for i, (raw, trimmed, label) in enumerate(session_data):
    if i == 0:
        pass  # No offset for session 1
    else:
        # Previous session's last 30 stable points (from raw, before trim of next)
        prev_raw = session_data[i - 1][0]
        prev_tail_ocv = np.mean([compute_ocv(r) for r in prev_raw[-30:]])
        prev_tail_ocv += (cumulative_offset - 0)  # adjust by prior cumulative

        # This session's first 30 stable points (after trim)
        this_head_ocv = np.mean([compute_ocv(r) for r in trimmed[:30]])

        offset = prev_tail_ocv - this_head_ocv
        cumulative_offset += offset
        print(f"{label}: trim={SESSIONS[i][1]}, head OCV={this_head_ocv:.1f}, "
              f"prev tail={prev_tail_ocv:.1f}, offset={offset:.1f}, "
              f"cumulative={cumulative_offset:.1f} mV")

        # Collect trimmed transient points (with same offset applied)
        trim_count = SESSIONS[i][1]
        for r in raw[:trim_count]:
            ah = float(r["ah_discharged"])
            soc = max(0.0, (1.0 - ah / USABLE_CAPACITY_AH) * 100.0)
            soc_trimmed.append(soc)
            ocv_trimmed.append((compute_ocv(r) + cumulative_offset) / 1000.0)

    for r in trimmed:
        v_mv = float(r["bus_voltage_mV"])
        if v_mv < 10000:  # skip BMS cutoff samples
            continue
        ah = float(r["ah_discharged"])
        soc = max(0.0, (1.0 - ah / USABLE_CAPACITY_AH) * 100.0)
        soc_stitched.append(soc)
        ocv_stitched.append((compute_ocv(r) + cumulative_offset) / 1000.0)

# === Empirical lookup table: extract median cell voltage at each SOC step ===
# Monotonic by construction — guaranteed one-to-one mapping, directly invertible.
x_soc = np.array(soc_stitched)
y_cell = np.array(ocv_stitched) / CELLS_SERIES * 1000  # cell mV

# Extract anchor points: 2.5% steps at endpoints (0-10%, 95-100%), 5% elsewhere
SOC_STEPS = (
    [0, 2.5, 5, 7.5, 10] +              # 2.5% steps: low knee
    list(range(15, 95, 5)) +              # 5% steps: plateau
    [95, 97.5, 100]                       # 2.5% steps: high knee
)
table = []
print(f"\nEmpirical Lookup Table (SOC → Cell Voltage):")
print(f"  {'SOC%':>5s}  {'cell_mV':>8s}  {'pack_mV':>8s}  {'points':>6s}")
for soc_target in SOC_STEPS:
    half_bin = 1.25 if (soc_target <= 10 or soc_target >= 95) else 2.5
    mask = np.abs(x_soc - soc_target) <= half_bin
    if np.sum(mask) >= 5:
        median_mv = np.median(y_cell[mask])
        table.append((soc_target, int(round(median_mv))))
        pack_mv = int(round(median_mv * CELLS_SERIES))
        print(f"  {soc_target:>5.1f}  {int(round(median_mv)):>8d}  {pack_mv:>8d}  {np.sum(mask):>6d}")

# Enforce strict monotonicity (voltage must increase with SOC)
for i in range(1, len(table)):
    if table[i][1] <= table[i - 1][1]:
        # Nudge up by 1 mV to maintain strict ordering
        table[i] = (table[i][0], table[i - 1][1] + 1)

print(f"\n  Table entries: {len(table)}")
print(f"  Python format for fuel gauge:")
print(f"  LFP_SOC_TABLE = [")
for soc, mv in reversed(table):  # high voltage first (matches existing format)
    soc_str = f"{soc:.1f}" if soc != int(soc) else f"{int(soc)}"
    print(f"      ({mv}, {soc_str}),")
print(f"  ]")

# Generate smooth curve from lookup table for plotting
soc_smooth = np.array([s for s, _ in table], dtype=float)
cell_smooth = np.array([mv for _, mv in table], dtype=float)
v_smooth = cell_smooth / 1000.0 * CELLS_SERIES

fig, ax = plt.subplots(figsize=(10, 6))
ax.scatter(soc_trimmed, ocv_trimmed, s=6, alpha=0.5, color="lightcoral",
           label="Trimmed (diffusion transients)", zorder=2)
ax.scatter(soc_stitched, ocv_stitched, s=4, alpha=0.6, color="steelblue",
           label="Stitched OCV", zorder=3)
ax.plot(soc_smooth, v_smooth, color="darkorange", linewidth=2, alpha=0.8,
        marker='o', markersize=5, label="Empirical lookup table", zorder=4)
ax.set_xlabel("SOC (%)")
ax.set_ylabel("Pack Voltage (V)")
ax.set_title("Battery A Discharge — OCV vs SOC (Renogy RBT2425LFP)")
ax.invert_xaxis()
ax.grid(True, alpha=0.3)
ax.legend(loc="upper right")
fig.tight_layout()

plot_path = os.path.join(results_dir, "voltage_vs_soc.png")
fig.savefig(plot_path, dpi=150)
print(f"\nPlot saved: {plot_path}")
