
## AutoNav — Charge Indicator PCB

This repository contains the KiCad project for a compact battery charge-level indicator board. It is designed to be attached across a battery's power and ground (the original target is an RBT245LFP pack) and displays charge state using a set of LEDs at roughly 100%, 80%, 60%, 40%, 20%, and 0% (with a small buffer).

Key goals
- Provide a small, removable indicator that shows battery level with color-coded LEDs.
- Provide over-voltage protection (target ~30 V).
- Use surface-mount components (0603/0805/1210 footprints) for compactness.
- Make the project editable in KiCad and easy to generate artwork/BOMs.

Files of interest
- `Charge_Indicator/Charge_Indicator.kicad_pro` — KiCad project file.
- `Charge_Indicator/Charge_Indicator.kicad_sch` — schematic (Eeschema) source.
- `Charge_Indicator/Charge_Indicator.kicad_pcb` — PCB layout (pcbnew) source.
- `Charge_Indicator-backups/` — KiCad automatic backups.

Footprints & libraries
- The project uses footprints from a Wavenumber footprint set (footprint names like `wavenumber:R0603_0.55MM_HD`, `wavenumber:C1210_2.70MM_MD`) and standard footprints for connectors (e.g. `wavenumber:1984617` Phoenix-style terminal block). Some STEP models are embedded for 3D preview.

Opening the project (quick start)
1. Open KiCad and choose File → Open Project. Select `Charge_Indicator/Charge_Indicator.kicad_pro`.
2. From the project manager you can open the schematic (Eeschema) and PCB (pcbnew).
3. To generate a BOM: open the schematic editor (Eeschema) and use Tools → Generate Bill of Materials (or the BOM exporter configured in the project — default filename is `${PROJECTNAME}.csv`).
4. To create fabrication outputs: open the PCB editor (pcbnew) → File → Plot (Gerbers) and Fabrication Outputs → Drill Files.

KiCad compatibility
- Project files include generator_version `9.0` and a kicad_sch version dated 2025-01-14; if you have trouble opening them, try a recent KiCad release (KiCad 7/8 or newer). If you run into compatibility issues, please open an issue describing the KiCad version and error.

Contact / Author
- Repository owner: `nfikes` (GitHub).
- Repository collaborator: `ehughes` (GitHub).

Datasheets for the battery:

https://github.com/nfikes/AutoNav-Charge_Indicator-KiCad_Pcb/blob/80e677aa5d561c7ffa7e2566f1dbaed0d212a4c6/Battery%20Datasheets/RBT2425LFP%20-%20Datasheet.pdf

https://github.com/nfikes/AutoNav-Charge_Indicator-KiCad_Pcb/blob/80e677aa5d561c7ffa7e2566f1dbaed0d212a4c6/Battery%20Datasheets/RBT2425LFP%20-%20User%20Manual.pdf
