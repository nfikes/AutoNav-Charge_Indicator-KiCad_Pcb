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

Follow this procedure exactly when building a new board. The BQ34Z100-R2 fuel
gauge (U1) ships with VOLTSEL=1 as the factory default, which bypasses the
internal 5:1 voltage divider and exposes the ADC to destructive overvoltage.
**Two chips have been permanently damaged by powering the BAT pin before
clearing VOLTSEL.** The procedure below prevents this.

### Step 1 — Solder everything except U1

Populate all components on the board **except** the BQ34Z100-R2 (U1). Leave
that pad empty for now.

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
  (approximately 10 V / 6.75 ≈ 1.48 V).

Confirm both states, then **turn the divider OFF** before proceeding.

### Step 7 — Solder U1 (BQ34Z100-R2)

With the voltage divider **confirmed OFF**, solder the BQ34Z100-R2 onto the
board. The MOSFET array must remain disabled throughout this step and the
next.

### Step 8 — Communication tests and VOLTSEL safety

Connect the Aardvark I2C adapter and run both communication tests. The
BQ34Z100-R2 will power up parasitically through the I2C pull-ups — no BAT
pin voltage is needed.

```
cd Programming/scripts
python3 ina226_comm_test.py
python3 bq_comm_test.py
```

`bq_comm_test.py` will automatically detect and clear VOLTSEL=1 if present.
**Confirm the output shows VOLTSEL = 0 and that the write was verified.**

### Step 9 — Enable the voltage divider

**Only** after both conditions are met:

1. VOLTSEL = 0 is **verified** in the BQ34Z100-R2 data flash, AND
2. The voltage divider has been **confirmed off** (Step 6)

...may the MOSFET array be turned on to connect the voltage divider to the
BAT pin.

> **WARNING:** If VOLTSEL is 1 when voltage is applied to the BAT pin, the
> ADC will be **permanently and instantly damaged**. There is no recovery.
> This has happened on both Rev 2 (3.7 V exposure, fully destroyed) and
> Rev 3 (2.2 V exposure, partially destroyed). Even brief exposure of
> seconds is enough to cause irreversible damage.

Initial Board Programming (BQ34Z100-R2)
----------------------------------------

After completing the assembly and bring-up procedure above, the BQ34Z100-R2
must be programmed with battery parameters before the board will report
accurate voltage, SOC, or current. All configuration is stored in
non-volatile Data Flash and persists across power cycles.

### Hardware required

- Total Phase Aardvark I2C adapter (connected to the board's I2C header)
- 24 V power supply or the Renogy RBT2425LFP battery pack

### Safety: VOLTSEL and the BAT pin

The BQ34Z100-R2 has an internal 5:1 voltage divider on the BAT pin. The
board's external resistor divider (R27 = 200 kΩ / R22 = 34.8 kΩ) steps the
~25.6 V pack voltage down to ~3.8 V at the BAT pin. The internal divider
further reduces this to ~0.76 V, safely within the ADC's 1 V limit.

If **VOLTSEL** (bit 3 of Pack Configuration, SC 64) is set to 1, the internal
divider is bypassed and the full ~3.8 V reaches the ADC, **permanently
damaging the analog front-end**. VOLTSEL must always be 0 on this board.

The BQ34Z100-R2 **ships from the factory with VOLTSEL = 1**. The MOSFET array
disconnects the external voltage divider from the BAT pin. Use it to protect
the ADC whenever the chip's VOLTSEL state is unknown (e.g., on a brand-new or
replacement chip). The chip can be programmed safely with the MOSFET array off
— it powers up parasitically through the I2C bus pull-ups.

### Programming procedure

1. **MOSFET array OFF** — confirm the voltage divider is disconnected from the
   BAT pin (see assembly Step 6 above).
2. **Connect the Aardvark** to the board's I2C header with target power
   enabled.
3. **Verify / clear VOLTSEL** — run `bq_comm_test.py` which auto-clears
   VOLTSEL if set:
   ```
   cd Programming/scripts
   python3 bq_comm_test.py
   ```
4. **Enable the MOSFET array** — the BAT pin now receives the divided pack
   voltage safely through the internal 5:1 divider.
5. **Run board diagnostics** to confirm I2C communication with both the
   INA226 and BQ34Z100-R2:
   ```
   python3 pcb_diagnostics.py
   ```
6. **Program battery parameters** (cell count, capacity, voltage divider
   ratio, QMax):
   ```
   python3 bq_program_battery.py
   ```
7. **Program the LiFePO4 chemistry profile** (R_a resistance tables, design
   parameters, voltage calibration using the INA226 as ground truth):
   ```
   python3 bq_program_chemistry.py
   ```
8. **Verify final readings** — re-run diagnostics and confirm that
   `Voltage()`, SOC, and temperature are reporting sensible values:
   ```
   python3 pcb_diagnostics.py
   ```

### After programming

- The chip seals itself automatically after each flash commit. Normal
  operation does not require the device to be unsealed.
- Configuration survives power cycles indefinitely — no reprogramming is
  needed unless you want to change parameters.
- The MOSFET array can be left on during normal operation; it only needs to be
  off as a safety precaution when VOLTSEL state is unknown (e.g., on a
  brand-new or replacement chip).
- If voltage reads 0 mV after programming, run `bq_fix_vdivider.py` to
  recalibrate the voltage divider using the INA226 as a reference.

### Programming scripts reference

All scripts are located in `Programming/scripts/`.

| Script                    | Purpose                                          |
|---------------------------|--------------------------------------------------|
| `ina226_comm_test.py`    | INA226 communication check (MFG/Die ID + regs)  |
| `bq_comm_test.py`        | BQ34Z100-R2 comm check + VOLTSEL safety clear    |
| `i2c_scan.py`            | Full I2C bus scan (all addresses 0x03-0x77)      |
| `bq_clear_voltsel.py`    | Standalone VOLTSEL=0 enforcer                    |
| `pcb_diagnostics.py`     | Full I2C diagnostics for INA226 + BQ34Z100-R2    |
| `bq_program_battery.py`  | Write design capacity, cell count, VD, QMax      |
| `bq_program_chemistry.py`| LiFePO4 R_a tables + voltage calibration         |
| `bq_fix_vdivider.py`     | Recalibrate voltage divider via INA226            |
| `bq_calibrate.py`        | CC Gain / CC Delta calibration                   |
| `bq_debug_voltage.py`    | Dump all registers for voltage debugging         |
| `bq_full_reset.py`       | Factory reset the gauge                          |
| `ina226_monitor.py`      | Real-time GUI monitor (voltage/current/power)    |

Battery Datasheets
------------------
Reference documentation for the RBT2425LFP LiFePO4 battery:

https://github.com/nfikes/AutoNav-Charge_Indicator-KiCad_Pcb/blob/80e677aa5d561c7ffa7e2566f1dbaed0d212a4c6/Battery%20Datasheets/RBT2425LFP%20-%20Datasheet.pdf

https://github.com/nfikes/AutoNav-Charge_Indicator-KiCad_Pcb/blob/80e677aa5d561c7ffa7e2566f1dbaed0d212a4c6/Battery%20Datasheets/RBT2425LFP%20-%20User%20Manual.pdf



