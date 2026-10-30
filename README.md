# ModbusSpec

Machine-readable Modbus register maps for solar inverters, batteries, energy meters, wallboxes and heat pumps.

Each device family is one YAML file: registers, data types, scaling, **sign conventions**, models and how to tell
them apart, identification, request limits, the faults and warnings the device reports, and which settings can be
written. Any program, in any language, can read and control a device from these files instead of hard-coding
register lists. The values use one common
vocabulary (`vocabulary.yaml`), so "grid power" means the same thing — and has the same sign — for every meter.

Device files are edited by hand. Their facts come from two kinds of source:

- **Manufacturer documents:** the Modbus documents the makers publish. Each file names its documents with version and
  address.
- **Open-source projects** (taken once; points from them are `verified: false` and name their sources): Home
  Assistant integrations (core and HACS) and the libraries they use, evcc's device templates and drivers, the mbmd meter
  definitions, and the device drivers of OpenEMS, openWB, openHAB, FHEM, Tasmota and SmartHomeNG. The projects are
  listed in `THIRD_PARTY_NOTICES.md`.

SunSpec devices are marked `sunspec: true`: their points are SunSpec models at the usual addresses. Finding the
models on a particular device (walking the SunSpec chain) is left to SunSpec's own tools.

## Contents

| Path | What |
|---|---|
| `FORMAT.md` | The file format (version 0, draft) |
| `OPEN.md` | Open issues: what needs a real device, documents wanted, what isn't done yet |
| `schema/device.schema.json` | JSON Schema for device files |
| `vocabulary.yaml` | Standard value keys, units and sign directions |
| `devices/<kind>/<maker>/<family>.yaml` | The device files, in a folder per `kind` |
| `LICENSE`, `LICENSES/` | CC0 1.0 for the data, MIT for the code |
| `tools/msp.py` | Reference tool: validate files, and read or write a real device with one (Modbus TCP, TLS, UDP, RTU over TCP/UDP; stdlib only) |
| `tools/collisions.py` | Which files' identification would take another file's device for theirs |
| `tests/` | Tests against simulated devices |

## Use

```sh
python3 tools/msp.py validate                                   # check every device file
python3 tools/msp.py read devices/charger/keba/kecontact-p30.yaml --host 192.168.1.40
python3 tools/msp.py write devices/charger/keba/kecontact-p30.yaml x.set_charging_current 16 --host 192.168.1.40
python3 -m pytest -q                                            # needs pytest, PyYAML, jsonschema
```

`read` prints the values in the vocabulary's units and signs, the detected model and word order, and any faults:

```json
{"device": "keba-kecontact-p30", "model": null, "word_order": "big",
 "values": {"state": 3, "state.text": "Charging", "consumer_power": 7360.0, "l1_current": 16.0, "…": "…"},
 "problems": []}
```

`write` sets one writable point (in the point's unit; an enum point also takes the value's name) and reads it back.
Writing changes how a real device runs: check the point's notes and the device's manual first.

## Editing device files

Every file in `devices/` is edited by hand; there is no generator.

- A value from a project stays `verified: false` until a manufacturer document or a real device confirms it.
- A `conflict` lists a different reading of a point. When a document or a real device settles it, set the right value,
  remove the conflict and say why in a `note`.
- `verified: true` only after a reading on a real device, with the reading in the `note`. Never put serial numbers or
  MAC addresses of real devices in a file.
- A project's `commit` and `path` under `sources` say where a fact came from at import time. Change them only after
  checking the fact against the new commit. New project versions don't reach these files by themselves.

## Adding a device

1. Create `devices/<kind>/<maker>/<family>.yaml` following `FORMAT.md`; start from an existing file.
2. List every document you used under `sources` (title, version, address). Don't copy the documents into the
   repository: most manufacturers don't allow redistribution. Register addresses, types and names are facts;
   keep notes in your own words.
3. Use vocabulary keys where they fit, `x.<name>` otherwise. For directional values (grid, battery, consumer
   power) say which way the device's raw value is positive.
4. Mark anything the documents don't state, or that you derived, with `verified: false` and a `note`. Set
   `verified: true` only after checking on a real device.
5. Run `python3 tools/msp.py validate` and add a test with a simulated device in `tests/`.

## License

Copyright (C) 2026 Amsler Solar GmbH

- **Data** — the device files (`devices/`), `vocabulary.yaml`, `schema/` and the
  documentation: [CC0 1.0](LICENSES/CC0-1.0.txt). Use them for anything, in any project, open or closed, with or
  without credit.
- **Code** — `tools/` and `tests/`: [MIT](LICENSES/MIT.txt).

See [LICENSE](LICENSE). The device files take only facts from the projects listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and from manufacturer documents; no code, comments or document text.
Everything comes without warranty.

Product and company names are trademarks of their owners. The register maps describe how to read and write
devices; they come with no guarantee that a device behaves as described — check on the real device before relying
on them.
