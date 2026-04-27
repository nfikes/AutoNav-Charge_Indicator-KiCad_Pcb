"""I2C Bus Scan — probe known addresses + full range with register reads."""
from hw_common import *

handle = aardvark_init()

def probe(addr):
    """Try to read 1 byte from register 0x00. Returns True if device ACKs."""
    aa_i2c_write(handle, addr, AA_I2C_NO_STOP, array('B', [0x00]))
    rc, data = aa_i2c_read(handle, addr, AA_I2C_NO_FLAGS, 1)
    return rc == 1

# --- Known devices first ---
print("I2C Bus Probe")
print("=" * 45)
known = [
    (INA, "INA226 (U3)"),
    (BQ,  "BQ34Z100-R2 (U1)"),
]
for addr, desc in known:
    ok = probe(addr)
    status = "ACK" if ok else "NACK"
    print(f"  0x{addr:02X}  {desc:<22s}  {status}")

# --- Full scan ---
print(f"\nFull scan (0x03-0x77):")
print("-" * 45)
found = []
for addr in range(0x03, 0x78):
    if probe(addr):
        found.append(addr)

if found:
    for a in found:
        label = ""
        for ka, kd in known:
            if ka == a:
                label = f"  <- {kd}"
        print(f"  0x{a:02X}{label}")
    print(f"\n{len(found)} device(s) responding")
else:
    print("  No devices found!")

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
