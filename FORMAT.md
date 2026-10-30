# ModbusSpec format, version 0 (draft)

One YAML file per device family in `devices/<kind>/<maker>/<family>.yaml`; the folder is the file's `kind`. It describes what a program needs to read and
write the device over Modbus — registers, types, scaling, sign, models, identification, limits, faults and which
settings can be written — so any language can use it. Checked by `schema/device.schema.json` and `tools/msp.py validate`.

## Top level

| Key | Required | Meaning |
|---|---|---|
| `modbusspec` | yes | Format version: `0` |
| `id` | yes | Unique id, lowercase with dashes, e.g. `eastron-sdm` |
| `manufacturer`, `name` | yes | Shown to users |
| `kind` | yes | `inverter`, `battery`, `meter`, `charger` (wallbox), `heat_pump`, `heating_rod`, `boiler` (any other heating: gas, oil, pellets, heating controllers), `ventilation`, `hvac` (air conditioning), `pool`, `ups`, `io` (relay and input modules, sensors), `energy_manager` (oversees a site: grid, PV, battery and loads; reports site totals and may control the devices behind it, e.g. home energy managers, data loggers, plant controllers), `other` |
| `sources` | yes | Documents and projects the file is based on (below) |
| `connection` | yes | Defaults and limits (below) |
| `encoding` | no | Byte and word order (below); default big-endian both |
| `defaults` | no | `verified` and `sources` most points share (below) |
| `sunspec` | no | `true`: the points are SunSpec models (below) |
| `models` | no | Variants with their own registers and how to tell them apart |
| `model_choice` | no | `auto` (default): readers detect the model; `user`: the models can't be told apart from the device, the user picks one (below) |
| `identify` | no | Checks that this really is the device, and where the serial number is |
| `points` | yes | The values (below) |
| `enums` | no | Named value tables, referenced by points |
| `flags` | no | Named bit tables (bit number → text), for status, alarm and error words; referenced by points |
| `problems` | no | Faults and warnings the device reports (below) |
| `reserved` | no | Registers (or bits) the manufacturer marks reserved: no point may read them (below) |
| `notes` | no | Free text: anything a reader should know; mark unverified things as such |

## `sources`

```yaml
sources:
  - title: GoodWe ET/EH/BT/BH Modbus protocol    # a manufacturer document
    version: "1.7"
    url: https://…
  - id: goodwe                                   # an open-source project the registers were taken from
    title: goodwe (Python library)
    url: https://github.com/marcelblijleven/goodwe
    license: MIT
    commit: 66dfcdd9cd947bfd799f2bddb40b4e05ba9db6f6
    path: goodwe/et.py
```

A source with an `id` can be named by points (`sources: [goodwe]`). Points without `sources` come from the
documents. Only facts are taken from projects (address, type, scale, unit, name); never their code or comments.
Values taken from projects are `verified: false` until checked against a manufacturer document or a real device.

A document source can also say what was recorded about the document when it was collected. This describes that copy,
which needn't be the very one the file was written from:

```yaml
  - title: BESS Modbus protocol Map
    version: V1.1
    url: https://…
    sha256: 5f4292b8…              # of the collected file
    archive_url: https://web.archive.org/…   # a byte-identical copy in a public web archive
    date: 2025-03                  # also `number` (the maker's document number) and `language`, if known
    devices: [GW15K-ET]            # the products the document names
    related:                       # other documents that belong with it, e.g. manuals with the fault tables
      - {title: "ET Series 15-30 kW – User Manual", what: fault tables}
```

## Addresses

Addresses are **0-based protocol addresses** together with the table: `table: holding` (function 03), `input`
(function 04), `coil` (function 01) or `discrete` (discrete inputs, function 02). A document's "30001" or "40001"
style reference becomes `address: 0` with the matching table. Hex is fine: `address: 0x0034`. Coils and discrete
inputs are single bits: their points have `type: bool` (0 or 1), the only type they may have.

