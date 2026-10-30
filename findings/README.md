# Findings: Home Assistant and evcc checked against ModbusSpec

What Home Assistant core and evcc read and write over Modbus, compared register by register with ModbusSpec's device
files and, where one exists, the manufacturer's document. A finding counts against a project only where the
manufacturer's document (or clear independent evidence) shows it is wrong; facts ModbusSpec took from the same project
are not counted as evidence. Each file gives, per finding, where (file:line in the project), what it does, what is
right, the evidence and a confidence. `_method.md` in each folder is the brief the checks followed.

Checked versions:

- Home Assistant core `bd8b1bc`, with each integration's library at the version Home Assistant pins.
- evcc `bf5c276` (2026-10-23), with mbmd `af19f17` (the version in evcc's go.mod).

Private manufacturer documents are cited by title, version and page; `modbus-docs/` is the local folder of those
documents (not part of this repository).

## Home Assistant (`home-assistant/`): 21 candidates

| File | Highest-confidence findings |
|---|---|
| stiebel_eltron.md | WPM controllers (390/391/449) are accepted but always read with the LWZ register map (`coordinator.py:45`); "not available" operating mode shown as Emergency |
| neopool.md | Chlorine flow sensor inverted (`status_mask.py:98`; bit 3 = 0 means no flow); failed timer / relay-mode writes reported as success; heating modes offered without checking 0x0414; filtration mode 14 missing |
| solaredge_modbus.md | solaredged reads "advanced power control enabled" from 0xF108 instead of 0xF142; `set_reactive_power` writes 0xF140 (the active power limit); status 8 named "standby" |
| sofar.md | Serial read 7 of 8 registers; feed-in limitation mode 3 missing; power-limit write shorter than the documented block |
| smarty.md | Temperatures decoded unsigned; boost "off" writes a coil value that does nothing |
| flexit.md | YAML entity: a failed read shows fan mode "High"; temperatures read unsigned |
| bluetti_modbus.md | Battery current decoded as \|raw − 30000\| (no direction) |
| fronius.md, kaco_modbus.md | No bug found (the fronius-modbus library HA pins was not available) |

## evcc (`evcc/`): 86 candidates, 23 high confidence

| File | Highest-confidence findings |
|---|---|
| meters-solax-solinteg-solis-solplanet.md | SolaX MIC G2 32-bit values high word first (document: low word first); SolaX G3 battery control writes the G4 registers (sets minimum SoC to 0–1 %); G3 battery registers shown as phase voltages / currents; Solis RHI battery power never negative |
| meters-sofar-solaredge-solarlog-solarmax.md | Sofar G3 PV4 power read from the PV4 current register; Sofar 2017 grid power ~65× and PV power 1000× off; SolarEdge export-control bits combined against the document |
| meters-storaxe-sungrow.md | Sungrow iHomeManager feed-in limit written as 0x55/0xAA instead of 0/1; rated power read with the wrong word order |
| meters-acrel-to-growatt-tlxh.md | Carlo Gavazzi EM100/ET100 32-bit values high word first; B+G DS100 / WS100 default 1200 baud (unsupported) |
| meters-growatt-hybrid-to-sigenergy.md | Sigenergy grid energy from a register now reserved; inverter currents used as grid currents; Kostal Plenticore gen2 ignores its endianness option |
| meters-go-and-mbmd.md | mbmd EM24 (RS-485) energy from the resettable partial counter; SBC ALE3 tariff 2 counter used as export; NaN never reaches evcc's "NaN means 0" handling; Siemens PAC2200 tariff-1 counters |
| meters-sma.md | SMA 30581 decoded signed (U32 in SMA's list) |
| meters-varta-victron.md | No bug found |
| chargers-go-abb-to-etek.md | ABL eMH1 phases reversed; Amperfied state C1 counted as charging, derating as an error |
| chargers-go-etrel-to-phoenix-charx.md | Mennekes error state resets the limit to "no limitation"; Etrel connector 2 reads connector 1's currents; Heidelberg derating as an error; KEBA P30 phase count; my-PV power from the command register |
| chargers-go-phoenix-em-to-weishaupt.md | Pulsares heartbeat panics (logger never assigned); Victron EVCS "charged" shown as charging; Schneider charge duration from one word of a 32-bit value; SmartEVSE waits after a phase switch only on error |
| charger-and-curtailer-templates.md | Xtherma power limit never written (`type: holding` is a read); NIBE energy counter read as 16 bits; SolarEdge curtailer removes installer export limits |

## What changed in ModbusSpec

Every finding was checked against the device files. ModbusSpec already had nearly all documented cases right; these
were corrected from the manufacturer documents:

- sma-hybrid: new document file from SMA's register list v3.1 (30581 U32, 40801 S32).
- solax-inverter: the battery-mode write registers per generation (G3: 0x001F 3 = feed-in priority, 0x0020 = minimum
  SoC; G4: work / manual mode).
- stiebel-lwz: newest ISG edition (compressor starts split into thousands and remainder).
- deye-hybrid: AC power ratio (holding 54, 10 W units); deye-p3: 0–185 A limits.
- sigenergy-inverter: 30554–30565 reserved since V2.4.
- huawei-sun2000: active power control 47415–47418 from Issue 05.
- sugarvalley-neopool: 0x0300 marked "not used"; sofar-inverter: write rule of the power-control group;
  solis-inverter: note on 43110 bit 5; openwb-series2: −1 = not available on the energy counter.
- evcc importer: Hoymiles DTU slot stride (40 addresses, 20 registers read).

Still open (no document): see OPEN.md.

## Notes for ModbusSpec itself (as found)


Found on the way; check before changing a device file:

- devices/bluetti/balco260.yaml: grid phase 1 power (50235) is unsigned, copied from the library; probably signed.
- devices/sma/hybrid.yaml: 30581 is U32 in SMA's register list, not s32.
- devices/stiebel/lwz.yaml: the newest ISG edition splits compressor starts into thousands (31) and remainder (34);
  the note says otherwise.
- devices/hoymiles/dtu-pro-s.yaml: panel slot stride; evcc steps 40 addresses per slot, the file says 20.
- devices/solis/inverter.yaml: 43110 bit 5 follows the document (1 = grid charging not allowed); real firmware
  reportedly does the opposite.
- devices/salda/mcb.yaml vs smarty.yaml: one register apart for the same controller family; needs a real unit.
