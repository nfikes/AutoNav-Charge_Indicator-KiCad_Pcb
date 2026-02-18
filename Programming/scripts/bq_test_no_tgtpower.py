"""Test BQ34Z100-R2 WITHOUT Aardvark target power.

Theory: Aardvark's 3.3V target power may be backfeeding into REG25
through internal protection diodes, overriding the 2.5V regulator
and corrupting the ADC reference. Running with target power OFF lets
the IC power itself from BAT alone.
"""
from aardvark_py import *
from array import array

BQ = 0x55
INA = 0x40

handle = aa_open(0)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)

# CRITICAL: No target power — let the IC power from BAT only
aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_sleep_ms(2000)

print("=" * 60)
print("  BQ34Z100-R2 — No Aardvark Target Power Test")
print("=" * 60)
print("  Target power: OFF")
print("  IC must power itself from BAT pin only.")
print()


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


# Wake with DF-safe method
print("Waking (DF-safe)...")
alive = False
for i in range(10):
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
    aa_sleep_ms(200)
    d = array('B', [0x0A])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, _) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        alive = True
        print(f"  I2C response on attempt {i+1}")
        break

if not alive:
    print("  No I2C response without target power.")
    print("  The board may need Aardvark target power for I2C pull-ups.")
    print()
    print("  Trying with target power ON briefly for comparison...")
    aa_target_power(handle, AA_TARGET_POWER_BOTH)
    aa_sleep_ms(1000)
    for i in range(6):
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
        aa_sleep_ms(100)
    v = read_std(0x0A)
    print(f"  With target power: Voltage()={v}")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    print("\nDone. The board needs target power for I2C to work.")
    print("Measure REG25 with ONLY the power supply (no Aardvark USB).")
    exit(0)

print()
print("--- Readings without Aardvark target power ---")
print("   (Measure REG25 pin now — should be 2.5V from internal reg)")
print()

v = read_std(0x0A)
t = read_std(0x0E)
it = read_std(0x1E)
c = read_std(0x14, signed=True)
flags = read_std(0x10)
soc = read_std(0x03, n=1)

print(f"  Voltage()     : {v} mV")
if t is not None:
    print(f"  Temperature() : {t} raw ({t*0.1-273.15:.1f} C)")
if it is not None:
    print(f"  InternalTemp(): {it} raw ({it*0.1-273.15:.1f} C)")
if c is not None:
    print(f"  Current()     : {c} mA")
if flags is not None:
    print(f"  Flags         : 0x{flags:04X}")
if soc is not None:
    print(f"  SOC           : {soc}%")

# INA226
ina_d = array('B', [0x02])
aa_i2c_write(handle, INA, AA_I2C_NO_STOP, ina_d)
(rc, ina_data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
if rc == 2:
    ina_mv = int(((ina_data[0] << 8) | ina_data[1]) * 1.25)
    print(f"  INA226 Bus V  : {ina_mv} mV")

# Control status
unseal_fa()
status = read_control_sub(0x0000)
if status is not None:
    print(f"  CtrlStatus    : 0x{status:04X}")
    print(f"    VOK={bool(status&2)}, QEN={bool(status&1)}, SLEEP={bool(status&(1<<4))}")

if v is not None and v > 0:
    print()
    print("  *** VOLTAGE IS READING! Target power was the problem! ***")

# Try reset without target power
print()
print("--- Reset without target power ---")
send_control(0x0041)
aa_sleep_ms(5000)

for i in range(8):
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
    aa_sleep_ms(200)

v2 = read_std(0x0A)
t2 = read_std(0x0E)
it2 = read_std(0x1E)
c2 = read_std(0x14, signed=True)
print(f"  Voltage()     : {v2} mV")
if t2 is not None:
    print(f"  Temperature() : {t2} raw ({t2*0.1-273.15:.1f} C)")
if it2 is not None:
    print(f"  InternalTemp(): {it2} raw ({it2*0.1-273.15:.1f} C)")
if c2 is not None:
    print(f"  Current()     : {c2} mA")

if v2 is not None and v2 > 0:
    print()
    print("  *** RECOVERED! ***")

aa_close(handle)
print("\nDone.")
print()
print("NEXT: Measure REG25 pin right now (Aardvark still connected")
print("but target power is OFF). It should read 2.5V if the internal")
print("regulator is working correctly.")
