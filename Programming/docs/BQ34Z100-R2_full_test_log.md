# BQ34Z100-R2 Debugging History

Complete record of every trial performed to diagnose and recover the
BQ34Z100-R2 fuel gauge on the AutoNav Charge Indicator board (Rev 2-4).
Covers the period from initial bringup (Feb 2026) through the decision to
adopt the INA226 as the primary fuel gauge (Apr 2026).

---

## Table of Contents

1. [Background](#1-background)
2. [Hardware Evolution](#2-hardware-evolution)
3. [Chip Inventory](#3-chip-inventory)
4. [Phase 0A: Board Bringup and First I2C Contact (Feb 6)](#4-phase-0a-board-bringup-and-first-i2c-contact-feb-6)
5. [Phase 0B: First Data Flash Experiments (Feb 10)](#5-phase-0b-first-data-flash-experiments-feb-10)
6. [Phase 0C: VOLTSEL Catastrophe and Chip Deaths (Feb 2026)](#6-phase-0c-voltsel-catastrophe-and-chip-deaths-feb-2026)
7. [Phase 0D: Battery Programming and VD=844 Gauge Lockup (Feb 18)](#7-phase-0d-battery-programming-and-vd844-gauge-lockup-feb-18)
8. [Phase 0E: Recovery Campaign and Third Chip Death (Feb-Mar 2026)](#8-phase-0e-recovery-campaign-and-third-chip-death-feb-mar-2026)
9. [Phase 1: Voltage Divider Retrofit (Mar 19)](#9-phase-1-voltage-divider-retrofit-mar-19)
10. [Phase 2: First Fresh Chip (Defective)](#10-phase-2-first-fresh-chip-defective)
11. [Phase 3: Old Chip Cross-Validation](#11-phase-3-old-chip-cross-validation)
12. [Phase 4: Second Fresh Chip (Chip 1G)](#12-phase-4-second-fresh-chip-chip-1g)
13. [Phase 5: Overnight Recovery Attempts](#13-phase-5-overnight-recovery-attempts)
14. [Phase 6: Third Fresh Chip -- Incremental Isolation](#14-phase-6-third-fresh-chip----incremental-isolation)
15. [Phase 7: Multi-Chip Rotation and ADC Mystery](#15-phase-7-multi-chip-rotation-and-adc-mystery)
16. [Phase 8: Final Recovery Attempts (Chips 2G and 1G)](#16-phase-8-final-recovery-attempts-chips-2g-and-1g)
17. [Phase 9: LED Test and INA226 Adoption](#17-phase-9-led-test-and-ina226-adoption)
18. [Theory Tracker](#18-theory-tracker)
19. [Final Chip Status](#19-final-chip-status)
20. [Scripts Written](#20-scripts-written)
21. [Lessons Learned](#21-lessons-learned)

---

## 1. Background

The BQ34Z100-R2 is a battery fuel gauge IC from Texas Instruments, used on
the AutoNav Charge Indicator PCB to measure pack voltage, current, and state
of charge for a Renogy RBT2425LFP battery (24V 25Ah LiFePO4, 8S7P). The
chip communicates over I2C at address 0x55 and uses a voltage divider on
the BAT pin to scale down the 20-30V pack voltage for its internal ADC.

The project went through two distinct hardware eras:

- **Rev 2-3 (original, Feb-Mar 2026):** R22=34.8kOhm bottom divider, ratio
  6.75:1. BAT pin saw ~3.8V at nominal pack voltage. With VOLTSEL=1 (factory
  default), the full 3.8V reached the ADC directly -- nearly 4x over the 1.0V
  maximum. Three chips had their ADCs permanently destroyed this way. A
  physical disconnect switch (SW1) was used as a safety measure during
  programming, but procedural errors still caused damage.

- **Rev 4+ (after Mar 19, 2026):** R22=6.49kOhm bottom divider, ratio
  31.82:1. BAT pin stays under 1V across the full 20-30V operating range.
  VOLTSEL=1 is now safe and correct. This eliminated the VOLTSEL danger at
  the hardware level, but the resulting low BAT voltage (~0.94V max)
  introduced new challenges with the IT algorithm and an unsolved 18x ADC
  discrepancy.

### Hardware Architecture (Rev 4+)

```
Pack (20-30V)
    |
  R27 = 200kOhm (top)
    |
    +--- Divider junction
    |         |
  R22 = 6.49kOhm (bottom)   TLV271CW5-7 (unity-gain buffer)
    |         |                  (+) <-- divider junction
   GND        |                  (-) <-- output
              +--- Buffer out --> BQ BAT pin (Pin 4)
                                  2.0V zener to GND (protection)

BQ Power: REGIN (Pin 6) = 5V, REG25 (Pin 7) = 2.5V LDO out
          VEN (Pin 2) tied to REG25 = always enabled
I2C: SDA/SCL with 10kOhm pull-ups to 3.3V
```

The TLV271 op-amp buffer eliminates divider loading concerns -- the BAT pin
sees a low-impedance drive regardless of its input current.

### Hardware Architecture (Rev 2-3, original)

```
Pack (20-30V)
    |
  R27 = 200kOhm (top)
    |
    +--- Divider junction --[SW1 disconnect switch]--> BQ BAT pin (Pin 4)
    |                                                   2.0V zener to GND
  R22 = 34.8kOhm (bottom)
    |
   GND

BAT pin voltage at 25.6V pack: ~3.8V (DANGEROUS with VOLTSEL=1)
BAT pin voltage at 30V pack:   ~4.4V (DANGEROUS with VOLTSEL=1)

With VOLTSEL=0: internal 5:1 divider active, ADC sees 3.8V/5 = 0.76V (safe)
With VOLTSEL=1: internal divider bypassed, ADC sees full 3.8V (DESTRUCTIVE)
```

SW1 was a physical SPDT slide switch used to disconnect the divider from the
BAT pin during programming, so VOLTSEL could be verified/cleared before
voltage was applied.

---

## 2. Hardware Evolution

Physical changes made to the PCB across all debugging phases:

| Change | From | To | When | Reason |
|--------|------|----|------|--------|
| R22 (bottom divider) | 34.8kOhm | 6.49kOhm | Mar 19, 2026 | Protect ADC: BAT < 1V at 30V pack |
| R5/R6 (I2C pull-ups) | 4.7kOhm | 10kOhm | Mar 2026 | Per BQ datasheet recommendation |
| VOLTSEL policy | Must be 0 (clear before connecting divider) | Must be 1 (factory default, now safe) | Mar 19, 2026 | New divider makes bypass safe |
| BQ chip | (multiple swaps) | -- | Feb-Mar 2026 | At least 5 solder/desolder cycles on the BQ footprint |

### Rev 2-3 divider (original)

With R22=34.8kOhm and R27=200kOhm, divider ratio is 6.75:1:

| Pack Voltage | BAT Pin | ADC (VOLTSEL=0, 5:1) | ADC (VOLTSEL=1, bypass) | Safe? |
|---|---|---|---|---|
| 20V | 2.96V | 0.59V | 2.96V | VOLTSEL=0 only |
| 25.6V | 3.79V | 0.76V | 3.79V | VOLTSEL=0 only |
| 30V | 4.44V | 0.89V | 4.44V | VOLTSEL=0 only |

### Rev 4+ divider (after retrofit)

With R22=6.49kOhm and R27=200kOhm, divider ratio is 31.82:1:

| Pack Voltage | BAT Pin (calculated) | BAT Pin (measured) |
|---|---|---|
| 20V | 0.629V | 0.631V |
| 25V | 0.786V | 0.784V |
| 30V | 0.943V | 0.935V |

All within the BQ34Z100-R2 BAT ADC input range of 0.05V to 1.0V.

---

## 3. Chip Inventory

Eight BQ34Z100-R2 chips were involved across all trials:

| Chip ID | Description | Destroyed By | Origin |
|---------|-------------|--------------|--------|
| Old Chip A | ADC destroyed by ~3.8V on BAT (VOLTSEL=1 + old 34.8k divider) | VOLTSEL=1 overvoltage | Original bringup, Feb 2026 |
| Old Chip B | ADC destroyed by same mechanism | VOLTSEL=1 overvoltage | Original bringup, Feb 2026 |
| Old Chip C | ADC destroyed; also suffered VD=844 gauge lockup during recovery attempts | VOLTSEL=1 overvoltage + VD=844 lockup | Programming attempts, Feb 2026 |
| First fresh chip | New from stock, defective I2C -- never ACKed under any conditions | Dead on arrival | Soldered for Trial 2 (post-divider) |
| Chip 1G | New from stock, initially worked (33mV), then ADC locked at 0mV after CC cal | CC calibration at low BAT | Soldered for Trial 16 (post-divider) |
| Chip 2G | One of the old configured chips, later NACKed due to solder damage | Repeated solder/desolder | Swapped in for Trial 33 (post-divider) |
| Chip 1N | New/unused, in storage | -- | Reserved for future use with TI tools |
| Chip 2N | New/unused, in storage | -- | Reserved for future use with TI tools |

---

## 4. Phase 0A: Board Bringup and First I2C Contact (Feb 6)

*Reconstructed from git commit 9d376e2 (Feb 6, 2026) and script contents.*

**Goal:** Verify I2C communication with both INA226 and BQ34Z100-R2 on the
Rev 3 PCB using the Total Phase Aardvark USB-I2C adapter.

**Hardware state:** Original voltage divider R27=200kOhm / R22=34.8kOhm
(ratio 6.75:1). I2C pull-ups R5/R6 = 4.7kOhm to 3.3V. VOLTSEL state on
the chip unknown at this point.

### Trial 0-1: First pcb_diagnostics.py run

**Action:** Created `pcb_diagnostics.py` (476 lines) -- the first I2C
diagnostics script. Connected Aardvark adapter at 100kHz, powered board
with bench supply.

**Results:**
- INA226 (0x40): ACKed. Manufacturer ID = 0x5449 (TI), Die ID = 0x2260.
  Calibration register written (CAL=1706 for 12mOhm shunt R4). Bus voltage,
  current, and power readings functional.
- BQ34Z100-R2 (0x55): ACKed. Standard command registers readable: SOC,
  Voltage, AvgCurrent, InstantCurrent, Temperature, RemainingCapacity,
  FullChargeCapacity, Flags.
- BQ Flags decoded: OTC, OTD, CHG_INH, FC, CHG, SOC1, SOCF, DSG bits.

**Significance:** Both chips confirmed alive and communicating on the Rev 3
board. This was a purely read-only diagnostic -- no Data Flash writes were
attempted. The BQ chip's ADC was functional at this point.

**Script characteristics:** Read-only. Used `aardvark_py` with graceful
ImportError handling. Defined all INA226 registers (SBOS547B) and BQ standard
commands (SLUUCO5A). Byte helpers for big-endian (INA226) and little-endian
(BQ34Z100) conversions.

---

## 5. Phase 0B: First Data Flash Experiments (Feb 10)

*Reconstructed from git commit 34951ea (Feb 10, 2026) and script contents.*

**Goal:** Attempt to write to BQ34Z100-R2 Data Flash to begin configuring
battery parameters.

### Trial 0-2: ENTER_CAL mode for DF access (bq_init_test.py)

**Action:** Created `bq_init_test.py` (328 lines). Sent unseal keys
(0x0414, 0x3672) and full access keys (0xFFFF, 0xFFFF), then ENTER_CAL
(0x0081) sub-command to enter calibration mode for Data Flash access.
Attempted DF write to subclass 68.

**Result:** Partial success. Established the core DF write protocol:
1. Set block access via registers 0x61, 0x3E, 0x3F
2. Read 32-byte block at 0x40-0x5F
3. Modify target bytes in the buffer
4. Compute checksum: 255 - (sum of all 32 bytes) & 0xFF
5. Write checksum to 0x60 to commit

**Key discovery:** The chip auto-seals after every flash commit (checksum
write to 0x60). Must re-unseal before the next DF operation.

### Trial 0-3: ROM Mode (0x0F00) attempt

**Action:** Sent ROM Mode sub-command (0x0F00). In ROM mode, the BQ moves
from I2C address 0x55 to 0x0B and exposes a raw memory map.

**Result:** Probed address 0x0B and other candidates. Searched for known DF
patterns (0x0A 0xF0 for SC 68 data) in ROM memory rows. Attempted exit
sequence.

**Key discovery:** Writing to Control register 0x00 disrupts the DF block
access context. Subsequent DF reads return stale/wrong data. The workaround
is to use register 0x61 for wake operations when DF access is needed
(`bq_wake_for_df()` pattern). This became a critical protocol rule for all
future scripts.

---

## 6. Phase 0C: VOLTSEL Catastrophe and Chip Deaths (Feb 2026)

*Reconstructed from git commits 0d897fd and 68075b4 (Feb 18, 2026), script
docstrings (`bq_clear_voltsel.py`, `bq_recover.py`, `bq_fix_cells.py`), and
README programming procedure. The README at commit 6c85e0e (Mar 19) states
"Two chips have been permanently damaged by powering the BAT pin before
clearing VOLTSEL." The README at commit 08743e7 (same day, later) states
"Three chips were damaged this way."*

**Goal:** Configure the BQ34Z100-R2 for the Renogy RBT2425LFP battery. This
phase resulted in the permanent destruction of at least two chip ADCs.

### The VOLTSEL Problem

The BQ34Z100-R2 ships with **VOLTSEL=1 as the factory default** (bit 3 of
Pack Configuration in Data Flash subclass 64). VOLTSEL controls whether the
chip's internal 5:1 voltage divider is active on the BAT pin:

- **VOLTSEL=0:** Internal 5:1 divider active. BAT pin voltage is divided by 5
  before reaching the ADC. With the old R22=34.8kOhm divider: 3.8V / 5 =
  0.76V at the ADC -- **safe** (ADC max is 1.0V).
- **VOLTSEL=1 (factory default):** Internal divider bypassed. BAT pin voltage
  goes directly to the ADC. With the old divider: full 3.8V hits the ADC --
  **destructive** (nearly 4x over the 1.0V maximum).

The safe procedure required clearing VOLTSEL to 0 before ever connecting the
voltage divider to the BAT pin. A physical disconnect switch (SW1, SPDT slide)
was added to isolate the BAT pin during initial programming.

**Intended safe procedure (from README at commit 68075b4):**
1. SW1 OFF -- disconnect divider from BAT pin
2. Connect Aardvark adapter and apply power (REGIN gets 5V, BQ boots)
3. Run `bq_clear_voltsel.py` to verify/clear VOLTSEL to 0
4. SW1 ON -- divider output (~3.8V) now safely divided by internal 5:1
5. Run diagnostics, program battery parameters, program chemistry

### Trial 0-4: First chip ADC destruction

**Action:** Chip powered with the voltage divider connected (SW1 ON) while
VOLTSEL was still at its factory default of 1. The full ~3.8V from the old
divider reached the ADC directly, exceeding the 1.0V maximum by nearly 4x.

**Result:** FAIL. ADC permanently destroyed. Voltage() reads 0mV, Temperature
reads garbage. I2C communication still works (powered by REGIN/REG25,
independent of BAT), but all analog measurements are permanently dead.

### Trial 0-5: Second chip ADC destruction

**Action:** Attempted the SW1-based safety procedure -- program the chip with
the divider disconnected (SW1 OFF, chip running on REGIN power only), then
reconnect the divider. However, VOLTSEL=1 was still stored in the chip's
flash memory from factory defaults. When SW1 was turned ON, the ~3.8V
reached the unprotected ADC.

**Result:** FAIL. Second chip's ADC permanently destroyed by the same
mechanism. The fundamental issue: clearing VOLTSEL required successful DF
writes, but the DF write procedure was still being debugged (auto-seal
behavior, register 0x00 context disruption). Any failure to reliably clear
VOLTSEL before connecting the divider was catastrophic.

### Response: bq_clear_voltsel.py created

**Action:** Dedicated safety script written to verify and clear VOLTSEL before
the divider is ever connected. Script docstring (from commit 0d897fd):

> "VOLTSEL=1 bypasses the internal 5:1 divider and exposes the ADC to >1V,
> destroying analog front-end measurements on this board."

Features:
- Reads Pack Config from SC 64
- Checks bit 3 (VOLTSEL)
- Clears it if set, writes back, verifies
- Checksum validation on DF block reads
- Stale data detection (all-zeros check)

**README updated** with explicit warnings: "If VOLTSEL is 1 when voltage is
applied to the BAT pin, the ADC will be permanently and instantly damaged."

---

## 7. Phase 0D: Battery Programming and VD=844 Gauge Lockup (Feb 18)

*Reconstructed from git commit 0d897fd (Feb 18, 2026). Scripts
`bq_program_battery.py`, `bq_fix_vdivider.py`, `bq_fix_cells.py`,
`bq_debug_voltage.py`, and `bq_full_reset.py` were all created on this date,
documenting the progression from programming attempt to lockup to recovery.*

**Goal:** Program battery parameters on a surviving chip with VOLTSEL properly
cleared to 0.

### Trial 0-6: Program Renogy RBT2425LFP parameters (bq_program_battery.py)

**Action:** Using `bq_program_battery.py`, programmed the following parameters
for the Renogy RBT2425LFP battery pack. The Voltage Divider (VD) value was
calculated for the original R22=34.8kOhm divider:

| Parameter | Subclass | Value | Calculation |
|-----------|----------|-------|-------------|
| Design Energy | SC 48 | 64000 cWh | 640 Wh battery |
| Design Capacity | SC 48 | 25000 mAh | 25 Ah battery |
| Series Cells | SC 64 | 8 | 8S LiFePO4 |
| VOLTSEL | SC 64 bit 3 | 0 | Cleared to protect ADC |
| QMax | SC 82 | 25000 mAh | Same as design capacity |
| Voltage Divider (VD) | SC 104 | 844 | (200+34.8)/34.8 * 1000 / 8 |

The VD formula: external ratio (6.75) times 1000, divided by number of cells
(8), equals 844. This tells the gauge how to convert the BAT pin voltage back
to a per-cell voltage.

**Result:** Parameters written and committed to flash. Sent RESET (0x0041).

### Trial 0-7: Gauge lockup after VD=844 + cells=8

**Observation after RESET:**
- Voltage() = 0mV
- InternalTemp() = 0 (raw), displayed as -273C (absolute zero)
- Current() = garbled values
- VOK flag = False

**Root cause analysis:** VD=844 with cells=8 caused the gauge to calculate
per-cell voltage as approximately:

```
BAT_pin_voltage * VD / 1000 / cells = 0.76V * 844 / 1000 / 8 = ~80mV per cell
```

This was far below the gauge's internal minimum cell voltage threshold for
LiFePO4 (~2000mV per cell). The Impedance Track algorithm interpreted this
as cells that were essentially dead/missing, and entered an unrecoverable
error state. The IT algorithm refused to initialize with impossibly low
per-cell voltages.

**Significance:** The VD calculation was mathematically correct for the
hardware, but the resulting per-cell voltage at the current BAT pin level
(~0.76V with VOLTSEL=0) was too low for the IT algorithm to accept. This
is a catch-22: the VD value must be correct for accurate readings, but the
correct VD value produces per-cell voltages below the gauge's minimum.

### Trial 0-8: Restore VD to default (bq_fix_vdivider.py)

**Action:** Created `bq_fix_vdivider.py`. Restored VD from 844 back to 5000
(factory default). Script docstring: "The VD=844 value caused per-cell
voltage below gauge minimum threshold." Attempted Ralim calibration:
`newVD = (INA226_actual / BQ_reported) * currentVD`.

**Result:** FAIL. Voltage() still reads 0mV after restoring VD=5000 and
issuing RESET. The gauge lockup persists even after correcting the parameter.
The IT algorithm's error state survived the VD change.

### Trial 0-9: Cell count experiments (bq_fix_cells.py)

**Action:** Created `bq_fix_cells.py`. Set cells=1 and VD=5000 to maximize
per-cell voltage calculation. Also tried different VD values with cells=8,
using INA226 as ground truth for calibration. Script enforced VOLTSEL=0 on
all SC 64 writes with explicit safety warning: "VOLTSEL (bit 3 of Pack
Config) must NEVER be set to 1 on this board."

**Result:** FAIL. No combination of VD and cell count restored voltage
readings. The analog subsystem remained locked at 0mV regardless of
parameter values.

### Trial 0-10: PF flag investigation (bq_full_reset.py)

**Action:** Created `bq_full_reset.py` (472 lines). Script docstring:
"Theory: When VD=844 + cells=8 caused per-cell voltage ~400mV, the gauge
may have triggered a Permanent Failure (PF) condition or other safety lockout
stored in non-volatile flash that persists across resets."

Attempted:
- Read all control sub-commands for PF flags
- Scanned all known DF subclasses (0-3, 34, 36, 48-49, 51, 53-59, 64, 68,
  80-82, 104-107, 112) for anomalous values
- Multiple PF clearing sequences
- Forced battery re-detection: BAT_REMOVE + BAT_INSERT + OCV_CMD
- Cleared lifetime data (SC 80, 81)

**Result:** FAIL. No PF flags found, but voltage remained at 0mV. The lockup
appears to be in the analog measurement subsystem itself, not a software
safety latch that can be cleared via control commands.

---

## 8. Phase 0E: Recovery Campaign and Third Chip Death (Feb-Mar 2026)

*Reconstructed from scripts `bq_recover.py`, `bq_debug_voltage.py`,
`bq_test_no_tgtpower.py` (commit 0d897fd, Feb 18, 2026), `bq_comm_test.py`
(commit 6c85e0e, Mar 19, 2026), and README changes between commits 68075b4
and 08743e7.*

**Goal:** Recover the locked-up gauge or understand the failure mechanism
well enough to prevent it on future chips.

### Trial 0-11: Multi-strategy recovery (bq_recover.py)

**Action:** Created `bq_recover.py` (525 lines). Script docstring documented
the starting state: "The gauge entered a persistent error state after setting
VD=844 with cells=8, which caused impossibly low per-cell voltage
calculations. All DF parameters have been restored to defaults but the analog
subsystem remains dead: Voltage()=0, InternalTemp()=0, Current()=garbled,
VOK=False."

Five recovery strategies attempted in sequence:

1. **SHUTDOWN (0x0010) + power toggle:** Deep power-down command, then
   disconnect ALL power (supply + Aardvark USB) for 60+ seconds, reconnect.
   - Result: FAIL. Voltage still 0mV.

2. **Calibration mode entry/exit:** CAL_ENABLE + ENTER_CAL + EXIT_CAL + RESET.
   Entered calibration mode successfully, but voltage remained 0mV after exit.
   - Result: FAIL.

3. **Force Flash Update OK Voltage to 0mV:** Lowered the BAT threshold for DF
   writes from 2800mV to 0mV in SC 68. VOK flag eventually went True, but
   voltage still reads 0mV.
   - Result: FAIL. The measurement subsystem is stuck deeper than VOK.

4. **CLEAR_FULLSLEEP + IT_ENABLE + RESET:** Cleared any sleep state, forced
   IT algorithm re-initialization, then hard reset.
   - Result: FAIL.

5. **VOLTSEL toggle + power cycle:** Set VOLTSEL=0, cells=1, shutdown, full
   power cycle to force complete re-initialization.
   - Result: FAIL.

**Conclusion:** All five strategies failed. The chip's analog subsystem is
permanently locked in a non-functional state.

### Trial 0-12: Comprehensive voltage debugging (bq_debug_voltage.py)

**Action:** Created `bq_debug_voltage.py`. Read every standard command
register (0x03-0x14), every extended command (0x1C-0x3C), all control
sub-commands (status, chemistry ID, FW version), and key DF values (SC 64,
104, 68). Sent IT_ENABLE and RESET with long waits between operations.

**Result:** Every voltage-related register reads 0mV. Temperature registers
return 0 (raw) or -273C. The ADC is completely non-functional across all
measurement registers.

### Trial 0-13: Aardvark backfeed test (bq_test_no_tgtpower.py)

**Action:** Created `bq_test_no_tgtpower.py`. Tested theory that Aardvark's
3.3V target power was backfeeding through the I2C pull-ups into REG25,
corrupting the ADC voltage reference. Ran with `AA_TARGET_POWER_NONE` to let
the IC power entirely from the bench supply.

**Result:** FAIL. Same 0mV readings. Eliminated Aardvark backfeed as a cause.

### Trial 0-14: Third chip ADC destruction (between Feb 18 and Mar 19)

**Event:** A third chip's ADC was destroyed by the VOLTSEL=1 + powered divider
failure mode. Evidence: the README at commit 68075b4 (Feb 18) warned "Two
chips have been permanently damaged," but the README at commit 08743e7
(Mar 19) stated "Three chips were damaged this way."

**Significance:** Despite the SW1 safety switch, the `bq_clear_voltsel.py`
script, and documented safety procedures, the VOLTSEL trap continued to claim
chips. The fundamental problem was that the old divider output (~3.8V) was
inherently dangerous with VOLTSEL=1, and any procedural mistake -- forgetting
to disconnect SW1, failing to verify VOLTSEL was actually cleared, auto-seal
preventing the write from sticking -- could destroy the ADC instantly and
irreversibly.

### Trial 0-15: Pre-divider-change diagnostics (bq_comm_test.py, Mar 19)

**Action:** Created `bq_comm_test.py` (307 lines) with two phases:
- Phase 1: Read all standard SBS registers with formatted output
- Phase 2: Unseal, read Pack Config (SC 64), auto-clear VOLTSEL if set

Script banner: "BQ34Z100-R2 Comm Test + VOLTSEL Safety -- Rev 3 PCB"

VOLTSEL display logic: `'EXT -- DANGEROUS!' if voltsel else 'INT -- safe'`

If VOLTSEL=1 detected: "!!! VOLTSEL=1 DETECTED -- AUTO-CLEARING TO PROTECT
ADC !!!"

**Result:** Useful diagnostic tool, but could not prevent the third chip death
(which had already occurred by this point).

### Trial 0-16: Decision to change the voltage divider (Mar 19, 2026)

**Action:** After three destroyed chips and an unrecoverable gauge lockup, the
decision was made to eliminate the VOLTSEL danger at the hardware level by
changing R22 from 34.8kOhm to 6.49kOhm.

**Rationale:** With R22=6.49kOhm, the divider ratio becomes 31.82:1, producing
less than 1V at the BAT pin across the entire 20-30V operating range. This
makes VOLTSEL=1 (factory default) completely safe -- even with the internal
5:1 divider bypassed, the ADC never sees more than ~0.94V. The VOLTSEL safety
dance (SW1 disconnect, clear-before-connect, verify-before-enable) becomes
unnecessary.

**VOLTSEL policy reversal:** All BQ scripts were updated in git commit
08743e7 (Mar 19, 10:39 PM):
- `bq_comm_test.py`: Changed from auto-clearing VOLTSEL to auto-setting it.
  "VOLTSEL=0 detected -- setting to 1 for best ADC resolution."
- `bq_clear_voltsel.py`: Marked as legacy with warning: "OBSOLETE for Rev 4+
  boards."
- `pcb_diagnostics.py`: VOLTSEL auto-correction logic inverted.
- README: VOLTSEL=1 described as "correct and preferred."

**New Phase 3 added to bq_comm_test.py:** A `reset_and_power_cycle()` function
was added because of an earlier hard-won lesson: "Flash commits do NOT update
running firmware. A RESET is required after changing Pack Config so the new
values take effect."

---

## 9. Phase 1: Voltage Divider Retrofit (Mar 19)

**Goal:** Protect the BQ BAT pin ADC by reducing the divider output voltage.

### Trial 1: Swap R22 from 34.8kOhm to 6.49kOhm

**Action:** Physically replaced R22 on the Rev 3 board.

**Measurements (multimeter on BAT pin):**
- 25V input: 0.784V (expected 0.786V) -- 0.3% error
- 30V input: 0.935V (expected 0.943V) -- 0.8% error
- 20V input: 0.631V (expected 0.629V) -- 0.3% error

**Result:** PASS. Divider working correctly. BAT pin stays safely under 1V
across the full 20-30V operating range. The existing 2.0V zener diode
provides additional overvoltage protection.

---

## 10. Phase 2: First Fresh Chip (Defective)

**Goal:** Bring up a fresh BQ34Z100-R2 on the board with the new safe divider.

### Trial 2: Solder fresh chip and run diagnostics

**Action:** Fresh BQ34Z100-R2 soldered onto Rev 3 board. Power supply at 20V.

**Result:** FAIL. INA226 (0x40) ACKed immediately. BQ (0x55) NACKed on all
transactions. Completely unresponsive on I2C.

### Trial 3: Enable voltage divider and retry

**Action:** Ensured divider was active so BAT pin received ~0.63V at 20V.

**Result:** FAIL. Still NACKing.

### Trial 4: Verify power pins with multimeter

**Measurements:**
- REGIN (Pin 6) = 5.0V (correct)
- REG25 (Pin 7) = 2.545V (internal LDO alive and regulating)
- SDA idle = 3.455V, SCL idle = 3.456V

**Theory proposed:** 3.3V I2C pull-ups are 0.8V above BQ's 2.5V REG25 rail,
possibly causing internal ESD clamp diodes to conduct and preventing
communication.

**Counter-evidence:** Previous chips on the same board with identical pull-ups
communicated fine. Theory WEAKENED.

### Trial 5: Run bq_calibrate.py

**Action:** Attempted CC calibration script.

**Result:** FAIL. All data flash reads failed. Chip completely unresponsive.

### Trial 6: Review TI reference schematic

**Discovery:** TI reference design uses no pull-ups on the BQ side -- only
AZ23C5V6-7 ESD zener pairs on SDA/SCL. Pull-ups are expected from host.
Our 10kOhm pull-ups to 3.3V are within spec.

### Trial 7: Disable Aardvark target power

**Action:** Turned off Aardvark's switchable 2.2kOhm internal pull-ups
(leaving only the board's 10kOhm).

**Result:** FAIL. Still NACKing.

### Trial 8: Oscilloscope analysis (Rigol DS1054)

**Action:** Probed SDA and SCL during I2C transactions.

**Observations:**
- Clean square waves from 0ms to ~1.66ms (the scan burst)
- Signals pulling cleanly to ~0V (bus electrically healthy)
- Targeted 0x55-only transaction: SDA HIGH during 9th clock pulse = confirmed NACK

**Result:** BQ is definitively NACKing. Not even attempting a partial ACK.
Bus integrity confirmed good.

### Trial 9: First solder reflow

**Action:** Reflowed BQ chip pins with soldering iron.

**Result:** FAIL. Still NACKing.

### Trial 10: Swap I2C pull-ups from 4.7kOhm to 10kOhm

**Action:** Changed R5/R6 from 4.7kOhm to 10kOhm per BQ34Z100-R2 datasheet
recommendations.

**Result:** FAIL. Still NACKing. Pull-up resistance is not the problem.

### Trial 11: Reduce I2C clock to 10kHz

**Action:** Changed Aardvark from 100kHz to 10kHz.

**Result:** FAIL. BQ still NACKs. INA226 works fine at 10kHz, confirming the
bus is clean at both speeds.

### Trial 12: Feed 2V directly to BAT pin

**Action:** Applied 2V from bench supply directly to BAT pin, bypassing the
voltage divider entirely.

**Result:** FAIL. Still NACKing.

**Significance:** ELIMINATED BAT voltage and UVLO as root causes. The chip's
I2C interface runs from REGIN/REG25, independent of BAT.

### Trial 13: Heavy reflow with flux

**Action:** Thorough reflow of all BQ pins with generous flux application.

**Result:** FAIL. Still NACKing.

### Trial 14: Run every BQ script exhaustively

**Scripts run:** `bq_comm_test.py`, `bq_calibrate.py`, `bq_program_battery.py`,
`bq_program_chemistry.py`, `bq_recover.py`, `bq_debug_voltage.py`

**Result:** FAIL. Every script failed. Zero response from chip.

**Conclusion:** This chip has a defective I2C interface. Dead on arrival.

### Variables Eliminated for First Fresh Chip

| Variable | Tested | Result |
|----------|--------|--------|
| I2C clock speed | 10kHz and 100kHz | No change |
| Pull-up resistance | 4.7kOhm and 10kOhm | No change |
| Aardvark target power | On and off | No change |
| BAT pin voltage | 0.63V, 0.94V, 2.0V direct | No change |
| Solder joints | Reflowed twice (with and without flux) | No change |
| REG25 bypass cap | Present (1uF) | Confirmed stable |
| REG25 output | 2.545V measured | Normal |
| REGIN supply | 5.0V measured | Normal |

---

## 11. Phase 3: Old Chip Cross-Validation

**Goal:** Confirm the board itself is functional by testing with a known chip.

### Trial 15: Swap in old (previously damaged) chip

**Action:** Soldered one of the original chips (dead ADC from prior 3.8V
incident) onto the board with the new 6.49kOhm divider.

**Result:** ACKed immediately at 0x55. Board, pull-ups, divider, and I2C bus
all confirmed working.

**Readings from old chip:**
- Pack Config = 0x0159 (VOLTSEL=EXT, RSNS=LOW) -- configured from past sessions
- CC Gain/Delta = calibrated for 5mOhm sense resistor
- Voltage() = 0mV (ADC dead from prior VOLTSEL incident)
- Temperature = 343.5C (garbage -- ADC dead)

**Significance:** Proved the first fresh chip was simply defective. The board
hardware is fine. BAT voltage is irrelevant to I2C -- communication runs
entirely off REGIN/REG25.

---

## 12. Phase 4: Second Fresh Chip (Chip 1G)

**Goal:** Try another fresh chip, learn from the defective one.

### Trial 16: Solder second fresh chip

**Action:** Another fresh BQ34Z100-R2 soldered onto the board.

**Result:** NACKing again. Two fresh chips in a row failing to respond.

**Theory proposed:** Fresh chips may require a minimum BAT voltage for their
very first I2C initialization, even though configured chips (which first
booted with the old 34.8kOhm divider where BAT saw ~3.8V) work at any
voltage thereafter.

**Proposed fix:** Temporarily feed 3-4V to BAT for initial programming. With
VOLTSEL=0 (factory default), the internal 5:1 divider means the ADC would
see 0.6-0.8V -- safe.

**Decision:** Deferred. Board left powered while investigating.

### Trial 17: Surprise ACK after ~20 minute warm-up

**Action:** Board had been sitting powered at 30V for ~20 minutes. Went to
capture oscilloscope photo of the NACK waveform.

**Observation:** On the oscilloscope, SDA was LOW during the 9th clock cycle
-- that is an ACK, not a NACK!

**Result:** I2C scan confirmed 0x55 responding. The chip came alive
spontaneously after extended powered warm-up time.

**Significance:** Fresh BQ34Z100-R2 chips may need 15-20 minutes of powered
soak time before their I2C interface becomes active. This is undocumented
in the TI datasheet.

### Trial 18: Immediate diagnostics on newly responding chip

**Readings:**
- Pack Config = 0x41D9 (factory defaults: RSNS=HIGH, VOLTSEL=EXT)
- Voltage() = 33mV (non-zero! ADC is alive and measuring!)
- CC Gain/Delta = uninitialized values

**Action:** Wrote two changes to Data Flash:
1. RSNS: HIGH -> LOW (Pack Config 0x41D9 -> 0x4159) for low-side sensing
2. CC Calibration: Gain=0.9536, Delta=1,135,489 for 5mOhm sense resistor

Then sent RESET command (0x0041).

**Result after RESET:** Voltage dropped to 0mV. Gauge locked up in the same
pattern as the old dead chips.

**Significance:** The configuration write + RESET killed the gauge. The 33mV
reading on virgin boot was the only functional measurement window.

**Discovery:** VOLTSEL=1 (external divider bypass) was already the factory
default -- previously assumed to be VOLTSEL=0.

### Trial 19: Monitor BQ during voltage sweep

**Action:** INA226 and BQ monitored side-by-side while sweeping supply
20V -> 30V -> 20V.

**Results:**
- INA226: Tracked perfectly (20,000 -> 30,015 -> 20,000 mV)
- BQ: Locked at constant 9mV -- not tracking supply changes at all

**Result:** FAIL. BQ ADC is completely unresponsive to voltage changes.

### Trial 20: Lower Flash Update OK Voltage to 0mV

**Action:** Wrote Flash Update OK Voltage from 2800mV down to 0mV in
Data Flash subclass 68, to try to get the VOK (Voltage OK) flag set.

**Result:** VOK eventually went True after sending IT_ENABLE (0x0021), but
Voltage() still reads 0mV. The measurement subsystem is stuck at a deeper
level than the VOK flag.

**Discussion about raising supply to 40V:** Considered but rejected -- INA226
has a 36V maximum bus voltage rating and would be damaged.

---

## 13. Phase 5: Overnight Recovery Attempts

**Goal:** Attempt full recovery of Chip 1G after overnight power-off.

### Trial 21: Check chip after overnight power-off

**Result:** Both INA226 and BQ ACKing. Gauge lockup persists:
- Voltage() = 0mV
- PackVoltage() = 1mV
- InternalTemp = -273C (absolute zero -- indicates broken ADC)

**Research discovery:** BQ34Z100-R2 BAT pin ADC input range is 0.05V to 1.0V.
Optimal target is ~0.9V. The divider puts BAT at 0.94V at 30V -- right in
the sweet spot. The hardware design is correct.

### Trial 22: Four-strategy recovery attempt (bq_restore_factory.py)

**Strategy 1:** Restore Pack Config to factory 0x41D9 (undo RSNS write) + RESET.
- **Result:** FAIL. Voltage still 0mV.

**Strategy 2:** Also restore CC Gain/Delta to 10mOhm factory defaults + RESET.
- **Result:** FAIL. Voltage still 0mV.

**Strategy 3:** SHUTDOWN (0x0010) + full Aardvark power cycle (off 10 seconds,
then back on) to force complete power drain.
- **Result:** FAIL. Voltage still 0mV.

**Strategy 4:** IT_ENABLE (0x0021) to explicitly kick the Impedance Track
algorithm, then wait 10 seconds.
- **Result:** FAIL. VOK flipped to True (Control Status 0x0015 -> 0x0013),
  but Voltage still 0mV.

**Conclusion:** All four recovery strategies failed. The script's final output
stated: "ALL RECOVERY STRATEGIES FAILED. Factory defaults restored but IT
algorithm still won't initialize. This chip's analog subsystem may be
permanently stuck."

---

## 14. Phase 6: Third Fresh Chip -- Incremental Isolation

**Goal:** Use a fresh chip with a carefully staged bringup to identify exactly
which operation kills the gauge.

### Trial 23: Fresh chip with incremental bringup (bq_fresh_chip.py)

**Action:** Soldered on another fresh chip. This one ACKed immediately with
no warm-up delay.

**Initial reading:** Voltage() = 38mV (ADC alive, similar to Chip 1G's
initial 33mV).

### Trial 24: Stage 1 -- Bare RESET with zero DF writes

**Action:** Sent RESET command (0x0041) without writing anything to Data Flash.

**Result:** Voltage went from 43mV to 26mV (still reading -- just settling
after reboot).

**Significance:** PROVED the 6.49kOhm divider is compatible with the BQ chip.
The chip survives a RESET at 0.94V BAT with factory defaults intact. The
divider is not the problem.

### Trial 25: Stage 2 -- RSNS fix only + RESET

**Action:** Changed only RSNS from HIGH to LOW in Pack Config
(0x41D9 -> 0x4159), committed to flash, then RESET.

**Result:** Voltage went from 35mV to 26mV. Still measuring.

**Conclusion:** RSNS change is NOT the culprit. The chip survives this
modification at low BAT voltage.

### Trial 26: Stage 3 -- CC Calibration + RESET (THE KILLER)

**Action:** Wrote CC Gain = 0.9536 and CC Delta = 1,135,489 (correct values
for the 5mOhm sense resistor R26), committed to flash, then RESET.

**Result:** Voltage went from 34mV to 0mV. Gauge dead.

**ROOT CAUSE IDENTIFIED:** CC calibration values for the 5mOhm sense resistor
specifically kill the IT algorithm when BAT voltage is this low (~0.94V).
The IT algorithm cannot re-bootstrap with these parameters after a RESET.

### Trial 27: Immediate recovery -- restore virgin CC values

**Action:** Immediately restored the pre-calibration CC Gain/Delta values
(the uninitialized/factory values), committed to flash, then RESET.

**Result:** Voltage came back to 26mV! Chip recovered!

**Significance:** CONFIRMED that:
1. CC calibration values are the specific cause of the lockup
2. The lockup is REVERSIBLE if you restore the old values quickly
3. The IT algorithm can re-bootstrap with factory CC values at low BAT

### Trial 28: VD (Voltage Divider) calibration attempt

**Action:** Tried to calibrate the BQ's internal Voltage Divider register using
the Ralim method: `newVD = (INA226_actual / BQ_reported) * currentVD`.

**Result:** BQ reads 36mV for an actual 25V pack (INA226 confirms 24,995mV).
The calculated VD would be 3,471,527 -- far beyond the u16 maximum of 65,535.

**Mystery discovered:** The ADC reads ~40mV for ~786mV physically present on
the BAT pin. This is an ~18x discrepancy that cannot be corrected with the
VD register.

### Trial 29: VOLTSEL toggle test

**Action:** Toggled VOLTSEL between 0 (internal 5:1 divider active) and 1
(bypassed) to measure the ADC response change.

**Results:**
- VOLTSEL=1 (bypassed): reads 43mV
- VOLTSEL=0 (5:1 divider): reads 27mV
- Ratio: 1.6x

**Expected ratio:** 5.0x (the internal divider is 5:1).

**Significance:** The ADC is not behaving according to the datasheet. The
internal divider appears to provide the wrong scaling ratio.

### Trial 30: Physical BAT pin measurement vs ADC reading

**Action:** Measured BAT pin with multimeter while reading ADC.

**Results:**
- Multimeter on BAT pin: 0.787V
- BQ Voltage() register: 44mV
- Discrepancy: 787 / 44 = 17.9x

**Conclusion:** 787mV is physically present on the BAT pin, but the ADC only
reports 44mV. An ~18x error with no known explanation. All obvious causes
(divider loading, pin mapping, power supply, ground offset) have been
eliminated.

---

## 15. Phase 7: Multi-Chip Rotation and ADC Mystery

**Goal:** Investigate the ADC mystery across different chips.

### Trial 31: Voltage sweep monitoring on Chip 1G

**Action:** Monitor BQ and INA226 side-by-side while sweeping 20V -> 30V -> 20V.

**Results:**
- INA226: Tracked perfectly at every voltage step
- BQ: Reads constant 9mV regardless of supply voltage -- completely static

**ADC degradation timeline for Chip 1G (across all sessions):**
- Virgin boot: 33mV
- After RSNS fix: 35mV
- After CC cal kill + restore: 26-43mV
- After multiple resets/writes: 9mV
- Final: 0mV (locked)

### Trial 32: Check SRP/SRN pins (sense resistor connections)

**Action:** Measured voltage on sense resistor pins with multimeter.

**Results:**
- SRP = 1.2mV
- SRN = 1.1mV
- Differential: ~0.1mV (essentially zero -- no load current flowing)

**Result:** Sense resistor connections appear normal. Not relevant to the
voltage ADC issue.

### Trial 33: Swap to Chip 2G (previously configured chip)

**Action:** Soldered on Chip 2G (one of the old configured chips with known
dead ADC).

**Result:** FAIL. NACKing on I2C. Would not respond.

**Assessment:** Likely bad solder joints from repeated soldering and
desoldering cycles. The footprint pads may be degraded.

### Trial 34: Extended polling on Chip 2G

**Action:** Multiple power cycles, 2+ minutes of continuous polling.

**Result:** FAIL. Still NACKing after prolonged attempts. Left to sit
unpowered for several hours.

---

## 16. Phase 8: Final Recovery Attempts (Chips 2G and 1G)

### Trial 35: Chip 2G after extended rest

**Action:** Board powered at 20V after letting Chip 2G sit for hours.

**Result:** FAIL. Still NACKing after 60+ seconds of polling. Extended to
several minutes -- still NACKing.

**Conclusion:** Chip 2G's I2C is dead, likely from solder joint damage
during repeated swaps.

### Trial 36: Swap back to Chip 1G with reflow

**Action:** Chip 1G resoldered onto the board with careful reflow.

**Initial result:** NACKing (solder joint issue from repeated swaps).

**After reflow:** ACKed. Reads 8mV voltage (still stuck from prior sessions).

### Trial 37: Comprehensive "kitchen sink" recovery (bq_kitchen_sink.py)

**Script ran all 5 phases:**

**Phase 1 -- Factory defaults restoration:**
- Restored CC Gain/Delta to 10mOhm defaults (0.4768 / 567744.5)
- Restored Pack Config to 0x41D9
- Sent RESET
- Result: Still 0mV

**Phase 2 -- BAT pin loading investigation:**
- 20 rapid-fire voltage reads to check for variation
- Read ControlStatus and OperationStatus
- Result: All reads return 0mV, no variation

**Phase 3 -- VD + cell count experiments:**
- Config A: VD=MAX, Cells=1, VOLTSEL=1 -> 0mV
- Config B: VD=5000, Cells=1, VOLTSEL=0 -> 0mV
- Config C: VD=MAX, Cells=1, VOLTSEL=0 -> 0mV
- Config D: Restore VD=5000, Cells=1, VOLTSEL=1 -> 0mV
- Result: No configuration recovers the voltage reading

**Phase 4 -- Voltage tracking test:**
- 10 samples of INA226 vs BQ while supply changes
- INA226 tracks supply, BQ locked at 0mV
- Result: BQ completely unresponsive to voltage changes

**Phase 5 -- Final state dump:**
- All DF values restored to known-good
- Voltage still 0mV
- Result: FAIL. Chip 1G is unrecoverable.

**Also tried:**
- SHUTDOWN + full power cycle
- IT_ENABLE (0x0021)
- CAL_ENABLE / EXIT_CAL (calibration mode entry/exit)
- CLEAR_FULLSLEEP

**Result:** ALL failed. Chip 1G's ADC is in an unrecoverable lockup state
after too many kill/restore cycles.

### Theory: Divider loading collapses BAT pin voltage

**Proposed:** The chip's own current draw through the BAT pin input impedance
might collapse the high-impedance divider output from ~787mV to ~40mV.

**ELIMINATED:** The TLV271CW5-7 op-amp is configured as a unity-gain voltage
follower between the divider junction and the BAT pin. It drives BAT with
low output impedance. The chip's input current cannot collapse a buffered
source.

### Trial 38: Verify complete circuit architecture

**Confirmed from KiCad schematic:**
- TLV271 non-inverting input (+) connected to divider junction
- TLV271 output connected to VTRANS net which connects to BQ BAT pin
- TLV271 inverting input (-) connected to output (unity gain feedback)
- TLV271 V+ from ENABLE net (REG25 = 2.5V), always powered
- Pin 4 = BAT (ADC input only)
- Pin 6 = REGIN (power input, measured 5.033V)
- Pin 7 = REG25 (2.5V LDO output, measured 2.551V)
- Pin 2 = VEN (tied to REG25, always enabled)
- Pin mapping matches TI BQ34Z100-R2 datasheet exactly

### Trial 39: Systematic theory elimination

| Theory | Evidence | Status |
|--------|----------|--------|
| REGIN underpowered | Measured 5.033V | ELIMINATED |
| REG25 not regulating | Measured 2.551V | ELIMINATED |
| Divider loading | Op-amp buffer provides low impedance | ELIMINATED |
| KiCad pin mapping error | Matches TI datasheet | ELIMINATED |
| VEN timing issue | VEN tied to REG25, always high | ELIMINATED |
| VSS ground offset | 5mV on VSS, essentially ground | ELIMINATED |

**Conclusion:** Every measurable/testable theory has been eliminated. The
~18x ADC discrepancy remains unexplained.

---

## 17. Phase 9: LED Test and INA226 Adoption

### Trial 40: Send All-LEDs-ON command (0x0030)

**Action:** Wrote Control sub-command 0x0030 (All LEDs ON) to Chip 1G.

**Result:** Write ACKed, but no LEDs lit up.

**Investigation:** Read LED Config byte from Data Flash subclass 64, offset 5.

**Finding:** LED Config = 0x00 (No LED mode). With mode = 0, the All LEDs ON
command has no effect because the LED driver is disabled entirely.

**Attempted fix:** Tried to write LED Config = 0x0A (mode 2: Four LEDs direct,
LED_ON bit = 1 for always display).

**Result:** FAIL. Data Flash writes are silently rejected because the chip's
ADC reads BAT as 0mV, which is below the Flash Update OK Voltage threshold
(2800mV by default, even after lowering it to 0mV in earlier trials, the
running firmware never loaded the new value due to ADC lockup).

**Conclusion:** BQ cannot drive LEDs in its current state. LED Config is stuck
at 0x00 and cannot be changed. LED driving requires separate hardware
(MCU like ATtiny412/85 or I2C GPIO expander).

### Trial 41: INA226 fuel gauge validation

**Action:** Ran `ina226_fuel_gauge.py` with full voltage sweep 20V -> 30V -> 20V.

**Results:**
- Bus voltage locked accurately at each set point (20,000mV, 25,000mV, 30,000mV)
- SOC correctly mapped the LFP discharge curve:
  - 20V = 0% SOC
  - 25V = 15.5% SOC
  - 29.9V = 100% SOC
- Coulomb counter initialized from voltage-based SOC estimate
- Peukert correction and charge termination detection working
- BMS warning thresholds functional

**Decision:** INA226 adopted as primary fuel gauge. BQ34Z100-R2 placed on
hold pending acquisition of TI ecosystem tools (EV2300/EV2400 adapter +
Battery Management Studio software) and posting the ADC mystery to TI E2E
support forums.

---

## 18. Theory Tracker

Complete list of every theory proposed and its final status:

| # | Theory | Phase | Status | Evidence |
|---|--------|-------|--------|----------|
| 1 | VOLTSEL=1 + old divider destroys ADC | 0C | **CONFIRMED (3 chips)** | Three chips permanently damaged by ~3.8V on ADC (max 1.0V) |
| 2 | VD=844 + cells=8 causes IT algorithm lockup | 0D | **CONFIRMED** | Per-cell voltage ~80mV triggered unrecoverable error state |
| 3 | Writing to Control reg 0x00 disrupts DF context | 0B | **CONFIRMED** | DF reads return stale data after 0x00 write; use 0x61 instead |
| 4 | Auto-seal after flash commit blocks subsequent writes | 0B | **CONFIRMED** | Must re-unseal after every checksum write to 0x60 |
| 5 | 3.3V I2C pull-ups too high for 2.5V REG25 | 2 | ELIMINATED | Old chips worked with identical pull-ups |
| 6 | Pull-up resistance too low (4.7kOhm) | 2 | ELIMINATED | 10kOhm also NACKed on defective chip; old chip ACKed with both |
| 7 | UVLO from low BAT voltage prevents I2C | 2 | ELIMINATED | 2V applied directly to BAT, still NACKed; old chips ACK at 0mV BAT |
| 8 | REG25 bypass cap missing/oscillating | 2 | ELIMINATED | 1uF present, REG25 stable at 2.55V |
| 9 | Fresh chip needs high BAT for first boot | 2,4 | PARTIALLY SUPPORTED | 2 fresh chips NACKed initially; one ACKed after ~20 min warm-up; 2V direct didn't help first one |
| 10 | First fresh chip is defective | 2,3 | **CONFIRMED** | All other chips ACK on same board; this one never ACKed under any conditions |
| 11 | CC calibration kills IT algorithm at low BAT | 6 | **CONFIRMED, REPRODUCIBLE** | Incremental test: bare RESET survives, RSNS fix survives, CC cal kills. Reversible when caught early. |
| 12 | Divider loading collapses BAT voltage | 8 | ELIMINATED | Op-amp buffer provides low-impedance drive to BAT pin |
| 13 | REGIN underpowered | 8 | ELIMINATED | Measured 5.033V |
| 14 | REG25 not regulating | 8 | ELIMINATED | Measured 2.551V |
| 15 | KiCad pin mapping wrong | 8 | ELIMINATED | Verified against TI datasheet, all pins correct |
| 16 | VEN timing issue | 8 | ELIMINATED | VEN tied to REG25, always high when powered |
| 17 | VSS ground offset | 8 | ELIMINATED | 5mV on VSS, negligible |
| 18 | Aardvark 3.3V backfeed corrupts ADC reference | 0E | ELIMINATED | `bq_test_no_tgtpower.py` ran without target power, same results |
| 19 | External thermistor pin (TS) causes ADC lockup | 7 | ELIMINATED | `bq_temps_test.py` toggled TEMPS bit, no change in voltage reading |
| 20 | PF (Permanent Failure) flag latched from low voltage | 0D | ELIMINATED | `bq_full_reset.py` found no PF flags; clearing sequences had no effect |
| 21 | ADC reads ~40mV for ~787mV BAT input (18x error) | 6,7 | **UNSOLVED** | Physical measurement confirms 787mV on pin; ADC reports 44mV; no known explanation; all testable theories eliminated |

---

## 19. Final Chip Status

| Chip | I2C | ADC | Destroyed By | DF Writes | LEDs | Usability |
|------|-----|-----|--------------|-----------|------|-----------|
| Old Chip A | ACKs | Dead (0mV) | VOLTSEL=1 + 3.8V | Blocked | N/A | Dead |
| Old Chip B | ACKs | Dead (0mV) | VOLTSEL=1 + 3.8V | Blocked | N/A | Dead |
| Old Chip C | ACKs | Dead (0mV) | VOLTSEL=1 + VD=844 | Blocked | N/A | Dead |
| First fresh | Never ACKed | Unknown | Defective (DOA) | N/A | N/A | Dead |
| Chip 1G | ACKs | Locked at 0mV | CC cal at low BAT | Blocked (BAT < 2800mV) | Cannot enable (LED Config stuck at 0x00) | Dead |
| Chip 2G | NACKing | Unknown | Solder damage | N/A | N/A | Dead |
| Chip 1N | Untested | Untested | -- | Untested | Untested | Reserved for TI tools |
| Chip 2N | Untested | Untested | -- | Untested | Untested | Reserved for TI tools |

---

## 20. Scripts Written

Every script created during the entire debugging campaign, in chronological
order of creation:

### Pre-divider-change scripts (Feb-Mar 2026, R22=34.8kOhm era)

| Script | Date | Purpose | Key Finding |
|--------|------|---------|-------------|
| `pcb_diagnostics.py` | Feb 6 | Original all-in-one diagnostic (INA226 + BQ) | Both chips alive and communicating |
| `bq_init_test.py` | Feb 10 | First DF write experiments (ENTER_CAL + ROM Mode) | Discovered auto-seal, 0x00 context disruption |
| `bq_program_battery.py` | Feb 18 | Program Renogy battery params (VD=844, cells=8) | VD=844 caused gauge lockup |
| `bq_calibrate.py` | Feb 18 | CC Gain/Delta calibration for 5mOhm sense | **DO NOT USE** -- kills gauge at low BAT |
| `bq_clear_voltsel.py` | Feb 18 | Dedicated VOLTSEL=0 enforcer (Rev 2-3 safety) | VOLTSEL clearing works when DF writes succeed |
| `bq_debug_voltage.py` | Feb 18 | Deep voltage diagnostic (all registers) | All voltage registers read 0mV |
| `bq_fix_vdivider.py` | Feb 18 | VD restore to 5000 + Ralim calibration | Restoring VD alone doesn't recover gauge |
| `bq_fix_cells.py` | Feb 18 | Cell count + VD experiments | No parameter combo recovers locked gauge |
| `bq_full_reset.py` | Feb 18 | PF flag clearing, full DF scan | No PF flags found |
| `bq_recover.py` | Feb 18 | 5-strategy analog recovery | All strategies failed |
| `bq_test_no_tgtpower.py` | Feb 18 | Test without Aardvark 3.3V target power | Eliminated backfeed theory |
| `bq_write_test.py` | Feb 18 | I2C write behavior investigation | Tested register write patterns |
| `bq_program_chemistry.py` | Feb 18 | 6-phase LiFePO4 chemistry programming (1136 lines) | Never fully executed |
| `ina226_monitor.py` | Feb 18 | Real-time tkinter GUI with rolling plots + CSV logging | INA226 confirmed working perfectly |

### Post-divider-change scripts (Mar 19+, R22=6.49kOhm era)

| Script | Purpose | Key Finding |
|--------|---------|-------------|
| `i2c_scan.py` | Full I2C bus scan (0x03-0x77) | Confirmed which chips ACK/NACK |
| `bq_comm_test.py` | 3-phase comm check + Pack Config auto-correct | VOLTSEL/RSNS verification works |
| `ina226_comm_test.py` | INA226 identity + register check | Confirmed INA226 working correctly |
| `bq_fresh_chip.py` | Incremental staged bringup (probe/reset/rsns/cc/vd) | **Identified CC cal as the killer** |
| `bq_restore_factory.py` | 4-strategy factory default restore | All strategies failed |
| `bq_kitchen_sink.py` | 5-phase comprehensive "throw everything at it" | All phases failed on Chip 1G |
| `bq_fix_packconfig.py` | Full DF dump + Pack Config bit decode | Useful for diagnostics |
| `bq_cal_mode_test.py` | Enter CAL mode for raw ADC values | Raw ADC also reads ~0mV |
| `bq_voltsel_toggle_test.py` | Toggle VOLTSEL, measure 5:1 ratio | Got 1.6x instead of 5x |
| `bq_temps_test.py` | Toggle TEMPS bit (internal vs external thermistor) | No effect on voltage reading |
| `bq_readonly_test.py` | Pure read-only linearity test (zero writes) | Used for safe Chip 2G monitoring |
| `bq_ina_monitor.py` | Side-by-side BQ + INA226 monitor | Confirmed BQ doesn't track, INA226 does |
| `bq_led_test.py` | LED Config test + All-LEDs-ON command | Confirmed LED Config=0x00, BQ cannot drive LEDs |
| `ina226_fuel_gauge.py` | Complete INA226 fuel gauge with coulomb counting | **PRIMARY fuel gauge** -- validated and working |

---

## 21. Lessons Learned

### Confirmed Root Causes (Pre-Divider Era)

1. **VOLTSEL=1 + old divider = instant ADC death.** The factory default
   VOLTSEL=1 bypasses the internal 5:1 divider. With R22=34.8kOhm, the BAT
   pin saw ~3.8V, which went directly to the ADC (max 1.0V). Three chips
   were destroyed this way. No amount of software safety procedures (SW1
   switch, clear-before-connect scripts) could reliably prevent procedural
   errors that led to destruction.

2. **VD=844 + cells=8 locks up the IT algorithm.** The mathematically correct
   VD value for the old divider, combined with 8 cells, produced per-cell
   voltage calculations of ~80mV -- far below the gauge's minimum threshold.
   The IT algorithm entered an unrecoverable error state that survived
   parameter restoration and power cycling.

3. **Auto-seal after flash commit.** Every write to the checksum register
   (0x60) causes the chip to re-seal itself. Scripts must re-unseal before
   each subsequent DF operation.

4. **Control register 0x00 disrupts DF block context.** Writing to register
   0x00 (even for wake purposes) corrupts the block access state. Use
   register 0x61 for wake operations during DF access (`bq_wake_for_df()`).

5. **Flash commits do NOT update running firmware.** A RESET command (0x0041)
   is required after DF changes for the new values to take effect in the
   running gauge algorithm.

### Confirmed Root Causes (Post-Divider Era)

6. **CC calibration kills the IT algorithm at low BAT voltages.** Writing
   CC Gain/Delta values for the 5mOhm sense resistor and then issuing RESET
   causes the Impedance Track algorithm to fail to re-bootstrap when BAT is
   under ~1V. The factory 10mOhm defaults do not cause this problem.
   The lockup is reversible if factory values are restored before the chip
   enters a permanent error state.

7. **Fresh BQ chips may need 15-20 minutes of powered warm-up** before their
   I2C interface becomes active. This is not documented in the TI datasheet.

8. **Repeated soldering/desoldering damages footprint pads and joints.**
   After 5+ swap cycles, chips that previously ACKed begin NACKing due to
   degraded solder connections.

### Unsolved Mystery

The ADC reads ~40mV for a physically measured ~787mV on the BAT pin. This
18x discrepancy cannot be explained by:
- Divider loading (op-amp buffer eliminates this)
- Pin mapping errors (verified against datasheet)
- Power supply issues (REGIN and REG25 both nominal)
- Ground offsets (VSS measured at 5mV)
- VOLTSEL setting (toggling gives 1.6x not 5x ratio)
- Thermistor configuration (toggling TEMPS has no effect)
- Aardvark power backfeed (tested without target power)

This mystery requires TI's own tools (EV2300/EV2400 + Battery Management
Studio) or a response from TI E2E support forums to resolve.

### Recommendations for Future Attempts

1. **Use TI ecosystem tools.** The BQ34Z100-R2 is designed to be configured
   with TI's EV2300/EV2400 adapter and Battery Management Studio software.
   Raw I2C configuration has proven unreliable.

2. **Never write CC calibration at low BAT.** If configuring via raw I2C,
   ensure BAT > 2.8V before writing CC Gain/Delta and issuing RESET.

3. **Read first, write never (initially).** On a fresh chip, run the `probe`
   stage of `bq_fresh_chip.py` to capture all factory defaults before making
   any changes.

4. **Minimize solder cycles.** Use a socket or test fixture if further chip
   swaps are needed. The QFN footprint pads degrade with repeated
   rework.

5. **Two fresh chips remain (1N, 2N).** Save these for when TI tools are
   available.

6. **The INA226 works.** For immediate needs, the INA226-based fuel gauge
   provides accurate voltage, current, and coulomb counting. It lacks
   standalone LED driving, but an ATtiny412 or I2C GPIO expander can fill
   that gap.
