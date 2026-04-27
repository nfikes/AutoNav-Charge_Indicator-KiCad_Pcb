# PCB Design Guidelines — Net Pair Clearance and Protection

These guidelines are derived from the Revision 2 board failure analysis
and the Revision 3 metal shaving risk assessment. They apply to any
future revision of the Battery Status Indication PCB and to similar
mixed-voltage I2C sensor boards.

## BAT+ and GND

- Maintain maximum practical clearance between BAT+ and GND pads,
  traces, and vias.
- Use solder mask dams between adjacent BAT+ and GND pads on bulk
  capacitors (C1) and sense resistors (R26, R4).
- Route BAT+ on a separate layer from GND pours where possible to
  avoid via-to-pour shorts.
- Never route BAT+ under QFN or fine-pitch IC packages.

## BAT+ and FB / Low-Voltage Control Pins

- The SGM61410 FB pin has a 5.5V absolute max. Keep BAT+ traces and
  pads as far as physically possible from FB, BOOT, and COMP pins.
- Do not place feedback divider resistors (R1, R2, R3) adjacent to
  components carrying BAT+.
- Consider a ground guard trace between BAT+ and the feedback network.

## +5V and GND

- Use thermal relief on +5V pads connected to ground pours to reduce
  the chance of solder bridging.
- Place decoupling capacitors (C8, C10) with pad orientation that
  maximizes the gap between +5V and GND pads relative to nearby IC
  pins.
- The TPS7A2033 LDO has only 1.5V margin above its 5V input. Add
  input overvoltage protection if the +5V rail is exposed to
  transients.

## +3v3 and GND

- The +3v3 rail powers the INA226 (VS pin). A short here kills the
  I2C bus.
- Keep +3v3 decoupling caps (C5) oriented so their pads do not face
  INA226 GND pads.

## SCL / SDA and Power Rails (+5V, +3v3, GND)

- The INA226 SCL absolute max is only VS + 0.3V (3.6V at 3.3V
  supply). Do not route SCL adjacent to any rail above 3.3V.
- The BQ34Z100 has only 500V HBM ESD — the lowest on the board. Add
  dedicated ESD protection (TVS diodes rated below 5.5V) on SDA and
  SCL as close to the BQ34Z100 as possible.
- Replace the 5.6V zener clamps (D8/D9) with 3.3V TVS diodes to
  actually protect the INA226 SCL pin.
- I2C pull-up resistors (R5, R6) bridge +3v3 to SCL/SDA. Orient
  them so their pads do not face GND pours or power vias.
- Route SDA and SCL as a differential pair with ground guard traces
  on both sides when passing through dense areas.

## SCL / SDA and BAT+

- Never route I2C traces adjacent to or crossing BAT+ traces.
- The R2 board failure was caused by a short injecting voltage into
  the SCL line, triggering CMOS latch-up in the INA226. This is the
  single highest-risk failure mode on this board.

## ENABLE and GND

- The ENABLE net controls the voltage divider MOSFET array. If
  grounded by a shaving, the divider disables and voltage readings
  drop to zero.
- Add a pull-up resistor on ENABLE to maintain default-on state even
  if the switch or control signal is disrupted.
- Keep ENABLE traces away from GND vias and pours.

## VTRANS and Power Rails

- VTRANS carries the scaled battery voltage to the BQ34Z100 BAT pin
  ADC. Noise or shorts on this net corrupt all fuel gauge readings.
- Keep VTRANS traces short and shielded with ground guard traces.
- Do not route VTRANS near +5V or +3v3 rails — a short injects
  wrong voltage into the ADC input.
- The TLV271 op-amp (U6) processes VTRANS. Its input max is VDD +
  0.2V. Ensure no high-voltage net can reach its input pins.

## BAT- and GND

- BAT- connects through the current sense shunt resistor (R26).
  Shorting BAT- to GND bypasses the shunt, causing the INA226 to
  read zero current.
- Maintain clearance between BAT- and GND, especially near the
  sense resistor pads and the INA226 IN- pin.

## AGND and GND

- AGND (analog ground) and GND (digital ground) should be connected
  at a single star point near the BQ34Z100.
- Do not allow metal debris to create additional AGND-GND paths, as
  this creates ground loops that inject noise into the fuel gauge
  ADC.

## General Practices

- **Conformal coating:** Apply conformal coating to all boards
  deployed in environments with metallic debris.
- **Housing:** All deployed boards must have a protective enclosure.
  Bare boards are not acceptable for robot chassis mounting.
- **Pad orientation:** Orient component pads so that the short axis
  (narrow dimension) faces the nearest different-net pad. This
  minimizes the bridging target area.
- **Solder mask dams:** Ensure solder mask dams exist between every
  adjacent pad pair on different nets, especially on fine-pitch ICs.
- **Via tenting:** Tent all vias with solder mask to prevent exposed
  copper from participating in shorts.
- **Clearance DRC:** Run a custom DRC rule with a 1.6mm clearance
  check (0603 diagonal) between pads on nets carrying different
  voltage domains. Flag any violations for review.
- **Component selection:** Prefer ICs with higher ESD ratings
  (>2kV HBM) and wider absolute maximum voltage margins for pins
  exposed to adjacent high-voltage nets.
