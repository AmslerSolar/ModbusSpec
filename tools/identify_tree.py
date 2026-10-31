#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Amsler Solar GmbH
"""A decision tree that identifies a device with few reads, generated from the `identify` blocks of the device files.

    python3 tools/identify_tree.py                                # how many reads the trees take
    python3 tools/identify_tree.py --out identify_tree.json       # write the trees (after changing a device file)
    python3 tools/identify_tree.py --host 192.168.1.40 [--port 502] [--unit 1] [--transport tcp] [--timeout 1]
                                                                  #   [--tree port:502]
                                                                  # identify a real device (reads only)

The JSON has one root per way of finding a device: `serial` (a device on an RS485 line, directly or through a
transparent gateway) and `port:<n>` (a TCP or UDP port found open; devices behind a Modbus TCP gateway count as well):

    {"roots": {"serial": 12, "port:502": 40},
     "tests": [{"if": {"table": "holding", "address": 0, "type": "u16", "equals": 5},
                "reads": [{"table": "holding", "address": 0, "count": 1}]}],
     "nodes": [{"test": 0, "yes": 1, "no": 2}, {"found": ["meter/eastron/sdm"]}, {"found": []}]}

To walk it, start at a root. At a node with `test`, make each request in `reads` not made yet, wait `min_interval_ms`
first where a request gives one, and go on with `yes` if the condition `if` holds (see `identify` in FORMAT.md; no
answer to the request: the register doesn't answer), else with `no`. Answers are kept, so a test on registers already
read costs nothing. A test with `encoding` has the register order given by that `detect`, as in a device file. A node
with `found` ends the walk: the files that identify the device, the most specific first (empty: unknown device).

A tree is one chain of tests. Each next test on it is free if one is left on registers already read, else one of the
request that can rule out the most files (a file with alternatives counts for its share). When a test holds, the walk
leaves the chain to confirm the files that test speaks for, the most specific first, and comes back to the next test if
none holds, so the size of a tree grows with the number of tests, not with their combinations.

Files with strong evidence (`SURE_BITS`) come first on the chain, and those with weak evidence alone (a plausible range,
a small number) after them, since other devices can pass weak checks too. A walk ends at the first file that holds once
no more specific file is left to confirm, so `found` names more than one file only when they hold on the same answers.
A device known by weak evidence therefore costs all the reads for the strong files.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time

import msp

SURE_BITS = 16  # evidence that ends a search; see bits()
TEXT = ("str", "datetime")
SERIAL = {"rtu", "ascii", "rtu_over_tcp"}


def bits(c: dict) -> float:
    """A rough count of how much a condition tells: the chance, as bits, that some other device passes by accident.
    Numbers up to 255 are common register values and ranges only say the value is plausible."""
    def of(v):
        return 6 * len(v) if isinstance(v, str) else 16 if abs(v) > 255 else 6
    n = 0.0
    if "equals" in c:
        n += of(c["equals"])
    if "in" in c:
        n += max(0.0, min(of(v) for v in c["in"]) - math.log2(len(c["in"])))
    if "prefix" in c:
        n += of(c["prefix"])
    if "contains" in c:
        n += min(of(t) for t in c["contains"])
    if "range" in c:
        n += 4
    if c.get("printable"):
        n += 6
    return n or 1  # only `not`, `not_in` or `answers`


def request_key(r: dict) -> tuple:
    return r["table"], r["address"], r["count"], r.get("unit_id")


def requests(conds: list[dict], conn: dict) -> list[dict]:
    """The requests a device with this `connection` takes for these conditions, each on its own."""
    limits = {**conn.get("limits", {}), "max_gap": 0}
    out = []
    for c in conds:
        r = (msp.table_key(c), c["address"], msp.registers(c))
        block = [b for b in msp.fixed_blocks({"connection": conn})
                 if r[0] == b[0] and b[1] <= r[1] and r[1] + r[2] <= b[1] + b[2]]
        for key, a, n in block[:1] or msp.blocks([r], limits):
            table, _, unit = key.partition("@")
            req = {"table": table, "address": a, "count": n, **({"unit_id": int(unit)} if unit else {})}
            if req not in out:
                out.append(req)
    return out


class Builder:
    def __init__(self, specs: dict[str, dict]):
        self.tests, self.index = [], {}
        self.nodes, self.seen, self.memo = [], {}, {}
        self.names = sorted(specs)
        self.ids = {n: i for i, n in enumerate(self.names)}
        self.exprs = [self.identify_expr(specs[n]) for n in self.names]
        self.atoms = [self.leaves(e) for e in self.exprs]
        self.strength = [self.evidence(e) for e in self.exprs]
        self.reads = [tuple(sorted(map(request_key, t["reads"]), key=str)) for t in self.tests]

    # ---- conditions to tests

    def test(self, c: dict, spec: dict) -> int:
        """The test for a condition as this file reads it: register order and requests spelled out."""
        conn, enc = spec["connection"], spec.get("encoding", {})
        c = dict(c)
        word, byte = c.pop("word_order", enc.get("word_order", "big")), c.pop("byte_order", enc.get("byte_order", "big"))
        if c["type"] in TEXT or msp.registers(c) == 1:
            word = "big"
        conds, encoding = [c], None
        if "detect" in (word, byte):
            encoding = {k: enc[k] for k in ("word_order", "byte_order", "detect") if k in enc}
            conds.insert(0, enc["detect"])
        if word not in ("big", "detect"):
            c["word_order"] = word
        if byte not in ("big", "detect"):
            c["byte_order"] = byte
        t = {"if": c, "reads": requests(conds, conn)}
        if encoding:
            t["encoding"] = encoding
        key = json.dumps(t, sort_keys=True)
        if key not in self.index:
            self.index[key] = len(self.tests)
            self.tests.append(t)
        i = self.index[key]
        gap = conn.get("limits", {}).get("min_interval_ms")
        for r in self.tests[i]["reads"] if gap else []:
            r["min_interval_ms"] = max(gap, r.get("min_interval_ms", 0))
        return i

    def identify_expr(self, spec: dict):
        """A file's `identify` as ("and"/"or", children) over test numbers, read like msp.identifies does."""
        ident = spec["identify"]

        def one(c):
            return every(c) if isinstance(c, list) else self.test(c, spec)

        def every(cs):
            return ("and", [("or", [one(y) for y in x]) if isinstance(x, list) else one(x) for x in cs])
        parts = [every(ident.get("checks", []))]
        if "any" in ident:
            parts.append(("or", [one(c) for c in ident["any"]]))
        return ("and", parts)

    def leaves(self, e) -> set[int]:
        return {e} if isinstance(e, int) else set().union(*[self.leaves(c) for c in e[1]], set())

    def evidence(self, e) -> float:
        """What a file's identification tells at the least: all of an "and", the weakest of an "or"."""
        if isinstance(e, int):
            return bits(self.tests[e]["if"])
        values = [self.evidence(c) for c in e[1]]
        return (sum(values) if e[0] == "and" else min(values)) if values else 0

    # ---- the tree

    def holds(self, e, truth: dict[int, bool]) -> bool | None:
        if isinstance(e, int):
            return truth.get(e)
        values = [self.holds(c, truth) for c in e[1]]
        stop = e[0] == "or"  # one True decides an "or", one False an "and"
        if stop in values:
            return stop
        return None if None in values else not stop

    def open_tests(self, e, truth: dict[int, bool], share: float, out: dict[int, float]) -> None:
        """The unanswered tests that still matter for a file, with the share of the file they can rule out."""
        if isinstance(e, int):
            if e not in truth:
                out[e] = max(out.get(e, 0), share)
            return
        live = [c for c in e[1] if self.holds(c, truth) is None]
        for c in live:
            self.open_tests(c, truth, share if e[0] == "and" else share / len(live), out)

    def next_test(self, files: list[int], truth: dict[int, bool], made: set[tuple]) -> int:
        """A free test, else a test of the requests that can rule out the most files per request made."""
        need_of, score, count = {}, {}, {}
        for f in files:
            shares: dict[int, float] = {}
            self.open_tests(self.exprs[f], truth, 1.0, shares)
            best: dict[tuple, float] = {}
            for a, s in shares.items():
                need = need_of.setdefault(a, tuple(k for k in self.reads[a] if k not in made))
                best[need] = max(best.get(need, 0), s)
                count[a] = count.get(a, 0) + s
            for need, s in best.items():
                score[need] = score.get(need, 0) + s
        need = min(score, key=lambda n: (-score[n] / len(n) if n else -math.inf, str(n)))
        return min((a for a in count if need_of[a] == need), key=lambda a: (-count[a], a))

    def chain(self, files: list[int], made: set[tuple]) -> list[tuple[int, list[int], frozenset]]:
        """The tests for these files when none holds: (test, the files it speaks for, requests made before it). A test
        that holds and whose files all fail is taken as not holding from then on, as no file left depends on it."""
        steps, truth = [], {}
        while True:
            files = [f for f in files if self.holds(self.exprs[f], truth) is None]
            if not files:
                return steps
            a = self.next_test(files, truth, made)
            steps.append((a, [f for f in files if a in self.atoms[f]], frozenset(made)))
            truth[a] = False
            made.update(self.reads[a])

    def confirm(self, files: list[int], passed: frozenset[int], truth: dict[int, bool], made: frozenset,
                otherwise: int) -> int:
        """The node that settles these files, given the answers so far: the most specific first; `otherwise` if none
        holds."""
        still = []
        for f in files:
            v = self.holds(self.exprs[f], truth)
            if v is True:
                passed |= {f}
            elif v is None:
                still.append(f)
        wanted = {a for f in still for a in self.atoms[f]}
        key = (tuple(still), passed, tuple(sorted((a, v) for a, v in truth.items() if a in wanted)), otherwise)
        if key in self.memo:
            return self.memo[key]
        proven = max((self.strength[f] for f in passed), default=-1)
        pool = [f for f in still if self.strength[f] > proven]
        if pool:
            top = max(self.strength[f] for f in pool)
            a = self.next_test([f for f in pool if self.strength[f] == top], truth,
                               made.union(k for t in truth for k in self.reads[t]))
            out = self.node(a, self.confirm(still, passed, {**truth, a: True}, made, otherwise),
                            self.confirm(still, passed, {**truth, a: False}, made, otherwise))
        elif passed:
            found = sorted(passed, key=lambda f: (-self.strength[f], self.names[f]))
            out = self.node(None, found=[self.names[f] for f in found])
        else:
            out = otherwise
        self.memo[key] = out
        return out

    def node(self, test: int | None, yes: int | None = None, no: int | None = None,
             found: list[str] | None = None) -> int:
        if test is not None and yes == no:  # the answer changes nothing: skip the read
            return yes
        key = (test, yes, no, tuple(found or ()))
        if key not in self.seen:
            self.seen[key] = len(self.nodes)
            self.nodes.append({"found": found} if test is None else {"test": test, "yes": yes, "no": no})
        return self.seen[key]

    def build(self, names: list[str]) -> int:
        """The root for these files: the strong ones first on the chain, then the weak ones."""
        files = sorted(self.ids[n] for n in names)
        made: set[tuple] = set()
        steps = self.chain([f for f in files if self.strength[f] >= SURE_BITS], made)
        steps += self.chain([f for f in files if self.strength[f] < SURE_BITS], made)
        node = self.node(None, found=[])
        for a, speaks_for, before in reversed(steps):
            node = self.node(a, self.confirm(speaks_for, frozenset(), {a: True}, before, node), node)
        return node


