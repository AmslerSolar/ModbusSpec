#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Amsler Solar GmbH
"""ModbusSpec reference tool: validate device files, and read or write a device with one.

    python3 tools/msp.py validate [files…]          # all of devices/ by default
    python3 tools/msp.py read devices/charger/keba/kecontact-p30.yaml --host 192.168.1.40 [--unit 255] [--port 502]
    python3 tools/msp.py write devices/charger/keba/kecontact-p30.yaml x.set_charging_current 16 --host 192.168.1.40

Reading and writing need nothing but Python: it speaks Modbus TCP, Modbus/TCP Security (TLS), Modbus over UDP and
RTU frames over TCP or UDP itself (functions 01–06, 15, 16); --transport picks one.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import re
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SIZES = {"bool": 1, "sm16": 1, "bcd16": 1, "sm32": 2, "bcd32": 2, "bcd64": 4, "u16": 1, "s16": 1, "u32": 2, "s32": 2, "u64": 4, "s64": 4, "f16": 1, "f32": 2, "f64": 4}
FUNCTION = {"coil": 1, "discrete": 2, "holding": 3, "input": 4}
BIT_TABLES = {"coil", "discrete"}
# The direction of a device's main power, for keys whose vocabulary direction is "main" (per-phase power).
MAIN_DIRECTION = {"meter": "export", "inverter": "export", "battery": "discharge", "charger": "consumption",
                  "heat_pump": "consumption", "heating_rod": "consumption", "boiler": "consumption",
                  "ventilation": "consumption", "hvac": "consumption", "pool": "consumption", "ups": "consumption",
                  "io": "consumption", "energy_manager": "export", "other": "consumption"}
# Directions that are opposite to each other: a point with the opposite of the key's direction is negated.
OPPOSITE = {"export": "import", "import": "export", "discharge": "charge", "charge": "discharge",
            "consumption": "generation", "generation": "consumption"}


def load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return expand(yaml.safe_load(f))


def expand(spec: dict) -> dict:
    """The device with its `defaults` applied to every point and derived value: a point that doesn't give
    `verified` or `sources` takes the file's default; `verified: null` and `sources: []` mean "not set" (a fact
    from the documents). Idempotent."""
    if "defaults" not in spec:
        return spec
    defaults = spec["defaults"]
    out = {k: v for k, v in spec.items() if k != "defaults"}
    for part in ("points", "derived"):
        if part in spec:
            items = []
            for p in spec[part]:
                q = {**defaults, **p}
                if q.get("verified") is None:
                    q.pop("verified", None)
                if q.get("sources") == []:
                    q.pop("sources", None)
                items.append(q)
            out[part] = items
    return out


def vocabulary() -> dict:
    return load(ROOT / "vocabulary.yaml")["keys"]


def direction(key_entry: dict, spec: dict) -> str | None:
    """The vocabulary direction of a key for this device ("main" resolved by the device kind)."""
    d = key_entry.get("positive")
    return MAIN_DIRECTION[spec["kind"]] if d == "main" else d


def registers(p: dict) -> int:
    return p.get("length", 1) if p["type"] in ("str", "datetime") else SIZES[p["type"]]


def table_key(p: dict) -> str:
    """The register table, qualified by the point's own unit id where it has one ("holding@50")."""
    return f"{p['table']}@{p['unit_id']}" if "unit_id" in p else p["table"]


# ---------------------------------------------------------------- validation

def bits_apart(a: dict, b: dict) -> bool:
    """Points on the same register that may coexist: bitfields whose bits don't overlap, or a bitfield and the
    whole value it is part of."""
    if (a["address"], registers(a)) != (b["address"], registers(b)) or ("bits" not in a and "bits" not in b):
        return False
    if "bits" not in a or "bits" not in b:
        return True
    return a["bits"][1] < b["bits"][0] or b["bits"][1] < a["bits"][0]


def on_reserved(p: dict, r: dict) -> bool:
    """Whether a point reads a register (or bits) the device marks reserved."""
    if p["table"] != r["table"] or "unit_id" in p:
        return False
    if r.get("models") and p.get("models") and not set(r["models"]) & set(p["models"]):
        return False
    lo, n = r["address"], r.get("count", 1)
    if not (p["address"] < lo + n and lo < p["address"] + registers(p)):
        return False
    if "bits" in r:  # reserved bits of a register: only a point on those bits reads them as a value
        return "bits" in p and not (p["bits"][1] < r["bits"][0] or r["bits"][1] < p["bits"][0])
    return True


