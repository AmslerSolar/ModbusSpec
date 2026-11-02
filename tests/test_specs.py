# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Amsler Solar GmbH
import json
import socket
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import msp  # noqa: E402

DEVICES = sorted((msp.ROOT / "devices").rglob("*.yaml"))


@pytest.mark.parametrize("path", DEVICES, ids=lambda p: str(p.relative_to(msp.ROOT)))
def test_device_files_are_valid(path):
    assert msp.validate(msp.load(path), path.name) == []


def f32(v, order="big"):
    hi, lo = struct.unpack(">HH", struct.pack(">f", v))
    return [hi, lo] if order == "big" else [lo, hi]


def u32(v):
    return [v >> 16, v & 0xFFFF]


class FakeDevice:
    """Answers reads from a register image; unknown registers raise like a Modbus exception 2."""

    def __init__(self, holding=None, input=None):
        self.regs = {"holding": holding or {}, "input": input or {}}
        self.requests = []

    def read(self, table, address, count):
        self.requests.append((table, address, count))
        t = self.regs[table]
        if any(a not in t for a in range(address, address + count)):
            raise IOError("Modbus exception 2")
        return [t[a] for a in range(address, address + count)]


def put(regs, address, words):
    regs.update(zip(range(address, address + len(words)), words))


def sdm630(order):
    inp, hold = {}, {}
    for a, v in [(0x00, 231.0), (0x02, 232.0), (0x04, 230.0), (0x06, 5.0), (0x08, 4.0), (0x0A, 3.0),
                 (0x0C, 1000.0), (0x0E, 900.0), (0x10, 800.0), (0x34, 2700.0), (0x38, 2900.0), (0x3C, 100.0),
                 (0x3E, 0.98), (0x46, 50.0), (0x48, 1234.5), (0x4A, 678.25), (0x4C, 1.0), (0x4E, 2.0)]:
        put(inp, a, f32(v, order))
    put(hold, 0x0A, f32(3.0, order))
    put(hold, 0xFC00, u32(12345678) if order == "big" else list(reversed(u32(12345678))))
    put(hold, 0xFC02, [0x0070, 0x0102])  # meter code, software version
    return FakeDevice(hold, inp)


@pytest.mark.parametrize("order", ["big", "little"])
def test_eastron_sdm630_both_word_orders(order):
    spec = msp.load(msp.ROOT / "devices/meter/eastron/sdm.yaml")
    r = msp.read_device(spec, sdm630(order))
    assert r["model"] == "sdm630" and r["word_order"] == order
    v = r["values"]
    assert v["grid_power"] == -2700.0  # the meter's + = import becomes the vocabulary's − = import
    assert v["l1_power"] == -1000.0
    assert v["frequency"] == 50.0 and v["grid_import_energy"] == 1234.5
    assert v["x.system_type.text"] == "3 phase 4 wire"
    assert v["serial"] == 12345678


def test_eastron_requests_respect_the_limits():
    spec = msp.load(msp.ROOT / "devices/meter/eastron/sdm.yaml")
    dev = sdm630("big")
    msp.read_device(spec, dev)
    assert all(a % 2 == 0 and n % 2 == 0 and n <= 80 for _, a, n in dev.requests)


def keba(state=3, error=0):
    hold = {}
    for a, v in [(1000, state), (1004, 7), (1006, error), (1008, 16000), (1010, 15500), (1012, 0),
                 (1020, 7_360_000), (1502, 52_340), (1036, 12_345_678), (1040, 230), (1042, 231), (1044, 0),
                 (1046, 990), (1100, 16000), (1110, 32000), (1014, 22334455), (1016, 311_401), (1018, 0x030A1000)]:
        put(hold, a, u32(v))
    return FakeDevice(hold)


def test_keba_values_and_scaling():
    spec = msp.load(msp.ROOT / "devices/charger/keba/kecontact-p30.yaml")
    dev = keba()
    r = msp.read_device(spec, dev)
    v = r["values"]
    assert v["consumer_power"] == 7360.0 and v["l1_current"] == 16.0
    assert v["session_energy"] == 5.234 and v["consumer_energy"] == 1234.5678
    assert v["state.text"] == "Charging"
    assert r["problems"] == []
    assert all(n <= 2 for _, _, n in dev.requests)


def test_keba_fault():
    spec = msp.load(msp.ROOT / "devices/charger/keba/kecontact-p30.yaml")
    r = msp.read_device(spec, keba(state=4, error=0x40000))
    assert r["problems"] == [
        {"kind": "fault", "text": "Charging station error (code 0x40000)"},
        {"kind": "fault", "text": "Charging station error (state 4)"},
    ]


def test_validator_catches_mistakes():
    spec = msp.load(msp.ROOT / "devices/charger/keba/kecontact-p30.yaml")
    spec["points"].append({"key": "grid_power", "label": "x", "table": "holding", "address": 1020, "type": "u32", "unit": "kW"})
    errors = msp.validate(spec)
    assert any("unit" in e for e in errors)
    assert any("needs `positive`" in e for e in errors)
    assert any("overlaps" in e for e in errors)


def test_blocks():
    assert msp.blocks([("input", 0, 2), ("input", 2, 2), ("input", 8, 2)], {"max_gap": 2}) == [("input", 0, 4), ("input", 8, 2)]
    assert msp.blocks([("input", 0, 2), ("input", 4, 2)], {"max_gap": 2, "max_registers": 4}) == [("input", 0, 2), ("input", 4, 2)]
    assert msp.blocks([("input", 3, 1)], {"even_address": True}) == [("input", 2, 2)]


def test_coils_and_discrete_inputs_are_read_as_bits():
    spec = {"modbusspec": 0, "id": "acme-relay", "manufacturer": "Acme", "name": "Relay", "kind": "io",
            "sources": [{"title": "t"}], "connection": {"default_port": 502, "default_unit": 1},
            "points": [{"key": "x.relay_2", "label": "Relay 2", "table": "coil", "address": 1, "type": "bool"},
                       {"key": "x.input_1", "label": "Input 1", "table": "discrete", "address": 0, "type": "bool"}]}
    assert msp.validate(spec) == []
    assert msp.validate({**spec, "points": [{**spec["points"][0], "type": "u16"}]}) != []
    dev = FakeDevice()
    dev.regs.update(coil={0: 0, 1: 1}, discrete={0: 1})
    assert msp.read_device(spec, dev)["values"] == {"x.relay_2": 1, "x.input_1": 1}


class UnitFake:
    """Registers per unit id: {unit: {table: {address: word}}}; the default unit is 1."""

    def __init__(self, units):
        self.units = units

    def read(self, table, address, count, unit=1):
        t = self.units[unit][table]
        if any(a not in t for a in range(address, address + count)):
            raise IOError("Modbus exception 2")
        return [t[a] for a in range(address, address + count)]


def device(points, **extra):
    spec = {"modbusspec": 0, "id": "acme-x", "manufacturer": "Acme", "name": "X", "kind": "meter",
            "sources": [{"title": "t"}], "connection": {"default_port": 502, "default_unit": 1}, "points": points,
            **extra}
    assert msp.validate(spec) == []
    return spec


