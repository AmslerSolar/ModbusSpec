# Unit 2 – evcc Go charger drivers (evcc bf5c276)

Paths: evcc = upstream/evcc, MS = devices.

## Bugs

### 1. victron.go:153-154 – status 3 "Charged" is reported as charging
- Does: values 0-3 go through `ChargeStatusString('A'+u)`, so 3 becomes "D", which evcc maps to StatusC (charging).
- Right: 3 = "charged" (charging finished, car still connected), so it should be StatusB.
- Evidence: Victron "EVCS Modbus-TCP register list" v3.9 (2026-05-08), register 5015: 0 disconnected, 1 connected, 2 charging, 3 charged, …; the GX list (CCGX-Modbus-TCP-register-list 3.81) gives the same values for 3824. ModbusSpec: MS victron/evcs.yaml:99 and victron/gx-evcharger.yaml:75.
- Effect: after a session ends, evcc still shows "charging" with 0 W. The session doesn't close cleanly, and charge-end logic and plans see a car that is still charging.
- Confidence: high.

### 2. victron.go:152-158 – documented states 20, 22, 23, 24 (and 4, 7) give an error
- Does: everything except 0-3, 5, 6 and 21 returns "invalid status".
- Right: 22/23 = switching to 3/1 phase, 24 = stop charging, 20 = charging limit are normal states (same document).
- Effect: evcc's own 1p/3p switch (register 5055, which it implements) and its own stop command put the device into states that evcc reports as errors. This gives error logs and a loadpoint whose status can't be read during the switch.
- Confidence: medium (whether the device holds these states long enough to be polled is not documented).

### 3. pulsares.go:88-92, 138-139 – the logger is never set; a heartbeat error panics
- Does: the struct has `log *util.Logger`, but `NewPulsares` never assigns it (`log` is a local variable). The heartbeat goroutine calls `wb.log.ERROR.Println` when its read fails.
- Effect: the first failed heartbeat read (any Modbus timeout while backup mode 2-6 is set) dereferences nil and crashes evcc.
- Confidence: high (code bug).

### 4. schneider-v3.go:270-276 – the charge duration is decoded from the wrong half of a 32-bit register
- Does: reads 2 registers at 4009 but decodes `encoding.Uint16(b)`, which is the first register only.
- Right: 4009 "Session charging time" is uint32 in seconds. The guide defines UINT32 as high word in the first register (U32-4321).
- Evidence: EVlink Pro AC Modbus Connectivity Guide GEX1969300-06 (03/2026), register table (4007/4009 uint32 s) and data-type glossary (UINT32 / U32-4321). ModbusSpec: MS schneider/evlink-pro-ac.yaml:78.
- Effect: with high word first, the charge duration is nearly always 0. Even if the device sent low word first, it would wrap after 18.2 h.
- Confidence: high that it is wrong (one 16-bit word of a uint32). How it fails depends on word order.

### 5. schneider-v3.go:223, 235, 261 – word order differs from the guide (version/doc note)
- Does: float32 values (currents 2999, voltages 3027, power 3059) are decoded low word first (`Float32LswFirst`), and the int64 energy at 3203 uses `Uint64LswFirst`.
- Guide: the table only says "float32" / "int64". The glossary defines IEEEFloat = F32-4321 (high word first) and U64/S64-87-21 (high word first); the low-word-first variants are F32-2143 / U64-21-87. GEX1969300-06, data-type glossary.
- Effect if the guide is right: wrong V/A/W/kWh values. Because the evcc driver is in use, the device probably sends low word first and the guide's glossary is generic. Report as a conflict to check on a device.
- Confidence: low.

### 6. schneider-v3.go:135-137 – the setpoint 99 sentinel is taken as a current
- Does: at startup `wb.curr` takes the value of 4004 if it is above 6.
- Right: 99 = "no setpoint defined by Modbus" (only after a station restart). The valid range is 0-32 A (GEX1969300-06, register 4004).
- Effect: if `Enable(true)` runs before any `MaxCurrent`, evcc writes 99, outside the documented range. With today's loadpoint order (MaxCurrent first) the impact is small.
- Confidence: medium on the fact, low on the impact.

