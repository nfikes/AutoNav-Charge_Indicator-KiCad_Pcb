# BQ34Z100-R2 Debugging History

Complete record of every trial performed to diagnose and recover the
BQ34Z100-R2 fuel gauge on the AutoNav Charge Indicator board (Rev 3/4).
Covers the period from initial bringup through the decision to adopt the
INA226 as the primary fuel gauge.

---

## Table of Contents

1. [Background](#1-background)
2. [Hardware Changes](#2-hardware-changes)
3. [Chip Inventory](#3-chip-inventory)
4. [Phase 1: Voltage Divider Retrofit](#4-phase-1-voltage-divider-retrofit)
5. [Phase 2: First Fresh Chip (Defective)](#5-phase-2-first-fresh-chip-defective)
6. [Phase 3: Old Chip Cross-Validation](#6-phase-3-old-chip-cross-validation)
7. [Phase 4: Second Fresh Chip (Chip 1G)](#7-phase-4-second-fresh-chip-chip-1g)
8. [Phase 5: Overnight Recovery Attempts](#8-phase-5-overnight-recovery-attempts)
9. [Phase 6: Third Fresh Chip -- Incremental Isolation](#9-phase-6-third-fresh-chip-incremental-isolation)
10. [Phase 7: Multi-Chip Rotation and ADC Mystery](#10-phase-7-multi-chip-rotation-and-adc-mystery)
11. [Phase 8: Final Recovery Attempts (Chips 2G and 1G)](#11-phase-8-final-recovery-attempts-chips-2g-and-1g)
12. [Phase 9: LED Test and INA226 Adoption](#12-phase-9-led-test-and-ina226-adoption)
13. [Theory Tracker](#13-theory-tracker)
14. [Final Chip Status](#14-final-chip-status)
15. [Scripts Written](#15-scripts-written)
16. [Lessons Learned](#16-lessons-learned)

---

## 1. Background

The BQ34Z100-R2 is a battery fuel gauge IC from Texas Instruments, used on
the AutoNav Charge Indicator PCB to measure pack voltage, current, and state
of charge for a Renogy RBT2425LFP battery (24V 25Ah LiFePO4, 8S7P). The
chip communicates over I2C at address 0x55 and uses a voltage divider on
the BAT pin to scale down the 20-30V pack voltage to under 1V for its
internal ADC.

Prior to this debugging campaign, three BQ chips had their ADCs destroyed
because the old voltage divider (R27=200k / R22=34.8k) placed ~3.8V on
the BAT pin when VOLTSEL=1 was set. This exceeded the ADC's safe range.

### Hardware Architecture

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

---

## 2. Hardware Changes

These physical changes were made to the PCB during the debugging campaign:

| Change | From | To | Reason |
|--------|------|----|--------|
| R22 (bottom divider) | 34.8kOhm | 6.49kOhm | Protect ADC: BAT < 1V at 30V pack |
| R5/R6 (I2C pull-ups) | 4.7kOhm | 10kOhm | Per BQ datasheet recommendation |
| BQ chip | (multiple swaps) | -- | At least 5 solder/desolder cycles on the BQ footprint |

With R22=6.49kOhm and R27=200kOhm, the divider ratio is 31.82:1. BAT pin
voltages at key pack levels:

| Pack Voltage | BAT Pin (calculated) | BAT Pin (measured) |
|---|---|---|
| 20V | 0.629V | 0.631V |
| 25V | 0.786V | 0.784V |
| 30V | 0.943V | 0.935V |

All within the BQ34Z100-R2 BAT ADC input range of 0.05V to 1.0V.

---

## 3. Chip Inventory

Six BQ34Z100-R2 chips were involved across all trials:

| Chip ID | Description | Origin |
|---------|-------------|--------|
| 3 old chips (unnamed) | ADC destroyed by 3.8V on BAT (old 34.8k divider + VOLTSEL=1) | Previous sessions |
| First fresh chip (unnamed) | New from stock, defective I2C -- never ACKed | Soldered for Trial 2 |
| Chip 1G | New from stock, initially worked, then ADC locked at 0mV | Soldered for Trial 16 |
| Chip 2G | One of the old configured chips, later NACKed due to solder damage | Swapped in for Trial 33 |
| Chip 1N | New/unused, in storage | Reserved for future use with TI tools |
| Chip 2N | New/unused, in storage | Reserved for future use with TI tools |

---

## 4. Phase 1: Voltage Divider Retrofit

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

## 5. Phase 2: First Fresh Chip (Defective)

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

## 6. Phase 3: Old Chip Cross-Validation

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

## 7. Phase 4: Second Fresh Chip (Chip 1G)

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

## 8. Phase 5: Overnight Recovery Attempts

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

## 9. Phase 6: Third Fresh Chip -- Incremental Isolation

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

## 10. Phase 7: Multi-Chip Rotation and ADC Mystery

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

## 11. Phase 8: Final Recovery Attempts (Chips 2G and 1G)

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

## 12. Phase 9: LED Test and INA226 Adoption

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

## 13. Theory Tracker

Complete list of every theory proposed and its final status:

| # | Theory | Status | Evidence |
|---|--------|--------|----------|
| 1 | 3.3V I2C pull-ups too high for 2.5V REG25 | ELIMINATED | Old chips worked with identical pull-ups |
| 2 | Pull-up resistance too low (4.7kOhm) | ELIMINATED | 10kOhm also NACKed on defective chip; old chip ACKed with both |
| 3 | UVLO from low BAT voltage prevents I2C | ELIMINATED | 2V applied directly to BAT, still NACKed; old chips ACK at 0mV BAT |
| 4 | REG25 bypass cap missing/oscillating | ELIMINATED | 1uF present, REG25 stable at 2.55V |
| 5 | Fresh chip needs high BAT for first boot | PARTIALLY SUPPORTED | 2 fresh chips NACKed initially; one ACKed after ~20 min warm-up; 2V direct didn't help first one |
| 6 | First fresh chip is defective | CONFIRMED | All other chips ACK on same board; this one never ACKed under any conditions |
| 7 | CC calibration kills IT algorithm at low BAT | CONFIRMED, REPRODUCIBLE | Incremental test: bare RESET survives, RSNS fix survives, CC cal kills. Reversible when caught early. |
| 8 | Divider loading collapses BAT voltage | ELIMINATED | Op-amp buffer provides low-impedance drive to BAT pin |
| 9 | REGIN underpowered | ELIMINATED | Measured 5.033V |
| 10 | REG25 not regulating | ELIMINATED | Measured 2.551V |
| 11 | KiCad pin mapping wrong | ELIMINATED | Verified against TI datasheet, all pins correct |
| 12 | VEN timing issue | ELIMINATED | VEN tied to REG25, always high when powered |
| 13 | VSS ground offset | ELIMINATED | 5mV on VSS, negligible |
| 14 | Aardvark 3.3V backfeed corrupts ADC reference | TESTED, ELIMINATED | `bq_test_no_tgtpower.py` ran without target power, same results |
| 15 | External thermistor pin (TS) causes ADC lockup | TESTED, ELIMINATED | `bq_temps_test.py` toggled TEMPS bit, no change in voltage reading |
| 16 | ADC reads ~40mV for ~787mV BAT input (18x error) | UNSOLVED | Physical measurement confirms 787mV on pin; ADC reports 44mV; no known explanation; all testable theories eliminated |

---

## 14. Final Chip Status

| Chip | I2C | ADC | DF Writes | LEDs | Usability |
|------|-----|-----|-----------|------|-----------|
| Chip 1G | ACKs | Locked at 0mV | Blocked (BAT < 2800mV) | Cannot enable (LED Config stuck at 0x00) | Dead for fuel gauge purposes |
| Chip 2G | NACKing | Unknown | N/A | N/A | Dead (solder damage from repeated swaps) |
| Chip 1N | Untested | Untested | Untested | Untested | Reserved for TI tools |
| Chip 2N | Untested | Untested | Untested | Untested | Reserved for TI tools |

---

## 15. Scripts Written

Every script created during this debugging campaign, in approximate
chronological order of creation:

| Script | Purpose | Key Finding |
|--------|---------|-------------|
| `pcb_diagnostics.py` | Original all-in-one diagnostic (INA226 + BQ) | Baseline readings |
| `i2c_scan.py` | Full I2C bus scan (0x03-0x77) | Confirmed which chips ACK/NACK |
| `bq_comm_test.py` | 3-phase comm check + Pack Config auto-correct | VOLTSEL/RSNS verification works |
| `bq_calibrate.py` | CC Gain/Delta calibration for 5mOhm sense | **DO NOT USE** -- kills gauge at low BAT |
| `bq_program_battery.py` | Program Renogy battery parameters | Never used successfully |
| `bq_program_chemistry.py` | 6-phase LiFePO4 chemistry programming (1136 lines) | Never fully executed |
| `bq_debug_voltage.py` | Deep voltage diagnostic (all registers) | Confirmed ADC reads ~0mV across all registers |
| `bq_fix_cells.py` | Cell count + VD experiments | No configuration fixes the ADC |
| `bq_fix_vdivider.py` | VD restore + Ralim calibration | VD cannot correct an 18x ADC error |
| `bq_fix_packconfig.py` | Full DF dump + Pack Config bit decode | Useful for diagnostics |
| `bq_recover.py` | 5-strategy analog recovery | All strategies failed |
| `bq_restore_factory.py` | 4-strategy factory default restore | All strategies failed |
| `bq_kitchen_sink.py` | 5-phase comprehensive "throw everything at it" | All phases failed on Chip 1G |
| `bq_cal_mode_test.py` | Enter CAL mode for raw ADC values | Raw ADC also reads ~0mV |
| `bq_voltsel_toggle_test.py` | Toggle VOLTSEL, measure 5:1 ratio | Got 1.6x instead of 5x |
| `bq_temps_test.py` | Toggle TEMPS bit (internal vs external thermistor) | No effect on voltage reading |
| `bq_test_no_tgtpower.py` | Test without Aardvark 3.3V target power | No effect -- eliminated backfeed theory |
| `bq_readonly_test.py` | Pure read-only linearity test (zero writes) | Used for safe Chip 2G monitoring |
| `bq_ina_monitor.py` | Side-by-side BQ + INA226 monitor | Confirmed BQ doesn't track, INA226 does |
| `bq_led_test.py` | LED Config test + All-LEDs-ON command | Confirmed LED Config=0x00, BQ cannot drive LEDs |
| `bq_fresh_chip.py` | Incremental staged bringup (probe/reset/rsns/cc/vd) | **Identified CC cal as the killer** |
| `ina226_comm_test.py` | INA226 identity + register check | Confirmed INA226 working correctly |
| `ina226_fuel_gauge.py` | Complete INA226 fuel gauge with coulomb counting | **PRIMARY fuel gauge** -- validated and working |
| `ina226_monitor.py` | Real-time tkinter GUI with rolling plots + CSV logging | Used for bench testing and data capture |

---

## 16. Lessons Learned

### Confirmed Root Causes

1. **CC calibration kills the IT algorithm at low BAT voltages.** Writing
   CC Gain/Delta values for the 5mOhm sense resistor and then issuing RESET
   causes the Impedance Track algorithm to fail to re-bootstrap when BAT is
   under ~1V. The factory 10mOhm defaults do not cause this problem.

2. **Fresh BQ chips may need 15-20 minutes of powered warm-up** before their
   I2C interface becomes active. This is not documented in the TI datasheet.

3. **Repeated soldering/desoldering damages footprint pads and joints.**
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