def test_sign_magnitude_bcd_and_one_character_per_register():
    assert msp.decode([0x8005], "sm16") == -5 and msp.decode([0x0005], "sm16") == 5
    assert msp.decode([0x8000, 0x0010], "sm32") == -16
    assert msp.decode([0x1234], "bcd16") == 1234 and msp.decode([0x0012, 0x3456], "bcd32") == 123456
    assert msp.decode([0x12A4], "bcd16") is None
    assert msp.decode([0x0041, 0x0042, 0x0000], "str", chars="low") == "AB"
    assert msp.decode([0x4100, 0x4200], "str", chars="high") == "AB"


def test_datetime_layouts():
    packed = {"year": {"register": 0, "bits": [8, 15], "offset": 2000}, "month": {"register": 0, "bits": [0, 7]},
              "day": {"register": 1, "bits": [8, 15]}, "hour": {"register": 1, "bits": [0, 7]},
              "minute": {"register": 2, "bits": [8, 15]}, "second": {"register": 2, "bits": [0, 7]}}
    assert msp.datetime_of([0x1A0A, 0x180E, 0x2A05], packed) == "2026-10-24T14:42:05"
    bcd = {"hour": {"register": 0, "bcd": True}, "minute": {"register": 1, "bcd": True}}
    assert msp.datetime_of([0x23, 0x59], bcd) == "23:59"
    spec = device([{"key": "x.clock", "label": "Clock", "table": "holding", "address": 10, "type": "datetime",
                    "length": 3, "datetime": packed}])
    dev = UnitFake({1: {"holding": {10: 0x1A0A, 11: 0x180E, 12: 0x2A05}}})
    assert msp.read_device(spec, dev)["values"]["x.clock"] == "2026-10-24T14:42:05"


def test_derived_values_and_negated_scale_factor():
    spec = device(
        [{"key": "x.import_power", "label": "In", "table": "input", "address": 0, "type": "u16", "unit": "W"},
         {"key": "x.export_power", "label": "Out", "table": "input", "address": 1, "type": "u16", "unit": "W"},
         {"key": "x.energy_mwh", "label": "MWh", "table": "input", "address": 2, "type": "u16", "unit": "kWh",
          "scale": 1000},
         {"key": "x.energy_kwh", "label": "kWh", "table": "input", "address": 3, "type": "u16", "unit": "kWh"},
         {"key": "x.lg_power", "label": "P", "table": "input", "address": 4, "type": "s16", "unit": "W",
          "scale_exponent_from": {"table": "input", "address": 5, "type": "s16", "negate": True}}],
        derived=[{"key": "grid_power", "label": "Grid", "unit": "W", "positive": "import",
                  "sum": [{"key": "x.import_power"}, {"key": "x.export_power", "factor": -1}]},
                 {"key": "grid_import_energy", "label": "Import", "unit": "kWh",
                  "sum": [{"key": "x.energy_mwh"}, {"key": "x.energy_kwh"}]}])
    dev = UnitFake({1: {"input": {0: 200, 1: 1500, 2: 12, 3: 345, 4: 1234, 5: 1}}})
    v = msp.read_device(spec, dev)["values"]
    assert v["grid_power"] == 1300  # 1300 W exported: + = export in the vocabulary
    assert v["grid_import_energy"] == 12345
    assert v["x.lg_power"] == 123.4  # LG divides by 10^SF


def test_points_on_another_unit_id():
    spec = device([{"key": "x.a", "label": "A", "table": "holding", "address": 1, "type": "u16"},
                   {"key": "x.b", "label": "B", "table": "holding", "address": 1, "type": "u16", "unit_id": 50}])
    dev = UnitFake({1: {"holding": {1: 7}}, 50: {"holding": {1: 9}}})
    assert msp.read_device(spec, dev)["values"] == {"x.a": 7, "x.b": 9}


def test_problem_conditions_on_ranges_and_text():
    spec = device([{"key": "state", "label": "S", "table": "holding", "address": 0, "type": "u16"},
                   {"key": "x.mode3", "label": "M", "table": "holding", "address": 1, "type": "str", "length": 1}],
                  problems=[{"when": {"key": "state", "range": [200, 299]}, "kind": "fault", "text": "Error {value}"},
                            {"when": {"key": "x.mode3", "prefix": "F"}, "kind": "fault", "text": "State {value}"}])
    dev = UnitFake({1: {"holding": {0: 205, 1: 0x4631}}})
    assert msp.read_device(spec, dev)["problems"] == [{"kind": "fault", "text": "Error 205"},
                                                      {"kind": "fault", "text": "State F1"}]


def test_printable_model_match():
    spec = device([{"key": "x.name", "label": "N", "table": "holding", "address": 0, "type": "str", "length": 2}],
                  models=[{"id": "named", "name": "Named",
                           "match": {"table": "holding", "address": 0, "type": "str", "length": 2, "printable": True}},
                          {"id": "other", "name": "Other"}])
    assert msp.read_device(spec, UnitFake({1: {"holding": {0: 0x5543, 1: 0x4D00}}}))["model"] == "named"
    assert msp.read_device(spec, UnitFake({1: {"holding": {0: 0x0102, 1: 0}}}))["model"] == "other"


def test_bcd64_and_signed_bit_fields():
    assert msp.decode([0x0000, 0x1234, 0x5678, 0x9012], "bcd64") == 123456789012
    spec = device([{"key": "x.setpoint_low", "label": "Low", "table": "input", "address": 0, "type": "u16",
                    "bits": [0, 7], "signed": True, "unit": "°C"},
                   {"key": "x.setpoint_high", "label": "High", "table": "input", "address": 0, "type": "u16",
                    "bits": [8, 15], "signed": True, "unit": "°C"}])
    assert msp.read_device(spec, UnitFake({1: {"input": {0: 0x1EF6}}}))["values"] == {"x.setpoint_low": -10,
                                                                                      "x.setpoint_high": 30}


def test_decimal_time_parts_and_epoch_counters():
    hhmm = {"hour": {"register": 0, "div": 100}, "minute": {"register": 0, "mod": 100}}
    assert msp.datetime_of([1435], hhmm) == "14:35"
    spec = device([{"key": "x.unix", "label": "T", "table": "input", "address": 0, "type": "u32",
                    "epoch": {"start": "1970-01-01", "unit": "s"}},
                   {"key": "x.battery_date", "label": "D", "table": "input", "address": 2, "type": "u16",
                    "epoch": {"start": "2000-01-01", "unit": "d"}}])
    v = msp.read_device(spec, UnitFake({1: {"input": {0: 0x6A1A, 1: 0x5E40, 2: 9793}}}))["values"]
    assert v == {"x.unix": "2026-05-30T03:49:20", "x.battery_date": "2026-10-24T00:00:00"}


