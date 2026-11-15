"""Local plans (station/localplans.py): the area's clubs, band plan and ARES / RACES plans from one search, kept only
when the operator confirms them, saved offline, and used to name a radio's frequency (owner 2026-11-15)."""
import base64
import json
import threading
import urllib.request

import pytest

from station import localplans as LP
from station.server import serve
from tests.test_agent import _station, xai_key  # noqa: F401
from tests.test_history import _post

ARES = {"freq_mhz": 146.94, "mode": "FM", "offset_mhz": -0.6, "tone_hz": 103.5, "kind": "repeater",
        "use": "County ARES primary", "priority": "primary", "org": "County ARES",
        "source_url": "https://example.org/ares-plan.pdf",
        "net": {"name": "County ARES Net", "weekdays": ["Tue"], "start": "19:30", "time_zone": "local", "repeat": "weekly"}}
SIMPLEX = {"freq_mhz": 147.48, "mode": "FM", "kind": "simplex", "use": "Tactical simplex 1", "priority": "alternate",
           "org": "County ARES", "source_url": "https://example.org/ares-plan.pdf"}
NOSRC = {"freq_mhz": 146.52, "mode": "FM", "kind": "simplex", "use": "Calling"}
ANSWER = {"clubs": [{"name": "Springfield Amateur Radio Club", "url": "https://example.org/", "area": "Springfield",
                     "emcomm": False, "repeaters": ["146.940 -0.6 PL 103.5"]},
                    {"name": "County ARES", "url": "https://example.org/ares", "emcomm": True}],
          "documents": [{"title": "County ARES Communications Plan 2026", "url": "https://example.org/ares-plan.pdf",
                         "kind": "ares_plan", "org": "County ARES", "date": "2026-03", "public": True},
                        {"title": "RACES members plan", "url": "https://example.org/races", "kind": "races_plan",
                         "public": False}],
          "frequencies": [ARES, SIMPLEX, NOSRC]}


def _resp(obj, opened=()):
    return {"output": [{"type": "web_search_call", "action": {"type": "open_page", "url": u}} for u in opened]
            + [{"type": "message", "content": [{"type": "output_text", "text": "```json\n" + json.dumps(obj) + "\n```"}]}],
            "usage": {"cost_in_usd_ticks": 3_000_000_000}}


def _plans(tmp_path, answer=ANSWER, fetched=None):
    st = _station(tmp_path)
    st._save({"operator": {"grid": "EN49ab"}})
    sent, got = [], fetched if fetched is not None else []

    def post(key, body, timeout):
        sent.append(body)
        return _resp(answer, ["https://example.org/ares-plan.pdf"])

    def fetch(url):
        got.append(url)
        return b"%PDF-1.4 a plan", "application/pdf"
    return st, LP.Plans(st, post=post, fetch=fetch), sent, got


def test_a_search_proposes_and_nothing_is_kept_until_confirmed(tmp_path, xai_key):
    st, p, sent, got = _plans(tmp_path)
    s = p.search({"km": 60})
    q = sent[0]["input"][0]["content"]
    assert "60 km" in q and "frequency coordinator" in q and "ICS-205" in q and "members-only" in q
    assert "latitude" in q and "EN49" in q                                 # a rounded position only
    assert {f["use"] for f in s["frequencies"]} == {"County ARES primary", "Tactical simplex 1"}
    assert "Calling: no source page" in s["left_out"] and s["kept"] == [] and s["cost_usd"] == 0.3
    ares = next(f for f in s["frequencies"] if f["use"] == "County ARES primary")
    assert ares["source_opened"] and ares["band"] == "2 m" and ares["plan_says"] == "FM repeater outputs"
    assert [c["emcomm"] for c in s["clubs"]] == [False, True]
    p.save_copies()                                                       # the public plan saved for an outage
    s = p.state()
    doc = next(x for x in s["documents"] if x["kind"] == "ares_plan")
    assert doc["saved"]["path"].endswith(".pdf") and got == ["https://example.org/ares-plan.pdf"]
    races = next(x for x in s["documents"] if x["kind"] == "races_plan")
    assert races["saved"] is None                                          # members only: never fetched
    path, ctype, name = p.doc_file(doc["saved"]["id"])
    assert path.read_bytes().startswith(b"%PDF") and ctype == "application/pdf" and name.endswith(".pdf")
    assert p.doc_file("../../etc") is None


