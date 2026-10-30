# Unit u5b: evcc meter templates (evcc bf5c276)

Files: sofarsolar-g3, sofarsolar, solaredge-hybrid, solaredge-inverter, solarlog, solarmax-inverter-smt, solarmax-maxstorage
(all under templates/definition/meter/).

## Bugs

### 1. sofarsolar-g3: PV4 power reads the PV4 current register
- Where: templates/definition/meter/sofarsolar-g3.yaml:146 (`address: 0x58E #Power_PV4`, uint16, scale 10)
- evcc: reads 0x058E and treats it as PV4 power in 10 W units.
- Right: Power_PVn starts at 0x0586 with a stride of 3 (0x0586, 0x0589, 0x058C, 0x058F). 0x058E is Current_PV4 (U16, 0.01 A).
  Power_PV4 is 0x058F.
- Evidence: SofarSolar Modbus Communication Protocol G3, three-phase, V1.22 (2023-11-29), sheet "Address Description",
  rows 174–176 (Voltage_PV1–16 0x0584, Current_PV1–16 0x0585, Power_PV1–16 0x0586, "addresses start at 0x0586, every 3
  addresses one channel"). ModbusSpec devices/sofar/inverter.yaml:297 (1422 = Current_PV4) and :298 (1423 = Power_PV4).
- Effect: on inverters with a 4th MPPT, PV power gets PV4 current in centiamps × 10 added. For example 8 A turns into 8000 W,
  so PV power is far too high. Inverters without PV4 read 0 and aren't affected.
- Confidence: high.

### 2. sofarsolar (2017 protocol): grid power decoded as int32 across two registers with scale -0.01
- Where: templates/definition/meter/sofarsolar.yaml:32-35 (`0x0212`, decode int32, scale -0.01)
- evcc: reads 0x0212 and 0x0213 (Feed in/out power and Power of the load) as one int32, then multiplies by -0.01.
- Right: 0x0212 is int16 in units of 0.01 kW (so ×10 for W). 0x0213 is a separate register (load power).
  Result in W = −raw(0x0212) × 10 (with ModbusSpec's assumption that + = export).
- Evidence: SOFARSOLAR ModBus-RTU Communication Protocol (2017-11-27), page 10: "0x0212 Feed in/out power int 16
  -10-10 KW 0.01KW" and "0x0213 The power of load Uint 16 0.01KW". ModbusSpec devices/sofar/old.yaml:166 (530, s16, W, scale 10).
- Effect: grid power ≈ raw × 655.36 instead of raw × 10, so it is about 65× too large, plus 0.01× the raw load value.
  Load management and surplus charging get nonsense grid values.
- Confidence: high, as far as the 2017 document matches the devices this template is used for (sofar-modbus, solarman and
  solax-modbus in ModbusSpec read 0x0212 as a single register too).

### 3. sofarsolar (2017 protocol): PV power scaled to kW instead of W
- Where: templates/definition/meter/sofarsolar.yaml:71-74 (`0x0215`, uint16, scale 0.01)
- evcc: raw × 0.01, which is kW, but evcc expects W.
- Right: 0x0215 "The power of generation" is Uint16 in units of 0.01 kW, so W = raw × 10.
- Evidence: same document, page 10 ("0x0215 The power of generation Uint 16 0-10 KW 0.01KW"). ModbusSpec
  devices/sofar/old.yaml:169 (533, u16, W, scale 10).
- Effect: PV power is shown 1000× too small (for example 5 kW shows as 5 W), so there is effectively no PV surplus.
- Confidence: high.

### 4. solaredge-hybrid: curtail ORs in bit 0 of Export Control Mode without clearing bits 1–2
- Where: templates/definition/meter/solaredge-hybrid.yaml:178-179 (`mode | 1 // ... preserve other bits`); also
  line 155 (`mode &^ 1`).
- evcc: sets bit 0 (direct export limitation) and keeps all other bits.
- Right: in Export Control Mode, bits 0–2 select the meter or limit type, and "Only single selection is allowed on bits 0-2".
  Bits 10–11 may be combined.
- Evidence: SolarEdge Technical Note "Power Control Open Protocol for SolarEdge Inverters" V1.3 (Nov. 2017), Export Limit
  Control Block, page 15. ModbusSpec devices/solaredge/control.yaml:73 (note "Only one of bits 0–2") and :206.
- Effect: a site set up for indirect limitation (consumption meter, bit 1) or production limitation (bit 2) ends up with
  bits 0+1 or 0+2. That combination is invalid, and with a consumption meter direct limitation reads the wrong meter.
  Related, not covered by the document: curtail(100) clears bit 0 and curtail(<100) overwrites the site limit (0xE002) and
  forces limit mode Total (0xE001). This can remove or change an export limit the installer set at commissioning.
- Confidence: medium (only bites when bits 1 or 2 are already set).

### 5. solaredge-inverter: writes "Commit Power Control Settings" after every dynamic power-limit write
- Where: templates/definition/meter/solaredge-inverter.yaml:140-148 (writes 1 to 61696 = 0xF100 after 0xF001)
- evcc: after each Active Power Limit write (0xF001), it writes 1 to 0xF100.
- Right: 0xF001 is a dynamic command ("does not require any reset", not saved). The commit register "performs the
  actual writing of the power control register map (Addresses 0xF102 and further)" and takes 5–10 s. 0xF001 needs no
  commit.
- Evidence: Power Control Open Protocol V1.3 (Nov. 2017), page 3 (dynamic power control, F001 Uint16 0-100 %; Global Control
  Block – Commit and Restore). ModbusSpec devices/solaredge/control.yaml:87 (persistent: false) and :89.
- Effect: each curtail step starts an unneeded 5–10 s commit of the stored power-control settings, which probably writes to
  non-volatile memory again and again. The limit itself works. Also, the documented prerequisites
  (AdvancedPwrControlEn 0xF142 = 1, ReactivePwrConfig 0xF104 = 4) are not mentioned in the template's requirements.
- Confidence: low-medium (the commit is harmless functionally; flash wear isn't documented).

## Checked, no difference
- sofarsolar-g3: grid PCC total, phase currents and powers (0x0488/0492/0493/049D/049E/04A8/04A9), Energy_Purchase_Total 0x068E,
  PV_Generation_Total 0x0686, PV1–3 powers, ActivePower_PV_Ext 0x04AE, Power_Bat1–8 and SOC_Bat1–8 (stride 7), signs
  (PCC + = export, so -10; Bat + = charge, so -10), mode 0x1110 values 0/3, passive block 0x1187–0x118C (I32 Gdes/Blo/Bup,
  + = charge, written as one block, negative values as two's complement). All match V1.22.
- sofarsolar: currents 0x0207/09/0B (int16 0.01 A), battery 0x020D (int16 0.01 kW, ×10, sign not stated in the document),
  SOC 0x0210, energies 0x021C and 0x0220 (u32 kWh). These match.
- solaredge-hybrid: 0xE174 power float (sign not in the document, + = charge is assumed by everyone), 0xE176/0xE17A u64 Wh
  low word first, 0xE184 SOE, 0xE00D modes 3/4/7, 0xE00E/0xE010 float32 W, 0xE144/0xE146, 0xE002 float W, 0xE001 = 0 Total.
  These match the Power Control Open Protocol 1.3 and the SunSpec logging note (word order).
- solaredge (both): SunSpec 203 meter signs and energies, 101/103 W and WH. These match the ModbusSpec solaredge meter/inverter.

## No independent reference (no manufacturer document locally)
- solarlog.yaml (3502 Pac, 3516 total yield Wh, 3518 consumption, input, uint32 low word first). Only evcc and OpenEMS
  agree (OpenEMS: s32).
- solarmax-inverter-smt.yaml (4151 u32 holding ×0.1 W). Only evcc and openWB agree.
- solarmax-maxstorage.yaml (110/114/118 s32 low word first, 122 SOC, writes 140/141/142). Only evcc and openWB agree.
  Note: "hold" writes 0 to both 140 and 141. If these are the charge and discharge limits, hold also blocks charging,
  unlike evcc's other hold implementations. This can't be decided without a document.
