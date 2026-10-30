# Unit 3 (meter templates) — evcc bf5c276 vs ModbusSpec and manufacturer documents

Paths are relative to the evcc checkout (upstream/evcc).

## Bugs

### 1. Carlo Gavazzi EM110/111/112, ET112: 32-bit values read with the wrong word order — high
- Where: templates/definition/meter/cg-emt1xx.yaml:22 (power, 0x4) and :34 (energy, 0x10 / 0x20): `decode: int32`.
- What evcc does: reads INT32 most significant word first.
- Right: the meter sends INT32/UINT32/UINT64 least significant word first, so `int32s` is needed (as for every
  other CG meter).
- Evidence: Carlo Gavazzi "EM100 Series and ET100 Series Modbus Communication Protocol" Version 4.0 (2025-06-20),
  section 3.1 data formats: "In INT32, UINT32 and UINT64 formats, the word order is LSW-> MSW."
  ModbusSpec devices/carlogavazzi/em111.yaml (encoding word_order little; points 0x4, 0x10, 0x20 list evcc as the only
  `word_order: big` conflict). OpenEMS reads the same registers with WordOrder.LSWMSW.
- Effect: power and energy are garbage — e.g. 100 W (raw 1000 = [0x03E8, 0x0000]) decodes as 1000·65536·0.1 ≈
  6.5 MW; negative power and any energy below 6553.5 kWh likewise blow up. PV and charger meters unusable.

### 2. B+G e-tech DS100 and WS100: default baud rate 1200, which the meters don't support — high
- Where: templates/definition/meter/bgetech-ds100.yaml:12 and bgetech-ws100.yaml:12 (`baudrate: 1200`).
- Right: factory setting 9600 8N1; selectable 9600 / 19200 / 38400 / 115200 only.
- Evidence: "B+G e-tech DS100 Serie, Beschreibung" (January 2026): technical data "RS485 Baudrate
  9600/19200/38400/115200", Auslieferzustand "Baudrate: 9600"; register 100C table 6=9600 … 9=115200.
  "B+G e-tech WS100-19xx Serie, Datenblatt" (04.2026): "Einstellung im Auslieferzustand 9600 / NONE / 8 / 1"; register
  100C note "(Actually only 9600, 19200, 38400, 115200 are supported)". ModbusSpec devices/bgetech/ds100.yaml and
  ws100.yaml connection.serial baud 9600.
- Effect: a user who keeps the template default gets no communication at all.

### 3. Deye single-phase storage (deye-storage): 10 W power scaling ignored — medium
- Where: templates/definition/meter/deye-storage.yaml:24 (grid power 169) and :95 (battery power 190), no scale.
- Right: holding 54 "AC power ratio": when it reads 10, registers 167–172, 176–179, 185 and 190 are in 10 W units
  (1 W otherwise).
