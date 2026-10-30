# Home Assistant `solaredge_modbus`: findings (read only)

HA core bd8b1bc, `homeassistant/components/solaredge_modbus/` pins `solaredged==0.5.0`. The local checkout
`upstream/lib/solaredged` is at tag v0.5.0 (c80f8a8), so it is the version HA uses. Field types and sentinels come
from `modbus-connection` (`model/sunspec`).

References:
- ModbusSpec `devices/solaredge/{inverter,meter,battery,control}.yaml`
- SolarEdge Technical Note "Power Control Protocol for SolarEdge Inverters" v1.3 (Nov 2017) (local ef2bbde6….pdf):
  sections "Register Mapping – Power Control Data" (pp. 3–7), "StorEdge Control and Status Block" (pp. 15–20)

## Bug candidates

### 1. `AdvancedPowerControl.enabled` reads the wrong register (library)
- Where: solaredged `src/solaredged/components.py:832` `_enabled = int32_le(61704, …)` (0xF108). `set_enabled()`
  writes 61762 (0xF142).
- Right: AdvancedPwrControlEn is at 0xF142 (Int32, 0–1). See the Power Control Block table on p. 4 and the steps on
  pp. 3, 15 and 24. 0xF108 is "ActivePwrGradEn" (wakeup gradient enable, p. 7). ModbusSpec control.yaml:
  61704 = x.active_power_gradient, 61762 = x.advanced_power_control.
- Effect: `enabled` reports the wakeup-gradient flag, not whether grid control is enabled. In HA this only shows in
  diagnostics (`diagnostics.py:97`), where it can mislead whoever is debugging why power-limit writes have no effect.
  Library users get wrong state, and read-back after `set_enabled()` does not match.
- Confidence: high.

### 2. `AdvancedPowerControl.set_reactive_power()` writes the power-limit register (library)
- Where: `components.py:850-852` writes a float32 "fixed reactive-power value" to 61760 (0xF140).
- Right: 0xF140 is "PowerReduce", Float32 0–100 %, the inverter active power limit (p. 6, Active Power
  configuration). Fixed reactive power is "FixedReactPwr" at 0xF10C (Float32 VAR, p. 5). ModbusSpec control.yaml:
  61708 = x.fixed_reactive_power, 61760 = x.power_reduce.
- Effect: a caller setting e.g. 500 var instead sets a persistent active-power limit of 500 % (out of range, likely
  refused at commit). A small value such as 0–100 would cap the inverter's production after `commit()`. HA does not
  call this method today, so HA users are not affected.
- Confidence: high.

### 3. "Negative site limit" switch, but the site limit cannot be set below 0
- Where: HA `switch.py:41` exposes `negative_site_limit` (bit 11 of 0xE000). The `site_limit` number has
  `native_min_value=0` (`number.py:76-86`), and the library validator is `_at_least(0)` (`components.py:687`).
- Right: bit 11 "Negative Site Limit – Allows setting of negative site limit to allow minimum import power" (p. 15).
  The register table on p. 16 still gives "0-Max_Site Power" for 0xE002.
- Effect: a user can turn the flag on but cannot enter the negative limit it exists for, from HA or the library.
- Confidence: medium-low (the document contradicts itself).

### 4. Inverter status 8 named "standby" (enum meaning)
- Where: solaredged `const.py:90` `STANDBY = 8`. HA status sensor options (`sensor.py:303`).
- Right: SunSpec I_Status / SolarEdge note: 8 = "Maintenance / setup" (ModbusSpec inverter.yaml enum `status`).
- Effect: an inverter in setup or maintenance shows as "Standby".
- Confidence: medium. Arguably a label difference.

## Notes (not bugs by themselves)
- Active power limit (0xF001) and CosPhi (0xF002) are exposed as HA numbers unconditionally. The document (pp. 3–4)
  says dynamic control only works after AdvancedPwrControlEn=1 (0xF142), ReactivePwrConfig=4 (0xF104) and a commit
  (0xF100). HA neither does this nor tells the user, so a write can appear to do nothing.
- Signs are passed through unchanged:
  - meter `ac_power`: positive = export (ModbusSpec meter.yaml grid_power `positive: export`)
  - battery `dc_power`: positive = charge (battery.yaml)
  HA's energy-dashboard power conventions are the opposite (grid import +, battery discharge +), so users must invert
  these themselves.
- The meter energy counters are deliberately decoded with 0 as a valid value (SunSpec acc32 says 0 = not
  accumulated; ModbusSpec meter.yaml `invalid: [0]`). HA's `SolarEdgeModbusEnergySensorEntity` holds the highest
  value seen, so a transient 0 does not corrupt statistics. The same guard means a genuinely reset or replaced
  counter, or a single spurious high sample, keeps the sensor stuck at the old maximum.
- Battery 3 at base 0xE400 and battery status values 6 and 10 come from community sources. The document only
  defines batteries 1 (0xE100) and 2 (0xE200) and status values 0–5 and 7.

## Checked and matching the document / ModbusSpec
- Inverter:
  - common block 40000–40068
  - model 101–103 40069–40108: types, scale-factor registers, SunSpec sentinels
  - heatsink temperature 40103/SF 40106
  - AC energy acc32 40093/SF 40095
- Grid status extension 40113 (0 = on grid) and vendor status 40119.
- MMPPT model 160: header 40121–40130, modules from 40131 with stride 20, scale factors 40123–40126, meter shift
  10 + 20·N.
- Meters 1–3: 40121/40188, stride 174, 40190–40293 including scale factors. Event bits 2–7 match.
- Battery block 0xE100–0xE187: word-swapped float32, uint64 energies (Wh), status uint32.
- Storage control 0xE004–0xE011 (enums, float32 limits, uint32 timeout) and export control 0xE000–0xE003/0xE012
  (bitfield 0–2, 10, 11; limit mode 0/1).
- Power control 0xF000–0xF003; commit 0xF100, restore 0xF101, reactive power config 0xF104 (Int32).
