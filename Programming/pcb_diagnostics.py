"""
AutoNav Charge Indicator PCB Diagnostics
-----------------------------------------
Reads INA226 (U3) and BQ34Z100-R2 (U1) over I2C using Total Phase Aardvark.

INA226 Datasheet:  https://www.ti.com/lit/ds/symlink/ina226.pdf
BQ34Z100-R2 TRM:   https://www.ti.com/lit/pdf/sluuco5

Hardware:
  - INA226 (U3) at slave address 0x40
  - BQ34Z100-R2 (U1) at slave address 0x55
  - Shunt resistor R4 = 12 mOhm (RL1206FR-070R012L)
"""

import sys
import time
from array import array

try:
    from aardvark_py import *
except ImportError:
    print("ERROR: aardvark_py not installed.")
    print("Install via:  pip install aardvark_py")
    print("Or download from: https://www.totalphase.com/products/aardvark-software-api/")
    sys.exit(1)

# ---------------------------------------------------------------------------
# I2C slave addresses
# ---------------------------------------------------------------------------
INA226_ADDR   = 0x40
BQ34Z100_ADDR = 0x55

# ---------------------------------------------------------------------------
# INA226 register pointer addresses (Table 2, datasheet SBOS547B)
# All registers are 16-bit, big-endian (MSB first).
# ---------------------------------------------------------------------------
INA226_REG_CONFIG   = 0x00  # Configuration
INA226_REG_SHUNT_V  = 0x01  # Shunt Voltage   (LSB = 2.5 uV, signed)
INA226_REG_BUS_V    = 0x02  # Bus Voltage      (LSB = 1.25 mV, unsigned)
INA226_REG_POWER    = 0x03  # Power            (LSB = 25 * Current_LSB, unsigned)
INA226_REG_CURRENT  = 0x04  # Current          (LSB = Current_LSB, signed)
INA226_REG_CAL      = 0x05  # Calibration
INA226_REG_MASK_EN  = 0x06  # Mask / Enable
INA226_REG_ALERT    = 0x07  # Alert Limit
INA226_REG_MFR_ID   = 0xFE  # Manufacturer ID  (expect 0x5449 = "TI")
INA226_REG_DIE_ID   = 0xFF  # Die ID           (expect 0x2260)

# ---------------------------------------------------------------------------
# BQ34Z100-R2 standard command addresses (TRM SLUUCO5A)
# All standard commands return 16-bit little-endian (LSB first).
# ---------------------------------------------------------------------------
BQ_CMD_STATE_OF_CHARGE   = 0x03  # % (SOC byte at pointer 0x03)
BQ_CMD_MAX_ERROR         = 0x04  # %
BQ_CMD_REMAINING_CAP     = 0x06  # mAh
BQ_CMD_FULL_CHARGE_CAP   = 0x08  # mAh
BQ_CMD_VOLTAGE           = 0x0A  # mV
BQ_CMD_AVG_CURRENT       = 0x0C  # mA  (signed)
BQ_CMD_TEMPERATURE       = 0x0E  # 0.1 K
BQ_CMD_FLAGS             = 0x10
BQ_CMD_FLAGS_B           = 0x12
BQ_CMD_CURRENT           = 0x14  # mA  (signed, instantaneous)

# ---------------------------------------------------------------------------
# Shunt resistor value (R4 on schematic, CSR2512B0R005F / RL1206FR-070R012L)
# ---------------------------------------------------------------------------
R_SHUNT = 0.012  # 12 mOhm

# INA226 calibration constants (Section 7.5, datasheet)
# Current_LSB chosen so max measurable current ~ 8 A with headroom
# Current_LSB = Max_Expected_Current / 2^15
CURRENT_LSB = 0.00025       # 250 uA per bit
POWER_LSB   = 25 * CURRENT_LSB  # 6.25 mW per bit
CAL_VALUE   = int(0.00512 / (CURRENT_LSB * R_SHUNT))  # = 1706

