# Unit 7: evcc meter/cfos.go, meter/hoymiles-dtu-mbtcp.go, meter/mbmd.go + mbmd models used by evcc templates

evcc bf5c276, mbmd af19f17 (upstream/lib/mbmd). mbmd paths are relative to upstream/lib/mbmd/meters/rs485/.

## Bugs

### 1. Carlo Gavazzi EM24 (RS-485): "Import" reads the resettable PARTIAL counter — high
- Where: mbmd carlogavazzi-em24.go:36 `Import: 0x42`; used by evcc templates/definition/meter/cg-em24.yaml:26
  (`energy: Import`, grid/charge) and :41 (`returnenergy: Import`, pv).
- What it does: reads input register 0x0042 = "KWh(+) PAR" (partial, resettable via 0x3002 "Reset of partial meters").
- Right: total import "KWh(+) TOT" is 0x003E (62), INT32 LSW first, kWh*10.
- Evidence: Carlo Gavazzi EM24-DIN Communication Protocol, Version 2 Revision 0 (2007-02-05) (ccontrols
  CarloGavazziEM24.pdf, the doc mbmd cites), register table: 300063/003Eh KWh(+) TOT, 300067/0042h KWh(+) PAR; 3002h
  reset of partial meters. Also EM24 v4r0 doc; ModbusSpec devices/carlogavazzi/em24-din.yaml:112 (62 = grid_import_energy)
  and :114 (66 = x.import_energy_partial).
- Effect: evcc's meter/charge energy is the partial counter — wrong totals, and drops to 0 whenever the user resets
  partial counters on the meter (charged-energy / grid-import statistics jump).
- (Ethernet EM24_E1 and EM3x0 models use 0x34 = TOT correctly.)

### 2. SBC (Saia-Burgess) ALE3: "Import"/"Export" are tariff 1 / tariff 2 consumption counters — high
- Where: mbmd sbc.go:19-20 `Import: 28`, `Export: 32` (minus 1 -> addresses 27 and 31); evcc
  templates/definition/meter/sbc-axx3.yaml:20-21 (`energy: Import`, `returnenergy: Export`) and :32-33 (pv:
  `energy: Export`, `returnenergy: Import`).
- What it does: treats WT1 total as import and WT2 total as export.
- Right: registers 28-29 = "WT1 total, Counter Energy Total Tariff 1", 32-33 = "WT2 total, Counter Energy Total Tariff 2",
  both drawn energy, 0.01 kWh. The meter has no export counter. Total import = WT1 + WT2.
- Evidence: Saia Burgess "Energy meter ALE3 with Modbus" data sheet 26-527 EN02 (2012-12-14), Modbus register table
  (regs 27-35); ALE3-Modbus user instructions 431951130a (2012-11-01) same table, and display text "T1/T2 total =
  total consumption tariff 1/2". ModbusSpec devices/sbc/ale3.yaml:69,71 and note at :112.
- Effect: grid/charge: import energy misses all tariff-2 consumption; tariff-2 consumption is shown as grid export
  (feed-in). pv usage: PV production energy = tariff-2 counter (0 for most users). For a single-tariff installation
  "Import" is right and "Export" stays 0.

### 3. evcc mbmd.go: the "NaN -> 0" handling never fires; invalid readings reach evcc as NaN — medium
- Where: evcc meter/mbmd.go:161-165 (`if err != nil && errors.Is(err, meters.ErrNaN) { res.Value = 0 }`).
- What it does: expects mbmd's rs485 QueryOp to return meters.ErrNaN. It never does: rs485.go QueryOp (rs485.go:78-109)
  just returns `op.Transform(bytes)`; ErrNaN is only produced by mbmd's sunspec package. The ABB producer
  (abb.go:68-85, wrapTransform) and EnergyMID (energymid.go:79, mantissa -32768) return math.NaN() as a value with
  err == nil.
- Right: ABB/Janitza B-series mark unavailable values with 0x7FFF.. (signed) / 0xFFFF.. (unsigned) (ModbusSpec
  devices/abb/b23-b24.yaml:69-111 `invalid:`, from the ABB B23/B24 user manual Rev. A and the ABB EQ B-Serie
  Produkthandbuch 05.14); EnergyMID uses -32768 (ModbusSpec gossenmetrawatt/energymid.yaml:78-101). evcc should map
  these (math.IsNaN on res.Value) to 0 / error as the comment intends.
- Effect: NaN power / phase currents / voltages / energies propagate into evcc (UI, load management, totals) whenever
  the meter reports a value as not available (e.g. L-N quantities on a 3-wire connection, unsupported quantity).

### 4. Siemens PAC2200: "Import"/"Export" are the tariff-1 counters, not the totals — medium
- Where: mbmd pac2200.go:35-36 `Import: 801`, `Export: 809`; evcc templates/definition/meter/siemens-pac2200.yaml:17-18, 29-30.
- Right: 801 = "Active energy import tariff 1", 805 = import tariff 2, 809/813 = export tariff 1/2 (all Double, Wh);
  totals are 969 "Total active energy import" / 973 "Total active energy export" (MID register).