def roots_of(spec: dict) -> list[str]:
    """Where a search can meet this device: its ports, and the serial line if it has a serial transport."""
    c = spec["connection"]
    transports = c.get("transports", ["tcp"])
    ports = {c["default_port"]} | {p for t, p in c.get("ports", {}).items() if t in transports}
    return sorted(f"port:{p}" for p in ports) + (["serial"] if SERIAL & set(transports) else [])


def load_all() -> dict[str, dict]:
    """The device files that can recognise their device, by path below devices/."""
    specs = {str(f.relative_to(msp.ROOT / "devices"))[:-5]: msp.load(f)
             for f in sorted((msp.ROOT / "devices").rglob("*.yaml"))}
    return {n: s for n, s in specs.items() if msp.has_identify(s)}


def generate(specs: dict[str, dict]) -> dict:
    b = Builder(specs)
    groups: dict[str, list[str]] = {}
    for name in b.names:
        for root in roots_of(specs[name]):
            groups.setdefault(root, []).append(name)
    roots = {root: b.build(groups[root]) for root in sorted(groups)}
    return {"roots": roots, "tests": b.tests, "nodes": b.nodes}


def dumps(tree: dict) -> str:
    """The trees as JSON, one test or node per line, so that a change to a device file gives a readable diff."""
    def one(x):
        return json.dumps(x, ensure_ascii=False, separators=(", ", ": "))

    def lines(items):
        return ",\n".join("  " + one(x) for x in items)
    return f'{{\n "roots": {one(tree["roots"])},\n "tests": [\n{lines(tree["tests"])}\n ],\n' \
           f' "nodes": [\n{lines(tree["nodes"])}\n ]\n}}\n'