def test_optional_derived_terms_and_not_conditions():
    spec = device([{"key": "x.mppt1", "label": "1", "table": "input", "address": 0, "type": "u16", "unit": "W"},
                   {"key": "x.mppt2", "label": "2", "table": "input", "address": 1, "type": "u16", "unit": "W",
                    "invalid": [65535]},
                   {"key": "x.code", "label": "C", "table": "input", "address": 2, "type": "u16"}],
                  derived=[{"key": "pv_power", "label": "PV", "unit": "W",
                            "sum": [{"key": "x.mppt1"}, {"key": "x.mppt2", "optional": True}]}],
                  models=[{"id": "storage", "name": "S",
                           "match": {"table": "input", "address": 2, "type": "u16", "range": [1, 9], "not": 3}},
                          {"id": "other", "name": "O"}])
    v = msp.read_device(spec, UnitFake({1: {"input": {0: 500, 1: 65535, 2: 3}}}))
    assert v["values"]["pv_power"] == 500 and v["model"] == "other"



def test_nan_float_is_not_available():
    spec = device([{"key": "x.a", "label": "A", "table": "input", "address": 0, "type": "f32", "unit": "W"},
                   {"key": "x.b", "label": "B", "table": "input", "address": 2, "type": "f32", "unit": "W"}])
    v = msp.read_device(spec, UnitFake({1: {"input": {0: 0x7FC0, 1: 0, 2: 0x4120, 3: 0}}}))["values"]
    assert v == {"x.b": 10.0}

class Recorder(UnitFake):
    """UnitFake that records requests; `refuse` = blocks it only answers whole, `silent` = addresses that time out."""

    def __init__(self, units, refuse=(), silent=()):
        super().__init__(units)
        self.requests, self.refuse, self.silent = [], refuse, silent

    def read(self, table, address, count, unit=1):
        self.requests.append((table, address, count))
        if any(address <= s < address + count for s in self.silent):
            raise TimeoutError("timed out")
        for t, a, n in self.refuse:
            if t == table and a <= address < a + n and (address, count) != (a, n):
                raise IOError("Modbus exception 2")
        return super().read(table, address, count, unit)


def test_fixed_blocks_are_read_whole():
    regs = {a: 0x4141 for a in range(100, 127)}
    spec = device([{"key": "x.order", "label": "Order", "table": "holding", "address": 102, "type": "str",
                    "length": 4}],
                  connection={"default_port": 502, "default_unit": 1,
                              "blocks": [{"table": "holding", "address": 100, "count": 27}]})
    dev = Recorder({1: {"holding": regs}}, refuse=[("holding", 100, 27)])
    assert msp.read_device(spec, dev)["values"] == {"x.order": "AAAAAAAA"}
    assert dev.requests == [("holding", 100, 27)]


def test_optional_points_are_read_alone():
    spec = device([{"key": "x.a", "label": "A", "table": "holding", "address": 0, "type": "u16"},
                   {"key": "x.sensor", "label": "S", "table": "holding", "address": 1, "type": "s16",
                    "optional": True},
                   {"key": "x.b", "label": "B", "table": "holding", "address": 2, "type": "u16"}],
                  connection={"default_port": 502, "default_unit": 1, "limits": {"max_gap": 10}})
    dev = Recorder({1: {"holding": {0: 1, 1: 5, 2: 2}}}, silent=[1])
    assert msp.read_device(spec, dev)["values"] == {"x.a": 1, "x.b": 2}
    assert ("holding", 1, 1) in dev.requests and ("holding", 0, 3) not in dev.requests


def test_byte_and_word_order_detection():
    spec = device([{"key": "x.e", "label": "E", "table": "holding", "address": 0, "type": "u32"}],
                  encoding={"word_order": "detect", "byte_order": "detect",
                            "detect": {"table": "holding", "address": 4, "type": "u32", "in": [0x310033]}})
    swapped = lambda w: (w >> 8) | ((w & 0xFF) << 8)  # noqa: E731
    r = msp.read_device(spec, UnitFake({1: {"holding": {0: swapped(2), 1: swapped(1), 4: 0x3300, 5: 0x3100}}}))
    assert (r["word_order"], r["byte_order"], r["values"]["x.e"]) == ("little", "little", 0x10002)
    r = msp.read_device(spec, UnitFake({1: {"holding": {0: 1, 1: 2, 4: 0x31, 5: 0x33}}}))
    assert (r["word_order"], r["byte_order"], r["values"]["x.e"]) == ("big", "big", 0x10002)


def test_match_lists_answers_and_user_model_choice():
    models = [{"id": "island", "name": "I", "match_any": [{"table": "holding", "address": 5, "type": "u16",
                                                           "answers": True},
                                                          {"table": "holding", "address": 0, "type": "u16",
                                                           "equals": 7}]},
              {"id": "map2", "name": "M2", "match": [{"table": "holding", "address": 0, "type": "u16",
                                                      "range": [1, 9]},
                                                     {"table": "holding", "address": 1, "type": "u16", "equals": 0}]},
              {"id": "map1", "name": "M1"}]
    pts = [{"key": "x.a", "label": "A", "table": "holding", "address": 0, "type": "u16"},
           {"key": "x.b", "label": "B", "table": "holding", "address": 1, "type": "u16", "models": ["map2"]}]
    spec = device(pts, models=models)
    assert msp.read_device(spec, UnitFake({1: {"holding": {0: 3, 1: 0, 5: 1}}}))["model"] == "island"
    assert msp.read_device(spec, UnitFake({1: {"holding": {0: 3, 1: 0}}}))["model"] == "map2"
    assert msp.read_device(spec, UnitFake({1: {"holding": {0: 7, 1: 0}}}))["model"] == "island"
    assert msp.read_device(spec, UnitFake({1: {"holding": {0: 3, 1: 4}}}))["model"] == "map1"
    user = device(pts, models=models, model_choice="user")
    r = msp.read_device(user, UnitFake({1: {"holding": {0: 3, 1: 0, 5: 1}}}))
    assert r["model"] is None and r["values"] == {"x.a": 3}
    assert msp.read_device(user, UnitFake({1: {"holding": {0: 3, 1: 0}}}), "map2")["values"] == {"x.a": 3, "x.b": 0}


def test_first_present_term_and_sleeping_devices():
    spec = device([{"key": "x.grid", "label": "G", "table": "holding", "address": 0, "type": "s16", "unit": "W"},
                   {"key": "x.export", "label": "E", "table": "holding", "address": 9, "type": "u16", "unit": "W"}],
                  derived=[{"key": "grid_power", "label": "Grid", "unit": "W", "positive": "import",
                            "first": [{"key": "x.grid"}, {"key": "x.export", "factor": -1}]}],
                  connection={"default_port": 502, "default_unit": 1, "sleeps": True})
    assert msp.read_device(spec, UnitFake({1: {"holding": {0: 300, 9: 50}}}))["values"]["grid_power"] == -300
    assert msp.read_device(spec, UnitFake({1: {"holding": {9: 50}}}))["values"]["grid_power"] == 50
    r = msp.read_device(spec, UnitFake({1: {"holding": {}}}))
    assert r["asleep"] is True and r["values"] == {}


