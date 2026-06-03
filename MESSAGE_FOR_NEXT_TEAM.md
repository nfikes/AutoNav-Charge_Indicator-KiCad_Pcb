# Message for the Next Team

This document captures the hardware recommendations we accumulated over the
2025–2026 season and through competition. The Charge Indicator PCB went
through four revisions, multiple chip failures, and one declared-dead board
(R2 on Shogi). Each item below is a direct response to something we hit in
the lab or in the field — please incorporate them on the next revision before
producing new boards.

---

## 1. DIP Switches for I²C Address Selection

**Recommendation:** Add a small DIP switch (or jumper block) on the PCB that
selects the I²C addresses of the INA226 and BQ34Z100-R2.

**Why it matters:**
- The current board hard-wires the INA226 address pins to a fixed value.
  When we tried to run two Charge Indicator boards on the same I²C bus
  (one per battery pack), they collided and neither responded reliably.
- The BQ34Z100-R2 address is also fixed in firmware, but having a hardware
  identifier on the bus made debugging which board was responding much
  harder than it needed to be.
- DIP switches make it possible to swap a spare board into any robot
  without re-flashing or re-cutting traces.

**What to do:** Route the INA226 A0/A1 pins (and any equivalent addressing
options) to a 2- or 4-position SMT DIP switch with pull-ups. Silkscreen the
address map next to the switch so the bench tech does not need the
datasheet.

---

## 2. Shunt Resistor Rated for 10 A Steady-State

**Recommendation:** Replace the current shunt with one rated for **10 A
continuous** with appropriate power dissipation headroom.

**Why it matters:**
- During competition runs the robot pulled sustained current well above
  what the existing low-side shunt was specified for. The shunt got hot
  enough to drift its resistance, which made the INA226 current reading
  inaccurate at exactly the moment we needed it (high-load navigation).
- A shunt that is only sized for peak current and not steady-state
  dissipation will degrade over a season even if it never fails outright.

**What to do:** Pick a 4-terminal Kelvin-sense shunt rated for ≥10 A
steady-state with a power rating that gives at least 2× margin at peak load
(e.g., a 2 mΩ, 3 W part). Make sure the INA226 sense traces are pulled
straight from the Kelvin pads, not tapped off the high-current copper.

---

## 3. Solid-State SMT Fuses

**Recommendation:** Add resettable solid-state fuses (PPTC / e-fuse ICs) on
the power input and on the 5 V / 3.3 V rails.

**Why it matters:**
- The R2 board on Shogi failed catastrophically when metal chassis
  shavings shorted exposed pins. The INA226 latched up (SCL shorted to GND
  at ~5 Ω internal), and the SGM61410 buck converter's feedback network
  was destroyed. See `README.md` "Revision 2 Board Failure Report" for the
  full forensics.
- A correctly chosen e-fuse on the input would have current-limited or
  cut the rail before the latch-up event cascaded into the buck.
- Traditional glass/ceramic fuses are too slow and not friendly to SMT
  assembly. Solid-state e-fuses (e.g., TI TPS25xxx family) give us
  overcurrent, overvoltage, and reverse-polarity protection in one part.

**What to do:** Spec a hot-swap / e-fuse IC on the pack input, sized for
the worst-case 10 A continuous + transient envelope. Add smaller PPTCs
or polyfuses on the 5 V and 3.3 V rails so a downstream short does not
take out U2 again.

---

## 4. Larger Power Trace Widths

**Recommendation:** Widen all power-carrying traces — pack input,
load output, and the high-current path through the shunt — and use
copper pours instead of routed traces wherever possible.

**Why it matters:**
- Several of the current power traces were sized for the original
  "LED threshold indicator" use case and were never re-spec'd when the
  board grew into a 10 A pack-side monitor.
- Narrow traces under sustained load contribute heat directly into the
  INA226 and the BQ34Z100, biasing their internal temperature reading
  and (we suspect) accelerating the failures we saw on Shogi.

**What to do:** Re-run the IPC-2152 calculation for the actual peak and
steady-state currents on this board. As a starting point, target ≥100 mil
on the pack input/return and a full pour on inner layers if you go 4-layer.
Keep the high-current path physically separated from analog sense lines.

---

## 5. Corrected Ecosystem for the BQ34Z100-R2

**Recommendation:** Rework the supporting circuitry around the
BQ34Z100-R2 so it matches TI's reference design, not the patched-together
version we ended up with.

**Why it matters:**
- Rev 2 and Rev 3 destroyed three BQ34Z100-R2 chips because the external
  voltage divider was sized for VOLTSEL = 0 while the factory default is
  VOLTSEL = 1. The BAT pin saw ~3.8 V — well above the 1 V ADC max — on
  every fresh chip.
- Rev 4 fixed the divider (R27 = 200 kΩ / R22 = 6.49 kΩ, ratio 31.82), but
  the rest of the ecosystem — REG25 decoupling, SRP/SRN Kelvin routing,
  pack-thermistor path, and the BAT-pin filter network — was never
  brought fully back in line with the BQ34Z100-R2 reference layout.
- Every quirk we worked around in `bq_program_battery.py` and
  `bq_fix_vdivider.py` exists because the hardware around U1 forced
  software compensation.

**What to do:**
- Start the next revision from the BQ34Z100-R2 reference schematic and
  EVM layout in TI's datasheet, then justify each deviation in writing.
- Confirm VOLTSEL behavior at the BAT pin with the new divider *before*
  populating production boards.
- Move the Kelvin sense to true 4-terminal pads on the shunt.
- Bring REG25 and the analog ground reference inside the U1 keep-out
  region. Do not share the digital return.

---

## 6. A Working Thermistor

**Recommendation:** Add a functioning NTC thermistor on the BQ34Z100-R2's
TS pin, mounted thermally close to the battery pack — not the PCB.

**Why it matters:**
- The current board reports an internal die temperature, which tracks
  ambient PCB temperature, not pack temperature. For LiFePO4 SOC
  estimation this is the wrong number.
- During competition the pack temperature climbed well above board
  temperature, and the gauge had no idea — SOC stayed optimistic for too
  long and the robot dropped out under load.
- The BQ34Z100-R2 explicitly supports an external 103AT-style NTC on TS
  and uses it for both temperature compensation and SOC correction.

**What to do:** Route a JST or 2-pin Phoenix header off the board to a
remote 10 kΩ NTC that sits on the pack itself. Configure the gauge
(`Temperature Mode` in Data Flash) to read the external TS input instead
of the internal die sensor. Verify the readback in `pcb_diagnostics.py`
before declaring the board calibrated.

---

## Closing Notes

A protective enclosure for every deployed board is now mandatory — that
was the single biggest lesson from the R2 failure. The recommendations
above are the *electrical* half of the same story. If you do nothing else,
do the shunt, the e-fuse, and the external thermistor — those three alone
would have prevented most of what we saw this year.

Good luck. Ask questions early, populate one board at a time, and verify
every rail with a multimeter before applying full pack voltage.

— The 2025–2026 AutoNav Electrical Team
