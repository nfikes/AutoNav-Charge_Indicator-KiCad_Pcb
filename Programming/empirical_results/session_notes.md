# Discharge Test Session Notes

## Session 1 — Battery A (2026-04-01)
- **Battery**: Renogy RBT2425LFP, started at 100% (charger confirmed)
- **Load**: Robot idle, ~1.19A average
- **Duration**: 2h 01m
- **Frequency**: 0.1Hz (1 sample / 10 seconds)
- **CSV**: discharge_log_20260401_175518.csv
- **Start**: 26,558 mV under load (3,320 mV/cell)
- **End**: 26,238 mV under load (3,280 mV/cell), 2.395 Ah discharged, 90.4% SOC
- **Rested OCV after disconnect**: 26.54V (3,318 mV/cell) — measured with Keysight U1233A
- **IR drop observed**: 302 mV pack (26,238 → 26,540 mV) at 1.19A = ~254 mOhm total path
- **Rest before next session**: ~21 hours

## Session 2 — Battery A (2026-04-02)
- **Load**: Suspended spinning (motors, wheels in air), ~1.87A average
- **Duration**: 2h 01m
- **Frequency**: 0.4Hz (1 sample / 2.5 seconds)
- **Start**: 90.4% SOC, 26,338 mV under load
- **End**: 26,083 mV under load (3,260 mV/cell), 6.150 Ah discharged, 75.4% SOC
- **Rest before next session**: ~18.5 hours

## Session 3 — Battery A (2026-04-03)
- **Load**: Suspended spinning (motors, wheels in air), ~2.37A average
- **Duration**: 6h 01m
- **Frequency**: 0.4Hz (1 sample / 2.5 seconds)
- **Start**: 75.4% SOC, 26,326 mV under load
- **End**: 24,162 mV under load (3,020 mV/cell), 19.852 Ah discharged, 20.6% SOC
- **Rested OCV after disconnect**: 24.55V (3,069 mV/cell) — measured with Keysight U1233A
- **IR drop observed**: 388 mV pack (24,162 → 24,550 mV) at 2.27A = ~171 mOhm
- **Note**: IR recovery larger than session 1 (388 vs 302 mV) — internal resistance increases at low SOC

## Session 4 — Battery A (2026-04-04)
- **Load**: Driving forward motion + suspended spinning, ~2.5A average
- **Duration**: ~15 min (BMS cutoff reached)
- **Frequency**: 0.4Hz (1 sample / 2.5 seconds)
- **Start**: 20.6% SOC, ~24,100 mV under load
- **End**: BMS cutoff at 22,522 mV (2,815 mV/cell), 20.476 Ah discharged
- **BMS cutoff voltage**: 22.5V (2,815 mV/cell) — higher than spec'd 20V (2,500 mV/cell)
- **Note**: BMS disconnected instantly, last valid sample followed by 4,117 mV reading

## Summary — Full Discharge (Sessions 1-4)
- **Total Ah discharged**: 20.476 Ah
- **Rated capacity**: 25.0 Ah
- **Usable capacity**: 20.476 Ah (**82% of rated**)
- **SOC rescaled**: 0% = BMS cutoff (20.476 Ah), 100% = fully charged
- **Total discharge time**: ~10h 18m across 4 sessions over 4 days

## Calibration Points (OCV, rested, Keysight U1233A)
| SOC (%) | OCV (mV) | Cell OCV (mV) | Source |
|---------|----------|---------------|--------|
| 100.0   | ~26,558  | ~3,320        | First reading under light load |
| 90.4    | 26,540   | 3,318         | Multimeter after session 1 |
| 20.6    | 24,550   | 3,069         | Multimeter after session 3 |

## IR Resistance vs SOC
| SOC (%) | IR Drop (mV) | Current (A) | R_path (mOhm) |
|---------|-------------|-------------|----------------|
| 90.4    | 302         | 1.19        | 254            |
| 20.6    | 388         | 2.27        | 171            |

Note: R_path at 20.6% appears lower because the higher current causes more
diffusion overpotential (not captured by simple IR model). True ohmic resistance
likely increased but is masked by the diffusion component.

## Empirical Lookup Table — Cell OCV (mV) vs SOC (%)

Extracted from 12,054 IR-compensated data points (Battery A full discharge).
Median cell voltage at each 5% SOC step. Monotonic, directly invertible.

| SOC (%) | Cell OCV (mV) | Pack OCV (mV) |
|---------|---------------|---------------|
| 100.0   | 3323          | 26,584        |
| 97.5    | 3322          | 26,576        |
| 95.0    | 3321          | 26,568        |
| 90.0    | 3320          | 26,560        |
| 85.0    | 3319          | 26,552        |
| 80.0    | 3318          | 26,544        |
| 75.0    | 3313          | 26,504        |
| 70.0    | 3307          | 26,456        |
| 65.0    | 3290          | 26,320        |
| 60.0    | 3288          | 26,304        |
| 55.0    | 3287          | 26,296        |
| 50.0    | 3284          | 26,272        |
| 45.0    | 3281          | 26,248        |
| 40.0    | 3276          | 26,208        |
| 35.0    | 3269          | 26,152        |
| 30.0    | 3260          | 26,080        |
| 25.0    | 3248          | 25,984        |
| 20.0    | 3232          | 25,856        |
| 15.0    | 3211          | 25,688        |
| 10.0    | 3196          | 25,568        |
| 7.5     | 3179          | 25,432        |
| 5.0     | 3138          | 25,104        |
| 2.5     | 3044          | 24,352        |
| 0.0     | 2922          | 23,376        |

- **IR compensation**: OCV = V_measured + |I| × 0.254 Ω (apply before lookup)
- **Usable capacity**: 20.476 Ah (82% of 25 Ah rated)
- **0% SOC** = BMS cutoff (~2815 mV/cell under load, ~2971 mV/cell OCV)
- **80-100% plateau**: Only 4 mV span — voltage cannot distinguish SOC in this range
- **Use for**: initial SOC estimation when connecting a new Renogy RBT2425LFP battery
- **Primary SOC method**: coulomb counting (this table supplements it)
- **Why not a polynomial?** LFP's flat plateau makes high-order polynomials non-monotonic,
  giving multiple SOC values for one voltage. A lookup table is guaranteed invertible.