- Evidence: Deye "Modbus RTU single phase (1P)" V119 (2024-02-19), register 053/054 rows ("10: 167,168,169,170,171,
  172,176,177,178,179,190,185 number register value is 10W"), and register 169 row "1W / 10W:54 register=10";
  ModbusSpec devices/deye/hybrid.yaml notes ("Registers 167…172 and 176…178 … in 10 W when register 54 is 10") and
  points 169 / 190.
- Effect: on inverters reporting ratio 10 (larger models), grid and battery power are shown 10× too small, so surplus
  charging and battery control work with wrong numbers. evcc's 3-phase template already handles the analogous HV
  10 W case; the single-phase one does not read register 54 or offer an option.

### 4. Afore hybrid: grid currents are the inverter's output currents — medium
- Where: templates/definition/meter/afore-hybrid.yaml:36-53 (input 510/511/512, commented "Igrid R/S/T").
- Right: 510–512 are "R/S/T phase inverter current (IinvR/S/T)"; the protocol has no meter (grid-connection) current.
- Evidence: "Afore T6 communication protocol V1.0-211109" (xlsx, sheet "run info 04", rows 36–38); ModbusSpec
  devices/afore/hybrid.yaml points 510–512 (from the document).
- Effect: evcc's grid currents (used for phase/load management and current limits) show the inverter's own AC
  current, not the current at the grid connection; wrong whenever loads or the battery are running.

### 5. Afore hybrid: grid power sign possibly inverted — low/medium
- Where: templates/definition/meter/afore-hybrid.yaml:29 (input 535, comment "positive = import") and powers 529/531/533.
- Document: Pgrid R (529) "Positive means the inverter sends power to the grid, negative means the inverter draws
  power from the grid"; 535 is the matching total (no own sign text).
- Evidence: Afore T6 communication protocol V1.0-211109 (xlsx, sheet "run info 04", row 49); ModbusSpec
  devices/afore/hybrid.yaml:535 positive export, with conflict `{sources: [evcc, solarman], positive: import}`.
- Effect if the document is right: import and export swapped on the grid meter (evcc would see feed-in as import).
  Two projects (evcc, ha-solarman) use import-positive, so this needs a check on a device before changing; flagged
  because the only manufacturer statement says the opposite.

### 6. AlphaESS SMILE: "Charge Cut SOC" written in % although documented as 0.1 % per step — low
- Where: templates/definition/meter/alpha-ess-smile.yaml:189-196 and :211-218 (holding 2133 = `{{ .minsoc }}` /
  `{{ .maxsoc }}`).
- Document: 0x0855 Charge Cut Soc, R/W, unsigned, "0.1/bit" (same unit as the battery SOC 0x0102, which evcc does
  read with scale 0.1).
- Evidence: "Handbuch Modbus RTU - Storion SMILE + T30" V1.23 (German), page 19; ModbusSpec
  devices/alphaess/inverter.yaml:2133 scale 0.1 with conflict `{sources: [evcc, openwb, solax-modbus], scale: 1}`.
- Effect if the document is right: "charge" writes e.g. 100 → 10 % target (grid charging stops almost at once) and
  "hold" writes 10 → 1 %. Three projects use 1 % steps, so possibly a document error; needs a device check.

## Minor / version notes
- GoodWe ET over Wi-Fi (goodwe-wifi-et.yaml:42): grid power read as int16 from 35140, the low word of the documented
  s32 "AC Active Power" at 35139 (template comment: firmware doesn't sign-extend). Wraps above ±32.7 kW; fine for
  the ET/EH range. Document: GoodWe Modbus Protocol Hybrid 1.2 (ModbusSpec devices/goodwe/et.yaml 35139).
- Deye 3-phase (deye-hybrid-3p.yaml:35-62, 470-475, 568-575): help text suggests 50–350 A for max discharge / grid
  charge current (holding 109 / 128); Deye three-phase storage protocol V105.4 (2024-08-13) gives range [0,185] A
  for both. Values above 185 A are outside the documented range (newer large LV models may allow more).
- Deye 3-phase grid power 625 read as int16: the document calls 625 the low 16 bits of the total grid-side power,
  so it wraps above ±32.7 kW (same limitation evcc documents for the GEN port).
- Deye 3-phase energies: V105.4 lists 0.1 kWh for 516–538; the revised .doc's change log has a firmware-dependent
  0.1 kWh / 1 kWh entry, consistent with evcc's `firmware1098` HV option — not contradicted.
- Eastron SDM120 (eastron-sdm120.yaml): no device baud default, so evcc's generic 9600 applies; Eastron SDM120
  protocol v2.5 gives 2400 baud as factory default (an older Eastron Europe document says 9600). Version note.
- GoodWe grid energy 36017 (goodwe-hybrid.yaml:53, goodwe-wifi-et.yaml:51) read as Wh (scale 0.001): the maps give no
  unit; goodwe library and openWB agree with evcc. Not a bug on current evidence.
- Ferroamp battery power 6100 (ferroamp-energyhub.yaml:120): evcc positive = discharge; ferroamp-modbus
  positive = charge. No manufacturer document available locally; unresolved.
- FoxESS Avocado / MQ2200 grid power 39168 (fox-ess-avocado.yaml:47-50): evcc and openHAB positive = export,
  NextEnergy integration positive = import. No document; unresolved.

## Checked, consistent with documents
alpha-ess-smile (all reads), bgetech-ds100 / ws100 registers and scaling, deye-hybrid-3p (registers, HV 10 W
scaling, 143 Max Sell Power units, battery sign), deye-mi, deye-mi-solarman, deye-string (63/86, little-endian,
0.1 scales), deye-storage (energies incl. 78/80 split counter), eastron-sdm120 registers, goodwe-hybrid
(35105…35117, 35182, 35191, 35209, 36019…36025, 36052…36057, 37007), growatt-hybrid-tlxh (3005…3017, 3041/3043,
3053, 3069, 3127, 3171, 3178/3180, TOU word 3038/3039 bit layout, 3049 AC charge enable — Growatt Modbus RTU Protocol
II V1.39).

## No independent reference (only evcc or other projects)
acrel-adw300, anker-solix-solarbank-max-ac (Anker's own HA integration agrees), anker-solix-x1, askoheat (evcc reads
input 317 for power; OpenEMS/openWB use input 110 — different register sets, no document), atmoce, chint-ech-hybrid,
e3dc-modbus (deprecated), ecoflow-powerocean-modbus, enecess-ecomain, ferroamp-energyhub, fox-ess-avocado,
fox-ess-h1, fox-ess-h3, fox-ess-h3-smart, goodwe-dt (781/786 only from evcc), goodwe-wifi-dt (goodwe library only),
goodwe-wifi-es. Afore battery registers 2002/2007/2013 and PV total 1026 are not in the Afore document either.
