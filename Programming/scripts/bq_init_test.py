"""Try ENTER_CAL (0x0081) and ROM Mode (0x0F00) to enable DF writes."""
import sys, struct, time
from array import array

try:
    from aardvark_py import *
except ImportError:
    sys.exit(1)

BQ34Z100_ADDR = 0x55
ROM_MODE_ADDR = 0x0B  # BQ address in ROM mode

def i2c_wr(handle, addr, reg, n):
    data_out = array('B', [reg])
    aa_i2c_write(handle, addr, AA_I2C_NO_STOP, data_out)
    (c, d) = aa_i2c_read(handle, addr, AA_I2C_NO_FLAGS, n)
    return list(d[:c]) if c == n else None

def bq_ctrl(handle, subcmd):
    lsb = subcmd & 0xFF
    msb = (subcmd >> 8) & 0xFF
    aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS,
                 array('B', [0x00, lsb, msb]))

def unseal(handle):
    bq_ctrl(handle, 0x0414); aa_sleep_ms(5)
    bq_ctrl(handle, 0x3672); aa_sleep_ms(5)
    bq_ctrl(handle, 0xFFFF); aa_sleep_ms(5)
    bq_ctrl(handle, 0xFFFF); aa_sleep_ms(10)

def check_status(handle):
    bq_ctrl(handle, 0x0000)
    aa_sleep_ms(10)
    d = i2c_wr(handle, BQ34Z100_ADDR, 0x00, 2)
    if d:
        return d[0] | (d[1] << 8)
    return None

def hex_str(data):
    return ' '.join(f'{b:02X}' for b in data) if data else 'None'

def wake(handle):
    for i in range(4):
        aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, array('B', [0x00]))
        aa_sleep_ms(50*(i+1))
        aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_STOP, array('B', [0x08]))
        (c, _) = aa_i2c_read(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, 2)
        if c == 2: return True
    return False

def probe_addr(handle, addr):
    """Check if a device responds at the given I2C address."""
    data_out = array('B', [0x00])
    result = aa_i2c_write(handle, addr, AA_I2C_NO_FLAGS, data_out)
    return result >= 0

def df_write_and_verify(handle, subclass, offset, new_bytes, label=""):
    """Standard TI DF write sequence — returns True if write persisted."""
    print(f"  [{label}] SC {subclass}, offset {offset}, data={hex_str(new_bytes)}")

    # Setup
    aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
    aa_sleep_ms(5)
    aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, array('B', [0x3E, subclass]))
    aa_sleep_ms(5)
    aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, array('B', [0x3F, 0x00]))
    aa_sleep_ms(50)

    # Read current block
    old_data = i2c_wr(handle, BQ34Z100_ADDR, 0x40, 32)
    if not old_data:
        print("    Read FAILED")
        return False

    # Write changed bytes
    for i, b in enumerate(new_bytes):
        aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS,
                     array('B', [0x40 + offset + i, b]))
        aa_sleep_ms(2)

    # Compute new checksum
    new_data = list(old_data)
    for i, b in enumerate(new_bytes):
        new_data[offset + i] = b
    new_ck = 255 - (sum(new_data) & 0xFF)

    # Write checksum
    aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, array('B', [0x60, new_ck]))
    aa_sleep_ms(500)

    # Re-unseal (auto-seals after commit)
    unseal(handle); aa_sleep_ms(10)

    # Verify
    aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
    aa_sleep_ms(5)
    aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, array('B', [0x3E, subclass]))
    aa_sleep_ms(5)
    aa_i2c_write(handle, BQ34Z100_ADDR, AA_I2C_NO_FLAGS, array('B', [0x3F, 0x00]))
    aa_sleep_ms(50)
    verify = i2c_wr(handle, BQ34Z100_ADDR, 0x40, 32)

    if verify:
        correct = all(verify[offset + i] == new_bytes[i] for i in range(len(new_bytes)))
        print(f"    Verify: {'PASS' if correct else 'FAIL'} — {hex_str(verify[:8])}...")
        return correct
    print("    Verify read failed")
    return False


# === Main ===
(_, ports) = aa_find_devices(16)
handle = aa_open(ports[0] & 0x7FFF)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(200)

wake(handle)

# ============================================================
# TEST A: Try ENTER_CAL (0x0081) — correct sub-command per TRM
# ============================================================
print("=" * 60)
print("TEST A: ENTER_CAL (0x0081) + EXIT_CAL (0x0080)")
print("=" * 60)

unseal(handle); aa_sleep_ms(10)
s = check_status(handle)
print(f"  Pre-status: 0x{s:04X}" if s else "  Pre-status: None")

