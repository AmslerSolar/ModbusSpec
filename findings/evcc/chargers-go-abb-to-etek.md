# Unit 0: evcc Go charger drivers (abb … etek), evcc bf5c276

Paths relative to upstream/evcc. Read only, nothing edited.

## Bugs

### 1. ABL eMH1: phase currents reported in reverse order (L1 and L3 swapped). Confidence: medium-high
- Where: charger/abl.go:244 (`return res[2], res[1], res[0], nil` in `currents()`).
- What evcc does: it reads 0x002E ×5. res[0] is register 0x0030, res[1] is 0x0031 and res[2] is 0x0032. It returns them as L1 = 0x0032, L2 = 0x0031, L3 = 0x0030.
- What is right: 0x0030 = Ict1, 0x0031 = Ict2, 0x0032 = Ict3 (bits 47..32 / 31..16 / 15..0 of the R5 reply).
- Evidence: ABL "EVCC2/3 API subset for external applications (05 0015 20)", Rev. B (2020-03-12), p. 10, "0x002E – Read current (full)". The example on p. 3 shows `0064 ICT1 = 10A, 0064 ICT2 = 10A, 0000 ICT3 = 0A`. ModbusSpec devices/abl/emh1.yaml lists l1_current at 48, l2 at 49 and l3 at 50.
- Effect: a single-phase car on L1 shows up as charging on L3. Phase detection, measured-phase counts and the per-phase display are wrong. Total power (sum) is unaffected. The swap may be deliberate for some wiring, but no comment says so and the document does not support it.

### 2. ABL eM4: status 0xA0 "outlet blocked, car detected" is mapped to A (no car). Confidence: medium
- Where: charger/abl-em4.go:133-138. The high nibble 0xA maps to StatusA.
- What is right: 0x00A0 means the outlet is blocked and an EV is detected, so StatusB. In the same table, 0x00E0 "blocked, car not detected" and 0x00E2 "booting" fall to the error branch, although neither is a fault (only 0x00Fx is).
- Evidence: ABL "Modbus TCP – Schnittstellenbeschreibung Wallbox eM4 Controller / Extender", R 01 (19.12.2023), p. 7, register 0x..31 "Status outlet". ModbusSpec devices/abl/em4.yaml, enum outlet_state.
- Effect: a car connected to a blocked outlet is reported as disconnected. A blocked or booting outlet without a car raises an "invalid status" error instead of A.

### 3. Amperfied / Heidelberg: charging state 6 (C1, wallbox does not allow charging) is mapped to C (charging). Confidence: medium
- Where: charger/amperfied.go:161 (`case 6, 7: return api.StatusC`).
- What is right: 6 = C1, meaning the car requests charging but the wallbox does not allow it. Only 7 = C2 is charging. evcc's own generic rule (api/chargemodestatus.go:82) maps C1 to B.
- Evidence: Heidelberg/Amperfied "Table Modbus Register – Wallbox Energy Control" (EC_ModBus_register_table_20210222_LW), input register 5 with the "Notice Charging States" table: C1 = "Wallbox doesn't allow charging", C2 = "Wallbox allows charging". ModbusSpec devices/heidelberg/energy-control.yaml, enum charging_state.
- Effect: when evcc disables the wallbox (current 0) with a car that still requests charging, evcc sees "charging". The charging timer, session state and the enabled/charging consistency checks are wrong while charging is paused.

### 4. Amperfied / Heidelberg: charging state 8 (derating) gives an error. Confidence: medium
- Where: charger/amperfied.go:183 (default branch). States 8 and 9 (E) both return "invalid status".
- What is right: 8 = "derating", a documented state in which the box is still charging with reduced current. It is not an error.
- Evidence: same document, input register 5: "7=C2, 8=derating, 9=E, 10=F, 11=ERR".
- Effect: while the wallbox derates (for example on temperature), every Status() call fails and the loadpoint update errors, even though the car is charging.

### 5. Bender ECU: voltage capability check accepts the "not available" value. Confidence: low-medium
- Where: charger/bender.go:165 (`binary.BigEndian.Uint32(b) > 0`).
- What is right: METER_VOL_L1..3 (222–227) read 0xFFFFFFFF when the meter has no voltages (for example the EMH eHZ). The check passes for that value. `getPhaseValues` then maps it to 0.
- Evidence: ECU-BRx/ECU-BBx Modbus TCP Server Specification 1.07 (2022-06-10), meter section (0xFFFFFFFF = not available, voltages from software 5.22 and not with every meter). ModbusSpec devices/bender/ecu.yaml, l1_voltage with `invalid: [4294967295]`.
- Effect: chargers whose meter has no voltages report 0/0/0 V instead of "not supported".

### 6. em2go (single): enable/disable relies on the charge command, which only works in charge mode 1. evcc never sets or checks that mode. Confidence: low-medium
- Where: charger/em2go.go:201-208 (`Enabled()` reads register 95 == 1) and `Enable()` (writes 95 = 1/2). Register 93 is never written.
- What is right: "Charge commands are only available when 'Charge mode' is set to 1."
- Evidence: EM2GO "Program EV Chargers – ModBus TCP" V5 012023 (252210_modbus_tcp_register.pdf), charge-command table note. ModbusSpec devices/em2go/wallbox.yaml, x.charge_command note "Only with charge mode 1".
- Effect: in plug-and-charge mode (0) the start/stop command is ignored. `Enabled()` can then disagree with the real state. Disabling still works because `Enable(false)` also writes current 0.

