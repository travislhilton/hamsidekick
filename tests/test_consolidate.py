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
    assert _at(d, 14.13)[0]["unplanned"] and _at(d, 21.13)[0]["unplanned"]   # VARA: unplanned ranges too (11-16)
    assert not _at(d, 3.54) and not _at(d, 7.05) and not _at(d, 219.5)      # HF CW; 219-220 is links only
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


def test_fm_bands_list_free_simplex_channels_and_vara_fm_wide_needs_room(tmp_path):
    """Owner 2026-11-16: Ad hoc voice showed nothing on 2 m (the local plans name a channel every 20-40 kHz, so no
    "range" was left), and "For VARA FM we need to consider bandwidth for WIDE and NARROW". FM bands now list the free
    simplex channels on the usual steps, neighbours in one row; VARA FM wide only where there is about 25 kHz of room;
    nothing in the leftover gaps between segments (they border repeaters); 6 m below 51 MHz stays SSB ranges."""
    used = [146.42, 146.46, 146.50, 146.52, 146.54, 146.56, 146.58, 147.45, 147.46, 147.52, 145.03]
    t = C.build("general", [{"id": "a", "name": "County plan", "authority": "local", "segments": [],
                             "frequencies": [{"freq_mhz": f, "mode": "FM", "use": f"Tac {f}"} for f in used]}])
    v, d = C.open_ranges(t, "voice"), C.open_ranges(t, "data")
    two = [(x["from"], x["to"], x["count"]) for x in v if x["band"] == "2 m"]
    assert (146.44, 146.44, 1) in two and (146.48, 146.48, 1) in two and (147.48, 147.5, 2) in two
    assert all(x["channel"] and x["mode"] == "FM" and x["step"] == 0.02 for x in v if x["band"] == "2 m")
    assert not any(abs(x["from"] - 147.44) < 1e-6 for x in v)      # 10 kHz from 147.45: not free
    assert not _at(v, 146.6) and not _at(v, 147.99) and not _at(v, 146.37)  # no unplanned gaps beside repeaters
    seventy = [x for x in v if x["band"] == "70 cm"]
    assert seventy and max(x["count"] for x in seventy) > 10 and seventy[0]["step"] == 0.025
    six = [x for x in v if x["band"] == "6 m" and x["from"] < 51]
    assert six and all(x["mode"] == "USB" and not x.get("channel") for x in six)
    fm = {x["from"]: x for x in d if x["mode"] == "VARA FM" and x["band"] == "2 m"}
    assert fm[145.05]["wide"] is False                              # 20 kHz from 145.03: narrow only
    assert any(x["wide"] for x in fm.values())                       # further off: narrow and wide


def test_no_duplicates_when_the_band_plan_is_changed(tmp_path, xai_key):
    """Owner 2026-11-16: "Ensure that there are no duplicates when modifying the band plan" and "Only offer to select
    only those that are not duplicates"."""
    dup_answer = {"clubs": [{"name": "County ARES"}, {"name": "county ares"}],
                  "documents": [{"title": "County ARES plan", "url": "https://example.org/ares-plan.pdf",
                                 "kind": "ares_plan", "public": True},
                                {"title": "County ARES plan (again)", "url": "http://www.example.org/ares-plan.pdf/",
                                 "kind": "ares_plan", "public": True},
                                {"title": "Mirror of the plan", "url": "https://mirror.example.net/plan.pdf",
                                 "kind": "comm_plan", "public": True}],
                  "frequencies": [{"freq_mhz": 147.48, "mode": "FM", "use": "Tactical simplex 1", "kind": "simplex",
                                   "source_url": "https://example.org/ares-plan.pdf"},
                                  {"freq_mhz": 147.480, "mode": "FM", "use": "tactical  Simplex 1.", "priority": "alternate",
                                   "source_url": "https://example.org/ares"}]}
    st, p, _, _ = _plans(tmp_path, answer=dup_answer)
    seg = {"from_mhz": 146.61, "to_mhz": 147.39, "use": "FM repeater outputs"}
    reads = []

    def extract(key, sys, user):
        reads.append(1)
        return {"segments": [seg, dict(seg, use="FM Repeater Outputs.")],
                "frequencies": [{"freq_mhz": 147.0, "mode": "FM", "use": "ARES tactical"},
                                {"freq_mhz": 147.0, "mode": "FM", "use": "ARES Tactical"}]}
    p.extract, p._text_of = extract, (lambda path: "a plan")
    s = p.search()
    p.save_copies()                                   # every copy is the same PDF bytes (the test fetcher)
    s = p.state()
    assert len(s["clubs"]) == 1 and len(s["documents"]) == 2               # the same address once
    found = [f for f in s["frequencies"] if not f["kept"]]
    assert len(found) == 1 and found[0]["priority"] == "alternate"         # one channel, its details merged
    url, mirror = "https://example.org/ares-plan.pdf", "https://mirror.example.net/plan.pdf"
    p.choose(url, True, background=False)
    s = p.state()
    m = next(x for x in s["documents"] if x["url"] == mirror)
    assert m["band"]["dup"] == "County ARES plan"                          # the same bytes: not offered
    with pytest.raises(ValueError, match="same document"):
        p.choose(mirror, True, background=False)
    with pytest.raises(ValueError, match="same document"):
        p.add_file("ares.pdf", b"%PDF-1.4 a plan")                         # uploaded again as a file
    ent = p.consolidated()
    r = next(x for x in _rows(ent, "2 m") if x["type"] == "range" and x["from"] <= 147.0 <= x["to"])
    assert [x["use"] for x in r["statements"] if x["authority"] == "local"] == ["FM repeater outputs"]
    ch = [x for x in _rows(ent, "2 m") if x["type"] == "channel" and x["from"] == 147.0]
    assert len(ch) == 1 and len(ch[0]["statements"]) == 1
    n = len(p.state()["frequencies"])
    p.choose(url, True, again=True, background=False)                      # read again: replaced, not added
    assert len(p.state()["frequencies"]) == n and len(reads) == 2
    tac = next(f for f in p.state()["frequencies"] if f["freq_mhz"] == 147.0)
    p.keep([tac["id"]])
    s = p.state()
    assert not [f for f in s["frequencies"] if f["freq_mhz"] == 147.0 and not f["kept"]]   # kept: not offered again
    ch = [x for x in _rows(p.consolidated(), "2 m") if x["type"] == "channel" and x["from"] == 147.0]
    assert len(ch) == 1 and ch[0]["kept"] and len(ch[0]["statements"]) == 1   # kept from that plan: one statement
    p.keep([tac["id"]])
    assert len([k for k in p.state()["kept"] if k["freq_mhz"] == 147.0]) == 1


