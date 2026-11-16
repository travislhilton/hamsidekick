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
    assert [(r["freq_mhz"], r["kind"], r["width"], r["name"]) for r in rows] == [
        (445.525, "data", "wide", ""), (446.525, "voice", None, "Tac 1")]
    with pytest.raises(ValueError, match="already"):
        adhoc.apply(rows, {"add": {"freq_mhz": 445.525, "kind": "data"}})
    rows = adhoc.apply(rows, {"rename": {"freq_mhz": 445.525, "kind": "data", "name": "VARA 1"}})
    rows = adhoc.apply(rows, {"width": {"freq_mhz": 445.525, "kind": "data", "width": "narrow"}})
    assert rows[0]["name"] == "VARA 1" and rows[0]["width"] == "narrow"
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
    assert {(r["freq_mhz"], r["name"]) for r in got} == {(445.525, "VARA 1"), (446.525, "Tac 1")}
    got, rep = adhoc.import_(got, {"format": adhoc.FORMAT, "channels": [{"freq_mhz": 223.74, "kind": "data"}]},
                             replace=True)
    assert [r["freq_mhz"] for r in got] == [223.74]
    with pytest.raises(ValueError, match="not a HAM Sidekick"):
        adhoc.import_(got, {"channels": []})


def test_chirp_csv():
    rows = adhoc.apply([], {"add": {"freq_mhz": 446.525, "kind": "voice", "name": "Tac 1"}})
    rows = adhoc.apply(rows, {"add": {"freq_mhz": 145.53, "kind": "data"}})
    r = list(csv.DictReader(io.StringIO(adhoc.chirp_csv(rows))))
    assert [(x["Name"], x["Frequency"], x["Duplex"], x["Mode"]) for x in r] == [
        ("Tac 1", "446.525000", "", "FM"), ("V145.530", "145.530000", "", "FM")]


def test_in_the_band_plan_marked_and_still_listed():
    res = [{"freq_mhz": 445.525, "kind": "data", "width": "wide", "name": "VARA 1"},
           {"freq_mhz": 446.525, "kind": "voice", "name": "Tac 1"}]
    t = C.build("technician", [], None, res)
    rows = {r["from"]: r for b in t["bands"] for r in b["rows"] if r["type"] == "channel"}
    assert rows[445.525]["adhoc"] == [{"kind": "data", "width": "wide", "name": "VARA 1"}]
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
    assert "data-adtog" in html and "/api/adhoc/export.csv" in html and "data-adimport" in html and "★ my ad hoc" in html
