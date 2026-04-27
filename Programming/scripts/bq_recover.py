"""BQ34Z100-R2 Recovery — attempt to restore analog measurements after lockup.

The gauge entered a persistent error state after setting VD=844 with cells=8,
which caused impossibly low per-cell voltage calculations. All DF parameters
have been restored to defaults but the analog subsystem remains dead:
  - Voltage() = 0
  - InternalTemp() = 0 (raw)
  - Current() = garbled
  - VOK = False

Recovery strategies attempted here (in order):
  1. SHUTDOWN command (0x0010) — deep power-down, then wake
  2. Calibration mode entry/exit (CAL_ENABLE + ENTER_CAL + EXIT_CAL)
     — this reconfigures the analog measurement subsystem
  3. Force Flash Update OK Voltage to 0 mV (remove BAT threshold)
  4. Toggle IT_ENABLE + RESET combination
  5. Full diagnostic dump at each stage

IMPORTANT: Before running, disconnect ALL power (supply + Aardvark USB) for
60+ seconds to drain all capacitors, then reconnect.
"""
import struct, time
from hw_common import *

handle = aardvark_init()

print("=" * 60)
print("  BQ34Z100-R2 Analog Recovery")
print("=" * 60)
print()


# ---------------------------------------------------------------------------
#  Helpers
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


def show_status(label):
    print(f"\n  --- {label} ---")
    v = read_std(0x0A)
    t = read_std(0x0E)
    it = read_std(0x1E)
    c = read_std(0x14, signed=True)
    flags = read_std(0x10)
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
    if soc is not None:
        print(f"    SOC           : {soc}%")

    status = read_control_status()
    if status is not None:
        print(f"    CtrlStatus    : 0x{status:04X}")
        print(f"      VOK={bool(status&2)}, QEN={bool(status&1)}, "
              f"SLEEP={bool(status&(1<<4))}, "
              f"SS={bool(status&(1<<13))}, FAS={bool(status&(1<<14))}")

    # INA226 for reference
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

recovered = show_status("Initial State")
if recovered:
    print("\n  Gauge is already reading voltage! No recovery needed.")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    exit(0)


# ---------------------------------------------------------------------------
#  STRATEGY 1: SHUTDOWN + Wake
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("  STRATEGY 1: SHUTDOWN Command")
print("=" * 60)
print("  Sending SHUTDOWN (0x0010)...")
unseal_fa()
send_control(0x0010)
print("  Waiting 10 seconds for full shutdown...")
aa_sleep_ms(10000)

# Turn off Aardvark target power briefly
print("  Toggling Aardvark target power (off 3s, on)...")
aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_sleep_ms(3000)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(2000)

# Wake
print("  Waking...")
wake_df_safe()
aa_sleep_ms(1000)

recovered = show_status("After SHUTDOWN + Power Toggle")
if recovered:
    print("\n  *** RECOVERED via SHUTDOWN! ***")


# ---------------------------------------------------------------------------
#  STRATEGY 2: Calibration Mode Entry/Exit
# ---------------------------------------------------------------------------

if not recovered:
    print("\n" + "=" * 60)
    print("  STRATEGY 2: Calibration Mode Entry/Exit")
    print("=" * 60)
    print("  This reconfigures the analog measurement subsystem.")
    print()

    unseal_fa()

    # CAL_ENABLE (0x002D) — must be sent first
    print("  Sending CAL_ENABLE (0x002D)...")
    send_control(0x002D)
    aa_sleep_ms(1000)

    # ENTER_CAL (0x0081)
    print("  Sending ENTER_CAL (0x0081)...")
    send_control(0x0081)
    aa_sleep_ms(3000)

    # Check if calibration mode is active
    status = read_control_status()
    if status is not None:
        cal_mode = bool(status & (1 << 12))  # CCA or CAL bit
        print(f"  Control Status: 0x{status:04X} (CAL related bit 12: {cal_mode})")

    # Read voltage in cal mode
    v_cal = read_std(0x0A)
    print(f"  Voltage in cal mode: {v_cal} mV")

    # EXIT_CAL (0x0080)
    print("  Sending EXIT_CAL (0x0080)...")
    send_control(0x0080)
    aa_sleep_ms(3000)

    # RESET after cal exit
    print("  Sending RESET (0x0041)...")
    send_control(0x0041)
    aa_sleep_ms(5000)

    wake_df_safe()
    aa_sleep_ms(1000)

    recovered = show_status("After Cal Mode Entry/Exit + Reset")
    if recovered:
        print("\n  *** RECOVERED via Calibration Mode! ***")