def test_the_search_finds_winlink_gateways_and_they_go_into_the_band_plan(tmp_path, xai_key):
    """Owner 2026-11-16: "also search in the winlink gateways and include those for our area (VHF/UHF)"."""
    gw = {"freq_mhz": 145.07, "mode": "FM", "kind": "winlink", "use": "Winlink gateway K7ABC-10 (VARA FM)",
          "org": "K7ABC", "source_url": "https://example.org/gateways"}
    hf = dict(gw, freq_mhz=7.1035, mode="USB", use="Winlink gateway K7ABC (VARA HF)")
    st, p, sent, _ = _plans(tmp_path, answer={"clubs": [], "documents": [], "frequencies": [gw, hf, dict(gw)]})
    s = p.search()
    assert "Winlink RMS gateways on VHF / UHF" in sent[0]["input"][0]["content"]
    g = next(x for x in s["gateways"] if x["key"] == "search:winlink")
    assert g["band"]["in"] and [x["freq_mhz"] for x in g["list"]] == [145.07]       # VHF/UHF only, once
    t = p.consolidated()
    ch = [x for x in _rows(t, "2 m") if x["type"] == "channel" and x["from"] == 145.07]
    assert ch and ch[0]["use"] == "Winlink gateway K7ABC-10 (VARA FM)"
    assert not _at(t["open"]["data"], 145.07)                                       # ad hoc VARA keeps clear of it
    p.choose(g["key"], False)                                                       # leave them out
    assert not p.state()["gateways"][0]["band"]["in"]
    assert not [x for x in _rows(p.consolidated(), "2 m") if x["type"] == "channel" and x["from"] == 145.07]
    p.choose(g["key"], True)
    assert p.state()["gateways"][0]["band"]["in"]


def test_seventy_cm_simplex_is_open_to_vara_fm(tmp_path):
    """Owner 2026-11-16: "The Ad hoc VARA FM band plan is showing no 70cm available ... 70cm is actually the most
    probable band for local VARA FM ad-hoc traffic". Data is legal on all of 420-450 (97.305(c)) but the ARRL plan
    sets no data segment there: its local-option FM simplex (445-447) is offered to VARA FM, shared with voice."""
    t = C.build("technician", [])
    d = [x for x in C.open_ranges(t, "data") if x["band"] == "70 cm"]
    pts = [round(x["from"] + i * x["step"], 3) for x in d for i in range(x["count"])]
    assert 445.025 in pts and 446.975 in pts and len(pts) > 70
    assert all(445 < f < 447 for f in pts)                             # never ATV, links, satellites, repeaters
    assert 446.0 not in pts and 445.0 not in pts and 447.0 not in pts  # the calling channel; the segment's edges
    assert all(x["shared"] and x["mode"] == "VARA FM" and "listen first" in x["note"] for x in d)
    assert any(x["wide"] for x in d) and not next(x for x in d if x["from"] == 445.975)["wide"]   # beside 446.000
    two = [x for x in C.open_ranges(t, "data") if x["band"] == "2 m"]
    assert not any(146.4 <= x["from"] <= 146.58 for x in two)          # 2 m voice simplex stays voice


