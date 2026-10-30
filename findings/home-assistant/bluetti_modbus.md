# bluetti_modbus (Home Assistant core bd8b1bc)

## What HA reads
- HA pins `bluetti-modbus==0.52.0`. The local checkout (upstream/lib/bluetti-modbus, f5f8401) is tagged 0.52.0, so it matches.
  Transport: `modbus-connection[tmodbus]==4.12.6`. The local checkout (upstream/lib/modbus-connection, 2d29ba2) is tagged 4.12.6, so it matches.
- HA supports only the Balco 260. The config flow checks that `d_inverter_type` (50200, 6 registers) is "Balco260", and the unique ID is `d_serial` (50206, u64).
  The integration only reads (it has no writes). It leaves out the writable settings, alarm and fault bitmaps, the unit-250 pack summary, phases 2 and 3, and the pack and IoT identity
  (const.py EXCLUDED_FIELDS).
- It exposes 41 sensors. These are the 50001-50022 summary block, grid and AC phase 1, inverter 1 V/A, the PV count and PV1-4 (type, P, V, I), and the pack
  values: V, I, SOC, SOH, cycles, cell and NTC counts, and charged and discharged energy (Wh). The firmware versions go into DeviceInfo.
- Library decode: all multi-word values use low word first. Strings use low byte first. `b_c` (51220) = abs(raw-30000)*0.1 A.

## Reference
- ModbusSpec devices/bluetti/balco260.yaml comes **only from this library** (sources: bluetti-modbus). No manufacturer document exists locally.
  modbus-docs has no BLUETTI entry. The library cites "Bluetti-Open-Modbus-TCP-register-list.xlsx"
  (bluetti-official/bluetti-modbus-tcp-slave), which was not downloaded, as the brief requires. So nothing could be checked against a manufacturer document. The ModbusSpec
  file matches the library on every point but one: b_c.

## Findings

### 1. The battery current direction is thrown away. HA shows only the magnitude (medium)
- Where: bluetti-modbus 0.52.0, src/bluetti_modbus_lib/fields/custom_fields.py:113-131 (`reference_offset_current`,
  `convert=lambda raw: abs(raw - reference) * 0.1`), used by devices/balco260.py:465. HA uses it as-is:
  ha-core homeassistant/components/bluetti_modbus/sensor.py:272-279 (`b_c`, "battery_current", MEASUREMENT, A).
- What it does: it decodes 51220 as |raw-30000|*0.1. A charging pack and a discharging pack at the same current read the same value.
- What is right: (raw-30000)*0.1 A, signed, with + for charging and - for discharging. ModbusSpec balco260.yaml:115 already has this: scale 0.1, offset -3000.
- Evidence: the library's own commit 0baa0f6 ("BLUETTI support confirmed the formula directly: raw values below 30000 mean
  discharging, above mean charging") and its docstring (custom_fields.py:119-122) say the direction *is* encoded. The
  docstring's next sentence, "the direction isn't encoded here", contradicts that. The real capture (issue #8) shows 30335 while charging,
  which fits. No manufacturer document is available locally.
- What the user sees: the "Battery current" sensor is always ≥ 0. Users can't tell charging from discharging, and templates that multiply it by
  battery voltage to get a signed battery power get the sign wrong whenever the battery discharges.
- Latent issue in the same helper: the NumberField has no `signed=False`, so it uses the default signed=True. A raw value of 32768 or more would fold negative and decode to more than 6000 A.
  That would take a charge current above 276.7 A, which a Balco 260 can't reach, so it has no practical effect.

### 2. pv_ac_e is shown as "unknown" for good when its real value is 0 (low, HA code)
- Where: ha-core sensor.py:186-194 (`value_fn=_nonzero`) together with const.py:72-73. That comment says pv_ac_count "Always 0 on the
  Balco 260 tested, whose four PV inputs are all DC".
- What it does: `_nonzero` turns 0 into None so that a 0 glitch doesn't look like a meter reset. On units with no AC-coupled PV the true total
  is 0, so the entity is unknown forever. `pv_ac_p` (sensor.py:147-153) is exposed too, and it always reads 0 there.
- What is right: show 0, or skip the glitch some other way (for example, only drop a 0 that follows a non-zero value).
- What the user sees: an "unknown" energy sensor on every Balco 260 without AC PV. It is cosmetic and does not affect energy statistics.
- Evidence: comments in the HA code itself. Confidence: medium that it happens; it is a minor issue.

### 3. Other cumulative counters have no guard against the 0 glitch (low, unverified)
- Where: sensor.py:154-185 (ac_o_e_total, pv_i_e_total, g_i_e_total, g_o_e_total), sensor.py:294-323 (b_cycle_count,
  b_i_e, b_o_e). All are TOTAL_INCREASING and use plain `_as_is`.
- HA guards only pv_ac_e against "reads 0 for a single poll now and then". pv_ac_e (50020-21) sits in its own read block (max_span 20 splits
  50001-50019 from 50020-50022), so the glitch could be specific to that block. If the device does the same in other blocks, any 0 is taken as a
  meter reset, and the next real value counts the whole lifetime total again in the energy dashboard.
- Evidence: only HA's own comment. This is not shown for these registers. Low confidence. Listed so someone can check it, not as a confirmed bug.

### Library notes (not visible in HA, because HA excludes these fields)
- balco260.py:128-132 decodes g_1_i_p (50235) as UINT16, while the sibling register g_1_i_c (50237) is INT16. FP, which shares the
  Balco 260 register set, as well as EP2000 and PA030, decode g_1_i_p as INT16. With grid feed-in (g_o_switch) a negative grid power would read as about 65 kW.
  ModbusSpec balco260.yaml:57 copies u16. HA excludes g_1_i_p (const.py:76), so HA is not affected. ModbusSpec should be checked against the
  official register list.
- Within the library, Balco 500 (balco500.py:453, unsigned 0.1 A, hardware-confirmed in bda615a) and EP2000 (int16 0.1 A) decode 51220 differently from the Balco 260.
  HA supports only the Balco 260, so this has no effect there.

## Checked without finding anything
Every one of the 41 HA sensors was checked for address, width, signedness, scale, unit, device and state class, and enum table (InverterStatus 0-7, PvType
0-3/100/101). Also checked: the 32-bit totals (count 2, low word first), the u64 serial, the version packing, nibble decode of 50267, string byte order, the error and
retry path (all raised types are ModbusError subclasses that HA catches), the config-flow model check and unique ID, and the read-plan span
(20) and gap (5). An unknown enum value decodes to None and shows as unknown rather than raising.
