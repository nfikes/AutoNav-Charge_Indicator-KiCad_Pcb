"""BQ34Z100-R2 Battery Configuration — Program design parameters for Renogy RBT2425LFP.

Target Battery: Renogy RBT2425LFP
  - Chemistry: LiFePO4
  - Configuration: 8S (8 cells in series)
  - Nominal Voltage: 25.6V (3.2V per cell)
  - Charge Voltage: 29.0V
  - Capacity: 25 Ah (25000 mAh)
  - Energy: 640 Wh (640,000 mWh)

Voltage Divider: R27=200kOhm (top), R22=6.49kOhm (bottom)
  - Ratio: (200+6.49)/6.49 = 31.82
  - DF value: calibrate empirically using Ralim method

Parameters programmed:
  SC 48  offset 0-1:   Design Energy    = 64000
  SC 48  offset 11-12: Design Capacity  = 25000 mAh
  SC 64  offset 7:     Series Cells     = 8
  SC 82  offset 0-1:   QMax Cell 0      = 25000 mAh
  SC 104 offset 14-15: Voltage Divider  = 5000 (calibrate with Ralim method)
"""
from aardvark_py import *
from array import array
import struct

BQ = 0x55

# === Target values ===
DESIGN_CAPACITY  = 25000   # mAh
DESIGN_ENERGY    = 64000   # mWh (needs EnergyScale=10 for correct 640 Wh)
NUM_CELLS        = 8       # 8S LiFePO4
QMAX             = 25000   # mAh
VOLTAGE_DIVIDER  = 5000    # Calibrate empirically with Ralim method

handle = aa_open(0)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(500)

print("=" * 60)
print("  BQ34Z100-R2 Battery Configuration")
print("  Renogy RBT2425LFP (24V 25Ah LiFePO4, 8S)")
print("=" * 60)
print()


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def wake():
    """Wake BQ34Z100-R2 using DF-safe method (writes to 0x61, not 0x00)."""
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
    """Unseal + Full Access. Writes to Control reg 0x00."""
    for subcmd in [0x0414, 0x3672, 0xFFFF, 0xFFFF]:
        d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(5)
    aa_sleep_ms(100)


def read_block(subclass, block=0):
    """Read a 32-byte DF block. Returns list or None."""
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

    # Validate checksum
    d = array('B', [0x60])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc2, ck) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 1)
    if rc2 == 1:
        expected = (255 - (sum(blk) & 0xFF)) & 0xFF
        if ck[0] != expected:
            if all(b == 0 for b in blk[:16]):
                print(f"  STALE DATA (SC {subclass} block {block})")
                return None
    return blk


def write_block_and_verify(subclass, original, modifications, block=0):
    """Modify specific offsets in a DF block, commit to flash, verify.

    modifications: list of (offset, [byte_values]) tuples.
    Returns True on success.
    """
    modified = list(original)
    for offset, new_bytes in modifications:
        for i, b in enumerate(new_bytes):
            modified[offset + i] = b

    # Re-issue full setup to load block into BQ RAM
    for reg, val in [(0x61, 0x00), (0x3E, subclass), (0x3F, block)]:
        d = array('B', [reg, val])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(10)
    aa_sleep_ms(100)

    # Write all 32 bytes individually (proven working approach)
    for i in range(32):
        d = array('B', [0x40 + i, modified[i]])
        c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        if c != 2:
            print(f"    WRITE FAIL at byte {i}: {c}/2")
            return False
        aa_sleep_ms(3)

    # Commit with checksum
    cksum = (255 - (sum(modified) & 0xFF)) & 0xFF
    aa_sleep_ms(20)
    d = array('B', [0x60, cksum])
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    if c != 2:
        print(f"    CHECKSUM NACK")
        return False
    print(f"    Committed (0x{cksum:02X}), waiting 2s...")
    aa_sleep_ms(2000)

    # Device auto-seals after flash commit — re-unseal for verification
    unseal_fa()

    # Verify
    verify = read_block(subclass, block)
    if verify is None:
        print(f"    Verify read FAILED")
        return False

    for offset, new_bytes in modifications:
        for i, b in enumerate(new_bytes):
            if verify[offset + i] != b:
                print(f"    VERIFY FAIL offset {offset+i}: "
                      f"wrote 0x{b:02X}, read 0x{verify[offset+i]:02X}")
                return False
    return True


def u16_be(val):
    """uint16 to 2 big-endian bytes."""
    return [(val >> 8) & 0xFF, val & 0xFF]