I2C_BITRATE = 100  # kHz


# ===========================================================================
#  Aardvark I2C helpers
# ===========================================================================

def aardvark_open():
    """Find and open the first available Aardvark adapter."""
    (num, ports) = aa_find_devices(16)
    if num <= 0:
        print("ERROR: No Aardvark devices found.")
        sys.exit(1)

    # Strip the "in use" flag (bit 15) and try the first port
    all_ports = [p & 0x7FFF for p in ports[:num]]
    if not all_ports:
        print("ERROR: No Aardvark ports enumerated.")
        sys.exit(1)

    port = all_ports[0]
    handle = aa_open(port)
    if handle <= 0:
        print(f"ERROR: Could not open Aardvark on port {port} (error {handle}).")
        sys.exit(1)

    # Configure as I2C subsystem enabled
    aa_configure(handle, AA_CONFIG_SPI_I2C)
    aa_i2c_bitrate(handle, I2C_BITRATE)
    # Enable target power (provides pull-ups on SDA/SCL from Aardvark)
    aa_target_power(handle, AA_TARGET_POWER_BOTH)
    # Small delay for power to stabilize
    aa_sleep_ms(100)

    print(f"Aardvark opened on port {port}, I2C bitrate = {I2C_BITRATE} kHz")
    return handle


def i2c_write_read(handle, slave_addr, reg_addr, num_bytes):
    """
    Write a register pointer then read num_bytes from an I2C slave.

    Returns the raw bytes as a list of ints, or None on failure.
    """
    # Write the register pointer byte
    data_out = array('B', [reg_addr])
    count = aa_i2c_write(handle, slave_addr, AA_I2C_NO_STOP, data_out)
    if count < 0:
        print(f"  I2C write error to 0x{slave_addr:02X} reg 0x{reg_addr:02X}: {count}")
        return None

    # Read the response
    (count, data_in) = aa_i2c_read(handle, slave_addr, AA_I2C_NO_FLAGS, num_bytes)
    if count < 0:
        print(f"  I2C read error from 0x{slave_addr:02X} reg 0x{reg_addr:02X}: {count}")
        return None
    if count != num_bytes:
        print(f"  Warning: expected {num_bytes} bytes, got {count}")

    return list(data_in[:count])


def bytes_to_uint16_be(data):
    """Convert 2 bytes (big-endian, MSB first) to unsigned 16-bit int."""
    return (data[0] << 8) | data[1]


def bytes_to_int16_be(data):
    """Convert 2 bytes (big-endian, MSB first) to signed 16-bit int (two's complement)."""
    val = (data[0] << 8) | data[1]
    if val >= 0x8000:
        val -= 0x10000
    return val


def bytes_to_uint16_le(data):
    """Convert 2 bytes (little-endian, LSB first) to unsigned 16-bit int."""
    return data[0] | (data[1] << 8)


def bytes_to_int16_le(data):
    """Convert 2 bytes (little-endian, LSB first) to signed 16-bit int (two's complement)."""
    val = data[0] | (data[1] << 8)
    if val >= 0x8000:
        val -= 0x10000
    return val


# ===========================================================================
#  INA226 diagnostics
# ===========================================================================

def ina226_verify_id(handle):
    """Read and verify the INA226 Manufacturer and Die IDs."""
    mfr = i2c_write_read(handle, INA226_ADDR, INA226_REG_MFR_ID, 2)
    die = i2c_write_read(handle, INA226_ADDR, INA226_REG_DIE_ID, 2)

    ok = True
    if mfr:
        mfr_id = bytes_to_uint16_be(mfr)
        expected = 0x5449
        status = "OK" if mfr_id == expected else "MISMATCH"
        print(f"  Manufacturer ID : 0x{mfr_id:04X}  (expected 0x{expected:04X}) [{status}]")
        if mfr_id != expected:
            ok = False
    else:
        print("  Manufacturer ID : READ FAILED")
        ok = False

    if die:
        die_id = bytes_to_uint16_be(die)
        expected = 0x2260
        status = "OK" if die_id == expected else "MISMATCH"
        print(f"  Die ID          : 0x{die_id:04X}  (expected 0x{expected:04X}) [{status}]")
        if die_id != expected:
            ok = False
    else:
        print("  Die ID          : READ FAILED")
        ok = False

    return ok


