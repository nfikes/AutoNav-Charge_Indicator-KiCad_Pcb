"""BQ34Z100-R2 — Comprehensive recovery + voltage investigation.

Chip 1G: known CC-calibration-killed state (Voltage=8mV).
Plan:
  Phase 1: Restore factory defaults (CC, Pack Config) + RESET -> recover
  Phase 2: Measure BAT pin loading effect (the chip's own current draw
           through the 200k/6.49k divider may collapse BAT during measurement)
  Phase 3: Try every VD / cell-count combo to maximize reported voltage
  Phase 4: Voltage tracking test (does BQ follow INA226 when supply changes?)
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *
from array import array
import struct

BQ = 0x55
INA = 0x40
handle = aa_open(0)
if handle < 0:
    print(f"Aardvark open failed: {handle}")
    exit(1)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(1000)


# ============================================================================
#  Helpers
# ============================================================================

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
    return list(raw[:32])


def write_block(subclass, modified, block=0):
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
        return False
    aa_sleep_ms(2000)
    return True


def read_ina_bus():
    d = array('B', [0x02])
    aa_i2c_write(handle, INA, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        return int(((data[0] << 8) | data[1]) * 1.25)
    return None


def snapshot(label):
    print(f"\n  --- {label} ---")
    v = read_std(0x0A)
    pv = read_std(0x28)
    t = read_std(0x0E)
    it = read_std(0x1E)
    ina = read_ina_bus()
    t_str = f"{t*0.1-273.15:.1f}C" if t is not None else "FAIL"
    it_str = f"{it*0.1-273.15:.1f}C" if it is not None else "FAIL"
    print(f"    Voltage()    : {v} mV")
    print(f"    PackVoltage(): {pv} mV")
    print(f"    Temperature  : {t} ({t_str})")
    print(f"    InternalTemp : {it} ({it_str})")
    print(f"    INA226 Bus   : {ina} mV")
    if v and v > 0 and ina:
        print(f"    INA/BQ ratio : {ina/v:.1f}x")
    return v, pv, ina


def do_reset(wait=10):
    print(f"\n  Sending RESET (0x0041)... waiting {wait}s...")
    unseal_fa()
    send_control(0x0041)
    aa_sleep_ms(wait * 1000)
    wake_df_safe()
    aa_sleep_ms(2000)


# ============================================================================
#  PHASE 1: Recovery — restore factory defaults
# ============================================================================

print("=" * 70)
print("  PHASE 1: Recovery — Restore Factory Defaults")
print("=" * 70)

wake_df_safe()
v0, pv0, ina0 = snapshot("Initial State (Chip 1G)")

# Read current DF
blk104 = read_block(104)
blk64 = read_block(64)

if blk104:
    cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0]
    cc_d = struct.unpack('>f', bytes(blk104[4:8]))[0]
    vd = (blk104[14] << 8) | blk104[15]
    print(f"\n    CC Gain  : {cc_g:.6g}")
    print(f"    CC Delta : {cc_d:.6g}")
    print(f"    VD       : {vd}")

if blk64:
    pc = (blk64[0] << 8) | blk64[1]
    cells = blk64[7]
    print(f"    PackConfig: 0x{pc:04X}  Cells: {cells}")

# Step 1a: Restore Pack Config to factory 0x41D9
if blk64:
    pc = (blk64[0] << 8) | blk64[1]
    if pc != 0x41D9:
        print(f"\n  Restoring Pack Config: 0x{pc:04X} -> 0x41D9")
        mod64 = list(blk64)
        mod64[0] = 0x41
        mod64[1] = 0xD9
        if write_block(64, mod64):
            print("    OK")
        else:
            print("    FAILED")

# Step 1b: Restore CC Gain/Delta to 10mOhm factory defaults
if blk104:
    factory_gain = 0.4768
    factory_delta = 567744.5
    cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0]
    if abs(cc_g - factory_gain) > 0.01:
        print(f"\n  Restoring CC Gain: {cc_g:.6g} -> {factory_gain}")
        print(f"  Restoring CC Delta: -> {factory_delta}")
        blk104 = read_block(104)  # Re-read after potential seal
        if blk104:
            mod104 = list(blk104)
            mod104[0:4] = list(struct.pack('>f', factory_gain))
            mod104[4:8] = list(struct.pack('>f', factory_delta))
            if write_block(104, mod104):
                print("    OK")
            else:
                print("    FAILED")

# RESET
do_reset(10)
v1, pv1, ina1 = snapshot("After Factory Restore + RESET")

if v1 is not None and v1 > 0:
    print("\n  >>> PHASE 1 SUCCESS — voltage recovered! <<<")
else:
    print("\n  Phase 1 did not recover voltage. Trying SHUTDOWN + power cycle...")
    unseal_fa()
    send_control(0x0010)
    aa_sleep_ms(3000)
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    print("  Power OFF for 10 seconds...")
    aa_sleep_ms(10000)
    aa_target_power(handle, AA_TARGET_POWER_BOTH)
    aa_sleep_ms(3000)
    wake_df_safe()
    aa_sleep_ms(3000)
    v1, pv1, ina1 = snapshot("After SHUTDOWN + Power Cycle")

    if v1 is not None and v1 > 0:
        print("\n  >>> Recovered after power cycle! <<<")
    else:
        # Try IT_ENABLE
        print("\n  Trying IT_ENABLE (0x0021)...")
        unseal_fa()
        send_control(0x0021)
        aa_sleep_ms(10000)
        v1, pv1, ina1 = snapshot("After IT_ENABLE")

        if v1 is None or v1 == 0:
            print("\n  All recovery attempts failed. Chip may need extended rest.")
            print("  Continuing with investigation anyway...")


# ============================================================================
#  PHASE 2: Loading Theory Investigation
# ============================================================================

print("\n\n" + "=" * 70)
print("  PHASE 2: BAT Pin Loading Investigation")
print("=" * 70)
print("""
  THEORY: The chip's own operating current (~100uA) flows through the
  voltage divider (R_th = R27||R22 = 6.3kOhm). This causes a voltage
  drop of ~630mV at BAT, collapsing it from 786mV to ~150mV.

  The ADC reading of ~40mV might be correct for the ACTUAL BAT voltage
  under load, not the unloaded divider voltage.

  Test: Read voltage rapidly vs slowly. If the chip samples between
  its own current spikes, readings might vary.
