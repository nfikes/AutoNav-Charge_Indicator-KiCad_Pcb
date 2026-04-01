"""BQ34Z100-R2 Fresh Chip Incremental Bringup.

Run in stages to isolate exactly what kills the gauge:

  python3 bq_fresh_chip.py probe     — Poll for ACK + read everything (NO writes)
  python3 bq_fresh_chip.py reset     — Bare RESET test (zero writes, just reset)
  python3 bq_fresh_chip.py rsns      — Write RSNS fix only -> RESET -> check
  python3 bq_fresh_chip.py cc        — Write CC calibration only -> RESET -> check
  python3 bq_fresh_chip.py vd        — Calibrate VD using Ralim method -> RESET -> check

CRITICAL: Run stages in order. Each stage checks voltage before and after.
If voltage dies at any stage, you know exactly which operation killed it.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *
from array import array
import struct
import time

BQ = 0x55
INA = 0x40
SENSE_R_MOHM = 5

USAGE = """Usage: python3 bq_fresh_chip.py <stage>

Stages (run in order):
  probe  — Poll for I2C ACK + read all registers (NO writes)
  reset  — Bare RESET test (no config changes, just RESET)
  rsns   — Write RSNS LOW fix only -> RESET -> check voltage
  cc     — Write CC calibration (5mOhm) -> RESET -> check voltage
  vd     — Calibrate VD via Ralim method -> RESET -> check voltage