def ina226_write_calibration(handle):
    """Write the calibration register so current and power readings are valid."""
    msb = (CAL_VALUE >> 8) & 0xFF
    lsb = CAL_VALUE & 0xFF
    data_out = array('B', [INA226_REG_CAL, msb, lsb])
    count = aa_i2c_write(handle, INA226_ADDR, AA_I2C_NO_FLAGS, data_out)
    if count < 0:
        print(f"  ERROR: Failed to write calibration register (error {count})")
        return False
    print(f"  Calibration register written: {CAL_VALUE} (0x{CAL_VALUE:04X})")
    return True


def ina226_read_config(handle):
    """Read and display the INA226 configuration register."""
    data = i2c_write_read(handle, INA226_ADDR, INA226_REG_CONFIG, 2)
    if data:
        config = bytes_to_uint16_be(data)
        print(f"  Configuration   : 0x{config:04X}")
        return config
    print("  Configuration   : READ FAILED")
    return None


def ina226_read_measurements(handle):
    """Read bus voltage, current, and power from the INA226."""
    results = {}

    # Bus Voltage (register 0x02) - unsigned, LSB = 1.25 mV
    data = i2c_write_read(handle, INA226_ADDR, INA226_REG_BUS_V, 2)
    if data:
        raw = bytes_to_uint16_be(data)
        voltage_v = raw * 1.25e-3
        results['bus_voltage_V'] = voltage_v
        print(f"  Bus Voltage     : {voltage_v:8.3f} V   (raw: 0x{raw:04X})")
    else:
        print("  Bus Voltage     : READ FAILED")

    # Current (register 0x04) - signed, LSB = Current_LSB
    data = i2c_write_read(handle, INA226_ADDR, INA226_REG_CURRENT, 2)
    if data:
        raw = bytes_to_int16_be(data)
        current_a = raw * CURRENT_LSB
        results['current_A'] = current_a
        print(f"  Current         : {current_a:8.4f} A   (raw: {raw})")
    else:
        print("  Current         : READ FAILED")

    # Power (register 0x03) - unsigned, LSB = 25 * Current_LSB
    data = i2c_write_read(handle, INA226_ADDR, INA226_REG_POWER, 2)
    if data:
        raw = bytes_to_uint16_be(data)
        power_w = raw * POWER_LSB
        results['power_W'] = power_w
        print(f"  Power           : {power_w:8.4f} W   (raw: 0x{raw:04X})")
    else:
        print("  Power           : READ FAILED")

    # Shunt Voltage (register 0x01) - signed, LSB = 2.5 uV
    data = i2c_write_read(handle, INA226_ADDR, INA226_REG_SHUNT_V, 2)
    if data:
        raw = bytes_to_int16_be(data)
        shunt_uv = raw * 2.5
        results['shunt_voltage_uV'] = shunt_uv
        print(f"  Shunt Voltage   : {shunt_uv:8.1f} uV  (raw: {raw})")
    else:
        print("  Shunt Voltage   : READ FAILED")

    return results


# ===========================================================================
#  BQ34Z100-R2 diagnostics
# ===========================================================================

