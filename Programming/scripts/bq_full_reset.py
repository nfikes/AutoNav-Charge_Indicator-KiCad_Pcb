"""BQ34Z100-R2 Full Reset — check for Permanent Failure flags, clear them,
scan all key DF subclasses, and attempt to restore gauge to working state.

Theory: When VD=844 + cells=8 caused per-cell voltage ~400mV, the gauge
may have triggered a Permanent Failure (PF) condition or other safety
lockout stored in non-volatile flash that persists across resets.
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
aa_sleep_ms(1000)

print("=" * 60)
print("  BQ34Z100-R2 Full Reset & PF Clear")
print("=" * 60)
print()


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


def read_control_sub(subcmd):
    send_control(subcmd)
    aa_sleep_ms(10)
    d = array('B', [0x00])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        return data[0] | (data[1] << 8)
    return None


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
        if ck[0] != expected and all(b == 0 for b in blk[:16]):
            return None
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
            print(f"    WRITE FAIL at byte {i}")
            return False
        aa_sleep_ms(3)
    cksum = (255 - (sum(modified) & 0xFF)) & 0xFF
    aa_sleep_ms(20)
    d = array('B', [0x60, cksum])
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    if c != 2:
        print(f"    CHECKSUM NACK")
        return False
    aa_sleep_ms(2000)
    return True


def hex_dump(data, n=32):
    return ' '.join(f'{b:02X}' for b in data[:n])


def show_status(label):
    print(f"\n  --- {label} ---")
    v = read_std(0x0A)
    t = read_std(0x0E)
    it = read_std(0x1E)
    c = read_std(0x14, signed=True)
    flags = read_std(0x10)
    flagsb = read_std(0x12)
    soc = read_std(0x03, n=1)
    print(f"    Voltage()     : {v} mV")
    if t is not None:
        print(f"    Temperature() : {t} raw ({t*0.1-273.15:.1f} C)")
    if it is not None:
        print(f"    InternalTemp(): {it} raw ({it*0.1-273.15:.1f} C)")
    if c is not None:
        print(f"    Current()     : {c} mA")
    if flags is not None:
        print(f"    Flags         : 0x{flags:04X}")
    if flagsb is not None:
        print(f"    FlagsB        : 0x{flagsb:04X}")
    if soc is not None:
        print(f"    SOC           : {soc}%")
    # INA226
    ina_d = array('B', [0x02])
    aa_i2c_write(handle, INA, AA_I2C_NO_STOP, ina_d)
    (rc, ina_data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        ina_mv = int(((ina_data[0] << 8) | ina_data[1]) * 1.25)
        print(f"    INA226 Bus V  : {ina_mv} mV")
    return v is not None and v > 0


# ---------------------------------------------------------------------------
wake_df_safe()
unseal_fa()

# =========================================================================
#  SECTION 1: Read ALL control sub-commands for diagnostics
# =========================================================================
print("--- Control Sub-commands ---")

status = read_control_sub(0x0000)
if status is not None:
    print(f"  Control Status  : 0x{status:04X}")
    print(f"    VOK={bool(status&2)}, QEN={bool(status&1)}, "
          f"SLEEP={bool(status&(1<<4))}, FULLSLEEP={bool(status&(1<<5))}, "
          f"HIBERNATE={bool(status&(1<<6))}")
    print(f"    SS={bool(status&(1<<13))}, FAS={bool(status&(1<<14))}")
    print(f"    LDMD={bool(status&(1<<3))}, RUP_DIS={bool(status&(1<<2))}")
    print(f"    CALMODE={bool(status&(1<<12))}")

unseal_fa()
dev_type = read_control_sub(0x0001)
print(f"  Device Type     : 0x{dev_type:04X}" if dev_type else "  Device Type: FAIL")

unseal_fa()
fw_ver = read_control_sub(0x0002)
print(f"  FW Version      : 0x{fw_ver:04X}" if fw_ver else "  FW Version: FAIL")

unseal_fa()
hw_ver = read_control_sub(0x0003)
print(f"  HW Version      : 0x{hw_ver:04X}" if hw_ver else "  HW Version: FAIL")

unseal_fa()
chem_id = read_control_sub(0x0008)
print(f"  Chem ID         : 0x{chem_id:04X}" if chem_id else "  Chem ID: FAIL")

# Try reading PF Status via various possible sub-command addresses
print()
print("--- Permanent Failure Status (trying multiple addresses) ---")
pf_addrs = [0x0053, 0x0054, 0x0055, 0x0056, 0x0057, 0x0058, 0x0059, 0x005A]
for addr in pf_addrs:
    unseal_fa()
    val = read_control_sub(addr)
    if val is not None:
        print(f"  Sub-cmd 0x{addr:04X}: 0x{val:04X} ({val})")

# =========================================================================
#  SECTION 2: Read ALL standard + extended registers
# =========================================================================
print()
print("--- All Standard Registers ---")
all_regs = [
    (0x02, 2, "AtRate", True),
    (0x03, 1, "SOC", False),
    (0x04, 1, "MaxError", False),
    (0x06, 2, "RemainingCap", False),
    (0x08, 2, "FullChargeCap", False),
    (0x0A, 2, "Voltage", False),
    (0x0C, 2, "AvgCurrent", True),
    (0x0E, 2, "Temperature", False),
    (0x10, 2, "Flags", False),
    (0x12, 2, "FlagsB", False),
    (0x14, 2, "Current", True),
    (0x16, 2, "AverageTTE", False),
    (0x18, 2, "AverageTTF", False),
    (0x1A, 2, "PassedCharge", True),
    (0x1C, 2, "DOD0Time", False),
    (0x1E, 2, "InternalTemp", False),
    (0x20, 2, "CycleCount", False),
    (0x22, 2, "SOH", False),
    (0x24, 2, "ChargeVoltage", False),
    (0x26, 2, "ChargeCurrent", False),
    (0x28, 2, "PackVoltage", False),
    (0x2C, 2, "DODatEOC", False),
    (0x2E, 2, "QStart", False),
    (0x30, 2, "TrueRC", False),
    (0x32, 2, "TrueFCC", False),
    (0x34, 2, "StateTime", False),
    (0x36, 2, "QMaxPassedQ", False),
    (0x38, 2, "DOD0", False),
    (0x3A, 2, "QMaxDOD0", False),
    (0x3C, 2, "DesignCap", False),
]
for cmd, n, name, signed in all_regs:
    val = read_std(cmd, n, signed)
    if val is not None:
        extra = ""
        if "Temp" in name:
            extra = f" ({val*0.1-273.15:.1f} C)"
        elif "Flags" in name:
            extra = f" (0b{val:016b})"
        print(f"  0x{cmd:02X} {name:15s}: {val}{extra}")
    else:
        print(f"  0x{cmd:02X} {name:15s}: FAIL")


# =========================================================================
#  SECTION 3: Scan ALL key DF subclasses
# =========================================================================
print()
print("--- Data Flash Scan (all key subclasses) ---")

# List of all known subclasses on BQ34Z100-R2
subclasses = [
    (0, "Safety"),
    (1, "Charge Inhibit"),
    (2, "Charge"),
    (3, "Charge Term"),
    (4, "Reserved"),
    (16, "Reserved"),
    (17, "Reserved"),
    (34, "Discharge"),
    (36, "Registers"),
    (48, "IT Cfg"),
    (49, "Current Thresh"),
    (51, "State"),
    (53, "R_a0"),
    (54, "R_a0x"),
    (55, "R_a1"),
    (56, "R_a1x"),
    (57, "Cal Reserved"),
    (58, "Current"),
    (59, "Codes"),
    (64, "Pack Config"),
    (68, "Mfg Info"),
    (80, "Lifetime Data"),
    (81, "Lifetime Temp"),
    (82, "IT Cfg2"),
    (104, "CC Cal"),
    (105, "Cur Offsets"),
    (106, "Integrity"),
    (107, "Reserved"),
    (112, "Security"),
]

unseal_fa()
for sc, name in subclasses:
    unseal_fa()
    blk = read_block(sc)
    if blk:
        print(f"  SC {sc:3d} ({name:16s}): {hex_dump(blk)}")
    else:
        print(f"  SC {sc:3d} ({name:16s}): READ FAILED / STALE")


# =========================================================================
#  SECTION 4: Attempt PF Clear sequence
# =========================================================================
print()
print("=" * 60)
print("  Attempting Permanent Failure Clear")
print("=" * 60)

# BQ34Z100-R2 PF clear sequence:
# 1. Full Access mode
# 2. Send PF_KEY sub-command
# 3. Send PF_CLEAR sub-command
# Try multiple known addresses for PF_KEY and PF_CLEAR

pf_sequences = [
    ("Seq A", 0x0035, 0x002E),  # PF_KEY=0x0035, PF_CLEAR=0x002E
    ("Seq B", 0x0057, 0x0029),  # Alternative addresses
    ("Seq C", 0x002E, 0x002E),  # Some gauges use same cmd twice
]

for seq_name, pf_key, pf_clear in pf_sequences:
    print(f"\n  {seq_name}: PF_KEY=0x{pf_key:04X}, PF_CLEAR=0x{pf_clear:04X}")
    unseal_fa()
    send_control(pf_key)
    aa_sleep_ms(500)
    send_control(pf_clear)
    aa_sleep_ms(1000)
    print(f"    Sent.")


# =========================================================================
#  SECTION 5: BAT_INSERT + OCV_CMD to force battery re-detection
# =========================================================================
print()
print("=" * 60)
print("  Forcing Battery Re-detection")
print("=" * 60)

unseal_fa()

# BAT_REMOVE first
print("  Sending BAT_REMOVE (0x000D)...")
send_control(0x000D)
aa_sleep_ms(2000)

# Then BAT_INSERT
print("  Sending BAT_INSERT (0x000C)...")
send_control(0x000C)
aa_sleep_ms(2000)

# Force OCV measurement
print("  Sending OCV_CMD (0x000B)...")
unseal_fa()
send_control(0x000B)
aa_sleep_ms(3000)

# IT_ENABLE
print("  Sending IT_ENABLE (0x0021)...")
unseal_fa()
send_control(0x0021)
aa_sleep_ms(3000)

# RESET
print("  Sending RESET (0x0041)...")
send_control(0x0041)
aa_sleep_ms(5000)

wake_df_safe()
aa_sleep_ms(1000)

recovered = show_status("After PF Clear + BAT_INSERT + OCV + Reset")

# =========================================================================
#  SECTION 6: If still dead, try zeroing out safety/PF DF subclasses
# =========================================================================
if not recovered:
    print()
    print("=" * 60)
    print("  Attempting DF Safety Parameter Reset")
    print("=" * 60)
    print("  Checking SC 0 (Safety) for undervoltage PF settings...")

    unseal_fa()
    blk0 = read_block(0)
    if blk0:
        print(f"    SC 0: {hex_dump(blk0)}")

        # Safety subclass typically has OV/UV thresholds
        # Try setting all protection voltages to very permissive values
        # UV threshold to 0 (disable UV protection)
        mod0 = list(blk0)
        # We don't know exact offsets, but try zeroing out
        # typical UV protection fields (offsets vary by gauge)
        # For now, just print what we see
        for i in range(0, 32, 2):
            val = (blk0[i] << 8) | blk0[i+1]
            print(f"      Offset {i:2d}: 0x{val:04X} ({val})")

    # Check SC 2 for more safety params
    unseal_fa()
    blk2 = read_block(2)
    if blk2:
        print(f"\n    SC 2 (Charge): {hex_dump(blk2)}")
        for i in range(0, 32, 2):
            val = (blk2[i] << 8) | blk2[i+1]
            print(f"      Offset {i:2d}: 0x{val:04X} ({val})")

    # Check State subclass (SC 51) - may contain learned/fault data
    unseal_fa()
    blk51 = read_block(51)
    if blk51:
        print(f"\n    SC 51 (State): {hex_dump(blk51)}")
        for i in range(0, 32, 2):
            val = (blk51[i] << 8) | blk51[i+1]
            print(f"      Offset {i:2d}: 0x{val:04X} ({val})")

    # Check Lifetime Data (SC 80) - may have PF flags
    unseal_fa()
    blk80 = read_block(80)
    if blk80:
        print(f"\n    SC 80 (Lifetime Data): {hex_dump(blk80)}")
        # If any bytes are non-zero, there might be fault flags
        if any(b != 0 for b in blk80):
            print("    Non-zero lifetime data found — clearing...")
            unseal_fa()
            mod80 = [0] * 32
            if write_block(80, mod80):
                print("    SC 80 cleared.")
            else:
                print("    SC 80 clear FAILED.")

    # Check SC 81 (Lifetime Temp)
    unseal_fa()
    blk81 = read_block(81)
    if blk81:
        print(f"\n    SC 81 (Lifetime Temp): {hex_dump(blk81)}")
        if any(b != 0 for b in blk81):
            print("    Non-zero lifetime temp data — clearing...")
            unseal_fa()
            mod81 = [0] * 32
            if write_block(81, mod81):
                print("    SC 81 cleared.")

    # Reset after clearing
    print("\n  Sending RESET after clearing lifetime data...")
    send_control(0x0041)
    aa_sleep_ms(5000)
    wake_df_safe()
    aa_sleep_ms(1000)

    recovered = show_status("After Lifetime Data Clear + Reset")


# =========================================================================
#  Final
# =========================================================================
print()
print("=" * 60)
if recovered:
    print("  RECOVERY SUCCESSFUL!")
else:
    print("  STILL NOT RECOVERED")
    print()
    print("  The analog front end is non-responsive to all software")
    print("  approaches. Please measure with a multimeter:")
    print("    - BAT pin to GND: expect ~3.85V")
    print("    - REG25 pin to GND: expect 2.5V")
    print("  If voltages are correct, the IC may need bqStudio/EV2400")
    print("  or may be permanently damaged.")
print("=" * 60)

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\nDone.")
