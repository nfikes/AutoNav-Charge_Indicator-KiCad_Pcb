"""Fix Voltage Divider — restore to 5000 (default) and test voltage reading.

The VD=844 value caused per-cell voltage below gauge minimum threshold.
Need to find the correct VD empirically using the Ralim calibration approach:
  newVD = (actualVoltage / reportedVoltage) * currentVD
"""
import struct
from hw_common import *

handle = aardvark_init()

print("=" * 60)
print("  BQ34Z100-R2 Voltage Divider Fix")
print("=" * 60)
print()


def wake():
    for i in range(6):
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
        aa_sleep_ms(50 * (i + 1))
        d = array('B', [0x0A])
        aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
        (rc, _) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
        if rc == 2:
            return True
    return False


def unseal_fa():
    for subcmd in [0x0414, 0x3672, 0xFFFF, 0xFFFF]:
        d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(5)
    aa_sleep_ms(100)


def read_block(subclass, block=0):
    for reg, val in [(0x61, 0x00), (0x3E, subclass), (0x3F, block)]:
        d = array('B', [reg, val])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(10)
    aa_sleep_ms(100)
    d = array('B', [0x40])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, raw) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 32)
    if rc != 32:
        return None
    blk = list(raw[:32])
    d = array('B', [0x60])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc2, ck) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 1)
    if rc2 == 1:
        expected = (255 - (sum(blk) & 0xFF)) & 0xFF
        if ck[0] != expected and all(b == 0 for b in blk[:16]):
            print(f"  STALE DATA")
            return None
    return blk


def write_vd(new_vd):
    """Write Voltage Divider to SC 104 offset 14-15, preserving other bytes."""
    unseal_fa()
    blk = read_block(104)
    if blk is None:
        print("  Read failed")
        return False

    old_vd = (blk[14] << 8) | blk[15]
    print(f"  Current VD: {old_vd} -> {new_vd}")

    modified = list(blk)
    modified[14] = (new_vd >> 8) & 0xFF
    modified[15] = new_vd & 0xFF

    # Re-issue setup
    for reg, val in [(0x61, 0x00), (0x3E, 104), (0x3F, 0x00)]:
        d = array('B', [reg, val])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(10)
    aa_sleep_ms(100)

    # Write all 32 bytes individually
    for i in range(32):
        d = array('B', [0x40 + i, modified[i]])
        c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        if c != 2:
            print(f"  WRITE FAIL at byte {i}")
            return False
        aa_sleep_ms(3)

    # Commit
    cksum = (255 - (sum(modified) & 0xFF)) & 0xFF
    aa_sleep_ms(20)
    d = array('B', [0x60, cksum])
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    if c != 2:
        print(f"  CHECKSUM NACK")
        return False
    print(f"  Committed (0x{cksum:02X})")
    aa_sleep_ms(2000)

    # Verify
    unseal_fa()
    verify = read_block(104)
    if verify:
        vd_check = (verify[14] << 8) | verify[15]
        cc_g = struct.unpack('>f', bytes(verify[0:4]))[0]
        cc_d = struct.unpack('>f', bytes(verify[4:8]))[0]
        print(f"  Verified VD: {vd_check} {'OK' if vd_check == new_vd else 'FAIL'}")
        print(f"  CC Gain: {cc_g:.6g}  CC Delta: {cc_d:.6g}")
        return vd_check == new_vd
    return False


def read_voltage():
    d = array('B', [0x0A])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        return data[0] | (data[1] << 8)
    return None


def read_temperature():
    d = array('B', [0x0E])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        raw = data[0] | (data[1] << 8)
        return raw * 0.1 - 273.15
    return None


def read_current():
    d = array('B', [0x14])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        raw = data[0] | (data[1] << 8)
        if raw >= 0x8000:
            raw -= 0x10000
        return raw
    return None


# --- Main ---
print("Waking...")
wake()
print()

