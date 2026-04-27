"""INA226 Communication Test — Rev 3 PCB
Quick check: open Aardvark, read INA226 ID registers & config,
report pass/fail.
"""
from hw_common import *

def read_u16(handle, addr, reg):
    aa_i2c_write(handle, addr, AA_I2C_NO_STOP, array('B', [reg]))
    rc, data = aa_i2c_read(handle, addr, AA_I2C_NO_FLAGS, 2)
    if rc != 2:
        return None
    return (data[0] << 8) | data[1]

def read_s16(handle, addr, reg):
    v = read_u16(handle, addr, reg)
    if v is None:
        return None
    return v - 0x10000 if v >= 0x8000 else v

# ---- Open Aardvark ----
print("=" * 50)
print("INA226 Communication Test — Rev 3 PCB")
print("=" * 50)

handle = aardvark_init()

# ---- Read identification registers ----
print(f"\nTarget address: 0x{INA:02X}")
print("-" * 50)

mfg_id = read_u16(handle, INA, REG_MFG_ID)
die_id = read_u16(handle, INA, REG_DIE_ID)

if mfg_id is None:
    print("FAIL: No ACK on Manufacturer ID read — device not responding!")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    sys.exit(1)

print(f"Manufacturer ID (0xFE): 0x{mfg_id:04X}  {'PASS' if mfg_id == 0x5449 else 'UNEXPECTED (expect 0x5449)'}")
print(f"Die ID          (0xFF): 0x{die_id:04X}  {'PASS' if die_id == 0x2260 else 'UNEXPECTED (expect 0x2260)'}")

# ---- Read functional registers ----
config  = read_u16(handle, INA, REG_CONFIG)
shunt_v = read_s16(handle, INA, REG_SHUNT_V)
bus_v   = read_u16(handle, INA, REG_BUS_V)
cal     = read_u16(handle, INA, REG_CAL)

print(f"\nConfig          (0x00): 0x{config:04X}" if config is not None else "Config: READ FAIL")
print(f"Shunt Voltage   (0x01): 0x{shunt_v:04X}  ({shunt_v * 2.5e-3:.4f} mV)" if shunt_v is not None else "Shunt Voltage: READ FAIL")
print(f"Bus Voltage     (0x02): 0x{bus_v:04X}  ({bus_v * 1.25e-3:.3f} V)" if bus_v is not None else "Bus Voltage: READ FAIL")
print(f"Calibration     (0x05): 0x{cal:04X}  ({cal})" if cal is not None else "Calibration: READ FAIL")

# ---- Summary ----
print("\n" + "=" * 50)
if mfg_id == 0x5449 and die_id == 0x2260:
    print("RESULT: INA226 communication OK")
    if bus_v is not None and bus_v > 0:
        print(f"  Bus voltage reads {bus_v * 1.25e-3:.3f} V")
    elif bus_v == 0:
        print("  Bus voltage = 0 V (no power on bus?)")
else:
    print("RESULT: Unexpected ID — wrong device or communication error")

# ---- Cleanup ----
aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
