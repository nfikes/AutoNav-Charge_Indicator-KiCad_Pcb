"""Debug BQ34Z100-R2 voltage reading issue after cell count change."""
from aardvark_py import *
from array import array
import struct

BQ = 0x55

handle = aa_open(0)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(500)

print("=" * 60)
print("  BQ34Z100-R2 Voltage Debug")
print("=" * 60)
print()


def unseal_fa():
    for subcmd in [0x0414, 0x3672, 0xFFFF, 0xFFFF]:
        d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(5)
    aa_sleep_ms(100)


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


def read_control_sub(subcmd):
    """Send control sub-command and read result."""
    d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    aa_sleep_ms(10)
    d = array('B', [0x00])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        return data[0] | (data[1] << 8)
    return None


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
    return list(raw[:32])


# Wake
for i in range(6):
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
    aa_sleep_ms(100)

# Read ALL standard commands
print("--- Standard Command Registers ---")
cmds = [
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
]
for cmd, n, name, signed in cmds:
    val = read_std(cmd, n, signed)
    if val is not None:
        extra = ""
        if name == "Temperature":
            extra = f" ({val*0.1 - 273.15:.1f} C)"
        elif name == "Flags" or name == "FlagsB":
            extra = f" (0x{val:04X})"
        print(f"  0x{cmd:02X} {name:15s}: {val}{extra}")
    else:
        print(f"  0x{cmd:02X} {name:15s}: READ FAIL")

# Extended commands
print()
print("--- Extended Commands ---")
ext_cmds = [
    (0x1C, 2, "AvgPower", True),
    (0x1E, 2, "InternalTemp", False),
    (0x20, 2, "CycleCount", False),
    (0x22, 2, "SOH", False),
    (0x24, 2, "ChargeVoltage", False),
    (0x26, 2, "ChargeCurrent", False),
    (0x28, 2, "PackVoltage", False),
    (0x2A, 2, "AvgPower2", True),
    (0x2C, 2, "Cmd_0x2C", False),
    (0x2E, 2, "Cmd_0x2E", False),
    (0x30, 2, "Cmd_0x30", False),
    (0x32, 2, "Cmd_0x32", False),
    (0x3C, 2, "DesignCap", False),
]
for cmd, n, name, signed in ext_cmds:
    val = read_std(cmd, n, signed)
    if val is not None:
        extra = ""
        if name == "InternalTemp":
            extra = f" ({val*0.1 - 273.15:.1f} C)"
        print(f"  0x{cmd:02X} {name:15s}: {val}{extra}")
    else:
        print(f"  0x{cmd:02X} {name:15s}: READ FAIL")

# Control sub-commands
print()
print("--- Control Sub-commands ---")
unseal_fa()
status = read_control_sub(0x0000)
if status is not None:
    print(f"  Control Status  : 0x{status:04X}")
    print(f"    SS={bool(status&(1<<13))}, FAS={bool(status&(1<<14))}")
    print(f"    VOK={bool(status&(1<<1))}")  # Voltage OK
    print(f"    QEN={bool(status&(1<<0))}")  # Impedance tracking

chem = read_control_sub(0x0008)
if chem is not None:
    print(f"  Chemistry ID    : 0x{chem:04X}")

fw = read_control_sub(0x0002)
if fw is not None:
    print(f"  FW Version      : 0x{fw:04X}")

# Read key DF values
print()
print("--- Data Flash Check ---")
unseal_fa()

blk64 = read_block(64)
if blk64:
    pc = (blk64[0] << 8) | blk64[1]
    cells = blk64[7]
    voltsel = bool(pc & 0x0008)
    print(f"  Pack Config: 0x{pc:04X} (VOLTSEL={int(voltsel)} "
          f"{'EXT — correct' if voltsel else 'INT — suboptimal'})")
    print(f"  Cell Count : {cells}")
    print(f"  Block: {' '.join(f'{b:02X}' for b in blk64[:16])}")

blk104 = read_block(104)
if blk104:
    vd = (blk104[14] << 8) | blk104[15]
    cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0]
    print(f"  VD         : {vd}")
    print(f"  CC Gain    : {cc_g:.6g}")

blk68 = read_block(68)
if blk68:
    fu_v = (blk68[0] << 8) | blk68[1]
    print(f"  Flash Update OK V: {fu_v} mV")
    print(f"  SC68 Block: {' '.join(f'{b:02X}' for b in blk68[:16])}")

# Try IT_ENABLE
print()
print("--- Trying IT_ENABLE (0x0021) ---")
d = array('B', [0x00, 0x21, 0x00])
aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
aa_sleep_ms(3000)

v = read_std(0x0A)
t = read_std(0x0E)
print(f"  Voltage after IT_ENABLE: {v} mV")
if t:
    print(f"  Temperature: {t*0.1 - 273.15:.1f} C")

# Try RESET one more time with longer wait
print()
print("--- Reset with 10s wait ---")
d = array('B', [0x00, 0x41, 0x00])
aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
aa_sleep_ms(10000)

for i in range(10):
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
    aa_sleep_ms(200)

v = read_std(0x0A)
t = read_std(0x0E)
c = read_std(0x14, signed=True)
print(f"  Voltage()    : {v} mV")
if t:
    print(f"  Temperature(): {t*0.1 - 273.15:.1f} C")
if c is not None:
    print(f"  Current()    : {c} mA")

# Check flags
flags = read_std(0x10)
if flags is not None:
    print(f"  Flags        : 0x{flags:04X}")

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print()
print("Done.")
