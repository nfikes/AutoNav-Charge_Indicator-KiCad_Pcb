"""INA226-Based Fuel Gauge for LiFePO4 8S 25Ah Pack.

Since the BQ34Z100-R2 ADC can't measure voltage through the divider,
this implements a complete fuel gauge using only the INA226:

  - Bus voltage measurement (pack voltage)
  - Current measurement (via 12mOhm shunt R4)
  - Coulomb counting (integrate current over time)
  - Voltage-based SOC estimation (for initial estimate + recalibration)
  - Peukert correction for rate-dependent capacity
  - Charge termination detection (CC-CV with tail current)
  - BMS protection threshold warnings

Target Battery: Renogy RBT2425LFP (from datasheet + user manual)
  - Chemistry: LiFePO4 (8S7P)
  - Nominal: 25.6V (8 x 3.2V)
  - Charge voltage: 29.0V +/- 0.2V (CC-CV, tail current 1.25A)
  - Charge cutoff: 29.2V (BMS overvoltage protection)
  - Discharge cutoff: 20.0V (8 x 2.5V, BMS undervoltage protection)
  - Rated capacity: 25Ah @ 0.2C (5A)
  - Max charge current: 25A (1C)
  - Max discharge current: 25A continuous
  - Peukert exponent: 1.05
  - Internal resistance: <= 40 mOhm
  - BMS overcurrent: 27.5A

Hardware: INA226 at 0x40, 12mOhm shunt (R4), Aardvark I2C adapter

Press Ctrl+C to stop. Displays live readings + SOC estimate.
"""
import sys, os, time, struct, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *
from array import array

INA = 0x40
SHUNT_R = 0.012       # 12 mOhm
CURRENT_LSB = 250e-6  # 250 uA per bit
POWER_LSB = CURRENT_LSB * 25  # 6.25 mW per bit
CAL_REG = 1706        # 0.00512 / (CURRENT_LSB * SHUNT_R)

# ============================================================================
#  Renogy RBT2425LFP — LiFePO4 8S7P 25Ah (from datasheet)
# ============================================================================
PACK_CAPACITY_MAH = 25000.0   # 25Ah rated at 0.2C (5A)
CELLS_SERIES = 8
CELLS_PARALLEL = 7
RATED_C_RATE = 0.2            # Capacity rated at 0.2C = 5A

# Pack voltage thresholds (from datasheet)
V_CHARGE_TARGET = 29.0        # CC-CV charge voltage (29.0 +/- 0.2V)
V_CHARGE_CUTOFF = 29.2        # BMS overvoltage protection
V_NOMINAL = 25.6              # 8 x 3.20V
V_EMPTY = 20.0                # BMS undervoltage protection (8 x 2.50V)
V_STORAGE = 26.4              # ~50% SOC for long-term storage (8 x 3.30V)

# Per-cell limits (from BMS specs)
CELL_V_MAX = 3.80             # BMS cell overvoltage (V)
CELL_V_MIN = 2.50             # BMS cell undervoltage (V)

# Current limits
I_CHARGE_MAX_MA = 25000.0     # 25A max charge (1C)
I_DISCHARGE_MAX_MA = 25000.0  # 25A max continuous discharge
I_BMS_OVERCURRENT_MA = 27500.0  # 27.5A BMS overcurrent trip
I_TAIL_MA = 1250.0            # 1.25A charge termination (tail current)

# Peukert correction
PEUKERT_EXP = 1.05            # From datasheet
PEUKERT_REF_I_MA = 5000.0     # Reference rate: 0.2C = 5A

# Internal resistance
R_INTERNAL_MOHM = 40.0        # <= 40 mOhm (from datasheet)

