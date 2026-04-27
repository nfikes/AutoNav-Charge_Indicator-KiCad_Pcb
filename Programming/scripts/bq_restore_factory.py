"""BQ34Z100-R2 Factory Default Restore — recover locked-up gauge.

Theory: The fresh chip read 33mV with factory defaults (Pack Config 0x41D9).
After we wrote RSNS fix (0x4159) + CC calibration + RESET, the IT algorithm
locked up at 0mV. Restoring factory defaults and resetting may allow
the IT algorithm to reinitialize at BAT=0.94V, since it worked there before.

Strategy:
  1. Read current DF state
  2. Restore Pack Config to factory 0x41D9 (RSNS=HIGH, VOLTSEL=1)
  3. Restore CC Gain/Delta to 10mOhm defaults (0.4768 / 567744.5)
  4. Leave Flash Update OK V at 0 (enables writes at low BAT)
  5. RESET and check if voltage recovers
  6. If that fails, try SHUTDOWN + full power cycle
"""
import struct
from hw_common import *

# Factory default values
FACTORY_PACK_CONFIG = 0x41D9   # VOLTSEL=1/EXT, RSNS=HIGH
FACTORY_CC_GAIN = 0.4768       # 4.768 / 10mOhm default
FACTORY_CC_DELTA = 567744.5    # 5677445.3 / 10mOhm default

handle = aardvark_init()

print("=" * 60)
print("  BQ34Z100-R2 Factory Default Restore")
print("=" * 60)
print()


# ---------------------------------------------------------------------------
#  Helpers (same proven patterns from bq_recover.py)
# ---------------------------------------------------------------------------

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


def read_control_status():
    send_control(0x0000)
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
    unseal_fa()
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
            print(f"    WARNING: Stale/sealed data in SC {subclass}")
            return None
    return blk


def write_block(subclass, modified, block=0):
    """Write 32-byte block to data flash. Re-unseals before setup."""
    unseal_fa()
    for reg, val in [(0x61, 0x00), (0x3E, subclass), (0x3F, block)]:
        d = array('B', [reg, val])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(10)
    aa_sleep_ms(100)
    for i in range(32):
        d = array('B', [0x40 + i, modified[i]])
        c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        if c != 2:
            print(f"    Write NACK at offset {i}")
            return False
        aa_sleep_ms(3)
    cksum = (255 - (sum(modified) & 0xFF)) & 0xFF
    aa_sleep_ms(20)
    d = array('B', [0x60, cksum])
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    if c != 2:
        print(f"    Checksum commit NACK")
        return False
    aa_sleep_ms(2000)  # Wait for flash commit
    return True


def show_status(label):
    print(f"\n  --- {label} ---")
    v = read_std(0x0A)
    pv = read_std(0x28)
    t = read_std(0x0E)
    it = read_std(0x1E)
    c = read_std(0x14, signed=True)
    flags = read_std(0x10)

    print(f"    Voltage()     : {v} mV")
    print(f"    PackVoltage() : {pv} mV")
    if t is not None:
        print(f"    Temperature() : {t} raw ({t*0.1-273.15:.1f} C)")
    if it is not None:
        print(f"    InternalTemp(): {it} raw ({it*0.1-273.15:.1f} C)")
    if c is not None:
        print(f"    Current()     : {c} mA")
    if flags is not None:
        print(f"    Flags         : 0x{flags:04X}")

    # Re-unseal since we need Control access (previous DF reads may have
    # used Control for unseal, disrupting context, but show_status is
    # called after DF operations are done)
    unseal_fa()
    status = read_control_status()
    if status is not None:
        print(f"    CtrlStatus    : 0x{status:04X}")
        print(f"      VOK={bool(status&2)}, QEN={bool(status&1)}, "
              f"SLEEP={bool(status&(1<<4))}")

    # INA226 bus voltage for reference
    ina_d = array('B', [0x02])
    aa_i2c_write(handle, INA, AA_I2C_NO_STOP, ina_d)
    (rc, ina_data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        ina_mv = int(((ina_data[0] << 8) | ina_data[1]) * 1.25)
        print(f"    INA226 Bus V  : {ina_mv} mV")

    recovered = v is not None and v > 0
    if recovered:
        print(f"    *** VOLTAGE IS READING! ***")
    return recovered


# ---------------------------------------------------------------------------
#  Initial state
# ---------------------------------------------------------------------------

print("Waking (DF-safe)...")
wake_df_safe()

recovered = show_status("Initial State (before any changes)")
if recovered:
    print("\n  Gauge is already reading voltage! No recovery needed.")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    exit(0)


# ---------------------------------------------------------------------------
#  Read current DF values
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("  Reading Current Data Flash State")
print("=" * 60)

blk64 = read_block(64)
if blk64:
    pc = (blk64[0] << 8) | blk64[1]
    cells = blk64[7]
    print(f"  SC 64 Pack Config : 0x{pc:04X}  (factory=0x{FACTORY_PACK_CONFIG:04X})")
    print(f"  SC 64 Cell Count  : {cells}")
    print(f"  SC 64 Block       : {' '.join(f'{b:02X}' for b in blk64[:16])}")
else:
    print("  SC 64 read FAILED")

blk104 = read_block(104)
if blk104:
    cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0]
    cc_d = struct.unpack('>f', bytes(blk104[4:8]))[0]
    vd = (blk104[14] << 8) | blk104[15]
    print(f"  SC 104 CC Gain    : {cc_g:.6g}  (factory={FACTORY_CC_GAIN:.6g})")
    print(f"  SC 104 CC Delta   : {cc_d:.6g}  (factory={FACTORY_CC_DELTA:.6g})")
    print(f"  SC 104 VD         : {vd}")
    print(f"  SC 104 Block      : {' '.join(f'{b:02X}' for b in blk104[:16])}")
