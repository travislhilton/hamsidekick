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
    assert [x["alias"] for x in m] == ["K7ABC", "2M CALL", "CLUB"]      # callsign / national calling / the name
    assert m[2]["tone_hz"] == 103.5                                         # the nearest CTCSS tone
    with pytest.raises(ValueError, match="already"):
        R.apply(m, {"add": RPT})
    m = R.apply(m, {"edit": {"freq_mhz": 146.94, "offset_mhz": -0.6, "alias": "ares rptr one"}})
    assert m[0]["alias"] == "ARES RPT" and m[0]["name"].startswith("K7ABC repeater")
    m = R.apply(m, {"remove": {"freq_mhz": 442.1, "offset_mhz": 5}})
    assert len(m) == 2
    r = _csv(R.listing([], m, []))
    assert [(x["Location"], x["Name"], x["Frequency"], x["Duplex"], x["Offset"], x["Tone"], x["rToneFreq"])
            for x in r] == [("1", "2M CALL", "146.520000", "", "0.000000", "", "88.5"),
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


def test_a_seven_character_radio_names_aliases_that_would_read_the_same():
    """CHIRP's File -> Import keeps the first valid_name_length characters (filter_name; a UV-5R: 7), so the export
    never cuts an alias but names the two that a 7-character display would show alike (read in CHIRP 2026-11-17)."""
    items = R.listing([], [R.clean_mark(x) for x in (
        {"freq_mhz": 145.61, "alias": "VARAFM11"},
        {"freq_mhz": 145.63, "alias": "VARAFM12"},
        {"freq_mhz": 146.52, "alias": "CALLING"},
        {"freq_mhz": 446.0, "alias": "CALLING7"},     # 'CALLING' already: a 7-character radio shows both alike
        {"freq_mhz": 147.42, "alias": "K7ABC"},
        {"freq_mhz": 147.48, "alias": "K7ABC"})], [])   # a plain duplicate is named once, under dups
    p = R.plan(items, "ht")
    assert [r["chirp_name"] for r in p["rows"]][:2] == ["VARAFM11", "VARAFM12"] and not p["shortened"]
    assert p["dups"] == ["K7ABC: 147.42 and 147.48 MHz"]
    assert p["clash_short"] == ["VARAFM11 and VARAFM12 → VARAFM1", "CALLING and CALLING7 → CALLING"]
    assert "VARAFM12" in R.chirp_csv(items, "ht")


def _chan(f, use, off=None, org=None, adhoc=None):
    return {"type": "channel", "from": f, "to": f, "use": use, "offset_mhz": off, "org": org, "adhoc": adhoc or []}


def test_every_plan_channel_gets_a_smart_unique_alias_and_mine_are_kept():
    """Owner 2026-11-24: "radio aliases for each repeater and simplex specific frequency reserved in the band plan.
    Create a smart 8 char default radio alias for those and allow the user to modify them. These will feed a radio
    CHIRP file export." From the plan's words; unique in the plan (band, then the frequency's last digits); typed
    ones (by frequency and offset), an ad hoc reservation's alias and a 💾 mark's typed alias win."""
    rows = [_chan(146.94, "Springfield (linked repeater)", -0.6), _chan(444.95, "Springfield", 5.0),
            _chan(146.46, "Tac #1 (assigned as necessary)", 0.0), _chan(146.52, "Most often used simplex frequency"),
            _chan(146.54, "Simplex frequency"), _chan(442.1, "10 Meter Repeater", 5.0),
            _chan(147.2, "Command Net #1 (primary); Command Net #2 (secondary)", 0.6),
            _chan(145.05, "Winlink gateway K7ABC-10 (VARA FM)"), _chan(447.0, "DMR Digital (K7ABC) (CC1)", -5.0),
            _chan(449.575, "D-Star B (K7ABC)", -5.0), _chan(146.42, "State Wide Net (RACES) backup", 0.0),
            _chan(147.45, "State Wide Net (RACES) backup", 0.0), _chan(445.525, "x", adhoc=[{"alias": "VARA1"}]),
            _chan(449.9, "County EOC", -5.0), _chan(147.3, "Hospital net", 0.6)]
    table = {"bands": [{"band": "all", "rows": rows}]}
    marks = [R.clean_mark({"freq_mhz": 449.9, "offset_mhz": -5.0, "alias": "EOC UHF", "name": "County EOC"}),
             R.clean_mark({"freq_mhz": 147.3, "offset_mhz": 0.6, "name": "Hospital net"})]
    R.assign_aliases(table, {R.key({"freq_mhz": 146.54, "offset_mhz": None}): "simplx 3"}, marks)
    a = {r["from"]: r["alias"] for r in rows}
    assert (a[146.94], a[444.95]) == ("SPRNG 2M", "SPRNG 70")                 # the same site on two bands
    assert a[146.46] == "TAC1" and a[146.52] == "2M CALL" and a[442.1] == "R442.1" and a[147.2] == "CMD NET1"
    assert a[145.05] == "K7ABC-10" and {a[447.0], a[449.575]} == {"K7ABC447", "K7ABC575"}
    assert (a[146.42], a[147.45]) == ("STWN 642", "STWN 745") and a[146.54] == "SIMPLX 3" and a[445.525] == "VARA1"
    assert a[449.9] == "EOC UHF" and a[147.3] == "HOSP NET"                   # a mark's typed alias wins
    own = {r["from"] for r in rows if r["alias_own"]}
    assert own == {146.54, 445.525, 449.9}
    assert len(set(a.values())) == len(a) and all(len(v) <= R.ALIAS_MAX for v in a.values())
    lst = R.listing([], marks, [], table)                        # the 💾 list and its CHIRP file use the same aliases
    assert [x["alias"] for x in lst] == ["HOSP NET", "EOC UHF"]