# Check VOLTSEL status
unseal_fa()
blk64_check = read_block(64)
if blk64_check:
    pc_check = (blk64_check[0] << 8) | blk64_check[1]
    voltsel = bool(pc_check & 0x0008)
    print(f"  PackConfig=0x{pc_check:04X}, VOLTSEL={int(voltsel)} "
          f"({'EXT (correct)' if voltsel else 'INT (suboptimal)'})")
    if not voltsel:
        print("  Setting VOLTSEL=1 for best ADC resolution...")
        mod = list(blk64_check)
        pc_correct = pc_check | 0x0008
        mod[0] = (pc_correct >> 8) & 0xFF
        mod[1] = pc_correct & 0xFF
        for reg, val in [(0x61, 0x00), (0x3E, 64), (0x3F, 0x00)]:
            d = array('B', [reg, val])
            aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
            aa_sleep_ms(10)
        aa_sleep_ms(100)
        for i in range(32):
            d = array('B', [0x40 + i, mod[i]])
            aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
            aa_sleep_ms(3)
        cksum = (255 - (sum(mod) & 0xFF)) & 0xFF
        aa_sleep_ms(20)
        d = array('B', [0x60, cksum])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(2000)
        print(f"  VOLTSEL set (0x{pc_check:04X} -> 0x{pc_correct:04X})")
print()

# Step 1: Restore VD to 5000 (known default that gave readings before)
print("--- Step 1: Restore VD = 5000 ---")
if write_vd(5000):
    print("  OK")
else:
    print("  FAILED")
    aa_close(handle)
    exit(1)

# Step 2: Reset gauge
print()
print("--- Step 2: Reset ---")
d = array('B', [0x00, 0x41, 0x00])
aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
print("  Waiting 5 seconds...")
aa_sleep_ms(5000)

# Wake
for i in range(6):
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
    aa_sleep_ms(200)

# Step 3: Read voltage
print()
print("--- Step 3: Read with VD=5000, cells=8 ---")
v = read_voltage()
t = read_temperature()
c = read_current()
print(f"  Voltage()    : {v} mV")
print(f"  Temperature(): {t:.1f} C" if t else "  Temperature(): FAIL")
print(f"  Current()    : {c} mA" if c is not None else "  Current(): FAIL")

if v and v > 0:
    # Calculate the correct VD
    # INA226 reads ~26V. The user has the power supply connected.
    # We know the divider ratio: (200+6.49)/6.49 = 31.82
    # But let's use the actual INA226 reading as ground truth.
    # For now, use 26000 mV as the expected pack voltage.
    #
    # The Ralim calibration formula:
    #   newVD = (actualVoltage / reportedVoltage) * currentVD
    #
    # But we need the ACTUAL pack voltage. Let's read the INA226.
    ina_d = array('B', [0x02])
    aa_i2c_write(handle, INA, AA_I2C_NO_STOP, ina_d)
    (rc, ina_data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
    actual_mv = 0
    if rc == 2:
        raw = (ina_data[0] << 8) | ina_data[1]
        actual_mv = int(raw * 1.25)
        print(f"  INA226 Bus V : {actual_mv} mV")

    if actual_mv > 5000:
        new_vd = int(round((actual_mv / v) * 5000))
        print()
        print(f"  Calibration: actual={actual_mv}, reported={v}, VD=5000")
        print(f"  New VD = ({actual_mv} / {v}) * 5000 = {new_vd}")

        # Write calibrated VD
        print()
        print(f"--- Step 4: Write calibrated VD = {new_vd} ---")
        if write_vd(new_vd):
            print("  OK")
        else:
            print("  FAILED")

        # Reset again
        print()
        print("--- Step 5: Reset and verify ---")
        d = array('B', [0x00, 0x41, 0x00])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        print("  Waiting 5 seconds...")
        aa_sleep_ms(5000)

        for i in range(6):
            aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
            aa_sleep_ms(200)

        v2 = read_voltage()
        t2 = read_temperature()
        c2 = read_current()
        print(f"  Voltage()    : {v2} mV")
        print(f"  Temperature(): {t2:.1f} C" if t2 else "  Temperature(): FAIL")
        print(f"  Current()    : {c2} mA" if c2 is not None else "  Current(): FAIL")

        if v2 and actual_mv:
            error_pct = abs(v2 - actual_mv) / actual_mv * 100
            print(f"  Error        : {error_pct:.2f}%")
            if error_pct < 2:
                print(f"  *** VOLTAGE CALIBRATION SUCCESSFUL ***")
            else:
                print(f"  WARNING: Error > 2%, may need fine-tuning")
    else:
        print("  Cannot read INA226 — manual calibration needed")
else:
    print()
    print("  Voltage still 0 with VD=5000. Trying VD=5000 without cells change...")
    print("  The gauge may need a learning cycle after major config changes.")

# Seal and close
d = array('B', [0x00, 0x20, 0x00])
aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print()
print("Done.")
