# Unit u5d: storaxe, sungrow-hybrid, sungrow-ihm, sungrow-inverter, sungrow-meter

evcc commit bf5c276. Paths relative to upstream/evcc. Addresses are evcc's 0-based ones;
Sungrow documents number from 1 (doc register = address + 1).

## Bugs

### 1. sungrow-ihm: feed-in limitation switch written as 0xAA/0x55, document says 1/0 (high)
- Where: templates/definition/meter/sungrow-ihm.yaml:145-167 (write) and :168-195 (`curtailed` read, `ena == 170`).
- evcc: writes 85 (0x55) to address 8027 (doc 8028) to switch the feed-in limitation off and 170 (0xAA) to switch it on;
  `curtailed` reports a limit only when the register reads 170.
- Right: doc 8028 "Feed-in limitation", U16, `1: On`, `0: Off`. Section 3.1.1/3.1.2: set 8028 to 0 to disable, to 1
  before writing the ratio (8031). 0xAA/0x55 are the values of the other switches (8049-8051), not of 8028.
- Evidence: Sungrow "Communication Protocol of iHomeManager" V1.0.2 (2026-01-21), Table 4 item 4 (p. 7) and section 3.1.1/3.1.2
  (pp. 9-11); change log "Added Feed-in limitation (8028)". ModbusSpec devices/sungrow/ihm.yaml (x.feed_in_limitation,
  enum off_on {0: Off, 1: On}).
- Effect: curtailment writes an out-of-range value (likely rejected with an exception or ignored, so the limit never
  turns on/off); `curtailed` always reports 100 % because the register never reads 170, so evcc thinks the plant is
  never curtailed. On V1.0.1 firmware the register doesn't exist at all (version note).

### 2. sungrow-ihm: maxacpower read with the wrong word order (high)
- Where: templates/definition/meter/sungrow-ihm.yaml:21
  (`modbus/read?address=8144&type=input&encoding=uint32&scale=100`).
- evcc: `uint32` = high word first (util/modbus/register.go:108; the modbus/read service uses the same decoder,
  util/service/modbus.go). The template itself reads every other 32-bit iHM value as `int32s`/`uint32s`.
- Right: U32 "little-endian for double-word data", i.e. low word first (transmission order of 0x01020304 is 03 04 01 02);
  register 8145-8146 "Total rated active power", U32, 0.1 kW. So it must be `uint32s`.
- Evidence: iHM Communication Protocol V1.0.2, data-type table (p. 4-5) and running-data table item 6 (p. 6).
  ModbusSpec devices/sungrow/ihm.yaml encoding word_order: little; x.rated_active_power at 8144.
- Effect: a 10 kW plant (low word 100, high word 0) reads 100*65536*100 W ≈ 655 MW as maxacpower, so the PV AC
  limit evcc uses for the pv meter is meaningless (effectively no cap).

### 3. sungrow-hybrid: battery power decoded as int16, document says U16 (medium for SH50-125CX, otherwise latent)
- Where: templates/definition/meter/sungrow-hybrid.yaml:304-315 (input `bp`, address 13021, `decode: int16`) and the
  script at :273-278.
- evcc: reads the magnitude register as signed; the script only applies the charge sign when `bp >= 0`.
- Right: doc 13022 "Battery power", U16, 1 W (S16 only for SH3.0-6.0RS / SH8.0-10RS); the document recommends
  5214-5215 (S32) instead.
- Evidence: Sungrow "Communication Protocol of Residential and Small Industrial Hybrid Inverter" V1.1.17 (2026-09-30),
  running-data table items 100-101 (register 13021/13022 remarks); item 44 "Battery power 5214-5215 S32".
  ModbusSpec devices/sungrow/shx.yaml:185-186.
- Effect: above 32767 W (possible only on the SH50-125CX listed in the same document) the value wraps negative, the
  charge test is skipped and battery power is reported with wrong magnitude and sign. Residential SH models stay
  below 32.7 kW, so no effect there.

### 4. sungrow-hybrid: inverter AC phase currents used as grid currents (low-medium)
- Where: templates/definition/meter/sungrow-hybrid.yaml:189-221 (grid usage without `lan`: addresses 13030-13032,
  commented "Smart meter phase L1 current").
- evcc: uses these as the grid connection point's phase currents (e.g. for load management / max current).
- Right: doc 13031-13033 "Phase A/B/C current", S16 0.1 A, remark "Output type (5002) is 0: only phase A ...", directly
  followed by 13034 "Total active power" — inverter output values. Unlike the meter values (5601-5607, 13008-13011,
  13036-13047) they carry no "See note 1" (smart-meter data). V1.0.23 lists them the same way.