else:
    print("  SC 104 read FAILED")

blk68 = read_block(68)
if blk68:
    fu_v = (blk68[0] << 8) | blk68[1]
    print(f"  SC 68 Flash Update OK V: {fu_v} mV  (factory=2800)")
else:
    print("  SC 68 read FAILED")


# ---------------------------------------------------------------------------
#  STRATEGY 1: Restore Pack Config to factory 0x41D9
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("  STRATEGY 1: Restore Pack Config to Factory Default")
print("=" * 60)

if blk64:
    pc = (blk64[0] << 8) | blk64[1]
    if pc == FACTORY_PACK_CONFIG:
        print("  Pack Config already at factory default 0x41D9.")
    else:
        print(f"  Changing Pack Config: 0x{pc:04X} -> 0x{FACTORY_PACK_CONFIG:04X}")
        mod64 = list(blk64)
        mod64[0] = (FACTORY_PACK_CONFIG >> 8) & 0xFF
        mod64[1] = FACTORY_PACK_CONFIG & 0xFF
        if write_block(64, mod64):
            print("  Written OK — verifying...")
            verify64 = read_block(64)
            if verify64:
                vpc = (verify64[0] << 8) | verify64[1]
                print(f"  Verified: 0x{vpc:04X} {'PASS' if vpc == FACTORY_PACK_CONFIG else 'FAIL'}")
            else:
                print("  Verify read failed")
        else:
            print("  Write FAILED")

    # RESET
    print("\n  Sending RESET (0x0041)...")
    unseal_fa()
    send_control(0x0041)
    print("  Waiting 8 seconds...")
    aa_sleep_ms(8000)

    wake_df_safe()
    aa_sleep_ms(1000)

    recovered = show_status("After Pack Config Restore + RESET")
    if recovered:
        print("\n  *** RECOVERED via Pack Config restore! ***")
else:
    print("  Cannot restore — SC 64 read failed earlier")


# ---------------------------------------------------------------------------
#  STRATEGY 2: Also restore CC Gain/Delta to defaults
# ---------------------------------------------------------------------------

if not recovered and blk104:
    print("\n" + "=" * 60)
    print("  STRATEGY 2: Restore CC Gain/Delta to Factory Defaults")
    print("=" * 60)

    # Re-read SC 104 (auto-sealed after previous write)
    blk104 = read_block(104)
    if blk104:
        mod104 = list(blk104)
        gain_bytes = list(struct.pack('>f', FACTORY_CC_GAIN))
        delta_bytes = list(struct.pack('>f', FACTORY_CC_DELTA))
        mod104[0:4] = gain_bytes
        mod104[4:8] = delta_bytes
        print(f"  Writing CC Gain={FACTORY_CC_GAIN:.6g}, CC Delta={FACTORY_CC_DELTA:.6g}")

        if write_block(104, mod104):
            print("  Written OK — verifying...")
            verify104 = read_block(104)
            if verify104:
                vg = struct.unpack('>f', bytes(verify104[0:4]))[0]
                vd_val = struct.unpack('>f', bytes(verify104[4:8]))[0]
                print(f"  CC Gain:  {vg:.6g}  {'PASS' if abs(vg - FACTORY_CC_GAIN) < 0.001 else 'FAIL'}")
                print(f"  CC Delta: {vd_val:.6g}  {'PASS' if abs(vd_val - FACTORY_CC_DELTA) < 100 else 'FAIL'}")
        else:
            print("  Write FAILED")

        # RESET
        print("\n  Sending RESET (0x0041)...")
        unseal_fa()
        send_control(0x0041)
        print("  Waiting 8 seconds...")
        aa_sleep_ms(8000)

        wake_df_safe()
        aa_sleep_ms(1000)

        recovered = show_status("After CC Cal Restore + RESET")
        if recovered:
            print("\n  *** RECOVERED via CC Cal restore! ***")
    else:
        print("  SC 104 re-read failed")


