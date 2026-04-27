"""BQ34Z100-R2 — Calibration Mode ADC Test.

Enter calibration mode to see if the raw ADC reads the true BAT pin voltage
(~786mV at 25V supply) rather than the IT algorithm's processed ~45mV.
"""
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


def read_control_status():
    send_control(0x0000)
    aa_sleep_ms(10)
    d = array('B', [0x00])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        return data[0] | (data[1] << 8)
    return None


# Wake
for i in range(6):
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
    aa_sleep_ms(100)

print("=" * 60)
print("  BQ34Z100-R2 — Calibration Mode ADC Test")
print("=" * 60)

# Normal mode readings
print("\n  --- Normal Mode (IT processed) ---")
v = read_std(0x0A)
pv = read_std(0x28)
t = read_std(0x0E)
it_temp = read_std(0x1E)
print(f"    Voltage()     : {v} mV")
print(f"    PackVoltage() : {pv} mV")
if t is not None:
    print(f"    Temperature() : {t} raw ({t*0.1-273.15:.1f} C)")
if it_temp is not None:
    print(f"    InternalTemp(): {it_temp} raw ({it_temp*0.1-273.15:.1f} C)")

# Enter calibration mode
print("\n  --- Entering Calibration Mode ---")
unseal_fa()
print("    CAL_ENABLE (0x002D)...")
send_control(0x002D)
aa_sleep_ms(1000)

print("    ENTER_CAL (0x0081)...")
send_control(0x0081)
aa_sleep_ms(3000)

status = read_control_status()
if status is not None:
    print(f"    CtrlStatus    : 0x{status:04X}")

# Read in CAL mode
print("\n  --- Calibration Mode Readings ---")
for sample in range(5):
    v_cal = read_std(0x0A)
    pv_cal = read_std(0x28)
    t_cal = read_std(0x0E)
    it_cal = read_std(0x1E)
    c_cal = read_std(0x14, signed=True)
    print(f"    [{sample}] V={v_cal}mV  PV={pv_cal}mV  I={c_cal}mA  T={t_cal}  IT={it_cal}")
    aa_sleep_ms(2000)

# Scan extended registers for raw ADC data
print("\n  --- Extended Register Scan ---")
for reg in range(0x28, 0x40, 2):
    val = read_std(reg)
    if val is not None:
        print(f"    0x{reg:02X}: {val} (0x{val:04X})")

# Exit calibration mode
print("\n  --- Exiting Calibration Mode ---")
send_control(0x0080)
aa_sleep_ms(3000)

# Post-cal
print("\n  --- After CAL Exit ---")
v_after = read_std(0x0A)
pv_after = read_std(0x28)
print(f"    Voltage()     : {v_after} mV")
print(f"    PackVoltage() : {pv_after} mV")

# INA226 reference
ina_d = array('B', [0x02])
aa_i2c_write(handle, INA, AA_I2C_NO_STOP, ina_d)
(rc, ina_data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
if rc == 2:
    ina_mv = int(((ina_data[0] << 8) | ina_data[1]) * 1.25)
    bat_expected = ina_mv * 6.49 / 206.49
    print(f"    INA226 Bus V  : {ina_mv} mV")
    print(f"    Expected BAT  : {bat_expected:.0f} mV")

print()
if v_cal is not None and v_cal > 100:
    print(f"  CAL mode reads {v_cal}mV — higher than normal mode!")
    print(f"  The IT algorithm was suppressing the reading.")
else:
    print(f"  CAL mode reads {v_cal}mV — same low range.")

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\nDone.")
