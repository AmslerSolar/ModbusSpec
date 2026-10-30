# Unit 6 — evcc charger (heating) and curtailer templates

evcc checkout bf5c276. Paths are relative to upstream/evcc unless stated.

## Bugs

### 1. xtherma: setmaxpower always fails because the register type is `holding`, not a write type
- Where: templates/definition/charger/xtherma.yaml:18-24 (`setmaxpower` → `set` → register 71, `type: holding`).
- What it does: `util/modbus/register.go` FuncCode() maps `holding` to FC03 (read). `plugin/modbus.go` writeFunc() (l.205-233)
  handles only FC05/FC06/FC16 and returns `invalid func code: 3` for anything else. Every setmaxpower call (and the watchdog's
  periodic re-write and its reset to 0) returns an error. Nothing is ever written.
- What is right: `type: writesingle` (or `writemultiple`) for register 71, as in every other template.
- Evidence: evcc's own code (register.go FuncCode, plugin/modbus.go writeFunc). openWB writes 71 with write_register
  (platforms/openwb/packages/modules/consumers/xtherma/xtherma/consumer.py). ModbusSpec devices/xtherma/heatpump.yaml:4 lists 71
  as writable.
- Effect: PV surplus power control of Xtherma heat pumps does nothing. evcc logs errors.
- Confidence: high.
- Related, lower confidence: openWB writes register 70 = 1 (surplus mode on) before register 71 takes effect, and limits writes of
  70/71 to once a minute (ModbusSpec xtherma/heatpump.yaml notes). evcc never writes 70. Its 120 s watchdog re-writes at about
  60 s, which is right at that limit.

### 2. xtherma: temperature is multiplied by 10 instead of divided
- Where: templates/definition/charger/xtherma.yaml:33-40 (input 124, int16, `scale: 10`).
- What it does: shows raw × 10. A temperature register in 0.1 °C (the usual case) becomes 100× too large. One in whole °C becomes
  10× too large. No unit of a temperature register makes ×10 right.
- What is right: very likely `scale: 0.1`. limittemp (input 51) is read unscaled, so it is in whole °C or the two are inconsistent.
- Evidence: no independent reference. ModbusSpec xtherma/heatpump.yaml:10 has only evcc's own value. The manufacturer's
  xtherma_tcp repository (linked in the template header) is not in the local archive.
- Effect: the heat pump's temperature reads nonsense (for example 4500 °C). Temperature-based logic (limittemp, boost) does
  not work.
- Confidence: medium. It is implausible in itself but not confirmed by a document.

### 3. xtherma: `getmaxpower` reads the electrical power input, not a limit
- Where: templates/definition/charger/xtherma.yaml:25-32 (holding 177, uint16, scale 10). The template has no `power`.
- What it does: reports register 177 as the current maximum-power setting.
- What is right: openWB documents 177 as "in_total: elektrische Leistungsaufnahme, Auflösung 10 W" and reads it as power
  (consumer.py `update`). It should be `power` (meter), not `getmaxpower`.
- Evidence: openWB consumer.py (independent of evcc). ModbusSpec xtherma/heatpump.yaml:7 maps it to consumer_power.
- Effect: evcc shows the actual consumption as the configured limit and has no power reading for the device.
- Confidence: medium.

### 4. NIBE S-series: the energy counter reads only the low word of a 32-bit register
- Where: templates/definition/charger/nibe-s-series.yaml:155-162 (input 3823, `uint16`, scale 0.1).
- What it does: reads 1 register.
- What is right: NIBE register 33824 "Tot. consumption" is u32, factor 10, kWh (nibe library data
  lib/nibe/nibe/data/s1155_s1255.json, s1156_s1256.json, s2125.json, s320_s325.json, s330_s332.json, s735.json, smos40.json).
  NIBE's own document (Technical information MODBUS S-SERIES M12676EN, TIF EN 2608, "32-bit register", p. 6) says 32-bit values
  come low word first. evcc therefore gets only the low word. The value wraps every 6553.6 kWh.