def walk(tree: dict, root: str, client, pace: bool = True) -> tuple[list[str], int]:
    """(the files that identify the device, requests made). `client.read` raises IOError when there is no answer."""
    img, made = msp.Image(), set()
    node = tree["nodes"][tree["roots"][root]]
    while "found" not in node:
        t = tree["tests"][node["test"]]
        for r in t["reads"]:
            key = f"{r['table']}@{r['unit_id']}" if "unit_id" in r else r["table"]
            if (key, r["address"], r["count"]) in made:
                continue
            made.add((key, r["address"], r["count"]))
            if pace:
                time.sleep(r.get("min_interval_ms", 0) / 1000)
            try:
                words = msp.fetch(client, key, r["address"], r["count"])
                img.regs.setdefault(key, {}).update(zip(range(r["address"], r["address"] + r["count"]), words))
            except IOError:
                pass
        word, byte = msp.detect_orders({"encoding": t["encoding"]}, img) if "encoding" in t else ("big", "big")
        node = tree["nodes"][node["yes" if msp.condition_holds(img, t["if"], word, byte) else "no"]]
    return node["found"], len(made)


class Simulated:
    """A device that answers from a register image and with an exception for everything else."""

    def __init__(self, img: msp.Image):
        self.img = img

    def read(self, table: str, address: int, count: int, unit: int | None = None) -> list[int]:
        words = self.img.words(f"{table}@{unit}" if unit is not None else table, address, count)
        if words is None:
            raise IOError("illegal address")
        return words


