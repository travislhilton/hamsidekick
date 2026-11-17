"""Radio channels for a CHIRP file (station/radiochan.py). Owner 2026-11-17: "give a short name to any frequency that is
allocated in the overall band plan ... and flag them to be included in a Chirp export ... the quick creation of a Chirp
export to update a radio"; Baofeng and Quansheng radios show 8 characters."""
import csv
import io
import json

import pytest

from station import radiochan as R

RPT = {"freq_mhz": 146.94, "offset_mhz": -0.6, "tone_hz": 100, "mode": "FM", "org": "K7ABC",
       "name": "K7ABC repeater, county ARES net Tuesdays"}


def _csv(items, profile="ht", start=1):
    return list(csv.DictReader(io.StringIO(R.chirp_csv(items, profile, start))))


def test_mark_a_repeater_and_a_simplex_channel():
    m = R.apply([], {"add": RPT})
    m = R.apply(m, {"add": {"freq_mhz": 146.52, "mode": "FM", "name": "National simplex calling"}})
    m = R.apply(m, {"add": {"freq_mhz": 442.1, "offset_mhz": 5, "tone_hz": 103.4, "name": "Club repeater"}})
    assert [x["alias"] for x in m] == ["K7ABC", "146.52", "R442.1"]       # callsign / frequency / R + frequency
    assert m[2]["tone_hz"] == 103.5                                         # the nearest CTCSS tone
    with pytest.raises(ValueError, match="already"):
        R.apply(m, {"add": RPT})
    m = R.apply(m, {"edit": {"freq_mhz": 146.94, "offset_mhz": -0.6, "alias": "ares rptr one"}})
    assert m[0]["alias"] == "ARES RPT" and m[0]["name"].startswith("K7ABC repeater")
    m = R.apply(m, {"remove": {"freq_mhz": 442.1, "offset_mhz": 5}})
    assert len(m) == 2
    r = _csv(R.listing([], m, []))
    assert [(x["Location"], x["Name"], x["Frequency"], x["Duplex"], x["Offset"], x["Tone"], x["rToneFreq"])
            for x in r] == [("1", "146.52", "146.520000", "", "0.000000", "", "88.5"),
                            ("2", "ARES RPT", "146.940000", "-", "0.600000", "Tone", "100.0")]
    assert r[1]["Comment"].startswith("K7ABC repeater")


def test_ad_hoc_and_marks_in_one_list_in_my_order():
    ad = [{"freq_mhz": 445.525, "kind": "data", "width": "wide", "name": "County VARA", "alias": "VARA1"},
          {"freq_mhz": 446.525, "kind": "voice", "name": "", "alias": "TAC1"}]
    marks = R.apply([], {"add": RPT})
    rows = R.listing(ad, marks, [])
    assert [r["alias"] for r in rows] == ["K7ABC", "VARA1", "TAC1"]           # by frequency until ordered
    order = R.move([], [r["key"] for r in rows], rows[2]["key"], -2)
    assert [r["alias"] for r in R.listing(ad, marks, order)] == ["TAC1", "K7ABC", "VARA1"]
    r = _csv(R.listing(ad, marks, order), start=10)
    assert [x["Location"] for x in r] == ["10", "11", "12"] and r[2]["Comment"] == "County VARA"


def test_each_radio_gets_its_bands_and_aliases_are_never_cut():
    """Owner 2026-11-17: "my older Baofengs only support 7 characters. Let's stick with 8 ... and let the user manually
    change them after export"."""
    items = R.listing([], [R.clean_mark(x) for x in (
        {"freq_mhz": 146.94, "offset_mhz": -0.6, "alias": "LONGNAME"},
        {"freq_mhz": 146.52, "alias": "longname"},
        {"freq_mhz": 223.5, "alias": "220SMPL"},
        {"freq_mhz": 7.2, "mode": "LSB", "alias": "40M NET"})], [])
    p = R.plan(items, "ht")
    assert [r["chirp_name"] for r in p["rows"]] == ["LONGNAME", "LONGNAME"] and not p["shortened"]
    assert p["dups"] == ["LONGNAME: 146.52 and 146.94 MHz"]
    assert p["left_out"] == ["7.2 MHz (40M NET): not a band this radio has", "223.5 MHz (220SMPL): not a band this radio has"]
    a = R.plan(items, "any")
    assert len(a["rows"]) == 4 and not a["left_out"] and {r["mode"] for r in a["rows"]} == {"FM", "LSB"}
    assert set(R.PROFILES) == {"ht", "any"} and all(v["len"] == 8 for v in R.PROFILES.values())


def test_station_routes_and_sharing(tmp_path):
    import threading
    import urllib.request
    from station.server import serve
    from tests.test_history import _post
    from tests.test_winlink_channels import _plans
    st, p, _, _ = _plans(tmp_path)
    p._class = lambda: "technician"
    p.adhoc_set({"add": {"freq_mhz": 445.525, "kind": "data", "name": "County ARES VARA simplex"}})
    st._localplans = p
    srv = serve(st, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        _post(base, "/api/radio", {"add": RPT})
        _post(base, "/api/radio", {"profile": "any", "start": 5})
        with urllib.request.urlopen(base + "/api/bandplan/area") as h:
            r = json.loads(h.read())["radio"]
        assert r["profile"] == "any" and r["start"] == 5 and [c["alias"] for c in r["channels"]] == ["K7ABC", "VARA1"]
        k7 = r["channels"][0]
        assert not k7["ok"] and "no longer lists" in k7["why"]           # no plan here lists the repeater
        with urllib.request.urlopen(base + "/api/radio/export.csv") as h:
            assert h.headers["Content-Type"] == "text/csv"
            rows = list(csv.DictReader(io.StringIO(h.read().decode())))
        assert [(x["Location"], x["Name"]) for x in rows] == [("5", "K7ABC"), ("6", "VARA1")]
        with urllib.request.urlopen(base + "/api/radio/export.csv?radio=ht&start=1") as h:
            assert h.read().decode().splitlines()[1].startswith("1,K7ABC,146.940000,-,0.600000,Tone,100.0")
        with urllib.request.urlopen(base + "/api/adhoc/export") as h:
            assert "radio_channels" not in json.loads(h.read())               # not shared unless ticked
        with urllib.request.urlopen(base + "/api/adhoc/export?radio=1") as h:
            f = json.loads(h.read())
        assert f["radio_channels"][0]["alias"] == "K7ABC"
        with pytest.raises(urllib.error.HTTPError):
            _post(base, "/api/radio", {"profile": "nope"})
    finally:
        srv.shutdown()
    st2, p2, _, _ = _plans(tmp_path / "b")
    p2._class = lambda: "technician"
    rep = p2.adhoc_import(f)["report"]
    assert rep["added"] == 1 and rep["radio_added"] == 1
