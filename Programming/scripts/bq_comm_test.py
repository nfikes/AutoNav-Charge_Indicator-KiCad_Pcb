"""BQ34Z100-R2 Communication Test + VOLTSEL Safety Check — Rev 3 PCB

Phase 1: Read standard SBS registers to verify I2C communication.
Phase 2: Unseal, read Pack Config (SC 64), verify VOLTSEL=0.
         If VOLTSEL=1, automatically clear it to protect the ADC.
Does NOT calibrate or modify any other parameters.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *
from array import array

BQ = 0x55

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
print("=" * 58)
print("  BQ34Z100-R2 Comm Test + VOLTSEL Safety — Rev 3 PCB")
print("=" * 58)

handle = aa_open(0)
if handle <= 0:
    print(f"\nFAIL: Cannot open Aardvark adapter (error {handle})")
    sys.exit(1)
print(f"Aardvark opened (handle={handle})")

aa_configure(handle, AA_CONFIG_SPI_I2C)
bitrate = aa_i2c_bitrate(handle, 100)
print(f"I2C bitrate: {bitrate} kHz")
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(500)

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
    print("\n" + "=" * 58)
    print("RESULT: BQ34Z100-R2 NOT responding — no ACK at 0x55")
    print("  Check: Is BAT pin powered? Solder joints OK?")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    sys.exit(1)

print("\n  Phase 1 PASS — communication OK")

# ==================================================================
#  PHASE 2 — VOLTSEL Safety Check (unseal + read SC 64)
# ==================================================================
print(f"\n--- Phase 2: VOLTSEL Safety Check ---")

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
    print("  *** PROCEED WITH EXTREME CAUTION ***")
    cleanup(handle)
    sys.exit(1)

pack_config = (blk64[0] << 8) | blk64[1]
voltsel = bool(pack_config & 0x0008)   # bit 3
cell_count = blk64[7]

print(f"  Pack Config : 0x{pack_config:04X}")
print(f"  VOLTSEL     : {int(voltsel)} ({'EXT — DANGEROUS!' if voltsel else 'INT — safe'})")
print(f"  Cell Count  : {cell_count}")

if voltsel:
    print()
    print("  !!! VOLTSEL=1 DETECTED — AUTO-CLEARING TO PROTECT ADC !!!")
    pc_safe = pack_config & ~0x0008
    print(f"  Pack Config: 0x{pack_config:04X} -> 0x{pc_safe:04X}")

    unseal_fa(handle)
    fresh = read_df_block(handle, 64)
    if fresh is None:
        print("  Fresh read failed — ABORTING (do NOT power bus voltage!)")
        cleanup(handle)
        sys.exit(1)

    ok = write_df_block_and_verify(handle, 64, fresh, [
        (0, [(pc_safe >> 8) & 0xFF, pc_safe & 0xFF]),
    ])
    if ok:
        print("  VOLTSEL cleared and VERIFIED — ADC is safe.")
    else:
        print("  *** VOLTSEL CLEAR FAILED — do NOT power bus voltage! ***")
        cleanup(handle)
        sys.exit(1)
else:
    print("\n  VOLTSEL=0 confirmed — ADC is safe.")

# ==================================================================
#  Summary
# ==================================================================
print("\n" + "=" * 58)
print("RESULT: BQ34Z100-R2 communication OK, VOLTSEL verified safe")
print("=" * 58)

cleanup(handle)
