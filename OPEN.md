# Open issues

What the documents don't settle, what is missing, and what isn't done yet. Remove an entry when it is settled.

## Needs a real device

The documents leave these open; a reading from a real device settles them.

| Device file | Question |
|---|---|
| peblar-wallbox | Does holding 30123 read 1 (the identify check)? The only local material, Peblar's example client, reads 30122 for two values. |
| shoto-battery | Cell voltage factor: the document prints "100 0" on every row; 1000 (mV) is assumed, 100 would also give plausible values. |
| mainstream-mainprobe | Address offset: every 4xxxx number in the document is even, which hints at 40000 + address instead of 40001 = address 0. |
| rotronic-pf | Word order of 32-bit values: the layout tables and the read example disagree; detected from the ambient pressure. |
| huawei-luna2000b-cabinet, -ess | Which unit id each subsystem answers on (0 is the document's TCP default for the directly connected node); sign of charge/discharge and phase power. |
| alfen-eve-station, -socket | Word order on current firmware (detected). |
| keba-kecontact-p30 | Which firmware changed registers 1036 / 1502 from Wh to 0.1 Wh. |
| eltako-dsz15 | Meter code 0x0D at 0xFC02 (identify), read from the document's format column. |
| sungrow-shx | Grid state 13029 (0xAA off grid): scoped to the SH…K models; the old editions list it for the first SH…RS / RT too. |
| roth-touchline-sl, sauter-nrfc4, selco-s6100, ssregeltechnik-klgf, tolomatic-acs | The documents number registers without saying how numbers map to addresses; number − 1 (or as printed) is assumed, all unverified. |
| saci-cp40 | Register 816: model (V04) or firmware (V06); hour meters 84 / 86: float or integer. |
| fluidwell-f193x | How the document's byte offsets map to registers. |
| stange-em71 | Energy unit of the 0x2000 double counters. |
| ouman-eh200 | Scales (inferred from the decimals of the ranges); which alarms stop the heating. |
| zehnder-evo | 40000 → address 0; register 41004 (printed as a one-register float in °C); CO2 "not available" printed as 7FFh. |
| turbovex-tx | "CO2 external input" (3x0004) is to be written with function 06; how that maps to a holding register. |
| ventila-xcont | Two example frames (act_CO2 0x7537, filter lifetime 0x9C55) disagree with the register table. |
| eastron-sdm72 | The SDM72D-M-2 table skips L3 voltage (0x0004) although the meter shows it. |
| eastron-sdm | Meter code of the SDM220 (no document gives one). |
| etek-ekepc2 | Which edition is newer (only PDF dates): baud rate and the pole / trademark registers depend on it. |
| janitza-umg509pro, -umg512pro, -umg605pro, -umg96rmel, -umg96s2, -umg96pa, -umg96pql, -umg96el, -umg103, -umg806, -emd485 | No real device yet. Address base and power sign (lists don't state them; taken like the other UMG files). Files without identify: nothing in their lists tells them from other users of the 19000 block. |
| janitza-umg806 | Which firmware changed the 19000 block from kW / kWh (list of 01/2022) to W / Wh. |
| janitza-umg800, -umg801, -umg804, -umg20cm | No real device yet. UMG 800: units and signs inferred (its list has none), and the map is replaceable. UMG 804: address base (register 153 = 31415 would settle it); the firmware between its two lists is uncovered. UMG 20 CM: 8-bit `char` read as u16; module counts above I20. |
| janitza-rcm201-rogo, -rcm202ab, -procont, -prodata2, -ahf-svg | No real device yet; each identify rests on ranges or values not seen on a device. RCM 202-AB: bit 4 listed twice (bit 5 assumed for Current2k), and whether settings are writable. Procont: sign of main-meter power; External Meter Power listed UINT16 over two registers (read as u32). AHF / SVG: 0x1203 device type; TCP assumed. |
| bituo-sdm01 | No real device yet. Sign of power (import assumed); whether 247 is really the factory address although 1–246 are listed as valid. |
| aerl-coolpro | No real device yet. What kind of device it is; whether address and baud rate survive a power cycle. |
| sentek-probe | No real device yet. Default Modbus address (1 assumed); units of the cooked values (none given); relative address of 30025 (0x0018 by the layout, 0x0019 printed). |
| energielenker-lobas | No real system yet. Which rows of models 60000 and 60001 can be written; device models 113, 213 and 124 have no fixed address, so they stay in the notes. |
| navien-nfb700 | No real device yet. Address base (no frame example; references read as 1-based); whether registers follow the C/F display setting; scale of the sub 2–7 current gas (Resolution 1, main and sub 1 have 100); units beyond sub 7 (ranges imply 32, rows stop at 7). |
| marley-marleygard-cd | No real device yet. Nothing about the protocol is stated: table, 1-based addresses, Short / Long signedness, float word order and alarm bit order are assumed. No units, and nothing can be marked writable from the document. |
| mccrometer-procomm | No real device yet. The sensor test flags are printed for register 0021 (the sample count) but fit 0032; how the overflow count adds to a total. |
| benshaw-emx4 | No real device yet. Which value clears a command (bit 15 needed; 0 means legacy mode on TCP); units of current and voltage; whether AuCom's 30621 and 30622, reserved in Benshaw's guides, answer. |
| Benshaw RSi S, RSi H2 | No file: their Ethernet/IP & Modbus-TCP manuals (890049-09-00, 890053-03-01) give only the frame and function codes, no named register. Needs the drives' own manuals. |
| abb-b23-b24 | Outage time 0x8A39 (2 registers listed, the layout needs 3); 0x8A50 / 0x8A54 labelled "active", probably reactive. A real B23 with firmware B1.28.0 reads all of 8A30–8A5F as invalid, so another firmware is needed. |
| carlogavazzi-em24-din | Whether the extra V2R0 registers still exist on current (V4) meters. |
| deye-p3 | Device type 0x0005 / 0x0006 in the HP3 edition: typo for 0x0500 / 0x0600, or real (accepted in identify). |
| sungrow-sg | State data 2 (5045): the document points to a value table it doesn't contain. |
| huawei-dtsu666-h | Read on a real meter with only L1 connected and no load: the phase order of the per-phase energies (L1 showed at +6, not +2), the sign and scale of current, active power and power factor, the reactive / apparent power positions (2134–2148), and the unknown pairs at input 5438–5452 / 8244–8258 need a load on two or three phases. |
| acrel-dtsd1352 | Read on one Sungrow-labelled unit with only L1 connected and no load. Needs a load on three phases for currents, powers, signs and power factors. Register 20480 (not in Acrel's manual) reads 0x102F there: does a plain Acrel read the same? Meanings of the undocumented registers found by the sweep (0x0099 to 0x00B1, 0x00C4 to 0x00CB), which need a setting changed on the display and read back. Single-register sweep above about 0x24B8. Harmonic registers read 0 with 235 V on L1: does this unit measure them? |
| acrel-adl400, acrel-adl200, acrel-acr10r-dxxte, acrel-acr10rh-dxxte4 | No real device yet and no identification in the manuals. Direction of power and the word order of floats are assumed. ACR10RH: whether its power registers carry a sign, or only register 3001 does. ACR10R-DxxTE: whether measurements are primary or secondary. |
| acrel-adl200m-adl400m | No real device yet. Does 0x000B really read 0xAC01 to 0xAC04? Word order of the floats and doubles, and what unused registers return on single-phase and single-channel models. |
| acrel-adw300 | No real device yet. RS485 default settings (1200 8N1 comes from evcc), and the signedness of power and energy. |
| sungrow-dtsu666 | Does any meter really report 0x20D5 at 20480? The one Sungrow-labelled meter read so far reports 0x102F and is an Acrel DTSD1352. Is real Sungrow Chint hardware also on this map? That meter's baud setting follows the ADL400 list (3 = 9600, 4 = 19200), not the 1 = 9600 list of Sungrow's document, which this file keeps. |
| socomec-countis-e4x | No reading from a real E43 / E44 yet: frequency factor Hz / 100, and everything else from the tables. |
| socomec-countis-e0x, -e1x, -e3x, -e5x, -p04 | Written from the tables; no real device read. The model names at 50058 are assumed from the E24 ("Countis E24"). |
| socomec-countis-m04, -m34 | Written from the tables; no real device read, and no identification: the table gives no Product ID values. Serial number at 64512 assumed to be a holding register. |
| socomec-diris-b30 | Written from the table, a focused part of its 5,565 rows; no real device read. Direction of the active power, and the model name at 50058. |
| socomec-countis-eci, -evdc, -diris-mcm48, socomec-atys-c55, -c65, socomec-statys | Written from the documents; no real device read. Names at 50058 assumed; EVDC, MCM-48 and STATYS have no identification; EVDC input addresses assumed from register numbers. |
| socomec-ups | Delphys XM / XL added from their manuals; no real device read. XL S011: 'Temperature' in the manual, taken as a slip for 'Operating'. |
| socomec-countis-e2x | Read on a real E24 without load: the sign of the powers needs a load. E23, E27 and E28 not read. |
| kostal-ksem | Signs of inverter AC, PV DC and battery power in the energy-flow block (40974–40984): read 0 at night on a real KSEM (firmware 2.7) without a managed KOSTAL inverter; grid power (40972) is settled. Modbus TLS (port 802) not tested. |

## Answers without a document

Read on a real device, outside any document of its maker.

| Device file | Registers and values read |
|---|---|
| goodwe-et | One ET (GW29.9K-ET, firmware 04062-13-S00, 8 battery clusters), two sweeps; holding registers in no GoodWe document: **22000–22164** 8 records of 21 registers, one per cluster (37077 / 37078 read 8): 10 registers ASCII (a module serial number, space padded), then 3, 3, 16, 1000 and counters; **23000–23255** 8 records of 32 registers (values like 0x258, 0x0D30 = 3376, 0x0103–0x0108; meanings unknown); **38000–38051** 4 records of 20 (e.g. 0x096C = 2412, 0x1389 = 5001); **45000–45019** and **45155–45158** ASCII "12345678"; **45075–45110** "tcp.goodwe-power.com" and 0x4E21 (20001), a cloud server setting; **45134** "GW29.9K-ET"; **45203** and **2000–2008** the inverter serial (2008: 0xF7, the unit id); **45361–45371** 1, 3000, 3400, 3800, 4000, 3700, 5000, 3000, 4150, 4350, 4700 (most as at 51001–51007); **32100–32114** (0x0201 at 32100, 1 at 32109, 0x0800 at 32111); **33000–33017** (1000 at 33000 and 33003; 36000 at 33002, 33005 and 33012; 45000 at 33007; 2000 at 33008; 29900 at 33010 and 33017, the rated power; 2 at 33013); **35041** (3); **37079–37094** after the BMS1 block; **48900–48999**, **55250–55316** and **15021–15030** (patterns like 0x5555); the SunSpec chain at **60000–60655** (noted at 45153). Zero and 0xFFFF also stand for "not there" on this inverter. |
| abb-b23-b24 | One B23 212-100 (firmware B1.28.0): **1002–1047** in no manual (236, 189, 187 at 1003 / 1005 / 1007 and 48, 4, 50 at 1009 / 100B / 100D, the phase and line-to-line voltages in whole V; 3 at 103F; 0x0000C35A = 50010 at 1046, probably the frequency in mHz; the rest 0); **8911** (0x0102); **8966–896D** a 16-character text starting with "ABB" and ending with the serial number. |
| (none) Fronius Smart Meter TS 65A-3 | One meter (production year 2022) on RS485, unit 1, 9600 8N1; no Fronius or Carlo Gavazzi document for it. Carlo Gavazzi layout: 32-bit values low word first, functions 03 and 04 give the same registers. Answered stretches: 0000–0097, 00F8–01B5, 0400–040F, 0500–0533, 1000, 1010–1011, 1100–1105, 1200–1201, 2000–2004, 4000–4001, 5000–5008, 5010; more single registers answer alone (0302–0303: 1, 4, firmware / revision as on an EM300). Input 000B read alone gives **731**, a model code no Carlo Gavazzi file knows (read in a block it is the high word of V L3-L1, 0). Serial number one character per register at 5000–5006, 2022 at 5010. Unlike the EM300 map, 0031 reads 500 (50.0 Hz?) and 0033 reads 0. |

## From the Home Assistant / evcc check (no document)

| Device file | Question |
|---|---|
| bluetti-balco260 | Grid phase 1 power (50235) u16 from the library; probably s16. |
| salda-smarty / salda-mcb | One register apart for the same controller family; Smarty temperatures signed or not. |
| xtherma-heatpump | Temperature 124 scaled ×10 (from evcc), implausible. |
| nibe-s-series | Total consumption (input 3823): u16 (evcc) or u32 low word first (nibe library). |
| weishaupt-wbb | 45101 / 45102 labelled writable mode registers (projects); possibly read-only input configuration. |
| solaredge-se-mtr-3y | Energy from the counters mbmd calls resettable (0x03EA / 0x0458); 0x03EE / 0x045A may be the totals. |
| cfos-power-brain | Power 8062 signed or not. |
| sigenergy-inverter | evcc's holding-table copies of 31017–31021 labelled grid currents (the document's are inverter currents). |
| kostal-plenticore | Project-only points 1038–1044 fixed to little word order; no local document. |
| huawei-smartlogger-plant | 40446 (s64, evcc) not in Issue 35; 40428 s16 vs the document's U16. |
| goodwe-et | 36015 / 36017 energy unit: kWh assumed, the projects use Wh. |
| evracing-evse-wb-din | 2005 bit 7: "PWM debug" in the datasheet, a 0.01 A mode in the projects. |
| sma-hybrid | DC input 3 (30967) on newer Smart Energy models. |
| webasto-next | Currents 1008 / 1010 / 1012: function 03 (OpenEMS) or 04 (evcc). |

## Decisions

- **growatt-legacy:** do the projects' models MIC 600-3300TL-X, MIC 2500-5500MTL-S and TL3-S 3000-15000 use the old
  V3 map? Their points on the V3 registers give 38 conflicts.
- **solax-inverter / solax-x3-mic-g2:** the projects' MIC models stay in solax-inverter; the MIC G2 document is its
  own file. No identify overlap.
- **fronius-datamanager / fronius-gen24:** identical identify blocks (recorded in tests/identify_overlaps.yaml).
- **solarfocus-vampair:** the document also covers Solarfocus pellet / therminator boilers and the standalone
  ecomanager-touch; they are in the heat pump's file.

## Documents wanted

Named by documents in the collection but not in it:

- Carlo Gavazzi EM500 communication protocol (EM530 / EM540 registers)
- ABB CM-TCN operating manual (insulation monitor register map)
- Daikin ED 15063 (MicroTech II chiller Modbus register map)
- DEIF ASC-4 and iE 150 Modbus register spreadsheets; Multi-line 2 option H2
- SEG Electronics WIC1-2.3 Modbus data point list (Excel)
- e-Controls e-Bus Display and e-Room ECO Modbus register documents (V1.1.0)
- JVL MAC400 / MAC800 and SMC75 / MIS user manuals with full register lists
- ICP DAS (P)ET-7000 register table
- IMI TA-Slider 160 BACnet / Modbus protocol document
- Electrex (Akse) NET D6 Modbus protocol document
- descon trol programming guide KA00213 (XV controller register map)
- Tpiab THAITI-118-130 ElectaMAXI-ECO: the copy is password-protected
- Siemens SENTRON PAC4200 register map; Carlo Gavazzi EM24 V4 protocol; NIBE AirSite / GreenMaster v26; Peblar
  Modbus developer page

Not named by a document, but missing for a device file:

- Huawei EMMA (SmartHEMS) Modbus interface definitions: huawei-emma is taken from open-source projects only
- Fronius Smart Meter TS 65A-3 Modbus register list (model code 731): no device file for the meter on RS485

## Not done

- **Socomec DIRIS B-10:** table not read yet.
- **Socomec COUNTIS E47 / E48, P43, P44:** only manuals and datasheets without register tables were at hand.

- **Vertiv IntelliSlot guide SL-28170:** the UPS and power maps are done; cooling (CW/DS/PDX, DCD, CRV, CRC, CAHU,
  DCP, DME2, iCOM XDM, DataMate / MiniMate2, Mini-Mate3, PEX4, XDC, XDP, CoolPhase Wall, CoolCenter, CoolLoop), PDUs
  and STS2, Alber BDSU and Liqui-tect LP3000 / LP6000 are not.
- **Vertiv EXS/ITA2:** 30471–30473 (battery run time, humidity, commission date) have garbled units in the guide.
- **Vertiv EXL S1:** a legacy Chloride map (holding 40002–40148) is only described in a note.
- **Source URLs:** DEIF MIB, ICS Schneider IDCT, meteocontrol, Nanotec CLC, Enovates, SmartEVSE and Peblar cite
  their documents under a URL that differs by a query string or path from the address the document was collected from.

## Format gaps

Written as notes until the format can say them:

- Units chosen by a setting on the device (°C / °F).
- Settings the device saves to EEPROM by itself every few minutes (PMA KS, Sugar Valley NeoPool): neither
  `persistent: true` nor `false`.
- Writes that need a sequence: a password first, a save command after, a heartbeat to keep a mode.
- Persistence that depends on the function code (UUMotor: 16 stores, 06 doesn't).
- Ranges with gaps or special values beyond `invalid` (e.g. "0 or 6–32 A", "0–100 or 255", power factor
  −1…−0.8 and 0.8…1).

## Not tested on a real device

- `msp.py write` (and the write rules in FORMAT.md) are tested against a simulated device only.