"""

if len(sys.argv) < 2 or sys.argv[1] not in ("probe", "reset", "rsns", "cc", "vd"):
    print(USAGE)
    exit(1)

stage = sys.argv[1]

handle = aa_open(0)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(1000)


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


def read_control_sub(subcmd):
    send_control(subcmd)
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
    aa_sleep_ms(2000)
    return True


def full_status(label):
    """Read and display all standard registers, control status, and key DF values."""
    print(f"\n  --- {label} ---")

    # Standard registers
    v = read_std(0x0A)
    pv = read_std(0x28)
    t = read_std(0x0E)
    it = read_std(0x1E)
    c = read_std(0x14, signed=True)
    ac = read_std(0x0C, signed=True)
    flags = read_std(0x10)
    flagsb = read_std(0x12)
    soc = read_std(0x03, n=1)
    rc_cap = read_std(0x06)
    fcc = read_std(0x08)

    print(f"    Voltage()      : {v} mV")
    print(f"    PackVoltage()  : {pv} mV")
    if t is not None:
        print(f"    Temperature()  : {t} raw ({t*0.1-273.15:.1f} C)")
    if it is not None:
        print(f"    InternalTemp() : {it} raw ({it*0.1-273.15:.1f} C)")
    print(f"    Current()      : {c} mA")
    print(f"    AvgCurrent()   : {ac} mA")
    if flags is not None:
        print(f"    Flags          : 0x{flags:04X}")
    if flagsb is not None:
        print(f"    FlagsB         : 0x{flagsb:04X}")
    print(f"    SOC            : {soc}%")
    print(f"    RemainingCap   : {rc_cap} mAh")
    print(f"    FullChargeCap  : {fcc} mAh")

    # Control status
    unseal_fa()
    status = read_control_status()
    if status is not None:
        print(f"    CtrlStatus     : 0x{status:04X}")
        print(f"      VOK={bool(status&2)}, QEN={bool(status&1)}, "
              f"SLEEP={bool(status&(1<<4))}, "
              f"SS={bool(status&(1<<13))}, FAS={bool(status&(1<<14))}")

    fw = read_control_sub(0x0002)
    chem = read_control_sub(0x0008)
    if fw is not None:
        print(f"    FW Version     : 0x{fw:04X}")
    if chem is not None:
        print(f"    Chemistry ID   : 0x{chem:04X}")

    # INA226 reference
    ina_d = array('B', [0x02])
    aa_i2c_write(handle, INA, AA_I2C_NO_STOP, ina_d)
    (rc2, ina_data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
    if rc2 == 2:
        ina_mv = int(((ina_data[0] << 8) | ina_data[1]) * 1.25)
        print(f"    INA226 Bus V   : {ina_mv} mV")

    return v


def read_df_state():
    """Read and display key data flash parameters."""
    print("\n  --- Data Flash ---")

    blk64 = read_block(64)
    if blk64:
        pc = (blk64[0] << 8) | blk64[1]
        cells = blk64[7]
        voltsel = bool(pc & 0x0008)
        rsns = bool(pc & 0x0080)
        ext = "EXT" if voltsel else "INT"
        rstr = "HIGH" if rsns else "LOW"
        print(f"    Pack Config    : 0x{pc:04X}  VOLTSEL={int(voltsel)}/{ext}  RSNS={int(rsns)}/{rstr}")
        print(f"    Cell Count     : {cells}")
    else:
        print("    SC 64: READ FAILED")

    blk104 = read_block(104)
    if blk104:
        cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0]
        cc_d = struct.unpack('>f', bytes(blk104[4:8]))[0]
        vd = (blk104[14] << 8) | blk104[15]
        print(f"    CC Gain        : {cc_g:.6g}")
        print(f"    CC Delta       : {cc_d:.6g}")
        print(f"    VD             : {vd}")
    else:
        print("    SC 104: READ FAILED")

    blk68 = read_block(68)
    if blk68:
        fu_v = (blk68[0] << 8) | blk68[1]
        print(f"    Flash Update OK: {fu_v} mV")
    else:
        print("    SC 68: READ FAILED")

    blk82 = read_block(82)
    if blk82:
        qmax = (blk82[0] << 8) | blk82[1]
        print(f"    QMax Cell 0    : {qmax}")

    blk48 = read_block(48)
    if blk48:
        de = (blk48[0] << 8) | blk48[1]
        dc = (blk48[11] << 8) | blk48[12]
        print(f"    Design Energy  : {de} cWh")
        print(f"    Design Capacity: {dc} mAh")


def cleanup():
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)


# ===========================================================================
#  STAGE: probe — Poll for ACK + read everything (NO WRITES)
# ===========================================================================

if stage == "probe":
    print("=" * 60)
    print("  STAGE: PROBE — Read Only (no writes)")
    print("=" * 60)
    print()
    print("  Polling for BQ34Z100-R2 ACK at 0x55...")
    print("  (Fresh chips may take 15-20 minutes to respond)")
    print("  Press Ctrl+C to stop.")
    print()

    alive = False
    start = time.time()
    attempt = 0

    try:
        while True:
            attempt += 1
            elapsed = time.time() - start
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)

            # DF-safe wake attempt
            aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
            aa_sleep_ms(100)

            # Try reading Temperature register as ACK test
            d = array('B', [0x0E])
            aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
            (rc, _) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)

            if rc == 2:
                alive = True
                print(f"  ACK received! (attempt {attempt}, {mins}m {secs}s elapsed)")
                break

            if attempt % 10 == 0:
                print(f"  Still NACKing... attempt {attempt}, {mins}m {secs}s elapsed")

            aa_sleep_ms(2000)  # Poll every ~2 seconds
    except KeyboardInterrupt:
        elapsed = time.time() - start
        print(f"\n  Stopped after {attempt} attempts, {elapsed:.0f}s elapsed.")

    if not alive:
        print("\n  Chip did not ACK. Leave board powered and try again later.")
        cleanup()
        exit(1)

    # Chip is alive — read everything
    print()
    print("  Chip is responding! Reading all registers (NO WRITES)...")
    v = full_status("Fresh Chip — Virgin State")

    # Read DF (requires unseal, which writes to Control reg 0x00, but
    # does NOT write to data flash — this is read-only)
    read_df_state()

    print()
    print("=" * 60)
    if v is not None and v > 0:
        print(f"  ADC IS WORKING! Voltage = {v} mV")
        print()
        print("  Next: run 'python3 bq_fresh_chip.py reset'")
        print("  to test if a bare RESET preserves the voltage reading.")
    else:
        print(f"  Voltage = {v} mV (may be normal for very low BAT input)")
        print("  The ADC reported 33mV on the last fresh chip at 0.94V BAT.")
        print()
        print("  If voltage > 0, proceed to: python3 bq_fresh_chip.py reset")
        print("  If voltage = 0, the chip may need more warmup time.")
    print("=" * 60)

    cleanup()


# ===========================================================================
#  STAGE: reset — Bare RESET test (no config changes)
# ===========================================================================

elif stage == "reset":
    print("=" * 60)
    print("  STAGE: RESET — Bare Reset Test (no config writes)")
    print("=" * 60)
    print()

    wake_df_safe()

    # Pre-reset voltage
    v_before = full_status("Before RESET (should show voltage)")

    if v_before is None or v_before == 0:
        print()
        print("  WARNING: Voltage is already 0 before RESET.")
        print("  Run 'probe' stage first to confirm ADC is working.")
        print("  Proceeding anyway...")

    print()
    print("  Sending RESET (0x0041) — no config changes were made...")
    unseal_fa()
    send_control(0x0041)
    print("  Waiting 10 seconds for reboot...")
    aa_sleep_ms(10000)

    # Wake and re-read
    wake_df_safe()
    aa_sleep_ms(2000)

    v_after = full_status("After Bare RESET")

    print()
    print("=" * 60)
    if v_after is not None and v_after > 0:
        print(f"  BARE RESET SURVIVED! Voltage: {v_before} -> {v_after} mV")
        print()
        print("  The gauge survives resets at this BAT voltage.")
        print("  The divider is safe for production use.")
        print()
        print("  Next: run 'python3 bq_fresh_chip.py rsns'")
        print("  to test the RSNS configuration change.")
    else:
        print(f"  BARE RESET KILLED VOLTAGE! {v_before} -> {v_after} mV")
        print()
        print("  The IT algorithm cannot reinitialize at this BAT voltage")
        print("  even with factory defaults. The 6.49k divider is too low")
        print("  for this chip to survive power cycles.")
        print()
        print("  R22 must be increased (10-13kOhm range) for reliable operation.")
    print("=" * 60)

    cleanup()


# ===========================================================================
#  STAGE: rsns — Write RSNS fix only
# ===========================================================================

elif stage == "rsns":
    print("=" * 60)
    print("  STAGE: RSNS — Write RSNS LOW Fix Only")
    print("=" * 60)
    print()

    wake_df_safe()

    # Pre-change voltage
    v_before = full_status("Before RSNS Change")

    if v_before is None or v_before == 0:
        print()
        print("  WARNING: Voltage is 0. The gauge may already be locked up.")
        print("  Run 'probe' and 'reset' stages first.")
        response = input("  Continue anyway? (y/n): ").strip().lower()
        if response != 'y':
            cleanup()
            exit(0)

    # Read current Pack Config
    blk64 = read_block(64)
    if not blk64:
        print("  SC 64 read failed!")
        cleanup()
        exit(1)

    pc = (blk64[0] << 8) | blk64[1]
    print(f"\n  Current Pack Config: 0x{pc:04X}")

    # Change RSNS bit (bit 7) from HIGH to LOW: clear bit 7
    # 0x41D9 -> 0x4159
    new_pc = pc & ~0x0080  # Clear RSNS bit
    if new_pc == pc:
        print("  RSNS is already LOW — no change needed.")
    else:
        print(f"  Changing Pack Config: 0x{pc:04X} -> 0x{new_pc:04X}")
        print(f"    RSNS: HIGH -> LOW")
        mod64 = list(blk64)
        mod64[0] = (new_pc >> 8) & 0xFF
        mod64[1] = new_pc & 0xFF
        if write_block(64, mod64):
            print("  Written OK — verifying...")
            verify = read_block(64)
            if verify:
                vpc = (verify[0] << 8) | verify[1]
                status = "PASS" if vpc == new_pc else "FAIL"
                print(f"  Verified: 0x{vpc:04X} {status}")
            else:
                print("  Verify read failed")
        else:
            print("  Write FAILED!")
            cleanup()
            exit(1)

    # RESET
    print("\n  Sending RESET (0x0041)...")
    unseal_fa()
    send_control(0x0041)
    print("  Waiting 10 seconds...")
    aa_sleep_ms(10000)

    wake_df_safe()
    aa_sleep_ms(2000)

    v_after = full_status("After RSNS Fix + RESET")

    print()
    print("=" * 60)
    if v_after is not None and v_after > 0:
        print(f"  RSNS CHANGE SURVIVED! Voltage: {v_before} -> {v_after} mV")
        print()
        print("  Next: run 'python3 bq_fresh_chip.py cc'")
    else:
        print(f"  RSNS CHANGE KILLED VOLTAGE! {v_before} -> {v_after} mV")
        print()
        print("  The RSNS configuration change causes the lockup.")
        print("  Consider leaving RSNS=HIGH (factory default) if possible,")
        print("  or increase R22 before changing RSNS.")
    print("=" * 60)

    cleanup()


# ===========================================================================
#  STAGE: cc — Write CC calibration only
# ===========================================================================

elif stage == "cc":
    print("=" * 60)
    print(f"  STAGE: CC — Calibrate for {SENSE_R_MOHM}mOhm Sense Resistor")
    print("=" * 60)
    print()

    wake_df_safe()

    v_before = full_status("Before CC Calibration")

    if v_before is None or v_before == 0:
        print()
        print("  WARNING: Voltage is 0. Previous stage may have failed.")
        response = input("  Continue anyway? (y/n): ").strip().lower()
        if response != 'y':
            cleanup()
            exit(0)

    # Calculate target values
    exp_gain = 4.768 / SENSE_R_MOHM       # 0.9536
    exp_delta = 5677445.3 / SENSE_R_MOHM   # 1,135,489.06

    # Read current SC 104
    blk104 = read_block(104)
    if not blk104:
        print("  SC 104 read failed!")
        cleanup()
        exit(1)

    cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0]
    cc_d = struct.unpack('>f', bytes(blk104[4:8]))[0]
    print(f"\n  Current CC Gain : {cc_g:.6g}")
    print(f"  Current CC Delta: {cc_d:.6g}")
    print(f"  Target CC Gain  : {exp_gain:.6g}")
    print(f"  Target CC Delta : {exp_delta:.6g}")

    mod104 = list(blk104)
    mod104[0:4] = list(struct.pack('>f', exp_gain))
    mod104[4:8] = list(struct.pack('>f', exp_delta))

    print(f"\n  Writing CC calibration...")
    if write_block(104, mod104):
        print("  Written OK — verifying...")
        verify = read_block(104)
        if verify:
            vg = struct.unpack('>f', bytes(verify[0:4]))[0]
            vd_val = struct.unpack('>f', bytes(verify[4:8]))[0]
            g_ok = abs(vg - exp_gain) < 0.001
            d_ok = abs(vd_val - exp_delta) < 100
            print(f"  CC Gain:  {vg:.6g}  {'PASS' if g_ok else 'FAIL'}")
            print(f"  CC Delta: {vd_val:.6g}  {'PASS' if d_ok else 'FAIL'}")
    else:
        print("  Write FAILED!")
        cleanup()
        exit(1)

    # RESET
    print("\n  Sending RESET (0x0041)...")
    unseal_fa()
    send_control(0x0041)
    print("  Waiting 10 seconds...")
    aa_sleep_ms(10000)

    wake_df_safe()
    aa_sleep_ms(2000)

    v_after = full_status("After CC Calibration + RESET")

    print()
    print("=" * 60)
    if v_after is not None and v_after > 0:
        print(f"  CC CALIBRATION SURVIVED! Voltage: {v_before} -> {v_after} mV")
        print()
        print("  Next: run 'python3 bq_fresh_chip.py vd'")
    else:
        print(f"  CC CALIBRATION KILLED VOLTAGE! {v_before} -> {v_after} mV")
        print()
        print("  The CC calibration change causes the lockup.")
        print("  The 5mOhm CC values may interact badly at this BAT voltage.")
    print("=" * 60)

    cleanup()


# ===========================================================================
#  STAGE: vd — Calibrate voltage divider using Ralim method
# ===========================================================================

elif stage == "vd":
    print("=" * 60)
    print("  STAGE: VD — Voltage Divider Calibration (Ralim Method)")
    print("=" * 60)
    print()

    wake_df_safe()

    v_before = full_status("Before VD Calibration")

    if v_before is None or v_before == 0:
        print()
        print("  WARNING: Voltage is 0. Cannot calibrate VD without a reading.")
        print("  The gauge must be measuring voltage first.")
        cleanup()
        exit(1)

    # Read INA226 as reference voltage
    ina_d = array('B', [0x02])
    aa_i2c_write(handle, INA, AA_I2C_NO_STOP, ina_d)
    (rc, ina_data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
    if rc != 2:
        print("  INA226 read failed!")
        cleanup()
        exit(1)
    ina_mv = int(((ina_data[0] << 8) | ina_data[1]) * 1.25)

    # Read current VD
    blk104 = read_block(104)
    if not blk104:
        print("  SC 104 read failed!")
        cleanup()
        exit(1)

    current_vd = (blk104[14] << 8) | blk104[15]

    # BQ reports voltage in mV — use PackVoltage (0x28) which includes VD scaling
    pv = read_std(0x28)
    # Also read raw Voltage() for comparison
    raw_v = read_std(0x0A)

    print(f"\n  INA226 actual voltage : {ina_mv} mV")
    print(f"  BQ Voltage()         : {raw_v} mV")
    print(f"  BQ PackVoltage()     : {pv} mV")
    print(f"  Current VD           : {current_vd}")

    if raw_v is None or raw_v == 0:
        print("\n  BQ Voltage() is 0 — cannot calibrate.")
        cleanup()
        exit(1)

    # Ralim calibration: newVD = (actual / reported) * currentVD
    # Use raw Voltage() since that's what VD scales
    new_vd = int((ina_mv / raw_v) * current_vd)
    print(f"\n  Ralim calculation:")
    print(f"    newVD = ({ina_mv} / {raw_v}) * {current_vd} = {new_vd}")

    if new_vd < 1 or new_vd > 65535:
        print(f"\n  VD value {new_vd} is out of range (1-65535)!")
        cleanup()
        exit(1)

    # Write new VD
    mod104 = list(blk104)
    mod104[14] = (new_vd >> 8) & 0xFF
    mod104[15] = new_vd & 0xFF
    print(f"\n  Writing VD = {new_vd}...")
    if write_block(104, mod104):
        print("  Written OK — verifying...")
        verify = read_block(104)
        if verify:
            v_vd = (verify[14] << 8) | verify[15]
            print(f"  VD verified: {v_vd} {'PASS' if v_vd == new_vd else 'FAIL'}")
    else:
        print("  Write FAILED!")
        cleanup()
        exit(1)

    # RESET
    print("\n  Sending RESET (0x0041)...")
    unseal_fa()
    send_control(0x0041)
    print("  Waiting 10 seconds...")
    aa_sleep_ms(10000)

    wake_df_safe()
    aa_sleep_ms(2000)

    v_after = full_status("After VD Calibration + RESET")

    # Check new PackVoltage
    pv_after = read_std(0x28)
    print(f"\n  PackVoltage after VD cal: {pv_after} mV  (INA226: {ina_mv} mV)")
    if pv_after is not None and ina_mv > 0:
        error_pct = abs(pv_after - ina_mv) / ina_mv * 100
        print(f"  Error: {error_pct:.1f}%")

    print()
    print("=" * 60)
    if v_after is not None and v_after > 0:
        print(f"  VD CALIBRATION SURVIVED! Voltage: {v_before} -> {v_after} mV")
        print()
        print("  All stages complete! The gauge is configured and measuring.")
        print("  Summary of applied config:")
        read_df_state()
        print()
        print("  Consider a final power-cycle test:")
        print("  1. Turn off power supply + disconnect Aardvark")
        print("  2. Wait 30 seconds")
        print("  3. Reconnect and run: python3 bq_fresh_chip.py probe")
        print("  4. If voltage reads > 0, the board is production-ready")
    else:
        print(f"  VD CALIBRATION KILLED VOLTAGE! {v_before} -> {v_after} mV")
        print()
        print("  The VD change causes the lockup.")
    print("=" * 60)

    cleanup()
