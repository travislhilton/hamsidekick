"""Reserved ad hoc channels (station/adhoc.py). Owner 2026-11-16: "split up each frequency range into channel
frequencies and add a button or link to reserve for my ad-hoc and add my reserved ad-hoc frequencies to the band plan
with a special marker ... export my ad-hoc reserved frequencies to another operator ... Do something similar for FM
voice"."""
import csv
import io

import pytest

from station import adhoc
from station import consolidate as C


def test_reserve_rename_width_release():
    rows = adhoc.apply([], {"add": {"freq_mhz": 445.525, "kind": "data", "width": "wide"}})
    rows = adhoc.apply(rows, {"add": {"freq_mhz": 446.525, "kind": "voice", "name": "  Tac   1 "}})
    assert [(r["freq_mhz"], r["kind"], r["width"], r["name"], r["alias"]) for r in rows] == [
        (445.525, "data", "wide", "", "VARA1"), (446.525, "voice", None, "Tac 1", "TAC 1")]
    with pytest.raises(ValueError, match="already"):
        adhoc.apply(rows, {"add": {"freq_mhz": 445.525, "kind": "data"}})
    rows = adhoc.apply(rows, {"rename": {"freq_mhz": 445.525, "kind": "data", "name": "County ARES VARA, drills"}})
    rows = adhoc.apply(rows, {"rename": {"freq_mhz": 445.525, "kind": "data", "alias": "ares vara"}})
    rows = adhoc.apply(rows, {"width": {"freq_mhz": 445.525, "kind": "data", "width": "narrow"}})
    assert (rows[0]["name"], rows[0]["alias"], rows[0]["width"]) == ("County ARES VARA, drills", "ARES VAR", "narrow")
    for bad in ({"freq_mhz": 7.1, "kind": "voice"}, {"freq_mhz": 146.52, "kind": "fax"}, {"kind": "data"},
                {"freq_mhz": 144.05, "kind": "data"}):
        with pytest.raises(ValueError):
            adhoc.apply(rows, {"add": bad})
    rows = adhoc.apply(rows, {"remove": {"freq_mhz": 446.525, "kind": "voice"}})
    assert len(rows) == 1


def test_export_import_between_operators():
    mine = adhoc.apply([], {"add": {"freq_mhz": 445.525, "kind": "data", "width": "wide", "name": "VARA 1"}})
    mine = adhoc.apply(mine, {"add": {"freq_mhz": 446.525, "kind": "voice", "name": "Tac 1"}})
    f = adhoc.export(mine, "W9XYZ")
    assert f["format"] == adhoc.FORMAT and f["from"] == "W9XYZ" and len(f["channels"]) == 2
    theirs = adhoc.apply([], {"add": {"freq_mhz": 446.525, "kind": "voice"}})
    got, rep = adhoc.import_(theirs, dict(f, channels=f["channels"] + [{"freq_mhz": 14.1, "kind": "data"}]))
    assert rep["added"] == 1 and rep["renamed"] == 1 and len(rep["skipped"]) == 1
    assert {(r["freq_mhz"], r["name"], r["alias"]) for r in got} == {(445.525, "VARA 1", "VARA 1"),
                                                                     (446.525, "Tac 1", "TAC 1")}
    got, rep = adhoc.import_(got, {"format": adhoc.FORMAT, "channels": [{"freq_mhz": 223.74, "kind": "data"}]},
                             replace=True)
    assert [r["freq_mhz"] for r in got] == [223.74]
    with pytest.raises(ValueError, match="not a HAM Sidekick"):
        adhoc.import_(got, {"channels": []})


def test_chirp_csv():
    rows = adhoc.apply([], {"add": {"freq_mhz": 446.525, "kind": "voice", "name": "Tac 1"}})
    rows = adhoc.apply(rows, {"add": {"freq_mhz": 145.53, "kind": "data"}})
    r = list(csv.DictReader(io.StringIO(adhoc.chirp_csv(rows))))
    assert [(x["Location"], x["Name"], x["Frequency"], x["Duplex"], x["Mode"]) for x in r] == [
        ("1", "VARA1", "145.530000", "", "FM"), ("2", "TAC 1", "446.525000", "", "FM")]


def test_in_the_band_plan_marked_and_still_listed():
    res = [{"freq_mhz": 445.525, "kind": "data", "width": "wide", "name": "VARA 1"},
           {"freq_mhz": 446.525, "kind": "voice", "name": "Tac 1"}]
    t = C.build("technician", [], None, res)
    rows = {r["from"]: r for b in t["bands"] for r in b["rows"] if r["type"] == "channel"}
    assert rows[445.525]["adhoc"] == [{"kind": "data", "width": "wide", "name": "VARA 1", "alias": None}]
    assert rows[445.525]["use"] == "My ad hoc VARA FM wide: VARA 1" and rows[445.525]["authority"] == "adhoc"
    assert not rows[445.525]["flags"]
    pts = lambda k: {round(x["from"] + i * x["step"], 4): x for x in C.open_ranges(t, k) if x.get("channel")  # noqa: E731
                     for i in range(x["count"])}
    d, v = pts("data"), pts("voice")
    assert 445.525 in d and d[445.525]["wide"]                         # its own reservation stays listed
    assert 446.525 not in d and 446.525 in v                           # a voice reservation is not offered to VARA
    assert 445.525 not in v