def bq34z100_read_all(handle):
    """Read key battery parameters from the BQ34Z100-R2."""
    results = {}

    # State of Charge (pointer 0x03) - single byte, 0-100%
    data = i2c_write_read(handle, BQ34Z100_ADDR, BQ_CMD_STATE_OF_CHARGE, 1)
    if data:
        soc = data[0]
        results['soc_pct'] = soc
        print(f"  State of Charge : {soc:6d} %    (raw: 0x{data[0]:02X})")
    else:
        print("  State of Charge : READ FAILED")

    # Voltage (command 0x0A) - mV (unsigned)
    data = i2c_write_read(handle, BQ34Z100_ADDR, BQ_CMD_VOLTAGE, 2)
    if data:
        voltage_mv = bytes_to_uint16_le(data)
        results['voltage_mV'] = voltage_mv
        print(f"  Battery Voltage : {voltage_mv:6d} mV   (raw: 0x{data[1]:02X}{data[0]:02X})")
    else:
        print("  Battery Voltage : READ FAILED")

    # Average Current (command 0x0C) - mA (signed)
    data = i2c_write_read(handle, BQ34Z100_ADDR, BQ_CMD_AVG_CURRENT, 2)
    if data:
        current_ma = bytes_to_int16_le(data)
        results['avg_current_mA'] = current_ma
        print(f"  Avg Current     : {current_ma:6d} mA   (raw: 0x{data[1]:02X}{data[0]:02X})")
    else:
        print("  Avg Current     : READ FAILED")

    # Instantaneous Current (command 0x14) - mA (signed)
    data = i2c_write_read(handle, BQ34Z100_ADDR, BQ_CMD_CURRENT, 2)
    if data:
        current_ma = bytes_to_int16_le(data)
        results['inst_current_mA'] = current_ma
        print(f"  Inst. Current   : {current_ma:6d} mA   (raw: 0x{data[1]:02X}{data[0]:02X})")
    else:
        print("  Inst. Current   : READ FAILED")

    # Temperature (command 0x0E) - 0.1 K
    data = i2c_write_read(handle, BQ34Z100_ADDR, BQ_CMD_TEMPERATURE, 2)
    if data:
        raw = bytes_to_uint16_le(data)
        temp_k = raw * 0.1
        temp_c = temp_k - 273.15
        results['temperature_C'] = temp_c
        print(f"  Temperature     : {temp_c:6.1f} C    ({temp_k:.1f} K)")
    else:
        print("  Temperature     : READ FAILED")

    # Remaining Capacity (command 0x06) - mAh
    data = i2c_write_read(handle, BQ34Z100_ADDR, BQ_CMD_REMAINING_CAP, 2)
    if data:
        cap = bytes_to_uint16_le(data)
        results['remaining_mAh'] = cap
        print(f"  Remaining Cap   : {cap:6d} mAh")
    else:
        print("  Remaining Cap   : READ FAILED")

    # Full Charge Capacity (command 0x08) - mAh
    data = i2c_write_read(handle, BQ34Z100_ADDR, BQ_CMD_FULL_CHARGE_CAP, 2)
    if data:
        cap = bytes_to_uint16_le(data)
        results['full_charge_mAh'] = cap
        print(f"  Full Charge Cap : {cap:6d} mAh")
    else:
        print("  Full Charge Cap : READ FAILED")

    # Flags (command 0x10)
    data = i2c_write_read(handle, BQ34Z100_ADDR, BQ_CMD_FLAGS, 2)
    if data:
        flags = bytes_to_uint16_le(data)
        results['flags'] = flags
        print(f"  Flags           : 0x{flags:04X}")
        _decode_bq_flags(flags)
    else:
        print("  Flags           : READ FAILED")

    return results


def _decode_bq_flags(flags):
    """Decode BQ34Z100-R2 Flags register bits (Table 4, TRM)."""
    flag_bits = [
        (15, "OTC",    "Over-Temperature in Charge"),
        (14, "OTD",    "Over-Temperature in Discharge"),
        (11, "CHG_INH","Charge Inhibit"),
        (9,  "FC",     "Full Charge detected"),
        (8,  "CHG",    "Fast Charging allowed"),
        (3,  "SOC1",   "State-of-Charge Threshold 1 reached"),
        (2,  "SOCF",   "State-of-Charge Final threshold reached"),
        (1,  "DSG",    "Discharging detected"),
    ]
    active = []
    for bit, name, desc in flag_bits:
        if flags & (1 << bit):
            active.append(f"    [{name}] {desc}")
    if active:
        for line in active:
            print(line)