def validate(spec: dict, name: str = "") -> list[str]:
    """Schema check plus the rules a schema can't express. Returns the problems found (empty = valid)."""
    import jsonschema

    schema = json.loads((ROOT / "schema" / "device.schema.json").read_text(encoding="utf-8"))
    errors = [f"{name}: {'/'.join(map(str, e.path)) or '(top)'}: {e.message}"
              for e in jsonschema.Draft202012Validator(schema).iter_errors(spec)]
    if errors:
        return errors
    spec = expand(spec)
    vocab = vocabulary()
    models = {m["id"] for m in spec.get("models", [])}
    enums = spec.get("enums", {})
    limits = spec["connection"].get("limits", {})
    conn = spec["connection"]
    seen: dict[tuple, dict] = {}
    source_ids = {s["id"] for s in spec["sources"] if "id" in s}
    keys_per_model: dict[str, set] = {}
    for i, p in enumerate(spec["points"]):
        where = f"{name}: points[{i}] {p['key']}"
        key = p["key"]
        if not key.startswith("x."):
            if key not in vocab:
                errors.append(f"{where}: not a vocabulary key (use x.{key} for a device-specific value)")
            else:
                v = vocab[key]
                if p.get("unit", v["unit"]) != v["unit"]:
                    errors.append(f"{where}: unit {p.get('unit')!r} but the vocabulary says {v['unit']!r}")
                want = direction(v, spec)
                if want and "positive" not in p:
                    errors.append(f"{where}: needs `positive` ({want} or {OPPOSITE[want]})")
                if "positive" in p and p["positive"] not in (want, OPPOSITE.get(want)):
                    errors.append(f"{where}: positive {p['positive']!r} doesn't fit this key")
        if p["type"] in ("str", "datetime") and "length" not in p:
            errors.append(f"{where}: {p['type']} needs `length`")
        if (p["type"] == "datetime") != ("datetime" in p):
            errors.append(f"{where}: type datetime and the `datetime` layout go together")
        for part, d in p.get("datetime", {}).items():
            if d["register"] >= p.get("length", 1):
                errors.append(f"{where}: datetime {part} register {d['register']} outside the value")
        if p.get("signed") and "bits" not in p:
            errors.append(f"{where}: `signed` only applies to a bit field (`bits`)")
        if "epoch" in p and p["type"] in ("str", "datetime", "bool"):
            errors.append(f"{where}: `epoch` needs a numeric type")
        if "chars" in p and p["type"] != "str":
            errors.append(f"{where}: `chars` only applies to str")
        for c in [p, *p.get("conflicts", [])]:
            unknown_sources = set(c.get("sources", [])) - source_ids
            if unknown_sources:
                errors.append(f"{where}: unknown sources {sorted(unknown_sources)}")
        if (p["table"] in BIT_TABLES) != (p["type"] == "bool"):
            errors.append(f"{where}: type bool goes with the coil and discrete tables, and only there")
        if "bits" in p and not (0 <= p["bits"][0] <= p["bits"][1] < 16 * registers(p)):
            errors.append(f"{where}: bits {p['bits']} outside the value")
        if p.get("writable") and p["table"] == "discrete":
            errors.append(f"{where}: discrete inputs can't be written")
        lacking = [k for k in ("write_only", "write_address", "write_multiple", "write_single", "min", "max",
                               "persistent") if k in p and not p.get("writable")]
        if p.get("write_multiple", conn.get("write_multiple")) and p.get("write_single", conn.get("write_single")):
            errors.append(f"{where}: write_multiple and write_single exclude each other")
        if lacking:
            errors.append(f"{where}: {', '.join(lacking)} needs writable")
        if p.get("min", float("-inf")) > p.get("max", float("inf")):
            errors.append(f"{where}: min above max")
        if p.get("enum") and p["enum"] not in enums:
            errors.append(f"{where}: unknown enum {p['enum']!r}")
        if p.get("flags") and p["flags"] not in spec.get("flags", {}):
            errors.append(f"{where}: unknown flags {p['flags']!r}")
        unknown = set(p.get("models", [])) - models
        if unknown:
            errors.append(f"{where}: unknown models {sorted(unknown)}")
        n = registers(p)
        if n > limits.get("max_registers", 125) and p["type"] != "str":  # a text may take several requests
            errors.append(f"{where}: {n} registers but max_registers is {limits.get('max_registers', 125)}")
        if limits.get("even_address") and p["address"] % 2 and p["table"] not in BIT_TABLES:
            errors.append(f"{where}: odd address but the device needs even addresses")
        for m in p.get("models") or sorted(models) or ["*"]:
            if key in keys_per_model.setdefault(m, set()):
                errors.append(f"{where}: key used twice for model {m}")
            keys_per_model[m].add(key)
            for a in range(p["address"], p["address"] + n):
                other = seen.get((m, table_key(p), a))
                if other and other["key"] != key and not bits_apart(p, other):
                    errors.append(f"{where}: register {table_key(p)} {a} overlaps {other['key']} (model {m})")
                seen[(m, table_key(p), a)] = p
    for i, p in enumerate(spec["points"]):
        for r in spec.get("reserved", []):
            if on_reserved(p, r):
                errors.append(f"{name}: points[{i}] {p['key']}: on a register the device marks reserved")
    for i, r in enumerate(spec.get("reserved", [])):
        if set(r.get("models", [])) - models:
            errors.append(f"{name}: reserved[{i}]: unknown models {sorted(set(r['models']) - models)}")
    serials = spec.get("identify", {}).get("serial")
    for r in serials if isinstance(serials, list) else []:
        if set(r.get("models", [])) - models:
            errors.append(f"{name}: identify.serial: unknown models {sorted(set(r['models']) - models)}")
    point_keys = {p["key"] for p in spec["points"]}
    for i, d in enumerate(spec.get("derived", [])):
        where = f"{name}: derived[{i}] {d['key']}"
        if d["key"] in point_keys:
            errors.append(f"{where}: key already used by a point")
        for t in d.get("sum", d.get("first", [])):
            if t["key"] not in point_keys:
                errors.append(f"{where}: no point or earlier derived value {t['key']!r}")
        if not d["key"].startswith("x."):
            if d["key"] not in vocab:
                errors.append(f"{where}: not a vocabulary key")
            else:
                v = vocab[d["key"]]
                if d.get("unit", v["unit"]) != v["unit"]:
                    errors.append(f"{where}: unit {d.get('unit')!r} but the vocabulary says {v['unit']!r}")
                want = direction(v, spec)
                if want and d.get("positive") not in (want, OPPOSITE[want]):
                    errors.append(f"{where}: needs `positive` ({want} or {OPPOSITE[want]})")
        unknown = set(d.get("models", [])) - models
        if unknown:
            errors.append(f"{where}: unknown models {sorted(unknown)}")
        point_keys.add(d["key"])
    for i, pr in enumerate(spec.get("problems", [])):
        if pr["when"]["key"] not in point_keys:
            errors.append(f"{name}: problems[{i}]: no point with key {pr['when']['key']!r}")
    enc = spec.get("encoding", {})
    if "detect" in (enc.get("word_order"), enc.get("byte_order")) and "detect" not in enc:
        errors.append(f"{name}: word_order or byte_order detect needs encoding.detect")
    if "detect" in enc and not {"plausible", "equals", "in", "range", "word_orders"} & set(enc["detect"]):
        errors.append(f"{name}: encoding.detect needs plausible, equals, in, range or word_orders")
    if "word_orders" in enc.get("detect", {}) and enc.get("word_order") != "detect":
        errors.append(f"{name}: encoding.detect.word_orders needs word_order detect")
    for i, b in enumerate(spec["connection"].get("blocks", [])):
        if b["count"] > limits.get("max_registers", 125):
            errors.append(f"{name}: connection.blocks[{i}]: {b['count']} registers but max_registers is "
                          f"{limits.get('max_registers', 125)}")
    ident = spec.get("identify", {})
    for c in conditions([ident.get("checks", []), ident.get("any", [])]):
        if c.get("type") == "u32" and c.get("equals") == 0x53756E53 and \
                c.get("word_order", enc.get("word_order", "big")) != "big":
            errors.append(f"{name}: identify: the SunSpec marker 'SunS' at {c['address']} is big-endian whatever the "
                          "device's word order; give it word_order: big")
    transports = spec["connection"].get("transports", ["tcp"])
    for t in set(spec["connection"].get("ports", {})) - set(transports):
        errors.append(f"{name}: connection.ports.{t}: not in connection.transports")
    if "tls" in spec["connection"] and "tls" not in transports:
        errors.append(f"{name}: connection.tls needs the tls transport")
    if "reply_prefix" in spec["connection"] and not {"rtu_over_tcp", "rtu_over_udp"} & set(transports):
        errors.append(f"{name}: connection.reply_prefix needs an rtu_over_tcp or rtu_over_udp transport")
    if spec.get("model_choice") == "user" and not models:
        errors.append(f"{name}: model_choice user needs models")
    return errors