def hex_dump(data, n=16):
    """Format first n bytes as hex string."""
    return ' '.join(f'{b:02X}' for b in data[:n])


def read_std_cmd(cmd, nbytes=2, signed=False):
    """Read a BQ standard command register."""
    d = array('B', [cmd])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, nbytes)
    if rc != nbytes:
        return None
    if nbytes == 1:
        return data[0]
    val = data[0] | (data[1] << 8)
    if signed and val >= 0x8000:
        val -= 0x10000
    return val


# ---------------------------------------------------------------------------
#  PHASE 1: Read current values
# ---------------------------------------------------------------------------

print("Waking...")
if wake():
    print("  Awake")
else:
    print("  WARNING: No response")
unseal_fa()
print()

print("--- Current Data Flash Values ---")
print()

blk48 = read_block(48)
if blk48:
    de_cur = (blk48[0] << 8) | blk48[1]
    dc_cur = (blk48[11] << 8) | blk48[12]
    print(f"  SC 48 Design Energy   : {de_cur} (offset 0-1)")
    print(f"  SC 48 Design Capacity : {dc_cur} mAh (offset 11-12)")
    print(f"    Block 0: {hex_dump(blk48, 32)}")
else:
    print("  SC 48: READ FAILED")
print()

blk64 = read_block(64)
if blk64:
    pc = (blk64[0] << 8) | blk64[1]
    cells_cur = blk64[7]
    print(f"  SC 64 Pack Config     : 0x{pc:04X}")
    print(f"  SC 64 Cell Count      : {cells_cur} (offset 7)")
    print(f"    Block: {hex_dump(blk64)}")
else:
    print("  SC 64: READ FAILED")
print()

blk82 = read_block(82)
if blk82:
    qmax_cur = (blk82[0] << 8) | blk82[1]
    print(f"  SC 82 QMax            : {qmax_cur} mAh (offset 0-1)")
    print(f"    Block: {hex_dump(blk82)}")
else:
    print("  SC 82: READ FAILED")
print()

blk104 = read_block(104)
if blk104:
    cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0]
    cc_d = struct.unpack('>f', bytes(blk104[4:8]))[0]
    vd_cur = (blk104[14] << 8) | blk104[15]
    print(f"  SC104 CC Gain         : {cc_g:.6g}")
    print(f"  SC104 CC Delta        : {cc_d:.6g}")
    print(f"  SC104 Voltage Divider : {vd_cur} (offset 14-15)")
    print(f"    Block: {hex_dump(blk104, 32)}")
else:
    print("  SC104: READ FAILED")
print()


# ---------------------------------------------------------------------------
#  PHASE 2: Write parameters
# ---------------------------------------------------------------------------

print("=" * 60)
print("  Writing Battery Parameters")
print("=" * 60)
print()
if blk48:
    print(f"  Design Energy   : {de_cur} -> {DESIGN_ENERGY}")
    print(f"  Design Capacity : {dc_cur} -> {DESIGN_CAPACITY} mAh")
if blk64:
    print(f"  Cell Count      : {cells_cur} -> {NUM_CELLS}")
if blk82:
    print(f"  QMax            : {qmax_cur} -> {QMAX} mAh")
if blk104:
    print(f"  Voltage Divider : {vd_cur} -> {VOLTAGE_DIVIDER}")
print()

results = {}

# --- SC 48: Design Energy + Design Capacity ---
if blk48:
    print("--- SC 48: Design Energy + Design Capacity ---")
    # Check if already correct
    if de_cur == DESIGN_ENERGY and dc_cur == DESIGN_CAPACITY:
        print("    Already correct, skipping.")
        results['SC48'] = True
    else:
        unseal_fa()
        fresh = read_block(48)
        if fresh:
            ok = write_block_and_verify(48, fresh, [
                (0, u16_be(DESIGN_ENERGY)),
                (11, u16_be(DESIGN_CAPACITY)),
            ])
            results['SC48'] = ok
            print(f"    {'PASS' if ok else 'FAIL'}")
        else:
            print("    Fresh read failed")
            results['SC48'] = False
    print()