def test_word_order_stated_in_a_register():
    spec = device([{"key": "x.e", "label": "E", "table": "holding", "address": 0, "type": "u32"}],
                  encoding={"word_order": "detect",
                            "detect": {"table": "holding", "address": 5, "type": "u16",
                                       "word_orders": {"0": "little", "1": "big"}}})
    r = msp.read_device(spec, UnitFake({1: {"holding": {0: 2, 1: 1, 5: 0}}}))
    assert (r["word_order"], r["values"]["x.e"]) == ("little", 0x10002)
    r = msp.read_device(spec, UnitFake({1: {"holding": {0: 1, 1: 2, 5: 1}}}))
    assert (r["word_order"], r["values"]["x.e"]) == ("big", 0x10002)


def test_identify_with_groups_and_not_answering_registers():
    spec = device([{"key": "x.a", "label": "A", "table": "input", "address": 0, "type": "s16"}],
                  identify={"checks": [[{"table": "input", "address": 0, "type": "s16", "range": [-600, 800]},
                                        {"table": "input", "address": 0, "type": "s16", "equals": -32768}]],
                            "any": [{"table": "input", "address": 9, "type": "u16", "in": [390, 391]},
                                    {"table": "input", "address": 9, "type": "u16", "answers": False}]})
    img = lambda regs: msp.Image({"input": regs})  # noqa: E731
    assert msp.identifies(spec, img({0: 200, 9: 390}), "big")
    assert msp.identifies(spec, img({0: 0x8000}), "big")
    assert not msp.identifies(spec, img({0: 900}), "big")
    assert not msp.identifies(spec, img({0: 200, 9: 7}), "big")


def test_lg_hbc_battery():
    spec = msp.load(msp.ROOT / "devices/battery/lg/hbc.yaml")
    regs = {a: 0 for a in list(range(101, 122)) + list(range(201, 254)) + list(range(2001, 2026))}
    regs.update({101: 0x8123, 102: 0x4567, 103: 4, 104: 0x0005, 105: 0x2E31, 106: 0x3030, 107: 15000,
                 201: 3, 202: (-1500) & 0xFFFF, 203: 38900, 204: 16950, 209: 4486, 210: 4006,
                 214: (-334) & 0xFFFF, 215: 126, 216: (-450) & 0xFFFF, 219: 436, 221: 3813, 222: 4074, 247: 740})
    dev = UnitFake({15: {"holding": regs}})
    dev.read = lambda table, address, count, unit=15, _r=dev.read: _r(table, address, count, unit)
    r = msp.read_device(spec, dev)
    v = r["values"]
    assert msp.identifies(spec, msp.Image({"holding": regs}), "big")
    assert v["state.text"] == "Run" and v["battery_power"] == 1500 and v["battery_current"] == 33.4
    assert v["battery_voltage"] == 448.6 and v["battery_soc"] == 43.6 and v["x.firmware_build"] == ".100"
    assert (v["x.firmware_major"], v["x.firmware_minor"], v["x.firmware_patch"]) == (4, 0, 5)
    assert "x.temperature_216" not in v and v["x.min_cell_voltage"] == 3.813
    assert r["problems"] == [{"kind": "fault", "text": "Battery fault B740: Cell voltage imbalance"}]


def test_no_unknown_identify_collisions():
    """A search must tell devices apart: only the overlaps listed (with a reason) in identify_overlaps.yaml."""
    import collisions
    import yaml
    known = yaml.safe_load((Path(__file__).parent / "identify_overlaps.yaml").read_text(encoding="utf-8"))
    allowed = {(a, b) for o in known for a in o["devices"] for b in o["devices"] if a != b and
               (not o.get("one_way") or a == o["devices"][0])}
    found, unsimulated = collisions.collisions(collisions.load_all())
    assert unsimulated == []
    assert sorted(set(found) - allowed) == []
    assert sorted(allowed - set(found)) == [], "listed overlaps that no longer happen: remove them"


def test_identify_rejects_blank_registers():
    """A device answering every register with 0 or FFFFh must not be taken for any device file, except those listed
    (with a reason) in identify_blank.yaml."""
    import yaml

    class Fill(dict):
        def __init__(self, value):
            super().__init__()
            self.value = value

        def get(self, key, default=None):
            return self.value

    known = yaml.safe_load((Path(__file__).parent / "identify_blank.yaml").read_text(encoding="utf-8"))
    allowed = {(k["device"], f) for k in known for f in k["fills"]}
    found = set()
    for path in DEVICES:
        spec = msp.load(path)
        if not msp.has_identify(spec):
            continue
        name = f"{path.parent.name}/{path.stem}"
        for fill in (0, 0xFFFF):
            img = msp.Image({t: Fill(fill) for t in ("holding", "input", "coil", "discrete")})
            if any(msp.identifies(spec, img, w, b) for w in ("big", "little") for b in ("big", "little")):
                found.add((name, fill))
    assert sorted(found - allowed) == []
    assert sorted(allowed - found) == [], "listed files that no longer accept blank registers: remove them"


@pytest.fixture(scope="module")
def identify_tree():
    import identify_tree as it
    specs = it.load_all()
    return it, specs, it.generate(specs)


def short(name):
    """A file's name as identify_overlaps.yaml and identify_blank.yaml have it: maker/family."""
    return "/".join(name.split("/")[-2:])


def test_identify_tree_file_is_current(identify_tree):
    it, _, tree = identify_tree
    assert json.loads(it.dumps(tree)) == tree
    assert (msp.ROOT / "identify_tree.json").read_text(encoding="utf-8") == it.dumps(tree), \
        "a device file changed: run python3 tools/identify_tree.py --out identify_tree.json"


def test_identify_tree_finds_every_file(identify_tree):
    """A simulated device of every file ends at its own file, or at files listed as taking it for theirs; every file
    named really accepts the registers."""
    import collisions
    import yaml
    it, specs, tree = identify_tree
    known = yaml.safe_load((Path(__file__).parent / "identify_overlaps.yaml").read_text(encoding="utf-8"))
    allowed = {(a, b) for o in known for a in o["devices"] for b in o["devices"] if a != b and
               (not o.get("one_way") or a == o["devices"][0])}
    wrong, others = [], []
    for name, spec in specs.items():
        img = it.simulated_image(spec)
        for root in it.roots_of(spec):
            found, _ = it.walk(tree, root, it.Simulated(img), pace=False)
            wrong += [(root, name, f) for f in found if not collisions.accepts(specs[f], img)]
            if name not in found:
                others += [(root, name, f) for f in found if (short(name), short(f)) not in allowed] or \
                    ([(root, name, None)] if not found else [])
    assert wrong == []
    assert others == []


def test_identify_tree_unknown_devices(identify_tree):
    """A device that answers nothing is unknown; one with blank registers can only be a file known to accept them."""
    import yaml
    it, specs, tree = identify_tree

    class Blank:
        def __init__(self, fill):
            self.fill = fill

        def read(self, table, address, count, unit=None):
            return [self.fill] * count

    allowed = {(k["device"], f) for k in yaml.safe_load(
        (Path(__file__).parent / "identify_blank.yaml").read_text(encoding="utf-8")) for f in k["fills"]}
    for root in tree["roots"]:
        found, requests = it.walk(tree, root, it.Simulated(msp.Image()), pace=False)
        assert found == [] and requests <= len(tree["tests"])
        for fill in (0, 0xFFFF):
            found, _ = it.walk(tree, root, Blank(fill), pace=False)
            assert [f for f in found if (short(f), fill) not in allowed] == []


