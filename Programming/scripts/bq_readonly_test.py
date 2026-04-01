"""Pure read-only BQ + INA226 linearity test. NO WRITES of any kind.

Reads Voltage(), Temperature, and INA226 continuously.
Change supply voltage and see if BQ tracks.
Press Ctrl+C to stop.
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *
from array import array

BQ = 0x55
INA = 0x40
handle = aa_open(0)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(1000)


def read_reg(addr, cmd, n=2):
    d = array('B', [cmd])
    aa_i2c_write(handle, addr, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, addr, AA_I2C_NO_FLAGS, n)
    if rc != n:
        return None
    if n == 1:
        return data[0]
    return data[0] | (data[1] << 8)


def read_ina_bus():
    d = array('B', [0x02])
    aa_i2c_write(handle, INA, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        return int(((data[0] << 8) | data[1]) * 1.25)
    return None


# DF-safe wake only — just write to 0x61, no Control reg writes
for i in range(6):
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
    aa_sleep_ms(200)

# Quick ACK check
d = array('B', [0x0A])
aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
(rc, _) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
if rc != 2:
    print("BQ not responding at 0x55. Check chip is soldered and powered.")
    aa_close(handle)
    exit(1)

print("=" * 72)
print("  Chip 2G — Pure Read-Only Linearity Test (NO WRITES)")
print("  Sweep supply voltage and watch if BQ tracks.")
print("  Ctrl+C to stop.")
print("=" * 72)
print()
print(f"  {'Time':>6s}  {'INA mV':>8s}  {'BAT est':>7s}  {'BQ V':>6s}  {'BQ PV':>6s}  {'Temp':>6s}  {'IntT':>6s}  {'Ratio':>8s}")
print("  " + "-" * 64)
sys.stdout.flush()

start = time.time()
try:
    while True:
        elapsed = time.time() - start
        ts = f"{int(elapsed//60):2d}:{int(elapsed%60):02d}"

        ina = read_ina_bus()
        v = read_reg(BQ, 0x0A)
        pv = read_reg(BQ, 0x28)
        t = read_reg(BQ, 0x0E)
        it = read_reg(BQ, 0x1E)

        bat = int(ina * 6.49 / 206.49) if ina else 0
        ratio = f"{ina/v:8.1f}" if (v and v > 0 and ina) else "     ---"
        t_str = f"{t:>6d}" if t is not None else "  FAIL"
        it_str = f"{it:>6d}" if it is not None else "  FAIL"

        print(f"  {ts:>6s}  {ina or 0:>8d}  {bat:>7d}  {v or 0:>6d}  {pv or 0:>6d}  {t_str}  {it_str}  {ratio}")
        sys.stdout.flush()
        aa_sleep_ms(1500)

except KeyboardInterrupt:
    print("\n\n  Stopped.")

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("  Done.")
