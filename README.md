## AutoNav — Charge Indicator PCB

This repository contains the updated KiCad project for a compact, high-accuracy
battery charge-level indicator board. The design has evolved from a simple LED
threshold indicator into a more robust, instrumentation-grade battery monitor
using Texas Instruments (TI) power-management and monitoring ICs. The board is
intended to connect directly across the battery terminals (original target:
RBT245LFP pack) and provide a clear visual indication of pack state of charge.

## Images:

# Physical PCB:

<img width="811" height="703" alt="スクリーンショット 2026-02-18 23 04 25" src="https://github.com/user-attachments/assets/0359917f-749a-4381-a1ca-dbddd50b14f0" />


# Routing:

<img width="689" height="688" alt="スクリーンショット 2026-02-18 23 04 41" src="https://github.com/user-attachments/assets/a04603f5-d48f-4f94-82b4-d51cf403aeb7" />


# Schematic:

<img width="1001" height="691" alt="スクリーンショット 2026-02-18 23 05 13" src="https://github.com/user-attachments/assets/90be156a-7b6e-491a-81d8-5eb7c5e39b0f" />

Overview
--------
The Charge Indicator PCB now uses TI analog front-end components, current-sense
amplifiers, and DC-DC regulation to deliver stable LED indicators across the
battery’s full operating voltage range. Measurement is performed using the
INA226 current/power monitor and processed with logic-level circuitry to drive
a bank of status LEDs corresponding to approximate SOC thresholds (100%, 80%,
60%, 40%, 20%, and critical/low).

Additional focus has been placed on noise immunity, transient protection, and
safe operation across the pack’s voltage extremes.

Key Features (Updated)
----------------------
- High-accuracy measurement using TI INA226 for voltage/current/power monitoring.
- Regulated low-voltage rail provided by TI TLV34063-based regulator (or similar
  TI DC/DC device).
- Configurable threshold indication using hardware logic and a 74HC164 shift
  register for stable LED control.
- Protection circuitry including input filtering, reverse-polarity protection,
  and transient suppression.
- Low-power design suitable for continuous monitoring with minimal impact on
  battery life.
- Compact SMT layout using 0603/0805/1210 components and custom Wavenumber
  footprints.
- Removable module mountable via Phoenix-style terminal connectors or solder pads.
- Easy BOM and fabrication generation directly inside KiCad.

Repository Structure
--------------------
- Charge_Indicator/Charge_Indicator.kicad_pro      — Full KiCad project.
- Charge_Indicator/Charge_Indicator.kicad_sch      — Updated schematic including
                                                     TI power monitor + regulation
                                                     circuitry.
- Charge_Indicator/Charge_Indicator.kicad_pcb      — PCB layout with revised
                                                     component placement and routing.
- Charge_Indicator-backups/                       — Automated KiCad backups.
- Battery Datasheets/                             — Datasheets for the RBT245LFP
                                                     battery pack.

Components of Interest
----------------------
Texas Instruments ICs included in the design:
- INA226 — Precision digital current/power/voltage monitor with I²C output.
- TLV34063-based regulator (or TLV34033/LM2596 variant) — Low-voltage regulation
  for logic and LED rail.
- BQ24120 (optional/regulating block depending on revision).
- 74HC164 — LED control/sequence logic, used to manage indicator states.

(If needed, replace these with the exact ICs used in the final version.)

Custom Footprints & Libraries
------------------------------
The project uses both standard KiCad libraries and Wavenumber footprint libraries.
These include:
- Resistors/capacitors (R0603, C1210, C0805, etc.)
- Phoenix-style connectors (e.g., wavenumber:1984617)
- Embedded STEP models for realistic 3D visualization

Quick Start — Opening & Editing the Project
-------------------------------------------
1. Launch KiCad and open:
   Charge_Indicator/Charge_Indicator.kicad_pro
2. From the project window, open Eeschema to view/edit the TI measurement and
   regulation circuitry.
3. Open pcbnew to inspect component placement, routing, and copper pours.
4. To generate a BOM:
   Eeschema → Tools → Generate Bill of Materials
5. To generate fabrication outputs:
   pcbnew → File → Plot (Gerbers)
           → Fabrication Outputs → Drill Files

KiCad Version Compatibility
---------------------------
The project was created using KiCad 8/9 toolchain (schema version 9.0, updated
2025-01-14). It is recommended to use KiCad 7 or newer.

If you experience compatibility issues, please open an issue with details about
your KiCad version and the error message.

Contact / Author
- Repository owner: `nfikes` (GitHub).
- Repository collaborator: `ehughes` (GitHub).

PCB Assembly & Bring-Up Procedure
---------------------------------

Follow this procedure when building a new board.