def small_tree(**files):
    import identify_tree as it
    specs = {name.replace("_", "/"): {"connection": {"default_port": 502, "default_unit": 1, **f.pop("connection", {})},
                                      **f} for name, f in files.items()}
    return it, json.loads(json.dumps(it.generate(specs)))


class CountingDevice:
    def __init__(self, **tables):
        self.tables, self.requests = tables, []

    def read(self, table, address, count, unit=None):
        self.requests.append((table, address, count))
        regs = self.tables.get(table, {})
        if any(a not in regs for a in range(address, address + count)):
            raise IOError("illegal address")
        return [regs[a] for a in range(address, address + count)]


def test_identify_tree_reads_shared_register_once():
    it, tree = small_tree(
        a_x={"identify": {"checks": [{"table": "holding", "address": 0, "type": "u16", "equals": 1000}]}},
        b_x={"identify": {"checks": [{"table": "holding", "address": 0, "type": "u16", "equals": 2000}]}},
        c_x={"identify": {"checks": [{"table": "holding", "address": 0, "type": "u16", "equals": 3000}]}},
        d_x={"identify": {"checks": [{"table": "holding", "address": 9, "type": "u16", "equals": 4000}]}})
    device = CountingDevice(holding={0: 3000})
    assert it.walk(tree, "port:502", device, pace=False)[0] == ["c/x"]
    assert device.requests == [("holding", 0, 1)]


def test_identify_tree_tries_the_more_specific_file_first():
    general = {"table": "holding", "address": 0, "type": "u16", "equals": 1000}
    it, tree = small_tree(
        a_general={"identify": {"checks": [general]}},
        b_specific={"identify": {"checks": [general, {"table": "holding", "address": 5, "type": "u16", "equals": 7000}]}})
    assert it.walk(tree, "port:502", CountingDevice(holding={0: 1000, 5: 7000}), pace=False)[0] == \
        ["b/specific", "a/general"]
    assert it.walk(tree, "port:502", CountingDevice(holding={0: 1000, 5: 1}), pace=False)[0] == ["a/general"]


def test_identify_tree_weak_evidence_waits_for_strong():
    """A plausible value must not win over a device that states who it is."""
    it, tree = small_tree(
        a_weak={"identify": {"checks": [{"table": "input", "address": 70, "type": "u16", "range": [40, 70]}]}},
        b_strong={"identify": {"checks": [{"table": "holding", "address": 0, "type": "str", "length": 2,
                                           "prefix": "ACME"}]}})
    device = CountingDevice(input={70: 50}, holding={0: 0x4143, 1: 0x4D45})  # "ACME"
    assert it.walk(tree, "port:502", device, pace=False)[0] == ["b/strong"]
    assert device.requests == [("holding", 0, 2)]
    assert it.walk(tree, "port:502", CountingDevice(input={70: 50}), pace=False)[0] == ["a/weak"]


def test_identify_tree_tries_weak_files_strongest_first():
    it, tree = small_tree(
        a_loose={"identify": {"checks": [{"table": "holding", "address": 0, "type": "u16", "range": [0, 14]}]}},
        b_code={"identify": {"checks": [{"table": "input", "address": 11, "type": "u16", "in": [71, 72, 73]}]}})
    device = CountingDevice(holding={0: 0}, input={11: 72})
    assert it.walk(tree, "port:502", device, pace=False)[0] == ["b/code"]
    assert it.walk(tree, "port:502", CountingDevice(holding={0: 0}, input={11: 5}), pace=False)[0] == ["a/loose"]


def test_identify_tree_on_a_real_em24(identify_tree):
    """A real Carlo Gavazzi EM24-DIN AV5, as read on 2026-10-31: its model code at input 11, also answered at holding
    11, passed the loose checks of other files while holding 0 and 3 read 0."""
    it, _, tree = identify_tree
    device = CountingDevice(input={11: 72}, holding={0: 0, 3: 0, 7: 0, 11: 72})
    assert it.walk(tree, "serial", device, pace=False)[0] == ["meter/carlogavazzi/em24-din"]


def test_identify_tree_requests_follow_the_connection():
    even = {"limits": {"even_address": True, "min_interval_ms": 200}}
    block = {"blocks": [{"table": "holding", "address": 100, "count": 10}]}
    it, tree = small_tree(
        a_even={"connection": even, "identify": {"checks": [{"table": "input", "address": 7, "type": "u16", "equals": 1000}]}},
        b_block={"connection": block, "identify": {"checks": [{"table": "holding", "address": 104, "type": "u16", "equals": 2000}]}},
        c_unit={"identify": {"checks": [{"table": "holding", "address": 3, "unit_id": 50, "type": "u16", "equals": 3000}]}})
    reads = {it.request_key(r): r for t in tree["tests"] for r in t["reads"]}
    assert reads[("input", 6, 2, None)]["min_interval_ms"] == 200
    assert ("holding", 100, 10, None) in reads and ("holding", 3, 1, 50) in reads


def test_identify_tree_detects_the_register_order():
    def spec(value):
        return {"encoding": {"word_order": "detect", "detect": {"table": "holding", "address": 0, "type": "f32",
                                                                "plausible": [40, 70]}},
                "identify": {"checks": [{"table": "holding", "address": 10, "type": "u32", "equals": value}]}}
    it, tree = small_tree(a_x=spec(0x00010002))
    assert it.walk(tree, "port:502", CountingDevice(holding={**dict(enumerate(f32(50))), 10: 1, 11: 2}), pace=False)[0] == ["a/x"]
    little = {**dict(enumerate(f32(50, "little"))), 10: 2, 11: 1}
    assert it.walk(tree, "port:502", CountingDevice(holding=little), pace=False)[0] == ["a/x"]
    assert it.walk(tree, "port:502", CountingDevice(holding={**little, 10: 1, 11: 2}), pace=False)[0] == []


def test_identify_tree_sends_serial_devices_to_their_own_root():
    import identify_tree as it
    both = {"default_port": 502, "default_unit": 1, "transports": ["tcp", "rtu"]}
    assert it.roots_of({"connection": both}) == ["port:502", "serial"]
    assert it.roots_of({"connection": {**both, "transports": ["tcp"]}}) == ["port:502"]
    assert it.roots_of({"connection": {"default_port": 1502, "default_unit": 1}}) == ["port:1502"]