# Re-unseal after status read
unseal(handle); aa_sleep_ms(10)

print("  Sending ENTER_CAL (0x0081)...")
bq_ctrl(handle, 0x0081)
aa_sleep_ms(2000)

wake(handle)
v = i2c_wr(handle, BQ34Z100_ADDR, 0x08, 2)
voltage = (v[0] | (v[1] << 8)) if v else None

s2 = check_status(handle)
if s2:
    calmode = bool(s2 & (1 << 12))
    initcomp = bool(s2 & (1 << 7))
    print(f"  After ENTER_CAL: voltage={voltage} mV, status=0x{s2:04X}, CALMODE={calmode}, INITCOMP={initcomp}")

    if calmode:
        print("  *** ENTER_CAL WORKED! Trying DF write in CAL_MODE... ***")
        unseal(handle); aa_sleep_ms(10)
        result = df_write_and_verify(handle, 68, 0, [0x00, 0x00], "SC68-CALMODE")
        if result:
            print("  *** DF WRITE SUCCEEDED IN CAL_MODE! ***")
        # Exit cal mode
        unseal(handle); aa_sleep_ms(10)
        bq_ctrl(handle, 0x0080)  # EXIT_CAL
        aa_sleep_ms(1000)
    else:
        print("  CALMODE bit not set")
else:
    print(f"  After ENTER_CAL: voltage={voltage} mV, status=None")

# ============================================================
# TEST B: ROM Mode (0x0F00)
# ============================================================
print("\n" + "=" * 60)
print("TEST B: Enter ROM Mode (0x0F00)")
print("=" * 60)

wake(handle)
unseal(handle); aa_sleep_ms(10)

# Verify unsealed
s = check_status(handle)
print(f"  Pre-status: 0x{s:04X}" if s else "  Pre-status: None")

# Re-unseal
unseal(handle); aa_sleep_ms(10)

print("  Sending ENTER_ROM (0x0F00)...")
bq_ctrl(handle, 0x0F00)
aa_sleep_ms(1000)

# Check if device still responds at 0x55
print("\n  Probing addresses after ENTER_ROM:")
for addr in [0x55, 0x0B, 0x16, 0x08, 0x0A, 0x0C]:
    data_out = array('B', [0x00])
    result = aa_i2c_write(handle, addr, AA_I2C_NO_FLAGS, data_out)
    # Try to read
    (c, d) = aa_i2c_read(handle, addr, AA_I2C_NO_FLAGS, 2)
    responded = (c > 0)
    print(f"    0x{addr:02X}: write_result={result}, read_count={c}, responded={responded}")
    if responded:
        print(f"      Data: {hex_str(list(d[:c]))}")

# Check if we're in ROM mode at 0x0B
print("\n  Trying ROM mode operations at address 0x0B:")
# In ROM mode, read 2 bytes from address 0x00
rom_data = i2c_wr(handle, ROM_MODE_ADDR, 0x00, 2)
print(f"  Read from 0x0B reg 0x00: {hex_str(rom_data)}")

rom_data2 = i2c_wr(handle, ROM_MODE_ADDR, 0x04, 2)
print(f"  Read from 0x0B reg 0x04: {hex_str(rom_data2)}")

