# smarty (HA core bd8b1bc) + pysmarty2 0.10.3

Library checkout upstream/lib/pysmarty2 is at tag v0.10.3 = HA's pin (manifest `pysmarty2==0.10.3`). It uses pymodbus
directly (sync, in the executor).

What HA uses: holding 1 (system mode 0…3, fan entity, read/write), holding 200/201 (alarm/warning binary sensors), coil 5
(boost switch + boost binary sensor), coil 1 (filter-timer reset button), input 18/19/21 (supply/extract/outdoor temp,
×0.1), input 30 (filter days left → timestamp), input 55/56 (fan rpm), input 2/3 (versions).

Document: Salda "MCB 1.21 Modbus table 2018-05-03" (modbus-docs fdcaea0c…xlsx). ModbusSpec: devices/salda/smarty.yaml
(project-only, from pysmarty2) and devices/salda/mcb.yaml (from the document).

## Bug 1: temperatures are decoded unsigned (medium)
- Where: upstream/lib/pysmarty2/pysmarty2/registers/input_register.py:297 (`round(self.state * self.multiplier, 2)`), used by
  smarty.py:56-75 and HA sensor.py:124-144 (outdoor/supply/extract temperature).
- What it does: the raw u16 is scaled without sign conversion. −0.1 °C (0xFFFF) becomes 6553.5 °C.
- What is right: signed ×0.1. The MCB 1.21 table gives only "Value*0,1 °C" (no type), but outdoor air of a ventilation unit
  is regularly below 0 °C; ModbusSpec mcb.yaml types all temperatures s16; modbus_local_gateway's Salda config reads them
  `signed: true`. ModbusSpec smarty.yaml:113-115 already notes the library applies no sign conversion.
- Effect: in winter the outdoor temperature sensor shows ~6550 °C, spoiling history/statistics (state class is not set, so
  no long-term stats, but the value is wrong).
- Confidence: medium (document does not state the type; the physics and two independent sources do).

## Bug 2: boost "off" writes a no-op command; boost state comes from a command coil (medium)
- Where: pysmarty2 smarty.py:146-153 (`disable_boost` writes coil 5 = 0), smarty.py:91-96 (`boost` reads coil 5); HA
  switch.py:349-356 and binary_sensor.py:528-532.
- What it does: HA's boost switch turns off by writing 0 to COIL_INTENSIVE_AIR_FLOW_BOOST.
- What is right: MCB 1.21 table, sheet "Coils", COIL_INTENSIVE_AIR_FLOW_BOOST (5): "0: Nothing, 1:Activate". 0 is "do
  nothing", so writing 0 does not stop intensive air flow; it runs for HR_USER_CONFIG_INTENSIVE_AIR_FLOW_TIME_SET (14,
  default 600 s). Running boost is shown by input 15 IR_CURRENT_SYSTEM_MODE = 4 / input 1 state 7 "Boost" and the remaining
  time by input 13 IR_INTENSIVE_AIR_FLOW_TIME_LEFT (or holding 107).
- Effect: switching boost off in HA does not end boost, and the switch/binary sensor state follows the command coil, not
  whether boost is running.
- Confidence: medium (document is explicit about the coil values; actual device latch behaviour not verified).

## Unresolved: register address base (low, conflict; not claimed as a bug)
- pysmarty2 uses the table's "Address" column directly as protocol address (input 1 = system state, holding 1 = mode,
  coil 5 = boost, holding 200/201 = alarms; registers.py:378-425 read from address 1).
- ModbusSpec mcb.yaml (from the same document) uses number − 1 (mcb.yaml notes), supported by modbus_local_gateway's
  Salda_RIS_MCB.yaml ("Modbus PDU = XLS address - 1", confirmed writes to HR 0) for an RTU RIS unit.
- The document itself does not say whether the column is 0- or 1-based. If the Smarty's TCP interface is 0-based like the
  RIS, every HA register is off by one (e.g. holding 1 would be the comfort set point). pysmarty2 has a long user base on
  Smarty, which argues the Smarty TCP interface is 1-based. Needs a device check; ModbusSpec smarty.yaml and mcb.yaml
  disagree by one for the same controller family.

## Minor code issues (library)
- registers.py:384-425: block reads are mapped with one register too few (`zip(range(1, 37), …)` for count 37,
  `range(200, 202)` for count 3, `range(1, 67)` for count 67, `range(1, 132)` for 132 words). The last register of each block
  (holding 37, 202, discrete 67, input 132) is never stored. None of these are used by HA. Confidence: high, no visible
  effect in HA.
- HA sensor.py:109-113: the filter "timestamp" is `now() + days_left`, recomputed every 30 s poll, so the state changes on
  every update (recorder churn) although the device value is whole days. Low.

## Checked and matching (under pysmarty2's address convention)
Mode enum 0…3 (Standby, Building protection, Economy, Comfort) vs HA fan speed range 1…3 and off = 0; alarm A/B 0/1; filter
timer reset coil "1: Activate"; rpm and days-left units; scale 0.1 on temperatures.