- Evidence: Hybrid protocol V1.1.17 running-data table items 108-112 and Note 1; V1.0.23 (2021-12-22) items 74-77.
  ModbusSpec devices/sungrow/shx.yaml:154-156 (l1_current..l3_current, inverter, not meter).
- Effect: grid currents show the inverter's AC output current, not the current at the grid point; load management
  can overload the main fuse (e.g. at night with inverter idle, grid currents read ~0 A). evcc's own `lan` help text
  implies the real meter currents are only available via 5743-5745. Confidence low-medium because the document
  doesn't say explicitly "inverter" vs "meter".

### 5. sungrow-ihm: PV power taken from "total active power of inverter" (low-medium)
- Where: templates/definition/meter/sungrow-ihm.yaml:119-131 (pv usage, address 8154).
- evcc: reports 8155-8156 (doc) as PV production.
- Right: doc describes it as "Total active power accumulated from connected inverters" (AC output), which for hybrid
  inverters includes battery discharge and excludes PV that goes into the battery. The iHM has a separate PROD.CT
  channel (8569-8574) for production.
- Evidence: iHM Communication Protocol V1.0.2, running-data table item 13 (p. 6) and notes 1-2.
  ModbusSpec devices/sungrow/ihm.yaml x.inverter_power note.
- Effect: with a hybrid inverter behind the iHM, evcc's PV value is off by the battery power (battery discharge counted
  as PV, PV charging the battery missing). Correct only for plain string inverters.

### 6. sungrow-inverter: total active power decoded as unsigned (low-medium)
- Where: templates/definition/meter/sungrow-inverter.yaml:37-43 (address 5030, `decode: uint32s`).
- Right: V1.1.80 lists 5031-5032 "Total active power" as S32 (older editions V1.1.37/V1.1.53 say U32 — version note).
- Evidence: Sungrow "Communication Protocol of Residential & Commercial PV Grid-Connected Inverters" V1.1.80
  (2026-03-27), running-data table item 29. ModbusSpec devices/sungrow/sg.yaml:292.
- Effect: a small negative value (self-consumption at night/standby) decodes to ~4.29e9 W PV power. Should be
  `int32s`.

## Checked, no bug
- sungrow-hybrid: 33046/33047 writes `maxchargepower/10` = W/10 = 0.01 kW units — matches doc 33047/33048 0.01 kW
  (the ModbusSpec conflict "scale: 1" for evcc is an import artefact). Hold/holdcharge write 1 (=10 W). EMS mode 0/2,
  command 0xAA/0xBB/0xCC, 13051 power in W within 0-100 % of BDC rated power (5627 read in W) — all match V1.1.17
  Table 6 / section 3.2-3.3. 13009 export power with scale -1, 5602-5606 (+ = import), 13036/13045 energies,
  13002 PV energy, 5016 total DC power, 13022 SOC 0.1 %, 13026/13040 battery energies, 5000/5627/5638 scales: correct.
- sungrow-ihm: grid 8156 (0.01 kW, scale 10), energies 8175/8177 (0.1 kWh), per-phase powers 8558-8562 (1 W, no
  scale), battery 8160 (scale 10), SOC 8162, ratio 8030 S16 0.1 % (S32 in V1.0.1 — version note): correct.
- sungrow-inverter: 5082 meter power (+ = purchase per single-phase V10 doc), 5098 / 5143 energies, curtail 5006
  0xAA/0x55 and 5007 0.1 %: correct per V1.1.80 section 3.1.
- sungrow-meter: addresses 0x000A/0x0014/0x0061-0x0066/0x0164-0x016A match the Sungrow DTSU666 protocol (2021-06-01);
  that document gives no scales, signs or word order, so evcc's scales and signs have no independent reference.
- storaxe: no manufacturer document. Power (input 1, s16, ×100, + = discharge) and SOC (125) agree with OpenEMS;
  SOC s16 vs u16 harmless. Energy 114, voltages/currents 6-11: no independent reference.

## Version notes
- iHM 8028 only exists from V1.0.2; 8031 was S32 in V1.0.1 (single-register write of the low word still works).
- iHM voltages 4357/4359/4361 are undocumented; the document has 8554-8556 (0.1 V) for the GRID.CT voltages.
- SH LAN registers 5740-5745 are in no Sungrow document (sources only evcc and mkaiser).
- sungrow-hybrid writes 13051 = maxchargepower/maxdischargepower; the document limits it to 0-100 % of BDC rated power,
  so a user value above 5627 would exceed the range (evcc already has a caveat).
