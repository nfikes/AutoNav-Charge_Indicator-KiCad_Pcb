"""BQ34Z100-R2 Communication Test + Config Verification

Phase 1: Read standard SBS registers to verify I2C communication.
Phase 2: Unseal, read Pack Config (SC 64), verify VOLTSEL=1 and RSNS=LOW.
         If config is wrong, automatically correct it.
Phase 3: RESET + power cycle to ensure running firmware loads new config.
         Re-verify from flash after reboot.

Rev 4+ voltage divider (R27=200kOhm, R22=6.49kOhm, ratio=31.82) keeps
BAT pin below 1V at maximum pack voltage (30V), so both VOLTSEL states
are safe. VOLTSEL=1 (factory default) is the correct setting — it
bypasses the internal 5:1 divider for best ADC resolution.

Does NOT calibrate or modify any other parameters.
"""
from hw_common import *

# Standard command registers (read 2 bytes, little-endian)
REGS = [
    (0x00, "Control Status",      "u16",  None),
    (0x02, "StateOfCharge",       "u16",  "%"),
    (0x04, "MaxError",            "u16",  "%"),
    (0x06, "RemainingCapacity",   "u16",  "mAh"),
    (0x08, "FullChargeCapacity",  "u16",  "mAh"),
    (0x0A, "Voltage",             "u16",  "mV"),
    (0x0C, "AverageCurrent",      "s16",  "mA"),
    (0x0E, "Temperature",         "temp", "K"),
    (0x10, "Flags",               "hex",  None),
    (0x12, "FlagsB",              "hex",  None),
    (0x14, "Current",             "s16",  "mA"),
    (0x1C, "SerialNumber",        "u16",  None),
]


# ---- I2C helpers ----

def read_u16(handle, addr, reg):
    """SMBus-style word read: write reg, read 2 bytes LE."""
    aa_i2c_write(handle, addr, AA_I2C_NO_STOP, array('B', [reg]))
    rc, data = aa_i2c_read(handle, addr, AA_I2C_NO_FLAGS, 2)
    if rc != 2:
        return None
    return data[0] | (data[1] << 8)   # little-endian


def read_s16(handle, addr, reg):
    v = read_u16(handle, addr, reg)
    if v is None:
        return None
    return v - 0x10000 if v >= 0x8000 else v


def wake(handle):
    """Wake BQ34Z100-R2 using DF-safe method (writes to 0x61, not 0x00)."""
    for i in range(6):
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
        aa_sleep_ms(50 * (i + 1))
        aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, array('B', [0x0A]))
        (rc, _) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
        if rc == 2:
            return True
    return False


def unseal_fa(handle):
    """Unseal + Full Access."""
    for subcmd in [0x0414, 0x3672, 0xFFFF, 0xFFFF]:
        d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(5)
    aa_sleep_ms(100)


def read_df_block(handle, subclass, block=0):
    """Read a 32-byte DF block (must be unsealed first)."""
    for reg, val in [(0x61, 0x00), (0x3E, subclass), (0x3F, block)]:
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [reg, val]))
        aa_sleep_ms(10)
    aa_sleep_ms(100)

    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, array('B', [0x40]))
    (rc, raw) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 32)
    if rc != 32:
        return None
    blk = list(raw[:32])

    # Validate checksum
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, array('B', [0x60]))
    (rc2, ck) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 1)
    if rc2 == 1:
        expected = (255 - (sum(blk) & 0xFF)) & 0xFF
        if ck[0] != expected:
            if all(b == 0 for b in blk[:16]):
                return None   # stale — sealed or context lost
    return blk


def write_df_block_and_verify(handle, subclass, original, modifications, block=0):
    """Modify specific offsets, commit to flash, verify."""
    modified = list(original)
    for offset, new_bytes in modifications:
        for i, b in enumerate(new_bytes):
            modified[offset + i] = b

    # Re-load block into BQ RAM
    for reg, val in [(0x61, 0x00), (0x3E, subclass), (0x3F, block)]:
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [reg, val]))
        aa_sleep_ms(10)
    aa_sleep_ms(100)

    # Write all 32 bytes individually
    for i in range(32):
        c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS,
                         array('B', [0x40 + i, modified[i]]))
        if c != 2:
            print(f"    WRITE FAIL at byte {i}: {c}/2")
            return False
        aa_sleep_ms(3)

    # Commit with checksum
    cksum = (255 - (sum(modified) & 0xFF)) & 0xFF
    aa_sleep_ms(20)
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x60, cksum]))
    if c != 2:
        print("    CHECKSUM NACK")
        return False
    print(f"    Committed (cksum 0x{cksum:02X}), waiting 2s...")
    aa_sleep_ms(2000)

    # Auto-seals after flash commit — re-unseal
    unseal_fa(handle)

    # Verify
    verify = read_df_block(handle, subclass, block)
    if verify is None:
        print("    Verify read FAILED")
        return False
    for offset, new_bytes in modifications:
        for i, b in enumerate(new_bytes):
            if verify[offset + i] != b:
                print(f"    VERIFY FAIL offset {offset+i}: "
                      f"wrote 0x{b:02X}, read 0x{verify[offset+i]:02X}")
                return False
    return True


