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

Battery Datasheets
------------------
Reference documentation for the RBT2425LFP LiFePO4 battery:

https://github.com/nfikes/AutoNav-Charge_Indicator-KiCad_Pcb/blob/80e677aa5d561c7ffa7e2566f1dbaed0d212a4c6/Battery%20Datasheets/RBT2425LFP%20-%20Datasheet.pdf

https://github.com/nfikes/AutoNav-Charge_Indicator-KiCad_Pcb/blob/80e677aa5d561c7ffa7e2566f1dbaed0d212a4c6/Battery%20Datasheets/RBT2425LFP%20-%20User%20Manual.pdf