def _pts(rows, band):
    return [round(x["from"] + i * x["step"], 3) for x in rows if x["band"] == band and x.get("channel")
            for i in range(x["count"])]


def test_two_m_and_one_25_vara_fm(tmp_path):
    """Owner 2026-11-16: "do the same analysis for 2m and 1.25m VARA FM". ARRL: data set aside on 2 m 145.01-145.09
    and 1.25 m 223.52-223.64; "miscellaneous and experimental" (2 m 145.5-145.8) and "local option" (1.25 m
    223.71-223.85) are shared; FM voice simplex stays voice; links, satellites, weak signal, repeaters never."""
    t = C.build("technician", [])
    d = C.open_ranges(t, "data")
    two, one = _pts(d, "2 m"), _pts(d, "1.25 m")
    assert {145.03, 145.05, 145.07} <= set(two) and 145.51 in two and 145.79 in two
    assert all(round(f * 100) % 2 == 1 for f in two)                   # odd 20 kHz channels below 146
    assert not any(146 <= f for f in two) and not any(145.8 <= f < 146 or 145.1 <= f < 145.5 for f in two)
    assert {223.54, 223.62, 223.72, 223.84} <= set(one) and not any(223.4 <= f < 223.52 or 223.64 <= f < 223.71
                                                                     or f < 223.4 for f in one)
    shared = {x["from"]: x["shared"] for x in d if x.get("channel")}
    assert shared[145.03] is False and shared[223.54] is False and shared[145.53] and shared[223.74]
    w = {round(x["from"] + i * x["step"], 3): x["wide"] for x in d if x.get("channel") for i in range(x["count"])}
    assert w[145.51] is False and w[145.53] and w[223.84] is False   # 10 kHz from a closed edge: narrow only
    assert len(two) == len(set(two))


COORD_FM = {"id": "co", "name": "Coordinator VHF/UHF plan", "authority": "coordinator", "frequencies": [], "segments": [
    {"from_mhz": 144.9, "to_mhz": 145.2, "use": "Simplex/duplex packet operation"},
    {"from_mhz": 145.1, "to_mhz": 145.5, "use": "FM repeater outputs"},
    {"from_mhz": 145.5, "to_mhz": 145.8, "use": "Simplex, miscellaneous/experimental (no repeater operation allowed)"},
    {"from_mhz": 146.42, "to_mhz": 146.6, "use": "FM simplex"},
    {"from_mhz": 431.0, "to_mhz": 432.0, "use": "Digital/packet operation (9600+ baud)"},
    {"from_mhz": 438.0, "to_mhz": 441.0, "use": "Links, control and local simplex usage"},
    {"from_mhz": 440.05, "to_mhz": 441.05, "use": "Misc. digital/packet (except the northern area)"},
    {"from_mhz": 445.0, "to_mhz": 447.0, "use": "Simplex, links and control"}]}


def test_a_coordinator_plan_decides_its_area(tmp_path):
    """Where the area's frequency coordinator's band plan covers a stretch, its words decide (the ARRL plan defers
    to local plans): its digital stretch inside ARRL ATV simplex is VARA FM; its links are not; "no repeater" is not
    a repeater stretch; "except <area>" is not offered (the station cannot tell); channels never repeat."""
    t = C.build("technician", [COORD_FM])
    d = C.open_ranges(t, "data")
    two, cm = _pts(d, "2 m"), _pts(d, "70 cm")
    assert 144.91 in two and 145.09 in two and 145.53 in two and not any(145.1 < f < 145.5 for f in two)
    assert 431.025 in cm and 431.975 in cm and not any(438 <= f <= 441.05 for f in cm)   # links; "except"
    assert 445.5 in cm                                                 # "Simplex, links and control" shared
    assert len(cm) == len(set(cm)) and len(two) == len(set(two))
    v = _pts(C.open_ranges(t, "voice"), "2 m")
    assert 146.58 in v and len(v) == len(set(v)) and all(round(f * 100) % 2 == 0 for f in v)


def test_the_plan_reader_asks_for_segments(tmp_path, monkeypatch):
    """A structured answer holds only what the schema names: without "segments" a state band plan read as 0
    segments (2026-11-16)."""
    from station import agent, localplans
    seen = {}

    def fake(key, model, system, user, timeout=0, schema=None, max_tokens=0, name=""):
        seen.update(schema)
        return {"segments": [], "frequencies": []}, {}
    monkeypatch.setattr(agent, "call_xai", fake)
    p = localplans.Plans.__new__(localplans.Plans)
    p.extract = None
    p._call_extract("k", "s", "u")
    assert "segments" in seen["properties"] and "segments" in seen["required"]