**Rev 4+ voltage divider change:** The external voltage divider was changed
from R27 = 200 kΩ / R22 = 34.8 kΩ (ratio 6.75) to R27 = 200 kΩ /
R22 = 6.49 kΩ (ratio 31.82). This keeps the BAT pin below 1 V at maximum
pack voltage (30 V), making the BQ34Z100-R2 ADC safe **regardless of
VOLTSEL state**. The factory default VOLTSEL = 1 is now the correct setting.

### Step 1 — Solder all components

Populate all components on the board, including the BQ34Z100-R2 (U1).
With the new voltage divider, no special precautions are needed for U1.

### Step 2 — Continuity test (unpowered)

With the board **unpowered**, perform a continuity test on the load and power
terminals. Verify there are no shorts or unintended connections.

### Step 3 — Initial power-on test

Apply **10 V** to the power input and place a **1 MΩ resistor** across the
load terminal.

### Step 4 — Verify 5 V rail

Measure the **5 V pad** with a multimeter. If it reads 5 V, install the
solder bridge to connect the 5 V rail.

### Step 5 — Verify 3.3 V rail

Measure the **3.3 V pad** with a multimeter. If it reads 3.3 V, install the
solder bridge to connect the 3.3 V rail.

### Step 6 — Verify voltage divider / OP-AMP output

Measure the output of the OP-AMP that connects to the BAT pin:

- **Divider OFF (MOSFET array disabled):** should read negative millivolts
  (~0 V).
- **Divider ON (MOSFET array enabled):** should read the divided 10 V input
  (approximately 10 V / 31.82 ≈ 0.314 V).

### Step 7 — Communication tests

Connect the Aardvark I2C adapter and run both communication tests:

```
cd Programming/scripts
python3 ina226_comm_test.py
python3 bq_comm_test.py
```

`bq_comm_test.py` will verify that VOLTSEL = 1 (correct for the new divider)
and that RSNS is set correctly for low-side sensing.

### Step 8 — Enable the voltage divider

Turn on the MOSFET array to connect the voltage divider to the BAT pin.
With the new divider, the BAT pin will see ≤ 1 V regardless of VOLTSEL
state — both VOLTSEL = 0 and VOLTSEL = 1 are safe.

Initial Board Programming (BQ34Z100-R2)
----------------------------------------

After completing the assembly and bring-up procedure above, the BQ34Z100-R2
must be programmed with battery parameters before the board will report
accurate voltage, SOC, or current. All configuration is stored in
non-volatile Data Flash and persists across power cycles.

### Hardware required

