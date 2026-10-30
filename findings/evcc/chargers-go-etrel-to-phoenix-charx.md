# evcc unit 1 — Go charger drivers (evcc bf5c276)

Paths relative to upstream/evcc. ModbusSpec paths relative to devices.

## Bugs

1. **mennekes-compact: error-state recovery releases charging at full current** — charger/mennekes-compact.go:144-152.
   On EVSE state 6 (error) evcc writes 0x0302 = 0.0 and 0x0D05 = 1 and returns StatusNone without an error.
   The spec says 0x0302 = 0 means "no limitation, EVSE signals maximal current (16/32 A)". With 0x0D05 = 1 the box is
   released at its maximum, whatever evcc's enabled state and current were. Recovery needs a valid current (≥ 6 A, or
   evcc's own setpoint) and the release only if evcc had it enabled.
   Evidence: AMTRON 4You 300 / Compact 2.0s / Start 2.0s Modbus RTU Specification v2.5 (2025-07-11), p.2 notes and
   register table 0x0302; mennekes/amtron-compact.yaml:65. Effect: after a reboot or a missed heartbeat (error 200),
   a connected car can charge at 16/32 A until the next loadpoint cycle overwrites it. In PV/off mode this is
   unwanted grid draw. Confidence: high.

2. **heidelberg: state 8 (derating) treated as error** — charger/heidelberg-ec.go:139-170.
   The switch maps 2–7 and 10. State 8 "Derating" falls into the default case and returns "invalid status: 8".
   It should map to C (the car keeps charging at a reduced current); 9 and 11 (E and ERR) are the real errors.
   Evidence: EC ModBus register table 20210222 (register 5: "7=C2, 8=derating, 9=E, 10=F, 11=ERR"); Amperfied connect
   series register layout 20250422, charging-state table; heidelberg/energy-control.yaml enum charging_state.
   Effect: while the box derates (e.g. temperature), every loadpoint cycle fails and the charging session shows as an error.
   Confidence: medium-high.

