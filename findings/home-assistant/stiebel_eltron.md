# stiebel_eltron (HA core bd8b1bc) + pystiebeleltron 0.9.2

Library checkout upstream/lib/pystiebeleltron is at tag v0.9.2 = the version HA pins (manifest `pystiebeleltron==0.9.2`).
modbus_connection checkout is 4.12.6 (pin comes through pystiebeleltron; the nan check runs on the raw unsigned word, so
0x8000 on signed gauges is handled correctly).

What HA uses: climate entity only: input 0 (room temp HC1), input 2 (humidity HC1), holding 1000 (operating mode,
read/write), holding 1001 (comfort/day room temp HC1, read/write, 10–30), input 2000 (status bits 2, 3, 8, 12, 13). It
identifies the controller via input 5001.

Documents: "ISG Modbus TCP/IP software documentation" 321798-47824-0146 (modbus-docs 5a89d3…pdf, the newest),
A 321798-42758-9571 (621a10…pdf), A 321798-39096-9075 (e82a86…pdf). ModbusSpec: devices/stiebel/lwz.yaml, wpm.yaml.

## Bug 1: the LWZ register map is used for every controller, WPM included (high)
- Where: ha-core homeassistant/components/stiebel_eltron/coordinator.py:45 (`self.api_client = LwzStiebelEltronAPI(unit)`),
  with __init__.py:39 / config_flow.py:49 accepting any model `get_controller_model` knows.
- What it does: `get_controller_model` accepts 103/104 (LWZ) and also 390/391/449 (WPM 3, WPM 3i, WPMsystem) and 551.
  HA keeps the model only for the device name and always builds the LWZ API, so it reads LWZ input 0…33 and holding
  1000…1026, and writes the operating mode to holding 1000.
- What is right: WPM controllers use another map (document 321798-47824-0146 sections 6/7: system values from 501, operating
  mode at 1501 (protocol 1500), values 0…5 with 2 = programmed operation; the LWZ (05.1/07.1) Plus section 8 uses the same
  WPM-style map). ModbusSpec lwz.yaml identify accepts only 103/104; lwz.yaml:249 says 390/391/449 "use another map".
  wpm.yaml identifies 390/391/449.
- Effect: for a WPM heat pump the config flow succeeds, but then the pooled LWZ read either fails (illegal address →
  ConfigEntryNotReady retry loop forever) or shows registers that mean something else on a WPM. Mode/temperature writes
  would go to the wrong holding registers. pystiebeleltron has a WPM API (wpm.py / wpm3.py) that HA does not use.
- Confidence: high (code path is clear; the document shows the maps differ).

## Bug 2: "not available" operating mode is shown as Emergency (medium)
- Where: upstream/lib/pystiebeleltron/pystiebeleltron/lwz.py:364-369 (`get_operation`), used by climate.py `_set_attr`.
- What it does: holding 1000 = 0x8000 (ISG "not available") decodes to None, and `get_operation` then returns
  `OperatingMode.EMERGENCY_OPERATION`, so HA shows preset "emergency" and HVAC mode AUTO.
- What is right: unavailable should be unknown (None); 0 = EMERGENCY OPERATION is a real documented value
  (321798-47824-0146 section 9.2, register 1001, encoding list). The diagnostics also report "EMERGENCY_OPERATION".
- Effect: a missing/unreadable mode looks like the heat pump is in emergency operation.
- Confidence: medium.

## Bug 3: an undocumented mode value crashes the entity update (low)
- Where: lwz.py:369 `OperatingMode(int(op_mode))`, called from climate.py `_set_attr` without guarding.
- What it does: any value not in {0,1,3,4,5,11,14} raises ValueError inside the coordinator listener, so the climate entity
  stops updating (and diagnostics fail). Combined with bug 1, a WPM's value 2 (programmed operation) would hit this.
- What is right: map unknown values to None. Document 9.2 lists only those 7 values for LWZ, so on a correct LWZ this needs
  firmware outside the document.
- Confidence: low (for LWZ) / medium (together with bug 1).

## Bug 4: UnknownControllerModelError is not handled in setup (low)
- Where: __init__.py:38-41 catches only StiebelEltronModbusError; config_flow.py:52-57 maps it to "unknown".
- What it does: an ISG that reports a controller id not in the enum (document 321798-47824-0146 table at 5002 lists also
  190, 325, 340, 165, 331, 220, 219) gives "Unexpected exception"/"unknown" instead of a clear "unsupported device".
- Confidence: low (error handling only).

## Library-only findings (HA does not use these registers)
- DHW set day/night write range: lwz.py:93-94 `in_range(10, 65)`; document 321798-47824-0146 section 9.2 registers 1012/1013
  say 10…55 (1014 manual: 10…65). ModbusSpec lwz.yaml:109-110 max 55. Effect: library allows writes the controller
  documents as invalid. Confidence: high for the document, not user-visible in HA.
- Bus status: lwz.py:117 reads 2002 unsigned; document 9.3 register 2003 gives −4…0 (OK, −1…−4 faults). Unsigned decoding
  shows 65535…65532. ModbusSpec lwz.yaml:127 (s16). Not used by HA. Confidence: high.

## Version note
- Compressor starts: newest document 321798-47824-0146 §9.1: register 31 = "COMPRESSOR STARTS THOUSANDS" (0…65535),
  register 34 = "COMPRESSOR STARTS ONE" (0…999). The library's `hi*1000 + low` (input 30/33) matches this edition. The older
  editions (A 321798-42758-9571, A 321798-39096-9075) have only register 31 = full count. ModbusSpec lwz.yaml:95 note ("full
  count, not thousands") reflects the older editions only, and x.compressor_starts_low (lwz.yaml:183) is in the newest
  document, so it need not be project-only. This is a ModbusSpec issue, not an HA bug (HA does not use it).

## Checked and matching
Addresses (document number − 1), scale 0.1 / 0.01, signedness of the room temperature and humidity, the 0x8000 sentinel,
operating-mode values, holding 1001 range 10…30 (HA min/max 10/30), status bits 2 (heating), 3 (cooling), 8/12/13 (filter),
controller id at input 5001.