def reset_and_power_cycle(handle):
    """Send RESET command + power cycle to force firmware to reload from flash.

    Flash commits do NOT update running firmware. A RESET is required
    after changing Pack Config so the new values take effect.
    """
    print("  Sending RESET command (Control 0x0041)...")
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x00, 0x41, 0x00]))
    aa_sleep_ms(1000)

    print("  Power cycling (target power off/on)...")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_sleep_ms(2000)
    aa_target_power(handle, AA_TARGET_POWER_BOTH)
    aa_sleep_ms(2000)

    # Wait for chip to come back
    print("  Waiting for chip to reboot...")
    for attempt in range(10):
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
        aa_sleep_ms(500)
        aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, array('B', [0x0A]))
        (rc, _) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
        if rc == 2:
            print(f"  Chip back online (attempt {attempt + 1})")
            return True

    print("  WARNING: Chip did not respond after reset + power cycle")
    return False


def seal(handle):
    """Send Seal command (Control 0x0020)."""
    aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x00, 0x20, 0x00]))


def cleanup(handle):
    seal(handle)
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)


# ==================================================================
#  PHASE 1 — Basic I2C Communication Check
# ==================================================================
print("=" * 62)
print("  BQ34Z100-R2 Comm Test + Config Verification")
print("=" * 62)

handle = aardvark_init()

print(f"\n--- Phase 1: Standard Register Read (0x{BQ:02X}) ---")

any_ack = False
for reg, name, fmt, unit in REGS:
    raw = read_u16(handle, BQ, reg)
    if raw is None:
        print(f"  0x{reg:02X}  {name:<22s}  READ FAIL (no ACK)")
        continue
    any_ack = True

    if fmt == "hex":
        val_str = f"0x{raw:04X}"
    elif fmt == "s16":
        signed = raw - 0x10000 if raw >= 0x8000 else raw
        val_str = f"{signed}"
        if unit:
            val_str += f" {unit}"
    elif fmt == "temp":
        temp_k = raw * 0.1
        temp_c = temp_k - 273.15
        val_str = f"{temp_k:.1f} K  ({temp_c:.1f} C)"
    else:
        val_str = f"{raw}"
        if unit:
            val_str += f" {unit}"

    print(f"  0x{reg:02X}  {name:<22s}  {val_str}")

# Flags decode
if any_ack:
    flags_raw = read_u16(handle, BQ, 0x10)
    if flags_raw is not None:
        print(f"\n  Flags decode (0x{flags_raw:04X}):")
        flag_bits = [
            (15, "OTC",      "Over-Temperature in Charge"),
            (14, "OTD",      "Over-Temperature in Discharge"),
            (13, "BATHI",    "Battery High"),
            (12, "BATLOW",   "Battery Low"),
            (11, "CHG_INH",  "Charge Inhibit"),
            ( 9, "FC",       "Full Charge detected"),
            ( 8, "CHG",      "Charge allowed"),
            ( 4, "OCVTAKEN", "OCV measurement taken"),
            ( 3, "CF",       "Condition Flag"),
            ( 1, "SOC1",     "SOC threshold 1 reached"),
            ( 0, "SOCF",     "SOC Final threshold reached"),
        ]
        active = [f"    [{s}] {d}" for bit, s, d in flag_bits
                  if flags_raw & (1 << bit)]
        if active:
            for a in active:
                print(a)
        else:
            print("    (no flags set)")

if not any_ack:
    print("\n" + "=" * 62)
    print("RESULT: BQ34Z100-R2 NOT responding — no ACK at 0x55")
    print("  Check: Is BAT pin powered? Solder joints OK?")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    sys.exit(1)

print("\n  Phase 1 PASS — communication OK")

# ==================================================================
#  PHASE 2 — Config Verification (unseal + read SC 64)
# ==================================================================
print(f"\n--- Phase 2: Config Verification (VOLTSEL + RSNS) ---")

print("  Waking (DF-safe)...")
if not wake(handle):
    print("  Wake failed — chip may be in shutdown. Skipping VOLTSEL check.")
    cleanup(handle)
    sys.exit(0)
print("  Awake")

print("  Unsealing...")
unseal_fa(handle)

blk64 = read_df_block(handle, 64)
if blk64 is None:
    print("  SC 64 read FAILED (stale or context lost)")
    print("  Retrying after re-unseal...")
    unseal_fa(handle)
    blk64 = read_df_block(handle, 64)

if blk64 is None:
    print("  SC 64 read FAILED on retry — cannot verify VOLTSEL")
    print("  *** DO NOT ENABLE VOLTAGE DIVIDER ***")
    cleanup(handle)
    sys.exit(1)

