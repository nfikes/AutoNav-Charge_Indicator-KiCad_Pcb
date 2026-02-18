"""BQ34Z100-R2 I2C Write Investigation Script"""
from aardvark_py import *
from array import array
import struct

BQ = 0x55
handle = aa_open(0)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(500)

print("=== BQ34Z100-R2 Write Behavior Investigation ===")
print()

# Wake
print("--- Wake ---")
for i in range(10):
    d = array('B', [0x00])
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    aa_sleep_ms(150)
    d = array('B', [0x0A])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        v = data[0] | (data[1] << 8)
        print(f"  Awake after {i+1} attempts, voltage={v} mV")
        break
    else:
        print(f"  Attempt {i}: no response")

# Test writes BEFORE unsealing
print()
print("--- 2-byte writes BEFORE unseal ---")
regs = [
    (0x00, 0x00, "Control"),
    (0x3E, 104,  "DataFlashClass"),
    (0x3F, 0x00, "DataFlashBlock"),
    (0x40, 0x00, "BlockData[0]"),
    (0x60, 0xFF, "BlockDataChecksum"),
    (0x61, 0x00, "BlockDataControl"),
]
for reg, val, name in regs:
    d = array('B', [reg, val])
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    ok = "OK" if c == 2 else "NACK"
    print(f"  [0x{reg:02X}]=0x{val:02X} {name:25s}: {c}/2 {ok}")
    aa_sleep_ms(30)

# Unseal
print()
print("--- Unseal + Full Access ---")
for subcmd, name in [(0x0414, "KEY1"), (0x3672, "KEY2")]:
    lsb = subcmd & 0xFF
    msb = (subcmd >> 8) & 0xFF
    d = array('B', [0x00, lsb, msb])
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    print(f"  {name}: {c}/3")
    aa_sleep_ms(10)

for subcmd in [0xFFFF, 0xFFFF]:
    lsb = subcmd & 0xFF
    msb = (subcmd >> 8) & 0xFF
    d = array('B', [0x00, lsb, msb])
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    print(f"  FA: {c}/3")
    aa_sleep_ms(10)

# Check status
d = array('B', [0x00, 0x00, 0x00])
aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
aa_sleep_ms(10)
d = array('B', [0x00])
aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
(rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
if rc == 2:
    status = data[0] | (data[1] << 8)
    sealed = bool(status & (1 << 13))
    fas = bool(status & (1 << 14))
    print(f"  Status: 0x{status:04X} sealed={sealed} FA={not fas}")

# Test writes AFTER unsealing
print()
print("--- 2-byte writes AFTER unseal+FA ---")
aa_sleep_ms(200)
for reg, val, name in regs:
    d = array('B', [reg, val])
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    ok = "OK" if c == 2 else "NACK"
    print(f"  [0x{reg:02X}]=0x{val:02X} {name:25s}: {c}/2 {ok}")
    aa_sleep_ms(30)

# Try DF read
print()
print("--- DF read (subclass 104) ---")
d = array('B', [0x61, 0x00])
c1 = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
aa_sleep_ms(30)
d = array('B', [0x3E, 104])
c2 = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
aa_sleep_ms(30)
d = array('B', [0x3F, 0x00])
c3 = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
aa_sleep_ms(500)
print(f"  Setup: 0x61={c1}/2, 0x3E={c2}/2, 0x3F={c3}/2")

d = array('B', [0x40])
aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
(rc, blk) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 32)
if rc == 32:
    blk_list = list(blk[:32])
    print(f"  Block: {' '.join(f'{b:02X}' for b in blk_list[:16])}")
    d = array('B', [0x60])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc2, ck) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 1)
    if rc2 == 1:
        exp = (255 - (sum(blk_list) & 0xFF)) & 0xFF
        print(f"  Checksum: read=0x{ck[0]:02X} calc=0x{exp:02X} match={ck[0]==exp}")

    has_data = False
    for b in blk_list:
        if b != 0:
            has_data = True
            break
    if has_data:
        cc_gain = struct.unpack('>f', bytes(blk_list[0:4]))[0]
        cc_delta = struct.unpack('>f', bytes(blk_list[4:8]))[0]
        print(f"  CC Gain:  {cc_gain:.6g}")
        print(f"  CC Delta: {cc_delta:.6g}")
    else:
        print("  (all zeros - stale)")
else:
    print(f"  Read failed: {rc}")

# Block data write test
print()
print("--- Block data write test (individual bytes to 0x40-0x47) ---")
gain_bytes = list(struct.pack('>f', 4.768 / 5.0))
delta_bytes = list(struct.pack('>f', 5677445.3 / 5.0))
new_bytes = gain_bytes + delta_bytes
for i in range(8):
    d = array('B', [0x40 + i, new_bytes[i]])
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    ok = "OK" if c == 2 else "NACK"
    print(f"  [0x{0x40+i:02X}]=0x{new_bytes[i]:02X}: {c}/2 {ok}")
    aa_sleep_ms(10)

# Read back buffer
print()
print("--- Read back buffer after writes ---")
d = array('B', [0x40])
aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
(rc, buf) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 8)
if rc == 8:
    buf_list = list(buf[:8])
    print(f"  Buffer[0:8]: {' '.join(f'{b:02X}' for b in buf_list)}")
    print(f"  Want:        {' '.join(f'{b:02X}' for b in new_bytes)}")
    print(f"  Match: {buf_list == new_bytes}")

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print()
print("Done.")