- Evidence: nibe library data (exported from NIBE's register lists). ModbusSpec devices/nibe/s-series.yaml:2179 records the
  conflict. The register itself is not printed in M12676EN.
- Effect: the heat pump's total energy drops back to about 0 after 6553.6 kWh (one to two years for a typical heat pump). The
  energy statistics then jump.
- Confidence: medium-high.
- Same pattern for power (input 2305 = 32306, u32, factor 100 kW). Reading only the low word is harmless there, because values
  fit in 16 bits up to 655 kW.

### 5. Weishaupt WPM (deprecated template): setmode writes the input *configuration* registers, and boost and dim are swapped
- Where: templates/definition/charger/weishaupt-wpm.yaml:47-115 (writes 45101/45102). getmode is at l.19-46 (reads 35101/35102).
- What it does: boost writes 45101=1, 45102=0. dim writes 45101=0, 45102=1. normal writes 0/0.
- What is right:
  - Weishaupt Datenpunktliste Modbus TCP (WWP) 83807301, 1/2025-11, SG-Ready table (p. 18): SGR1 closed + SGR2 open = 1 Sperre
    (block), SGR1 open + SGR2 closed = 3 erhöhter Betrieb. evcc's own getmode follows this (SG1=1,SG2=0 → dim; SG2=1 →
    boost). setmode does the opposite: "boost" sets SGR1 (= block) and "dim" sets SGR2 (= raised operation).
  - The document has no writable SG-Ready state register. 35101/35102 are read-only inputs (p. 17). weishaupt_modbus
    (hacs/OStrama__weishaupt_modbus/.../hpconst.py:1592-1593, enum IO_KONFIG_IN l.690ff) names 45101/45102 "Konf. Eingang
    SGR1/SGR2", read-only. They choose the function of the input: 0 = SG Ready, 1 = EVU-Sperre, 2 = Erhöhter Betrieb, …
    Writing 1 to 45101 reconfigures input SGR1 as an EVU lock input.
- Evidence: Weishaupt document above; weishaupt_modbus (independent). ModbusSpec devices/weishaupt/wbb.yaml:78-79, 200-201.
- Effect: with this template, "boost" can block the heat pump (or reconfigure its inputs), and "dim" can raise it. The
  template is marked deprecated. Existing configurations still use it.
- Confidence: medium (the swap against the document is clear; the effect of writing 45101/45102 depends on firmware
  accepting the write).

### 6. SolarEdge curtailer: sets bit 0 on top of an existing bit 1/2, and overwrites the installer's export limit when it releases
- Where: templates/definition/curtailer/solaredge.yaml:65-104.
- What it does:
  - Curtail <100 %: `mode | 1` keeps the other bits of 0xE000. If the site already runs indirect export limitation (bit 1) or
    production limitation (bit 2), the result has two of bits 0-2 set.
  - Every curtail (also 100 %): writes 0xE001 = 0 (Total) and 0xE002 = percent × nominal. On 100 % it also clears bit 0.
- What is right: Power Control Open Protocol for SolarEdge Inverters (local copy ef2bbde6….pdf), Export Limit Control Block,
  p. 14-15: "Only single selection is allowed on bits 0-2". Bits 10-11 may be combined with them. An installer-configured
  export limit (bit 0 with a site limit, or per-phase mode 0xE001 = 1) is a site setting. evcc should restore the previous
  values, not set "off / Total / nominal".
- Evidence: SolarEdge document above. ModbusSpec devices/solaredge/control.yaml:73-75 and enum export_control_mode l.206.
- Effect: (a) on sites with indirect or production limitation, evcc writes an invalid mode combination (undefined inverter
  behaviour). (b) On sites with a required export limit (zero export, 70 % rule, per-phase limit), lifting the curtailment
  removes that limit and sets the site limit to 100 % of the nominal power and Total mode. The site can then export beyond
  what the grid operator allows.
- Confidence: medium-high for (a). Medium for (b), which only matters where the installer configured a limit.
- Version note: the document also requires AdvancedPwrControlEn (0xF142) = 1, ReactivePwrConfig (0xF104) = 4 and a commit
  (0xF100) for "enhanced export limit control". evcc neither sets nor checks these.

