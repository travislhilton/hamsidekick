"""The consolidated band plan (station/consolidate.py + localplans.ingest, owner 2026-11-15): saved plans are read into
segments and channels, merged with the FCC rules and the ARRL band plan, and every disagreement is flagged."""
import json
import threading
import urllib.request

from station import consolidate as C
from station import localplans as LP
from station.server import serve
from tests.test_localplans import _plans
from tests.test_agent import xai_key  # noqa: F401

COORD = {"id": "c", "name": "State coordinator band plan", "authority": "coordinator",
         "segments": [{"from_mhz": 146.61, "to_mhz": 147.39, "use": "FM repeater outputs"},
                      {"from_mhz": 147.42, "to_mhz": 147.57, "use": "FM simplex"},
                      {"from_mhz": 144.9, "to_mhz": 145.1, "use": "Weak signal and SSB"}]}
ARES = {"id": "a", "name": "County ARES plan", "authority": "local",
        "segments": [{"from_mhz": 144.9, "to_mhz": 145.1, "use": "Packet and Winlink"}],
        "frequencies": [{"freq_mhz": 147.0, "mode": "FM", "use": "ARES tactical simplex", "kind": "simplex"}]}


def _rows(t, band):
    return next(b for b in t["bands"] if b["band"] == band)["rows"]


def test_ranges_are_cut_at_every_edge_and_the_coordinator_speaks_first():
    t = C.build("general", [COORD])
    r = next(x for x in _rows(t, "2 m") if x["type"] == "range" and x["from"] <= 147.0 <= x["to"])
    assert r["use"] == "FM repeater outputs" and r["by"] == "State coordinator band plan"
    assert {s["authority"] for s in r["statements"]} == {"coordinator", "arrl", "fcc"} and not r["flags"]
    assert r["privileges"] == {"phone": True, "data": True, "cw": True}
    hf = next(x for x in _rows(t, "40 m") if x["type"] == "range" and x["from"] <= 7.03 <= x["to"])
    assert hf["privileges"]["phone"] is False and hf["privileges"]["cw"] is True      # General: CW/data only there


def test_disagreements_are_flagged_between_plans_and_against_a_range():
    t = C.build("general", [COORD, ARES])
    weak = next(x for x in _rows(t, "2 m") if x["type"] == "range" and x["from"] <= 145.0 <= x["to"])
    assert weak["use"] == "Weak signal and SSB"
    assert any("County ARES plan says “Packet and Winlink”" in f for f in weak["flags"])
    ch = next(x for x in _rows(t, "2 m") if x["type"] == "channel" and x["from"] == 147.0)
    assert any("sets aside for “FM repeater outputs”" in f for f in ch["flags"])
    assert C.differ("FM simplex", "national FM simplex calling frequency") is False
    assert C.differ("repeater outputs", "simplex") is True and C.differ("odd words", "simplex") is False


def test_kept_channels_outside_privileges_are_flagged():
    kept = [{"freq_mhz": 7.05, "mode": "LSB", "use": "Section HF net", "kind": "hf_net"},
            {"freq_mhz": 147.0, "mode": "FM", "offset_mhz": 0.6, "use": "Club repeater", "kind": "repeater"}]
    t = C.build("technician", [], kept)
    hf = next(x for x in _rows(t, "40 m") if x["type"] == "channel" and x["from"] == 7.05)
    assert hf["kept"] and any("outside your privileges" in f for f in hf["flags"])
    vu = next(x for x in _rows(t, "2 m") if x["type"] == "channel" and x["from"] == 147.0)
    assert vu["privileges"] is True and not vu["flags"]
    assert C.lookup(t, 147.0)["channel"]["use"] == "Club repeater"


def test_saved_plans_are_read_and_the_area_table_is_served(tmp_path, xai_key):
    st, p, _, _ = _plans(tmp_path)
    p.extract = lambda key, sys, user: {"segments": COORD["segments"], "frequencies": [
        {"freq_mhz": 147.48, "mode": "FM", "use": "Tactical simplex 1", "kind": "simplex"}]}
    p._text_of = lambda path: "a band plan"
    p.search()
    p.save_copies()                                   # saved, then read
    t = p.consolidated()
    assert t["read"][0]["segments"] == 3 and t["read"][0]["authority"] == "local"     # an ARES plan document
    assert t["read"][0]["channels"] == 1
    assert p.label(147.0)["plan"] == "FM repeater outputs"
    key = t["read"][0]["key"]
    p.set_source(key, authority="coordinator")
    r = next(x for x in _rows(p.consolidated(), "2 m") if x["type"] == "range" and x["from"] <= 147.0 <= x["to"])
    assert r["authority"] == "coordinator"
    p.set_source(key, excluded=True)
    r = next(x for x in _rows(p.consolidated(), "2 m") if x["type"] == "range" and x["from"] <= 147.0 <= x["to"])
    assert r["authority"] == "arrl"
    st._localplans = p
    srv = serve(st, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/bandplan/area") as r:
            v = json.loads(r.read())
        assert v["license_class"] is None and any(b["band"] == "2 m" for b in v["bands"])
        assert v["read"][0]["excluded"] is True
    finally:
        srv.shutdown()


def test_segments_are_cleaned():
    got = LP._clean_segments([{"from_mhz": 147.57, "to_mhz": 147.42, "use": " FM  simplex "},
                              {"from_mhz": 100, "to_mhz": 101, "use": "broadcast"}, {"from_mhz": 146.52, "use": ""},
                              {"from_mhz": 146.52, "use": "calling"}, "junk"])
    assert got == [{"from_mhz": 147.42, "to_mhz": 147.57, "use": "FM simplex"},
                   {"from_mhz": 146.52, "to_mhz": 146.52, "use": "calling"}]
