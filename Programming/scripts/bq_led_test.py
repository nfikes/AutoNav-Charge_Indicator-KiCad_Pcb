"""Test BQ34Z100-R2 LED control.

Found: LED Config = 0x00 (No LED mode). Need to enable it.
Board has 5 LEDs driven via P1/P2 through MOSFETs.

Plan:
1. Set LED Config to mode 2 (Four LEDs direct) + LED_ON=1
2. Commit + RESET
3. Try 0x0030 (All LEDs ON)
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *
from array import array

BQ = 0x55
handle = aa_open(0)
if handle < 0:
    print(f"Aardvark open failed: {handle}")
    exit(1)
aa_configure(handle, AA_CONFIG_SPI_I2C)
aa_i2c_bitrate(handle, 100)
aa_target_power(handle, AA_TARGET_POWER_BOTH)
aa_sleep_ms(500)


def wake():
    for i in range(6):
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, array('B', [0x61, 0x00]))
        aa_sleep_ms(200)


def unseal_fa():
    for subcmd in [0x0414, 0x3672, 0xFFFF, 0xFFFF]:
        d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
        aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
        aa_sleep_ms(5)
    aa_sleep_ms(100)


def send_control(subcmd):
    d = array('B', [0x00, subcmd & 0xFF, (subcmd >> 8) & 0xFF])
    rc = aa_i2c_write(handle, BQ, AA_I2C_NO_FLAGS, d)
    aa_sleep_ms(10)
    return rc


def read_control():
    d = array('B', [0x00])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    if rc != 2:
        return None
    return data[0] | (data[1] << 8)


def read_std(cmd):
    d = array('B', [cmd])
    aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
    (rc, data) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
    if rc != 2:
        return None
    return data[0] | (data[1] << 8)


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


wake()

# ACK check
d = array('B', [0x0A])
aa_i2c_write(handle, BQ, AA_I2C_NO_STOP, d)
(rc, _) = aa_i2c_read(handle, BQ, AA_I2C_NO_FLAGS, 2)
if rc != 2:
    print("BQ not responding at 0x55.")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    exit(1)
print("BQ ACK OK")

# ---- Step 1: Read current LED config ----
print("\n--- Current SC 64 State ---")
blk64 = read_block(64)
if not blk64:
    print("SC 64 read FAILED!")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    exit(1)

pc = (blk64[0] << 8) | blk64[1]
led_old = blk64[5]
print(f"  Pack Config: 0x{pc:04X}")
print(f"  LED Config (offset 5): 0x{led_old:02X}")
print(f"  Raw bytes 0-7: {' '.join(f'{b:02X}' for b in blk64[:8])}")

# ---- Step 2: Set LED Config = 0x0A (mode 2 + LED_ON) ----
# Bits [2:0] = 010 (mode 2: Four LEDs direct)
# Bit  [3]   = 1   (LED_ON: always display)
# Bits [7:4] = 0   (no external LED count)
new_led = 0x0A  # 0b00001010
print(f"\n--- Setting LED Config: 0x{led_old:02X} -> 0x{new_led:02X} ---")
print(f"  Mode: 2 (Four LEDs direct via P1/P2)")
print(f"  LED_ON: 1 (always display)")

mod64 = list(blk64)
mod64[5] = new_led
if not write_block(64, mod64):
    print("  Write FAILED!")
    aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_close(handle)
    exit(1)
print("  Write + checksum committed OK")

# Verify
verify = read_block(64)
if verify:
    v_led = verify[5]
    print(f"  Verify LED Config: 0x{v_led:02X} {'OK' if v_led == new_led else 'MISMATCH!'}")

# ---- Step 3: RESET to apply ----
print("\nResetting chip to apply LED config...")
unseal_fa()
send_control(0x0041)
aa_sleep_ms(5000)
wake()
aa_sleep_ms(2000)

# Check if LEDs came on after reset (LED_ON=1 should auto-display)
v = read_std(0x0A)
print(f"\n  Post-reset Voltage: {v} mV")
print("  LEDs should now be showing SOC bar graph (even if 0%).")
print("  Watch for ANY LED activity for 10 seconds...")
for i in range(10, 0, -1):
    print(f"  {i}...", end=" ", flush=True)
    aa_sleep_ms(1000)
print()

# ---- Step 4: Try 0x0030 All LEDs ON ----
print("\n--- Sending Control(0x0030) — All LEDs ON ---")
unseal_fa()
aa_sleep_ms(100)
send_control(0x0030)
print("  Sent. Watch LEDs for 15 seconds...")
for i in range(15, 0, -1):
    print(f"  {i}...", end=" ", flush=True)
    aa_sleep_ms(1000)
print()

# Turn off
print("\nSending Control(0x0031) — All LEDs OFF...")
send_control(0x0031)
aa_sleep_ms(2000)

# ---- Step 5: Restore LED Config to 0x00 ----
print("\nRestoring LED Config to 0x00 (No LED)...")
blk64 = read_block(64)
if blk64:
    mod64 = list(blk64)
    mod64[5] = 0x00
    write_block(64, mod64)
    unseal_fa()
    send_control(0x0041)  # RESET
    aa_sleep_ms(5000)
    wake()
    aa_sleep_ms(1000)
    verify = read_block(64)
    if verify:
        print(f"  Restored: LED Config = 0x{verify[5]:02X}")

aa_target_power(handle, AA_TARGET_POWER_NONE)
aa_close(handle)
print("\nDone.")
