## AutoNav — Charge Indicator PCB

This repository contains the updated KiCad project for a compact, high-accuracy
battery charge-level indicator board. The design has evolved from a simple LED
threshold indicator into a more robust, instrumentation-grade battery monitor
using Texas Instruments (TI) power-management and monitoring ICs. The board is
intended to connect directly across the battery terminals (original target:
RBT245LFP pack) and provide a clear visual indication of pack state of charge.

## Images:

# Physical PCB:

<img width="743" height="658" alt="Screenshot 2025-11-28 at 23 55 34" src="https://github.com/user-attachments/assets/18826243-7f9d-4236-8b8b-fdca2c30d851" />


# Routing:

<img width="703" height="703" alt="Screenshot 2025-11-28 at 23 56 09" src="https://github.com/user-attachments/assets/d0569d03-93f6-4175-a271-8092422319dd" />


# Schematic:

<img width="1004" height="693" alt="Screenshot 2025-11-28 at 23 56 23" src="https://github.com/user-attachments/assets/734c572a-19bc-43d5-9108-25eee76cf57e" />

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

Initial Board Programming (BQ34Z100-R2)
----------------------------------------

The BQ34Z100-R2 fuel gauge (U1) must be programmed once before the board will
report battery voltage, SOC, or current. All configuration is stored in
non-volatile Data Flash and persists across power cycles — you do not need to
reprogram the chip after removing power.

### Hardware required

- Total Phase Aardvark I2C adapter (connected to the board's I2C header)
- 24V power supply or the Renogy RBT2425LFP battery pack

### Safety: VOLTSEL and the BAT pin

The BQ34Z100-R2 has an internal 5:1 voltage divider on the BAT pin (pin 4).
The board's external resistor divider (R27 = 200 k / R22 = 34.8 k) steps the
~25.6 V pack voltage down to ~3.8 V at the BAT pin. The internal divider
further reduces this to ~0.76 V, safely within the ADC's 1 V limit.

If **VOLTSEL** (bit 3 of Pack Configuration, SC 64) is set to 1, the internal
divider is bypassed and the full ~3.8 V reaches the ADC, **permanently
damaging the analog front-end**. VOLTSEL must always be 0 on this board.

SW1 (SPDT slide switch) disconnects the external voltage divider from the BAT
pin. Use it to protect the ADC when the chip's VOLTSEL state is unknown.

### Programming procedure

1. **Switch SW1 OFF** — disconnects the voltage divider so no voltage is
   present on the BAT pin.
2. **Connect the Aardvark** to the board's I2C header and apply power.
3. **Verify / clear VOLTSEL** — run `bq_clear_voltsel.py` and confirm
   VOLTSEL = 0 (INT):
   ```
   cd Programming/scripts
   python bq_clear_voltsel.py
   ```
4. **Switch SW1 ON** — the BAT pin now receives the divided pack voltage
   safely through the internal 5:1 divider.
5. **Run board diagnostics** to confirm I2C communication with both the
   INA226 and BQ34Z100-R2:
   ```
   python pcb_diagnostics.py
   ```
6. **Program battery parameters** (cell count, capacity, voltage divider
   ratio, QMax):
   ```
   python bq_program_battery.py
   ```
7. **Program the LiFePO4 chemistry profile** (R_a resistance tables, design
   parameters, voltage calibration using the INA226 as ground truth):
   ```
   python bq_program_chemistry.py
   ```
8. **Verify final readings** — re-run diagnostics and confirm that
   `Voltage()`, SOC, and temperature are reporting sensible values:
   ```
   python pcb_diagnostics.py
   ```

### After programming

- The chip seals itself automatically after each flash commit. Normal
  operation does not require the device to be unsealed.
- Configuration survives power cycles indefinitely — no reprogramming is
  needed unless you want to change parameters.
- SW1 can be left ON during normal operation; it only needs to be OFF as a
  safety precaution when VOLTSEL state is unknown (e.g., on a brand-new or
  factory-reset chip).
- If voltage reads 0 mV after programming, run `bq_fix_vdivider.py` to
  recalibrate the voltage divider using the INA226 as a reference.

### Programming scripts reference

| Script                    | Purpose                                          |
|---------------------------|--------------------------------------------------|
| `bq_clear_voltsel.py`    | Safety-clear VOLTSEL bit (run first on new chips)|
| `pcb_diagnostics.py`     | Full I2C diagnostics for INA226 + BQ34Z100-R2    |
| `bq_program_battery.py`  | Write design capacity, cell count, VD, QMax      |
| `bq_program_chemistry.py`| LiFePO4 R_a tables + voltage calibration         |
| `bq_fix_vdivider.py`     | Recalibrate voltage divider via INA226            |
| `bq_calibrate.py`        | CC Gain / CC Delta calibration                   |
| `bq_debug_voltage.py`    | Dump all registers for voltage debugging         |
| `bq_full_reset.py`       | Factory reset the gauge                          |

Battery Datasheets
------------------
Reference documentation for the RBT2425LFP LiFePO4 battery:

https://github.com/nfikes/AutoNav-Charge_Indicator-KiCad_Pcb/blob/80e677aa5d561c7ffa7e2566f1dbaed0d212a4c6/Battery%20Datasheets/RBT2425LFP%20-%20Datasheet.pdf

https://github.com/nfikes/AutoNav-Charge_Indicator-KiCad_Pcb/blob/80e677aa5d561c7ffa7e2566f1dbaed0d212a4c6/Battery%20Datasheets/RBT2425LFP%20-%20User%20Manual.pdf



