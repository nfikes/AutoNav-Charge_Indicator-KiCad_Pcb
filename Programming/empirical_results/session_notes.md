# Discharge Test Session Notes

## Session 1 — Battery A (2026-04-01)
- **Battery**: Renogy RBT2425LFP, started at 100% (charger confirmed)
- **Load**: Robot idle, ~1.19A average
- **Duration**: 2h 01m
- **CSV**: discharge_log_20260401_175518.csv
- **Start**: 26,558 mV under load (3,320 mV/cell)
- **End**: 26,238 mV under load (3,280 mV/cell), 2.395 Ah discharged, 90.4% SOC
- **Rested OCV after disconnect**: 26.54V (3,318 mV/cell) — measured with Keysight U1233A
- **IR drop observed**: 302 mV pack (26,238 → 26,540 mV) at 1.19A = ~254 mOhm total path
- **Notes**: Voltage barely moved over 2 hours — deep in LFP plateau.
  Next session pick up from 90.4% SOC / 2.395 Ah discharged.

## Calibration Points (OCV, rested)
| SOC (%) | OCV (mV) | Cell OCV (mV) | Source |
|---------|----------|---------------|--------|
| 100.0   | ~26,558  | ~3,320        | First reading under light load |
| 90.4    | 26,540   | 3,318         | Multimeter after 2h discharge |
