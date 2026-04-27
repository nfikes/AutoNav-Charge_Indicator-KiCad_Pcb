"""Check and fix Pack Config, then test voltage tracking."""
import struct
from hw_common import *

handle = aardvark_init()


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


wake_df_safe()

print("=" * 60)
print("  BQ34Z100-R2 — DF State Check & Pack Config Fix")
print("=" * 60)

# Current readings
v = read_std(0x0A)
pv = read_std(0x28)
print(f"\n  Current Voltage(): {v} mV  PackVoltage(): {pv} mV")

# Read ALL key DF blocks
print("\n  --- Full DF State ---")
blk64 = read_block(64)
if blk64:
    pc = (blk64[0] << 8) | blk64[1]
    cells = blk64[7]
    print(f"  SC 64 raw     : {' '.join(f'{b:02X}' for b in blk64[:16])}")
    print(f"  Pack Config   : 0x{pc:04X}")
    print(f"    Bit 14      : {bool(pc & 0x4000)}")
    print(f"    Bit 13      : {bool(pc & 0x2000)}")
    print(f"    Bit 12 GNDSEL: {bool(pc & 0x1000)}")
    print(f"    Bit  9 SLEEP: {bool(pc & 0x0200)}")
    print(f"    Bit  8 RMFCC: {bool(pc & 0x0100)}")
    print(f"    Bit  7 RSNS : {bool(pc & 0x0080)} ({'HIGH' if pc & 0x0080 else 'LOW'})")
    print(f"    Bit  4 IWAKE: {bool(pc & 0x0010)}")
    print(f"    Bit  3 VOLTSEL: {bool(pc & 0x0008)} ({'EXT' if pc & 0x0008 else 'INT'})")
    print(f"    Bit  0 TEMPS: {bool(pc & 0x0001)} ({'EXT' if pc & 0x0001 else 'INT'})")
    print(f"  Cell Count    : {cells}")
else:
    print("  SC 64 READ FAILED")

blk104 = read_block(104)
if blk104:
    cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0]
    cc_d = struct.unpack('>f', bytes(blk104[4:8]))[0]
    vd = (blk104[14] << 8) | blk104[15]
    print(f"  SC 104 raw    : {' '.join(f'{b:02X}' for b in blk104[:16])}")
    print(f"  CC Gain       : {cc_g:.6g}")
    print(f"  CC Delta      : {cc_d:.6g}")
    print(f"  VD            : {vd}")

blk68 = read_block(68)
if blk68:
    fu_v = (blk68[0] << 8) | blk68[1]
    print(f"  Flash Update OK: {fu_v} mV")

# Fix Pack Config if wrong
FACTORY_PC = 0x41D9  # Factory default: VOLTSEL=1, RSNS=HIGH
TARGET_PC = 0x4159   # Our target: VOLTSEL=1, RSNS=LOW

if blk64:
    pc = (blk64[0] << 8) | blk64[1]
    if pc != FACTORY_PC and pc != TARGET_PC:
        print(f"\n  *** Pack Config 0x{pc:04X} is WRONG! ***")
        print(f"  Restoring to factory default 0x{FACTORY_PC:04X}...")
        mod64 = list(blk64)
        mod64[0] = (FACTORY_PC >> 8) & 0xFF
        mod64[1] = FACTORY_PC & 0xFF
        if write_block(64, mod64):
            print("  Written OK")
            verify = read_block(64)
            if verify:
                vpc = (verify[0] << 8) | verify[1]
                print(f"  Verified: 0x{vpc:04X}")

        # RESET
        print("\n  Resetting...")
        unseal_fa()
        send_control(0x0041)
        aa_sleep_ms(8000)
        wake_df_safe()
        aa_sleep_ms(2000)

        v2 = read_std(0x0A)
        pv2 = read_std(0x28)
        print(f"  After fix: Voltage()={v2} mV  PackVoltage()={pv2} mV")
    elif pc == FACTORY_PC:
        print(f"\n  Pack Config is at factory default 0x{FACTORY_PC:04X} — OK")
    elif pc == TARGET_PC:
        print(f"\n  Pack Config is at target 0x{TARGET_PC:04X} — OK")
        print("  Restoring to factory default to rule out RSNS as issue...")
        mod64 = list(blk64)
        mod64[0] = (FACTORY_PC >> 8) & 0xFF
        mod64[1] = FACTORY_PC & 0xFF
        if write_block(64, mod64):
            print("  Written OK")
        unseal_fa()
        send_control(0x0041)
        aa_sleep_ms(8000)
        wake_df_safe()
        aa_sleep_ms(2000)
        v2 = read_std(0x0A)
        print(f"  After factory restore: Voltage()={v2} mV")

# Final INA226 reference
d = array('B', [0x02])
aa_i2c_write(handle, INA, AA_I2C_NO_STOP, d)
(rc, data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
if rc == 2:
    ina_mv = int(((data[0] << 8) | data[1]) * 1.25)
    print(f"\n  INA226: {ina_mv} mV")

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\nDone.")