""")

print("  Rapid-fire voltage reads (20 samples, no delay):")
readings = []
for i in range(20):
    v = read_std(0x0A)
    readings.append(v)
    aa_sleep_ms(50)
print(f"    Values: {readings}")
non_none = [x for x in readings if x is not None]
if non_none:
    print(f"    Min={min(non_none)} Max={max(non_none)} Avg={sum(non_none)/len(non_none):.1f}")

# Check Control Status for operating mode info
unseal_fa()
send_control(0x0000)
aa_sleep_ms(10)
d = array('B', [0x00])
aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
(rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
if rc == 2:
    cs = data[0] | (data[1] << 8)
    print(f"\n    ControlStatus: 0x{cs:04X}")
    print(f"      VOK={bool(cs&2)}, QEN={bool(cs&1)}, SLEEP={bool(cs&16)}")
    print(f"      SS={bool(cs&(1<<13))}, FAS={bool(cs&(1<<14))}")

# Read OperationStatus for IT algorithm state
unseal_fa()
send_control(0x0054)
aa_sleep_ms(10)
d = array('B', [0x00])
aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
(rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
if rc == 2:
    ops = data[0] | (data[1] << 8)
    print(f"    OperationStatus: 0x{ops:04X}")


# ============================================================================
#  PHASE 3: VD + Cell Count Experiments
# ============================================================================

print("\n\n" + "=" * 70)
print("  PHASE 3: VD + Cell Count Experiments")
print("=" * 70)
print("""
  The BQ uses VD (Voltage Divider) and Cell Count to compute pack voltage.
  We'll try different combos to see what changes the reported values.

  Current: VD=5000, Cells=1 (factory)
