"""BQ34Z100-R2 — VOLTSEL Toggle Test.

Toggle VOLTSEL between 0 (internal 5:1 divider active) and 1 (bypassed)
to see how the ADC reading changes. This tells us if the internal divider
is functioning and whether the 44mV reading is truly the ADC output.

With BAT=787mV:
  VOLTSEL=1 (bypassed): ADC sees 787mV directly -> Voltage() should be ~787mV
  VOLTSEL=0 (active):   ADC sees 787/5=157mV    -> Voltage() should be ~157mV
                         (but gauge compensates, so Voltage() might still show ~787mV)

If Voltage() changes by ~5x when toggling, VOLTSEL works.
If Voltage() stays ~44mV either way, something else is wrong.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *
from array import array
import struct

BQ = 0x55
INA = 0x40
handle = aa_open(0)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(500)


def unseal_fa():
    for subcmd in [0x0414, 0x3672, 0xFFFF, 0xFFFF]:
        d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(5)
    aa_sleep_ms(100)


def send_control(subcmd):
    d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    aa_sleep_ms(10)


def read_std(cmd, n=2, signed=False):
    d = array('B', [cmd])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, n)
    if rc != n:
        return None
    if n == 1:
        return data[0]
    val = data[0] | (data[1] << 8)
    if signed and val >= 0x8000:
        val -= 0x10000
    return val


def wake_df_safe():
    for i in range(8):
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
        aa_sleep_ms(100)


def read_block(subclass, block=0):
    unseal_fa()
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
    return list(raw[:32])


def write_block(subclass, modified, block=0):
    unseal_fa()
    for reg, val in [(0x61, 0x00), (0x3E, subclass), (0x3F, block)]:
        d = array('B', [reg, val])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(10)
    aa_sleep_ms(100)
    for i in range(32):
        d = array('B', [0x40 + i, modified[i]])
        c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        if c != 2:
            return False
        aa_sleep_ms(3)
    cksum = (255 - (sum(modified) & 0xFF)) & 0xFF
    aa_sleep_ms(20)
    d = array('B', [0x60, cksum])
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    if c != 2:
        return False
    aa_sleep_ms(2000)
    return True


def read_voltage_samples(label, n=5):
    print(f"\n  --- {label} ---")
    for i in range(n):
        v = read_std(0x0A)
        pv = read_std(0x28)
        t = read_std(0x0E)
        it = read_std(0x1E)
        print(f"    [{i}] V={v}mV  PV={pv}mV  T={t}  IT={it}")
        aa_sleep_ms(1000)
    return v


# Wake
wake_df_safe()

print("=" * 60)
print("  BQ34Z100-R2 — VOLTSEL Toggle Test")
print("=" * 60)

# Read current Pack Config
blk64 = read_block(64)
if not blk64:
    print("  SC 64 read failed!")
    aa_close(handle)
    exit(1)

pc = (blk64[0] << 8) | blk64[1]
voltsel = bool(pc & 0x0008)
print(f"\n  Current Pack Config: 0x{pc:04X}  VOLTSEL={int(voltsel)}")

# --- Read with current VOLTSEL (should be 1) ---
v1 = read_voltage_samples(f"VOLTSEL={int(voltsel)} (current setting)")

# --- Toggle VOLTSEL ---
new_pc = pc ^ 0x0008  # Toggle bit 3
new_voltsel = bool(new_pc & 0x0008)
print(f"\n  Toggling VOLTSEL: {int(voltsel)} -> {int(new_voltsel)}")
print(f"  Pack Config: 0x{pc:04X} -> 0x{new_pc:04X}")

mod64 = list(blk64)
mod64[0] = (new_pc >> 8) & 0xFF
mod64[1] = new_pc & 0xFF
if not write_block(64, mod64):
    print("  Write failed!")
    aa_close(handle)
    exit(1)

# RESET to apply
print("  RESET to apply new VOLTSEL...")
unseal_fa()
send_control(0x0041)
aa_sleep_ms(8000)
wake_df_safe()
aa_sleep_ms(2000)

# Read with toggled VOLTSEL
v2 = read_voltage_samples(f"VOLTSEL={int(new_voltsel)} (after toggle)")

# --- Restore original VOLTSEL ---
print(f"\n  Restoring VOLTSEL={int(voltsel)} (original)...")
blk64_new = read_block(64)
if blk64_new:
    mod64 = list(blk64_new)
    mod64[0] = (pc >> 8) & 0xFF
    mod64[1] = pc & 0xFF
    write_block(64, mod64)

    unseal_fa()
    send_control(0x0041)
    aa_sleep_ms(8000)
    wake_df_safe()
    aa_sleep_ms(2000)

    v3 = read_voltage_samples(f"VOLTSEL={int(voltsel)} (restored)")

# INA226 reference
ina_d = array('B', [0x02])
aa_i2c_write(handle, INA, AA_I2C_NO_STOP, ina_d)
(rc, ina_data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
if rc == 2:
    ina_mv = int(((ina_data[0] << 8) | ina_data[1]) * 1.25)
    bat_mv = ina_mv * 6.49 / 206.49
    print(f"\n  INA226 Bus V  : {ina_mv} mV")
    print(f"  Expected BAT  : {bat_mv:.0f} mV")

# Analysis
print("\n" + "=" * 60)
print("  Analysis")
print("=" * 60)
if v1 is not None and v2 is not None:
    if v1 > 0 and v2 > 0:
        ratio = v1 / v2
        print(f"  VOLTSEL=1 reading: {v1} mV")
        print(f"  VOLTSEL=0 reading: {v2} mV")
        print(f"  Ratio: {ratio:.1f}x")
        if ratio > 3:
            print(f"  -> VOLTSEL IS WORKING. Internal 5:1 divider toggles properly.")
            print(f"  -> The {v1}mV reading IS the raw ADC output for {bat_mv:.0f}mV BAT.")
        elif ratio < 0.3:
            print(f"  -> VOLTSEL=0 reads HIGHER — unexpected!")
        else:
            print(f"  -> Readings are similar — VOLTSEL may not be affecting the ADC.")
    else:
        print(f"  VOLTSEL=1: {v1} mV, VOLTSEL=0: {v2} mV")
        if v2 == 0:
            print(f"  -> VOLTSEL=0 killed the voltage reading!")
        else:
            print(f"  -> One or both readings are 0.")

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\nDone.")
