# Unit u5c: evcc Modbus findings

evcc commit bf5c276. Paths relative to upstream/evcc.

## Bug 1: solax-g2 reads 32-bit values with the wrong word order

- Where: templates/definition/meter/solax-g2.yaml:31 (grid power 1083, `int32`), :39 (grid import energy 1087, `uint32`), :57 (pv energy yield_total 1059, `uint32`).
- What evcc does: decodes them high word first (`int32` / `uint32`).
- What is right: low word first, so the decodes should be `int32s` / `uint32s`. evcc's own solax.yaml for G3/G4 already uses the `s` decodes.
- Evidence:
  - SolaX Power MIC-G2 three phase inverter Modbus-RTU comms protocol V1.9 (2022-09-21), input register table, page 12: "0x423 YieldTotal.LSB / 0x424 YieldTotal.MSB", "0x43B:LSB 0x43C:MSB" Int32 1 W, "0x43F:LSB 0x440:MSB" Uint32 0.01 kWh.
  - ModbusSpec devices/solax/x3-mic-g2.yaml:30-32 (`word_order: little`), lines 75, 83 and 85, and note at line 117.
  - homeassistant-solax-modbus plugin_solax.py reads the same registers (0x423, 0x43B, 0x43F) with plugin-wide `order32="little"` (line 12771).
- User-visible effect: grid power is garbage, for example 500 W export reads as about 32.8 MW, and small imports read as tens of MW. Grid import energy and PV energy are also garbage. This breaks surplus charging on X3-MIC G2, X3-PRO G2 and Q.VOLT units. PV power (Pac, 16-bit) is not affected.
- Confidence: high.

## Bug 2: solax battery mode control writes the wrong registers on G3

- Where: templates/definition/meter/solax.yaml:174-226 (batterymode).
- What evcc does: writes 0x0020 = 0 (hold) or 1 (charge), then 0x001F = 3 ("manual mode"). The template is labelled "Hybrid X1/X3 G3/G4".
- What is right: this sequence is only correct for G4.
  - G4 (Hybrid X1&X3-G4 Modbus RTU V3.47, 2025-01-15, page 21): 0x001F 3 = Manual mode, and 0x0020 Manual mode (0 stop, 1 force charge, 2 force discharge).
  - G3 (Solax Hybrid X1&X3-G3 Modbus TCP&RTU V3.29, page 41): write 0x001F is SolarChargerUseMode, where 3 = FeedinPriority (0 Self use, 1 ForceTimeUse, 2 Back Up). Write 0x0020 is Battery1_MinCapcity in 1 % (0~100).
- User-visible effect on G3:
  - "hold" sets the battery minimum capacity to 0 % and switches to Feed-in Priority, so the battery is not held and can be discharged to empty.
  - "charge" sets the minimum capacity to 1 % and Feed-in Priority, so there is no grid charge.
  - "normal" restores the work mode but never the minimum capacity, so the user's discharge floor stays at 0 or 1 %. This is a deep-discharge risk.
- Evidence: G3 V3.29 page 41 (lines "0x001F SolarChargerUseMode … 3:FeedinPriority", "0x0020 Battery1_MinCapcity W Battery MinCapcity (0~100) 1%"). ModbusSpec devices/solax/inverter.yaml:857-858 has only evcc and solax-modbus as sources and no G3-specific write map.
- Confidence: high for the register facts. Medium on how many evcc users run G3 rather than G4.

## Bug 3: solax grid meter voltages and currents at 0x00CA–0x00D0 do not exist on G3

- Where: templates/definition/meter/solax.yaml:50-93 (currents 206-208, voltages 202-204).
- What evcc does: reads GridVoltage_R/S/T_Meter and GridCurrent_R/S/T_Meter for all G3/G4 models.
- What is right: these registers exist only in the G4 map.
  - G4 (Hybrid X1&X3-G4 Modbus TCP&RTU V3.36, 2024-06-11, page 33): 0x00CA–0x00CC are voltages and 0x00CE–0x00D0 are currents.
  - G3 (V3.29, input registers, page 20): 0x00CA BMS DischargeMaxCurrent, 0x00CB BatteryForceChargeFlag, 0x00CC–CD BMS energy throughput, 0x00CE BMS_RelayState, 0x00CF Battery_Tem_High, 0x00D0 Battery_Tem_Low.
  - ModbusSpec devices/solax/inverter.yaml:833-844 shows both meanings with their model lists.