- Total Phase Aardvark I2C adapter (connected to the board's I2C header)
- 24 V power supply or the Renogy RBT2425LFP battery pack

### Voltage divider and VOLTSEL

The BQ34Z100-R2 has an internal 5:1 voltage divider on the BAT pin. The
board's external resistor divider (R27 = 200 kΩ / R22 = 6.49 kΩ) steps the
~25.6 V pack voltage down to ~0.8 V at the BAT pin — safely below the ADC's
1 V limit in **both** VOLTSEL modes:

- **VOLTSEL = 1** (factory default, internal divider bypassed): ADC sees the
  BAT pin voltage directly (~0.8 V). Best ADC resolution.
- **VOLTSEL = 0** (internal 5:1 divider active): ADC sees BAT / 5 (~0.16 V).
  Still safe, but lower resolution.

VOLTSEL = 1 is the **correct and preferred** setting for this board.

> **Historical note (Rev 2–3):** Earlier revisions used R22 = 34.8 kΩ, which
> put ~3.8 V on the BAT pin. With VOLTSEL = 1 (factory default), the full
> 3.8 V reached the ADC, permanently destroying the analog front end. Three
> chips were damaged this way. The Rev 4+ divider eliminates this failure
> mode entirely.

### Programming procedure

1. **Connect the Aardvark** to the board's I2C header with target power
   enabled.
2. **Run communication tests**:
   ```
   cd Programming/scripts
   python3 ina226_comm_test.py
   python3 bq_comm_test.py
   ```
3. **Enable the MOSFET array** if not already on.
4. **Run board diagnostics** to confirm I2C communication with both the
   INA226 and BQ34Z100-R2:
   ```
   python3 pcb_diagnostics.py
   ```
5. **Program battery parameters** (cell count, capacity, voltage divider
   ratio, QMax):
   ```
   python3 bq_program_battery.py
   ```
6. **Program the LiFePO4 chemistry profile** (R_a resistance tables, design
   parameters, voltage calibration using the INA226 as ground truth):
   ```
   python3 bq_program_chemistry.py
   ```
7. **Verify final readings** — re-run diagnostics and confirm that
   `Voltage()`, SOC, and temperature are reporting sensible values:
   ```
   python3 pcb_diagnostics.py
   ```

### After programming

- The chip seals itself automatically after each flash commit. Normal
  operation does not require the device to be unsealed.
- Configuration survives power cycles indefinitely — no reprogramming is
  needed unless you want to change parameters.
- If voltage reads 0 mV after programming, run `bq_fix_vdivider.py` to
  recalibrate the voltage divider using the INA226 as a reference.

### Programming scripts reference

All scripts are located in `Programming/scripts/`.

| Script                    | Purpose                                          |
|---------------------------|--------------------------------------------------|
| `ina226_comm_test.py`    | INA226 communication check (MFG/Die ID + regs)  |
| `bq_comm_test.py`        | BQ34Z100-R2 comm check + config verification     |
| `i2c_scan.py`            | Full I2C bus scan (all addresses 0x03-0x77)      |
| `bq_clear_voltsel.py`    | Standalone VOLTSEL tool (legacy, Rev 2-3 only)   |
| `pcb_diagnostics.py`     | Full I2C diagnostics for INA226 + BQ34Z100-R2    |
| `bq_program_battery.py`  | Write design capacity, cell count, VD, QMax      |
| `bq_program_chemistry.py`| LiFePO4 R_a tables + voltage calibration         |
| `bq_fix_vdivider.py`     | Recalibrate voltage divider via INA226            |
| `bq_calibrate.py`        | CC Gain / CC Delta calibration                   |
| `bq_debug_voltage.py`    | Dump all registers for voltage debugging         |
| `bq_full_reset.py`       | Factory reset the gauge                          |
| `ina226_monitor.py`      | Real-time GUI monitor (voltage/current/power)    |

Revision 2 Board Failure Report (Bowser → Shogi Transfer)
----------------------------------------------------------

**Date:** 2026-04-23
**Board:** Revision 2, serial originally deployed on robot Bowser
**Status:** Declared dead

### Background

The R2 board was transferred from robot Bowser to robot Shogi. It was
fully functional on Bowser. After installation on Shogi, I2C
communication failed completely.

### Suspected Root Cause

Metal shavings from the robot chassis are suspected to have landed on
the board, creating transient shorts across exposed traces and
component pads. This triggered cascading failures in multiple ICs.

### Failure 1 — INA226 (U3) CMOS Latch-Up

**Symptom:** SCL held at ~3 ohms to ground. No I2C devices responded.

**Diagnosis:** With U3 removed, SCL-to-GND resistance rose from 3 ohms
to 200 kohms. Using the parallel resistance formula:

    1/R_total = 1/R_ina + 1/R_board
    R_ina ≈ 5.0 ohms

The INA226 had a ~5 ohm internal short from SCL to ground — consistent
with CMOS latch-up, where a parasitic PNPN thyristor (SCR) structure
activates and creates a self-sustaining low-impedance path. A metal
shaving shorting an I/O pin above or below the supply rails would
forward-bias the internal ESD protection diodes, injecting substrate
current and triggering the parasitic SCR.

**Resolution:** Replaced U3 (INA226). SCL impedance restored to normal.

### Failure 2 — SGM61410 (U2) DC-DC Buck Converter

**Symptom:** 5 V buck output only produced ~1.15 V from a 20 V input.
The downstream 3.3 V LDO (U5, TPS7A2033) also showed only ~1 V output.

**Diagnosis:**
- U2 pin 5 (VIN): 19.99 V — input is fine
- U2 pin 6 (SW): 1.15 V — not switching properly
- U2 pin 3 (FB): 1.144 V — essentially equal to the output

The feedback pin reading the full output voltage indicates the feedback
divider network is broken. The bottom resistor (FB to GND) is likely
open, causing FB to float to the output voltage through the top
resistor. The converter sees FB above its 0.6 V reference and
throttles switching to minimum duty cycle.

**Resolution:** None — board declared dead. The feedback network damage
combined with potential internal U2 damage makes further rework
impractical.

### Lessons Learned

1. Metal shavings from robot chassis work can cause catastrophic
   multi-IC failures through transient shorts and CMOS latch-up.
2. The INA226 SCL pin is particularly vulnerable — its absolute maximum
   is only VS + 0.3 V, and the 5.6 V zener ESD clamps (D8/D9) on this
   board clamp above that threshold.
3. **All future PCBs mandate a protective housing.** Bare boards must
   not be deployed on robots without an enclosure to prevent metallic
   debris from reaching exposed components and traces.
4. When one IC fails from an external short event, inspect all ICs on
   the board — cascading damage is likely.

Battery Datasheets
------------------
Reference documentation for the RBT2425LFP LiFePO4 battery:

https://github.com/nfikes/AutoNav-Charge_Indicator-KiCad_Pcb/blob/80e677aa5d561c7ffa7e2566f1dbaed0d212a4c6/Battery%20Datasheets/RBT2425LFP%20-%20Datasheet.pdf

https://github.com/nfikes/AutoNav-Charge_Indicator-KiCad_Pcb/blob/80e677aa5d561c7ffa7e2566f1dbaed0d212a4c6/Battery%20Datasheets/RBT2425LFP%20-%20User%20Manual.pdf



