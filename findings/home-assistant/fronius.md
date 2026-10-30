# fronius (Modbus part) — HA core bd8b1bc

## Scope / caveat
- HA pins `PyFronius==0.8.2` (HTTP Solar API, not Modbus) and `fronius-modbus==0.2.0` (PyPI library; with
  `modbus_connection` from HA's modbus component, `modbus-connection==4.12.6`).
- **The pinned `fronius-modbus==0.2.0` library is not checked out locally.** The ModbusSpec pin with id `fronius-modbus`
  (tools/import/upstream/fronius-modbus.yaml) is a *different* project: redpomodoro/fronius_modbus (HACS integration,
  upstream/hacs/redpomodoro__fronius_modbus). Its conflicts in devices/fronius/gen24.yaml (e.g. MinRsvPct/ChaState/
  InWRte/OutWRte fixed scale 0.01) are about the HACS project, not about what HA core runs. Not downloaded (brief).
  So the library register map (addresses, SF handling, StorCtl_Mod bits, ChaGriSet mapping, unit-id mapping
  `GEN24_UNIT_ID` / `datamanager_unit_id`) could NOT be checked. Only the HA component layer was checked.

## What HA reads / writes (component layer)
- Readings (coordinator.py:250-279, sensor.py:296-368): SunSpec model 160 per module DCA/DCV/DCW/DCWH (up to 6 modules),
  plus library aggregates `pv_energy_total`, `storage_charge_energy_total`, `storage_discharge_energy_total`.
  Energies: Wh, TOTAL_INCREASING, `invalid_when_falsy=True` (0 -> unknown). Entities only created once a value is not None.
- Settings (coordinator.py:282-497, number.py:39-82, switch.py:37-62): model 123 WMaxLimPct (0-100 %, step 1) +
  WMaxLim_Ena + WMaxLimPct_RvrtTms (3600 s or 0, heartbeat every 15 min); model 124 charge/discharge limits
  (0-100 %), their enables, MinRsvPct (0-100 %), ChaGriSet (switch).

## Checked against the manufacturer documents
Fronius GEN24 / GEN24 Plus Modbus TCP & RTU workbooks (doc 42,0410,2649, zip changelog up to 1.2.7-2),
`Gen24_Primo_Symo_Inverter_Register_Map_Int&SF_storage_ROW.xlsx` sheets controls (123), mppt (160), storage (124); and
Inverter Register Map Float v1.0 with SYMOHYBRID MODEL 124 (Datamanager).
- WMaxLimPct 0-100 % (SF -2): HA 0..100 step 1 — OK.
- WMaxLimPct_RvrtTms 0-28800 s: HA writes 3600 or 0 — OK.
- Model 160 DCWH acc32 Wh with shared auto-scaled DCWH_SF; 0 = not accumulated — HA maps 0 to unknown — OK.
- MinRsvPct uint16 % with SF -2 — HA 0..100 — OK.
- ChaGriSet 0 = PV (grid charging off), 1 = GRID (on) — HA exposes a bool switch; the library's mapping could not be checked.
- StorCtl_Mod bit 0 = CHARGE limit (InWRte) active, bit 1 = DISCHARGE limit (OutWRte) active — matches HA's
  charge_limit/discharge_limit + *_enabled pairing; library mapping not checkable.

## Bug candidates
None confirmed at the HA component layer.

## Notes (not bugs)
- Limitation: battery charge/discharge limits are restricted to 0..100 % (number.py:56-69), while the documents allow
  InWRte/OutWRte -100.00..+100.00 % (negative = force the opposite direction; power window). Forced charge/discharge is
  therefore not possible from HA. Design choice.
- Safety-net asymmetry: the "auto revert" option only sets WMaxLimPct_RvrtTms (model 123). Battery limits written via
  model 124 get no InOutWRte_RvrtTms (Gen24 doc: RW, 0-28800 s; Datamanager/Symo Hybrid: "Not supported"), so a 0 %
  discharge limit set from HA stays in force indefinitely if HA stops. Design note.
- Version note (Gen24 doc model 160, modules 3/4): up to SW 1.30 the storage charge/discharge DCV/DCWH read 0 while the
  battery runs the other way; since 1.31 they are continuous. HA's invalid_when_falsy turns those 0 into unknown — OK.
- Version note (changelog 1.2.6-1): US Gen24 without battery expose model 124 with all registers "not supported";
  HA only creates entities for non-None values, so this is fine provided the library returns None for the sentinels
  (not checkable).
- Datamanager workbook: model 160 DCWH / DCWH_SF "Not supported for Fronius Hybrid inverters" — affects
  pv_energy / mppt energy on Symo Hybrid; fine if the library yields 0/None (not checkable).
- Modules 3/4 on Gen24 with storage are battery charge/discharge (IDStr 'StCha 3' / 'StDisCha 4') but HA also exposes
  them as "MPPT 3/4" power/energy sensors (power enabled by default). Naming only.

Checked: 2 coordinators, 27 sensor descriptions (6 modules x 4 + 3 totals), 4 numbers, 4 switches,
write/heartbeat logic vs 2 Fronius workbooks; library register map not checkable (0.2.0 not local).
