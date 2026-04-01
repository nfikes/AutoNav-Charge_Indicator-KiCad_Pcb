"""Test TEMPS=0 (internal temp) vs TEMPS=1 (external thermistor).

If no thermistor is connected, TEMPS=1 may cause the ADC to get stuck
trying to measure the TS pin, locking up voltage measurement too.
"""
import sys, os, time
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


def read_ina_bus():
    d = array('B', [0x02])
    aa_i2c_write(handle, INA, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        return int(((data[0] << 8) | data[1]) * 1.25)
    return None


wake_df_safe()

print("=" * 60)
print("  BQ34Z100-R2 — TEMPS Bit Test")
print("=" * 60)

# Current state
v = read_std(0x0A)
t = read_std(0x0E)
it = read_std(0x1E)
ina = read_ina_bus()
print(f"\n  Current: V={v}mV  T={t}  IT={it}  INA={ina}mV")

blk64 = read_block(64)
if not blk64:
    print("  SC 64 read failed!")
    aa_close(handle)
    exit(1)

pc = (blk64[0] << 8) | blk64[1]
temps_bit = bool(pc & 0x0001)
print(f"  Pack Config: 0x{pc:04X}  TEMPS={int(temps_bit)} ({'EXT' if temps_bit else 'INT'})")

# Set TEMPS=0 (internal temp sensor)
new_pc = pc & ~0x0001  # Clear TEMPS bit
print(f"\n  Setting TEMPS=0 (internal temp sensor)")
print(f"  Pack Config: 0x{pc:04X} -> 0x{new_pc:04X}")

mod64 = list(blk64)
mod64[0] = (new_pc >> 8) & 0xFF
mod64[1] = new_pc & 0xFF
if not write_block(64, mod64):
    print("  Write failed!")
    aa_close(handle)
    exit(1)

# Verify
verify = read_block(64)
if verify:
    vpc = (verify[0] << 8) | verify[1]
    print(f"  Verified: 0x{vpc:04X}")

# RESET to apply
print("\n  Resetting to apply TEMPS change...")
unseal_fa()
send_control(0x0041)
aa_sleep_ms(8000)
wake_df_safe()
aa_sleep_ms(2000)

# Read after TEMPS=0
print("\n  --- After TEMPS=0 + RESET ---")
for i in range(10):
    v = read_std(0x0A)
    pv = read_std(0x28)
    t = read_std(0x0E)
    it = read_std(0x1E)
    ina = read_ina_bus()

    t_c = f"{t*0.1-273.15:.1f}C" if t is not None else "FAIL"
    it_c = f"{it*0.1-273.15:.1f}C" if it is not None else "FAIL"

    print(f"  [{i}] V={v}mV  PV={pv}mV  T={t}({t_c})  IT={it}({it_c})  INA={ina}mV")
    aa_sleep_ms(1500)

print()
if v is not None and v > 10:
    print(f"  Voltage improved to {v}mV with TEMPS=0!")
    if t is not None and 2500 < t < 3500:
        print(f"  Temperature now reads {t*0.1-273.15:.1f}C — looks reasonable!")
else:
    print(f"  Voltage still at {v}mV. TEMPS wasn't the issue.")
    print("  Restoring TEMPS=1...")
    blk64 = read_block(64)
    if blk64:
        mod64 = list(blk64)
        mod64[0] = (pc >> 8) & 0xFF
        mod64[1] = pc & 0xFF
        write_block(64, mod64)
        unseal_fa()
        send_control(0x0041)
        aa_sleep_ms(5000)

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\nDone.")