- Evidence: SENTRON PAC2200CLP Equipment Manual L1V30820585B-04 (12/2022), Modbus table (offsets 801-813, 961-973);
  SENTRON PAC2200 Gerätehandbuch L1V30415167A-02 (05/2018) lists 801-813 as "Wirkarbeit Bezug/Lieferung Tarif 1/2", access
  RW (resettable). ModbusSpec devices/siemens/pac2200.yaml:120,122,162-163.
- Effect: with tariff switching (digital input) the tariff-2 energy is missing; resetting the counters (powerconfig /
  Modbus / display) resets evcc's energy. Version note: the 2018 German manual's Modbus TCP table does not list 969/973,
  so on old firmware 801 + 805 would be the fallback.

### 5. ORNO OR-WE-514/515: active power read as unsigned — low/medium
- Where: mbmd orno1p.go:22 `Power: 0x140` read with snip32 = RTUUint32ToFloat64 (orno1p.go:97); evcc
  templates/definition/meter/orno-we514_515.yaml:18 (`power: Power`; usages pv, charge).
- Right: 0x140-0x141 "Split phase active power P1" type LONG (signed; energies are ULONG), 0.001 kW.
- Evidence: "Register description OR-WE-514 & OR-WE-515" (ORNO, as linked by mbmd), register table 0x140 LONG; ModbusSpec
  devices/orno/we514.yaml:55 (s32, conflict lists mbmd u32).
- Effect: if the meter is wired so that power is negative (common for PV), evcc shows ~4.29 GW instead of a negative
  value. Same for Cosphi (u16 vs s16; not used by evcc).

### 6. CHINT DTSU666: values are secondary-side; CT/PT ratio not applied — low
- Where: mbmd dtsu666.go (all ops), evcc templates/definition/meter/chint-dtsu666.yaml.
- Right: the manual says the listed registers are the "regular" (secondary) data; primary = × IrAt (0x0006) × UrAt
  (0x0007); the display shows primary values.
- Evidence: CHINT DTSU666/DSSU666 User Manual (no version), register table note 2 and IrAt/UrAt rows; ModbusSpec
  devices/chint/dtsu666.yaml:137-138 note.
- Effect: on transformer-connected DTSU666 (IrAt > 1) power/current are too small by the CT ratio. Direct-connected
  meters (IrAt = 1) are fine. Whether energy registers are scaled is not stated.

### 7. SolarEdge SE-MTR-3Y: energies from the resettable counters — low, no independent reference
- Where: mbmd semtr3y.go:30 `Import: 0x03EA` and :53 `Export: 0x0458`; mbmd's own comments call 0x03EE / 0x045A the
  "non-reset" counters. evcc templates/definition/meter/solaredge-se-mtr-3y.yaml:20-21, 32-33.
- Effect: if the counters are reset, evcc totals reset. No manufacturer document available (map looks like the
  WattNode float map); ModbusSpec devices/solaredge/se-mtr-3y.yaml is mbmd-only.

## Checked, no bug found
- cFos (meter/cfos.go): 8058 u64 Wh /1e3, 8062 power — match the cFos Modbus register page (retrieved 2026-10-24). evcc
  reads power as uint32; the page gives no signedness (ModbusSpec cfos/power-brain.yaml assumes s32, unverified) — no
  independent reference.
- Hoymiles DTU (meter/hoymiles-dtu-mbtcp.go): no manufacturer document; ModbusSpec dtu-pro-s.yaml comes from evcc only.
  ModbusSpec inconsistency (not evcc): its note says slot N starts at 0x1000 + N × 20, but evcc steps 0x28 = 40 register
  addresses per slot (reading 20 registers); the per-point addresses 4099/4104/4106 assume register = 2 bytes inside a
  byte-addressed block. Worth fixing in ModbusSpec's hoymiles importer.
- mbmd models matching the manufacturer documents (registers, type, scale, word order): ABB A/B (abb.go), EM24_E1,
  EM3x0, DTSU666 addresses, DZG DVH4013, Eastron SDM/SDM220/SDM72/X96-1A, Eltako DSZ15, Finder 7M.24/7M.38, Gossen
  EnergyMID (mantissa/exponent and energy factor), inepro PRO380, Janitza (19000 float block, also in the Janitza B2x
  manual), ORNO WE-525, Schneider iEM3000, Socomec Countis E, WAGO 879-30xx (same map as inepro PRO380 doc).
- No independent reference (ModbusSpec has only mbmd/openWB): BE MPM3PM (mbmd holding vs openWB input registers),
  Eastron SDM54, DDM18SD, Lovato DMG610, ORNO WE-504, ORNO WE-516 (orno3p), SE-MTR-3Y.
- Template remarks (not bugs): cg-em24 has Export commented out (evcc issue 31143); DZG template uses
  ImportPower / -ExportPower (u32 each) and offers only pv/charge usages, fine.
