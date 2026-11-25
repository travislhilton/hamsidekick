"""Station packs (station/stationpack.py): one station's plans, kept channels, ad hoc channels and nets, sent to
another and installed after a review (owner 2026-11-24)."""
import gzip
import json

from station import localplans as LP
from station import stationpack as SP
from tests.test_portable import _two

PLAN_URL = "https://example.org/county-ares-plan.pdf"


def _freq(f, use, off=None, tone=None):
    g, _ = LP._clean_freq({"freq_mhz": f, "use": use, "offset_mhz": off, "tone_hz": tone, "mode": "FM",
                           "source_url": PLAN_URL}, set())
    return g


def _sender(a):
    d = {"ingested": {
        PLAN_URL: {"at": 2000.0, "title": "County ARES Plan", "kind": "ares_plan", "org": "County ARES", "url": PLAN_URL,
                   "authority": "local", "segments": [], "frequencies": [_freq(146.94, "Command net", -0.6, 100.0),
                                                                          _freq(146.46, "Tac 1")]},
        "file:abc123": {"at": 2000.0, "title": "Members-only plan", "kind": "ares_plan", "url": "file:abc123",
                        "authority": "local", "segments": [], "frequencies": [_freq(147.45, "Members tac")]},
        "express:vhf": {"at": 2000.0, "title": "Winlink gateways", "authority": "local", "segments": [],
                        "frequencies": [_freq(145.05, "Winlink gateway K7ABC-10")]},
        "https://example.org/left-out": {"at": 2000.0, "title": "Left out", "excluded": True, "segments": [],
                                         "frequencies": [_freq(147.0, "x")]}},
        "kept": [dict(_freq(146.52, "National simplex calling"), kept_at=1.0)],
        "adhoc": [{"freq_mhz": 147.42, "kind": "voice", "name": "ad hoc 1", "alias": "ADHOC1"}]}
    LP._save(a, d)
    a._saved = lambda: {"operator": {"callsign": "W9XYZ", "grid": "FN31pr"}}


def test_a_pack_carries_the_shared_plans_and_never_gateways_left_out_or_own_files(tmp_path):
    a, _ = _two(tmp_path)
    _sender(a)
    av = SP.available(a)
    assert {p["title"] for p in av["plans"]} == {"County ARES Plan", "Members-only plan"} and av["call"] == "W9XYZ"
    doc = SP.build(a)
    assert [p["title"] for p in doc["plans"]] == ["County ARES Plan"] and doc["area"] == "FN31" and doc["from"] == "W9XYZ"
    assert SP.counts(doc) == {"plans": 1, "channels": 2, "segments": 0, "kept": 1, "adhoc": 1, "nets": len(a.cfg["schedule"])}
    assert "checkins" not in json.dumps(doc) and "sidekick" not in doc
    assert [p["title"] for p in SP.build(a, own_files=True)["plans"]] == ["County ARES Plan", "Members-only plan"]
    only = SP.build(a, ["nets"])
    assert "plans" not in only and "kept" not in only and only["nets"]["nets"]
    data = SP.dumps(doc)
    assert data[:2] == b"\x1f\x8b" and len(data) < len(json.dumps(doc))
    assert SP.name_for(doc) == "W9XYZ-station-pack.hspack"


def test_the_other_station_reviews_then_installs_what_it_ticks(tmp_path):
    a, b = _two(tmp_path)
    _sender(a)
    b._saved = lambda: {"operator": {"callsign": "K7ABC", "grid": "EM59"}}
    p = tmp_path / "W9XYZ-station-pack.hspack"
    p.write_bytes(SP.dumps(SP.build(a)))
    assert SP.summary(p)["from"] == "W9XYZ" and SP.summary(p)["plans"] == 1
    doc = SP.read(p)
    before = LP._path(b).read_text() if LP._path(b).exists() else None
    rv = SP.review(b, doc)
    assert rv["other_area"] and rv["area"] == "FN31" and rv["my_area"] == "EM59"
    assert rv["plans"][0]["status"] == "new" and rv["plans"][0]["new_channels"] == 2 and rv["plans"][0]["tick"]
    assert rv["kept"]["new"] == 1 and rv["adhoc"]["new"] == 1
    assert {n["status"] for n in rv["nets"]} >= {"new"}
    assert (LP._path(b).read_text() if LP._path(b).exists() else None) == before          # review changes nothing
    tue = next(n["i"] for n in rv["nets"] if n["name"] == "Tuesday Net")
    r = SP.install(b, doc, {"plans": [0], "kept": True, "adhoc": True, "nets": [tue]})
    assert r["plans"] == 1 and r["channels"] == 2 and r["kept"] == 1 and r["adhoc"]["added"] == 1
    assert r["nets"]["added"] == 1 and r["from"] == "W9XYZ"
    names = {n["name"] for n in b.cfg["schedule"]}
    assert "Tuesday Net" in names and "No Radio Net" not in names                         # only what was ticked
    d = LP._load(b)
    ent = d["ingested"][PLAN_URL]
    assert ent["via"] == "W9XYZ" and ent["title"] == "County ARES Plan" and len(ent["frequencies"]) == 2
    t = LP.Plans(b).consolidated()
    assert any(x["via"] == "W9XYZ" for x in t["read"])
    assert any(r["type"] == "channel" and r["from"] == 146.94 for bnd in t["bands"] for r in bnd["rows"])
    rv2 = SP.review(b, doc)                                                               # again: nothing new
    assert rv2["plans"][0]["status"] == "same" and not rv2["plans"][0]["tick"] and rv2["kept"]["new"] == 0


