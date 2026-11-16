"""The consolidated band plan (station/consolidate.py + localplans.ingest, owner 2026-11-15): saved plans are read into
segments and channels, merged with the FCC rules and the ARRL band plan, and every disagreement is flagged."""
import json
import threading

import pytest
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
    p.save_copies()                                   # saved; nothing is read until the operator chooses it
    assert p.consolidated()["read"] == [] and p.consolidated()["unread"] == 1
    p.choose("https://example.org/ares-plan.pdf", True, background=False)
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


def test_the_operator_chooses_which_plans_go_into_the_band_plan(tmp_path, xai_key):
    """Owner 2026-11-16: "I need a way for the system to ingest those that I choose into the overall band plan
    table". A tick per plan: read once (its copy saved first if need be), out without reading again, back in free."""
    st, p, _, got = _plans(tmp_path)
    reads = []

    def extract(key, sys, user):
        reads.append(user)
        return {"segments": COORD["segments"], "frequencies": []}
    p.extract, p._text_of = extract, (lambda path: "a band plan")
    p.save_copies = lambda **kw: None                             # (a plan the search did not copy: a repeater list)
    p.search()
    url = "https://example.org/ares-plan.pdf"
    doc = next(x for x in p.state()["documents"] if x["url"] == url)
    assert doc["band"] == {"in": False, "reading": False, "read": False, "error": None, "segments": 0,
                           "channels": 0, "authority": None, "at": None}
    assert got == [] and reads == []                              # a search reads nothing into the plan
    s = p.choose(url, True, background=False)                     # not saved yet: saved, then read
    doc = next(x for x in s["documents"] if x["url"] == url)
    assert got == [url] and len(reads) == 1 and doc["band"]["in"] and doc["band"]["segments"] == 3
    assert doc["saved"]["path"].endswith(".pdf")
    r = next(x for x in _rows(p.consolidated(), "2 m") if x["type"] == "range" and x["from"] <= 147.0 <= x["to"])
    assert r["authority"] == "local"
    s = p.choose(url, False)                                       # out: the reading is kept
    assert not next(x for x in s["documents"] if x["url"] == url)["band"]["in"]
    r = next(x for x in _rows(p.consolidated(), "2 m") if x["type"] == "range" and x["from"] <= 147.0 <= x["to"])
    assert r["authority"] == "arrl"
    s = p.choose(url, True, background=False)                      # back in: no second read
    assert next(x for x in s["documents"] if x["url"] == url)["band"]["in"] and len(reads) == 1
    p.choose(url, True, again=True, background=False)              # read again on purpose
    assert len(reads) == 2
    with pytest.raises(ValueError, match="members-only"):
        p.choose("https://example.org/races", True)
    with pytest.raises(ValueError, match="no such plan"):
        p.choose("https://example.org/nowhere", True)


def test_a_plan_whose_copy_cannot_be_saved_says_so(tmp_path, xai_key):
    st, p, _, _ = _plans(tmp_path)
    p.fetch = lambda url: (_ for _ in ()).throw(OSError("timed out"))
    p.search()
    s = p.choose("https://example.org/ares-plan.pdf", True, background=False)
    b = next(x for x in s["documents"] if x["kind"] == "ares_plan")["band"]
    assert not b["in"] and "no copy could be saved" in b["error"] and "timed out" in b["error"]


def _at(rows, f):
    return [x for x in rows if x["from"] <= f <= x["to"]]


def test_open_for_ad_hoc_voice_and_vara(tmp_path):
    """Owner 2026-11-16: "a way to see unplanned frequency ranges where I can do ad hoc VARA sessions and also Voice
    sessions": inside the class's privileges, nothing else planned there, clear of every channel."""
    t = C.build("general", [])
    v, d = C.open_ranges(t, "voice"), C.open_ranges(t, "data")
    forty = _at(v, 7.2)
    assert forty and forty[0]["unplanned"] and forty[0]["mode"] == "LSB" and forty[0]["from"] >= 7.178
    assert not _at(v, 7.15)                                        # General: no phone below 7.175
    assert not _at(v, 146.52) and not _at(v, 146.51) and _at(v, 146.46)   # the calling frequency kept clear
    assert not _at(v, 146.94) and not _at(v, 144.39) and not _at(v, 145.9)  # repeaters, APRS, satellites
    assert not _at(v, 1.82)                                        # 160 m CW
    assert not _at(v, 14.07) and not _at(d, 14.03) and not _at(d, 14.2)    # data only where a plan sets it aside
    vara = _at(d, 14.105)
    assert vara and vara[0]["auto"] and "Winlink" in vara[0]["note"] and vara[0]["mode"].startswith("VARA HF")
    assert not _at(d, 14.074) and not _at(d, 14.1)                 # FT8, the beacons
    assert _at(d, 145.05)[0]["mode"] == "VARA FM" and not _at(d, 144.39)
    assert not any(x["band"] in ("33 cm", "23 cm", "60 m") for x in v + d)
    tech = C.open_ranges(C.build("technician", []), "voice")
    assert {x["band"] for x in tech if x["from"] < 30} == {"10 m"} and all(28.3 <= x["from"] for x in tech if x["from"] < 30)
    assert C.open_ranges(C.build(None, []), "voice") == []         # no class: nothing claimed
    local = C.build("general", [{"id": "a", "name": "County ARES plan", "authority": "local",
                                 "segments": [{"from_mhz": 7.25, "to_mhz": 7.26, "use": "Section HF net"}],
                                 "frequencies": [{"freq_mhz": 7.2, "mode": "LSB", "use": "County HF net"}]}])
    lv = C.open_ranges(local, "voice")
    assert not _at(lv, 7.2) and not _at(lv, 7.199) and _at(lv, 7.21)       # a local channel carved out
    assert _at(lv, 7.255)[0]["uses"] == ["Section HF net"] and not _at(lv, 7.255)[0]["unplanned"]
