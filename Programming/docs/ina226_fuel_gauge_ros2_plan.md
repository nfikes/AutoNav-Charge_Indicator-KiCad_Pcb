# INA226 Coulomb Counter — ROS2 Implementation Plan

## Overview

Rework the `autonav_electrical_publisher` ROS2 node to use the INA226 as a full
fuel gauge with high-frequency coulomb counting. The BQ34Z100-R2 is on hold
pending TI ecosystem research, so the INA226 must handle voltage, current,
SOC estimation, and charge state detection.

**Target repo:** `AutoNav_25-26` branch `origin/feature/electrical-publisher`
**Reference code:** `AutoNav-Charge_Indicator-KiCad_Pcb/Programming/scripts/ina226_fuel_gauge.py`

---

## 1. Dual-Timer Architecture

**Fast timer (300Hz)** — internal coulomb counting, no ROS2 publishing:
- Reads ONLY current register (0x04) — single 2-byte I2C read
- Integrates current x dt into `coulomb_mah_` accumulator
- Applies Peukert correction (discharge) or 99.5% coulombic efficiency (charge)
- Dead zone: skip integration below 50mA to filter noise

**Slow timer (10Hz)** — full measurement + publish:
- Reads voltage (0x02), current (0x04), power (0x03)
- Runs charge state machine
- Publishes `sensor_msgs/BatteryState` on `/electrical/battery_state`
- Publishes legacy Float32 topics (`/electrical/voltage`, `/electrical/current`, `/electrical/power`)
- Runs BMS protection checks with throttled warnings

### Timing Budget

INA226 config `0x4207` (AVG=4, 140us conversion, continuous shunt+bus):
- Conversion cycle: 4 x (140 + 140)us = **1.12ms** -> 893Hz max
- At 300Hz (3.33ms budget): 1.12ms conversion + 0.55ms read (100kHz I2C) = 1.67ms — fits easily

---

## 2. INA226 Configuration Fixes

**Config register (0x00)** — currently NOT written, must add:
```
0x4207: AVG=4, VBUSCT=140us, VSHCT=140us, continuous shunt+bus
```
AVG=4 balances noise reduction vs speed. AVG=16 (current 0x4427) maxes at 153Hz — too slow.

**Calibration register (0x05)** — currently WRONG:
```
Bug:    0x0800 (2048) — assumes 10mOhm shunt
Fix:    0x06AA (1706) — correct for 12mOhm shunt R4
Formula: CAL = 0.00512 / (250uA x 0.012 Ohm) = 1706
```
Current readings are ~20% too high with the wrong CAL.

**Add MFG/DIE ID verification** on init:
- MFG ID (0xFE) must be 0x5449
- DIE ID (0xFF) must be 0x2260

---

## 3. Battery Constants (Renogy RBT2425LFP)

From datasheets (already extracted and verified):

| Parameter | Value |
|---|---|
| Capacity | 25,000 mAh (rated at 0.2C / 5A) |
| Config | 8S7P LiFePO4 |
| Charge target | 29.0V (CC-CV) |
| BMS overvoltage | 29.2V |
| BMS undervoltage | 20.0V |
| Tail current | 1.25A (charge complete) |
| BMS overcurrent | 27.5A |
| Peukert exponent | 1.05 |
| Peukert ref rate | 5,000 mA (0.2C) |

---

## 4. Coulomb Counter Algorithm

**Initialization:** Estimate SOC from voltage using LFP lookup table, set
`coulomb_mah = soc% x 25000`. Inaccurate in the flat 20-80% zone but
provides a starting point.

**Integration (every 300Hz tick):**
```
if |current| > 50mA:
    if discharging:
        eff_cap = 25000 x (5000 / |I|)^0.05     // Peukert
        delta = I x (25000 / eff_cap) x dt / 3600
    else:  // charging
        delta = I x 0.995 x dt / 3600
    coulomb_mah += delta
    clamp to [0, 25000]
```

**Recalibration:** When charge state reaches FULL (CV phase + tail current
<= 1.25A), reset `coulomb_mah = 25000` (100%). This is the only reliable
recalibration point for LFP.

---

## 5. Charge State Machine

```
States: IDLE, CHARGING_CC, CHARGING_CV, FULL, DISCHARGING

IDLE  ->  CHARGING_CC    when I > 100mA and V < 29.0V
IDLE  ->  DISCHARGING    when I < -100mA

CHARGING_CC -> CHARGING_CV  when V >= 29.0V
CHARGING_CV -> FULL         when I <= 1250mA (recalibrate coulombs to 100%)

FULL -> DISCHARGING      when I < -100mA
FULL -> IDLE             (stays FULL until discharge begins)

DISCHARGING -> IDLE      when -100mA < I < 100mA
```

---

## 6. LFP Voltage-to-SOC Lookup Table

Per-cell millivolts, interpolated linearly between entries:

| Cell mV | SOC % | Notes |
|---------|-------|-------|
| 3650 | 100 | Fully charged (CV phase complete) |
| 3450 | 99 | Just off charger |
| 3380 | 95 | Settling after charge |
| 3350 | 90 | |
| 3340 | 80 | |
| 3330 | 70 | LFP plateau begins |
| 3320 | 60 | |
| 3310 | 50 | |
| 3300 | 40 | |
| 3280 | 30 | LFP plateau ends |
| 3200 | 20 | |
| 3100 | 14 | Knee — voltage drops faster |
| 3000 | 9 | |
| 2900 | 5 | |
| 2800 | 3 | |
| 2600 | 1 | |
| 2500 | 0 | BMS cutoff |

