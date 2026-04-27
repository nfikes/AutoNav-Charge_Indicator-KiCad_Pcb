# Risk Zone Key — Rev 3 Metal Shaving Analysis

| # | Severity | Components | Pairs | Nets at Risk | Reason |
|---|----------|------------|-------|--------------|--------|
| 1 | CRITICAL | U5 | 2 | +5v, GND | +5V/GND short through LDO — only 1.5V margin on 6.5V abs max input |
| 2 | CRITICAL | C1 | 1 | BAT+, GND | Direct battery-to-ground short through bulk capacitor pads |
| 3 | CRITICAL | C8 | 1 | +5v, GND | Power rail short through decoupling cap near BQ34Z100 |
| 4 | CRITICAL | C10 | 1 | +5v, AGND | +5V to analog ground short — corrupts BQ34Z100 analog reference |
| 5 | CRITICAL | J1 | 2 | +5v, SCL, SDA, GND | I2C connector — power and I2C signals adjacent, latch-up risk for BQ34Z100 (500V HBM) and INA226 |
| 6 | CRITICAL | C5 | 1 | +3v3, GND | 3.3V rail short — kills INA226 supply and I2C pull-ups |
| 7 | CRITICAL | C5, U3 | 1 | +3v3, GND | 3.3V decoupling cap adjacent to INA226 GND pad |
| 8 | CRITICAL | U3 | 12 | +3v3, Alert, BAT+, SCL, SDA, GND | INA226 internal pad shorts — 12 different net pairs within 0603 reach. SCL max only VS+0.3V (3.6V). Confirmed latch-up failure on R2 board |
| 9 | CRITICAL | R3, U3 | 2 | SCL, SDA, GND | FB divider ground resistor adjacent to INA226 I2C pads — shorts I2C to ground |
| 10 | CRITICAL | R3 | 1 | GND, FB | Feedback divider ground tied to FB — forces buck to wrong output voltage |
| 11 | CRITICAL | Q1 | 2 | BAT+, D1-A, Q1-D | P-FET drain (BAT+) adjacent to gate/source — gate oxide breakdown if BAT+ exceeds ±20V VGS max |
| 12 | CRITICAL | U2 | 4 | BAT+, GND, BOOT, FB, SW | Buck converter internal pad shorts — FB (5.5V max) adjacent to VIN (BAT+). Confirmed failure on R2 board |
| 13 | CRITICAL | Q1, R28 | 1 | BAT+, D1-A | BAT+ from Q1 drain bridging to zener anode |
| 14 | CRITICAL | Q1, U2 | 1 | BAT+, SW | Q1 BAT+ to buck switch node — injects battery voltage into switching node |
| 15 | CRITICAL | R6 | 1 | +3v3, SDA | 3.3V shorted to SDA — overvoltage on INA226 SDA, latch-up on BQ34Z100 |
| 16 | CRITICAL | R28 | 1 | BAT+, D1-A | Both pads of R28 bridge BAT+ to zener network |
| 17 | CRITICAL | D1, R28 | 1 | BAT+, D1-A | Zener cathode (BAT+) to anode — bypasses voltage clamp |
| 18 | CRITICAL | R5 | 1 | +3v3, SCL | 3.3V shorted to SCL — overvoltage on INA226 SCL (max VS+0.3V), latch-up risk |
| 19 | CRITICAL | D1 | 1 | BAT+, D1-A | Zener diode pads bridge BAT+ across clamp |
| 20 | CRITICAL | C2, C4 | 1 | BOOT, FB | Boot cap to FB cap — corrupts both buck bootstrap and feedback |
| 21 | CRITICAL | C4 | 1 | C3-Pad1, FB | Cap net adjacent to FB — injects wrong voltage into feedback |
| 22 | CRITICAL | R2 | 1 | R1-Pad2, FB | Feedback divider resistor pads — wrong divider ratio, wrong output voltage |
| 23 | HIGH | R31 | 1 | REG25, VEN | BQ34Z100 internal regulator output shorted to voltage enable — corrupts IC power management |
| 24 | HIGH | C8, U1 | 1 | AGND, GND | Analog ground to digital ground short near BQ34Z100 — ground loop noise |
| 25 | HIGH | C10, C9 | 1 | +5v, VTRANS | +5V rail injected into battery voltage translation — corrupts fuel gauge reading |
| 26 | HIGH | R20, R21 | 1 | BAT-, GND | Sense return shorted to ground — bypasses current sense resistor |
| 27 | HIGH | U1 | 9 | +5v, P1, P2, VTRANS, REG25, VEN | BQ34Z100 QFN pad shorts — 500V HBM ESD rating, dense pad array mixes power and signals |
| 28 | HIGH | C9 | 1 | VTRANS, AGND | Battery sense voltage shorted to analog ground — zero voltage reading |
| 29 | HIGH | U6 | 5 | ENABLE, VTRANS, GND, V+ | Op-amp internal pad shorts — ENABLE and VTRANS adjacent, corrupts voltage divider control |
| 30 | HIGH | R22, U6 | 1 | VTRANS, GND | Voltage translation signal grounded at op-amp input |
| 31 | HIGH | Q2 | 2 | ENABLE, GND, Q2-D | N-FET gate (ENABLE) adjacent to source (GND) — uncontrolled FET state |
| 32 | HIGH | R19, U6 | 1 | ENABLE, VTRANS | Enable signal cross-coupled with voltage translation |
| 33 | HIGH | R27, U6 | 1 | VTRANS, V+ | Voltage divider output shorted to op-amp non-inverting input reference |
| 34 | HIGH | R19 | 1 | ENABLE, GND | Enable pulled to ground — disables voltage divider MOSFET array |
| 35 | HIGH | SW1 | 1 | ENABLE, GND | Switch pads bridge enable to ground — same effect as #34 |
| 36 | MODERATE | R11 | 1 | SCL, D9-K | SCL series resistor to zener cathode — minor I2C impedance change |
| 37 | MODERATE | R10 | 1 | SDA, D8-K | SDA series resistor to zener cathode — minor I2C impedance change |
