"""
AutoNav Charge Indicator PCB Diagnostics
-----------------------------------------
Reads INA226 (U3) and BQ34Z100-R2 (U1) over I2C using Total Phase Aardvark.

INA226 Datasheet:  https://www.ti.com/lit/ds/symlink/ina226.pdf
BQ34Z100-R2 TRM:   https://www.ti.com/lit/pdf/sluuco5

Hardware:
  - INA226 (U3) at slave address 0x45
  - BQ34Z100-R2 (U1) at slave address 0x55
  - Shunt resistor R4 = 10 mOhm (WSL1206R0100JEA) — INA226 current sense
  - Sense resistor R26 = 5 mOhm (WSL25125L000FEA) — BQ34Z100-R2 low-side sense
  - Thermistor: Murata NCP18XH103D03RB — 10kΩ NTC, B25/85 = 3434K
"""

import time
import struct
from hw_common import *

# ---------------------------------------------------------------------------
# Shunt resistor value (R4 on schematic, WSL1206R0100JEA — INA226)
# ---------------------------------------------------------------------------
R_SHUNT = 0.010  # 10 mOhm
BQ_SENSE_R_MOHM = 5  # R26: WSL25125L000FEA, 5 mOhm (low-side sense for BQ34Z100-R2)

# ---------------------------------------------------------------------------
# Thermistor: Murata NCP18XH103D03RB (490-11813-1-ND)
#   10 kOhm NTC, B25/85 = 3434 K, 0603, 0.5% resistance tolerance
# ---------------------------------------------------------------------------
THERM_R25  = 10000   # Resistance at 25°C (ohms)
THERM_BETA = 3434    # B25/85 constant (K)
THERM_T0   = 298.15  # 25°C in Kelvin

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
    # TODO: Temperature reads garbage (~27.5 K) because R18 (thermistor) shares
    #       its ground path with R17/R19 and R1/R2/R3 networks, adding series
    #       resistance the BQ sees on the TS pin.  Needs PCB redesign to give
    #       R18 a clean path: TS → thermistor → 1µF cap → AGND (per TI ref).
    data = i2c_write_read(handle, BQ34Z100_ADDR, BQ_CMD_TEMPERATURE, 2)
    if data:
        raw = bytes_to_uint16_le(data)
        temp_k = raw * 0.1
        temp_c = temp_k - 273.15
        temp_f = temp_c * 9.0 / 5.0 + 32.0
        results['temperature_C'] = temp_c
        results['temperature_F'] = temp_f
        results['temperature_K'] = temp_k
        print(f"  Temperature     : {temp_c:6.1f} C / {temp_f:.1f} F  ({temp_k:.1f} K)")
        if temp_c < -40 or temp_c > 125:
            print(f"    (INVALID — thermistor circuit needs PCB rework)")
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
#  BQ34Z100-R2 calibration helpers
# ===========================================================================

def bq_wake(handle):
    """Wake BQ34Z100-R2 from SLEEP by sending repeated dummy writes.

    The BQ NACKs the first I2C transaction after sleeping and needs a
    second write + delay before it starts ACKing reads.  This function
    retries until the device responds or gives up after several attempts.

    NOTE: This writes to register 0x00 (Control) and reads Voltage.
    Do NOT use before Data Flash access — use bq_wake_for_df() instead.
    """
    for attempt in range(4):
        data_out = array('B', [0x00])
        aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, data_out)
        aa_sleep_ms(50 * (attempt + 1))

        # Check if the device is responding by reading Voltage (0x0A)
        data_out = array('B', [BQ_CMD_VOLTAGE])
        aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_STOP, data_out)
        (count, _) = aa_i2c_read(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, 2)
        if count == 2:
            print(f"  BQ34Z100-R2 awake (after {attempt + 1} pulse(s)).")
            return True

    print("  WARNING: BQ34Z100-R2 did not respond after wake attempts.")
    return False


def bq_wake_for_df(handle):
    """Wake BQ34Z100-R2 without touching the Control register (0x00).

    Uses BlockDataControl (0x61) as the wake target to avoid switching
    the BQ out of block-data mode.  Returns True if device responds.
    """
    for attempt in range(4):
        # Write 0x00 to BlockDataControl (0x61) — both wakes and sets up DF mode
        data_out = array('B', [BQ_BLOCK_DATA_CONTROL, 0x00])
        count = aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, data_out)
        aa_sleep_ms(30 * (attempt + 1))

        if count >= 0:
            # Verify device responds by reading the checksum register
            ck = i2c_write_read(handle, BQ34Z100_ADDR, BQ_BLOCK_DATA_CKSUM, 1)
            if ck is not None and len(ck) == 1:
                return True

    print("  WARNING: BQ34Z100-R2 did not respond (DF wake).")
    return False