### 7. pracht-alpha.go:141-160 – writes 0 A where the manual says values below 6 A are not allowed
- Does: `Enable(false)` writes 0 to 40004/40005 (per connector) and to 40003 (box total).
- Right: 40003-40005 "in A (Werte unter 6 A nicht zulässig)". Locking/releasing is done with the release register 102 / 40103 (11/21/12/22, 1/2).
- Evidence: PRACHT ALPHA XT(+) manual v2.1.0 (März 2025), chapter 4 MODBUS SCHNITTSTELLE, p.12-13. ModbusSpec: MS pracht/alpha.yaml:58-60, 67.
- Effect: if the firmware enforces the range, disabling doesn't stop charging, or the write is rejected. evcc issue 3738 suggests it works on some firmware.
- Confidence: medium.

### 8. pracht-alpha.go:150-157 – a connector-2 current overwrites the whole box's limit
- Does: every `setCurrent` also writes the same value to 40003 (total limit of all connectors). Enabled() also requires 40003 > 0.
- Effect on a two-connector box with two loadpoints: setting connector 2 to 6 A (or 0 to disable) caps or stops connector 1 too.
- Evidence: same manual, 40003 "max. Strom gesamt Grenze" is the box total.
- Confidence: medium (code logic).

### 9. pracht-alpha.go:115-116 – status 3 is mapped to "charging"
- Does: 2 and 3 → StatusC.
- Right: 3 = "KFZ sendet Ladeanforderung mit Lüfter, kein Laden möglich" (requests charging with ventilation, charging not possible). Same manual p.13, register 106/107. MS pracht/alpha.yaml:91.
- Effect: shows charging while nothing flows.
- Confidence: medium.

### 10. smartevse.go:41-66 – the register map is not SmartEVSE's documented map
- Does: reads state from input 0x0103 (low byte, 0-3), writes current as (A<<8)|A to 0x0201, and does phase switching by read-modify-write of bit 0 of 0x0204. The template calls the device "Edgetech Smart EVSE".
- Documented (SmartEVSE-2 README for firmware >2.20, commit 33afd9e; SmartEVSE-3 main.h v3.11.2): 0x0000 = state (0 A … 10 C1), 0x0002 = charging current 0.1 A. 0x0103 = MAX charge current of this EVSE (6-80 A). 0x0201 = EVSE circuit max current (10-160 A). 0x0204 = Max Mains Current (10-200 A). MS edgetech/smartevse.yaml:59-90.
- Effect on a SmartEVSE with documented firmware: status reads the configured max current (e.g. 16 gives "invalid status"). Each current change writes e.g. 0x1010 = 4112 into the circuit-max setting. Phase switching toggles bit 0 of Max Mains Current (e.g. 25 → 24 A). These are persistent misconfigurations.
- The pre-2.20 map (separate README revision) was not available locally, so the driver may target old firmware. If so, the template should say that.
- Confidence: medium.

### 11. smartevse.go:250-255 – the 10 s wait after a phase switch runs only on error
- Does: `if err != nil { time.Sleep(10s) }`.
- Right: the comment says the wait follows the switch, so the test should be `err == nil`.
- Effect: charging resumes right after the switch, without the intended settle time.
- Confidence: high (code bug), medium impact.

### 12. versicharge.go:136-145 and 173-179 – the scaling assumes firmware ≥ 2.135, which isn't checked (version note)
- Current: evcc writes current×100 to 1633. AJ map (fw ≥ 2.135): ≤100 = A, 101-8000 = 0.01 A, which is correct. AA map (fw 2.118-2.134): 1633 "Max Charging current Sum" in A, factor 1, so 600-3200 would be out of range.
- Energy: evcc divides 1692 by 1e3 (Wh). AA map: factor 0.1 Wh, so energy reads 10× too high on older firmware.
- Status: 1599 (EVSE state) exists only from V2.122 (AJ map, last column), so status fails on older firmware.
- Evidence: VersiCharge AC Series ModBus Map A5E52200882-AJ (06/2024) and -AA (10/2022), registers 41600/41634/41693. MS siemens/versicharge.yaml:85, 90-91, 130-131.
- Confidence: medium. The template should require firmware ≥ 2.135, or the driver should read the firmware string at holding 31.