# ---------------------------------------------------------------------------
#  STRATEGY 3: Lower Flash Update OK Voltage threshold
# ---------------------------------------------------------------------------

if not recovered:
    print("\n" + "=" * 60)
    print("  STRATEGY 3: Lower Flash Update OK Voltage to 0")
    print("=" * 60)
    print("  The gauge may have an internal state where it thinks")
    print("  BAT voltage is too low. Lowering the threshold to 0")
    print("  removes this check entirely.")
    print()

    unseal_fa()
    blk68 = read_block(68)
    if blk68:
        fu_v = (blk68[0] << 8) | blk68[1]
        print(f"  Current Flash Update OK Voltage: {fu_v} mV")

        if fu_v != 0:
            mod68 = list(blk68)
            mod68[0] = 0x00
            mod68[1] = 0x00
            print("  Setting to 0 mV...")
            if write_block(68, mod68):
                print("  Written OK")
                unseal_fa()
                verify = read_block(68)
                if verify:
                    v_check = (verify[0] << 8) | verify[1]
                    print(f"  Verified: {v_check} mV")
            else:
                print("  Write failed")

        # Reset
        print("  Sending RESET...")
        send_control(0x0041)
        aa_sleep_ms(5000)

        wake_df_safe()
        aa_sleep_ms(1000)

        recovered = show_status("After Flash Update OK V = 0 + Reset")
        if recovered:
            print("\n  *** RECOVERED via Flash Update OK Voltage = 0! ***")

        # Always restore Flash Update OK Voltage to 2800 mV
        if fu_v != 0:
            print("\n  Restoring Flash Update OK Voltage to 2800 mV...")
            unseal_fa()
            blk68 = read_block(68)
            if blk68:
                mod68 = list(blk68)
                mod68[0] = 0x0A  # 2800 >> 8 = 0x0A
                mod68[1] = 0xF0  # 2800 & 0xFF = 0xF0
                write_block(68, mod68)
    else:
        print("  SC 68 read failed")


# ---------------------------------------------------------------------------
#  STRATEGY 4: CLEAR_FULLSLEEP + IT_ENABLE + RESET combo
# ---------------------------------------------------------------------------

if not recovered:
    print("\n" + "=" * 60)
    print("  STRATEGY 4: CLEAR_FULLSLEEP + IT_ENABLE + RESET")
    print("=" * 60)

    unseal_fa()

    # Clear full sleep mode
    print("  Sending CLEAR_FULLSLEEP (0x0012)...")
    send_control(0x0012)
    aa_sleep_ms(500)

    # Enable impedance track
    print("  Sending IT_ENABLE (0x0021)...")
    send_control(0x0021)
    aa_sleep_ms(3000)

    # Check status
    status = read_control_status()
    if status is not None:
        print(f"  Control Status: 0x{status:04X}")

    # Now reset
    print("  Sending RESET (0x0041)...")
    send_control(0x0041)
    aa_sleep_ms(8000)

    wake_df_safe()
    aa_sleep_ms(1000)

    recovered = show_status("After CLEAR_FULLSLEEP + IT_ENABLE + Reset")
    if recovered:
        print("\n  *** RECOVERED via CLEAR_FULLSLEEP + IT_ENABLE! ***")


# ---------------------------------------------------------------------------
#  STRATEGY 5: Toggle VOLTSEL, RESET, read
# ---------------------------------------------------------------------------