def simulated_image(spec: dict) -> msp.Image | None:
    """Registers that pass a file's own identify, and that answer the whole requests its identification makes:
    aligned and block requests reach beyond what the checks look at (those registers read 0)."""
    import collisions
    img = collisions.simulate(spec)
    if img is None:
        return None
    ident, enc = spec["identify"], spec.get("encoding", {})
    conds = msp.conditions(ident.get("checks", [])) + msp.conditions(ident.get("any", []))
    conds += [enc["detect"]] if "detect" in enc else []
    for r in requests([c for c in conds if c.get("answers") is not False], spec["connection"]):
        key = f"{r['table']}@{r['unit_id']}" if "unit_id" in r else r["table"]
        known = img.regs.get(key, {})
        if any(a in known for a in range(r["address"], r["address"] + r["count"])):
            for a in range(r["address"], r["address"] + r["count"]):
                known.setdefault(a, 0)
    return img


def report(tree: dict, specs: dict[str, dict]) -> None:
    print(f"{len(specs)} files, {len(tree['tests'])} tests, {len(tree['nodes'])} nodes")
    print(f"{'tree':>12} {'files':>6} {'unknown':>8} {'known: median':>14} {'90 %':>6} {'max':>6}")
    for root in sorted(tree["roots"], key=lambda r: (-sum(r in roots_of(s) for s in specs.values()), r)):
        names = [n for n, s in specs.items() if root in roots_of(s)]
        costs = []
        for n in names:
            img = simulated_image(specs[n])
            if img is not None:
                costs.append(walk(tree, root, Simulated(img), pace=False)[1])
        costs.sort()
        _, silent = walk(tree, root, Simulated(msp.Image()), pace=False)
        print(f"{root:>12} {len(names):>6} {silent:>8} {costs[len(costs) // 2]:>14} "
              f"{costs[len(costs) * 9 // 10]:>6} {costs[-1]:>6}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", help="write the trees to this file")
    ap.add_argument("--host", help="identify the device at this address")
    ap.add_argument("--port", type=int, default=502)
    ap.add_argument("--unit", type=int, default=1)
    ap.add_argument("--transport", default="tcp", choices=sorted(msp.NETWORK_TRANSPORTS))
    ap.add_argument("--timeout", type=float, default=1.0, help="seconds to wait for each answer")
    ap.add_argument("--tree", help="the root to walk; by default port:<port>, or serial with rtu_over_tcp")
    args = ap.parse_args()
    specs = load_all()
    tree = generate(specs)
    if args.host:
        root = args.tree or ("serial" if args.transport == "rtu_over_tcp" else f"port:{args.port}")
        try:
            client = msp.connect({"connection": {"default_port": args.port, "default_unit": args.unit}}, args.host,
                                 args.transport, args.port, args.unit)
        except OSError as e:
            print(f"{args.host}:{args.port}: {e}", file=sys.stderr)
            return 2
        client.sock.settimeout(args.timeout)
        started = time.monotonic()
        found, requests = walk(tree, root, client)
        print(f"{', '.join(found) or 'unknown device'}: {requests} requests in {time.monotonic() - started:.1f} s")
        return 0 if found else 1
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(dumps(tree))
        print(f"wrote {args.out}")
    report(tree, specs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