def test_station_routes(tmp_path):
    from tests.test_winlink_channels import _plans
    st, p, _, _ = _plans(tmp_path)
    p._class = lambda: "technician"
    p.adhoc_set({"add": {"freq_mhz": 445.525, "kind": "data", "width": "wide"}})
    p.adhoc_set({"add": {"freq_mhz": 147.5, "kind": "data"}})            # 2 m voice simplex: not open for VARA
    t = p.consolidated()
    by = {a["freq_mhz"]: a for a in t["adhoc"]}
    assert by[445.525]["ok"] and not by[147.5]["ok"] and "no longer open" in by[147.5]["why"]
    data, ctype, name = p.adhoc_export()
    assert ctype == "application/json" and name.endswith(".json") and b"445.525" in data
    assert p.adhoc_export("csv")[1] == "text/csv"
    import json
    p.adhoc_import(json.loads(data), replace=True)
    assert [a["freq_mhz"] for a in p.adhoc()] == [147.5, 445.525]
    from station.server import STATIC
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "data-adtog" in html and "/api/radio/export.csv" in html and "data-rcadd" in html and "data-adimport" in html and "★ my ad hoc" in html


def test_a_long_name_and_a_radio_alias():
    """Owner 2026-11-17: a reservation has a name of any length and a radio alias, the short name for the CHIRP export;
    the owner's Baofeng and Quansheng radios show 8 characters (A-Z 0-9 space . / -)."""
    assert adhoc.NAME_MAX == 8
    assert adhoc.short_name("ares vara #1 longer") == "ARES VAR"
    assert adhoc.short_name("tac_2!") == "TAC2" and adhoc.short_name("Net/1.5-xyz") == "NET/1.5-"
    rows = adhoc.apply([], {"add": {"freq_mhz": 445.525, "kind": "data"}})
    rows = adhoc.apply(rows, {"add": {"freq_mhz": 445.55, "kind": "data", "name": "Springfield ARES VARA simplex"}})
    rows = adhoc.apply(rows, {"add": {"freq_mhz": 446.525, "kind": "voice", "name": "Tactical", "alias": "tac a"}})
    assert [(r["name"], r["alias"]) for r in rows] == [("", "VARA1"), ("Springfield ARES VARA simplex", "VARA2"),
                                                      ("Tactical", "TAC A")]
    assert adhoc.suggest(rows, "data") == "VARA3"
    assert adhoc.label(rows[1]) == "My ad hoc VARA FM: Springfield ARES VARA simplex"
    rows = adhoc.apply(rows, {"rename": {"freq_mhz": 446.525, "kind": "voice", "alias": "simplex tactical one"}})
    assert rows[-1]["alias"] == "SIMPLEX" and rows[-1]["name"] == "Tactical"
    got, _ = adhoc.import_([], {"format": adhoc.FORMAT, "channels": [{"freq_mhz": 147.5, "kind": "voice",
                                                                       "name": "OLD LO"}]})   # a version 1 file
    assert (got[0]["name"], got[0]["alias"]) == ("OLD LO", "OLD LO")
    f = adhoc.export(rows, "W9XYZ")
    assert f["version"] == 2 and f["channels"][1]["alias"] == "VARA2" and "radio_channels" not in f


def test_wide_reservations_keep_clear_of_each_other(tmp_path):
    """Owner 2026-11-16 ("do the fix"): two wide VARA FM reservations 25 kHz apart on 70 cm both looked fine. A wide
    signal needs 35 kHz to the next channel on 70 cm (25 on 2 m and 1.25 m), my own reservations included."""
    rows = adhoc.apply([], {"add": {"freq_mhz": 445.5, "kind": "data", "width": "wide"}})
    rows = adhoc.apply(rows, {"add": {"freq_mhz": 445.525, "kind": "data", "width": "wide"}})
    assert [r["width"] for r in rows] == ["wide", "narrow"] and "VARA1 at 445.500" in rows[1]["narrowed"]
    rows = adhoc.apply(rows, {"add": {"freq_mhz": 445.55, "kind": "data", "width": "wide"}})   # 50 kHz from 445.5,
    assert rows[-1]["width"] == "narrow"                                   # 25 from the narrow one: still too close
    two = adhoc.apply([], {"add": {"freq_mhz": 145.53, "kind": "data", "width": "wide"}})
    two = adhoc.apply(two, {"add": {"freq_mhz": 145.57, "kind": "data", "width": "wide"}})    # 40 kHz on 2 m: fine
    assert [r["width"] for r in two] == ["wide", "wide"]

    from tests.test_localplans import _plans
    st, p, _, _ = _plans(tmp_path)
    p._class = lambda: "technician"
    p.adhoc_set({"add": {"freq_mhz": 445.5, "kind": "voice"}})
    r = p.adhoc_set({"add": {"freq_mhz": 445.525, "kind": "data", "width": "wide"}})
    assert r["note"].startswith("Reserved as narrow: too close to your TAC1 at 445.500")
    assert "narrowed" not in r["adhoc"][0] and "narrowed" not in r["adhoc"][1]
    p.adhoc_set({"width": {"freq_mhz": 445.525, "kind": "data", "width": "wide"}})   # the operator insists: ⚠ shown
    a = next(x for x in p.consolidated()["adhoc"] if x["kind"] == "data")
    assert not a["ok"] and "TAC1 at 445.500" in a["why"] and "35 kHz" in a["why"]
    p.adhoc_set({"width": {"freq_mhz": 445.525, "kind": "data", "width": "narrow"}})
    assert all(x["ok"] for x in p.consolidated()["adhoc"] if x["kind"] == "data")
