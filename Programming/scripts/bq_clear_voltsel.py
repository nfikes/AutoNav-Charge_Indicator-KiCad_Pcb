"""Clear VOLTSEL (bit 3 of Pack Config, SC 64) on BQ34Z100-R2.

VOLTSEL=1 bypasses the internal 5:1 divider and exposes the ADC to >1V,
destroying analog front-end measurements on this board.  This script
reads Pack Config, clears bit 3 if set, writes it back, and verifies.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *
from array import array

BQ = 0x55

handle = aa_open(0)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(500)


def wake():
    """Wake BQ34Z100-R2 using DF-safe method (writes to 0x61, not 0x00)."""
    for i in range(6):
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
        aa_sleep_ms(50 * (i + 1))
        d = array('B', [0x0A])
        aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
        (rc, _) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
        if rc == 2:
            return True
    return False


def unseal_fa():
    """Unseal + Full Access."""
    for subcmd in [0x0414, 0x3672, 0xFFFF, 0xFFFF]:
        d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(5)
    aa_sleep_ms(100)


def read_block(subclass, block=0):
    """Read a 32-byte DF block."""
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
                print("  STALE DATA — sealed or context lost")
                return None
    return blk


def write_block_and_verify(subclass, original, modifications, block=0):
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
        c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x40 + i, modified[i]]))
        if c != 2:
            print(f"  WRITE FAIL at byte {i}: {c}/2")
            return False
        aa_sleep_ms(3)

    # Commit with checksum
    cksum = (255 - (sum(modified) & 0xFF)) & 0xFF
    aa_sleep_ms(20)
    c = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x60, cksum]))
    if c != 2:
        print("  CHECKSUM NACK")
        return False
    print(f"  Committed (cksum 0x{cksum:02X}), waiting 2s...")
    aa_sleep_ms(2000)

    # Auto-seals after flash commit — re-unseal
    unseal_fa()

    # Verify
    verify = read_block(subclass, block)
    if verify is None:
        print("  Verify read FAILED")
        return False
    for offset, new_bytes in modifications:
        for i, b in enumerate(new_bytes):
            if verify[offset + i] != b:
                print(f"  VERIFY FAIL offset {offset+i}: wrote 0x{b:02X}, read 0x{verify[offset+i]:02X}")
                return False
    return True


# ── Main ──────────────────────────────────────────────────────────────
print("=== BQ34Z100-R2: Clear VOLTSEL ===\n")

print("Waking...")
if not wake():
    print("  No response from BQ — aborting")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    raise SystemExit(1)
print("  Awake")

unseal_fa()

blk64 = read_block(64)
if blk64 is None:
    print("SC 64 read FAILED — aborting")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    raise SystemExit(1)

pc = (blk64[0] << 8) | blk64[1]
voltsel = bool(pc & 0x0008)
cells = blk64[7]
print(f"  Pack Config : 0x{pc:04X}")
print(f"  VOLTSEL     : {int(voltsel)} ({'EXT — DANGEROUS' if voltsel else 'INT — safe'})")
print(f"  Cell Count  : {cells}")
print()

if not voltsel:
    print("VOLTSEL is already 0 — nothing to do.")
else:
    pc_safe = pc & ~0x0008  # Clear bit 3
    print(f"Clearing VOLTSEL: 0x{pc:04X} -> 0x{pc_safe:04X}")
    unseal_fa()
    fresh = read_block(64)
    if fresh is None:
        print("  Fresh read failed — aborting")
        aa_target_power(handle, AA_TARGET_POWER_NONE)
        aa_close(handle)
        raise SystemExit(1)

    # Only modify Pack Config bytes (offset 0-1), leave everything else intact
    ok = write_block_and_verify(64, fresh, [
        (0, [(pc_safe >> 8) & 0xFF, pc_safe & 0xFF]),
    ])
    if ok:
        print("  VOLTSEL cleared and VERIFIED.")
    else:
        print("  *** WRITE FAILED ***")

# Seal and close
aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x00, 0x20, 0x00]))
aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\nDone.")
