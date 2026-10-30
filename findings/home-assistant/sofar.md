# Home Assistant `sofar`: findings (read only)

HA core bd8b1bc, `homeassistant/components/sofar/` pins `sofar-modbus==0.25.0`. The local checkout
`upstream/lib/sofar-modbus` is at tag 0.25.0 (1208faa), so it is the version HA uses. HA only uses the
current-generation map (`sofar_modbus.modern`). The legacy map and the BTS pack block are not used by HA.

References:
- ModbusSpec `devices/sofar/inverter.yaml`
- SofarSolar "Modbus Communication protocol (G3, English, three-phase only)" V1.22 (2023-11-29), xlsx
  (local cd58fd06…xlsx), sheets "Address Description" and "Fault Bit Field Description"

## Bug candidates

### 1. Serial number read 2 characters short (library), used as the HA unique id
- Where: sofar-modbus `src/sofar_modbus/modern/inverter.py:140` `serial_number = string(0x0445, 7)`. HA uses it as
  the config-entry unique id (`config_flow.py:130`, `:198`) and device serial.
- Does: reads 7 registers (14 characters), 0x0445–0x044B.
- Right: the document gives Serial_Number0–7 as 0x0445–0x044C, "8, indicating serial number bits 1-16". Characters
  17–20 are at 0x0470–0x0471. ModbusSpec `devices/sofar/inverter.yaml:242` has length 8 and `x.serial_ext` (0x0470,
  line 248). Its conflict entry shows only sofar-modbus and solax-modbus using 7.
- Effect: a serial longer than 14 characters is cut off in the device info and unique id. The serial-prefix model
  detection still works because the prefixes are short.
- Confidence: medium. The document is clear. Many real serials are 14 characters, so for those the 8th register is
  only padding.

### 2. Active-power-limit write is shorter than the block the document requires
- Where: sofar-modbus `modern/settings.py:86` writes `[Power_Control, Active_Power_Export_Limit]` as 2 registers
  at 0x1105. HA calls this through the `set_active_power_limit` service (`services.py:138-140`).
- Right: the remark for the 0x1105 "Power control" group (0x1105–0x110C) says: "When writing, the first address is
  fixed to any address within this range, and the length is the length of the range."
- Effect: some firmware may reject a 2-register write (exception) or ignore it, so the service fails or does
  nothing. Untested.
- Confidence: low. The document rule is clear, but whether devices enforce it is unknown.

### 3. Feed-in limitation mode 3 ("phase power mode") is missing from the enum
- Where: sofar-modbus `modern/enums.py` `FeedinLimitationMode` has only 0–2 (`:527`). HA builds the sensor options
  and the `set_feed_in_limit` service modes from it (`sensor.py:1483`).
- Right: 0x1023 AntiReflux_Control. The CN and EN text both list `3: Phase power mode` (相功率模式). The min/max
  columns still say 0–2.
- Effect: an inverter set to mode 3 (from the app or the display) shows the HA "Feed-in limitation mode" sensor as
  unknown. The mode cannot be selected from HA.
- Confidence: low–medium. The document contradicts itself (text says 3, max column says 2).

### 4. Charger use mode offers value 7, which V1.22 does not have (version note)
- Where: `modern/enums.py:592` `FEED_IN_PRIORITY_MODE = 7`. The HA select `charger_use_mode` (`select.py:37`) offers
  all 8 members.
- Right: 0x1110 Energy_Storage_Mode_Control has 0–6 in the text and min/max 0–4.
- Effect: selecting "feed_in_priority_mode" (or 5/6 on firmware that only takes 0–4) may be refused by the device,
  and HA shows a write error.
- Confidence: low. This is probably newer firmware (the value came from the solax-modbus plugin), but nothing in
  V1.22 backs it.

## Minor / not user-visible
- 0x0417 Countdown is U16 in the document. The library reads `waiting_time` as signed (`inverter.py:88`, ModbusSpec
  conflict at inverter.yaml:228). HA does not expose it.
- Label only: 0x0418/0x0419 are "Temperature_Env1-2 / Ambient temperature" in the document. HA calls them "Inverter
  temperature 1/2" (`sensor.py:325`).
- SyncRtcResult has extra values 2 and 4 that are not in the document. They are harmless.

## Checked and matching the document
- 0x0404 SysState enum (0–9).
- Fault registers 1–30. Bit to ID mapping was compared with ModbusSpec flags. The only extras are the "Disable" bits
  (ID464, ID480) and ID441, and none of them is mapped to a fault category.
- Grid block 0x0484–0x04BD: types, scales (0.01 kW, 0.1 V, 0.01 A, 0.001 PF) and signs. 0x048B scale 0.1 kW.
- Off-grid block 0x0504–0x0527.
- PV 0x0584–0x05A1 and 0x05C4 (0.1 kW).
- Battery strings 0x0604–0x063B (I16 current and power).
- Totals 0x0667 (0.1 kW, charge positive), 0x0668–0x066A.
- Energy 0x0684–0x069A: U32, today 0.01 kWh, total 0.1 kWh. TOTAL_INCREASING with torn-read hold and restore seeding.
- Rated power 0x06ED.
- Settings 0x1023/1024 (block write of 2), 0x1029/102A (block write of 2), 0x1044–0x105A, DOD/EOD semantics
  (cut-off SOC = 100 − DOD/EOD), 0x1104, 0x1106 (×0.1 %, 0–1000), 0x1110.
- Passive 0x1184/1185 (write of 2) and 0x1187/1189/118B (I32 W, written as one 6-register block; grid power positive
  means grid to system, which matches the HA service text).
- System time write 0x1004 (7 registers).