# LiFePO4 voltage-to-SOC lookup table (per-cell, mV)
# LFP has a very flat discharge curve — voltage is a poor SOC indicator
# in the 20-80% region but useful at endpoints. From Renogy discharge curves.
LFP_SOC_TABLE = [
    # (cell_mV, SOC%)
    (3650, 100),   # Fully charged (CV phase complete)
    (3450, 99),    # Just off charger
    (3380, 95),    # Settling after charge
    (3350, 90),
    (3340, 80),
    (3330, 70),    # LFP plateau region begins
    (3320, 60),
    (3310, 50),
    (3300, 40),
    (3280, 30),    # LFP plateau region ends
    (3200, 20),
    (3100, 14),    # Knee — voltage starts dropping faster
    (3000, 9),
    (2900, 5),
    (2800, 3),
    (2600, 1),
    (2500, 0),     # BMS cutoff
]


def voltage_to_soc(pack_mv):
    """Estimate SOC from pack voltage using LFP lookup table."""
    cell_mv = pack_mv / CELLS_SERIES
    if cell_mv >= LFP_SOC_TABLE[0][0]:
        return 100.0
    if cell_mv <= LFP_SOC_TABLE[-1][0]:
        return 0.0
    for i in range(len(LFP_SOC_TABLE) - 1):
        v_hi, soc_hi = LFP_SOC_TABLE[i]
        v_lo, soc_lo = LFP_SOC_TABLE[i + 1]
        if v_lo <= cell_mv <= v_hi:
            frac = (cell_mv - v_lo) / (v_hi - v_lo)
            return soc_lo + frac * (soc_hi - soc_lo)
    return 50.0  # fallback


def peukert_capacity(current_ma):
    """Adjusted capacity at a given discharge rate using Peukert's law.

    C_eff = C_rated * (I_rated / I_actual) ^ (k - 1)

    At 0.2C (5A), full 25Ah. At higher rates, effective capacity decreases.
    With k=1.05 (LFP, very mild), capacity loss is small:
      - At 0.2C (5A):  25.00 Ah
      - At 0.5C (12.5A): 24.3 Ah
      - At 1C (25A):   23.6 Ah
    """
    if abs(current_ma) < 100:
        return PACK_CAPACITY_MAH  # Negligible current, no correction
    ratio = PEUKERT_REF_I_MA / abs(current_ma)
    return PACK_CAPACITY_MAH * (ratio ** (PEUKERT_EXP - 1))


# ============================================================================
#  INA226 Register Access
# ============================================================================

handle = aa_open(0)
if handle < 0:
    print(f"Aardvark open failed: {handle}")
    exit(1)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(500)


def ina_write_reg(reg, value):
    """Write 16-bit register (big-endian)."""
    d = array('B', [reg, (value >> 8) & 0xFF, value & 0xFF])
    return aa_i2c_write(handle, INA, AA_I2C_NO_FLAGS, d)


def ina_read_reg(reg, signed=False):
    """Read 16-bit register (big-endian)."""
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
    """Read bus voltage in mV. LSB = 1.25 mV."""
    raw = ina_read_reg(0x02)
    if raw is None:
        return None
    return int(raw * 1.25)


def ina_read_current_ma():
    """Read current in mA. LSB = CURRENT_LSB = 0.25 mA."""
    raw = ina_read_reg(0x04, signed=True)
    if raw is None:
        return None
    return raw * CURRENT_LSB * 1000  # convert to mA


def ina_read_power_mw():
    """Read power in mW. LSB = POWER_LSB = 6.25 mW."""
    raw = ina_read_reg(0x03)
    if raw is None:
        return None
    return raw * POWER_LSB


def ina_read_shunt_uv():
    """Read shunt voltage in uV. LSB = 2.5 uV."""
    raw = ina_read_reg(0x01, signed=True)
    if raw is None:
        return None
    return raw * 2.5


# ============================================================================
#  Initialize INA226
# ============================================================================

# Verify INA226 identity
mfg = ina_read_reg(0xFE)
die = ina_read_reg(0xFF)
if mfg != 0x5449 or die != 0x2260:
    print(f"INA226 ID check failed: MFG=0x{mfg:04X} DIE=0x{die:04X}")
    print("Expected: MFG=0x5449 DIE=0x2260")
    aa_close(handle)
    exit(1)