def bq_write_control(handle, subcmd):
    """Write a 16-bit sub-command to BQ Control register (0x00), little-endian."""
    lsb = subcmd & 0xFF
    msb = (subcmd >> 8) & 0xFF
    data_out = array('B', [0x00, lsb, msb])
    count = aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, data_out)
    if count < 0:
        print(f"  ERROR: Control write 0x{subcmd:04X} failed (error {count})")
        return False
    return True


def bq_read_control_status(handle):
    """Read Control Status word and decode seal state.

    Returns (status_word, is_sealed, is_full_access) or (None, None, None) on failure.
    """
    bq_write_control(handle, BQ_SUBCMD_CONTROL_STATUS)
    aa_sleep_ms(5)
    data = i2c_write_read(handle, BQ34Z100_ADDR, 0x00, 2)
    if data is None or len(data) < 2:
        print("  ERROR: Could not read Control Status.")
        return None, None, None
    status = bytes_to_uint16_le(data)
    is_sealed = bool(status & (1 << 13))   # SS bit
    is_full_access = bool(status & (1 << 14))  # FAS bit
    print(f"  Control Status  : 0x{status:04X}  "
          f"(sealed={is_sealed}, full_access={not is_full_access})")
    return status, is_sealed, is_full_access


def bq_unseal(handle):
    """Unseal the BQ34Z100-R2 using default unseal keys."""
    bq_write_control(handle, BQ_UNSEAL_KEY1)
    aa_sleep_ms(5)
    bq_write_control(handle, BQ_UNSEAL_KEY2)
    aa_sleep_ms(5)
    status, is_sealed, _ = bq_read_control_status(handle)
    if status is not None and not is_sealed:
        print("  Unseal: OK")
        return True
    print("  Unseal: FAILED (device may use non-default keys)")
    return False


def bq_full_access(handle):
    """Enter Full Access mode using default keys."""
    bq_write_control(handle, BQ_FULL_ACCESS_KEY1)
    aa_sleep_ms(5)
    bq_write_control(handle, BQ_FULL_ACCESS_KEY2)
    aa_sleep_ms(5)
    status, _, fas = bq_read_control_status(handle)
    if status is not None and not fas:
        print("  Full Access: OK")
        return True
    print("  Full Access: FAILED (device may use non-default keys)")
    return False


def bq_seal(handle):
    """Re-seal the BQ34Z100-R2."""
    bq_write_control(handle, BQ_SUBCMD_SEALED)
    aa_sleep_ms(5)
    status, is_sealed, _ = bq_read_control_status(handle)
    if status is not None and is_sealed:
        print("  Seal: OK")
        return True
    print("  Seal: FAILED")
    return False


def bq_read_df_block(handle, subclass, block=0, retries=4):
    """Read a 32-byte Data Flash block via BlockDataControl protocol.

    Returns 32-byte list or None on failure.  Validates the block
    checksum (register 0x60) to confirm read integrity.  Only wakes
    the device on retries (the caller must ensure device is awake for
    the first attempt — writing to reg 0x00 during wake interferes
    with DF block context).
    """
    for attempt in range(retries):
        if attempt > 0:
            # Wake and retry — the device may have gone to sleep
            wait_ms = 200 * attempt
            print(f"  DF read retry {attempt}/{retries} "
                  f"(subclass {subclass}), waiting {wait_ms} ms...")
            bq_wake_for_df(handle)
            aa_sleep_ms(wait_ms)

        # Step 1: enable block data access
        data_out = array('B', [BQ_BLOCK_DATA_CONTROL, 0x00])
        aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, data_out)
        aa_sleep_ms(5)

        # Step 2: set subclass
        data_out = array('B', [BQ_DATA_FLASH_CLASS, subclass])
        aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, data_out)
        aa_sleep_ms(5)

        # Step 3: set block index — triggers 32-byte transfer inside the BQ
        data_out = array('B', [BQ_DATA_FLASH_BLOCK, block])
        aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, data_out)
        aa_sleep_ms(50)  # BQ needs time to load the block into RAM

        # Step 4: read 32 bytes from BlockData base
        data = i2c_write_read(handle, BQ34Z100_ADDR, BQ_BLOCK_DATA_BASE, 32)
        if data is None or len(data) != 32:
            continue

        # Step 5: read and validate checksum
        cksum_data = i2c_write_read(handle, BQ34Z100_ADDR, BQ_BLOCK_DATA_CKSUM, 1)
        if cksum_data is not None:
            expected_cksum = (255 - (sum(data) & 0xFF)) & 0xFF
            if cksum_data[0] != expected_cksum:
                print(f"  DF checksum mismatch (subclass {subclass}): "
                      f"read 0x{cksum_data[0]:02X}, expected 0x{expected_cksum:02X}")
                # Check if data is the telltale stale pattern (zeros + FFs)
                if all(b == 0 for b in data[:16]):
                    print(f"  (stale/uninitialized data detected)")
                    continue
                if attempt < retries - 1:
                    continue
                print(f"  WARNING: Using data despite checksum mismatch")

        return data

    print(f"  ERROR: Failed to read DF subclass {subclass} block {block} "
          f"after {retries} attempts")
    return None


