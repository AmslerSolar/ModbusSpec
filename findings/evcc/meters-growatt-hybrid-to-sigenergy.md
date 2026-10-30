# evcc unit 4 (meter templates growatt-hybrid … sigenergy): findings

evcc checkout bf5c276; paths relative to templates/definition/meter/.

## Bugs / discrepancies (by confidence)

### 1. sigenergy.yaml:54 — grid import energy from a register that is now "Reserved" (and is inverter-level)
- evcc: grid `energy` = holding 30562, u64 ×0.01 kWh, read on the user's unit id (inverter), label "Accumulated import energy".
- Document: Sigenergy Modbus Protocol V1.7 (2024-04-09) lists 30562 "Accumulated import energy" in the *hybrid
  inverter* table (inverter's own counter, next to 30554 daily export, 30556 accumulated export, 30560 daily import).
  From V2.4 (2025-02-05, "Modified a few inverter's registers") through V2.9 (2026-05-13, §5.3 row 11) 30554 is
  "Reserved", 12 registers (30554–30565). The plant (unit 247) counter is 30216 "Total imported" U64 gain 100 kWh
  (V2.9 §5.1 row 105; also 30260 "new statistics interface"). ModbusSpec devices/sigenergy/plant.yaml:160 (doc),
  inverter.yaml:239 (evcc only).
- Effect: grid import energy wrong/zero on current firmware; even where answered it is the inverter's AC import, not the
  grid connection point.
- Confidence: high (document), effect on a real device: medium.

### 2. sigenergy.yaml:58-79 — grid currents are the inverter's own output phase currents
- evcc: grid `currents` = 31017/31019/31021 (s32 ×0.01 A) on the inverter unit id.
- Document V2.9 §5.3 (hybrid inverter running information) rows 58–60: "Phase A/B/C current" of the inverter's AC
  output ("when output type is L/N refers to phase current"); no grid-sensor current register exists (grid sensor gives
  only powers 30005, 30052–30056 at unit 247). ModbusSpec sigenergy/inverter.yaml:150-152.
- Effect: evcc shows/uses inverter output currents as grid (house connection) currents, e.g. for load management /
  circuits; with one of several inverters, only that inverter's share.
- Confidence: high.

### 3. sigenergy.yaml (all reads, e.g. :48, :55, :63, :86, :96) — read-only registers read with FC03
- evcc reads 30005, 30562, 30568, 30574, 30599, 30601, 31017–31021, 31035 as `type: holding`.
- Document V2.9 §3 legend: "RO — Read only, only support 0x04 command"; all these are RO in input-register tables.
  ModbusSpec plant.yaml / inverter.yaml put them in `table: input`.
- Effect: none if the firmware also answers FC03 (openWB also uses FC03, so it probably does); per document it should
  fail. Confidence: medium (document), low that users see it.

### 4. kostal-plenticore-gen2.yaml:44-52 — parameter reads ignore the `endianness` option
- The render uses `float32` when `endianness: big`, `float32s` otherwise (lines 81, 146, 158, 170, 182), but the param
  services for capacity (1068), minsoc (1042), maxsoc (1044), maxchargepower (1038), maxdischargepower (1040) always
  decode `float32s`.
- Right: follow register 5 / the option (KOSTAL: 0 = CDAB default, 1 = ABCD; ModbusSpec kostal/plenticore.yaml:58-66,
  :254-256).
- Effect: with `endianness: big` the UI/default values (capacity, SoC limits, max charge/discharge power used for the
  charge/discharge setpoints) are garbage. Confidence: high (code), affects only users who switched to ABCD.

### 5. kostal-plenticore-gen2.yaml:41 — maxacpower ignores the scale factor
- evcc reads 531 as u16 W. Document (KOSTAL Interface description MODBUS (TCP) & SunSpec, v2.9, DOC02308910-0020, via
  ModbusSpec kostal/plenticore.yaml:109): 531 "Inverter Max Power" with scale factor 532 (S16, 10^SF).
- Effect: wrong default maxacpower if SF ≠ 0. Confidence: low-medium (SF is usually 0).

### 6. growatt-min-tlxe.yaml:15, :23 — MIN TL-X read from the TL3/storage input group
- evcc reads input 35 (Pac, s32 ×0.1 W) and 55 (Eac total, u32 ×0.1 kWh) — input group 0–124.
- Document: Growatt Inverter Modbus RTU Protocol II V1.24, p.3 "Register range for various types of inverter":
  TL-X/TL-XH (MIN type) input ranges are 3000–3124 / 3125–3249 only; input 0–124 is listed for TL3-X (MAX/MID/MAC),
  storage MIX and others. MIN TL-X equivalents: 3023 Pac (u32 ×0.1 W), 3053 Epv_total (or Eac total in the 3000
  group). ModbusSpec growatt/inverter.yaml:1658, :1678 and note :2361.
- Counter-evidence: growatt-modbus and Growatt_ModbusTCP also read 35/55 for MIN models (ModbusSpec
  growatt/tl-x.yaml:518, :537), so older MIN TL-XE firmware probably still answers the legacy group.
- Effect: possible no-answer / exception 2 on MIN TL-X firmware that follows the document. Confidence: low.

### 7. huawei-smartlogger.yaml:82 — PV energy from an undocumented register
- evcc reads 40446 (s64 ×0.01 kWh) at unit 0.
- Document: SmartLogger ModBus Interface Definitions, Issue 35 (2020-02-20), §2: no 40446; plant energy is 40560
  "E-Total" U32 kWh gain 10. (40446 may come from a newer SmartLogger3000 document not available here.)
- Confidence: low (no evidence it is wrong, only undocumented in the available issue).
- Note on the same file :91: the doc says 40428 is U16 0–100 % and "stores data … issue at intervals not less than 1
  second" (persistent); evcc writes it as int16 (negative values per its own comment) — harmless for 0–100.

### 8. openems-modbus.yaml:184-194 — "normal" writes a 0 W discharge cap
- evcc writes `SetActivePowerLessOrEquals = 0` on normal (same as hold) and then stops the watchdog (reset: 1).
- Right: normal should release the constraint (write nothing); OpenEMS keeps a written setpoint until its API timeout,
  so for up to that timeout (default 60 s) "normal" blocks discharge like "hold".
- Evidence: FEMS App Modbus/TCP Read Access 2023.6.1 doesn't cover writes; semantics from OpenEMS channel name only.
  Confidence: low-medium.
- Version note: the FEMS document (ModbusSpec fenecon/fems.yaml:112) says the registers are holding (FC03); evcc reads
  power and SoC with FC04 (input). OpenEMS answers both, so no effect.

### 9. huawei-sun2000-hybrid.yaml:285-290 — curtailed reports 47418 also when the mode isn't "%"
- Script: percent unless mode == 0. Document (Solar Inverter Modbus Interface Definitions, Issue 05, 2023-02-16,
  row 145): 47415 modes 0 unlimited, 1 DI scheduling, 5 zero-power grid connection, 6 power-limited (kW), 7 power-limited
  (%); 47418 (row 147, INT16 %, gain 10, default 0) only applies in mode 7.
- Effect: with an installer-set kW limit (6) or DI scheduling (1), evcc reports the stale % register (default 0 % → "fully
  curtailed"). huawei-emma.yaml:198 does it right (`mode != 7`). Confidence: medium (code), low impact.

### 10. saj-h1.yaml:21 — grid power from 0x40A1 (CT_GridPowerWatt)
- Documented (SAJ Modbus Communication Protocol A ed. 7.1, Nov 2022, §4.2.2 R6 3-15K real-time data: 40A1H
  CT_GridPowerWatt int16 W; evcc's comment "undocumented" is outdated). No sign given in the doc.
- saj-h2-modbus reports newer H1 firmware leaves 0x40A1 at 0 and the meter phase powers 0xA03F/0xA045/0xA04B carry the
  grid power (ModbusSpec saj/h2.yaml:400) — project evidence only. Confidence: low.

## Disagreements without a manufacturer document (report only)
- saj-h1.yaml:55 / saj-h2.yaml:81 — 0x40A6 TotalBatteryPower used as + = discharge; saj-h2-modbus wiki says + = charge
  (ModbusSpec saj/h2.yaml:236, :404). SAJ doc gives no sign. If the wiki is right, battery power sign is inverted.
- powerdog.yaml:19-34 — evcc reads holding 40002/40026; openWB reads input 40000/40002/40024/40026 and builds the grid
  power from import (40024) and export (40000) instead of consumption − PV (ModbusSpec powerdog/datalogger.yaml:41-50).
- ibc-homeone.yaml:37-49 — grid meter powers decoded `int32s` (low word first) while all other 32-bit values of the same
  device use high word first; device is a Solplanet/AISWEI rebrand (same 1600/1604/1618/1621 map as
  solplanet-modbus.yaml, which takes grid power from 6433 int32). Suspicious, unverified.
- intilion-scalebloc.yaml:38-55 — per-phase powers at 6010/6012/6014 (stride 2) read as int16 ×100 W, while voltages
  (6000–6002) and currents (6006–6008) have stride 1; looks like 32-bit values or wrong addresses. Unverified.
- senergy.yaml:21 (lists SolarMax SP) reads 4151 PAC unscaled; solarmax-inverter-smt.yaml reads the same register ×0.1
  (openWB agrees for SMT). Different series, unverified.
- senergy-hybrid.yaml:97 — PV total energy 0x1021 unscaled while all other energies of the device are ×0.01. Unverified.

## Checked, consistent with the documents
- growatt-hybrid: 1021/1029, 1009/1011, 1014, 1046, 1054, 1/91, writes 1092 (AC charge) / 1102 — Growatt Protocol II
  V1.24/V1.39 (ModbusSpec growatt/inverter.yaml:1525-1618).
- huawei-sun2000-inverter, huawei-sun2000-hybrid (37113 sign > 0 feed-in → negated, 37119/37121, 37101–37136 gains,
  32064, 32108, 37760/37765/37780/37782, 37758 Wh, 37046/37048, 47075/47077/47081/47082/47083 [0,1440],
  47087, 47100 0/1/2, 47246 0 = duration, 47247/47249 kW gain 1000 = W, 47415/47418) — Issue 05.
- huawei-smartlogger meter 32272–32278 (gain 10 A, kW gain 1000), 32349/32357 I64 gain 100; 40521; battery unit
  1/2 registers 37001/37004/37068, 37743/37738/37755 — SmartLogger Issue 35 / inverter Issue 05.
- kostal-ksem-inverter 252 float CDAB (default byte-order register 5 = 0), sign + = import — KOSTAL doc via ModbusSpec.
- openems-modbus 302/315/327/359/367/415 — FEMS Read Access 2023.6.1.
- saj-r5 275 / 305 — SAJ R5 protocol (ModbusSpec saj/r5.yaml:121, :149).
- sigenergy 30005 (> 0 buy from grid), 30568/30574, 30599, 30601 gain 10, 31035, 40046/40048 gain 10 — V2.9.

## Summary
Checked 31 templates (plus marstek-batterymode.tpl); 19 have no independent manufacturer reference (hager-flow,
huawei-emma, huawei-meter, ibc-homeone, intilion-scalebloc, marstek ×3, mypv-wifi-meter, plexlog, powerdog,
roche-energy-rel261, sax, schneider-micrologic, senergy, senergy-hybrid, sermatec-hybrid, siemens-7kt1665,
siemens-junelight); kostal-plenticore-gen2 and saj-h1/h2 only partly.