def test_a_plan_read_differently_here_is_offered_only_when_theirs_is_newer(tmp_path):
    a, b = _two(tmp_path)
    _sender(a)
    LP._save(b, {"ingested": {PLAN_URL: {"at": 3000.0, "title": "County ARES Plan", "url": PLAN_URL, "authority": "local",
                                         "segments": [], "frequencies": [_freq(146.94, "Command net", -0.6, 100.0)]}}})
    doc = SP.parse(SP.dumps(SP.build(a)))
    it = SP.review(b, doc)["plans"][0]
    assert it["status"] == "differs" and it["only_theirs"] == 1 and it["only_mine"] == 0 and not it["tick"]   # mine is newer


def test_a_bad_or_hostile_pack_is_refused_or_cleaned(tmp_path):
    for bad in (b"not a pack", gzip.compress(b'{"schema": "other"}'), json.dumps({"schema": SP.SCHEMA}).encode()[:-3]):
        try:
            SP.parse(bad)
            raise AssertionError(bad)
        except ValueError as e:
            assert "station pack" in str(e)
    doc = SP.parse(json.dumps({"schema": SP.SCHEMA, "from": "<b>K7ABC</b>", "area": "zz99", "plans": [
        {"title": "x" * 500, "url": "javascript:alert(1)", "authority": "fcc",
         "frequencies": [{"freq_mhz": 9999, "use": "no"}, {"freq_mhz": 146.52, "use": "ok", "source_url": "file:///c"}],
         "segments": "nope"}, {"no": "title"}]}).encode())
    p = doc["plans"]
    assert doc["from"] == "BK7ABC/B" and doc["area"] is None and len(p) == 1
    assert len(p[0]["title"]) == 160 and p[0]["url"] is None and p[0]["authority"] == "local"
    assert [f["freq_mhz"] for f in p[0]["frequencies"]] == [146.52] and not p[0]["frequencies"][0]["source_url"]
    assert p[0]["segments"] == []


def test_a_pack_goes_out_and_is_reviewed_and_installed_over_http(tmp_path):
    import base64
    import threading
    from station.server import serve
    from tests.test_einstein import _setup
    from tests.test_varalink import _post
    st, rid, m, clk, e = _setup(tmp_path)
    _sender(st)
    st.cfg["schedule"] = [{"id": "n1", "name": "Tuesday Net", "freq_mhz": 146.94, "mode": "FM", "start": "19:00",
                           "duration_min": 60, "repeat": {"freq": "weekly", "weekdays": ["Tue"]}}]
    srv = serve(st, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        import urllib.request
        av = json.loads(urllib.request.urlopen(base + "/api/pack/available").read())
        assert len(av["plans"]) == 2 and av["nets"] == 1
        b = _post(base, "/api/pack/build", {"parts": ["plans", "nets"], "own_files": False})
        assert b["name"] == "W9XYZ-station-pack.hspack" and b["counts"]["plans"] == 1 and b["counts"]["kept"] == 0
        inbox = st.data / "vara" / "radios" / rid / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "K7ABC-station-pack.hspack").write_bytes(base64.b64decode(b["data"]))
        f = next(x for x in m.view()["inbox"] if x["name"] == "K7ABC-station-pack.hspack")
        assert f["pack"]["plans"] == 1 and f["pack"]["nets"] == 1
        with urllib.request.urlopen(base + "/api/vara/view/K7ABC-station-pack.hspack") as r:
            assert b"County ARES Plan" in r.read()
        rv = _post(base, "/api/pack/review", {"name": "K7ABC-station-pack.hspack"})
        assert rv["plans"][0]["status"] == "same" and rv["nets"][0]["status"] in ("same", "update")   # its own pack
    finally:
        srv.shutdown()


def test_the_panel_has_share_and_review():
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="packDlg"' in idx and "function vSharePanel(one,r)" in idx and '"/api/pack/build"' in idx
    assert 'data-vpack="${esc(it.name)}"' in idx and 'data-vpack="${esc(f.name)}"' in idx            # chat and inbox
    assert '"/api/pack/review"' in idx and '"/api/pack/install"' in idx and "data-vsp=" in idx


def test_the_ask_side_taps_pack_and_the_owner_chooses_what_it_shares():
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'const V_ASK=["PACK",' in idx and "data-vasknow" in idx and "f.requestSubmit()" in idx
    assert "📦 Band plan &amp; nets for my station" in idx and "data-einshare=" in idx