def bq_write_df_bytes(handle, subclass, offset, new_bytes, block=0,
                      existing_block=None):
    """Write bytes to a Data Flash block and verify.

    If existing_block is provided, uses that as the base (avoids a
    re-read that may fail due to BQ sleep).  Otherwise reads the current
    block first.

    Wakes the device, issues the full setup sequence, writes the entire
    32-byte modified block, then commits with checksum.

    offset is byte position within the 32-byte block (0-31).
    new_bytes is a list/bytes of values to write starting at offset.

    Returns True on success, False on failure.
    """
    if existing_block is not None:
        old_block = list(existing_block)
    else:
        old_block = bq_read_df_block(handle, subclass, block)
        if old_block is None:
            return False

    # Build modified block
    modified = list(old_block)
    for i, b in enumerate(new_bytes):
        modified[offset + i] = b

    print(f"  DF write: subclass {subclass}, offset {offset}, "
          f"{len(new_bytes)} byte(s)")

    # Full setup sequence before writing (don't call bq_wake — it writes
    # to reg 0x00 which can interfere with DF block context)
    data_out = array('B', [BQ_BLOCK_DATA_CONTROL, 0x00])
    aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, data_out)
    aa_sleep_ms(5)

    data_out = array('B', [BQ_DATA_FLASH_CLASS, subclass])
    aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, data_out)
    aa_sleep_ms(5)

    data_out = array('B', [BQ_DATA_FLASH_BLOCK, block])
    aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, data_out)
    aa_sleep_ms(50)  # wait for block to load into RAM

    # Write the full 32-byte block in a single I2C transaction
    data_out = array('B', [BQ_BLOCK_DATA_BASE] + modified)
    count = aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, data_out)
    if count < 0:
        print(f"  ERROR: Block write failed (error {count})")
        return False
    aa_sleep_ms(10)

    # Compute and write checksum over the full 32-byte modified block
    cksum = (255 - (sum(modified) & 0xFF)) & 0xFF
    data_out = array('B', [BQ_BLOCK_DATA_CKSUM, cksum])
    count = aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, data_out)
    if count < 0:
        print(f"  ERROR: Checksum write failed (error {count})")
        return False
    print(f"  Flash commit... (checksum 0x{cksum:02X})")
    aa_sleep_ms(500)  # generous delay for flash commit

    # The BQ auto-seals after every flash commit.  Re-unseal + full access
    # before the verification read, otherwise DF reads return stale data.
    bq_wake(handle)
    bq_unseal(handle)
    bq_full_access(handle)

    # Verify by re-reading the block
    verify = bq_read_df_block(handle, subclass, block)
    if verify is None:
        print("  ERROR: Verification read failed after DF write.")
        return False
    for i, b in enumerate(new_bytes):
        if verify[offset + i] != b:
            print(f"  ERROR: Verify mismatch at offset {offset + i}: "
                  f"wrote 0x{b:02X}, read 0x{verify[offset + i]:02X}")
            print(f"         Block hex: {' '.join(f'{x:02X}' for x in verify)}")
            return False
    return True


def float_to_bytes_be(value):
    """Convert a Python float to 4 bytes, IEEE 754 big-endian."""
    return list(struct.pack('>f', value))


def bytes_to_float_be(data):
    """Convert 4 bytes (big-endian) to a Python float (IEEE 754)."""
    return struct.unpack('>f', bytes(data))[0]


def _hex_dump(data, prefix="  "):
    """Print a hex dump of a data block."""
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_str = ' '.join(f'{b:02X}' for b in chunk)
        print(f"{prefix}[{i:2d}] {hex_str}")