# ---------------------------------------------------------------------------
#  STRATEGY 3: SHUTDOWN + full power cycle (drain everything)
# ---------------------------------------------------------------------------

if not recovered:
    print("\n" + "=" * 60)
    print("  STRATEGY 3: SHUTDOWN + Full Power Cycle")
    print("=" * 60)
    print("  Sending SHUTDOWN (0x0010)...")
    unseal_fa()
    send_control(0x0010)
    print("  Waiting 5 seconds...")
    aa_sleep_ms(5000)

    print("  Turning OFF Aardvark target power for 10 seconds...")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_sleep_ms(10000)

    print("  Turning ON Aardvark target power...")
    aa_target_power(handle, AA_TARGET_POWER_BOTH)
    aa_sleep_ms(3000)

    print("  Waking...")
    wake_df_safe()
    aa_sleep_ms(2000)

    recovered = show_status("After SHUTDOWN + Power Cycle")
    if recovered:
        print("\n  *** RECOVERED via SHUTDOWN + Power Cycle! ***")


# ---------------------------------------------------------------------------
#  STRATEGY 4: IT_ENABLE after factory restore
# ---------------------------------------------------------------------------

if not recovered:
    print("\n" + "=" * 60)
    print("  STRATEGY 4: IT_ENABLE + Wait")
    print("=" * 60)
    print("  The IT algorithm may need an explicit kick after factory restore.")
    unseal_fa()
    print("  Sending IT_ENABLE (0x0021)...")
    send_control(0x0021)
    print("  Waiting 10 seconds for IT to initialize...")
    aa_sleep_ms(10000)

    recovered = show_status("After IT_ENABLE + 10s Wait")
    if recovered:
        print("\n  *** RECOVERED via IT_ENABLE! ***")


# ---------------------------------------------------------------------------
#  Final DF state dump
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("  Final Data Flash State")
print("=" * 60)

blk64 = read_block(64)
if blk64:
    pc = (blk64[0] << 8) | blk64[1]
    voltsel = bool(pc & 0x0008)
    rsns = bool(pc & 0x0080)
    ext = "EXT" if voltsel else "INT"
    rstr = "HIGH" if rsns else "LOW"
    print(f"  Pack Config    : 0x{pc:04X}  VOLTSEL={int(voltsel)}/{ext}  RSNS={int(rsns)}/{rstr}")
    print(f"  Cell Count     : {blk64[7]}")

blk104 = read_block(104)
if blk104:
    cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0]
    cc_d = struct.unpack('>f', bytes(blk104[4:8]))[0]
    vd = (blk104[14] << 8) | blk104[15]
    print(f"  CC Gain        : {cc_g:.6g}")
    print(f"  CC Delta       : {cc_d:.6g}")
    print(f"  VD             : {vd}")

blk68 = read_block(68)
if blk68:
    fu_v = (blk68[0] << 8) | blk68[1]
    print(f"  Flash Update OK: {fu_v} mV")


# ---------------------------------------------------------------------------
#  Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
if recovered:
    print("  RECOVERY SUCCESSFUL!")
    print()
    print("  The gauge is measuring voltage again with factory defaults.")
    print("  Pack Config is now 0x41D9 (RSNS=HIGH, VOLTSEL=1/EXT).")
    print("  CC calibration is at 10mOhm defaults (not our 5mOhm values).")
    print()
    print("  DO NOT rush to reconfigure! Next steps:")
    print("  1. Monitor voltage for a few minutes to confirm stability")
    print("  2. Try a RESET alone — verify voltage survives")
    print("  3. Then add ONE config change at a time:")
    print("     a. RSNS fix (0x41D9 -> 0x4159) -> RESET -> check voltage")
    print("     b. CC cal (5mOhm values) -> RESET -> check voltage")
    print("     c. VD calibration -> RESET -> check voltage")
    print("  4. Each step: if voltage dies, you know which write caused it")
else:
    print("  ALL RECOVERY STRATEGIES FAILED")
    print()
    print("  Factory defaults restored but IT algorithm still won't initialize.")
    print("  This chip's analog subsystem may be permanently stuck.")
    print()
    print("  Options:")
    print("  1. Leave board powered for 15-20 min (like fresh chip warmup)")
    print("     then run this script again")
    print("  2. Disconnect ALL power (supply + USB) for 5+ minutes,")
    print("     reconnect, wait 15-20 min, then run again")
    print("  3. Move to a fresh chip and use the incremental approach:")
    print("     - Wait for ACK -> Read voltage -> Bare RESET test")
    print("     - Then one config change at a time")
print("=" * 60)

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\nDone.")