# ===========================================================================
#  Main diagnostic routine
# ===========================================================================

def run_diagnostics():
    separator = "=" * 60
    print()
    print(separator)
    print("  AutoNav Charge Indicator - PCB Diagnostics")
    print(separator)
    print()

    handle = aardvark_open()
    print()

    # --- INA226 ---
    print(separator)
    print(f"  INA226 (U3) @ I2C 0x{INA226_ADDR:02X}")
    print(f"  Shunt Resistor R4 = {R_SHUNT * 1000:.0f} mOhm")
    print(separator)

    id_ok = ina226_verify_id(handle)
    if not id_ok:
        print("  WARNING: INA226 ID check failed - chip may not be responding.")
        print("           Check solder joints and I2C pull-ups.")

    ina226_read_config(handle)

    print(f"\n  Writing calibration (Current_LSB = {CURRENT_LSB * 1e6:.0f} uA)...")
    ina226_write_calibration(handle)
    # Wait for a conversion cycle after calibration
    aa_sleep_ms(50)

    print("\n  --- Measurements ---")
    ina226_results = ina226_read_measurements(handle)
    print()

    # --- BQ34Z100-R2 ---
    print(separator)
    print(f"  BQ34Z100-R2 (U1) @ I2C 0x{BQ34Z100_ADDR:02X}")
    print(separator)

    bq_results = bq34z100_read_all(handle)
    print()

    # --- Summary ---
    print(separator)
    print("  DIAGNOSTIC SUMMARY")
    print(separator)

    if 'bus_voltage_V' in ina226_results:
        v = ina226_results['bus_voltage_V']
        print(f"  INA226 Bus Voltage  : {v:.3f} V")
    if 'current_A' in ina226_results:
        i = ina226_results['current_A']
        print(f"  INA226 Current      : {i:.4f} A  ({i * 1000:.1f} mA)")
    if 'power_W' in ina226_results:
        p = ina226_results['power_W']
        print(f"  INA226 Power        : {p:.4f} W  ({p * 1000:.1f} mW)")

    if 'soc_pct' in bq_results:
        print(f"  Battery Charge      : {bq_results['soc_pct']}%")
    if 'voltage_mV' in bq_results:
        print(f"  Battery Voltage     : {bq_results['voltage_mV']} mV")
    if 'temperature_C' in bq_results:
        print(f"  Battery Temperature : {bq_results['temperature_C']:.1f} C  (no thermistor)")
    if 'remaining_mAh' in bq_results and 'full_charge_mAh' in bq_results:
        rem = bq_results['remaining_mAh']
        full = bq_results['full_charge_mAh']
        print(f"  Capacity            : {rem} / {full} mAh")

    # Basic sanity checks
    print()
    issues = []
    if not id_ok:
        issues.append("INA226 not responding or ID mismatch")
    if 'bus_voltage_V' in ina226_results and ina226_results['bus_voltage_V'] < 0.5:
        issues.append("INA226 bus voltage very low - check VBUS connection")
    if 'soc_pct' in bq_results and bq_results['soc_pct'] == 0:
        issues.append("BQ34Z100 reports 0% SOC - battery may be depleted or gauge uncalibrated")
    # No thermistor on PCB - temperature reading is not valid
    if 'voltage_mV' in bq_results and bq_results['voltage_mV'] == 0:
        issues.append("BQ34Z100 reports 0 mV - no battery connected (gauge data may be defaults)")

    if issues:
        print("  ISSUES DETECTED:")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print("  All readings nominal.")

    print()
    print(separator)

    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    print("  Aardvark closed.\n")


if __name__ == "__main__":
    run_diagnostics()
