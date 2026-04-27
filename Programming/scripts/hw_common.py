"""Shared hardware constants and Aardvark I2C init for AutoNav Charge Indicator.

All INA226 + BQ34Z100-R2 scripts import from here so that I2C addresses,
register maps, and unseal keys live in one place.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "aardvark-api-macos-arm64-v6.00", "python"))
from aardvark_py import *
from array import array

# ---------------------------------------------------------------------------
# I2C slave addresses
# ---------------------------------------------------------------------------
INA = 0x40            # INA226 (U3) — A1=GND, A0=GND (Rev 3 on robot)
BQ  = 0x55            # BQ34Z100-R2 (U1)

# Alias used by pcb_diagnostics
INA226_ADDR   = INA
BQ34Z100_ADDR = BQ

# ---------------------------------------------------------------------------
# INA226 register map (Table 2, datasheet SBOS547B)
# All registers are 16-bit, big-endian (MSB first).
# ---------------------------------------------------------------------------
REG_CONFIG   = 0x00   # Configuration
REG_SHUNT_V  = 0x01   # Shunt Voltage   (LSB = 2.5 uV, signed)
REG_BUS_V    = 0x02   # Bus Voltage      (LSB = 1.25 mV, unsigned)
REG_POWER    = 0x03   # Power            (LSB = 25 * Current_LSB, unsigned)
REG_CURRENT  = 0x04   # Current          (LSB = Current_LSB, signed)
REG_CAL      = 0x05   # Calibration
REG_MASK_EN  = 0x06   # Mask / Enable
REG_ALERT    = 0x07   # Alert Limit
REG_MFG_ID   = 0xFE   # Manufacturer ID  (expect 0x5449 = "TI")
REG_DIE_ID   = 0xFF   # Die ID           (expect 0x2260)

# Long-form aliases (used by pcb_diagnostics)
INA226_REG_CONFIG   = REG_CONFIG
INA226_REG_SHUNT_V  = REG_SHUNT_V
INA226_REG_BUS_V    = REG_BUS_V
INA226_REG_POWER    = REG_POWER
INA226_REG_CURRENT  = REG_CURRENT
INA226_REG_CAL      = REG_CAL
INA226_REG_MASK_EN  = REG_MASK_EN
INA226_REG_ALERT    = REG_ALERT
INA226_REG_MFR_ID   = REG_MFG_ID
INA226_REG_DIE_ID   = REG_DIE_ID

# ---------------------------------------------------------------------------
# BQ34Z100-R2 standard command addresses (TRM SLUUCO5A)
# All standard commands return 16-bit little-endian (LSB first).
# ---------------------------------------------------------------------------
BQ_CMD_STATE_OF_CHARGE = 0x03   # %
BQ_CMD_MAX_ERROR       = 0x04   # %
BQ_CMD_REMAINING_CAP   = 0x06   # mAh
BQ_CMD_FULL_CHARGE_CAP = 0x08   # mAh
BQ_CMD_VOLTAGE         = 0x0A   # mV
BQ_CMD_AVG_CURRENT     = 0x0C   # mA (signed)
BQ_CMD_TEMPERATURE     = 0x0E   # 0.1 K
BQ_CMD_FLAGS           = 0x10
BQ_CMD_FLAGS_B         = 0x12
BQ_CMD_CURRENT         = 0x14   # mA (signed, instantaneous)

# ---------------------------------------------------------------------------
# BQ34Z100-R2 Data Flash access registers and subclass IDs
# ---------------------------------------------------------------------------
BQ_BLOCK_DATA_CONTROL = 0x61
BQ_DATA_FLASH_CLASS   = 0x3E
BQ_DATA_FLASH_BLOCK   = 0x3F
BQ_BLOCK_DATA_BASE    = 0x40
BQ_BLOCK_DATA_CKSUM   = 0x60
BQ_SUBCLASS_PACK_CFG  = 64     # Pack Configuration (RSNS, VOLTSEL, TEMPS)
BQ_SUBCLASS_CC_CAL    = 104    # CC Gain and CC Delta

# ---------------------------------------------------------------------------
# BQ34Z100-R2 unseal / full-access keys (default from TI)
# ---------------------------------------------------------------------------
BQ_UNSEAL_KEY1      = 0x0414
BQ_UNSEAL_KEY2      = 0x3672
BQ_FULL_ACCESS_KEY1 = 0xFFFF
BQ_FULL_ACCESS_KEY2 = 0xFFFF
BQ_SUBCMD_SEALED         = 0x0020
BQ_SUBCMD_CONTROL_STATUS = 0x0000


# ---------------------------------------------------------------------------
# Aardvark I2C initialisation
# ---------------------------------------------------------------------------
def aardvark_init(bitrate=100, target_power=True):
    """Open the first Aardvark adapter, configure for I2C, return handle.

    Args:
        bitrate: I2C clock in kHz (default 100).
        target_power: If True, enable 5V target power (pull-ups). Set False
                      when the target must run from its own supply only.
    Returns:
        Aardvark handle (int).
    Exits on failure.
    """
    handle = aa_open(0)
    if handle <= 0:
        print(f"FAIL: Cannot open Aardvark adapter (error {handle})")
        sys.exit(1)
    aa_configure(handle, AA_CONFIG_SPI_I2C)
    aa_i2c_bitrate(handle, bitrate)
    if target_power:
        aa_target_power(handle, AA_TARGET_POWER_BOTH)
    else:
        aa_target_power(handle, AA_TARGET_POWER_NONE)
    aa_sleep_ms(500)
    return handle