### 7. cFos Power Brain: CP state 3 (D, charging with ventilation) gives an error. Its comment mislabels 5. Confidence: low
- Where: charger/cfos.go:118-131.
- What is right: 3 = D, a charging state (evcc maps D to C elsewhere). 5 = F (error), not "overtemperature" as the comment says.
- Evidence: cFos "Power Brain Controller – Modbus Registers" web page (retrieved 2026-10-24), charge_pilot_state 8092. ModbusSpec devices/cfos/power-brain.yaml, enum cp_state.
- Effect: a car in state D raises errors. Rare.

### 8. ETEK EKEPC2: some documented non-fault states give errors. Confidence: low
- Where: charger/etek.go:173-190.
- What is right: 2 = "I – waiting for RFID card" (car connected, so B) gives "unknown status". 13 = "M – circuit overload, DLB active" (charging limited by load balancing) also gives an error. evcc's case 19 is not in either document (0–13).
- Evidence: ETEK "Usage Manual for EKEPC2-C-S" (2022-03), working-status/LED table. ModbusSpec devices/etek/ekepc2.yaml, enum working_status.
- Effect: the loadpoint errors while the box waits for RFID or limits current through DLB.

### 9. DaheimLader: documented non-fault states give errors. Confidence: low
- Where: charger/daheimladen.go:203 (default).
- What is right: 8 = scheduled charging (OCPP/app) and 10 = powering up (CP voltage unstable) are not errors. Only 7 is a system error.
- Evidence: DaheimLader Modbus/TCP-Spezifikation (DaheimLadenModbus0726, 28.07.2026), register 0. ModbusSpec devices/daheimladen/daheimlader.yaml, enum charging_state.
- Effect: transient "invalid status" errors.

### 10. Free2move eProWallbox: total energy is negated. Confidence: low
- Where: charger/eprowallbox.go:194 (`return -(l1 + l2 + l3), err`).
- What the document says: L1..L3_ACTIVE_ENERGY (40658–40663) are float32 in Wh with no sign convention, and RESET_ENERGY (40501) clears them. They are not a lifetime meter.
- Evidence: "eProWallbox / eProWallbox Move – Modbus communication map" V1 2023. ModbusSpec devices/free2move/eprowallbox.yaml, energy_l1..3. The document has no local copy in modbus-docs, so this rests on the ModbusSpec transcription.
- Effect: if the device reports positive Wh, as the document implies, evcc's meter total is negative. evcc may be compensating for real device behaviour, so this needs a device check.

## Version notes and items with no independent reference
- abb.go: everything matches TAC Modbus Communication v1.11 (status in byte 1 bits 6–0, lock state ≥ 0x0101 = cable at car, scaling). `Enabled()` reads 0x400E, which is the limit the charger chose from all load-management inputs. The readback of the Modbus-set limit is 0x4022 (document ≥ 1.8). The charger's own load management could therefore make evcc read "disabled". Low.
- abl.go: evcc reads status at 0x0004 and the current setting at 0x000F..0x0013 (b[6:] = 0x0012). Neither is in the Rev. B API subset, which documents the state at 0x002E/0x0033 and says the controller stays silent on invalid registers. They probably come from an older full API. No independent reference. The Icmax write (I/0.06 in 0.1 % duty, 0x03E8 = off) matches the document (range 0x0050–0x03E8).
- amperfied.go: register 14 is VA, not W, on Energy Control layout ≥ 1.0.4 (the connect series gives W). Phase switch 501/5001 matches. `Identify()` reads 2002 ×6 regardless of the UID length in 2001, so it returns a zero-padded or zero hex string even without a card. Low.
- bender.go: registers 1001 / 1002 / 2200 (Mennekes 4You) and 730/740/741 are not in ECU spec 1.07. The Mennekes HA project and OpenEMS say 1000 is deprecated since protocol 1.5 (use 2000). That is not a manufacturer document, so this is a version note only.
- chargex.go: the registers match ChargeX Modbus TCP documentation (V1.6/1.7). Target power (504) is system-wide, not per module, so the `connector` option only selects which module's status and power are read. The phase count for the power write comes from module-state bit 1 ("charging mode 3-phase/1-phase"). The document notes that writable registers are persisted, and evcc writes Charging_Mode on every start and target power on every heartbeat.
- alfen.go: matches the Alfen NG9xx / ACE guide (holding 306/320/344/374 f32/f64 big-endian, 1201 mode-3 string, 1210 f32, 1215 phases). Version note: the 2025 guide is ambiguous on word order and off-by-one. Power and energy NaN values are not filtered (only voltages and currents are).
- enovates.go: matches Enovates' own enovates-modbus library (200–218, 301, 400 s16 mA, 417).
- em2go.go: registers 0–113 match the V5 012023 document. Register 200 (phases) is not in it; no independent reference.
- No independent reference (no manufacturer document, ModbusSpec built from projects or absent): alphatec.go, alpitronic.go (OpenEMS only, consistent), ambibox.go (OpenEMS only; energy 4026/4028 import/export vs ModbusSpec's consumer_energy = 4028 "production" is unresolved), compleo.go (evcc's map, input registers at 0x100 + 0x10·n, is not the eBOX holding map in the Compleo quickguide; it uses LittleEndian for the charge duration at compleo.go:287, which is suspicious), dadapower.go, delta.go, ego.go (openWB only, consistent), em2go-duo.go.

Checked: 21 Go drivers. 8 had no independent reference for the registers evcc uses (alphatec, alpitronic, ambibox, compleo, dadapower, delta, ego, em2go-duo). The undocumented parts of abl.go, bender.go and em2go.go also have none.