# Configure: 16 averages, 1.1ms bus + shunt conversion, continuous both
# Config register (0x00):
#   Bits 11-9: AVG = 010 (16 averages)
#   Bits 8-6:  VBUSCT = 100 (1.1ms)
#   Bits 5-3:  VSHCT = 100 (1.1ms)
#   Bits 2-0:  MODE = 111 (continuous shunt + bus)
config = (0b010 << 9) | (0b100 << 6) | (0b100 << 3) | 0b111  # 0x4427
ina_write_reg(0x00, config)

# Write calibration register
ina_write_reg(0x05, CAL_REG)
aa_sleep_ms(100)

# Initial readings
bus_mv = ina_read_bus_mv()
current_ma = ina_read_current_ma()

if bus_mv is None:
    print("INA226 not responding!")
    aa_close(handle)
    exit(1)

# ============================================================================
#  Coulomb Counter State
# ============================================================================

# Initialize SOC from voltage
initial_soc = voltage_to_soc(bus_mv)
coulomb_mah = initial_soc / 100.0 * PACK_CAPACITY_MAH
last_time = time.time()

# Charge state tracking
charge_state = "IDLE"  # IDLE, CHARGING_CC, CHARGING_CV, FULL, DISCHARGING
cv_start_time = None

print("=" * 86)
print("  INA226 Fuel Gauge — Renogy RBT2425LFP (LiFePO4 8S7P 25Ah)")
print("=" * 86)
print(f"  Shunt: {SHUNT_R*1000:.0f} mOhm | CAL: {CAL_REG} | Current LSB: {CURRENT_LSB*1e6:.0f} uA")
print(f"  Peukert exponent: {PEUKERT_EXP} | Tail current: {I_TAIL_MA:.0f} mA")
print(f"  Initial voltage: {bus_mv} mV | Initial SOC (voltage): {initial_soc:.1f}%")
print(f"  Coulomb counter initialized to {coulomb_mah:.0f} mAh")
print()
print(f"  {'Time':>6s}  {'Bus V':>8s}  {'Cell V':>7s}  {'Shunt':>8s}  "
      f"{'Current':>8s}  {'Power':>8s}  {'SOC_V':>6s}  {'SOC_C':>6s}  "
      f"{'Coulombs':>9s}  {'State':>6s}")
print(f"  {'':>6s}  {'(mV)':>8s}  {'(mV)':>7s}  {'(uV)':>8s}  "
      f"{'(mA)':>8s}  {'(mW)':>8s}  {'(%)':>6s}  {'(%)':>6s}  "
      f"{'(mAh)':>9s}  {'':>6s}")
print("  " + "-" * 84)
sys.stdout.flush()

start = time.time()
sample_count = 0
max_current = 0
min_voltage = 99999
max_voltage = 0
warnings_printed = set()

