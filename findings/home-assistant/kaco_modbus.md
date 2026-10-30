# kaco_modbus — HA core bd8b1bc

## Scope
- HA pins `kaco-modbus==1.1.0`; local checkout upstream/lib/kaco-modbus is at tag v1.1.0 (9f4578c) — same version.
  Runtime decoding from `modbus-connection==4.12.6` (HA modbus manifest), checked in scratchpad/mc/modbus_connection-4.12.6.
- HA reads only model 103 (sensor.py:33-75): W (offset 14, s16, W_SF @15), WH (offset 24, acc32, WH_SF @26),
  St (offset 38, enum16). No writes. Polls the library "readings" group (inverter, mppt, status) every 30 s.

## Comparison
ModbusSpec devices/kaco/inverter.yaml (model 103 at 40070 on the captured chain): W 40084 / SF 40085, WH 40094 u32 /
SF 40096, St 40108 enum 1..8 — all match the library offsets. Units W / Wh, TOTAL_INCREASING energy, enum options
(off…standby) match SunSpec OperatingState 1-8. Sentinels: s16 0x8000 / acc32 0 / enum 0xFFFF -> None (modbus_connection
sunspec/__init__.py:60-66); unknown St values -> None (fields.py:283-302). SF clamped to -10..10. No HA-side issue found.
Most model-103 points in the spec come from kaco-modbus itself; the KACO document (APL Modbus-Protocol 180730) only
describes model 1 and the supported-model table, so independent evidence for 103 offsets is the SunSpec model itself.

## Bug candidates

### 1. Single-phase KACO inverters (blueplanet TL1) rejected — LOW confidence
- Where: g4bri3lDev/kaco-modbus v1.1.0, src/kaco_modbus/const.py:20-35 (`INVERTER_MODEL_ID = 103`, comment "There is no
  TL1 or NX1"), device.py:190-192 (raises ModelMissingError when 103 absent); HA config_flow.py:72 maps it to
  "not_a_sunspec_inverter".
- What it does: only binds SunSpec model 103 (three-phase), on the stated premise that KACO has no single-phase models.
- What is right: the KACO document lists the blueplanet TL1 series as supported ("Supported Inverter Model: blueplanet
  TL1/TL3 series"; supported-SW table: blueplanet TL1 V3.00+, V3.26+, V4.00+). The table gives models "001, 102, 103"
  for the TL1/TL3/Powador rows jointly, so it does not settle whether a TL1 advertises 103 or only a single/split-phase
  model (101/102).
- Evidence: KACO Modbus Protocol Application Note, Tx1 and Tx3 Series, version 180730, page 2 ("Supported Inverter
  Model" and "Supported SW Version" table); ModbusSpec devices/kaco/inverter.yaml notes (supported models by version).
- User-visible effect: if a TL1 exposes only 101/102, setup fails with "not a SunSpec inverter".
- Confidence: low (the premise in the code is contradicted by the document; the actual chain of a TL1 is unknown).

## Notes (not bugs)
- Version note: per the document, blueplanet TL3 V2.02+/Powador TL3 V2.10+ have models 1, 102, 103 only (read-only);
  122/123 from TL3 V3.22 / TL1 V3.26; 160 etc. from V4.00. HA only needs 103 — fine.
- Unit id: document says the UID is ignored over TCP on legacy devices and addresses auxiliary RS485 devices (e.g.
  string combiners) on the new generation. HA defaults to 1 and allows 1..247 — fine as long as the inverter answers on 1
  (the library/ModbusSpec say it does on the captured device).
- Document warns that some settings are stored in flash and must not be written periodically; HA writes nothing, so
  not relevant. (The library's own control helpers write WMaxLimPct_RvrtTms on each set — not used by HA.)
- Library comment says the PF is "parked at 1.00 while asleep" (device.py power_factor docstring), the spec note says
  "reads 0"; PF is not used by HA.

Checked: 3 sensors (W, WH, St), model-103 offsets/types/SF/sentinels in library + modbus_connection, config flow /
identification, vs ModbusSpec kaco/inverter.yaml and KACO APL 180730.