if not recovered:
    print("\n" + "=" * 60)
    print("  STRATEGY 5: VOLTSEL toggle + RESET")
    print("=" * 60)
    print("  Toggle internal divider mode, reset, check voltage.")
    print()

    unseal_fa()
    blk64 = read_block(64)
    if blk64:
        pc = (blk64[0] << 8) | blk64[1]
        print(f"  Pack Config: 0x{pc:04X}")

        # Try toggling VOLTSEL to force analog reconfiguration.
        # With Rev 4+ divider (R22=6.49kOhm), both modes are safe.
        mod64 = list(blk64)
        new_pc = pc ^ 0x0008  # Toggle VOLTSEL
        mod64[0] = (new_pc >> 8) & 0xFF
        mod64[1] = new_pc & 0xFF
        mod64[7] = 1
        print(f"  Toggling VOLTSEL, cells=1 (Pack Config 0x{new_pc:04X})...")
        write_block(64, mod64)

        # SHUTDOWN then power cycle
        unseal_fa()
        print("  Sending SHUTDOWN (0x0010)...")
        send_control(0x0010)
        aa_sleep_ms(2000)

        print("  Power cycling Aardvark target (off 5s)...")
        aa_target_power(handle, AA_TARGET_POWER_NONE)
        aa_sleep_ms(5000)
        aa_target_power(handle, AA_TARGET_POWER_BOTH)
        aa_sleep_ms(3000)

        wake_df_safe()
        aa_sleep_ms(2000)

        # RESET
        send_control(0x0041)
        aa_sleep_ms(5000)
        wake_df_safe()
        aa_sleep_ms(1000)

        v_internal = read_std(0x0A)
        print(f"  Voltage with internal divider: {v_internal} mV")

        if v_internal and v_internal > 0:
            print(f"  Internal divider reads {v_internal} mV — gauge is alive!")
            recovered = True

        # Restore VOLTSEL=1 (correct for Rev 4+ divider) + cells=1.
        print("\n  Restoring VOLTSEL=1, cells=1...")
        unseal_fa()
        blk64 = read_block(64)
        if blk64:
            mod64 = list(blk64)
            restore_pc = (blk64[0] << 8) | blk64[1]
            restore_pc |= 0x0008  # Set VOLTSEL=1
            mod64[0] = (restore_pc >> 8) & 0xFF
            mod64[1] = restore_pc & 0xFF
            mod64[7] = 1
            write_block(64, mod64)

        send_control(0x0041)
        aa_sleep_ms(5000)
        wake_df_safe()
        aa_sleep_ms(1000)

        recovered = show_status("After VOLTSEL toggle + power cycle")
        if recovered:
            print("\n  *** RECOVERED via VOLTSEL toggle + power cycle! ***")
            # Ensure correct VOLTSEL=1 for Rev 4+
            unseal_fa()
            blk64 = read_block(64)
            if blk64:
                mod64 = list(blk64)
                pc = (blk64[0] << 8) | blk64[1]
                pc |= 0x0008  # Set VOLTSEL=1
                mod64[0] = (pc >> 8) & 0xFF
                mod64[1] = pc & 0xFF
                write_block(64, mod64)
    else:
        print("  SC 64 read failed")


# ---------------------------------------------------------------------------
#  Final DF state dump
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("  Final Data Flash State")
print("=" * 60)
unseal_fa()

blk64 = read_block(64)
if blk64:
    pc = (blk64[0] << 8) | blk64[1]
    print(f"  Pack Config : 0x{pc:04X} (VOLTSEL={bool(pc&8)})")
    print(f"  Cells       : {blk64[7]}")

blk104 = read_block(104)
if blk104:
    cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0]
    cc_d = struct.unpack('>f', bytes(blk104[4:8]))[0]
    vd = (blk104[14] << 8) | blk104[15]
    print(f"  CC Gain     : {cc_g:.6g}")
    print(f"  CC Delta    : {cc_d:.6g}")
    print(f"  VD          : {vd}")

blk48 = read_block(48)
if blk48:
    de = (blk48[0] << 8) | blk48[1]
    dc = (blk48[11] << 8) | blk48[12]
    print(f"  Design Energy   : {de}")
    print(f"  Design Capacity : {dc}")

blk82 = read_block(82)
if blk82:
    qmax = (blk82[0] << 8) | blk82[1]
    print(f"  QMax            : {qmax}")

blk68 = read_block(68)
if blk68:
    fu_v = (blk68[0] << 8) | blk68[1]
    print(f"  Flash Update OK V: {fu_v} mV")


# ---------------------------------------------------------------------------
#  Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
if recovered:
    print("  RECOVERY SUCCESSFUL!")
    print()
    print("  Next steps:")
    print("  1. Use Ralim calibration to set VD:")
    print("     newVD = (INA226_voltage / BQ_voltage) * current_VD")
    print("  2. Verify voltage reads correctly with new VD")
    print("  3. THEN set cells=8 (only after VD is correct)")
    print("  4. Program Design Capacity, Design Energy, QMax")
else:
    print("  ALL RECOVERY STRATEGIES FAILED")
    print()
    print("  The gauge's analog subsystem appears permanently stuck.")
    print("  Remaining options:")
    print("  1. Disconnect ALL power (supply + USB) for 5+ minutes")
    print("     to fully drain internal caps, then run this script again")
    print("  2. Measure BAT pin (pin 4) voltage with multimeter")
    print("     to rule out a hardware issue")
    print("  3. Use bqStudio with EV2400 adapter for factory reset")
    print("  4. The IC may have an internal fuse/fault that only")
    print("     clears through a manufacturer-specific procedure")
print("=" * 60)

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\nDone.")
