# u5a — evcc SMA meter templates (read only)

Files: sma-datamanager, sma-hybrid, sma-inverter-modbus, sma-sbs-15-25-modbus, sma-sbs-modbus, sma-si-modbus, sma-webbox
(evcc bf5c276, templates/definition/meter/).

References used:
- D1 "SMA Modbus Interface – SMA Data Manager", EDMx-Modbus-TI-en-16 v1.6 (local 9d5fab86…pdf), §3.4.5 NaN table p.9, §4.3 Unit ID 2 table p.14-16.
- D2 "SMA Modbus register lists per device family", SMA_Modbus-TI-en-31.xlsx v3.1 in SMA_Modbus-de-en_V25.zip (local a8c84a2b…zip):
  sheets "SB 3600-5000SE-10, PKG 2.4" (Sunny Boy Smart Energy), "SInnH-11 / SInnM-11, PKG 4.0" (Sunny Island), "SB nn00TL-21".
- D3 "Remote control of Sunny Tripower Storage X / Sunny Island X via Modbus", SMAModbus-STPS-X-SI-X-TI-en-11 v1.1, p.13 (40236 enum: 303 Off, 308 On, 2289 charging, 2290 discharging, 2424 default).
- evcc NaN handling: util/modbus/functions.go:97-115, util/modbus/register.go:104-131 (NaN sentinel -> returns 0).

## Bugs

### 1. sma-hybrid grid energy 30581 decoded as signed int32 (documented U32)
- Where: evcc templates/definition/meter/sma-hybrid.yaml:59-62 (`address: 30581`, `decode: int32nan`, scale 0.001).
- evcc: int32nan -> NaN sentinels 0x80000000 / 0x7FFFFFFF.
- Right: 30581 "Grid reference counter reading", U32, FIX0, Wh (D2 sheet "SB 3600-5000SE-10, PKG 2.4", row 37). U32 NaN = 0xFFFFFFFF (D1 §3.4.5 p.9). Should be `uint32nan`.
- Effect: when the inverter has no meter value (no Home Manager / energy meter connected), 0xFFFFFFFF is not recognized as NaN and decodes to -1 Wh -> grid import energy shows -0.001 kWh instead of 0 / not available. (Overflow beyond 2^31 Wh is irrelevant in practice.)
- ModbusSpec devices/sma/hybrid.yaml:38 copies evcc's s32 (source evcc only) - mirrors the bug.
- Confidence: high on type mismatch; impact low.

### 2. sma-hybrid PV power sums DC input [3] 30967, which Sunny Boy Smart Energy does not define (version note / low)
- Where: sma-hybrid.yaml:153-174 (pv = 30773 + 30961 + 30967, each a separate single read).
- D2 "SB 3600-5000SE-10, PKG 2.4" lists only 30773 "DC power input [1]" (row 42) and 30961 "DC power input [2]" (row 83); no 30967.
  D1 p.9 ("Reading multiple Modbus registers as a data block"): if none of the requested registers is defined, the device answers with a Modbus exception.
- Effect (if the device behaves as documented): the whole pv calc fails on 2-MPPT models -> no PV power. Newer SE firmware/models (STP x.0-3SE, SBSE) have no device sheet locally, so it may well be defined there.
- Confidence: low (only the older SB SE sheet as evidence).

## Checked, consistent with documents
- sma-datamanager: 30775 S32 W, 30513 U64 Wh, 30845 U32 %, 31249 S32 W (sign undocumented; evcc's scale -1 matches feed-in-positive naming of 31503-31507), 31535-31539 S32 FIX3 A (sign undocumented), 31393/31395 U32 W, 31401 U64 Wh, unit id 2 - all match D1 p.14-16.
- sma-hybrid: 30865/30867 S32 W reference/feed-in (D2 SB SE rows 74/75), grid = in - out OK; 30773/30961 S32 W; 30845 U32 %; writes 40236 (2289 / 2424 match D3 p.13), 40793/40795/40797/40799 U32 W (D2 SB SE rows 170-173); 40801 is S32 (row 174) but evcc writes uint32 0 - harmless.
- sma-sbs-modbus / sma-sbs-15-25-modbus: same control block; 30775/30513/30845 as in profile. Design note: no maxdischargepower param, discharge max in "normal" is written as maxchargepower (sma-sbs-modbus.yaml:100, sma-sbs-15-25-modbus.yaml:100) - not a register bug.
- sma-si-modbus: 30775 S32 W, 30513 U64 Wh, 30845 U32 %, 40149 S32 W WO, 40151 U32 ENUM WO (D2 SInnH-11 rows 33/13/50/172/173). Values 802/803 for 40151 and "negative setpoint = charge" are not in any local document.
- sma-inverter-modbus: 30775 S32 W "Power", 30513 U64 Wh "Total yield" (D2 SB nn00TL-21 rows 42/22). input vs holding: SMA answers FC 03 and 04 alike (D1 p.8 function code table).

## No independent reference
- sma-webbox (no WebBox Modbus document locally).
- sma-sbs-modbus, sma-sbs-15-25-modbus: no Sunny Boy Storage sheet; checked only by analogy with the SB SE / SI sheets.
- sma-hybrid: 31259-31269 per-phase powers, 31435-31439 currents, 31393/31395/31401 (not in the SB SE sheet; documented only for the Data Manager / SI), 30967.
- sma-si-modbus: 40151 enum values 802/803, sign of 40149.
- Signs of 31249 and 31535-31539 (Data Manager) undocumented.