def bq34z100_calibrate(handle):
    """Calibrate CC Gain, CC Delta, and RSNS for the R26 sense resistor.

    Reads current Data Flash values and only writes if they need changing.
    The BQ34Z100-R2 silently blocks all Data Flash writes when the
    measured cell voltage on BAT (pin 4) is below the Flash Update OK
    Voltage threshold (default 2800 mV).  If the BQ reports 0 mV, a
    battery or power supply must be connected to the BAT pin.

    Returns True if calibration was performed, False if already correct.
    """
    calibrated = False
    print("\n  --- BQ34Z100-R2 Calibration ---")

    # Check battery voltage — Flash Update OK Voltage (default 2800 mV)
    # blocks all DF writes if cell voltage is below threshold.
    # NOTE: The Voltage() command may report 0 mV on an unconfigured gauge
    # even when the BAT pin physically has voltage.  The BQ's internal
    # flash-write protection uses the raw ADC, not this processed value.
    # We warn but still attempt writes if the gauge reports 0 mV, since
    # the actual pin voltage may be above the threshold.
    data = i2c_write_read(handle, BQ34Z100_ADDR, BQ_CMD_VOLTAGE, 2)
    bq_voltage_mv = 0
    if data:
        bq_voltage_mv = bytes_to_uint16_le(data)
        print(f"  BQ Voltage      : {bq_voltage_mv} mV  (reported by gauge)")
        if bq_voltage_mv < 2800:
            print(f"  NOTE: Reported voltage ({bq_voltage_mv} mV) is below 2800 mV.")
            print(f"        Writes will proceed — verify BAT pin has >2.8V physically.")

    # Read Control Status to determine seal state
    status, is_sealed, fas = bq_read_control_status(handle)
    if status is None:
        print("  ERROR: Cannot read Control Status, aborting calibration.")
        return False

    # Unseal and enter Full Access if needed
    if is_sealed:
        if not bq_unseal(handle):
            return False
    if fas:  # FAS=1 means NOT in full access mode
        if not bq_full_access(handle):
            return False

    # ---- Pack Configuration: RSNS bit + VOLTSEL safety (subclass 64) ----
    pack_cfg_block = bq_read_df_block(handle, BQ_SUBCLASS_PACK_CFG, 0)
    if pack_cfg_block is not None:
        pack_cfg = (pack_cfg_block[0] << 8) | pack_cfg_block[1]
        rsns_bit = bool(pack_cfg & 0x0080)  # bit 7
        voltsel_bit = bool(pack_cfg & 0x0008)  # bit 3
        print(f"  Pack Config     : 0x{pack_cfg:04X}  "
              f"(RSNS={'HIGH' if rsns_bit else 'LOW'} side, "
              f"VOLTSEL={'EXT' if voltsel_bit else 'INT'})")
        _hex_dump(pack_cfg_block[:8], "    ")

        # VOLTSEL=1 is the correct setting for the Rev 4+ voltage divider.
        # With R22=6.49kOhm, BAT pin stays below 1V at 30V max, so
        # bypassing the internal 5:1 divider gives best ADC resolution.
        needs_fix = False
        new_cfg = pack_cfg
        if not voltsel_bit:
            new_cfg = new_cfg | 0x0008  # Set VOLTSEL
            print(f"  VOLTSEL=0 detected — setting to 1 for best ADC resolution.")
            needs_fix = True
        if rsns_bit:
            new_cfg = new_cfg & ~0x0080  # Clear RSNS
            print(f"  Fixing RSNS: HIGH -> LOW side...")
            needs_fix = True

        if needs_fix:
            new_bytes = [(new_cfg >> 8) & 0xFF, new_cfg & 0xFF]
            print(f"  Pack Config: 0x{pack_cfg:04X} -> 0x{new_cfg:04X}...")
            if bq_write_df_bytes(handle, BQ_SUBCLASS_PACK_CFG, 0, new_bytes, 0,
                                 existing_block=pack_cfg_block):
                print("  Pack Config fix: OK")
                calibrated = True
            else:
                print("  Pack Config fix: FAILED")
        else:
            print("  RSNS=LOW, VOLTSEL=EXT — no change needed.")

    # ---- CC Gain and CC Delta (subclass 104) ----
    # Re-unseal (writes to Control reg 0x00 interfere with DF block context,
    # and flash commits auto-seal the device)
    bq_wake(handle)
    bq_unseal(handle)
    bq_full_access(handle)
    cc_block = bq_read_df_block(handle, BQ_SUBCLASS_CC_CAL, 0)
    if cc_block is not None:
        print("  CC Cal block (subclass 104) raw data:")
        _hex_dump(cc_block[:16], "    ")
        cc_gain_raw = bytes_to_float_be(cc_block[0:4])
        cc_delta_raw = bytes_to_float_be(cc_block[4:8])
        print(f"  CC Gain (raw)   : {cc_gain_raw:.6g}  "
              f"(hex: {cc_block[0]:02X} {cc_block[1]:02X} {cc_block[2]:02X} {cc_block[3]:02X})")
        print(f"  CC Delta (raw)  : {cc_delta_raw:.6g}  "
              f"(hex: {cc_block[4]:02X} {cc_block[5]:02X} {cc_block[6]:02X} {cc_block[7]:02X})")

        # Expected values for R26 = 5 mOhm
        expected_gain = 4.768 / BQ_SENSE_R_MOHM    # 0.9536
        expected_delta = 5677445.3 / BQ_SENSE_R_MOHM  # 1135489.06

        # Zero values or wildly wrong values are always bad
        gain_ok = (cc_gain_raw != 0 and
                   abs(cc_gain_raw - expected_gain) / expected_gain < 0.005)
        delta_ok = (cc_delta_raw != 0 and
                    abs(cc_delta_raw - expected_delta) / expected_delta < 0.005)

        if not gain_ok or not delta_ok:
            print(f"  Expected Gain   : {expected_gain:.6g}")
            print(f"  Expected Delta  : {expected_delta:.6g}")

            gain_bytes = float_to_bytes_be(expected_gain)
            delta_bytes = float_to_bytes_be(expected_delta)
            new_cc_bytes = gain_bytes + delta_bytes
            print("  Writing corrected CC Gain and CC Delta...")
            if bq_write_df_bytes(handle, BQ_SUBCLASS_CC_CAL, 0, new_cc_bytes, 0,
                                 existing_block=cc_block):
                print("  CC calibration: OK")
                calibrated = True
            else:
                print("  CC calibration: FAILED")
        else:
            print("  CC Gain and CC Delta already correct — no change needed.")
    else:
        print("  WARNING: Could not read CC calibration data.")

    # Re-seal the device
    bq_wake(handle)
    bq_seal(handle)

    if calibrated:
        print("  Calibration COMPLETE — values were updated.")
    else:
        print("  Calibration check passed — no changes needed.")
    return calibrated


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
    print(f"  Sense Resistor R26 = {BQ_SENSE_R_MOHM} mOhm")
    print(separator)

    bq_wake(handle)
    bq_calibrated = bq34z100_calibrate(handle)
    print("\n  --- Measurements ---")
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
        tc = bq_results['temperature_C']
        tf = bq_results.get('temperature_F', tc * 9.0 / 5.0 + 32.0)
        print(f"  Battery Temperature : {tc:.1f} C / {tf:.1f} F")
        # Sanity check: room temp should be ~15-30°C (59-86°F)
        if tc < 10 or tc > 45:
            print(f"    WARNING: Temperature outside expected room-temp range")
    if 'remaining_mAh' in bq_results and 'full_charge_mAh' in bq_results:
        rem = bq_results['remaining_mAh']
        full = bq_results['full_charge_mAh']
        print(f"  Capacity            : {rem} / {full} mAh")

    if bq_calibrated:
        print(f"  BQ Calibration      : VALUES UPDATED (re-run to verify)")
    else:
        print(f"  BQ Calibration      : OK (no changes needed)")

    # Basic sanity checks
    print()
    issues = []
    if not id_ok:
        issues.append("INA226 not responding or ID mismatch")
    if 'bus_voltage_V' in ina226_results and ina226_results['bus_voltage_V'] < 0.5:
        issues.append("INA226 bus voltage very low - check VBUS connection")
    if 'soc_pct' in bq_results and bq_results['soc_pct'] == 0:
        issues.append("BQ34Z100 reports 0% SOC - battery may be depleted or gauge uncalibrated")
    if 'voltage_mV' in bq_results and bq_results['voltage_mV'] == 0:
        issues.append("BQ34Z100 reports 0 mV — gauge unconfigured (CHEM_ID=0, no chemistry loaded)")
        issues.append("  -> Voltage reading may be wrong; verify BAT pin physically with multimeter")
    if bq_calibrated:
        issues.append("BQ34Z100 calibration was applied — run again to confirm values stick")

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