Pack voltage is divided by 8 (cells in series) before table lookup.

---

## 7. ROS2 Message Strategy

**Primary:** `sensor_msgs/BatteryState` on `/electrical/battery_state` at 10Hz

| Field | Source |
|---|---|
| voltage | INA226 bus voltage (V) |
| current | INA226 current (A), negative = discharging |
| charge | coulomb_mah / 1000 (Ah) |
| capacity | Peukert-adjusted capacity (Ah) |
| design_capacity | 25.0 Ah |
| percentage | coulomb_mah / 25000 (0.0-1.0) |
| power_supply_status | Mapped from ChargeState enum |
| power_supply_health | GOOD / OVERVOLTAGE / DEAD from BMS checks |
| power_supply_technology | LIFE (4) |
| present | true if INA226 responding |
| cell_voltage | 8 entries, each = pack_V / 8 (estimate) |

**Legacy (backward compat):** Keep Float32 topics at 10Hz:
- `/electrical/voltage` (Volts)
- `/electrical/current` (Amps)
- `/electrical/power` (Watts)

These are consumed by `autonav_automated_testing` — must not break.

**No custom message needed** — BatteryState covers all fields.

---

## 8. BMS Warnings

Use `RCLCPP_WARN_THROTTLE` with 10s window (prevents log spam):
- **Overvoltage**: V >= 29.2V -> `POWER_SUPPLY_HEALTH_OVERVOLTAGE`
- **Undervoltage**: V <= 20.0V -> `POWER_SUPPLY_HEALTH_DEAD`
- **Overcurrent**: |I| >= 27.5A -> `POWER_SUPPLY_HEALTH_UNSPEC_FAILURE`

Health field in BatteryState provides programmatic access.

---

## 9. Files to Modify

All in `AutoNav_25-26` repo, branch `feature/electrical-publisher`:

| File | Change |
|---|---|
| `.../src/electrical_publisher.cpp` | Major rewrite: dual timers, coulomb counter, state machine, BatteryState |
| `.../CMakeLists.txt` | Add `sensor_msgs` to `find_package` and `ament_target_dependencies` |
| `.../package.xml` | Add `<depend>sensor_msgs</depend>` |
| `.../launch/electrical_publisher.launch.py` | Add `sample_rate`, `i2c_device`, `i2c_address`, `initial_soc` params |

No changes to `autonav_interfaces` (no custom messages needed).

---

## 10. Launch Parameters

| Parameter | Default | Description |
|---|---|---|
| `publish_rate` | 10.0 | Slow timer Hz (existing) |
| `sample_rate` | 300.0 | Fast timer Hz for coulomb counting (NEW) |
| `i2c_device` | `/dev/i2c-7` | I2C bus path (NEW) |
| `i2c_address` | 64 (0x40) | INA226 address, decimal (NEW) |
| `initial_soc` | -1.0 | Override initial SOC %, or -1 for auto (NEW) |
| `low_battery_threshold` | 22.0 | Low battery warning voltage (existing) |
| `critical_battery_threshold` | 20.0 | Critical battery voltage (existing) |

---

## 11. Implementation Sequence

1. Fix CAL register (0x0800 -> 0x06AA)
2. Add config register write (0x4207) + MFG/DIE ID check
3. Add `sensor_msgs` dependency to CMakeLists.txt and package.xml
4. Refactor into dual-timer architecture (fast 300Hz + slow 10Hz)
5. Add I2C helper methods (write_register_16, read_register_s16/u16)
6. Implement coulomb counter (voltage_to_soc, peukert_capacity, integration)
7. Implement charge state machine
8. Implement BatteryState publishing + legacy Float32 topics
9. Add BMS warnings (throttled logging + health field)
10. Update launch file with new parameters
11. Test on Jetson with real battery

---

## 12. Testing Strategy

**Bench (before Jetson):**
- Run `ina226_fuel_gauge.py` with known supply voltages, verify SOC table
- Sweep 20V->30V->20V, confirm SOC_V tracks correctly (already verified)

**Build & launch on Jetson:**
```bash
colcon build --packages-select autonav_electrical_publisher
ros2 launch autonav_electrical_publisher electrical_publisher.launch.py
```

**Verify topics:**
```bash
ros2 topic hz /electrical/battery_state      # Should show ~10Hz
ros2 topic echo /electrical/battery_state     # Check all fields
ros2 topic echo /electrical/voltage           # Legacy compat
```

**Integration test:**
- Run DAQ system, verify `data_publisher.cpp` still receives Float32 messages
- Charge cycle: watch IDLE -> CC -> CV -> FULL transition
- Discharge: confirm coulomb counter decreases, current reads negative

**Known risks:**
- ROS2 timer jitter at 300Hz — mitigated by using actual dt, not assumed dt
- I2C bus contention — 300Hz reads use ~17% bus at 100kHz, manageable
- LFP flat curve — voltage SOC unreliable 20-80%, coulombs are primary after init
- Coulomb drift — recalibrates at every full charge, bounded to 1 day's error