def test_fronius_smart_meter_ts():
    """Numbers from a published sniff, with the inverter's own readings: low word first, energy in whole units and the rest."""
    def words(v):
        return [v & 0xFFFF, (v >> 16) & 0xFFFF]
    spec = msp.load(msp.ROOT / "devices/meter/fronius/smart-meter-ts.yaml")
    holding = {a: 0 for p in spec["points"] if p["table"] == "holding" for a in range(p["address"], p["address"] + msp.registers(p))}
    put(holding, 0x0120, words(2370) + words(1157) + words(2066))
    put(holding, 0x0130, words(-418))
    put(holding, 0x0400, words(987) + words(340))
    inputs = {a: 0 for p in spec["points"] if p["table"] == "input" for a in range(p["address"], p["address"] + msp.registers(p))}
    inputs[11] = 731
    device = FakeDevice(holding=holding, input=inputs)
    v = msp.read_device(spec, device)["values"]
    assert v["l1_voltage"] == pytest.approx(237.0) and v["l1_current"] == pytest.approx(1.157)
    assert v["l2_current"] == pytest.approx(-0.418)
    assert v["grid_import_energy"] * 1000 + v["x.import_energy_rest"] == 987340  # the inverter's EnergyReal_WAC_Plus_Absolute
    assert ("input", 11, 1) in device.requests  # the model code alone: in a block it reads 0
    assert msp.identifies(spec, msp.Image({"input": {11: 731}}), "little")
    assert not msp.identifies(spec, msp.Image({"input": {11: 72}}), "little")


def test_edgetech_evse_c():
    """State and errors share a register, currents are in 1/256 A, and no read touches the registers that may act."""
    spec = msp.load(msp.ROOT / "devices/charger/edgetech/evse-c.yaml")
    inputs = {a: 0 for a in [*range(0, 6), 0x10, *range(0x100, 0x114)]}
    inputs[0x103] = 0x0403                                      # ground fault, state C
    inputs[0x105] = 0x086A                                      # 8.414 A in the document's example
    inputs[0x10D], inputs[0x10E] = 0x0100, 0x0001               # low word first
    device = FakeDevice(input=inputs, holding={a: 0 for a in [0x200, 0x201, 0x204, 0x205, 0x207, 0x208, 0x209, 0x20A]})
    r = msp.read_device(spec, device)
    assert r["values"]["state"] == 3
    assert r["values"]["l1_current"] == pytest.approx(8.4140625)
    assert r["values"]["consumer_energy"] == pytest.approx(0x00010100 / 256)
    assert r["problems"] == [{"kind": "fault", "text": "Ground fault (error bit 2)"}]
    acting = {0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x11, 0x12, 0x15, 0x16, 0x17}
    assert not [q for q in device.requests if q[0] == "input" and acting & set(range(q[1], q[1] + q[2]))]


def test_sunspec_marker_is_read_big_endian():
    spec = msp.load(msp.ROOT / "devices/inverter/kostal/plenticore.yaml")
    regs = {5: 0}  # MODBUS Byte Order: 0 = CDAB, the factory setting
    put(regs, 40000, [0x5375, 0x6E53])
    put(regs, 40004, [0x4B4F, 0x5354, 0x414C] + [0] * 13)                                   # "KOSTAL"
    put(regs, 40020, [0x504C, 0x454E, 0x5449, 0x434F, 0x5245, 0x2070, 0x6C75, 0x7300] + [0] * 8)  # "PLENTICORE plus"
    img = msp.Image({"holding": regs})
    word, byte = msp.detect_orders(spec, img)
    assert word == "little" and msp.identifies(spec, img, word, byte)
    broken = {**spec, "identify": {"checks": [{"table": "holding", "address": 40000, "type": "u32",
                                               "equals": 0x53756E53}]}}
    assert any("SunSpec marker" in e for e in msp.validate(broken))


def test_half_floats_and_texts_longer_than_one_request():
    assert msp.decode([0x3C00], "f16") == 1.0 and msp.decode([0xC500], "f16") == -5.0
    text = "SN-0123456789AB"
    words = list(struct.unpack(">8H", text.encode().ljust(16, b"\0")))
    spec = device([{"key": "x.v", "label": "V", "table": "holding", "address": 0, "type": "f16", "unit": "V"},
                   {"key": "serial", "label": "S", "table": "holding", "address": 10, "type": "str", "length": 8}],
                  connection={"default_port": 502, "default_unit": 1, "limits": {"max_registers": 3}})
    regs = {0: 0x4E40}  # 25.0
    put(regs, 10, words)
    dev = Recorder({1: {"holding": regs}})
    v = msp.read_device(spec, dev)["values"]
    assert v == {"x.v": 25.0, "serial": text}
    assert all(n <= 3 for _, _, n in dev.requests)


class WriteFake(UnitFake):
    """UnitFake that records writes and applies them (holding and coils)."""

    def __init__(self, units):
        super().__init__(units)
        self.writes = []

    def write(self, table, address, values, unit=None, multiple=False):
        self.writes.append((table, address, list(values), multiple))
        t = self.units[unit or 1].setdefault(table, {})
        for i, v in enumerate(values):
            t[address + i] = v
        if table == "holding":  # the fake's input table mirrors holding (read 04, write 06)
            self.units[unit or 1].setdefault("input", {}).update({address + i: v for i, v in enumerate(values)})


@pytest.mark.parametrize("value,type_,order", [
    (-5, "s16", "big"), (65535, "u16", "big"), (-123456, "s32", "little"), (2 ** 40, "u64", "big"),
    (-7, "sm16", "big"), (-70000, "sm32", "little"), (1234, "bcd16", "big"), (12345678, "bcd32", "big"),
    (1.5, "f16", "big"), (230.25, "f32", "little"), (-0.125, "f64", "big")])
def test_encode_is_the_inverse_of_decode(value, type_, order):
    assert msp.decode(msp.encode(value, type_, order), type_, order) == value
    assert msp.decode(msp.encode(value, type_, order, "little"), type_, order, "little") == value


def test_encode_text_and_refuses_what_does_not_fit():
    assert msp.decode(msp.encode("AB-1", "str", length=3), "str") == "AB-1"
    assert msp.encode("AB", "str", chars="low", length=3) == [0x41, 0x42, 0]
    for value, type_ in ((70000, "u16"), (-1, "u16"), (12345, "bcd16"), (-1, "bcd16"), (40000, "sm16")):
        with pytest.raises(ValueError):
            msp.encode(value, type_)
    with pytest.raises(ValueError):
        msp.encode("ABCDEFG", "str", length=3)


def test_write_scale_sign_enum_and_read_back():
    spec = device([{"key": "grid_power", "label": "P", "table": "holding", "address": 0, "type": "s16", "unit": "W",
                    "scale": 10, "positive": "import", "writable": True},
                   {"key": "x.mode", "label": "M", "table": "holding", "address": 1, "type": "u16", "enum": "mode",
                    "writable": True},
                   {"key": "x.current", "label": "I", "table": "holding", "address": 2, "type": "u16", "unit": "A",
                    "scale": 0.1, "min": 6, "max": 32, "writable": True, "persistent": False}],
                  enums={"mode": {"0": "Off", "1": "Auto", "17": "Time of use"}})
    fake = WriteFake({1: {"holding": {0: 0, 1: 0, 2: 0}}})
    out = msp.write_point(spec, fake, "grid_power", 500)  # vocabulary: + = export; the device's + = import
    assert fake.writes[-1] == ("holding", 0, [0xFFCE], False) and out["value"] == 500
    msp.write_point(spec, fake, "x.mode", "time of use")
    assert fake.writes[-1][2] == [17]
    assert msp.write_point(spec, fake, "x.current", 16.5)["written"] == [165]
    special = device([{"key": "x.set", "label": "S", "table": "holding", "address": 0, "type": "s16", "unit": "°C",
                       "scale": 0.1, "invalid": [-32768], "writable": True, "min": 5, "max": 50}])
    assert msp.write_point(special, WriteFake({1: {"holding": {0: 0}}}), "x.set", -3276.8)["written"] == [0x8000]
    for key, value in (("x.mode", 5), ("x.mode", "Manual"), ("x.current", 40), ("x.current", 16.55)):
        with pytest.raises(ValueError):
            msp.write_point(spec, fake, key, value)