### 13. sigenergy.go:87, 154, 166 – reads input registers with FC03
- Does: reads 32000-32004 (AC charger running information) as holding registers.
- Document: section 5.5 "AC-Charger running information register definition (input register)". The permission table says "RO: Read only, only support 0x04 command". The document's own examples are inconsistent (one reads a 3xxxx register with 03).
- Evidence: Sigenergy Modbus Protocol V2.9 (2026-05-13), table 5-5 and the permission legend. MS sigenergy/ac-charger.yaml (table: input).
- Effect: may fail on firmware that enforces the function code. Also, 32003 is S32 in the document but evcc decodes it as uint32.
- Confidence: low (the driver works in the field).

### 14. solax.go:160-179 – states documented as normal give errors (no manufacturer document)
- Does: 14 Occupied, 15 Waiting for response, 16 Discharging, 10 Card activation and 4 Faulted all return "invalid status".
- Source: homeassistant-solax-modbus run_mode enum (MS solax/ev-charger.yaml:432). evcc's own comment names a SolaX "X1/X3-HAC protocol V1.0.0" that is not in the local archive.
- Effect: error logs while plugged in, if the charger reports Occupied.
- Confidence: low.

### 15. solax.go:259-263 – the energy word order conflicts with the HA integration
- Does: on G2, `Uint32LswFirst` at input 0x0010.
- Other source: homeassistant-solax-modbus marks this register "word order big" for all models (MS solax/ev-charger.yaml:320).
- No independent manufacturer document. Confidence: low.

### 16. weishaupt.go:243-252 – the "no setpoint" sentinel is taken as a temperature
- Does: GetLimitSoc reads 32101 and accepts any value from -500 to 5000.
- Right: FormatSollwert: -32768 or 1 = "Keine Sollwertanforderung aktiv". Weishaupt Datenpunktliste Modbus TCP (WWP) 83807301, chapter 3.4 Warmwasser (32 101 FormatSollwert) and the FormatSollwert legend. MS weishaupt/wbb.yaml:58 (invalid: [-32768, 1]).
- Effect: when no setpoint is active, the limit shows as 0 °C instead of "not available".
- Confidence: medium, low impact.

## Minor / notes (not counted as bugs)
- sungrow.go:55 vs 207: the comment says 21202 is in 0.01 A, but the code writes 0.1 A (initial 60 = 6 A). No document available, so it can't be decided which is right.
- phoenix-ev-eth.go:163-173: on Wallbe firmware (register 528 in 0.1 A), plain `MaxCurrent` writes whole amps (16 → 1.6 A). This path is unused because evcc prefers ChargerEx when implemented.
- phoenix-ev-ser.go:65 decodes the status letter from byte 0, while ev-eth/em-eth use byte 1. No document available.
- raedian.go / sigenergy.go: C1 (S2 closed, no PWM) is mapped to StatusC, but evcc's own `ChargeStatusString` maps C1 to StatusB. Inconsistent, low impact.
- webasto-next.go:231: reads currents with FC04, while the comment and OpenEMS (MS webasto/next.yaml:34-36) use holding registers.
- voltie.go: state 4 (D, charging with ventilation) returns an error.
- Checked with no differences against the document: sigenergy-evdc.go (V2.9 tables 5-3/5-4, Appendix 14), weidmüller.go (2933050000 rev 02: 318 PHASES_LLM and 11050/11052 are volatile, mW/mA/mV scaling; word order not stated in the document), weishaupt addresses and SollwertPV.

## Checked
19 files. Compared with a manufacturer document: pracht-alpha, pulsares (both maps), schneider-v3, sigenergy, sigenergy-evdc, smartevse, versicharge, victron, weidmüller, weishaupt (10).
Compared only with other open-source projects: solax (HA), voltie (OpenEMS), webasto-next (OpenEMS) (3).
No independent reference: phoenix-em-eth, phoenix-ev-eth, phoenix-ev-ser, raedian, sungrow, vestel (6). Their ModbusSpec entries, where any exist, come from evcc itself.