### 7. Not-available sentinels used as real temperatures (low)
- Solvis: templates/definition/charger/solvis.yaml:92-99 reads S1/S2 (input 33024/33025) as int16 × 0.1 without handling the
  sensor-fault values. Technische Info SolvisControl 3 Modbus Spezifikationen (TNF-SC-3, 31399-2a, 1.0 2021-09), footnote
  under the input table (p. 9): 220 °C = open circuit, -30 °C = short circuit. evcc shows 220 °C as a real temperature,
  which is above any limittemp. Confidence: medium.
- NIBE S-series: nibe-s-series.yaml:139-146 reads BT7/BT6 (input 8/9) as `uint16`. M12676EN (p. 8) gives s16 × 10. Harmless
  for normal hot-water temperatures, but a negative or 0x8000 value turns into about 6500 °C / 3276.8 °C. Confidence: low.
- Stiebel LWZ: stiebel-lwa.yaml:25-32 reads input 15 as int16, not `int16nan`. ModbusSpec stiebel/lwz.yaml:76 (from the ISG
  document) marks -32768 as invalid. A missing sensor then shows -3276.8 °C. Confidence: low.

### 8. NIBE S-series: setmaxpower can be written below the documented minimum (low)
- nibe-s-series.yaml:163-171 writes holding 6007 (= 46008 "Power limitation", u16, factor 10 kW, min 11, max 1000 per nibe
  smos40.json) with W × 0.01. Below 1100 W evcc writes raw values under the minimum of 11 (1.1 kW). The template's help asks
  the user to set a minimum power, so this is only a guard issue. Confidence: low (only one model file gives the range).

## Checked, no bug found against a reference
- lambda-zewotherm: 102 (write, signed or unsigned by E-Manager setting), 103 / 1012 power, 1020 energy (INT32, Wh → ×0.001),
  2002/2003/3002/3003 temps and 2050/3050 limits (0.1 °C), all match Lambda "Modbus-Beschreibung-und-Protokoll" (2025-02-13).
  Its 5-minute refresh is satisfied by the 60 s watchdog. Version note: 1020 counts the compressor unit since the last
  statistics reset (not lifetime). 103 is the sum of all heat pumps, 1012 is heat pump 1 only.
- stiebel-lwa (stiebel.tpl stiebel-sgready): 4001/4002/5000 are the document's 1-based 4002/4003/5001. The input combinations
  (boost = input1, dim = input2) and the state map 1-4 match "Modbus Bedienungsanleitung" (ISG, SG-Ready Betriebszustände).
- nibe-s-series: 2741 (AUX via modbus 0/1, M12676EN p. 19), 1911 (31912 SG-Ready state 10/20/30/40), 6008 (46009 requested
  mode 0-3), 2305 power scale: consistent with the document and the nibe data.
- daikin-homehub / -air2air: 55/56 and 1000/1001 (1-based 56/57 and H1001/H1002 in daikin-ha-ekrhh-modbus). Power-limit scale
  W/10 matches POW16 (kW × 100). The SG map matches the enum.
- solvis: 2305 WW Sollwert (holding, 10-65 °C per TNF-SC-3). evcc's defaults 48/60 are in range, but the user values are not
  clamped. 33545 power: holding (evcc, hass_solvis_control) vs input (hassio-solvis-modbus, openWB). It is not in either Solvis
  document, so unresolved.
- kermi 301 (W × 10) and 108 (× 100): evcc and openWB agree. Only openHAB differs on the type.

## No independent reference (only evcc, or community sources that disagree without a document)
askoheat (319/317/325+/640; openEMS/openWB use 201/202/110/638 instead), glen-dimplex (5167/5170/5182/3/5048;
modbus_local_gateway has 5048 as holding in whole °C, while evcc reads input × 0.1), icharge-cion (100/101/139; status must be
ASCII A-F for StringGetter), idm (74/4122/1008-1014 read as holding, idm-heatpump-api as input), lg-therma, luxtronik (10311
energy read as uint16 kWh × 10 would wrap at 6553.5 kWh if the device has a 32-bit counter), mtec, ochsner-bwwp, ovum-mira, sma-homemanager
(40016).