""")

# Read current VD and cells
blk104 = read_block(104)
blk64 = read_block(64)
if not blk104 or not blk64:
    print("  DF read failed, skipping phase 3")
else:
    current_vd = (blk104[14] << 8) | blk104[15]
    current_cells = blk64[7]
    current_pc = (blk64[0] << 8) | blk64[1]
    print(f"  Current: VD={current_vd}, Cells={current_cells}, PC=0x{current_pc:04X}")

    # Read baseline
    v_base = read_std(0x0A)
    pv_base = read_std(0x28)
    ina_base = read_ina_bus()
    print(f"  Baseline: V()={v_base}mV  PV()={pv_base}mV  INA={ina_base}mV")

    # Test different VD values (no RESET needed — VD is used by firmware in real-time?)
    # Actually, DF changes DO need RESET. But let's try a few VD values.
    test_configs = [
        # (vd, cells, voltsel_bit, label)
        (65535, 1, True,  "VD=MAX, Cells=1, VOLTSEL=1"),
        (5000,  1, False, "VD=5000, Cells=1, VOLTSEL=0 (INT divider)"),
        (65535, 1, False, "VD=MAX, Cells=1, VOLTSEL=0"),
        (5000,  1, True,  "Restore: VD=5000, Cells=1, VOLTSEL=1"),
    ]

    for vd_val, cells_val, voltsel, label in test_configs:
        print(f"\n  --- Testing: {label} ---")

        # Read fresh blocks (auto-sealed after each write)
        blk104 = read_block(104)
        blk64 = read_block(64)
        if not blk104 or not blk64:
            print("    DF read failed, skipping")
            continue

        # Modify VD
        mod104 = list(blk104)
        mod104[14] = (vd_val >> 8) & 0xFF
        mod104[15] = vd_val & 0xFF
        if not write_block(104, mod104):
            print("    VD write failed")
            continue

        # Modify cells + VOLTSEL
        blk64 = read_block(64)  # Re-read after seal
        if not blk64:
            print("    SC64 re-read failed")
            continue
        mod64 = list(blk64)
        mod64[7] = cells_val
        pc = (blk64[0] << 8) | blk64[1]
        if voltsel:
            new_pc = pc | 0x0008   # Set VOLTSEL=1
        else:
            new_pc = pc & ~0x0008  # Clear VOLTSEL=0
        mod64[0] = (new_pc >> 8) & 0xFF
        mod64[1] = new_pc & 0xFF
        if not write_block(64, mod64):
            print("    SC64 write failed")
            continue

        # RESET to apply
        do_reset(8)

        # Read results
        v = read_std(0x0A)
        pv = read_std(0x28)
        ina = read_ina_bus()
        t = read_std(0x0E)

        vs_str = "EXT(bypass)" if voltsel else "INT(5:1)"
        print(f"    V()={v}mV  PV()={pv}mV  INA={ina}mV  VOLTSEL={vs_str}")
        if v and v > 0 and ina:
            print(f"    Ratio: INA/V = {ina/v:.1f}x")
        if pv and pv > 0 and ina:
            print(f"    Ratio: INA/PV = {ina/pv:.1f}x")

    # Restore factory defaults before phase 4
    print("\n  Restoring factory VD=5000, Cells=1, PC=0x41D9...")
    blk104 = read_block(104)
    blk64 = read_block(64)
    if blk104:
        mod104 = list(blk104)
        mod104[14] = (5000 >> 8) & 0xFF
        mod104[15] = 5000 & 0xFF
        write_block(104, mod104)
    if blk64:
        mod64 = list(blk64)
        mod64[0] = 0x41
        mod64[1] = 0xD9
        mod64[7] = 1
        write_block(64, mod64)
    do_reset(8)


# ============================================================================
#  PHASE 4: Voltage Tracking Test (10 samples)
# ============================================================================

print("\n\n" + "=" * 70)
print("  PHASE 4: Voltage Tracking (10 samples at current supply)")
print("=" * 70)

print(f"\n  {'#':>3s}  {'INA mV':>8s}  {'BQ V':>6s}  {'BQ PV':>6s}  {'Ratio':>8s}")
print("  " + "-" * 40)
for i in range(10):
    v = read_std(0x0A)
    pv = read_std(0x28)
    ina = read_ina_bus()
    ratio = f"{ina/v:.1f}" if (v and v > 0 and ina) else "---"
    print(f"  {i:>3d}  {ina or 0:>8d}  {v or 0:>6d}  {pv or 0:>6d}  {ratio:>8s}")
    aa_sleep_ms(1500)


# ============================================================================
#  PHASE 5: Final DF State Dump
# ============================================================================

print("\n\n" + "=" * 70)
print("  PHASE 5: Final State")
print("=" * 70)

blk64 = read_block(64)
blk104 = read_block(104)
blk68 = read_block(68)

if blk64:
    pc = (blk64[0] << 8) | blk64[1]
    cells = blk64[7]
    print(f"  Pack Config : 0x{pc:04X}")
    print(f"  Cell Count  : {cells}")
    print(f"  VOLTSEL     : {'EXT' if pc & 0x0008 else 'INT'}")
    print(f"  RSNS        : {'HIGH' if pc & 0x0080 else 'LOW'}")

if blk104:
    cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0]
    cc_d = struct.unpack('>f', bytes(blk104[4:8]))[0]
    vd = (blk104[14] << 8) | blk104[15]
    print(f"  CC Gain     : {cc_g:.6g}")
    print(f"  CC Delta    : {cc_d:.6g}")
    print(f"  VD          : {vd}")

if blk68:
    fu_v = (blk68[0] << 8) | blk68[1]
    print(f"  Flash Upd OK: {fu_v} mV")

v_final, pv_final, ina_final = snapshot("Final Readings")

print("\n" + "=" * 70)
print("  SUMMARY")
print("=" * 70)
print(f"  INA226 (actual)  : {ina_final} mV")
print(f"  BQ Voltage()     : {v_final} mV")
print(f"  BQ PackVoltage() : {pv_final} mV")
if v_final and v_final > 0:
    bat_est = ina_final * 6.49 / 206.49 if ina_final else 0
    print(f"  Expected BAT pin : {bat_est:.0f} mV (unloaded)")
    print(f"  ADC discrepancy  : {bat_est/v_final:.1f}x (unloaded BAT / ADC reading)")
    print()
    print("  If discrepancy is ~10-20x, the chip's own current draw (~100uA)")
    print("  is loading the 200k/6.49k divider (R_th=6.3kOhm), pulling BAT")
    print("  from ~786mV to ~40mV during measurement.")
    print()
    print("  Possible fixes:")
    print("  1. Add 10uF cap on BAT (helps briefly but DC droop remains)")
    print("  2. Use a low-Iq buffer/follower to drive BAT from divider")
    print("  3. Lower R27 from 200k (but must keep BAT < 1V at 30V)")
    print("     R27=30k, R22=6.49k => BAT=5.34V at 30V => UNSAFE!")
    print("  4. Accept that BQ can't measure voltage on this divider;")
    print("     use INA226 for voltage, and explore BQ for coulomb counting only")
else:
    print("  BQ voltage is still 0 — chip did not recover.")
print("=" * 70)

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\nDone.")