def test_write_bits_keep_the_rest_of_the_register():
    spec = device([{"key": "x.flag", "label": "F", "table": "holding", "address": 0, "type": "u16", "bits": [4, 6],
                    "writable": True}])
    fake = WriteFake({1: {"holding": {0: 0xF00F}}})
    msp.write_point(spec, fake, "x.flag", 5)
    assert fake.units[1]["holding"][0] == 0xF05F
    with pytest.raises(ValueError):
        msp.write_point(spec, fake, "x.flag", 8)
    cmd = device([{"key": "x.start", "label": "S", "table": "holding", "address": 0, "type": "u16", "bits": [1, 1],
                   "writable": True, "write_only": True}])
    fake = WriteFake({1: {"holding": {}}})  # nothing to read: the register can't be read back
    assert msp.write_point(cmd, fake, "x.start", 1) == {"key": "x.start", "written": [2], "value": None}


def test_write_functions_tables_and_write_only():
    spec = device([{"key": "x.set", "label": "S", "table": "input", "address": 3, "type": "u16", "writable": True},
                   {"key": "x.limit", "label": "L", "table": "holding", "address": 10, "type": "u32", "writable": True,
                    "write_only": True},
                   {"key": "x.relay", "label": "R", "table": "coil", "address": 2, "type": "bool", "writable": True},
                   {"key": "x.clock", "label": "C", "table": "holding", "address": 20, "type": "u16", "writable": True,
                    "write_address": 30, "write_multiple": True},
                   {"key": "x.state", "label": "St", "table": "input", "address": 0, "type": "u16"}])
    fake = WriteFake({1: {"holding": {}, "input": {0: 1, 3: 0}, "coil": {2: 0}}})
    assert msp.write_point(spec, fake, "x.set", 7)["value"] == 7  # read with 04, written with 06 at the same address
    assert fake.writes[-1] == ("holding", 3, [7], False)
    assert msp.write_point(spec, fake, "x.limit", 70000) == {"key": "x.limit", "written": [1, 4464], "value": None}
    msp.write_point(spec, fake, "x.relay", True)
    assert fake.writes[-1] == ("coil", 2, [1], False)
    fake.units[1]["holding"][20] = 0
    msp.write_point(spec, fake, "x.clock", 9)
    assert fake.writes[-1] == ("holding", 30, [9], True)
    with pytest.raises(ValueError):
        msp.write_point(spec, fake, "x.state", 2)  # not writable
    single = device([{"key": "x.ratio", "label": "R", "table": "input", "address": 0x1003, "type": "u32",
                      "writable": True}], connection={"default_port": 502, "default_unit": 1, "write_single": True},
                    encoding={"word_order": "little"})
    fake = WriteFake({1: {"holding": {}, "input": {}}})
    msp.write_point(single, fake, "x.ratio", 9990)
    assert fake.writes == [("holding", 0x1003, [9990], False), ("holding", 0x1004, [0], False)]


def test_write_datetime_and_scale_exponent():
    spec = device([{"key": "x.clock", "label": "C", "table": "holding", "address": 0, "type": "datetime", "length": 2,
                    "writable": True, "datetime": {"year": {"register": 0, "bits": [8, 15], "offset": 2000},
                                                   "month": {"register": 0, "bits": [0, 7]},
                                                   "hour": {"register": 1, "div": 100},
                                                   "minute": {"register": 1, "mod": 100}}},
                   {"key": "x.limit", "label": "W", "table": "holding", "address": 5, "type": "u16", "unit": "W",
                    "scale_exponent_from": {"table": "holding", "address": 6, "type": "s16"}, "writable": True}])
    fake = WriteFake({1: {"holding": {0: 0, 1: 0, 5: 0, 6: 0xFFFF}}})  # exponent −1: raw × 0.1
    assert msp.write_point(spec, fake, "x.clock", "2026-10-25T14:42")["written"] == [(26 << 8) | 10, 1442]
    assert msp.write_point(spec, fake, "x.limit", 1500.5)["written"] == [15005]
    with pytest.raises(ValueError):
        msp.write_point(spec, fake, "x.clock", "14:42")  # the layout needs the year and month too


def test_write_keys_need_writable_and_discrete_is_read_only():
    base = {"modbusspec": 0, "id": "acme-x", "manufacturer": "Acme", "name": "X", "kind": "meter",
            "sources": [{"title": "t"}], "connection": {"default_port": 502, "default_unit": 1}}
    bad = [{"key": "x.a", "label": "A", "table": "holding", "address": 0, "type": "u16", "min": 1},
           {"key": "x.b", "label": "B", "table": "discrete", "address": 0, "type": "bool", "writable": True},
           {"key": "x.c", "label": "C", "table": "holding", "address": 1, "type": "u16", "writable": True, "min": 5,
            "max": 1}]
    errors = msp.validate({**base, "points": bad})
    assert any("min needs writable" in e for e in errors) and any("can't be written" in e for e in errors) and \
        any("min above max" in e for e in errors)


def test_points_may_not_read_reserved_registers():
    base = {"modbusspec": 0, "id": "acme-x", "manufacturer": "Acme", "name": "X", "kind": "meter",
            "sources": [{"title": "t"}], "connection": {"default_port": 502, "default_unit": 1},
            "reserved": [{"table": "holding", "address": 10, "count": 2}, {"table": "holding", "address": 20, "bits": [3, 4]}]}
    ok = [{"key": "x.word", "label": "W", "table": "holding", "address": 20, "type": "u16"},
          {"key": "x.bit", "label": "B", "table": "holding", "address": 20, "type": "u16", "bits": [5, 5]},
          {"key": "x.next", "label": "N", "table": "holding", "address": 12, "type": "u16"}]
    assert msp.validate({**base, "points": ok}) == []
    bad = [{"key": "x.long", "label": "L", "table": "holding", "address": 9, "type": "u32"},
           {"key": "x.bit", "label": "B", "table": "holding", "address": 20, "type": "u16", "bits": [4, 4]}]
    assert len([e for e in msp.validate({**base, "points": bad}) if "reserved" in e]) == 2


