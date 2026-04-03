"""INA226 Discharge Logger — Empirical voltage-vs-SOC curve capture.

Logs INA226 readings to CSV as Battery A (Renogy RBT2425LFP, 100% charged)
discharges through the robot's normal load. The CSV provides the real
voltage-vs-Ah-discharged curve for calibrating the fuel gauge SOC table.

Output: discharge_log_YYYYMMDD_HHMMSS.csv in the same directory.
Press Ctrl+C to stop. Stops automatically at 20.0V (BMS cutoff).

Hardware: INA226 at 0x40, 12mOhm shunt (R4), Aardvark I2C adapter
Battery: Renogy RBT2425LFP — LiFePO4 8S7P, 25Ah, 25.6V nom, 29.0V charge
"""
import sys, os, time, csv
from datetime import datetime
from array import array

sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *

# INA226 config
INA = 0x40
SHUNT_R = 0.012
CURRENT_LSB = 250e-6
POWER_LSB = CURRENT_LSB * 25
CAL_REG = 1706

# Battery specs
PACK_CAPACITY_AH = 25.0
CELLS_SERIES = 8
V_BMS_CUTOFF = 20.0  # BMS undervoltage protection

# Sampling interval (seconds)
SAMPLE_INTERVAL_S = 2.5  # 0.4 Hz

# Session 1 carryover (Battery A idle discharge 2h, 2026-04-01)
AH_OFFSET = 2.395


# === I2C Setup ===
handle = aa_open(0)
if handle < 0:
    print(f"Aardvark open failed: {handle}")
    exit(1)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(500)


def ina_write_reg(reg, value):
    d = array('B', [reg, (value >> 8) & 0xFF, value & 0xFF])
    return aa_i2c_write(handle, INA, AA_I2C_NO_FLAGS, d)