pack_config = (blk64[0] << 8) | blk64[1]
voltsel = bool(pack_config & 0x0008)   # bit 3
cell_count = blk64[7]

print(f"  Pack Config : 0x{pack_config:04X}")
rsns = bool(pack_config & 0x0080)   # bit 7
print(f"  VOLTSEL     : {int(voltsel)} ({'EXT (correct)' if voltsel else 'INT (not optimal)'})")
print(f"  RSNS        : {'HIGH' if rsns else 'LOW'} side")
print(f"  Cell Count  : {cell_count}")

config_was_changed = False
new_config = pack_config

# VOLTSEL=1 is the correct setting for the Rev 4+ voltage divider.
# With R22=6.49kOhm, BAT pin stays below 1V at 30V max, so bypassing
# the internal 5:1 divider (VOLTSEL=1) gives the best ADC resolution.
if not voltsel:
    print()
    print("  VOLTSEL=0 detected — setting to 1 for best ADC resolution.")
    new_config = new_config | 0x0008  # Set VOLTSEL
    config_was_changed = True

# RSNS must be LOW for low-side current sensing (R26).
if rsns:
    print("  RSNS=HIGH detected — setting to LOW for low-side sensing.")
    new_config = new_config & ~0x0080  # Clear RSNS
    config_was_changed = True

if config_was_changed:
    print(f"  Pack Config: 0x{pack_config:04X} -> 0x{new_config:04X}")

    unseal_fa(handle)
    fresh = read_df_block(handle, 64)
    if fresh is None:
        print("  Fresh read failed — ABORTING.")
        cleanup(handle)
        sys.exit(1)

    ok = write_df_block_and_verify(handle, 64, fresh, [
        (0, [(new_config >> 8) & 0xFF, new_config & 0xFF]),
    ])
    if ok:
        print("  Config written to flash and VERIFIED.")
    else:
        print("  *** CONFIG WRITE FAILED ***")
        cleanup(handle)
        sys.exit(1)
else:
    print("\n  VOLTSEL=1, RSNS=LOW — config correct, no change needed.")

# ==================================================================
#  PHASE 3 — RESET + Power Cycle + Re-Verify
#
#  Flash commits do NOT update the running firmware.
#  The chip must be reset so it reloads Pack Config from flash
#  into RAM.
# ==================================================================
print(f"\n--- Phase 3: Reset + Reload + Re-Verify ---")

if config_was_changed:
    print()
    print("  Config was changed — reset required for new values to take effect.")

print()
if not reset_and_power_cycle(handle):
    print("  *** RESET FAILED ***")
    print("  Try disconnecting and reconnecting the Aardvark, then re-run.")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    sys.exit(1)

# Re-unseal after reboot
print("  Re-unsealing after reboot...")
unseal_fa(handle)

# Re-read SC 64 from flash to confirm config survived the reset
print("  Re-reading Pack Config after reset...")
blk64_post = read_df_block(handle, 64)
if blk64_post is None:
    print("  SC 64 read FAILED after reset")
    print("  Retrying...")
    unseal_fa(handle)
    blk64_post = read_df_block(handle, 64)

if blk64_post is None:
    print("  *** CANNOT VERIFY CONFIG AFTER RESET ***")
    cleanup(handle)
    sys.exit(1)

pc_post = (blk64_post[0] << 8) | blk64_post[1]
voltsel_post = bool(pc_post & 0x0008)
rsns_post = bool(pc_post & 0x0080)

print(f"  Pack Config : 0x{pc_post:04X}")
print(f"  VOLTSEL     : {int(voltsel_post)} ({'EXT (correct)' if voltsel_post else 'INT'})")
print(f"  RSNS        : {'HIGH' if rsns_post else 'LOW'} side")

if not voltsel_post:
    print()
    print("  WARNING: VOLTSEL is still 0 after reset — suboptimal ADC resolution.")
    print("  Re-run this script to retry.")

# Read voltage to confirm ADC is responding (should be near 0 with divider off)
v_post = read_u16(handle, BQ, 0x0A)
print(f"  Voltage()   : {v_post} mV (divider should be off)")

# ==================================================================
#  Summary
# ==================================================================
print("\n" + "=" * 62)
print("RESULT: BQ34Z100-R2 communication OK")
print(f"  VOLTSEL = {int(voltsel_post)} in flash — {'correct' if voltsel_post else 'suboptimal'}")
print(f"  RSNS = {'LOW' if not rsns_post else 'HIGH'} — {'correct' if not rsns_post else 'check sensing'}")
print(f"  Reset completed — firmware reloaded from flash")
if config_was_changed:
    print(f"  (Config was auto-corrected)")
print()
print("  Voltage divider is safe to enable.")
print("=" * 62)

cleanup(handle)
