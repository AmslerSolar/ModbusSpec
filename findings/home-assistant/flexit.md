# flexit (HA core bd8b1bc) + flexit-modbus 0.1.0

Library checkout upstream/lib/flexit-modbus is at tag 0.1.0 = HA's pin (manifest `flexit-modbus==0.1.0`).

What HA uses (config-entry path): holding 8 (target temp, s16 ×0.1, write 10…30), holding 17 (fan mode 0…3), input 8
(filter hours), 9 (supply temp), 11 (outdoor temp), 13/14/15 (cooling/heat-recovery/heater %), 27 (filter alarm),
28 (heater enabled), 48 (actual air speed). Serial 8E1, user-chosen baud (default 9600) and unit id.

Reference: no Flexit/CI66 manufacturer document in modbus-docs/index.csv. ModbusSpec devices/flexit/ci66.yaml is built
only from flexit-modbus itself, so the register map cannot be checked independently. Findings below are code bugs only.

## Bug 1: deprecated YAML entity shows "High" fan mode on a read error (medium)
- Where: ha-core homeassistant/components/flexit/climate.py:254-256 with :335-344.
- What it does: `_async_read_int16_from_register` returns −1 on a failed read; `res < len(self.fan_modes)` is true for −1
  and `self.fan_modes[-1]` is "High".
- What is right: leave the fan mode unknown on a failed read.
- Effect: YAML users (the legacy `Flexit` class is still set up from `async_setup_platform`, only a repair issue is raised)
  see fan mode "High" whenever the read fails.
- Confidence: high for the code path.

## Bug 2: deprecated YAML entity decodes temperatures unsigned and 0.0 °C as −1 (medium)
- Where: climate.py:346-354 (`_async_read_temp_from_register`).
- What it does: `int(result.registers[0])` is the unsigned word, so −5.0 °C outdoor (0xFFCE) becomes 6549.4 °C; a raw 0
  (0.0 °C) returns −1 (not −0.1, not 0.0); a read error returns −1 → −0.1 °C.
- What is right: signed ×0.1 (the library's own `temperature()` helper, data_model.py:77-96, decodes signed; ModbusSpec
  ci66.yaml points s16).
- Effect: legacy YAML users see wrong outdoor temperature (attribute `outdoor_air_temp`) below 0 °C and false −1/−0.1 °C
  values at 0 °C or on errors. The same unsigned read (climate.py:344) also applies to the % registers (13/14/15) that the
  library types as signed.
- Confidence: high for the code path (sign convention itself only from the library).

## Notes (not bugs)
- flexit-modbus enums.py:312 docstring says the fan mode is "holding register 8 (HR17)"; the code uses holding 17
  (setpoints.py:404-409), same as the legacy entity. Docstring only.
- Config-entry path (FlexitClimate, sensors) decodes signed temperatures, maps unknown fan codes to None and propagates
  read failures as UpdateFailed: no issue found.
- Filter running hours as TOTAL_INCREASING duration: a reset after a filter change is treated as a new cycle; fine.