def ina_read_reg(reg, signed=False):
    d = array('B', [reg])
    aa_i2c_write(handle, INA, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
    if rc != 2:
        return None
    val = (data[0] << 8) | data[1]
    if signed and val >= 0x8000:
        val -= 0x10000
    return val


def ina_read_bus_mv():
    raw = ina_read_reg(0x02)
    return int(raw * 1.25) if raw is not None else None


def ina_read_current_ma():
    """Negated: positive = charging, negative = discharging."""
    raw = ina_read_reg(0x04, signed=True)
    return -raw * CURRENT_LSB * 1000 if raw is not None else None


def ina_read_shunt_uv():
    raw = ina_read_reg(0x01, signed=True)
    return raw * 2.5 if raw is not None else None


def ina_read_power_mw():
    raw = ina_read_reg(0x03)
    return raw * POWER_LSB if raw is not None else None


# === Verify INA226 ===
mfg = ina_read_reg(0xFE)
die = ina_read_reg(0xFF)
if mfg != 0x5449 or die != 0x2260:
    print(f"INA226 ID check failed: MFG=0x{mfg:04X} DIE=0x{die:04X}")
    aa_close(handle)
    exit(1)

# Configure: 16 averages, 1.1ms conversion, continuous shunt+bus
ina_write_reg(0x00, 0x4427)
ina_write_reg(0x05, CAL_REG)
aa_sleep_ms(100)

# Initial reading
bus_mv = ina_read_bus_mv()
if bus_mv is None:
    print("INA226 not responding!")
    aa_close(handle)
    exit(1)

# === CSV Setup (append to session 1 CSV) ===
script_dir = os.path.dirname(os.path.abspath(__file__))
results_dir = os.path.join(script_dir, "..", "empirical_results")
os.makedirs(results_dir, exist_ok=True)
csv_path = os.path.join(results_dir, "discharge_log_20260401_175518.csv")

# Append mode — header already exists from session 1
csvfile = open(csv_path, 'a', newline='')
writer = csv.writer(csvfile)

# === State ===
ah_discharged = AH_OFFSET
last_time = time.time()
start_time = last_time
sample_count = 0

print("=" * 78)
print("  INA226 Discharge Logger — Battery A (Renogy RBT2425LFP)")
print("=" * 78)
print(f"  CSV: {csv_path}")
print(f"  Initial voltage: {bus_mv} mV ({bus_mv/CELLS_SERIES:.0f} mV/cell)")
print(f"  Sampling every {SAMPLE_INTERVAL_S}s | Stops at {V_BMS_CUTOFF}V BMS cutoff")
print(f"  Assuming 100% SOC at start ({PACK_CAPACITY_AH} Ah)")
print()
print(f"  {'Time':>8s}  {'Bus V':>8s}  {'Cell':>7s}  {'Current':>9s}  "
      f"{'Power':>8s}  {'Ah Out':>7s}  {'SOC':>6s}")
print(f"  {'':>8s}  {'(mV)':>8s}  {'(mV)':>7s}  {'(mA)':>9s}  "
      f"{'(mW)':>8s}  {'(Ah)':>7s}  {'(%)':>6s}")
print("  " + "-" * 76)
sys.stdout.flush()

try:
    while True:
        now = time.time()
        dt_s = now - last_time
        last_time = now
        elapsed = now - start_time

        bus_mv = ina_read_bus_mv()
        current_ma = ina_read_current_ma()
        shunt_uv = ina_read_shunt_uv()
        power_mw = ina_read_power_mw()

        if bus_mv is None or current_ma is None:
            print(f"  {'---':>8s}  INA226 READ FAILED")
            aa_sleep_ms(int(SAMPLE_INTERVAL_S * 1000))
            continue

        cell_mv = bus_mv / CELLS_SERIES

        # Coulomb counting (discharge current is negative, so ah_discharged grows)
        if dt_s < 60:  # skip huge gaps (first sample, reconnects)
            ah_discharged += abs(current_ma) / 1000.0 * dt_s / 3600.0

        soc_pct = max(0.0, (1.0 - ah_discharged / PACK_CAPACITY_AH) * 100.0)

        # Format elapsed time
        hrs = int(elapsed // 3600)
        mins = int((elapsed % 3600) // 60)
        secs = int(elapsed % 60)
        ts = f"{hrs}:{mins:02d}:{secs:02d}"

        # Write CSV row
        writer.writerow([
            f"{elapsed:.1f}", datetime.now().isoformat(),
            bus_mv, f"{cell_mv:.1f}",
            f"{current_ma:.1f}", f"{shunt_uv:.1f}", f"{power_mw:.1f}",
            f"{ah_discharged:.4f}", f"{soc_pct:.2f}"
        ])
        csvfile.flush()

        sample_count += 1

        # Console output (every sample)
        print(f"  {ts:>8s}  {bus_mv:>8d}  {cell_mv:>7.0f}  {current_ma:>9.1f}  "
              f"{power_mw:>8.1f}  {ah_discharged:>7.3f}  {soc_pct:>5.1f}%")
        sys.stdout.flush()

        # BMS cutoff check
        if bus_mv <= V_BMS_CUTOFF * 1000:
            print(f"\n  *** BMS CUTOFF: {bus_mv} mV <= {V_BMS_CUTOFF*1000:.0f} mV ***")
            break

        aa_sleep_ms(int(SAMPLE_INTERVAL_S * 1000))

except KeyboardInterrupt:
    pass

# === Summary ===
elapsed = time.time() - start_time
hrs = int(elapsed // 3600)
mins = int((elapsed % 3600) // 60)
print(f"\n  Stopped after {hrs}h {mins}m ({sample_count} samples)")
print(f"  Total Ah discharged: {ah_discharged:.3f} Ah")
print(f"  Final SOC: {soc_pct:.1f}%")
print(f"  Final voltage: {bus_mv} mV ({bus_mv/CELLS_SERIES:.0f} mV/cell)")
print(f"  CSV saved: {csv_path}")

csvfile.close()
aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("  Done.")