# --- SC 64: Cell Count + Config ---
if blk64:
    print("--- SC 64: Cell Count + Config ---")
    pc_cur = (blk64[0] << 8) | blk64[1]
    voltsel_set = bool(pc_cur & 0x0008)
    needs_write = cells_cur != NUM_CELLS or not voltsel_set
    if not needs_write:
        print("    Already correct (VOLTSEL=1), skipping.")
        results['SC64'] = True
    else:
        unseal_fa()
        fresh = read_block(64)
        if fresh:
            # VOLTSEL=1 is the correct setting for Rev 4+ divider.
            # With R22=6.49kOhm, BAT pin stays below 1V at 30V max.
            pc_fresh = (fresh[0] << 8) | fresh[1]
            pc_correct = pc_fresh | 0x0008  # Set VOLTSEL
            mods = [
                (0, [(pc_correct >> 8) & 0xFF]),
                (1, [pc_correct & 0xFF]),
                (7, [NUM_CELLS]),
            ]
            if not voltsel_set:
                print(f"    VOLTSEL=0 detected — setting to 1.")
            ok = write_block_and_verify(64, fresh, mods)
            results['SC64'] = ok
            print(f"    {'PASS' if ok else 'FAIL'}")
        else:
            print("    Fresh read failed")
            results['SC64'] = False
    print()

# --- SC 82: QMax ---
if blk82:
    print("--- SC 82: QMax ---")
    if qmax_cur == QMAX:
        print("    Already correct, skipping.")
        results['SC82'] = True
    else:
        unseal_fa()
        fresh = read_block(82)
        if fresh:
            ok = write_block_and_verify(82, fresh, [
                (0, u16_be(QMAX)),
            ])
            results['SC82'] = ok
            print(f"    {'PASS' if ok else 'FAIL'}")
        else:
            print("    Fresh read failed")
            results['SC82'] = False
    print()

# --- SC 104: Voltage Divider (preserve CC cal at offsets 0-7) ---
if blk104:
    print("--- SC 104: Voltage Divider ---")
    if vd_cur == VOLTAGE_DIVIDER:
        print("    Already correct, skipping.")
        results['SC104'] = True
    else:
        unseal_fa()
        fresh = read_block(104)
        if fresh:
            ok = write_block_and_verify(104, fresh, [
                (14, u16_be(VOLTAGE_DIVIDER)),
            ])
            results['SC104'] = ok
            print(f"    {'PASS' if ok else 'FAIL'}")
            # Double-check CC cal wasn't corrupted
            if ok:
                unseal_fa()
                check = read_block(104)
                if check:
                    g = struct.unpack('>f', bytes(check[0:4]))[0]
                    d_ = struct.unpack('>f', bytes(check[4:8]))[0]
                    print(f"    CC Gain preserved : {g:.6g}")
                    print(f"    CC Delta preserved: {d_:.6g}")
        else:
            print("    Fresh read failed")
            results['SC104'] = False
    print()


# ---------------------------------------------------------------------------
#  PHASE 3: Summary
# ---------------------------------------------------------------------------

print("=" * 60)
print("  Results")
print("=" * 60)
all_ok = all(results.values()) if results else False
for key, ok in results.items():
    print(f"  {key}: {'PASS' if ok else 'FAIL'}")
print()
if all_ok:
    print("  *** ALL PARAMETERS PROGRAMMED SUCCESSFULLY ***")
else:
    print("  *** SOME WRITES FAILED ***")


# ---------------------------------------------------------------------------
#  PHASE 4: Reset and read back
# ---------------------------------------------------------------------------

print()
print("Sending RESET (0x0041)...")
d = array('B', [0x00, 0x41, 0x00])
aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
print("  Waiting 5 seconds...")
aa_sleep_ms(5000)

# Wake with DF-safe method
for i in range(6):
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
    aa_sleep_ms(200)

print()
print("--- Post-Reset Readings ---")
v = read_std_cmd(0x0A)
if v is not None:
    print(f"  Voltage()      : {v} mV")

t = read_std_cmd(0x0E)
if t is not None:
    temp_c = t * 0.1 - 273.15
    print(f"  Temperature()  : {temp_c:.1f} C")

cur = read_std_cmd(0x14, signed=True)
if cur is not None:
    print(f"  Current()      : {cur} mA")

soc = read_std_cmd(0x03, nbytes=1)
if soc is not None:
    print(f"  SOC()          : {soc} %")

dcap = read_std_cmd(0x3C)
if dcap is not None:
    print(f"  DesignCap()    : {dcap} mAh")

print()
if all_ok:
    print("NOTE: Design Energy set to 64000. For correct 640 Wh reporting,")
    print("      EnergyScale may need to be set to 10 (requires further")
    print("      investigation of the DF offset for this parameter).")

# Seal and close
d = array('B', [0x00, 0x20, 0x00])
aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print()
print("Done.")