## `connection`

```yaml
connection:
  default_port: 502
  default_unit: 1
  transports: [tcp, rtu]          # how the device can be reached (below)
  ports: {rtu_over_udp: 8899}     # a transport's port where it isn't default_port
  reply_prefix: "AA55"            # bytes a device puts before each RTU reply frame (hex), with rtu_over_*
  tls:                            # with the tls transport: what the device requires (as far as documented)
    client_certificate: required  # required, optional or none
    roles: [Operator, Viewer]     # role names the device accepts in the client certificate's role extension
    min_version: "1.2"
  serial: {baud: 9600, format: 8N1}
  limits:
    max_registers: 80             # per request
    even_address: true            # start and count must be even
    max_gap: 0                    # registers a reader may read across between points (default 0)
    min_interval_ms: 500          # between requests
  input_equals_holding: true      # function 03 and 04 read the same registers (e.g. SMA, Siemens PAC); a reader
                                  # may use either
  write_multiple: true            # the device only takes writes with function 16 (registers) / 15 (coils), also
                                  # for a single register or coil (see "Writing")
  write_single: true              # the device has no function 16: a value over several registers is written with
                                  # one function 06 per register, first register first
  blocks:                         # ranges the device only answers as a whole: read each in exactly one request
    - {table: holding, address: 64000, count: 27}
  sleeps: true                    # powered by its panels: no answer at all means asleep (no production), not a fault
```

Transports:

