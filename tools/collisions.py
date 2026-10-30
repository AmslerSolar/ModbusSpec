#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Amsler Solar GmbH
"""Which device files would take another file's device for theirs in a search of the network.

    python3 tools/collisions.py                  # every pair, one per line

For each file with `identify`, a simulated device answers with register values that pass its own checks (and only
those registers); every other file's `identify` is then tried on it. A hit means a search can't tell the two apart
from the identification alone. Files with different default ports aren't compared.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import msp

STRING = "AB12"  # a printable text for `printable` checks without a prefix


def encode(v, c: dict, word_order: str, byte_order: str) -> list[int] | None:
    """Registers holding v as condition c reads them; None when v doesn't fit the type."""
    t, n = c["type"], msp.registers(c)
    try:
        if t == "str":
            raw = str(v).encode("latin-1")
            if c.get("chars", "both") != "both":
                words = [(b << 8 if c["chars"] == "high" else b) for b in raw[:n]] + [0] * (n - len(raw))
            else:
                raw = (raw + b"\0" * (2 * n))[:2 * n]
                words = list(struct.unpack(f">{n}H", raw))
        elif t in ("f16", "f32", "f64"):
            words = list(struct.unpack(f">{n}H", struct.pack({"f16": ">e", "f32": ">f", "f64": ">d"}[t], float(v))))
        elif t.startswith("bcd"):  # decimal digits as nibbles
            digits = f"{int(v):0{4 * n}d}"
            if int(v) < 0 or len(digits) > 4 * n:
                return None
            words = [int(digits[4 * i:4 * i + 4], 16) for i in range(n)]
        elif t in ("bool", "datetime") or t.startswith("sm"):
            return None
        else:
            signed = t.startswith("s")
            bits = 16 * n
            if not (-(1 << (bits - 1)) <= v < (1 << (bits - 1)) if signed else 0 <= v < (1 << bits)):
                return None
            u = int(v) & ((1 << bits) - 1)
            words = [(u >> (16 * (n - 1 - i))) & 0xFFFF for i in range(n)]
    except (struct.error, UnicodeEncodeError, ValueError, TypeError):
        return None
    if t != "str" and c.get("word_order", word_order) == "little":
        words.reverse()
    if c.get("byte_order", byte_order) == "little":
        words = [(w >> 8) | ((w & 0xFF) << 8) for w in words]
    return words


def candidates(c: dict) -> list:
    """Values that may pass a condition, the likely ones first."""
    out = []
    if "equals" in c:
        out.append(c["equals"])
    out += c.get("in", [])
    if "prefix" in c:
        out += [c["prefix"], c["prefix"] + "1"]
    out += [STRING + t for t in c.get("contains", [])]
    if "range" in c:
        lo, hi = c["range"]
        out += [lo, hi, (lo + hi) / 2 if c["type"].startswith("f") else (lo + hi) // 2]
    if c["type"] == "str":
        out.append(STRING)
    out += [1, 100, 1000, 12345, 2, 0]
    return out


def simulate(spec: dict) -> msp.Image | None:
    """Registers that pass the file's identify checks (the first way that works); None if none found."""
    word, byte = spec.get("encoding", {}).get("word_order", "big"), spec.get("encoding", {}).get("byte_order", "big")
    word, byte = ("big" if word == "detect" else word), ("big" if byte == "detect" else byte)
    ident = spec["identify"]
    # One alternative of each group: the checks, and the first item of `any`.
    needs: list[dict] = []
    for c in ident.get("checks", []):
        needs.append(c[0] if isinstance(c, list) else c)
    if ident.get("any"):
        first = ident["any"][0]
        needs += [x[0] if isinstance(x, list) else x for x in (first if isinstance(first, list) else [first])]
    img = msp.Image()
    groups: dict[tuple, list[dict]] = {}
    for c in needs:
        groups.setdefault((msp.table_key(c), c["address"]), []).append(c)
    for (table, address), conds in groups.items():
        if any(c.get("answers") is False for c in conds):
            continue  # the register stays silent
        widest = max(conds, key=msp.registers)
        both = [c.get("prefix", "") + t for c in conds for d in conds for t in d.get("contains", [])]
        for v in both + [v for c in conds for v in candidates(c)]:
            for c in [widest] + conds:
                words = encode(v, c, word, byte)
                if words is None:
                    continue
                trial = msp.Image({k: dict(t) for k, t in img.regs.items()})
                trial.regs.setdefault(table, {}).update(zip(range(address, address + len(words)), words))
                if all(msp.condition_holds(trial, x, word, byte) for x in conds):
                    img = trial
                    break
            else:
                continue
            break
        else:
            return None
    return img if msp.identifies(spec, img, word, byte) else None


def accepts(spec: dict, img: msp.Image) -> bool:
    """Whether a file's identify passes on these registers, in the orders it would detect."""
    word, byte = msp.detect_orders(spec, img)
    return msp.identifies(spec, img, word, byte)


def collisions(specs: dict[str, dict]) -> tuple[list[tuple[str, str]], list[str]]:
    """(pairs (a, b) where b's identify accepts a's simulated device, files that couldn't be simulated)."""
    found, unsimulated = [], []
    with_id = {n: s for n, s in specs.items() if msp.has_identify(s)}
    for a, sa in with_id.items():
        img = simulate(sa)
        if img is None:
            unsimulated.append(a)
            continue
        port = sa["connection"]["default_port"]  # a search tries the files of the port it found open
        found += [(a, b) for b, sb in with_id.items()
                  if b != a and sb["connection"]["default_port"] == port and accepts(sb, img)]
    return found, unsimulated


def load_all() -> dict[str, dict]:
    return {f"{f.parent.name}/{f.stem}": msp.load(f)  # maker/family
            for f in sorted((msp.ROOT / "devices").rglob("*.yaml"))}


def main() -> int:
    found, unsimulated = collisions(load_all())
    for a, b in found:
        print(f"{a}  is taken for  {b}")
    for a in unsimulated:
        print(f"{a}: no register values found that pass its own identify")
    return 1 if found or unsimulated else 0


if __name__ == "__main__":
    sys.exit(main())