try:
    while True:
        now = time.time()
        dt_s = now - last_time
        last_time = now

        elapsed = now - start
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        ts = f"{mins:2d}:{secs:02d}"

        # Read all INA226 values
        bus_mv = ina_read_bus_mv()
        current_ma = ina_read_current_ma()
        power_mw = ina_read_power_mw()
        shunt_uv = ina_read_shunt_uv()

        if bus_mv is None or current_ma is None:
            print(f"  {ts:>6s}  --- INA226 READ FAILED ---")
            aa_sleep_ms(1000)
            continue

        # --- Charge state detection ---
        cell_mv = bus_mv / CELLS_SERIES
        if current_ma > 100:  # Charging (positive = into battery)
            if bus_mv >= V_CHARGE_TARGET * 1000:
                if charge_state != "CHARGING_CV":
                    cv_start_time = now
                charge_state = "CHARGING_CV"
                if current_ma <= I_TAIL_MA:
                    charge_state = "FULL"
                    coulomb_mah = PACK_CAPACITY_MAH  # Recalibrate at 100%
            else:
                charge_state = "CHARGING_CC"
        elif current_ma < -100:  # Discharging
            charge_state = "DISCH"
            if charge_state == "FULL":
                pass  # Keep FULL until discharge starts
        else:
            if charge_state not in ("FULL",):
                charge_state = "IDLE"

        # --- Coulomb counting with Peukert correction ---
        if abs(current_ma) > 50:  # Dead zone for noise
            if current_ma < 0:  # Discharging — apply Peukert
                eff_cap = peukert_capacity(current_ma)
                scale = PACK_CAPACITY_MAH / eff_cap
                delta_mah = current_ma * scale * dt_s / 3600.0
            else:  # Charging — assume ~99.5% coulombic efficiency for LFP
                delta_mah = current_ma * 0.995 * dt_s / 3600.0
            coulomb_mah += delta_mah

        # Clamp
        coulomb_mah = max(0.0, min(PACK_CAPACITY_MAH, coulomb_mah))

        # SOC estimates
        soc_voltage = voltage_to_soc(bus_mv)
        soc_coulomb = (coulomb_mah / PACK_CAPACITY_MAH) * 100.0

        # --- BMS protection warnings ---
        if bus_mv >= V_CHARGE_CUTOFF * 1000 and "OV" not in warnings_printed:
            print(f"\n  *** WARNING: Pack voltage {bus_mv}mV >= {V_CHARGE_CUTOFF*1000:.0f}mV "
                  f"(BMS overvoltage) ***\n")
            warnings_printed.add("OV")
        if bus_mv <= V_EMPTY * 1000 and "UV" not in warnings_printed:
            print(f"\n  *** WARNING: Pack voltage {bus_mv}mV <= {V_EMPTY*1000:.0f}mV "
                  f"(BMS undervoltage cutoff) ***\n")
            warnings_printed.add("UV")
        if abs(current_ma) >= I_BMS_OVERCURRENT_MA and "OC" not in warnings_printed:
            print(f"\n  *** WARNING: Current {current_ma:.0f}mA >= {I_BMS_OVERCURRENT_MA:.0f}mA "
                  f"(BMS overcurrent) ***\n")
            warnings_printed.add("OC")

        # Track min/max
        abs_current = abs(current_ma)
        if abs_current > max_current:
            max_current = abs_current
        if bus_mv < min_voltage:
            min_voltage = bus_mv
        if bus_mv > max_voltage:
            max_voltage = bus_mv

        sample_count += 1

        # State abbreviation
        st = charge_state[:6]

        # Format output
        cur_str = f"{current_ma:8.1f}" if current_ma is not None else "    FAIL"
        pwr_str = f"{power_mw:8.1f}" if power_mw is not None else "    FAIL"
        shu_str = f"{shunt_uv:8.1f}" if shunt_uv is not None else "    FAIL"

        print(f"  {ts:>6s}  {bus_mv:>8d}  {cell_mv:>7.0f}  {shu_str}  "
              f"{cur_str}  {pwr_str}  {soc_voltage:>5.1f}%  {soc_coulomb:>5.1f}%  "
              f"{coulomb_mah:>8.0f}  {st:>6s}")
        sys.stdout.flush()

        aa_sleep_ms(2000)

except KeyboardInterrupt:
    elapsed = time.time() - start
    print(f"\n\n  Stopped after {elapsed:.0f}s ({sample_count} samples)")
    print(f"  Voltage range: {min_voltage} - {max_voltage} mV")
    print(f"  Max current: {max_current:.1f} mA")
    print(f"  Final SOC (voltage): {soc_voltage:.1f}%")
    print(f"  Final SOC (coulomb): {soc_coulomb:.1f}%")
    print(f"  Coulomb counter: {coulomb_mah:.0f} / {PACK_CAPACITY_MAH:.0f} mAh")
    print(f"  Charge state: {charge_state}")
    eff = peukert_capacity(max_current) if max_current > 100 else PACK_CAPACITY_MAH
    print(f"  Peukert effective capacity at peak load: {eff:.0f} mAh")

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\n  Done.")