3. **etrel: Currents() ignores the connector offset** — charger/etrel.go:213.
   It reads `etrelRegCurrents` (14) without `wb.base`, unlike Status, Enabled, setCurrent and CurrentPower.
   Connector 2 of an INCH Duo should read 114–118.
   Evidence: etrel/inch.yaml:91-93 (INCH and DUO SmartHome Modbus TCP Registers V6.0). Effect: on connector 2 the phase
   currents (and evcc's phase detection and current-based logic) are connector 1's. Confidence: high.

4. **keba-modbus: P30 1-phase state value** — charger/keba-modbus.go:137 (`wb.state1p = 0`), :420-430.
   For P30, getPhases treats 1552 == 0 as 1-phase. The P30 guide gives 1 = single-phase and 3 = 3-phase (P40 uses
   the same values, and evcc uses 1 for P40). With the documented values getPhases always returns 3 on a P30.
   Evidence: KeContact P30 Modbus TCP Programmers Guide 1.07 (12.2025) §3.21 "1552 – Phase switching state"; values
   first documented in 1.06 (07-2024); keba/kecontact-p30.yaml enum phase_switching_state. Effect: after a switch to 1p,
   evcc still believes 3p (wrong current-to-power calculation, repeated switch attempts). Confidence: medium. Older P30
   firmware may report 0/1, which the guide does not document.

5. **my-PV (ac-elwa-2 / ac-thor / ac-elwa-e): consumption read from the setpoint register, and not divided by `scale`**
   — charger/mypv.go:285-292 (CurrentPower), :176-185 (Status), and mypv_common.go:30.
   Register 1000 is the R/W "Power" command (in multi-mode the sum for all devices), not a measurement. The measured
   power is 1082 "Power of the queried device" (since AC•THOR a0020303, ELWA-E 00203.00) or 1074 (+1075/1076).
   Also, setPower writes `scale*power`, but CurrentPower returns the raw register without dividing by `scale` (the
   relay term at :315 does divide). Evidence: AC ELWA 2 Documentation of Controls 241205, register table 1000/1074/1082;
   AC-THOR / AC-THOR 9s Documentation of Controls 241205, 1000/1074–1076/1082; AC ELWA-E Documentation of Controls
   230725, 1000/1082; mypv/elwa-acthor.yaml:80 and its notes. Effect: the loadpoint shows the commanded power as heating
   power even when the thermostat has cut out (temperature reached), and it is off by the factor `scale` when scale ≠ 1.
   Status C also comes from the setpoint. Confidence: medium (the documents label 1000 only "Power", R/W).

6. **evsedin: register 2005 bit 7 is "PWM debug", not 0.01 A mode** — charger/evsedin.go:75-94.
   With firmware ≥ 17 evcc sets bit 7 of 2005 (persistent) and then writes currents in 0.01 A.
   The datasheet gives bit 7 as "PWM debug bit (rev17 and later), 0 disabled (default), 1 enable"; it documents no
   0.01 A mode. Evidence: EVSE Wallbox / DIN / W16 datasheet (evracing.cz, EVSE-WB-DIN_latest.pdf), register table p.29;
   evracing/evse-wb-din.yaml:82 (config_bits) vs :72 (milliamp_mode only from evcc/openWB). Effect: if the
   undocumented behaviour does not hold on a board, evcc writes 600–1600 to 1000 (documented as whole amps up to 80)
   and switches on a debug mode permanently. openWB does the same, so it probably works in practice. Confidence: low
   (a documentation conflict, not a confirmed device bug).

7. **openwb-2.0: "-1 = no value" read as unsigned energy** — charger/openwb-2.0.go:175-181.
   TotalEnergy decodes 10102 as uint32. The document marks it as a signed 32-bit value and says -1 means openWB has no
   valid value. A -1 becomes 4 294 967 kWh. Power (:166-172) is read signed but -1 is passed on as -1 W. Evidence: openWB
   Modbus Rev2.0 (16.10.2023); openwb/series2.yaml:40-41 and notes. Effect: a huge jump in the energy counter (session
   and total energy, statistics) whenever the value is unavailable. Confidence: medium.

8. **openwb-native: phase switch and wake-up always end enabled** — charger/openwb-native_linux.go:170-182, 184-196.
   runGpioSequence does Enable(false), toggles GPIOs, then Enable(true) unconditionally. evcc's loadpoint can switch
   phases while the charger is disabled (core/loadpoint.go:1447ff). Compare helper.go:95 whenDisabled, which restores the
   previous state. Effect: a disabled charge point is re-enabled (EVSE current written) after a phase switch until the
   loadpoint notices it is "out of sync". Confidence: medium (code bug; no manufacturer document needed).

9. **obo: heartbeat reads another driver's register** — charger/obo.go:89.
   The heartbeat reads `dlRegSafeCurrent` (87, from charger/daheimladen.go:58) instead of an OBO register. The OBO map
   (5, 6, 11, 28) has nothing at 87. If the device answers with an exception, every heartbeat logs an error and may not
   count as a valid request for the failsafe. No independent reference (obo/ion.yaml comes only from evcc).
   Confidence: medium as a code bug, low on its effect.

10. **innogy (Compleo eBOX): wrong function code and out-of-range disable value** — charger/innogy.go:105, 177, 197, 210,
    and setCurrent :131. evcc reads every register with function 04 (input). The Compleo guide says reads are holding
    registers with function 03 (all of 0–300 and 1000–1028). Disable writes 0.0 A to 1012/1014/1016, where the documented
    range is 6–32 A. Voltages at 301–306 and energy at 307 (table version ≥ 6) are not in the guide (it is table
    version 5; 300 is the cable state there). No reference for those. Evidence: Quickguide eBOX – Modbus Energiemanagement
    20230814, §2.3.1 and register table; compleo/ebox.yaml:50-70. Effect: on firmware that follows the guide, every read
    fails, and disabling may be rejected. Older innogy-branded firmware evidently answers FC04 (evcc users). Treat this
    as a version note unless the box answers only FC03. Confidence: low-medium.

11. **hesotec: power unit and energy source** (no independent reference) — charger/hesotec.go:39-40, 150-156, 172-180.
    evcc's own register comment gives N_Wirkleistung 0x400A as u32 in **mW**, but CurrentPower returns the raw value as
    W (1000× too high if the comment is right). TotalEnergy reads 0x401C "N_Energie_Ladesitzung" (session energy, Wh),
    which resets per session, as the meter total. Confidence: low-medium (only evcc's own comments).

12. **mypv-hea: operation state ≥ 4 reported as device error** (no independent reference for HEA) —
    charger/mypv-hea.go:139-141. For the related ELWA 2 / AC•THOR, 1077 = 4 means "red cross is on = no control signal",
    5 "red cross flashes" and 6 "block active": operating states, not faults (footnote 3 of the ELWA 2 and AC-THOR documents
    241205). If HEA uses the same table, a missing control signal or an active block shows as a device error.
    Confidence: low.

## Minor / code notes (not counted as bugs)

- goodwe.go:276-279 phases1p3p only stores the phase count and does not rewrite the power setpoint. foxess-evc.go:617ff
  rewrites it for the same kind of power-driven device. No GoodWe EV charger document, so no reference.
- mennekes-hcc3.go:180-182 Diagnose decodes the serial (0x030B/0x030C, low word first) with LittleEndian.Uint32 over
  big-endian words, so the printed serial is wrong (diagnostics only). Status maps CP C1 (no PWM) to C and D1/D2 to an
  error.
- kathrein.go:521 Diagnose prints only the low byte of DeviceInfo (the relay capability is in the high byte); Phases1p3p
  writes without the mutex the heartbeat holds.
- peblar.go:135 CP state D (ventilation) returns an error. The spec limits pauses (40000 = 0) to 3 per 10 minutes;
  evcc does not.
- heidelberg-ec.go: register 14 is apparent power (VA) on Energy Control layout 1.0.4+ (version note). The 261 maximum is
  16 A; evcc does not clamp it.
- etrel.go:131-140 status 8 (Faulted), 10 (Unavailable) and 11 (Reserved) return an error rather than StatusE/F.
- evsedin.go:130-140 state 5 (failure) returns an error. MaxCurrent(int) would write whole amps while 0.01 A mode is on,
  but the loadpoint only calls MaxCurrentMillis then (core/loadpoint.go:1032), so this is latent.
- keba-modbus: P40 1550/1552/5050/5052 need a newer P40 software (guide 1.01–1.03 revision record), a version note.

## Checked

All 21 files: etrel, evsedin, foxess-evc, goodwe, heidelberg-ec, hesotec, innogy, kathrein, keba-modbus, kse,
mennekes-compact, mennekes-hcc3, mypv-hea, mypv, mypv_common, nrggen2 (all registers match nrgkick/gen2.yaml), obo,
openwb-2.0, openwb-native_linux, peblar (matches peblar/wallbox.yaml), phoenix-charx (matches phoenixcontact/charx.yaml).
No independent reference: 7 (foxess-evc, goodwe, hesotec, kathrein, kse, obo, mypv-hea); innogy only in part.
