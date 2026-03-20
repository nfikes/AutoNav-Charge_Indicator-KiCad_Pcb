"""BQ34Z100-R2 CC Calibration — write all 32 bytes, check Flash Update OK Voltage."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *
from array import array
import struct

BQ = 0x55
SENSE_R_MOHM = 5

handle = aa_open(0)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(500)

print("=" * 60)
print("  BQ34Z100-R2 CC Calibration")
print("=" * 60)
print()

# Wake
for i in range(6):
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x00]))
    aa_sleep_ms(50 * (i + 1))
    d = array('B', [0x0A])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, _) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        print(f"BQ awake")
        break

# Unseal + FA (don't verify)
for subcmd in [0x0414, 0x3672, 0xFFFF, 0xFFFF]:
    d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    aa_sleep_ms(5)
aa_sleep_ms(100)

# ====== Read Flash Update OK Voltage (subclass 68, offset 0) ======
print()
print("--- Flash Update OK Voltage (subclass 68) ---")
for reg, val in [(0x61, 0x00), (0x3E, 68), (0x3F, 0x00)]:
    d = array('B', [reg, val])
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    aa_sleep_ms(10)
aa_sleep_ms(100)

d = array('B', [0x40])
aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
(rc, raw68) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 32)
if rc == 32:
    blk68 = list(raw68[:32])
    print(f"  Block 68: {' '.join(f'{b:02X}' for b in blk68[:16])}")
    # Flash Update OK Voltage is typically first 2 bytes, big-endian, in mV
    fu_voltage = (blk68[0] << 8) | blk68[1]
    print(f"  Bytes 0-1 (BE): {fu_voltage} mV")
    fu_voltage_le = blk68[0] | (blk68[1] << 8)
    print(f"  Bytes 0-1 (LE): {fu_voltage_le} mV")
    # Show a few more potential interpretations
    for off in range(0, 12, 2):
        val_be = (blk68[off] << 8) | blk68[off+1]
        val_le = blk68[off] | (blk68[off+1] << 8)
        print(f"  Offset {off}: BE={val_be} LE={val_le}")
else:
    print(f"  Read failed ({rc}/32)")

# ====== Now read CC Cal (subclass 104) ======
# Re-unseal since DF operations may have disrupted state
for subcmd in [0x0414, 0x3672, 0xFFFF, 0xFFFF]:
    d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    aa_sleep_ms(5)
aa_sleep_ms(100)

print()
print("--- CC Cal (subclass 104) ---")
for reg, val in [(0x61, 0x00), (0x3E, 104), (0x3F, 0x00)]:
    d = array('B', [reg, val])
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    aa_sleep_ms(10)
aa_sleep_ms(100)

d = array('B', [0x40])
aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
(rc, raw104) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 32)
if rc != 32:
    print(f"  Read failed ({rc}/32)")
    aa_close(handle)
    exit(1)

old_block = list(raw104[:32])
print(f"  Block: {' '.join(f'{b:02X}' for b in old_block[:16])}")

if all(b == 0 for b in old_block[:16]):
    print("  STALE DATA")
    aa_close(handle)
    exit(1)

cc_gain = struct.unpack('>f', bytes(old_block[0:4]))[0]
cc_delta = struct.unpack('>f', bytes(old_block[4:8]))[0]
print(f"  CC Gain:  {cc_gain:.6g}")
print(f"  CC Delta: {cc_delta:.6g}")

# Build modified block
exp_gain = 4.768 / SENSE_R_MOHM
exp_delta = 5677445.3 / SENSE_R_MOHM
gain_bytes = list(struct.pack('>f', exp_gain))
delta_bytes = list(struct.pack('>f', exp_delta))

modified = list(old_block)
modified[0:4] = gain_bytes
modified[4:8] = delta_bytes
new_cksum = (255 - (sum(modified) & 0xFF)) & 0xFF

print()
print(f"  Target Gain:  {exp_gain:.6g}")
print(f"  Target Delta: {exp_delta:.6g}")
print(f"  Checksum: 0x{new_cksum:02X}")

# ====== Write ALL 32 bytes + commit ======
print()
print("Writing ALL 32 bytes to RAM buffer...")
all_ok = True
for i in range(32):
    d = array('B', [0x40 + i, modified[i]])
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    if c != 2:
        print(f"  FAIL at offset {i}: {c}/2")
        all_ok = False
    aa_sleep_ms(3)

if not all_ok:
    print("WRITE FAILED")
    aa_close(handle)
    exit(1)
print("  All 32 bytes written OK")

# Commit
print(f"Committing (checksum 0x{new_cksum:02X})...")
aa_sleep_ms(20)
d = array('B', [0x60, new_cksum])
c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
print(f"  0x60: {c}/2 {'OK' if c==2 else 'NACK'}")

if c == 2:
    print("  Waiting 2s...")
    aa_sleep_ms(2000)

    # Verify
    print()
    print("=== Verification ===")
    for i in range(6):
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x00]))
        aa_sleep_ms(100)
    for subcmd in [0x0414, 0x3672, 0xFFFF, 0xFFFF]:
        d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(5)
    aa_sleep_ms(100)
    for reg, val in [(0x61, 0x00), (0x3E, 104), (0x3F, 0x00)]:
        d = array('B', [reg, val])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(10)
    aa_sleep_ms(100)

    d = array('B', [0x40])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, vdata) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 32)
    if rc == 32:
        verify = list(vdata[:32])
        print(f"  Block: {' '.join(f'{b:02X}' for b in verify[:16])}")
        v_gain = struct.unpack('>f', bytes(verify[0:4]))[0]
        v_delta = struct.unpack('>f', bytes(verify[4:8]))[0]
        g_ok = verify[0:4] == gain_bytes
        d_ok = verify[4:8] == delta_bytes
        print(f"  CC Gain:  {v_gain:.6g}  {'PASS' if g_ok else 'FAIL'}")
        print(f"  CC Delta: {v_delta:.6g}  {'PASS' if d_ok else 'FAIL'}")
        if g_ok and d_ok:
            print("\n  *** CALIBRATION SUCCESSFUL ***")
        else:
            print("\n  *** VALUES DID NOT PERSIST ***")
    else:
        print(f"  Verify: {rc}/32")

d = array('B', [0x00, 0x20, 0x00])
aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\nDone.")
