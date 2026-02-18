"""Fix: restore cell count to 1, verify gauge recovers, then try correct VD+cells combo.

SAFETY: VOLTSEL (bit 3 of Pack Config) must NEVER be set to 1 on this board.
All SC 64 writes enforce VOLTSEL=0 to protect the ADC from overvoltage.
"""
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

print("=" * 60)
print("  BQ34Z100-R2 Cell Count / Voltage Divider Fix")
print("=" * 60)
print()


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
    aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 1)
    return blk


def write_block(subclass, modified, block=0):
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
    print(f"    Committed (0x{cksum:02X})")
    aa_sleep_ms(2000)
    return True


def reset_and_wait(seconds=5):
    d = array('B', [0x00, 0x41, 0x00])
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    print(f"    RESET, waiting {seconds}s...")
    aa_sleep_ms(seconds * 1000)
    for i in range(10):
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
        aa_sleep_ms(200)


def read_voltage():
    d = array('B', [0x0A])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        return data[0] | (data[1] << 8)
    return None


def read_ina_voltage():
    d = array('B', [0x02])
    aa_i2c_write(handle, INA, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        return int(((data[0] << 8) | data[1]) * 1.25)
    return None


def read_temps():
    # External (TS pin)
    d = array('B', [0x0E])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    ext = None
    if rc == 2:
        raw = data[0] | (data[1] << 8)
        ext = raw * 0.1 - 273.15
    # Internal
    d = array('B', [0x1E])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    internal = None
    if rc == 2:
        raw = data[0] | (data[1] << 8)
        internal = raw * 0.1 - 273.15
    return ext, internal


def show_readings(label):
    v = read_voltage()
    ext_t, int_t = read_temps()
    ina_v = read_ina_voltage()
    print(f"  {label}:")
    print(f"    BQ Voltage()  : {v} mV")
    if ext_t is not None:
        print(f"    Temperature   : {ext_t:.1f} C")
    if int_t is not None:
        print(f"    Internal Temp : {int_t:.1f} C")
    if ina_v:
        print(f"    INA226 Bus V  : {ina_v} mV")
    return v, ina_v


# Wake
for i in range(6):
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
    aa_sleep_ms(100)


# ============================================================
# TEST 1: Restore cells=1, VD=5000 (original working config)
# ============================================================
print("=== TEST 1: Restore cells=1, VD=5000 ===")
unseal_fa()

# Write cells=1
blk64 = read_block(64)
if blk64:
    mod64 = list(blk64)
    mod64[7] = 1  # cells = 1
    # SAFETY: Enforce VOLTSEL=0 (bit 3 of Pack Config at offset 0-1)
    pc = (mod64[0] << 8) | mod64[1]
    pc &= ~0x0008  # Clear VOLTSEL
    mod64[0] = (pc >> 8) & 0xFF
    mod64[1] = pc & 0xFF
    print(f"  Setting cells=1 (was {blk64[7]}), VOLTSEL=0")
    write_block(64, mod64)

# Confirm VD=5000
unseal_fa()
blk104 = read_block(104)
if blk104:
    vd = (blk104[14] << 8) | blk104[15]
    print(f"  VD = {vd} (should be 5000)")

reset_and_wait(8)
bq_v, ina_v = show_readings("cells=1, VD=5000")

if bq_v and bq_v > 0:
    print(f"\n  Gauge recovered! Voltage is reading {bq_v} mV.")
    print(f"  Now computing correct VD for cells=8...")

    # ============================================================
    # TEST 2: Set correct VD FIRST, then change cells to 8
    # ============================================================
    # With cells=1, VD=5000, the gauge reports bq_v mV.
    # The actual pack voltage is ina_v mV.
    # For cells=8, Voltage() should report total pack = ina_v.
    # If the gauge multiplies by cells internally:
    #   Voltage(cells=8) = (bq_v) * 8  (with same VD)
    #   So to get ina_v: need VD = ina_v / 8 * 5000 / bq_v * ... complicated
    #
    # Simpler approach: try setting VD so that per-cell reading is correct
    # per_cell = ina_v / 8 ≈ 3250 mV
    # With cells=1, this per-cell should be Voltage()
    # So VD_percell = (per_cell / bq_v) * 5000

    per_cell_target = ina_v / 8.0 if ina_v else 3250
    vd_for_percell = int(round(per_cell_target / bq_v * 5000))
    total_vd = int(round(ina_v / bq_v * 5000)) if ina_v else 40000

    print()
    print(f"  Actual pack voltage (INA226): {ina_v} mV")
    print(f"  BQ reads with VD=5000, cells=1: {bq_v} mV")
    print(f"  Divider ratio = {ina_v/bq_v:.4f}" if ina_v else "")
    print()
    print(f"  Option A: VD for total pack reading = {total_vd}")
    print(f"    -> Voltage() = {bq_v * total_vd / 5000:.0f} mV (cells=1)")
    print(f"  Option B: VD for per-cell reading = {vd_for_percell}")
    print(f"    -> Voltage() = {bq_v * vd_for_percell / 5000:.0f} mV (cells=1)")

    # Test Option A: Set VD to total_vd with cells=1 first
    print()
    print(f"=== TEST 2: VD={total_vd}, cells=1 ===")
    unseal_fa()
    blk104 = read_block(104)
    if blk104:
        mod104 = list(blk104)
        mod104[14] = (total_vd >> 8) & 0xFF
        mod104[15] = total_vd & 0xFF
        write_block(104, mod104)

    reset_and_wait(8)
    bq_v2, _ = show_readings(f"cells=1, VD={total_vd}")

    if bq_v2 and bq_v2 > 0:
        print(f"\n  With VD={total_vd}: Voltage()={bq_v2} mV (target: {ina_v})")
        error = abs(bq_v2 - ina_v) / ina_v * 100 if ina_v else 0
        print(f"  Error: {error:.2f}%")

        # Now set cells=8 and see what happens
        print()
        print(f"=== TEST 3: VD={total_vd}, cells=8 ===")
        unseal_fa()
        blk64 = read_block(64)
        if blk64:
            mod64 = list(blk64)
            mod64[7] = 8
            # SAFETY: Enforce VOLTSEL=0
            pc = (mod64[0] << 8) | mod64[1]
            pc &= ~0x0008
            mod64[0] = (pc >> 8) & 0xFF
            mod64[1] = pc & 0xFF
            write_block(64, mod64)

        reset_and_wait(8)
        bq_v3, ina_v3 = show_readings(f"cells=8, VD={total_vd}")

        if bq_v3 and bq_v3 > 0:
            print(f"\n  SUCCESS! cells=8 + VD={total_vd} works!")
            print(f"  Voltage()={bq_v3} mV, INA226={ina_v3} mV")
        else:
            # cells=8 broke it again. Try per-cell VD approach.
            print(f"\n  cells=8 still gives 0. Restoring cells=1...")
            unseal_fa()
            blk64 = read_block(64)
            if blk64:
                mod64 = list(blk64)
                mod64[7] = 1
                # SAFETY: Enforce VOLTSEL=0
                pc = (mod64[0] << 8) | mod64[1]
                pc &= ~0x0008
                mod64[0] = (pc >> 8) & 0xFF
                mod64[1] = pc & 0xFF
                write_block(64, mod64)
            reset_and_wait(5)

            # Try option B: VD for per-cell + cells=8
            print()
            print(f"=== TEST 4: VD={vd_for_percell}, cells=8 ===")
            unseal_fa()
            blk104 = read_block(104)
            if blk104:
                mod104 = list(blk104)
                mod104[14] = (vd_for_percell >> 8) & 0xFF
                mod104[15] = vd_for_percell & 0xFF
                write_block(104, mod104)
            unseal_fa()
            blk64 = read_block(64)
            if blk64:
                mod64 = list(blk64)
                mod64[7] = 8
                # SAFETY: Enforce VOLTSEL=0
                pc = (mod64[0] << 8) | mod64[1]
                pc &= ~0x0008
                mod64[0] = (pc >> 8) & 0xFF
                mod64[1] = pc & 0xFF
                write_block(64, mod64)
            reset_and_wait(8)
            bq_v4, ina_v4 = show_readings(f"cells=8, VD={vd_for_percell}")
    else:
        print(f"\n  VD={total_vd} also gives 0 with cells=1")
else:
    print(f"\n  Gauge still dead with cells=1, VD=5000!")
    print(f"  May need full DF reset or power cycle.")

# Final state
print()
print("--- Final DF State ---")
unseal_fa()
blk64 = read_block(64)
if blk64:
    print(f"  Cells: {blk64[7]}")
blk104 = read_block(104)
if blk104:
    vd = (blk104[14] << 8) | blk104[15]
    cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0]
    cc_d = struct.unpack('>f', bytes(blk104[4:8]))[0]
    print(f"  VD: {vd}")
    print(f"  CC Gain: {cc_g:.6g}, CC Delta: {cc_d:.6g}")

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\nDone.")