def test_kept_channels_name_the_radio_frequency_and_a_new_search_says_what_changed(tmp_path, xai_key):
    st, p, _, _ = _plans(tmp_path)
    s = p.search()
    ids = [f["id"] for f in s["frequencies"]]
    s = p.keep(ids)
    assert [k["use"] for k in s["kept"]] == ["County ARES primary", "Tactical simplex 1"]
    lab = p.label(146.94)
    assert lab["channel"]["use"] == "County ARES primary" and lab["plan"] == "FM repeater outputs"
    assert p.label(146.34)["channel"]["use"] == "County ARES primary"     # the repeater's input
    assert p.label(146.52)["channel"] is None and "calling" in p.label(146.52)["plan"]
    p.post = lambda key, body, timeout: _resp(dict(ANSWER, frequencies=[ARES]), ["https://example.org/ares-plan.pdf"])
    s = p.search()
    gone = s["changes"]["gone"]
    assert len(gone) == 1 and next(k for k in s["kept"] if k["id"] == gone[0])["use"] == "Tactical simplex 1"
    s = p.drop(gone)
    assert [k["use"] for k in s["kept"]] == ["County ARES primary"]


def test_a_plans_net_goes_on_the_schedule(tmp_path, xai_key):
    st, p, _, _ = _plans(tmp_path)
    s = p.search()
    p.keep([f["id"] for f in s["frequencies"]])
    ares = next(k for k in p.state()["kept"] if k["net"])
    out = p.add_net(ares["id"])
    assert out["added"] == "County ARES Net"
    assert any(n["name"] == "County ARES Net" and n["freq_mhz"] == 146.94 for n in out["schedule"])
    simplex = next(k for k in p.state()["kept"] if not k["net"])
    with pytest.raises(ValueError, match="no net schedule"):
        p.add_net(simplex["id"])


def test_the_operators_own_plan_file_is_read_and_kept_offline(tmp_path, xai_key):
    st, p, _, _ = _plans(tmp_path)
    asked = []
    p.extract = lambda key, sys, user: asked.append(user) or {"frequencies": [SIMPLEX, dict(ARES, freq_mhz=7.2405,
                                                                                         mode="LSB", kind="hf_net",
                                                                                         use="Section HF net")]}
    s = p.add_file("members plan.txt", b"Tactical simplex 1: 147.480 FM\nSection HF net 7.2405 LSB")
    assert "147.480" in asked[0] and s["found"] == 2
    f = next(x for x in s["frequencies"] if x["use"] == "Section HF net")
    assert f["source_file"] == "members plan.txt" and f["band"] == "40 m"
    rec = s["files"][0]
    assert p.doc_file(rec["id"])[0].read_bytes().startswith(b"Tactical")
    with pytest.raises(ValueError, match="PDF, Word"):
        p.add_file("plan.exe", b"MZ")


def test_plans_over_http_and_the_band_plan(tmp_path, xai_key):
    st, p, _, _ = _plans(tmp_path)
    st._localplans = p
    srv = serve(st, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        s = _post(base, "/api/localplans/search", {"km": 50})
        assert s["km"] == 50 and len(s["frequencies"]) == 2
        s = _post(base, "/api/localplans/keep", {"ids": [s["frequencies"][0]["id"]]})
        assert len(s["kept"]) == 1
        p.extract = lambda key, sys, user: {"frequencies": [SIMPLEX]}
        s = _post(base, "/api/localplans/file", {"name": "plan.txt", "data": base64.b64encode(b"147.48").decode()})
        sid = s["files"][0]["id"]
        with urllib.request.urlopen(base + f"/api/localplans/doc/{sid}") as r:
            assert r.headers["Content-Disposition"].startswith("attachment") and r.headers["X-Content-Type-Options"] == "nosniff"
            assert r.read() == b"147.48"
        with urllib.request.urlopen(base + "/api/bandplan") as r:
            bp = json.loads(r.read())
        assert any(b["band"] == "2 m" for b in bp["bands"])
        with pytest.raises(urllib.error.HTTPError):
            _post(base, "/api/localplans/settings", {"km": 1000})
    finally:
        srv.shutdown()


def test_no_key_and_no_place_are_said_plainly(tmp_path):
    st = _station(tmp_path)
    p = LP.Plans(st, post=lambda *a: {})
    with pytest.raises(ValueError, match="xAI key"):
        p.search()