# Try reading more data to understand ROM mode memory layout
if rom_data is not None:
    print("\n  *** ROM MODE ENTERED SUCCESSFULLY! ***")
    print("  Reading ROM mode memory map:")

    # Read in chunks
    for base in range(0x00, 0x70, 0x10):
        chunk = i2c_wr(handle, ROM_MODE_ADDR, base, 16)
        if chunk:
            print(f"    0x{base:02X}: {hex_str(chunk)}")
        else:
            print(f"    0x{base:02X}: (no response)")

    # ============================================================
    # ROM Mode: Write DF parameters directly
    # ============================================================
    # In ROM mode, we write DF rows. The protocol is:
    # 1. Write row address (2 bytes) to registers 0x00-0x01
    # 2. Write row data (32 or 96 bytes) starting at register 0x04
    # 3. Write checksum/length to trigger commit
    #
    # But first, let's try to read the current DF to find our data.
    # DF rows are typically addressed starting from 0x0000 or 0x4000.

    # Try reading DF rows — look for our known pattern from SC 68:
    # 0A F0 00 0A 05 00 32 01 C2 14 14...
    print("\n  Searching for SC 68 data pattern in DF rows...")

    # The BQ34Z100 DF is organized in rows. Try different address ranges.
    # Row addressing in ROM mode: write [addr_lo, addr_hi] to reg 0x00-0x01
    # Then read data from reg 0x04+

    for row_addr in range(0x0000, 0x0800, 0x20):
        # Write row address
        addr_lo = row_addr & 0xFF
        addr_hi = (row_addr >> 8) & 0xFF
        aa_i2c_write(handle, ROM_MODE_ADDR, AA_I2C_NO_FLAGS,
                     array('B', [0x00, addr_lo, addr_hi]))
        aa_sleep_ms(5)

        # Read row data
        row_data = i2c_wr(handle, ROM_MODE_ADDR, 0x04, 32)
        if row_data and row_data[0] == 0x0A and row_data[1] == 0xF0:
            print(f"    FOUND SC 68 pattern at row 0x{row_addr:04X}: {hex_str(row_data[:16])}...")
            break
    else:
        print("    Pattern not found in 0x0000-0x0800 range")
        # Try higher range
        for row_addr in range(0x4000, 0x4800, 0x20):
            addr_lo = row_addr & 0xFF
            addr_hi = (row_addr >> 8) & 0xFF
            aa_i2c_write(handle, ROM_MODE_ADDR, AA_I2C_NO_FLAGS,
                         array('B', [0x00, addr_lo, addr_hi]))
            aa_sleep_ms(5)
            row_data = i2c_wr(handle, ROM_MODE_ADDR, 0x04, 32)
            if row_data and row_data[0] == 0x0A and row_data[1] == 0xF0:
                print(f"    FOUND SC 68 pattern at row 0x{row_addr:04X}: {hex_str(row_data[:16])}...")
                break
        else:
            print("    Pattern not found in 0x4000-0x4800 either")
            print("    Dumping first 16 rows for analysis:")
            for row_addr in range(0x0000, 0x0200, 0x20):
                addr_lo = row_addr & 0xFF
                addr_hi = (row_addr >> 8) & 0xFF
                aa_i2c_write(handle, ROM_MODE_ADDR, AA_I2C_NO_FLAGS,
                             array('B', [0x00, addr_lo, addr_hi]))
                aa_sleep_ms(5)
                row_data = i2c_wr(handle, ROM_MODE_ADDR, 0x04, 32)
                if row_data:
                    print(f"      0x{row_addr:04X}: {hex_str(row_data)}")

    # ============================================================
    # Exit ROM Mode
    # ============================================================
    print("\n  Exiting ROM mode...")
    # Standard exit sequence:
    # Write 0x0F to register 0x00
    # Write 0x0F to register 0x64
    # Write 0x00 to register 0x65
    aa_i2c_write(handle, ROM_MODE_ADDR, AA_I2C_NO_FLAGS,
                 array('B', [0x00, 0x0F]))
    aa_sleep_ms(10)
    aa_i2c_write(handle, ROM_MODE_ADDR, AA_I2C_NO_FLAGS,
                 array('B', [0x64, 0x0F]))
    aa_sleep_ms(10)
    aa_i2c_write(handle, ROM_MODE_ADDR, AA_I2C_NO_FLAGS,
                 array('B', [0x65, 0x00]))
    aa_sleep_ms(2000)

    # Check if device is back at 0x55
    wake(handle)
    v = i2c_wr(handle, BQ34Z100_ADDR, 0x08, 2)
    voltage = (v[0] | (v[1] << 8)) if v else None
    print(f"  After ROM exit: voltage={voltage} mV at 0x55")

    if voltage is None:
        print("  Device not responding at 0x55 — may need power cycle")
        # Check ROM mode address
        rom_check = i2c_wr(handle, ROM_MODE_ADDR, 0x00, 2)
        print(f"  Still in ROM mode at 0x0B? {rom_check is not None}")

else:
    print("\n  ROM mode NOT entered (0x0B not responding)")
    print("  Checking if 0x55 still responds...")
    wake(handle)
    v = i2c_wr(handle, BQ34Z100_ADDR, 0x08, 2)
    voltage = (v[0] | (v[1] << 8)) if v else None
    print(f"  0x55 voltage: {voltage} mV")

    if voltage is None:
        # Scan all addresses
        print("\n  Full I2C bus scan:")
        for addr in range(0x03, 0x78):
            data_out = array('B', [0x00])
            result = aa_i2c_write(handle, addr, AA_I2C_NO_FLAGS, data_out)
            if result >= 0:
                (c, d) = aa_i2c_read(handle, addr, AA_I2C_NO_FLAGS, 1)
                if c > 0:
                    print(f"    Device at 0x{addr:02X}")

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\nDone.")