# ---------------------------------------------------------------- decoding

def decode(words: list[int], type_: str, word_order: str = "big", byte_order: str = "big",
           chars: str = "both") -> int | float | str | None:
    """Registers (16-bit) to a value; None for a BCD digit above 9."""
    if byte_order == "little":
        words = [(w >> 8) | ((w & 0xFF) << 8) for w in words]
    if type_ == "bool":
        return words[0]
    if type_ == "str":
        if chars == "both":
            raw = b"".join(struct.pack(">H", w) for w in words)
        else:  # one character per register, in its high or low byte
            raw = bytes((w >> 8) if chars == "high" else (w & 0xFF) for w in words)
        return raw.split(b"\0")[0].decode("latin-1").strip()
    ws = list(words) if word_order == "big" else list(reversed(words))
    if type_ in ("sm16", "sm32", "bcd16", "bcd32", "bcd64"):
        n = 0
        for w in ws:
            n = (n << 16) | w
        bits = 16 * len(ws)
        if type_.startswith("sm"):  # sign and magnitude: the top bit is the sign
            mag = n & ((1 << (bits - 1)) - 1)
            return -mag if n >> (bits - 1) else mag
        digits = [(n >> (4 * i)) & 0xF for i in range(bits // 4)][::-1]
        return None if any(d > 9 for d in digits) else int("".join(map(str, digits)))
    raw = b"".join(struct.pack(">H", w) for w in ws)
    fmt = {"u16": ">H", "s16": ">h", "u32": ">I", "s32": ">i", "u64": ">Q", "s64": ">q", "f16": ">e", "f32": ">f", "f64": ">d"}[type_]
    return struct.unpack(fmt, raw)[0]


def encode(value, type_: str, word_order: str = "big", byte_order: str = "big", chars: str = "both",
           length: int = 1) -> list[int]:
    """A value to registers (16-bit): the inverse of `decode`. Raises ValueError for a value the type can't hold."""
    if type_ == "bool":
        words = [1 if value else 0]
    elif type_ == "str":
        raw = str(value).encode("latin-1")
        room = 2 * length if chars == "both" else length
        if len(raw) > room:
            raise ValueError(f"text longer than {room} characters")
        raw = raw.ljust(room, b"\0")
        if chars == "both":
            words = list(struct.unpack(f">{length}H", raw))
        else:
            words = [b << 8 if chars == "high" else b for b in raw]
    else:
        n = SIZES[type_]
        bits = 16 * n
        if type_.startswith(("sm", "bcd")):
            v = int(value)
            if type_.startswith("sm"):
                if abs(v) >= 1 << (bits - 1):
                    raise ValueError(f"{value} out of range for {type_}")
                num = abs(v) | ((1 << (bits - 1)) if v < 0 else 0)
            else:
                if v < 0 or len(str(v)) > bits // 4:
                    raise ValueError(f"{value} out of range for {type_}")
                num = int(str(v), 16)
            words = [(num >> (16 * (n - 1 - i))) & 0xFFFF for i in range(n)]
        else:
            fmt = {"u16": ">H", "s16": ">h", "u32": ">I", "s32": ">i", "u64": ">Q", "s64": ">q", "f16": ">e",
                   "f32": ">f", "f64": ">d"}[type_]
            try:
                raw = struct.pack(fmt, float(value) if type_.startswith("f") else int(value))
            except (struct.error, OverflowError):
                raise ValueError(f"{value} out of range for {type_}") from None
            words = list(struct.unpack(f">{n}H", raw))
        if word_order == "little":
            words.reverse()
    if byte_order == "little":
        words = [(w >> 8) | ((w & 0xFF) << 8) for w in words]
    return words


def datetime_words(text: str, layout: dict, current: list[int]) -> list[int]:
    """ISO 8601 text to the registers of a `datetime` layout: the inverse of `datetime_of`. Bits the layout doesn't
    cover keep their value from `current`."""
    m = re.fullmatch(r"(?:(\d{4})-(\d{2})-(\d{2}))?T?(?:(\d{2}):(\d{2})(?::(\d{2}))?)?", text.strip())
    if not m or not any(m.groups()):
        raise ValueError(f"not an ISO 8601 date or time: {text!r}")
    given = {k: int(v) for k, v in zip(("year", "month", "day", "hour", "minute", "second"), m.groups()) if v}
    missing = set(layout) - set(given)
    if missing:
        raise ValueError(f"the device needs {', '.join(sorted(missing))}")
    words, packed = list(current), {}
    for name, d in layout.items():
        v = given[name] - d.get("offset", 0)
        if d.get("bcd"):
            v = int(str(v), 16)
        r = d["register"]
        if "div" in d or "mod" in d:  # decimal packing: the parts of a register add up
            packed[r] = packed.get(r, 0) + v * d.get("div", 1)
        elif "bits" in d:
            lo, hi = d["bits"]
            mask = ((1 << (hi - lo + 1)) - 1) << lo
            words[r] = (words[r] & ~mask) | ((v << lo) & mask)
        else:
            words[r] = v & 0xFFFF
    for r, v in packed.items():
        words[r] = v & 0xFFFF
    return words


@dataclass
class Image:
    """Register values read so far, per table."""
    regs: dict[str, dict[int, int]] = field(default_factory=dict)

    def words(self, table: str, address: int, n: int) -> list[int] | None:
        t = self.regs.get(table, {})
        out = [t.get(a) for a in range(address, address + n)]
        return None if any(w is None for w in out) else out  # type: ignore[return-value]


def value_of(img: Image, reg: dict, word_order: str, byte_order: str = "big"):
    w = img.words(table_key(reg), reg["address"], registers(reg))
    if w is None:
        return None
    if reg["type"] == "datetime":
        return datetime_of(w, reg["datetime"])
    return decode(w, reg["type"], reg.get("word_order", word_order), reg.get("byte_order", byte_order),
                  reg.get("chars", "both"))


def datetime_of(words: list[int], layout: dict) -> str | None:
    """A date and time spread over registers: each part from a register (or some of its bits, or BCD), plus an
    offset; written as ISO 8601, with the parts the layout has."""
    parts = {}
    for name, d in layout.items():
        v = words[d["register"]]
        if "bits" in d:
            v = (v >> d["bits"][0]) & ((1 << (d["bits"][1] - d["bits"][0] + 1)) - 1)
        if "div" in d or "mod" in d:  # decimal packing, e.g. hours × 100 + minutes
            v = v // d.get("div", 1) % d.get("mod", 1 << 32)
        if d.get("bcd"):
            v = int(f"{v:x}") if all(c in "0123456789" for c in f"{v:x}") else None
            if v is None:
                return None
        parts[name] = v + d.get("offset", 0)
    date = "-".join(f"{parts[k]:0{4 if k == 'year' else 2}d}" for k in ("year", "month", "day") if k in parts)
    time_ = ":".join(f"{parts[k]:02d}" for k in ("hour", "minute", "second") if k in parts)
    return "T".join(x for x in (date, time_) if x)


def condition_holds(img: Image, c: dict | list, word_order: str, byte_order: str = "big") -> bool:
    """A condition on one register; a list of conditions holds when all hold, a list inside it when one does."""
    if isinstance(c, list):
        return all(any(condition_holds(img, y, word_order, byte_order) for y in x) if isinstance(x, list)
                   else condition_holds(img, x, word_order, byte_order) for x in c)
    v = value_of(img, c, word_order, byte_order)
    if "answers" in c and (v is not None) != c["answers"]:
        return False
    if v is None:
        return c.get("answers") is False
    if "equals" in c and v != c["equals"]:
        return False
    if "in" in c and v not in c["in"]:
        return False
    if "not" in c and v == c["not"]:
        return False
    if "not_in" in c and v in c["not_in"]:
        return False
    if "range" in c and not (c["range"][0] <= v <= c["range"][1]):
        return False
    if "prefix" in c and not str(v).startswith(c["prefix"]):
        return False
    if "contains" in c and not any(t in str(v) for t in c["contains"]):
        return False
    if c.get("printable") and not (isinstance(v, str) and v and v.isascii() and v.isprintable()):
        return False
    return True


def detect_orders(spec: dict, img: Image) -> tuple[str, str]:
    """(word order, byte order): the fixed ones, or the first combination in which the detect register reads as
    stated (big before little; word order varies first)."""
    enc = spec.get("encoding", {})
    word, byte = enc.get("word_order", "big"), enc.get("byte_order", "big")
    if "detect" not in (word, byte):
        return word, byte
    d = dict(enc["detect"])
    if "word_orders" in d:  # the device states its word order in a register
        v = value_of(img, d, "big", "big" if byte == "detect" else byte)
        word = d["word_orders"].get(str(v), "big") if v is not None else "big"
        return word, ("big" if byte == "detect" else byte)
    if "plausible" in d:
        d["range"] = d.pop("plausible")
    for b in ("big", "little") if byte == "detect" else (byte,):
        for w in ("big", "little") if word == "detect" else (word,):
            if condition_holds(img, d, w, b):
                return w, b
    return ("big" if word == "detect" else word), ("big" if byte == "detect" else byte)


def detect_word_order(spec: dict, img: Image) -> str:
    return detect_orders(spec, img)[0]


def conditions(c: dict | list) -> list[dict]:
    """The single conditions in a condition or (nested) list of them."""
    return [y for x in c for y in conditions(x)] if isinstance(c, list) else [c]


def identifies(spec: dict, img: Image, word_order: str, byte_order: str = "big") -> bool:
    """Whether the registers read fit the file's `identify` checks (all checks, and one of `any`)."""
    ident = spec.get("identify", {})
    return condition_holds(img, ident.get("checks", []), word_order, byte_order) and \
        ("any" not in ident or any(condition_holds(img, c, word_order, byte_order) for c in ident["any"]))


def has_identify(spec: dict) -> bool:
    """Whether the file can recognise its device (identify checks or any), e.g. for a search of the network."""
    return bool(spec.get("identify", {}).get("checks") or spec.get("identify", {}).get("any"))


def detect_model(spec: dict, img: Image, word_order: str, byte_order: str = "big") -> str | None:
    if spec.get("model_choice") == "user":  # the models can't be told apart from the device: the user picks one
        return None
    for m in spec.get("models", []):
        if ("match" not in m or condition_holds(img, m["match"], word_order, byte_order)) and \
                ("match_any" not in m or any(condition_holds(img, c, word_order, byte_order) for c in m["match_any"])):
            return m["id"]
    return None


def points_for(spec: dict, model: str | None) -> list[dict]:
    if model is None and spec.get("model_choice") == "user":  # no model chosen: only what every model has
        return [p for p in spec["points"] if "models" not in p]
    return [p for p in spec["points"] if model is None or "models" not in p or model in p["models"]]


def values(spec: dict, img: Image, model: str | None, word_order: str, byte_order: str | None = None) -> dict:
    """Decoded, scaled and sign-normalised values by key (vocabulary conventions)."""
    vocab = vocabulary()
    out: dict = {}
    for p in points_for(spec, model):
        if byte_order is None:
            byte_order = spec.get("encoding", {}).get("byte_order", "big")
            byte_order = "big" if byte_order == "detect" else byte_order
        raw = value_of(img, p, word_order, byte_order)
        if raw is None or (isinstance(raw, (int, float)) and raw in p.get("invalid", [])):
            continue
        if isinstance(raw, float) and math.isnan(raw):  # a float that reads NaN is never a value
            continue
        v = raw
        if "bits" in p and isinstance(v, int):
            lo, hi = p["bits"]
            v = (v >> lo) & ((1 << (hi - lo + 1)) - 1)
            if p.get("signed") and v >> (hi - lo):  # two's complement within the field
                v -= 1 << (hi - lo + 1)
        if isinstance(v, (int, float)) and p["type"] != "str":
            exp = p.get("scale_exponent_from")
            if exp is not None:
                e = value_of(img, exp, word_order, byte_order)
                if e is None:
                    continue
                if "bits" in exp:  # the exponent is a bit field of its register (e.g. a signed low byte)
                    lo, hi = exp["bits"]
                    e = (int(e) >> lo) & ((1 << (hi - lo + 1)) - 1)
                    if exp.get("signed") and e >> (hi - lo):
                        e -= 1 << (hi - lo + 1)
                v = v * 10 ** (-e if exp.get("negate") else e)
            v = v * p.get("scale", 1) + p.get("offset", 0)
            want = direction(vocab.get(p["key"], {}), spec)
            if want and p.get("positive") == OPPOSITE[want]:
                v = -v
            if isinstance(v, float):
                v = round(v, 6)
        if "epoch" in p and isinstance(v, (int, float)):
            start = datetime.datetime.fromisoformat(p["epoch"]["start"])
            unit = {"s": "seconds", "min": "minutes", "h": "hours", "d": "days"}[p["epoch"]["unit"]]
            v = (start + datetime.timedelta(**{unit: v})).isoformat()
        if p.get("flags") and isinstance(v, int):
            table = spec["flags"][p["flags"]]
            out[p["key"] + ".flags"] = [table.get(str(b), f"Bit {b}") for b in range(64) if v >> b & 1]
        if p.get("enum"):
            out[p["key"] + ".text"] = spec["enums"][p["enum"]].get(str(int(v)), f"Unknown ({v})")
        out[p["key"]] = v
    for d in spec.get("derived", []):
        if "models" in d and (model not in d["models"] if model is not None
                              else spec.get("model_choice") == "user"):
            continue
        if "first" in d:  # the first term present, e.g. a register older firmware lacks, then its fallback
            hit = next(((out[t["key"]], t) for t in d["first"] if isinstance(out.get(t["key"]), (int, float))), None)
            if hit is None:
                continue
            v = hit[0] * hit[1].get("factor", 1)
            want = direction(vocab.get(d["key"], {}), spec)
            if want and d.get("positive") == OPPOSITE[want]:
                v = -v
            out[d["key"]] = round(v, 6) if isinstance(v, float) else v
            continue
        terms = [out.get(t["key"]) for t in d["sum"]]
        present = [isinstance(t, (int, float)) for t in terms]
        if not any(present) or any(not ok and not f.get("optional") for ok, f in zip(present, d["sum"])):
            continue
        v = sum(t * f.get("factor", 1) for t, f, ok in zip(terms, d["sum"], present) if ok)
        want = direction(vocab.get(d["key"], {}), spec)
        if want and d.get("positive") == OPPOSITE[want]:
            v = -v
        out[d["key"]] = round(v, 6) if isinstance(v, float) else v
    return out


def problems(spec: dict, vals: dict) -> list[dict]:
    out = []
    for pr in spec.get("problems", []):
        w = pr["when"]
        v = vals.get(w["key"])
        if not isinstance(v, (int, float, str)):
            continue
        number = isinstance(v, (int, float))
        hit = (("equals" not in w or v == w["equals"]) and ("not" not in w or v != w["not"]) and
               ("in" not in w or v in w["in"]) and ("not_in" not in w or v not in w["not_in"]) and
               ("range" not in w or (number and w["range"][0] <= v <= w["range"][1])) and
               ("prefix" not in w or str(v).startswith(w["prefix"])) and
               ("bit" not in w or (number and (int(v) >> w["bit"]) & 1 == 1)))
        if hit:
            out.append({"kind": pr["kind"], "text": pr["text"].format(value=int(v) if number else v,
                                                                      text=vals.get(w["key"] + ".text", v))})
    return out


# ---------------------------------------------------------------- reading a device

def blocks(regs: list[tuple[str, int, int]], limits: dict) -> list[tuple[str, int, int]]:
    """Merge (table, address, count) into requests that respect max_registers, max_gap and even_address."""
    max_regs, gap, even = limits.get("max_registers", 125), limits.get("max_gap", 0), limits.get("even_address", False)
    out: list[list] = []
    # A value longer than one request (a long text) is read in parts of at most max_registers.
    regs = [(t, a + i, min(max_regs, n - i)) for t, a, n in regs for i in range(0, n, max_regs)]
    for table, a, n in sorted(set(regs)):
        if even and table.partition("@")[0] not in BIT_TABLES:
            if a % 2:
                a, n = a - 1, n + 1
            if n % 2:
                n += 1
        if out and out[-1][0] == table and a - (out[-1][1] + out[-1][2]) <= gap and \
                max(a + n, out[-1][1] + out[-1][2]) - out[-1][1] <= max_regs:
            out[-1][2] = max(a + n, out[-1][1] + out[-1][2]) - out[-1][1]
        else:
            out.append([table, a, n])
    return [tuple(b) for b in out]  # type: ignore[misc]


def crc16(data: bytes) -> int:
    """Modbus RTU CRC-16 (polynomial 0xA001, start 0xFFFF); sent low byte first."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def read_pdu(table: str, address: int, count: int) -> bytes:
    return struct.pack(">BHH", FUNCTION[table], address, count)


def write_pdu(table: str, address: int, values: list[int], multiple: bool = False) -> bytes:
    if table == "coil":
        if len(values) == 1 and not multiple:
            return struct.pack(">BHH", 5, address, 0xFF00 if values[0] else 0)
        packed = bytes(sum(1 << i for i, b in enumerate(values[j:j + 8]) if b) for j in range(0, len(values), 8))
        return struct.pack(">BHHB", 15, address, len(values), len(packed)) + packed
    if table == "holding":
        if len(values) == 1 and not multiple:
            return struct.pack(">BHH", 6, address, values[0])
        return struct.pack(f">BHHB{len(values)}H", 16, address, len(values), 2 * len(values), *values)
    raise ValueError(f"the {table} table can't be written")


def reply_length(pdu: bytes) -> int | None:
    """Length of a reply PDU from its first bytes (function, then byte count for reads); None if more is needed."""
    if len(pdu) < 2:
        return None
    if pdu[0] & 0x80:
        return 2
    if pdu[0] in (1, 2, 3, 4):
        return 2 + pdu[1]
    return 5  # 05, 06, 15, 16 echo address and value / count


class ModbusClient:
    """Reads holding and input registers (03, 04) and coils and discrete inputs (01, 02, one value per bit);
    writes coils (05, 15) and holding registers (06, 16). Subclasses frame the requests for one transport."""

    def __init__(self, unit: int, min_interval_ms: int = 0):
        self.unit, self.gap, self.last = unit, min_interval_ms / 1000, 0.0

    def read(self, table: str, address: int, count: int, unit: int | None = None) -> list[int]:
        body = self._request(read_pdu(table, address, count), self.unit if unit is None else unit)
        if body[0] & 0x80:
            raise IOError(f"Modbus exception {body[1]} at {table} {address}")
        if table in BIT_TABLES:
            return [body[2 + i // 8] >> (i % 8) & 1 for i in range(count)]
        return list(struct.unpack(f">{count}H", body[2:2 + 2 * count]))

    def write(self, table: str, address: int, values: list[int], unit: int | None = None,
              multiple: bool = False) -> None:
        """Write coils (05, or 15 with `multiple`) or holding registers (06 for one, 16 for several or with
        `multiple`)."""
        body = self._request(write_pdu(table, address, values, multiple), self.unit if unit is None else unit)
        if body[0] & 0x80:
            raise IOError(f"Modbus exception {body[1]} writing {table} {address}")

    def _request(self, pdu: bytes, unit: int) -> bytes:
        wait = self.last + self.gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return self._exchange(pdu, unit)
        finally:
            self.last = time.monotonic()

    def _exchange(self, pdu: bytes, unit: int) -> bytes:
        raise NotImplementedError


class ModbusTcp(ModbusClient):
    """Modbus TCP: MBAP header + PDU over a TCP connection."""

    def __init__(self, host: str, port: int, unit: int, timeout: float = 3.0, min_interval_ms: int = 0):
        super().__init__(unit, min_interval_ms)
        self.sock = socket.create_connection((host, port), timeout)
        self.tid = 0

    def _exchange(self, pdu: bytes, unit: int) -> bytes:
        self.tid = (self.tid + 1) & 0xFFFF
        self.sock.sendall(struct.pack(">HHHB", self.tid, 0, len(pdu) + 1, unit) + pdu)
        while True:  # skip a late reply to an earlier request that timed out
            tid, _, length, _ = struct.unpack(">HHHB", self._exact(7))
            body = self._exact(length - 1)
            if tid == self.tid:
                return body

    def _exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise IOError("connection closed")
            data += chunk
        return data


class ModbusTls(ModbusTcp):
    """Modbus/TCP Security (mbaps): the Modbus TCP frame inside TLS 1.2 or later. `cafile` verifies the device's
    certificate (devices are addressed by IP, so its name isn't checked); `certfile` / `keyfile` are the client
    certificate the device asks for. Without `cafile`, `insecure=True` is needed (the device isn't checked)."""

    def __init__(self, host: str, port: int, unit: int, timeout: float = 3.0, min_interval_ms: int = 0,
                 cafile: str | None = None, certfile: str | None = None, keyfile: str | None = None,
                 insecure: bool = False):
        import ssl
        ModbusClient.__init__(self, unit, min_interval_ms)
        if not cafile and not insecure:
            raise ValueError("TLS needs the device's CA (--cafile), or --insecure to skip checking the device")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False
        if insecure:
            ctx.verify_mode = ssl.CERT_NONE
        else:
            ctx.load_verify_locations(cafile)
        if certfile:
            ctx.load_cert_chain(certfile, keyfile)
        self.sock = ctx.wrap_socket(socket.create_connection((host, port), timeout))
        self.tid = 0


class ModbusUdp(ModbusClient):
    """Modbus over UDP: the Modbus TCP frame (MBAP header + PDU) in one datagram each way. A lost datagram is
    sent again after the timeout (`retries` times)."""

    def __init__(self, host: str, port: int, unit: int, timeout: float = 2.0, min_interval_ms: int = 0,
                 retries: int = 2):
        super().__init__(unit, min_interval_ms)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)
        self.sock.connect((host, port))
        self.tid, self.retries = 0, retries

    def _exchange(self, pdu: bytes, unit: int) -> bytes:
        self.tid = (self.tid + 1) & 0xFFFF
        frame = struct.pack(">HHHB", self.tid, 0, len(pdu) + 1, unit) + pdu
        for attempt in range(self.retries + 1):
            self.sock.send(frame)
            try:
                while True:  # skip stray datagrams (late replies to earlier requests)
                    data = self.sock.recv(1024)
                    if len(data) >= 8 and struct.unpack(">H", data[:2])[0] == self.tid:
                        return data[7:]
            except socket.timeout:
                if attempt == self.retries:
                    raise TimeoutError("no reply") from None
        raise TimeoutError("no reply")


class ModbusRtuOverTcp(ModbusClient):
    """Modbus RTU frames (unit, PDU, CRC-16) over a TCP connection, as transparent RS485 gateways pass them."""

    def __init__(self, host: str, port: int, unit: int, timeout: float = 3.0, min_interval_ms: int = 0,
                 reply_prefix: bytes = b""):
        super().__init__(unit, min_interval_ms)
        self.sock = socket.create_connection((host, port), timeout)
        self.prefix = reply_prefix

    def _exchange(self, pdu: bytes, unit: int) -> bytes:
        body = bytes([unit]) + pdu
        self.sock.sendall(body + struct.pack("<H", crc16(body)))
        data = b""
        while True:
            chunk = self.sock.recv(256)
            if not chunk:
                raise IOError("connection closed")
            data += chunk
            frame = data[len(self.prefix):]
            n = reply_length(frame[1:])
            if n is not None and len(frame) >= 1 + n + 2:
                return check_rtu(frame[:1 + n + 2], unit)


class ModbusRtuOverUdp(ModbusClient):
    """Modbus RTU frames (unit, PDU, CRC-16) in UDP datagrams. `reply_prefix`: bytes some devices put before the
    RTU frame of each reply (GoodWe: AA 55). A lost datagram is sent again after the timeout."""

    def __init__(self, host: str, port: int, unit: int, timeout: float = 2.0, min_interval_ms: int = 0,
                 retries: int = 2, reply_prefix: bytes = b""):
        super().__init__(unit, min_interval_ms)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)
        self.sock.connect((host, port))
        self.retries, self.prefix = retries, reply_prefix

    def _exchange(self, pdu: bytes, unit: int) -> bytes:
        body = bytes([unit]) + pdu
        frame = body + struct.pack("<H", crc16(body))
        for attempt in range(self.retries + 1):
            self.sock.send(frame)
            try:
                while True:
                    data = self.sock.recv(1024)
                    if data.startswith(self.prefix):
                        reply = data[len(self.prefix):]
                        if len(reply) >= 4 and reply[0] == unit and reply[1] & 0x7F == pdu[0]:
                            return check_rtu(reply, unit)
            except socket.timeout:
                if attempt == self.retries:
                    raise TimeoutError("no reply") from None
        raise TimeoutError("no reply")


def check_rtu(frame: bytes, unit: int) -> bytes:
    """The PDU of an RTU reply frame, after checking its CRC and unit id."""
    n = reply_length(frame[1:])
    if n is None or len(frame) < 1 + n + 2:
        raise IOError("short RTU reply")
    frame = frame[:1 + n + 2]
    if struct.unpack("<H", frame[-2:])[0] != crc16(frame[:-2]):
        raise IOError("RTU reply CRC mismatch")
    if frame[0] != unit:
        raise IOError(f"RTU reply from unit {frame[0]}, expected {unit}")
    return frame[1:-2]


NETWORK_TRANSPORTS = ("tcp", "tls", "udp", "rtu_over_tcp", "rtu_over_udp")


def connect(spec: dict, host: str, transport: str | None = None, port: int | None = None,
            unit: int | None = None, **tls) -> ModbusClient:
    """A client for the device on one of its network transports (the first the file lists unless given)."""
    c = spec["connection"]
    listed = [t for t in c.get("transports", ["tcp"]) if t in NETWORK_TRANSPORTS]
    if transport is None:
        if not listed:
            raise ValueError("the device has no network transport; reach it through a Modbus TCP gateway "
                             "(--transport tcp)")
        transport = listed[0]
    if transport not in NETWORK_TRANSPORTS:
        raise ValueError(f"unknown transport {transport!r} (one of {', '.join(NETWORK_TRANSPORTS)})")
    port = port or c.get("ports", {}).get(transport) or c["default_port"]
    unit = c["default_unit"] if unit is None else unit
    gap = c.get("limits", {}).get("min_interval_ms", 0)
    prefix = bytes.fromhex(c.get("reply_prefix", ""))
    if transport == "tls" and port == c["default_port"] and "tls" not in c.get("ports", {}):
        port = 802  # the registered Modbus/TCP Security port
    return {"tcp": lambda: ModbusTcp(host, port, unit, min_interval_ms=gap),
            "tls": lambda: ModbusTls(host, port, unit, min_interval_ms=gap, **tls),
            "udp": lambda: ModbusUdp(host, port, unit, min_interval_ms=gap),
            "rtu_over_tcp": lambda: ModbusRtuOverTcp(host, port, unit, min_interval_ms=gap, reply_prefix=prefix),
            "rtu_over_udp": lambda: ModbusRtuOverUdp(host, port, unit, min_interval_ms=gap, reply_prefix=prefix),
            }[transport]()


def fetch(client, key: str, address: int, count: int) -> list[int]:
    """Read from the table a table key names, on the point's own unit id if the key has one."""
    table, _, unit = key.partition("@")
    return client.read(table, address, count, unit=int(unit)) if unit else client.read(table, address, count)


def fixed_blocks(spec: dict) -> list[tuple[str, int, int]]:
    """connection.blocks as (table key, address, count): ranges the device only answers as one request."""
    return [(table_key(b), b["address"], b["count"]) for b in spec["connection"].get("blocks", [])]


def read_into(img: Image, client, regs: list[tuple[str, int, int]], limits: dict,
              fixed: list[tuple[str, int, int]] = (), alone: set = frozenset()) -> None:
    """Read the registers: those inside a fixed block by reading that whole block once, those in `alone`
    (optional points) each in a request of its own, the rest in merged blocks."""
    inside = lambda r, b: r[0] == b[0] and b[1] <= r[1] and r[1] + r[2] <= b[1] + b[2]  # noqa: E731
    for b in [b for b in fixed if any(inside(r, b) for r in regs)]:
        try:
            img.regs.setdefault(b[0], {}).update(zip(range(b[1], b[1] + b[2]), fetch(client, *b)))
        except IOError:
            pass
    regs = [r for r in regs if not any(inside(r, b) for b in fixed)]
    for r in sorted(set(r for r in regs if r in alone)):
        for t2, a2, n2 in blocks([r], {**limits, "max_gap": 0}):
            try:
                img.regs.setdefault(t2, {}).update(zip(range(a2, a2 + n2), fetch(client, t2, a2, n2)))
            except IOError:  # also a timeout: an optional sensor that isn't installed
                pass
    regs = [r for r in regs if r not in alone]
    # Requests don't reach across an optional register: group the rest by the optional registers before them.
    cut = lambda r: (r[0], sum(1 for o in alone if o[0] == r[0] and o[1] < r[1]))  # noqa: E731
    merged = [b for g in sorted({cut(r) for r in regs}) for b in blocks([r for r in regs if cut(r) == g], limits)]
    for table, a, n in merged:
        try:
            img.regs.setdefault(table, {}).update(zip(range(a, a + n), fetch(client, table, a, n)))
        except IOError:
            # A register in the block may not exist on this model: try the points one by one.
            single = sorted({r for r in regs if r[0] == table and a <= r[1] < a + n})
            if len(single) > 1 or (single and single[0] != (table, a, n)):
                for t2, a2, n2 in (b for r in single for b in blocks([r], {**limits, "max_gap": 0})):
                    try:
                        img.regs.setdefault(t2, {}).update(zip(range(a2, a2 + n2), fetch(client, t2, a2, n2)))
                    except IOError:
                        pass


def read_device(spec: dict, client, model: str | None = None) -> dict:
    """Read a device. `model` picks the model instead of detecting it (needed when model_choice is user)."""
    spec = expand(spec)
    conn = spec["connection"]
    limits, fixed = conn.get("limits", {}), fixed_blocks(spec)
    img = Image()
    enc = spec.get("encoding", {})
    conds = [enc["detect"]] if "detect" in enc else []
    for m in spec.get("models", []) if model is None else []:
        conds += conditions(m.get("match", [])) + m.get("match_any", [])
    setup = [(table_key(c), c["address"], registers(c)) for c in conds]
    read_into(img, client, setup, limits, fixed, {r for c, r in zip(conds, setup) if "answers" in c})
    word, byte = detect_orders(spec, img)
    if model is None:
        model = detect_model(spec, img, word, byte)
    pts = points_for(spec, model)
    regs = [(table_key(p), p["address"], registers(p)) for p in pts] + \
           [(table_key(p["scale_exponent_from"]), p["scale_exponent_from"]["address"], 1)
            for p in pts if "scale_exponent_from" in p]
    read_into(img, client, regs, limits, fixed,
              {(table_key(p), p["address"], registers(p)) for p in pts if p.get("optional")})
    out = {"device": spec["id"], "model": model, "word_order": word, "byte_order": byte}
    if conn.get("sleeps") and not any(img.regs.values()):  # nothing answered: asleep, e.g. after sunset
        return {**out, "asleep": True, "values": {}, "problems": []}
    vals = values(spec, img, model, word, byte)
    return {**out, "values": vals, "problems": problems(spec, vals)}


def raw_value(spec: dict, p: dict, value, exponent: int | None = None):
    """The raw number to write for a real value: the inverse of `values` (enum name, sign, scale, offset,
    exponent), checked against `min`, `max` and the enum. Raises ValueError."""
    if p["type"] in ("str", "datetime"):
        return value
    if p.get("enum") and isinstance(value, str) and not re.fullmatch(r"-?\d+(\.\d+)?", value.strip()):
        names = {str(t).casefold(): k for k, t in spec.get("enums", {})[p["enum"]].items()}
        if value.strip().casefold() not in names:
            raise ValueError(f"{value!r} is not one of {sorted(spec['enums'][p['enum']].values())}")
        value = names[value.strip().casefold()]
    v = real = float(value)
    if p.get("enum") and str(int(v)) not in spec.get("enums", {})[p["enum"]] and v == int(v):
        raise ValueError(f"{int(v)} is not in enum {p['enum']}")
    want = direction(vocabulary().get(p["key"], {}), spec)
    if want and p.get("positive") == OPPOSITE[want]:
        v = -v
    v = (v - p.get("offset", 0)) / p.get("scale", 1)
    if exponent is not None:
        v = v / 10 ** (-exponent if p["scale_exponent_from"].get("negate") else exponent)
    if p["type"] == "bool" or not p["type"].startswith("f"):
        r = round(v)
        if abs(r - v) > 1e-6 * max(1.0, abs(v)):
            raise ValueError(f"{value} is not a whole step of {p.get('scale', 1)}")
        v = r
    # a raw value from `invalid` (e.g. "no setpoint request") may be written whatever min and max say
    if ("min" in p and real < p["min"] or "max" in p and real > p["max"]) and v not in p.get("invalid", []):
        raise ValueError(f"{value} outside {p.get('min', '…')}…{p.get('max', '…')}")
    return v


def write_point(spec: dict, client, key: str, value, model: str | None = None, unit: int | None = None) -> dict:
    """Write one value. Reads first what the write needs (the device's word order where it is detected, the
    exponent register, the rest of a register a bit field or date shares), writes with function 05/15 (coil) or
    06/16 (registers, also for a point read from the input table), then reads the value back unless it is
    write-only. Returns {"key", "written": registers or bit, "value": read back or None}."""
    spec = expand(spec)
    pts = [q for q in points_for(spec, model) if q["key"] == key]
    if not pts:
        raise ValueError(f"no point {key!r}" + (f" for model {model}" if model else ""))
    p = pts[0]
    if not p.get("writable"):
        raise ValueError(f"{key} is not writable")
    conn = spec["connection"]
    limits = conn.get("limits", {})
    img = Image()
    enc = spec.get("encoding", {})
    if "detect" in enc:
        d = enc["detect"]
        read_into(img, client, [(table_key(d), d["address"], registers(d))], limits, fixed_blocks(spec))
    word, byte = detect_orders(spec, img)
    word, byte = p.get("word_order", word), p.get("byte_order", byte)
    exponent = None
    if "scale_exponent_from" in p:
        e = p["scale_exponent_from"]
        read_into(img, client, [(table_key(e), e["address"], 1)], limits, fixed_blocks(spec))
        exponent = value_of(img, e, word, byte)
        if "bits" in e:
            lo, hi = e["bits"]
            exponent = (int(exponent) >> lo) & ((1 << (hi - lo + 1)) - 1)
            if e.get("signed") and exponent >> (hi - lo):
                exponent -= 1 << (hi - lo + 1)
    raw = raw_value(spec, p, value, exponent)
    n = registers(p)
    table = "coil" if p["table"] == "coil" else "holding"
    address = p.get("write_address", p["address"])
    target = f"{table}@{p['unit_id']}" if "unit_id" in p else table
    if p["type"] == "bool":
        words = [1 if raw else 0]
    elif p["type"] == "datetime" or "bits" in p:
        if p.get("write_only"):  # can't be read back: the bits the point doesn't cover are written as 0
            current = [0] * n
        else:  # the rest of the register(s) keeps its value: read it first (from where the point is read)
            read_into(img, client, [(table_key(p), p["address"], n)], limits, fixed_blocks(spec))
            current = img.words(table_key(p), p["address"], n)
            if current is None:
                raise IOError(f"could not read {key} before writing it")
        if p["type"] == "datetime":
            words = datetime_words(str(raw), p["datetime"], current)
        else:
            lo, hi = p["bits"]
            width = hi - lo + 1
            if not (-(1 << (width - 1)) <= raw < 1 << width if p.get("signed") else 0 <= raw < 1 << width):
                raise ValueError(f"{value} doesn't fit bits {lo}…{hi}")
            whole = decode(current, p["type"], word, byte)
            mask = ((1 << width) - 1) << lo
            num = (int(whole) & ~mask) | ((int(raw) << lo) & mask)
            if p["type"].startswith("s") and num >= 1 << (16 * n - 1):
                num -= 1 << (16 * n)
            words = encode(num, p["type"], word, byte)
    else:
        words = encode(raw, p["type"], word, byte, p.get("chars", "both"), p.get("length", 1))
    multiple = p.get("write_multiple", conn.get("write_multiple", False))
    tbl, _, u = target.partition("@")
    if p.get("write_single", conn.get("write_single", False)):  # no function 16: one 06 per register, in order
        for i, w in enumerate(words):
            client.write(tbl, address + i, [w], unit=int(u) if u else unit)
    else:
        client.write(tbl, address, words, unit=int(u) if u else unit, multiple=multiple)
    out = {"key": key, "written": words, "value": None}
    if not p.get("write_only"):
        img = Image(regs={k: v for k, v in img.regs.items() if not k.startswith(p["table"])})
        read_into(img, client, [(table_key(p), p["address"], n)], limits, fixed_blocks(spec))
        got = values({**spec, "points": [p]}, img, model, word, byte)
        out["value"] = got.get(key)
    return out


# ---------------------------------------------------------------- command line

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("files", nargs="*", type=Path)
    r = sub.add_parser("read")
    r.add_argument("file", type=Path)
    r.add_argument("--host", required=True)
    r.add_argument("--port", type=int)
    r.add_argument("--unit", type=int)
    r.add_argument("--transport", choices=NETWORK_TRANSPORTS,
                     help="how to reach the device (default: the first network transport the file lists)")
    r.add_argument("--cafile", help="tls: CA certificate(s) that signed the device's certificate")
    r.add_argument("--cert", help="tls: client certificate (PEM)")
    r.add_argument("--key", help="tls: client key (PEM), if not in --cert")
    r.add_argument("--insecure", action="store_true", help="tls: don't check the device's certificate")
    r.add_argument("--model", help="the model id (for devices whose models can't be told apart)")
    w = sub.add_parser("write", help="write one value (a writable point), then read it back")
    w.add_argument("file", type=Path)
    w.add_argument("key")
    w.add_argument("value", help="a number, an enum name, true/false for a coil, text, or ISO 8601 date/time")
    w.add_argument("--host", required=True)
    w.add_argument("--port", type=int)
    w.add_argument("--unit", type=int)
    w.add_argument("--transport", choices=NETWORK_TRANSPORTS,
                     help="how to reach the device (default: the first network transport the file lists)")
    w.add_argument("--cafile", help="tls: CA certificate(s) that signed the device's certificate")
    w.add_argument("--cert", help="tls: client certificate (PEM)")
    w.add_argument("--key", help="tls: client key (PEM), if not in --cert")
    w.add_argument("--insecure", action="store_true", help="tls: don't check the device's certificate")
    w.add_argument("--model", help="the model id (for points that only some models have)")
    a = ap.parse_args(argv)
    if a.cmd == "validate":
        files = a.files or sorted((ROOT / "devices").rglob("*.yaml"))
        errors = [e for f in files for e in validate(load(f), str(f.relative_to(ROOT) if f.is_absolute() else f))]
        for e in errors:
            print(e)
        print(f"{len(files)} files, {len(errors)} problems")
        return 1 if errors else 0
    spec = load(a.file)
    tls = {"cafile": a.cafile, "certfile": a.cert, "keyfile": a.key, "insecure": a.insecure}
    client = connect(spec, a.host, a.transport, a.port, a.unit, **tls)
    if a.cmd == "write":
        value = {"true": 1, "false": 0, "on": 1, "off": 0}.get(a.value.lower(), a.value)
        print(json.dumps(write_point(spec, client, a.key, value, a.model), indent=2, ensure_ascii=False))
        return 0
    print(json.dumps(read_device(spec, client, a.model), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
