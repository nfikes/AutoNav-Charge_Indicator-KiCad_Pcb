"""BQ34Z100-R2 LiFePO4 Chemistry Profile Programming
=====================================================
Programs a complete LiFePO4 chemistry profile for the Renogy RBT2425LFP
(24V, 25Ah, 8S LiFePO4) including:

  - Chemistry ID verification/update (SC 59)
  - R_a resistance tables for Impedance Track (SC 53-56)
  - Design parameters (SC 48, 64, 82, 104)
  - Voltage recovery & calibration using INA226 as ground truth

The BQ34Z100-R2 needs a valid chemistry profile to compute voltage from
its ADC readings.  Without one, Voltage() returns 0 mV even though the
BAT pin physically has voltage.

LiFePO4 Cell Characteristics (per cell):
  - Nominal:  3.2 V
  - Full:     3.65 V
  - Empty:    2.5 V
  - Flat discharge curve 3.2-3.3 V across 20-80% SOC
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *
from array import array
import struct

BQ  = 0x55
INA = 0x40

# === Target Battery: Renogy RBT2425LFP ===
NUM_CELLS        = 8
DESIGN_CAPACITY  = 25000   # mAh
DESIGN_ENERGY    = 64000   # mWh (with EnergyScale=10 -> 640 Wh)
QMAX             = 25000   # mAh

# Voltage divider: R27=200k (top), R22=34.8k (bottom)
# Full ratio = (200+34.8)/34.8 = 6.7471
# BQ34Z100-R2 VD = ratio * 1000 / NumCells = 6747 / 8 = 843
# BUT: the /NumCells is ONLY correct when the gauge multiplies
# Voltage() by cells internally.  We'll calibrate empirically.
VD_INITIAL       = 5000    # Start with this (known to give readings)

# LiFePO4 R_a resistance tables (milliohms per cell at 15 SOC grid points)
# Grid: ~[100, 93, 86, 79, 72, 65, 58, 51, 44, 37, 30, 23, 16, 9, 2] %
# Values for 25Ah prismatic LiFePO4 cells (typical EVE/CATL type)
RA0_25C = [6, 6, 6, 6, 6, 6, 6, 7, 8, 10, 12, 16, 22, 35, 55]   # 25 deg C
RA1_N5C = [15, 15, 15, 15, 15, 15, 15, 18, 20, 25, 30, 40, 55, 85, 140]  # -5 deg C


# ===========================================================================
#  I2C / Aardvark Helpers
# ===========================================================================

def open_aardvark():
    handle = aa_open(0)
    if handle <= 0:
        print(f"ERROR: Cannot open Aardvark (error {handle})")
        sys.exit(1)
    aa_configure(handle, AA_CONFIG_SPI_I2C)
    aa_i2c_bitrate(handle, 100)
    aa_target_power(handle, AA_TARGET_POWER_BOTH)
    aa_sleep_ms(500)
    print("Aardvark opened, target power on.")
    return handle


def wake(handle):
    for i in range(8):
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
        aa_sleep_ms(100)
    # Verify with a read
    d = array('B', [0x0A])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, _) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    return rc == 2


def unseal_fa(handle):
    for subcmd in [0x0414, 0x3672, 0xFFFF, 0xFFFF]:
        d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(5)
    aa_sleep_ms(100)


def send_control(handle, subcmd):
    d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    aa_sleep_ms(10)


def read_control_sub(handle, subcmd):
    send_control(handle, subcmd)
    aa_sleep_ms(10)
    d = array('B', [0x00])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        return data[0] | (data[1] << 8)
    return None


def read_std(handle, cmd, n=2, signed=False):
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


def read_block(handle, subclass, block=0):
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
        if ck[0] != expected:
            if all(b == 0 for b in blk[:16]):
                print(f"    STALE DATA (SC {subclass})")
                return None
    return blk


def write_block(handle, subclass, modified, block=0):
    for reg, val in [(0x61, 0x00), (0x3E, subclass), (0x3F, block)]:
        d = array('B', [reg, val])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(10)
    aa_sleep_ms(100)
    # Write all 32 bytes individually (proven reliable)
    for i in range(32):
        d = array('B', [0x40 + i, modified[i]])
        c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        if c != 2:
            print(f"    WRITE FAIL at byte {i}: {c}")
            return False
        aa_sleep_ms(3)
    # Commit with checksum
    cksum = (255 - (sum(modified) & 0xFF)) & 0xFF
    aa_sleep_ms(20)
    d = array('B', [0x60, cksum])
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    if c != 2:
        print(f"    CHECKSUM NACK")
        return False
    print(f"    Committed (cksum 0x{cksum:02X}), waiting 2s for flash...")
    aa_sleep_ms(2000)
    return True


def write_and_verify(handle, subclass, modifications, block=0):
    """Read block, apply modifications, write, verify via reset-then-read.

    modifications: list of (offset, [bytes]) tuples.
    Returns True on success.
    """
    unseal_fa(handle)
    blk = read_block(handle, subclass, block)
    if blk is None:
        print(f"    Read SC {subclass} failed")
        return False

    modified = list(blk)
    for offset, new_bytes in modifications:
        for i, b in enumerate(new_bytes):
            modified[offset + i] = b

    if not write_block(handle, subclass, modified, block):
        return False

    # --- Verify via full reset (avoids stale-read after auto-seal) ---
    # The flash commit auto-seals the device.  Simply re-unsealing and
    # reading can return stale data because the Control-reg writes in
    # unseal_fa() disrupt the DF block-access context.  A full reset
    # clears all caches and gives us a clean read path.
    reset_and_wake(handle, 4)
    unseal_fa(handle)
    aa_sleep_ms(300)

    verify = read_block(handle, subclass, block)
    if verify is None:
        # Retry once: re-unseal with extra delay
        print(f"    Verify returned None — retrying with extra delay...")
        aa_sleep_ms(500)
        unseal_fa(handle)
        aa_sleep_ms(500)
        verify = read_block(handle, subclass, block)

    if verify is None:
        print(f"    Verify read failed after retry")
        return False

    # Dump raw verify block for diagnostics
    print(f"    Verify SC {subclass}: {hex_dump(verify)}")

    ok = True
    for offset, new_bytes in modifications:
        for i, b in enumerate(new_bytes):
            if verify[offset + i] != b:
                print(f"    VERIFY FAIL at SC {subclass} offset {offset+i}: "
                      f"wrote 0x{b:02X}, read 0x{verify[offset+i]:02X}")
                ok = False
    return ok


def u16_be(val):
    return [(val >> 8) & 0xFF, val & 0xFF]


def hex_dump(data, n=32):
    return ' '.join(f'{b:02X}' for b in data[:n])


def write_sc64_safe(handle, extra_mods):
    """Write SC 64 with VOLTSEL=0 unconditionally enforced.

    extra_mods: list of (offset, [bytes]) for fields OTHER than Pack Config.
    Pack Config (offsets 0-1) is always read, bit 3 cleared, and written back.
    Returns True on success.
    """
    unseal_fa(handle)
    blk = read_block(handle, 64)
    if blk is None:
        print("    SC 64 read failed")
        return False
    pc = (blk[0] << 8) | blk[1]
    pc_safe = pc & ~0x0008  # Clear VOLTSEL (bit 3) — ALWAYS
    mods = [(0, [(pc_safe >> 8) & 0xFF, pc_safe & 0xFF])] + list(extra_mods)

    modified = list(blk)
    for offset, new_bytes in mods:
        for i, b in enumerate(new_bytes):
            modified[offset + i] = b

    if not write_block(handle, 64, modified):
        return False

    # Verify via full reset (same rationale as write_and_verify)
    reset_and_wake(handle, 4)
    unseal_fa(handle)
    aa_sleep_ms(300)

    verify = read_block(handle, 64)
    if verify is None:
        print("    Verify read failed — retrying...")
        aa_sleep_ms(500)
        unseal_fa(handle)
        aa_sleep_ms(500)
        verify = read_block(handle, 64)

    if verify is None:
        print("    Verify read failed after retry")
        return False

    print(f"    Verify SC 64: {hex_dump(verify)}")

    for offset, new_bytes in mods:
        for i, b in enumerate(new_bytes):
            if verify[offset + i] != b:
                print(f"    VERIFY FAIL offset {offset+i}: "
                      f"wrote 0x{b:02X}, read 0x{verify[offset+i]:02X}")
                return False
    # Final paranoid VOLTSEL check
    pc_v = (verify[0] << 8) | verify[1]
    if pc_v & 0x0008:
        print("    CRITICAL: VOLTSEL=1 after verified write — aborting!")
        return False
    return True


def reset_and_wake(handle, wait_s=5):
    send_control(handle, 0x0041)
    print(f"    RESET sent, waiting {wait_s}s...")
    aa_sleep_ms(wait_s * 1000)
    wake(handle)
    aa_sleep_ms(500)


def read_ina_voltage(handle):
    d = array('B', [0x02])
    aa_i2c_write(handle, INA, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, INA, AA_I2C_NO_FLAGS, 2)
    if rc == 2:
        return int(((data[0] << 8) | data[1]) * 1.25)
    return None


# ===========================================================================
#  PHASE 1: Diagnostic Dump
# ===========================================================================

def phase1_diagnostics(handle):
    sep = "=" * 60
    print()
    print(sep)
    print("  PHASE 1: Diagnostic Dump")
    print(sep)
    print()

    # Control sub-commands
    unseal_fa(handle)

    dev_type = read_control_sub(handle, 0x0001)
    fw_ver   = read_control_sub(handle, 0x0002)
    hw_ver   = read_control_sub(handle, 0x0003)
    chem_id  = read_control_sub(handle, 0x0008)
    status   = read_control_sub(handle, 0x0000)

    print(f"  Device Type   : 0x{dev_type:04X}" if dev_type else "  Device Type   : FAIL")
    print(f"  FW Version    : 0x{fw_ver:04X}" if fw_ver else "  FW Version    : FAIL")
    print(f"  HW Version    : 0x{hw_ver:04X}" if hw_ver else "  HW Version    : FAIL")
    print(f"  Chem ID       : 0x{chem_id:04X}" if chem_id is not None else "  Chem ID       : FAIL")
    if status is not None:
        print(f"  Control Status: 0x{status:04X}")
        print(f"    VOK={bool(status&2)}, SLEEP={bool(status&(1<<4))}, "
              f"SS={bool(status&(1<<13))}, FAS={bool(status&(1<<14))}")

    # Standard measurements
    print()
    v     = read_std(handle, 0x0A)
    soc   = read_std(handle, 0x03, n=1)
    cur   = read_std(handle, 0x14, signed=True)
    temp  = read_std(handle, 0x0E)
    itemp = read_std(handle, 0x1E)
    flags = read_std(handle, 0x10)
    rcap  = read_std(handle, 0x06)
    fcc   = read_std(handle, 0x08)
    dcap  = read_std(handle, 0x3C)
    pv    = read_std(handle, 0x28)

    print(f"  Voltage()     : {v} mV")
    print(f"  PackVoltage() : {pv} mV")
    print(f"  SOC           : {soc}%")
    print(f"  Current()     : {cur} mA")
    if temp is not None:
        print(f"  Temperature() : {temp*0.1-273.15:.1f} C ({temp} raw)")
    if itemp is not None:
        print(f"  InternalTemp(): {itemp*0.1-273.15:.1f} C ({itemp} raw)")
    print(f"  Flags         : 0x{flags:04X}" if flags is not None else "  Flags: FAIL")
    print(f"  RemainingCap  : {rcap} mAh")
    print(f"  FullChargeCap : {fcc} mAh")
    print(f"  DesignCap     : {dcap} mAh")

    ina_v = read_ina_voltage(handle)
    print(f"  INA226 Bus V  : {ina_v} mV")

    # Key DF subclasses
    print()
    print("  --- Key Data Flash ---")
    unseal_fa(handle)

    # SC 59: Codes (Chemistry ID in DF)
    blk59 = read_block(handle, 59)
    if blk59:
        chem_code = (blk59[0] << 8) | blk59[1]
        print(f"  SC 59 (Codes)      : Chem Code = 0x{chem_code:04X} ({chem_code})")
        print(f"    Raw: {hex_dump(blk59, 16)}")
    else:
        print(f"  SC 59 (Codes)      : READ FAILED")

    # SC 53: R_a0 (resistance at temp 0)
    unseal_fa(handle)
    blk53 = read_block(handle, 53)
    if blk53:
        print(f"  SC 53 (R_a0)       : {hex_dump(blk53)}")
        # Decode as 16 x uint16_be values
        ra_vals = []
        for i in range(0, 30, 2):
            ra_vals.append((blk53[i] << 8) | blk53[i+1])
        print(f"    R_a0 values (mOhm): {ra_vals}")
    else:
        print(f"  SC 53 (R_a0)       : READ FAILED")

    # SC 55: R_a1 (resistance at temp 1)
    unseal_fa(handle)
    blk55 = read_block(handle, 55)
    if blk55:
        print(f"  SC 55 (R_a1)       : {hex_dump(blk55)}")
        ra1_vals = []
        for i in range(0, 30, 2):
            ra1_vals.append((blk55[i] << 8) | blk55[i+1])
        print(f"    R_a1 values (mOhm): {ra1_vals}")
    else:
        print(f"  SC 55 (R_a1)       : READ FAILED")

    # SC 54, 56: Extended R_a tables
    for sc, name in [(54, "R_a0x"), (56, "R_a1x")]:
        unseal_fa(handle)
        blk = read_block(handle, sc)
        if blk:
            print(f"  SC {sc} ({name:5s})      : {hex_dump(blk)}")
        else:
            print(f"  SC {sc} ({name:5s})      : READ FAILED")

    # SC 48: Design params
    unseal_fa(handle)
    blk48 = read_block(handle, 48)
    if blk48:
        de = (blk48[0] << 8) | blk48[1]
        dc = (blk48[11] << 8) | blk48[12]
        print(f"  SC 48 DesignEnergy : {de}, DesignCap: {dc} mAh")

    # SC 64: Pack Config
    unseal_fa(handle)
    blk64 = read_block(handle, 64)
    if blk64:
        pc = (blk64[0] << 8) | blk64[1]
        cells = blk64[7]
        print(f"  SC 64 PackConfig   : 0x{pc:04X}, Cells: {cells}")
        print(f"    VOLTSEL={bool(pc&8)}, RSNS={bool(pc&0x80)}")

    # SC 82: QMax
    unseal_fa(handle)
    blk82 = read_block(handle, 82)
    if blk82:
        qmax = (blk82[0] << 8) | blk82[1]
        print(f"  SC 82 QMax         : {qmax} mAh")

    # SC 104: CC Cal + VD
    unseal_fa(handle)
    blk104 = read_block(handle, 104)
    if blk104:
        cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0]
        cc_d = struct.unpack('>f', bytes(blk104[4:8]))[0]
        vd   = (blk104[14] << 8) | blk104[15]
        print(f"  SC104 CC Gain      : {cc_g:.6g}")
        print(f"  SC104 CC Delta     : {cc_d:.6g}")
        print(f"  SC104 VoltDivider  : {vd}")

    # SC 68: Flash Update OK Voltage
    unseal_fa(handle)
    blk68 = read_block(handle, 68)
    if blk68:
        fuv = (blk68[0] << 8) | blk68[1]
        print(f"  SC 68 FlashUpdateV : {fuv} mV")

    print()
    return {
        'chem_id': chem_id,
        'voltage': v,
        'ina_voltage': ina_v,
        'cells': blk64[7] if blk64 else None,
        'vd': (blk104[14] << 8) | blk104[15] if blk104 else None,
    }


# ===========================================================================
#  PHASE 2: Program LiFePO4 Chemistry (R_a tables)
# ===========================================================================

def phase2_chemistry(handle):
    sep = "=" * 60
    print(sep)
    print("  PHASE 2: Program LiFePO4 Chemistry")
    print(sep)
    print()

    results = {}

    # --- SC 53: R_a0 (resistance at 25 deg C) ---
    print("  --- SC 53: R_a0 (25 C resistance profile) ---")
    ra0_bytes = []
    for val in RA0_25C:
        ra0_bytes.extend(u16_be(val))
    # Pad to 30 bytes (15 values x 2 bytes), leave bytes 30-31 unchanged
    print(f"    Target values (mOhm): {RA0_25C}")

    unseal_fa(handle)
    blk53 = read_block(handle, 53)
    if blk53:
        # Check current values
        current_vals = [(blk53[i] << 8) | blk53[i+1] for i in range(0, 30, 2)]
        print(f"    Current values      : {current_vals}")

        if current_vals == RA0_25C:
            print(f"    Already correct.")
            results['SC53'] = True
        else:
            mods = [(i * 2, u16_be(RA0_25C[i])) for i in range(15)]
            ok = write_and_verify(handle, 53, mods)
            results['SC53'] = ok
            print(f"    {'PASS' if ok else 'FAIL'}")
    else:
        print(f"    READ FAILED")
        results['SC53'] = False
    print()

    # --- SC 55: R_a1 (resistance at -5 deg C) ---
    print("  --- SC 55: R_a1 (-5 C resistance profile) ---")
    print(f"    Target values (mOhm): {RA1_N5C}")

    unseal_fa(handle)
    blk55 = read_block(handle, 55)
    if blk55:
        current_vals = [(blk55[i] << 8) | blk55[i+1] for i in range(0, 30, 2)]
        print(f"    Current values      : {current_vals}")

        if current_vals == RA1_N5C:
            print(f"    Already correct.")
            results['SC55'] = True
        else:
            mods = [(i * 2, u16_be(RA1_N5C[i])) for i in range(15)]
            ok = write_and_verify(handle, 55, mods)
            results['SC55'] = ok
            print(f"    {'PASS' if ok else 'FAIL'}")
    else:
        print(f"    READ FAILED")
        results['SC55'] = False
    print()

    return results


# ===========================================================================
#  PHASE 3: Voltage Recovery
# ===========================================================================

def phase3_voltage_recovery(handle):
    """Attempt to recover voltage reading.

    Strategy:
    1. Set cells=1 + VD=5000 (known to produce readings)
    2. RESET and check voltage
    3. If voltage reads, calibrate VD using INA226
    4. If not, try CAL mode entry/exit, SHUTDOWN, etc.
    """
    sep = "=" * 60
    print(sep)
    print("  PHASE 3: Voltage Recovery")
    print(sep)
    print()

    # Check current voltage first
    v = read_std(handle, 0x0A)
    ina_v = read_ina_voltage(handle)
    print(f"  Current Voltage() : {v} mV")
    print(f"  INA226 reference  : {ina_v} mV")

    if v is not None and v > 0:
        print(f"  Voltage is already reading! Skipping recovery.")
        return v, ina_v

    # ----- STEP 1: cells=1, VD=5000 -----
    print()
    print("  STEP 1: Set cells=1, VD=5000 (safe defaults)...")

    # Write cells=1 (VOLTSEL=0 enforced)
    unseal_fa(handle)
    blk64 = read_block(handle, 64)
    if blk64 and blk64[7] != 1:
        print(f"    Setting cells: {blk64[7]} -> 1 (VOLTSEL=0 enforced)")
        write_sc64_safe(handle, [(7, [1])])
    elif blk64:
        print(f"    Cells already 1")

    # Write VD=5000
    unseal_fa(handle)
    blk104 = read_block(handle, 104)
    if blk104:
        old_vd = (blk104[14] << 8) | blk104[15]
        if old_vd != VD_INITIAL:
            mod104 = list(blk104)
            mod104[14] = (VD_INITIAL >> 8) & 0xFF
            mod104[15] = VD_INITIAL & 0xFF
            print(f"    Setting VD: {old_vd} -> {VD_INITIAL}")
            write_block(handle, 104, mod104)
        else:
            print(f"    VD already {VD_INITIAL}")

    reset_and_wake(handle, 8)

    v = read_std(handle, 0x0A)
    ina_v = read_ina_voltage(handle)
    print(f"    Voltage() = {v} mV, INA226 = {ina_v} mV")

    if v and v > 0:
        print(f"    Voltage recovered!")
        return v, ina_v

    # ----- STEP 2: Lower Flash Update OK Voltage to 0 -----
    print()
    print("  STEP 2: Lower Flash Update OK Voltage to 0...")
    unseal_fa(handle)
    blk68 = read_block(handle, 68)
    old_fuv = 0
    if blk68:
        old_fuv = (blk68[0] << 8) | blk68[1]
        if old_fuv != 0:
            mod68 = list(blk68)
            mod68[0] = 0
            mod68[1] = 0
            print(f"    FlashUpdateOK: {old_fuv} -> 0 mV")
            write_block(handle, 68, mod68)

    reset_and_wake(handle, 5)
    v = read_std(handle, 0x0A)
    ina_v = read_ina_voltage(handle)
    print(f"    Voltage() = {v} mV, INA226 = {ina_v} mV")

    if v and v > 0:
        print(f"    Voltage recovered (FlashUpdateOK was blocking)!")
        return v, ina_v

    # ----- STEP 3: CAL mode entry/exit -----
    print()
    print("  STEP 3: Calibration mode entry/exit (reconfigures analog)...")
    unseal_fa(handle)
    send_control(handle, 0x002D)  # CAL_ENABLE
    aa_sleep_ms(1000)
    send_control(handle, 0x0081)  # ENTER_CAL
    aa_sleep_ms(3000)

    # Read voltage in cal mode
    v_cal = read_std(handle, 0x0A)
    print(f"    Voltage in CAL mode: {v_cal} mV")

    send_control(handle, 0x0080)  # EXIT_CAL
    aa_sleep_ms(3000)

    reset_and_wake(handle, 5)
    v = read_std(handle, 0x0A)
    ina_v = read_ina_voltage(handle)
    print(f"    Voltage() = {v} mV, INA226 = {ina_v} mV")

    if v and v > 0:
        print(f"    Voltage recovered via CAL mode!")
        return v, ina_v

    # ----- STEP 4: SHUTDOWN + power toggle -----
    print()
    print("  STEP 4: SHUTDOWN + power cycle...")
    unseal_fa(handle)
    send_control(handle, 0x0010)  # SHUTDOWN
    aa_sleep_ms(3000)

    aa_target_power(handle, AA_TARGET_POWER_NONE)
    print("    Target power off for 5s...")
    aa_sleep_ms(5000)
    aa_target_power(handle, AA_TARGET_POWER_BOTH)
    aa_sleep_ms(2000)

    wake(handle)
    aa_sleep_ms(1000)

    v = read_std(handle, 0x0A)
    ina_v = read_ina_voltage(handle)
    print(f"    Voltage() = {v} mV, INA226 = {ina_v} mV")

    if v and v > 0:
        print(f"    Voltage recovered via SHUTDOWN!")
        return v, ina_v

    # ----- STEP 5: BAT_INSERT + OCV + IT_ENABLE -----
    print()
    print("  STEP 5: BAT_REMOVE -> BAT_INSERT -> OCV_CMD -> IT_ENABLE...")
    unseal_fa(handle)
    send_control(handle, 0x000D)  # BAT_REMOVE
    aa_sleep_ms(2000)
    send_control(handle, 0x000C)  # BAT_INSERT
    aa_sleep_ms(2000)
    unseal_fa(handle)
    send_control(handle, 0x000B)  # OCV_CMD
    aa_sleep_ms(3000)
    unseal_fa(handle)
    send_control(handle, 0x0021)  # IT_ENABLE
    aa_sleep_ms(3000)

    reset_and_wake(handle, 5)
    v = read_std(handle, 0x0A)
    ina_v = read_ina_voltage(handle)
    print(f"    Voltage() = {v} mV, INA226 = {ina_v} mV")

    if v and v > 0:
        print(f"    Voltage recovered via BAT_INSERT!")
        return v, ina_v

    # ----- STEP 6: Verify VOLTSEL=0 (SAFETY) -----
    # VOLTSEL must NEVER be set to 1 on this board — it bypasses the
    # internal 5:1 divider and exposes the ADC to >1 V, destroying
    # analog front-end measurements.
    print()
    print("  STEP 6: Verify VOLTSEL=0 and reset...")
    # Use safe helper — always enforces VOLTSEL=0 regardless of current state
    ok = write_sc64_safe(handle, [])
    if ok:
        unseal_fa(handle)
        blk64_check = read_block(handle, 64)
        if blk64_check:
            pc = (blk64_check[0] << 8) | blk64_check[1]
            print(f"    VOLTSEL=0 enforced (PackConfig=0x{pc:04X})")

        reset_and_wake(handle, 5)
        v_int = read_std(handle, 0x0A)
        ina_v = read_ina_voltage(handle)
        print(f"    Voltage(): {v_int} mV, INA226: {ina_v} mV")

        if v_int and v_int > 0:
            return v_int, ina_v

    print()
    print("  *** ALL RECOVERY STEPS FAILED ***")
    print("  Voltage() remains 0. Possible hardware issue on BAT pin.")
    print("  Continuing with chemistry programming anyway...")
    return 0, read_ina_voltage(handle)


# ===========================================================================
#  PHASE 4: Design Parameters
# ===========================================================================

def phase4_design_params(handle):
    sep = "=" * 60
    print(sep)
    print("  PHASE 4: Design Parameters")
    print(sep)
    print()

    results = {}

    # --- SC 48: Design Energy + Design Capacity ---
    print("  --- SC 48: Design Energy / Capacity ---")
    unseal_fa(handle)
    blk48 = read_block(handle, 48)
    if blk48:
        de = (blk48[0] << 8) | blk48[1]
        dc = (blk48[11] << 8) | blk48[12]
        print(f"    Current: Energy={de}, Capacity={dc}")
        print(f"    Target : Energy={DESIGN_ENERGY}, Capacity={DESIGN_CAPACITY}")

        if de == DESIGN_ENERGY and dc == DESIGN_CAPACITY:
            print(f"    Already correct.")
            results['SC48'] = True
        else:
            ok = write_and_verify(handle, 48, [
                (0, u16_be(DESIGN_ENERGY)),
                (11, u16_be(DESIGN_CAPACITY)),
            ])
            results['SC48'] = ok
            print(f"    {'PASS' if ok else 'FAIL'}")
    else:
        results['SC48'] = False
        print(f"    READ FAILED")
    print()

    # --- SC 82: QMax ---
    print("  --- SC 82: QMax ---")
    unseal_fa(handle)
    blk82 = read_block(handle, 82)
    if blk82:
        qmax_cur = (blk82[0] << 8) | blk82[1]
        print(f"    Current: {qmax_cur}, Target: {QMAX}")
        if qmax_cur == QMAX:
            print(f"    Already correct.")
            results['SC82'] = True
        else:
            ok = write_and_verify(handle, 82, [(0, u16_be(QMAX))])
            results['SC82'] = ok
            print(f"    {'PASS' if ok else 'FAIL'}")
    else:
        results['SC82'] = False
        print(f"    READ FAILED")
    print()

    return results


# ===========================================================================
#  PHASE 5: Set Cells + Calibrate VD
# ===========================================================================

def phase5_cells_and_vd(handle, bq_v, ina_v):
    sep = "=" * 60
    print(sep)
    print("  PHASE 5: Cell Count + Voltage Divider Calibration")
    print(sep)
    print()

    # If we have a valid BQ voltage reading (from cells=1, VD=5000),
    # calibrate the VD using INA226 as ground truth, then set cells=8.
    #
    # For the BQ34Z100-R2 with external divider:
    #   Voltage() = V_BAT_pin * VD / 1000
    # With cells=1, Voltage() should equal the full pack voltage.
    # So: correct_VD = (actual_pack_mV / V_BAT_pin) * 1000
    # Since V_BAT_pin = bq_v * 1000 / VD_current:
    #   correct_VD = (actual_pack_mV * VD_current) / bq_v
    #
    # For cells=8, the BQ divides Voltage() by cells to get per-cell.
    # So Voltage() returns per-cell voltage.
    # We need: VD_for_8cells such that
    #   per_cell = V_BAT_pin * VD_for_8cells / 1000
    #   per_cell = actual_pack_mV / 8
    #   VD_for_8cells = VD_for_1cell / 8
    # OR: we keep VD as is and the BQ internally handles the /8.

    if bq_v and bq_v > 0 and ina_v and ina_v > 5000:
        # First, calibrate VD with cells=1
        cal_vd_1cell = int(round((ina_v / bq_v) * VD_INITIAL))
        print(f"  With cells=1, VD={VD_INITIAL}:")
        print(f"    BQ reads:   {bq_v} mV")
        print(f"    INA226:     {ina_v} mV")
        print(f"    Calibrated VD (cells=1): {cal_vd_1cell}")
        print(f"    Formula: ({ina_v} / {bq_v}) * {VD_INITIAL}")

        # Write calibrated VD first (still cells=1)
        print()
        print(f"  Writing VD={cal_vd_1cell} with cells=1...")
        unseal_fa(handle)
        ok = write_and_verify(handle, 104, [(14, u16_be(cal_vd_1cell))])
        if ok:
            print(f"    VD write: PASS")
        else:
            print(f"    VD write: FAIL")
            return False

        # Verify the reading is now correct
        reset_and_wake(handle, 5)
        v_check = read_std(handle, 0x0A)
        ina_check = read_ina_voltage(handle)
        print(f"    Verification: BQ={v_check} mV, INA={ina_check} mV")
        if v_check and ina_check:
            error = abs(v_check - ina_check) / ina_check * 100
            print(f"    Error: {error:.2f}%")
            if error > 5:
                # Fine-tune
                cal_vd_2 = int(round((ina_check / v_check) * cal_vd_1cell))
                print(f"    Fine-tuning VD: {cal_vd_1cell} -> {cal_vd_2}")
                unseal_fa(handle)
                write_and_verify(handle, 104, [(14, u16_be(cal_vd_2))])
                cal_vd_1cell = cal_vd_2

        # Now set cells=8
        # The BQ34Z100-R2 with cells=8 divides the per-cell voltage by...
        # Actually, let's try two approaches:
        #
        # Approach A: Keep VD as calibrated for cells=1, set cells=8,
        #   and see what Voltage() reports. If it reports per-cell
        #   voltage correctly, we're done.
        #
        # Approach B: If Voltage() goes to 0 with cells=8, the VD
        #   formula with /cells applies, and we need VD = cal_vd_1cell / 8.

        print()
        print(f"  === Setting cells=8 (VD={cal_vd_1cell}) ===")
        unseal_fa(handle)
        ok = write_sc64_safe(handle, [(7, [NUM_CELLS])])
        if ok:
            print(f"    Cells write: PASS")
        else:
            print(f"    Cells write: FAIL")
            return False

        # Enable IT and reset
        unseal_fa(handle)
        send_control(handle, 0x0021)  # IT_ENABLE
        aa_sleep_ms(1000)
        reset_and_wake(handle, 8)

        v8 = read_std(handle, 0x0A)
        pv8 = read_std(handle, 0x28)
        ina8 = read_ina_voltage(handle)
        print(f"    Voltage()     : {v8} mV")
        print(f"    PackVoltage() : {pv8} mV")
        print(f"    INA226        : {ina8} mV")

        if v8 and v8 > 0:
            print(f"    cells=8 is reading voltage!")
            # Check if it's per-cell or total pack
            if ina8:
                per_cell = ina8 / 8
                if abs(v8 - per_cell) < abs(v8 - ina8):
                    print(f"    Voltage() = per-cell ({v8} mV, expected ~{per_cell:.0f})")
                else:
                    print(f"    Voltage() = total pack ({v8} mV, expected ~{ina8})")
            return True
        else:
            print(f"    cells=8 broke voltage again. Trying VD/8...")
            # Restore cells=1, write VD/8, then cells=8
            unseal_fa(handle)
            write_sc64_safe(handle, [(7, [1])])
            reset_and_wake(handle, 3)

            vd_div8 = cal_vd_1cell // 8
            print(f"    Trying VD={vd_div8} (={cal_vd_1cell}/8) with cells=8...")
            unseal_fa(handle)
            write_and_verify(handle, 104, [(14, u16_be(vd_div8))])
            unseal_fa(handle)
            write_sc64_safe(handle, [(7, [NUM_CELLS])])

            unseal_fa(handle)
            send_control(handle, 0x0021)
            aa_sleep_ms(1000)
            reset_and_wake(handle, 8)

            v8b = read_std(handle, 0x0A)
            pv8b = read_std(handle, 0x28)
            ina8b = read_ina_voltage(handle)
            print(f"    Voltage()     : {v8b} mV")
            print(f"    PackVoltage() : {pv8b} mV")
            print(f"    INA226        : {ina8b} mV")

            if v8b and v8b > 0:
                print(f"    VD/8 approach worked!")
                return True
            else:
                print(f"    Still 0. Leaving at cells=1 with calibrated VD.")
                unseal_fa(handle)
                write_sc64_safe(handle, [(7, [1])])
                unseal_fa(handle)
                write_and_verify(handle, 104, [(14, u16_be(cal_vd_1cell))])
                reset_and_wake(handle, 3)
                return False
    else:
        print(f"  No valid voltage reading available for calibration.")
        print(f"  Setting cells={NUM_CELLS} and VD=844 (calculated)...")
        unseal_fa(handle)
        write_sc64_safe(handle, [(7, [NUM_CELLS])])
        unseal_fa(handle)
        write_and_verify(handle, 104, [(14, u16_be(844))])
        unseal_fa(handle)
        send_control(handle, 0x0021)  # IT_ENABLE
        aa_sleep_ms(1000)
        reset_and_wake(handle, 5)
        return False


# ===========================================================================
#  PHASE 6: Final Verification
# ===========================================================================

def phase6_verify(handle):
    sep = "=" * 60
    print(sep)
    print("  PHASE 6: Final Verification")
    print(sep)
    print()

    unseal_fa(handle)

    # Re-read CHEM_ID
    chem_id = read_control_sub(handle, 0x0008)
    print(f"  Chem ID       : 0x{chem_id:04X}" if chem_id is not None else "  Chem ID: FAIL")

    # Measurements
    v    = read_std(handle, 0x0A)
    pv   = read_std(handle, 0x28)
    soc  = read_std(handle, 0x03, n=1)
    cur  = read_std(handle, 0x14, signed=True)
    temp = read_std(handle, 0x0E)
    rcap = read_std(handle, 0x06)
    fcc  = read_std(handle, 0x08)
    dcap = read_std(handle, 0x3C)

    ina_v = read_ina_voltage(handle)

    print(f"  Voltage()     : {v} mV")
    print(f"  PackVoltage() : {pv} mV")
    print(f"  INA226 Bus V  : {ina_v} mV")
    print(f"  SOC           : {soc}%")
    print(f"  Current()     : {cur} mA")
    if temp is not None:
        print(f"  Temperature() : {temp*0.1-273.15:.1f} C")
    print(f"  RemainingCap  : {rcap} mAh")
    print(f"  FullChargeCap : {fcc} mAh")
    print(f"  DesignCap     : {dcap} mAh")

    # DF verification
    unseal_fa(handle)
    blk53 = read_block(handle, 53)
    if blk53:
        vals = [(blk53[i] << 8) | blk53[i+1] for i in range(0, 30, 2)]
        print(f"  R_a0 (25C)    : {vals}")

    unseal_fa(handle)
    blk55 = read_block(handle, 55)
    if blk55:
        vals = [(blk55[i] << 8) | blk55[i+1] for i in range(0, 30, 2)]
        print(f"  R_a1 (-5C)    : {vals}")

    unseal_fa(handle)
    blk64 = read_block(handle, 64)
    cells_final = blk64[7] if blk64 else "?"
    pc_final = (blk64[0] << 8) | blk64[1] if blk64 else 0

    unseal_fa(handle)
    blk104 = read_block(handle, 104)
    vd_final = (blk104[14] << 8) | blk104[15] if blk104 else "?"
    cc_g = struct.unpack('>f', bytes(blk104[0:4]))[0] if blk104 else 0
    cc_d = struct.unpack('>f', bytes(blk104[4:8]))[0] if blk104 else 0

    unseal_fa(handle)
    blk48 = read_block(handle, 48)
    de_final = (blk48[0] << 8) | blk48[1] if blk48 else "?"
    dc_final = (blk48[11] << 8) | blk48[12] if blk48 else "?"

    unseal_fa(handle)
    blk82 = read_block(handle, 82)
    qmax_final = (blk82[0] << 8) | blk82[1] if blk82 else "?"

    print()
    print(f"  Config Summary:")
    print(f"    Cells         : {cells_final}")
    print(f"    Pack Config   : 0x{pc_final:04X}")
    print(f"    Voltage Div   : {vd_final}")
    print(f"    CC Gain       : {cc_g:.6g}")
    print(f"    CC Delta      : {cc_d:.6g}")
    print(f"    Design Energy : {de_final}")
    print(f"    Design Cap    : {dc_final} mAh")
    print(f"    QMax          : {qmax_final} mAh")
    print()

    # Assess
    issues = []
    if v is None or v == 0:
        issues.append("Voltage() still 0 — BAT pin hardware issue likely")
    elif ina_v and abs(v - ina_v) / ina_v > 0.10:
        issues.append(f"Voltage mismatch: BQ={v} vs INA={ina_v} (>10% error)")
    if temp is not None and (temp * 0.1 - 273.15) < -40:
        issues.append("Temperature invalid — thermistor circuit needs PCB rework")
    if fcc and fcc < 1000:
        issues.append(f"FullChargeCap too low ({fcc} mAh) — gauge needs learning cycles")

    if issues:
        print("  ISSUES:")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print("  All readings nominal!")

    return len(issues) == 0


# ===========================================================================
#  Main
# ===========================================================================

def main():
    sep = "=" * 60
    print()
    print(sep)
    print("  BQ34Z100-R2 LiFePO4 Chemistry Programming")
    print("  Battery: Renogy RBT2425LFP (24V 25Ah 8S LiFePO4)")
    print(sep)

    handle = open_aardvark()

    # Wake
    print("Waking BQ34Z100-R2...")
    if wake(handle):
        print("  Awake.")
    else:
        print("  WARNING: No response, continuing anyway...")
    print()

    # Phase 1: Diagnostic dump
    diag = phase1_diagnostics(handle)
    print()

    # Phase 2: Program LiFePO4 R_a tables
    chem_results = phase2_chemistry(handle)
    print()

    # Phase 3: Recover voltage reading
    bq_v, ina_v = phase3_voltage_recovery(handle)
    print()

    # Phase 4: Design parameters
    param_results = phase4_design_params(handle)
    print()

    # Phase 5: Set cells + calibrate VD
    vd_ok = phase5_cells_and_vd(handle, bq_v, ina_v)
    print()

    # Phase 6: Final verification
    all_ok = phase6_verify(handle)

    # Seal and close
    print("Sealing gauge...")
    unseal_fa(handle)  # need to be unsealed to send seal command
    send_control(handle, 0x0020)  # SEAL
    aa_sleep_ms(100)

    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)

    print()
    print(sep)
    if all_ok:
        print("  PROGRAMMING COMPLETE — ALL OK")
    else:
        print("  PROGRAMMING COMPLETE — SOME ISSUES REMAIN")
        print("  (see issues above)")
    print(sep)
    print()


if __name__ == "__main__":
    main()