def test_crc16_and_rtu_reply_check():
    # the textbook example: read 10 holding registers from 0 on unit 1 → CRC C5 CD on the wire
    assert struct.pack("<H", msp.crc16(bytes.fromhex("01030000000A"))) == bytes.fromhex("C5CD")
    reply = bytes.fromhex("0103020007")
    frame = reply + struct.pack("<H", msp.crc16(reply))
    assert msp.check_rtu(frame, 1) == bytes.fromhex("03020007")
    with pytest.raises(IOError):
        msp.check_rtu(frame[:-1] + b"\x00", 1)


class FakeServer:
    """A device on 127.0.0.1 answering reads of holding registers (value = address) over UDP or TCP, framed as
    Modbus TCP or RTU; `drop` datagrams are ignored first (lost packets), `prefix` goes before each RTU reply."""

    def __init__(self, kind: str, rtu: bool, prefix: bytes = b"", drop: int = 0):
        import threading
        self.rtu, self.prefix, self.drop = rtu, prefix, drop
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM if kind == "udp" else socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        if kind == "tcp":
            self.sock.listen(1)
        threading.Thread(target=self.serve_udp if kind == "udp" else self.serve_tcp, daemon=True).start()

    def answer(self, data: bytes) -> bytes:
        if self.rtu:
            unit, pdu = data[0], data[1:-2]
        else:
            tid, unit, pdu = data[:2], data[6], data[7:]
        fc, address, count = struct.unpack(">BHH", pdu[:5])
        body = bytes([fc, 2 * count]) + b"".join(struct.pack(">H", address + i) for i in range(count))
        if self.rtu:
            frame = bytes([unit]) + body
            return self.prefix + frame + struct.pack("<H", msp.crc16(frame))
        return tid + struct.pack(">HHB", 0, len(body) + 1, unit) + body

    def serve_udp(self):
        while True:
            data, peer = self.sock.recvfrom(1024)
            if self.drop:
                self.drop -= 1
                continue
            self.sock.sendto(self.answer(data), peer)

    def serve_tcp(self):
        conn, _ = self.sock.accept()
        while True:
            data = conn.recv(1024)
            if not data:
                return
            conn.sendall(self.answer(data))



def test_udp_and_rtu_framed_clients():
    udp = FakeServer("udp", rtu=False, drop=1)  # one lost datagram: sent again after the timeout
    assert msp.ModbusUdp("127.0.0.1", udp.port, 1, timeout=0.2).read("holding", 100, 3) == [100, 101, 102]
    goodwe = FakeServer("udp", rtu=True, prefix=bytes.fromhex("AA55"))
    client = msp.ModbusRtuOverUdp("127.0.0.1", goodwe.port, 247, timeout=0.5, reply_prefix=bytes.fromhex("AA55"))
    assert client.read("holding", 35100, 2) == [35100, 35101]
    gateway = FakeServer("tcp", rtu=True)
    assert msp.ModbusRtuOverTcp("127.0.0.1", gateway.port, 1).read("holding", 7, 2) == [7, 8]


def test_connect_picks_transport_and_port():
    spec = device([{"key": "x.a", "label": "A", "table": "holding", "address": 0, "type": "u16"}],
                  connection={"default_port": 502, "default_unit": 247, "transports": ["rtu_over_udp", "tcp"],
                              "ports": {"rtu_over_udp": 8899}, "reply_prefix": "AA55"})
    server = FakeServer("udp", rtu=True, prefix=bytes.fromhex("AA55"))
    spec["connection"]["ports"]["rtu_over_udp"] = server.port
    client = msp.connect(spec, "127.0.0.1")
    assert isinstance(client, msp.ModbusRtuOverUdp) and client.read("holding", 0, 1) == [0]
    bad = dict(spec, connection={"default_port": 502, "default_unit": 1, "transports": ["tcp"],
                                 "ports": {"udp": 9}, "reply_prefix": "AA55"})
    errors = msp.validate(bad)
    assert any("ports.udp" in e for e in errors) and any("reply_prefix" in e for e in errors)


TLS = Path(__file__).resolve().parent / "tls"


class TlsServer:
    """A Modbus/TCP Security device on 127.0.0.1 that requires a client certificate from the test CA and answers
    reads of holding registers (value = address)."""

    def __init__(self):
        import ssl
        import threading
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(TLS / "server.pem", TLS / "server.key")
        self.ctx.load_verify_locations(TLS / "ca.pem")
        self.ctx.verify_mode = ssl.CERT_REQUIRED
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.peer_role = None
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        import ssl
        while True:
            raw, _ = self.sock.accept()
            try:
                conn = self.ctx.wrap_socket(raw, server_side=True)
            except (ssl.SSLError, OSError):
                raw.close()
                continue
            cert = conn.getpeercert(binary_form=True)
            self.peer_role = b"Operator" if b"Operator" in cert else None
            data = conn.recv(1024)
            tid, unit, (fc, address, count) = data[:2], data[6], struct.unpack(">BHH", data[7:12])
            body = bytes([fc, 2 * count]) + b"".join(struct.pack(">H", address + i) for i in range(count))
            conn.sendall(tid + struct.pack(">HHB", 0, len(body) + 1, unit) + body)
            conn.close()


def test_tls_client_with_and_without_certificate():
    server = TlsServer()
    client = msp.ModbusTls("127.0.0.1", server.port, 1, cafile=str(TLS / "ca.pem"),
                           certfile=str(TLS / "client.pem"), keyfile=str(TLS / "client.key"))
    assert client.read("holding", 40, 2) == [40, 41] and server.peer_role == b"Operator"
    with pytest.raises(OSError):  # no client certificate: the device refuses the connection
        msp.ModbusTls("127.0.0.1", server.port, 1, cafile=str(TLS / "ca.pem")).read("holding", 0, 1)
    with pytest.raises(ValueError):  # the device can't be checked without its CA
        msp.ModbusTls("127.0.0.1", server.port, 1)


def test_tls_connection_block_and_default_port():
    spec = device([{"key": "x.a", "label": "A", "table": "holding", "address": 0, "type": "u16"}],
                  connection={"default_port": 502, "default_unit": 1, "transports": ["tcp", "tls"],
                              "tls": {"client_certificate": "required", "roles": ["Operator"]}})
    server = TlsServer()
    spec["connection"]["ports"] = {"tls": server.port}
    client = msp.connect(spec, "127.0.0.1", "tls", cafile=str(TLS / "ca.pem"), certfile=str(TLS / "client.pem"),
                         keyfile=str(TLS / "client.key"))
    assert client.read("holding", 5, 1) == [5]
    no_tls = dict(spec, connection={"default_port": 502, "default_unit": 1, "tls": {"client_certificate": "none"}})
    assert any("tls transport" in e for e in msp.validate(no_tls))


def test_device_files_are_edited_by_hand():
    """No generator writes device files any more: a header saying otherwise would stop people editing them."""
    for path in DEVICES:
        assert "Generated by" not in path.read_text(encoding="utf-8"), path


def test_device_files_are_in_the_folder_of_their_kind():
    for path in DEVICES:
        assert path.relative_to(msp.ROOT / "devices").parts[0] == msp.load(path)["kind"], path
