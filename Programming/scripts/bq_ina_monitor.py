"""Monitor BQ34Z100-R2 + INA226 side by side.

Shows both readings continuously so we can check linearity
as the supply voltage changes. Press Ctrl+C to stop.
"""
import time
from hw_common import *

handle = aardvark_init()


def read_std(addr, cmd, n=2, signed=False):
    d = array('B', [cmd])
    aa_i2c_write(handle, addr, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, addr, AA_I2C_NO_FLAGS, n)
    if rc != n:
        return None
    if n == 1:
        return data[0]
    val = data[0] | (data[1] << 8)
    if signed and val >= 0x8000:
        val -= 0x10000
    return val


def read_ina_bus():
    d = array('B', [0x02])
    aa_i2c_write(handle, INA, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        return int(((data[0] << 8) | data[1]) * 1.25)
    return None


# Wake BQ
for i in range(6):
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
    aa_sleep_ms(100)

print("=" * 70)
print("  BQ + INA226 Linearity Monitor")
print("  Change supply voltage and watch both readings.")
print("  Ctrl+C to stop.")
print("=" * 70)
print()
print(f"  {'Time':>6s}  {'INA226':>8s}  {'BAT est':>8s}  {'BQ V()':>7s}  {'BQ PV':>7s}  {'Ratio':>7s}")
print(f"  {'':>6s}  {'(mV)':>8s}  {'(mV)':>8s}  {'(mV)':>7s}  {'(mV)':>7s}  {'INA/BQ':>7s}")
print("  " + "-" * 55)

start = time.time()
try:
    while True:
        elapsed = time.time() - start
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        ts = f"{mins:2d}:{secs:02d}"

        ina_mv = read_ina_bus()
        bq_v = read_std(BQ, 0x0A)
        bq_pv = read_std(BQ, 0x28)

        bat_est = None
        ratio_str = "  ---"
        if ina_mv is not None:
            bat_est = int(ina_mv * 6.49 / 206.49)
        if bq_v is not None and bq_v > 0 and ina_mv is not None:
            ratio = ina_mv / bq_v
            ratio_str = f"{ratio:7.1f}"

        ina_str = f"{ina_mv:>8d}" if ina_mv is not None else "    FAIL"
        bat_str = f"{bat_est:>8d}" if bat_est is not None else "    FAIL"
        bqv_str = f"{bq_v:>7d}" if bq_v is not None else "   FAIL"
        bqpv_str = f"{bq_pv:>7d}" if bq_pv is not None else "   FAIL"

        print(f"  {ts:>6s}  {ina_str}  {bat_str}  {bqv_str}  {bqpv_str}  {ratio_str}")

        aa_sleep_ms(1500)

except KeyboardInterrupt:
    print("\n\n  Stopped.")

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("  Done.")