- User-visible effect on G3: the phase "voltages" come out as the BMS discharge current limit and similar values, for example 25.0 V. The phase "currents" come out as the relay state and battery temperatures (for example 1.0 A, 2.5 A). These wrong currents feed evcc's circuit/load management and phase display.
- Confidence: high (documents). The impact depends on the G3 user base.

## Bug 4: solis-hybrid (RHI) battery power is negated but not signed

- Where: templates/definition/meter/solis-hybrid.yaml:93-100.
- What evcc does: power = −(input 33149, int32).
- What is right: 33149 should be combined with the direction register 33135 (0 = charge, 1 = discharge), as evcc's own solis-hybrid-s.yaml:112-133 does.
- Evidence:
  - The Solis RS485_MODBUS RTU Hybrid Inverter Protocol (ESINV-33000ID, V002B000D01B, translated 2020-09-15), 33149 row, gives only "S32 1<->1W" and no direction. It gives the direction in 33135 ("0: charge 1: discharge").
  - ModbusSpec devices/solis/inverter.yaml:297 and note at line 695 ("Battery power (33149) is a magnitude; 33135 says the direction").
  - homeassistant-solax-modbus (const.py:562 value_function_battery_input_solis) and solis_modbus (hybrid_sensors.py:4672) both derive the sign from 33135.
- User-visible effect: if the register is a magnitude, which is how the other projects treat it, evcc always shows the battery as charging. Discharge is shown as charging and the battery's share of the home energy balance is wrong.
- Confidence: medium. The document does not state the sign, and solarman treats the value as signed.

## Checked, no bug / notes

- solax.yaml (G4):
  - Correct against G4 V3.47 / V3.36 and G3 V3.29: grid 0x46 int32s ×−1, 0x4A uint32s 0.01, PV 0x0A/0x0B, energy 0x94 uint32s 0.1, battery 0x16 int16 ×−1, SoC 0x1C, Bat_Awaken 0x56.
  - Version note: the options `mppt3` (0x124) and `storageunit` 2 (0x129, 0x12D) are not in the G3/G4 documents. Only solax-modbus lists them, for Gen5/Gen6.
- solis-hybrid-s:
  - Grid, phase, current, PV and SoC registers match the 2020 document. The meter powers are in 0.001 kW = 1 W, "+ to grid", and evcc negates them.
  - Battery sign via 33135 is correct.
  - Document conflict, not counted as a bug: for 43110 BIT05 the 2020 document (Appendix 7, page 32) says "0—Allow 1—Not allow" grid charging. evcc writes 49 (bit 5 set) for "charge" and 17 for normal. solis_modbus (switch_sensors.py:51-54) states that real firmware is the opposite of the document (bit set = allowed), and solax-modbus labels values without bit 5 as "No Grid Charging". evcc agrees with field practice. The ModbusSpec enum text (devices/solis/inverter.yaml:640, bit 5 "NOT allowed") follows the document and may deserve a note.
- solis.yaml (string): 3262 s32 W + export ×−1, 3282 u32 0.01 kWh, 3004 u32 W all match devices/solis/string.yaml:82,150,155 (document INV-3000ID V001B000D032).
- solinteg-gen2/gen3:
  - Correct against M-TEC Energy Butler RTU Protocol GEN2+GEN3 V1.0 (2022-11-19), page 5: SoC 43000/33000 (0.01 %), PV power 11028 UINT32, grid power 11000 INT32, battery power 40258/30258 INT32. The document gives no signs.
  - Mode values 257/258/259 at 50000 match solax-modbus plugin_solinteg (0x101 General, 0x102 Economic, 0x103 UPS).
  - Gen2 energy registers 41102-41112 have no independent reference. Gen3 31102-31112 are backed only by solax-modbus.
  - Note: the M-TEC document says the RS485 default unit id is 247 for GEN2 and GEN3. evcc gen3 defaults to 255; that may be right for TCP, and it is not counted.
- solplanet-modbus: no independent reference. ModbusSpec devices/solplanet/hybrid.yaml comes only from evcc, and no AISWEI/Solplanet document is in modbus-docs. No code-level errors were found; the int16 negative write goes through uint16(val) truncation, which is fine.