| Transport | On the wire |
|---|---|
| `tcp` | Modbus TCP: MBAP header + PDU over a TCP connection |
| `tls` | Modbus/TCP Security ("mbaps", Modbus Organization MB-TCP-Security): the Modbus TCP frame inside TLS 1.2 or later, usually on port 802, with x.509 certificates on both sides; the device may authorise by a role in the client certificate |
| `udp` | Modbus over UDP: the Modbus TCP frame (MBAP header + PDU), one datagram each way |
| `rtu` | Modbus RTU on a serial line (RS485), usually reached through a Modbus TCP gateway |
| `ascii` | Modbus ASCII on a serial line |
| `rtu_over_tcp` | RTU frames (unit id, PDU, CRC-16) over a TCP connection, as transparent RS485 gateways and some dongles pass them |
| `rtu_over_udp` | RTU frames in UDP datagrams (e.g. GoodWe's Wi-Fi/LAN dongles) |

The certificates belong to each installation and are never part of a device file; `tls` only says what the device
asks for. UDP doesn't guarantee delivery: a reader sends a request again after a timeout. `default_port` applies to every
transport `ports` doesn't name; `default_unit` to all of them.

A point inside a `blocks` range is read by reading the whole range. With `sleeps`, a reader that gets no answer
(timeouts, connection refused) reports the device as asleep instead of failed.

## `encoding`

```yaml
encoding:
  byte_order: big                 # within a register: big, little, or detect
  word_order: big                 # big = most significant register first; little; or detect
  detect:                         # only with detect
    table: input
    address: 0x0046
    type: f32
    plausible: [40, 70]           # the order that gives a value in this range wins
```

`detect` takes `plausible` (a range) or the condition fields `equals`, `in` or `range`, and `unit_id` where the
register answers on another unit id. Readers try big before
little, the word order first: with both set to detect, (big, big), (little, big), (big, little), (little, little);
the first combination in which the detect register meets the condition wins (big if none does).

A device that states its word order in a register names it with `word_orders`, value → order:

```yaml
  detect: {table: holding, address: 5, type: u16, word_orders: {"0": little, "1": big}}
```

## `points`

```yaml
points:
  - key: grid_power               # a key from vocabulary.yaml, or x.<name>
    label: Total system power     # the document's name
    table: input
    address: 0x0034
    type: f32                     # see "Types" below
    unit: W
    scale: 1                      # real value = raw × scale + offset (default 1, 0)
    scale_exponent_from: {table: holding, address: 40084, type: s16}   # SunSpec-style: × 10^value
                                  # (negate: true for devices that divide by 10^value instead)
    unit_id: 50                   # read on this unit id instead of the device's (for devices that answer
                                  # some registers on other unit ids)
    positive: import              # for keys with a direction: which way the raw value is positive
                                  # (per-phase power: the direction of the device's main power, by `kind`)
    enum: state                   # name in `enums`
    flags: alarm_bits             # name in `flags`: each set bit has its own meaning
    models: [sdm630]              # only for these models (default: all)
    poll: fast                    # fast (live values) or slow (counters, settings, identity)
    invalid: [0xFFFF]             # raw values meaning "not available" (a float reading NaN always is)
    optional: true                # may not be fitted (e.g. a sensor); then the device may not answer at all
                                  # (timeout): read it in a request of its own; no answer = value missing
    verified: false               # true when checked on a real device
    note: "…"
    word_order: little            # this point's word order, where it differs from the device's `encoding`
    byte_order: little            # likewise for the byte order within each register (e.g. text stored low byte first)
    bits: [4, 7]                  # only bits 4…7 of the raw value (shifted down), for bitfields
    signed: true                  # the bit field is a two's-complement number (e.g. a signed byte)
    writable: true                # the device accepts writes here (see "Writing")
    write_only: true              # written, but reads give nothing useful (commands, some setpoints): don't read it
    write_address: 49998          # written at this address instead of `address` (same table rules)
    write_multiple: true          # this register only takes function 16 / 15 (as connection.write_multiple)
    write_single: true            # this value is written one register at a time with 06 (as connection.write_single)
    min: 6                        # the lowest and highest value the device accepts, in the point's unit
    max: 32
    persistent: true              # stored in non-volatile memory: survives a restart, but each write wears it,
                                  # so don't write it in a control loop (false: volatile, may be written often)
    sources: [goodwe, solax-modbus]   # source ids this point was taken from (default: the documents)
    conflicts:                    # what other sources say where they disagree with this point
      - {sources: [huawei-solar], scale: 0.01}
```

Where projects disagree, the point holds what most sources say (documents and verified values always win) and
`conflicts` lists each different reading with the sources behind it. A conflict may give any of `key`, `label`,
`type`, `length`, `unit`, `scale`, `offset`, `scale_exponent_from`, `word_order`, `byte_order`, `positive`, `bits`, `models`.

Two points may share a register only when both have `bits` and the bits don't overlap, or when one has `bits` and
the other is the whole value (same address and size).

### Types

| Type | Registers | Value |
|---|---|---|
| `u16` `s16` `u32` `s32` `u64` `s64` | 1, 2, 4 | unsigned / two's complement integers |
| `f16` `f32` `f64` | 1, 2, 4 | IEEE 754 floats (half, single, double precision) |
| `sm16` `sm32` | 1, 2 | sign and magnitude: the top bit is the sign, the rest the amount |
| `bcd16` `bcd32` `bcd64` | 1, 2, 4 | binary-coded decimal, four bits per digit (0x1234 = 1234); a digit above 9 = no value |
| `str` | `length` | text; `chars: low` or `chars: high` for one character per register in that byte. A text longer than `max_registers` is read in several requests of at most `max_registers` |
| `datetime` | `length` | date and time over several registers, laid out by `datetime` (below) |
| `bool` | 1 bit | coils and discrete inputs only |

```yaml
  - key: x.clock
    type: datetime
    length: 3
    datetime:                     # each part: register (0 = the point's first), optional bits, offset, bcd
      year: {register: 0, bits: [8, 15], offset: 2000}
      month: {register: 0, bits: [0, 7]}
      day: {register: 1, bits: [8, 15]}
      hour: {register: 1, bits: [0, 7]}
      minute: {register: 2, bits: [8, 15], bcd: true}
```

A part may also be packed decimally: `div` and `mod` take (value ÷ div) mod mod, e.g. a register holding hours × 100
+ minutes is `hour: {register: 0, div: 100}, minute: {register: 0, mod: 100}`. A reader gives a `datetime` as ISO
8601 text with the parts the layout has (`2026-10-24T14:42`, `23:59`).

A counter of time since a start (Unix time, days since 2000-01-01 …) stays a numeric point with
`epoch: {start: "1970-01-01", unit: s}` (unit `s`, `min`, `h` or `d`); a reader gives it as ISO 8601 text.

## `defaults`

```yaml
defaults: {verified: false, sources: [nibe]}
```

Values every point (and derived value) has unless it says otherwise, to keep large files short. A point with
`verified: null` or `sources: []` says "not set" — a fact from the documents in a file whose points mostly come
from a project. Readers apply the defaults first (`msp.load` does); after that a file means exactly the same as if
every point spelled them out.

## `derived`

Values a device spreads over several registers: a sum of other points (or earlier derived values), each times a
factor, after their own scaling and sign handling.

```yaml
derived:
  - key: grid_power
    label: Grid power
    unit: W
    positive: import              # direction of the sum, as for points
    sum: [{key: x.import_power}, {key: x.export_power, factor: -1}]
  - key: grid_import_energy
    label: Imported energy
    unit: kWh
    sum: [{key: x.import_mwh}, {key: x.import_kwh}]   # the MWh part has scale 1000
```

A derived value is missing when one of its terms is, unless that term has `optional: true` (e.g. MPPT inputs a
smaller model doesn't have): then it counts as 0, as long as at least one term is there.

Instead of `sum`, `first` takes the first term that is present, times its factor: for a register older firmware
lacks and the one to use instead.

```yaml
  - key: grid_power
    label: Grid power
    unit: W
    positive: import
    first: [{key: x.meter_power}, {key: x.export_power, factor: -1}]
```

`models`, `note`, `verified` and `sources` work as for points. Values that need more than this aren't described
here.

## `sunspec`

`sunspec: true` marks a device whose registers here are SunSpec models ("SunS", then a chain of models), at the
addresses its usual chain gives them. A SunSpec device may lay the chain out differently (another base address,
other models before the one read), and the addresses here then don't fit. Walking the chain from "SunS" is SunSpec's
own business and not described here: a reader that has a SunSpec library should read such a device with it, and
use this file for what SunSpec doesn't say (identification, vendor registers, signs, notes).

## `models` and `identify`

```yaml
models:
  - id: sdm120
    name: SDM120
    match: {table: holding, address: 0xFC02, type: u16, equals: 0x0020}
  - id: sdm630
    name: SDM630
    match: {table: holding, address: 0x000A, type: f32, in: [1, 2, 3]}
identify:
  serial: {table: holding, address: 0xFC00, type: u32}
  checks:
    - {table: input, address: 0x0046, type: f32, range: [40, 70]}
```

Models are tried in order; the first `match` wins. A `match` may be a list of conditions that must all hold (a
list inside it: one of them must hold, e.g. a plausible value or "not connected"); `match_any` is a list of which at
least one must hold (as well as `match`, if there is one). With `model_choice: user` readers don't detect the model
(the `match` entries, if any, are hints): the user picks it, and until then only points without `models` are read.

`identify` tells a search of the network whether a device is this one. All `identify.checks` must hold (a list
among them: one of its conditions); of `identify.any`, at least one (e.g. one per model family; a list among them:
all of its conditions, as in a `match`). Where the serial number sits in a different register per model,
`identify.serial` is a list of registers, each with `models`. A file without `identify` but whose models all have a
`match` gets `identify.any` from those matches.

## `problems`

```yaml
problems:
  - when: {key: state, equals: 4}
    kind: fault                   # fault, warning, mains_lost, backup_mode
    text: "Charging station error (state 4)"
  - when: {key: error_code, not: 0}
    kind: fault
    text: "Charging station error (code 0x{value:X})"
  - when: {key: x.alarm_word, bit: 3}
    kind: warning
    text: "Fan fault (bit 3)"
  - when: {key: state, range: [200, 299]}
    kind: fault
    text: "Power stage error {value}"
  - when: {key: x.mode3_state, prefix: "F"}   # text points: equals, not, in, prefix
    kind: fault
    text: "Vehicle error ({value})"
```

`kind`: `fault` = the device stopped or can't work normally; `warning` = works but
something to check; `mains_lost` = the device reports the grid / AC input missing; `backup_mode` = the device runs
off-grid / backup / island. `{value}` and `{value:X}` insert the value (decimal / hex), `{text}` its name from
the point's enum. `when` takes `equals`, `not`, `in`, `not_in`, `range`, `prefix` and `bit`; every rule that
holds reports a problem, so rules for one value should not overlap.

Model `match` and `identify` conditions take `equals`, `in`, `not`, `not_in`, `range`, `prefix`, `contains` (a
list: the text contains one of them, e.g. model tags in a serial number), `printable: true` (a text that is all
printable ASCII characters, 20h–7Eh, and not empty, e.g. a device name only one family has; registers filled
with FFFFh don't count) and `answers: true` / `false` (the register answers
a read at all, or doesn't: e.g. registers only one model has). A reader reads a register with `answers` in a
request of its own.

## `reserved`

```yaml
reserved:
  - {table: holding, address: 120, count: 2}      # 120 and 121
  - {table: holding, address: 129, bits: [1, 1]}  # one bit of a status word
```

What the manufacturer's document marks reserved or unused. No point may read it (a whole-register point on a
register with reserved bits is fine; a bit field on those bits is not); `models` limits an entry to some models. The
merge leaves out what a project reads there and says so in the notes: the document wins.

## Writing

A point with `writable: true` may be written; everything else is read only. A writer works out the raw value as the
exact inverse of reading:

- an enum point takes the enum's number, or its name (the names in `enums`); any other number is refused;
- `positive`: a vocabulary key is written in the vocabulary's direction and negated where the point's `positive`
  is the opposite, as when reading;
- raw = (value − `offset`) ÷ `scale` (÷ 10^exponent with `scale_exponent_from`, whose register is read first),
  then rounded for an integer type; a value that isn't a whole step of the scale is refused;
- `min` and `max` (in the point's unit) are checked before writing; a raw value in the point's `invalid` list
  (e.g. "no setpoint request") may be written regardless;
- `bits`: the register is read, only those bits are changed, and the whole register is written back (not atomic:
  don't let two writers change bits of one register at once); with `write_only` the register can't be read, so the
  other bits are written as 0 (a command word whose bits are commands);
- `datetime` takes ISO 8601 text with every part the layout has; `str` is padded with zero bytes to `length`;
- word order, byte order and `chars` as for reading; `unit_id` as for reading.

Registers are written as holding registers with function 06 (one register) or 16 (several, or with
`write_multiple`; with `write_single` one 06 per register instead), coils with 05 (or 15 with `write_multiple`). A point read from the `input` table is written to
the holding register at the same address (devices that read a setting with function 04 and set it with 06, e.g.
KSTAR, iDM, or with `input_equals_holding`), or at `write_address`. Discrete inputs can't be written. After a
write, a writer should read the value back (unless `write_only`) and treat a Modbus exception as "refused".

What a written value means and when to write it — a password to unlock settings first, a command that has to be
written again within a time (a heartbeat), a mode that has to be set before a setpoint takes effect — is in the
point's `note` and the file's `notes`.

## Not in version 0

SunSpec chain discovery (see `sunspec` above), non-Modbus protocols, values that need more than a weighted sum of
points or the first present one (e.g. a quotient, or a register chosen by another's value), and writes that need
more than one value written (sequences, unlocking): those are notes. They may come in a later version.
