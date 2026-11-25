"""The live station end to end with a fake Whisper: segmenting, enrichment, log, server, schedule."""
import copy
import json
import threading
import time
import urllib.request
from datetime import datetime

import numpy as np
import pytest

from station import engine
from station.callbook import Callbook
from station.core import Station, speaker_of
from station.segmenter import Segmenter
from station.server import serve
from station.textclean import collapse_repeats, max_tokens


class ScriptGate:
    def __init__(self, pattern):
        self.p = list(pattern)

    def is_speech(self, _f):
        return self.p.pop(0) if self.p else False


def run(seg, n):
    out = []
    for _ in range(n):
        out += list(seg.feed(np.zeros(512, np.float32)))
    return out


def test_segmenter_start_partials_end_and_kerchunk():
    seg = Segmenter(ScriptGate([False] * 5 + [True] * 70 + [False] * 40), frame_ms=32, min_speech_ms=400,
                    hangover_ms=320, preroll_ms=96, partial_every_s=1.0, clock=lambda: 100.0)
    ev = run(seg, 115)
    kinds = [e[0] for e in ev]
    assert kinds[0] == "start" and kinds[-1] == "end" and kinds.count("audio") == 2
    audio, info = ev[-1][1], ev[-1][2]
    assert not info["kerchunk"] and info["speech_frames"] == 70 and len(audio) == (3 + 70 + 10) * 512
    blip = Segmenter(ScriptGate([True] * 3 + [False] * 20), hangover_ms=320, min_speech_ms=400)
    assert run(blip, 23)[-1][2]["kerchunk"]


def test_segmenter_splits_a_long_carrier_at_speech_pauses():
    """Repeater hang time: the gate never closes, so pieces are cut where the voice pauses (>= 0.8 s)."""
    from station.segmenter import Segmenter

    class Always:
        def is_speech(self, f):
            return True
    rng = np.random.default_rng(1)
    sr, n = 16000, 512
    def speech(s):   # 1 kHz tone with syllable-like bursts over a hiss floor
        t = np.arange(int(sr * s)) / sr
        return (0.3 * np.sin(2 * np.pi * 1000 * t) * (np.sin(2 * np.pi * 3 * t) > -0.3) + 0.003 * rng.standard_normal(len(t)))
    pause = lambda s: 0.003 * rng.standard_normal(int(sr * s))
    audio = np.concatenate([pause(6), speech(4), pause(1.5), speech(5), pause(1.5), speech(3), pause(0.3)]).astype(np.float32)
    seg = Segmenter(Always(), sr, 32, min_speech_ms=400, hangover_ms=900, split_pause_ms=800, min_split_s=2.0, clock=lambda: 0)
    ends = [ev for i in range(0, len(audio) - n + 1, n) for ev in seg.feed(audio[i:i + n]) if ev[0] == "end"]
    pieces = [e[2] for e in ends if not e[2]["kerchunk"]]
    assert len(pieces) == 3 - 1 and all(p["split"] for p in pieces)          # the third is still open (carrier up)
    assert 9 < pieces[0]["duration_s"] < 12 and 5 < pieces[1]["duration_s"] < 8   # 6 s quiet + 4 s, then 5 s + pause


def test_highpass_removes_tone_and_hum(station):
    t = np.arange(16000) / 16000
    hum = (0.2 * np.sin(2 * np.pi * 100 * t) + 0.2 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
    voice = (0.2 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    rid = next(iter(station.radios))
    station.radio_cfg[rid] = dict(station.radio_cfg[rid], gate="carrier")
    out = station.clean(rid, hum + voice)[4000:]
    assert np.sqrt(np.mean(out ** 2)) < 0.16 and np.sqrt(np.mean(out ** 2)) > 0.12      # ~voice only (rms 0.141)
    station.radio_cfg[rid]["highpass_hz"] = 0
    assert station.clean(rid, hum) is hum


def test_probably_noise():
    from station.core import probably_noise
    assert probably_noise("So.", []) and probably_noise("We'll be right back.", []) and probably_noise(".", [])
    assert not probably_noise("Thank you, KC7EZ, good evening.", ["KC7EZ"]) and not probably_noise("No traffic tonight.", [])


def test_loop_guard():
    t, looped = collapse_repeats("Net control this is K7ABC. Thank you. Thank you. Thank you. Thank you. Over.")
    assert looped and t == "Net control this is K7ABC. Thank you. Over."
    assert collapse_repeats("I said no, no, no traffic")[0] == "I said no, traffic"
    assert collapse_repeats("Roger roger, clear") == ("Roger roger, clear", False)
    assert max_tokens(5) == 64 and max_tokens(600) == 440


def test_speaker_guess():
    assert speaker_of("Net control, this is W9XYZ checking in", ["W9XYZ"]) == "W9XYZ"
    assert speaker_of("K7ABC, W9XYZ, go ahead", ["K7ABC", "W9XYZ"]) == "W9XYZ"
    assert speaker_of("no calls", []) is None


class FakeBook(Callbook):
    def __init__(self, known):
        self.known_db, self.qrz, self.roster, self.known, self.con, self.cty = known, None, set(), {}, None, None
        import threading as t; self.lock = t.Lock()

    def fcc(self, call):
        return {"call": call, "name": self.known_db[call]} if call in self.known_db else None

    def validate(self, call):
        return call in self.known_db or call in self.roster

    def card(self, call, qrz_network=False):
        return {"call": call, "name": self.known_db.get(call), "sources": ["FCC"]}


CFG = {"callsign": "W9XYZ", "radios": [{"id": "ftm", "name": "FTM-150R", "device": "NET-REC", "gate": "carrier",
                                         "freq_mhz": 146.94}],
       "schedule": [{"name": "Test net", "radio": "ftm", "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                     "start": "00:00", "duration_min": 1439, "ncs": "K7NET", "freq_mhz": 146.82}],
       "port": 0, "bind": "127.0.0.1", "qrz_online": False}


def wait_for(cond, s=5):
    t = time.time()
    while time.time() - t < s:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def station(tmp_path):
    texts = ["Break break, emergency traffic. Net control, this is K-7-A-B-C, QTH Springfield. Over."]
    st = Station(copy.deepcopy(CFG), lambda: engine.FakeEngine(texts, "fake-final"), lambda: engine.FakeEngine(name="fake-partial"),
                 callbook=FakeBook({"K7ABC": "Pat Example", "W9XYZ": "Pat Q Sample"}), data_dir=tmp_path)
    st.start(listen=False)
    yield st
    st.stop.set()


def test_transmission_flow_enrichment_and_log(station, tmp_path):
    q = station.bus.subscribe()
    station.inject("ftm", np.zeros(16000 * 3, np.float32))
    assert wait_for(lambda: station.tx and station.tx[-1]["status"] == "final")
    tx = station.tx[-1]
    assert tx["callsigns"] == ["K7ABC"] and tx["speaker"] == "K7ABC" and tx["model"] == "fake-final"
    assert {t["term"] for t in tx["terms"]} >= {"QTH", "BREAK BREAK"}
    assert station.hints["ftm"]["net"]["type"] == "emergency" and station.hints["ftm"]["cards"][0]["key"] == "emergency"
    assert station.heard["K7ABC"]["card"]["name"] == "Pat Example"
    kinds = set()
    while not q.empty():
        kinds.add(q.get()[0])
    assert {"tx", "hints", "heard"} <= kinds
    log = list((tmp_path / "logs").glob("*.jsonl"))[0].read_text().splitlines()
    assert json.loads(log[-1])["callsigns"] == ["K7ABC"]
    assert (tmp_path / tx["wav"]).exists()
    again = Station(copy.deepcopy(CFG), lambda: engine.FakeEngine(), callbook=FakeBook({"K7ABC": "Pat"}), data_dir=tmp_path)
    again.load_today()
    assert again.tx[-1]["id"] == tx["id"] and again.heard["K7ABC"]["count"] == 1
    assert again.hints["ftm"]["net"]["type"] == "emergency"


def test_schedule_current_and_retune(station):
    n = station.schedule_now(datetime(2026, 11, 3, 12, 0))
    cur = n["current"]
    assert cur["name"] == "Test net" and cur["retune"] and cur["band"]["band"] == "2 m" and cur["ncs"] == "K7NET"


def test_server_state_events_audio_lookup(station):
    srv = serve(station, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        station.inject("ftm", np.zeros(16000 * 2, np.float32))
        assert wait_for(lambda: station.tx and station.tx[-1]["status"] == "final")
        s = json.loads(urllib.request.urlopen(base + "/api/state").read())
        assert s["callsign"] == "W9XYZ" and s["radios"][0]["band"]["band"] == "2 m" and s["tx"]
        assert b"HAM Sidekick Station" in urllib.request.urlopen(base + "/").read()
        wav = urllib.request.urlopen(f"{base}/audio/{station.tx[-1]['id']}").read()
        assert wav[:4] == b"RIFF"
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/audio/../../etc")
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/api/lookup?call=%3Cscript%3E")
        r = urllib.request.urlopen(base + "/events", timeout=5)
        assert r.readline().strip() == b"event: snapshot"
        r.close()
    finally:
        srv.shutdown()


def test_callbook_validate_rules(tmp_path):
    cb = Callbook(fcc_db=tmp_path / "none.sqlite", cty=tmp_path / "none.dat")
    cb.fcc = lambda c: {"call": c} if c == "W9XYZ" else None
    cb.con = object()
    cb.country = lambda c: {"country": "Canary Islands"} if c.startswith("EA8") else (
        {"country": "United States"} if c[0] in "KNW" else None)
    assert cb.validate("W9XYZ") and not cb.validate("W9THQ")          # US: must be licensed
    assert cb.validate("EA8AB") and not cb.validate("ZZ1")            # foreign: a country + a full call
    cb.roster.add("N0NET"); cb.known.clear()
    assert cb.validate("N0NET")


def test_operator_sets_frequency_persisted_and_stamped(station, tmp_path):
    r = station.set_radio("ftm", "145.900", "fm")
    assert r["freq_mhz"] == 145.9 and r["mode"] == "FM" and r["band"]["band"] == "2 m"
    with pytest.raises(ValueError):
        station.set_radio("ftm", 99999)
    with pytest.raises(ValueError):
        station.set_radio("ftm", 145.9, "XYZ")
    with pytest.raises(KeyError):
        station.set_radio("nope", 145.9)
    station.inject("ftm", np.zeros(16000 * 2, np.float32))
    assert wait_for(lambda: station.tx and station.tx[-1]["status"] == "final")
    assert station.tx[-1]["freq_mhz"] == 145.9
    again = Station(copy.deepcopy(CFG), lambda: engine.FakeEngine(), data_dir=tmp_path)       # restart keeps it
    assert again.radios["ftm"]["freq_mhz"] == 145.9 and again.radios["ftm"]["tuned_at"]


def test_post_radio_requires_json(station):
    srv = serve(station, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/api/radios/ftm"
    try:
        req = urllib.request.Request(url, data=b'{"freq_mhz": 146.52, "mode": "FM"}', method="POST",
                                     headers={"Content-Type": "application/json"})
        assert json.loads(urllib.request.urlopen(req).read())["freq_mhz"] == 146.52
        form = urllib.request.Request(url, data=b"freq_mhz=1", method="POST",
                                      headers={"Content-Type": "application/x-www-form-urlencoded"})
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(form)
        bad = urllib.request.Request(url, data=b'{"freq_mhz": "abc"}', method="POST",
                                     headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(bad)
        assert e.value.code == 400
    finally:
        srv.shutdown()


def test_short_prompt_carries_frequency_and_phonetic_call(station):
    p = station.prompt_for("ftm")
    assert p == "Ham radio net on 146.940 MHz. This is W9XYZ, Whiskey Niner Xray Yankee Zulu. Over." and len(p) < 120
    station.set_radio("ftm", 145.9)
    assert "145.900 MHz" in station.prompt_for("ftm")


def test_raw_ring_keeps_the_last_minutes(tmp_path):
    from station.core import RawRing
    r = RawRing(tmp_path / "raw", keep_min=2)
    for i in range(4):
        r.buf, r.t0 = [np.zeros(512, np.float32)], datetime(2026, 11, 2, 16, i)
        r.flush()
    assert sorted(p.name for p in (tmp_path / "raw").glob("*.wav")) == ["20261102-160200.wav", "20261102-160300.wav"]


def test_pause_and_clear_survive_a_restart(station, tmp_path):
    station.inject("ftm", np.zeros(16000 * 3, np.float32))
    assert wait_for(lambda: station.tx and station.tx[-1]["status"] == "final")
    station.set_radio("ftm", 146.94, "FM")
    assert station.set_paused("ftm", True)["paused"] is True
    time.sleep(1.1)                                   # cleared_at is to the second; the log line is earlier
    r = station.clear_radio("ftm")
    assert not [t for t in station.tx if t["radio"] == "ftm"] and "K7ABC" not in station.heard
    assert list((tmp_path / "logs").glob("*.jsonl"))[0].read_text().strip()          # files kept on disk
    again = Station(copy.deepcopy(CFG), lambda: engine.FakeEngine(), callbook=FakeBook({"K7ABC": "Pat"}), data_dir=tmp_path)
    again.load_today()
    assert again.radios["ftm"]["paused"] and again.radios["ftm"]["cleared_at"] == r["cleared_at"]
    assert again.radios["ftm"]["freq_mhz"] == 146.94                                # tuning kept beside pause/clear
    assert not again.tx and not again.heard                                          # cleared stays cleared
    assert station.set_paused("ftm", False)["paused"] is False


def test_segmenter_flush_on_pause():
    from station.segmenter import Segmenter

    class Always:
        def is_speech(self, f):
            return True
    seg = Segmenter(Always(), 16000, 32, clock=lambda: 0)
    for _ in range(40):
        list(seg.feed(np.full(512, 0.1, np.float32)))
    ev = list(seg.flush())
    assert ev[0][0] == "end" and ev[0][2]["paused"] and not seg.active and list(seg.flush()) == []


class FakeRemote:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, 0

    def reachable(self):
        return self.ok

    def transcribe(self, wav, prompt, highpass_hz):
        self.calls += 1
        assert wav[:4] == b"RIFF" and prompt == "" and highpass_hz == 300
        return {"text": "Net control, this is K7ABC in Springfield, no traffic.", "model": "fake-large", "audio_s": 3.0, "elapsed_s": 0.1}


def test_accurate_pass_beside_the_live_text(tmp_path):
    cfg = copy.deepcopy(CFG); cfg["accurate"] = {"auto_after_min": 0}
    st = Station(cfg, lambda: engine.FakeEngine(["Net control this is K7-ABC, over."]), callbook=FakeBook({"K7ABC": "Pat"}), data_dir=tmp_path)
    st._accurate_remote = FakeRemote()
    st.start(listen=False)
    try:
        q = st.bus.subscribe()
        st.inject("ftm", np.zeros(16000 * 3, np.float32))
        assert wait_for(lambda: st.tx and st.tx[-1]["status"] == "final")
        live = st.tx[-1]["text"]
        j = st.accurate_now("ftm")
        assert j["total"] == 1 and j["state"] in ("queued", "running", "done")
        assert wait_for(lambda: st.accurate.status()[0]["state"] == "done")
        tx = st.tx[-1]
        assert tx["text"] == live and tx["accurate"]["text"].startswith("Net control, this is K7ABC")   # live kept
        assert tx["accurate"]["model"] == "fake-large" and st.accurate.status()[0]["done"] == 1
        p = st.winlink_preview("ftm")
        assert p["drafts"][0]["rows"][0]["sub"].startswith("Net control, this is K7ABC in Springfield") and p["accurate_missing"] == 0
        assert p["accurate"]["state"] == "done"
        kinds = set()
        while not q.empty():
            kinds.add(q.get()[0])
        assert "accurate" in kinds
        assert st.accurate_now("ftm")["state"] == "done" and st._accurate_remote.calls == 1   # nothing left to do
        st.accurate_now("ftm", force=True)                                                 # redo on request
        assert wait_for(lambda: st._accurate_remote.calls == 2 and st.accurate.status()[0]["state"] == "done")
        again = Station(copy.deepcopy(cfg), lambda: engine.FakeEngine(), callbook=FakeBook({"K7ABC": "Pat"}), data_dir=tmp_path)
        again.load_today()
        assert again.tx[-1]["accurate"]["text"] == tx["accurate"]["text"]                    # survives a restart
    finally:
        st.stop.set()


def test_accurate_pass_unreachable_and_auto(tmp_path):
    from datetime import datetime, timedelta
    cfg = copy.deepcopy(CFG); cfg["accurate"] = {"auto_after_min": 15, "live": False}
    st = Station(cfg, lambda: engine.FakeEngine(["Testing, this is W9XYZ."]), callbook=FakeBook({}), data_dir=tmp_path)
    st._accurate_remote = FakeRemote(ok=False)
    st.start(listen=False)
    try:
        st.inject("ftm", np.zeros(16000 * 2, np.float32))
        assert wait_for(lambda: st.tx and st.tx[-1]["status"] == "final")
        st.accurate.tick(datetime.now())                                   # not over yet: nothing queued
        assert st.accurate.status() == []
        st.accurate.tick(datetime.now() + timedelta(minutes=16))           # 16 quiet minutes: queued by itself
        assert wait_for(lambda: st.accurate.status() and st.accurate.status()[0]["state"] == "unreachable")
        assert st.accurate.status()[0]["auto"] and not st.tx[-1].get("accurate")
    finally:
        st.stop.set()


def test_wer_compares_numbers_and_callsigns():
    from station.wer import TEST_TEXT, wer, words
    assert words("145.9 W9XYZ") == words("one four five point nine W 9 X Y Z")
    assert wer(TEST_TEXT, TEST_TEXT, "W9XYZ")["wer"] == 0
    r = wer(TEST_TEXT, "This is W9XOZ testing speech to text on 145.9. The quick brown fox jumps over the lazy dog.", "W9XYZ")
    assert 0.2 < r["wer"] < 0.4 and r["words"] == len(words(TEST_TEXT, "W9XYZ"))


def test_score_test_and_history(tmp_path):
    from station.wer import TEST_TEXT
    cfg = copy.deepcopy(CFG); cfg["accurate"] = {"auto_after_min": 0, "live": False}     # the score-first path
    st = Station(cfg, lambda: engine.FakeEngine([TEST_TEXT.replace("lazy", "lacy")]), callbook=FakeBook({"W9XYZ": "T"}), data_dir=tmp_path)
    st._accurate_remote = FakeRemote()
    with pytest.raises(ValueError):
        st.score_test("ftm")
    st.start(listen=False)
    try:
        st.inject("ftm", np.zeros(16000 * 3, np.float32))
        assert wait_for(lambda: st.tx and st.tx[-1]["status"] == "final")
        r = st.score_test("ftm")
        assert 0 < r["live"]["wer"] < 0.1 and r["accurate_pending"]
        assert wait_for(lambda: st.tx[-1].get("accurate"))
        r2 = st.score_test("ftm", st.tx[-1]["id"])
        assert "accurate" in r2 and r2["accurate"]["wer"] > 0.5            # the fake Mac text is a different sentence
        h = st.test_history()
        assert len(h) == 1 and "accurate" in h[0]                          # the re-score replaced the first
    finally:
        st.stop.set()


def test_accurate_pass_follows_each_transmission(tmp_path):
    cfg = copy.deepcopy(CFG); cfg["accurate"] = {"auto_after_min": 0}           # live is the default
    st = Station(cfg, lambda: engine.FakeEngine(["Net control this is K7-ABC, over.", "W9XYZ, go ahead."]),
                 callbook=FakeBook({"K7ABC": "Pat"}), data_dir=tmp_path)
    st._accurate_remote = FakeRemote()
    st.start(listen=False)
    try:
        for _ in range(2):
            st.inject("ftm", np.zeros(16000 * 3, np.float32))
            assert wait_for(lambda: st.tx and st.tx[-1]["status"] == "final" and st.tx[-1].get("accurate"))
        jobs = st.accurate.status()
        assert len(jobs) == 1 and jobs[0]["state"] == "done" and jobs[0]["done"] == jobs[0]["total"] == 2   # one job per net
        assert st._accurate_remote.calls == 2
    finally:
        st.stop.set()


def test_accurate_pass_needs_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("EMCOMM_STT_KEY", raising=False)
    st = Station(copy.deepcopy(CFG), lambda: engine.FakeEngine(["Testing."]), callbook=FakeBook({}), data_dir=tmp_path)
    st.root = tmp_path                                                   # no config/secrets.env here
    st.start(listen=False)
    try:
        assert not st.accurate.enabled
        st.inject("ftm", np.zeros(16000 * 2, np.float32))
        assert wait_for(lambda: st.tx and st.tx[-1]["status"] == "final")
        assert st.accurate.status() == []                                # nothing sent anywhere
        st.accurate_now("ftm")
        assert wait_for(lambda: st.accurate.status()[0]["state"] == "error")
        assert "secrets.env" in st.accurate.status()[0]["error"]
    finally:
        st.stop.set()


def test_accurate_echo_of_the_prompt_keeps_the_live_text(tmp_path):
    cfg = copy.deepcopy(CFG); cfg["accurate"] = {"auto_after_min": 0}
    st = Station(cfg, lambda: engine.FakeEngine(["I'm going to test here, speech to text."]), callbook=FakeBook({}), data_dir=tmp_path)

    class Echo(FakeRemote):
        def transcribe(self, wav, prompt, highpass_hz):
            return {"text": " Radio net on 442.100 MHz.", "model": "fake-large", "audio_s": 3.0}
    st._accurate_remote = Echo()
    st.start(listen=False)
    try:
        st.inject("ftm", np.zeros(16000 * 3, np.float32))
        assert wait_for(lambda: st.tx and st.tx[-1].get("accurate_echo"))
        tx = st.tx[-1]
        assert "accurate" not in tx and ics_view(tx)["text"].startswith("I'm going to test")
        assert st.accurate.status()[0]["state"] == "done" and st.winlink_preview("ftm")["accurate_missing"] == 0
        again = Station(copy.deepcopy(cfg), lambda: engine.FakeEngine(), callbook=FakeBook({}), data_dir=tmp_path)
        again.load_today()
        assert again.tx[-1].get("accurate_echo") and "accurate" not in again.tx[-1]
    finally:
        st.stop.set()


def ics_view(t):
    from station.ics import view
    return view(t)


def test_template_loop():
    from station.textclean import template_loop
    assert template_loop("I'm a lawyer, I'm a tester, I'm an exercise, I'm a speech-to-text, I'm a machine, I'm a computer, I'm a computer")
    assert not template_loop("Net control, this is K7ABC in Springfield, no traffic, thank you, over.")
    assert not template_loop("Good evening, good signal there. Got you now. KW7, Dale and Norma, thanks.")


def test_accurate_available_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("EMCOMM_STT_KEY", raising=False)
    cfg = copy.deepcopy(CFG); cfg["accurate"] = {"auto_after_min": 0}
    st = Station(cfg, lambda: engine.FakeEngine(["Testing."]), callbook=FakeBook({}), data_dir=tmp_path)
    st._accurate_remote = FakeRemote(ok=False)
    st.start(listen=False)
    try:
        assert st.accurate.available()                                   # on, not yet known to be down
        st.inject("ftm", np.zeros(16000 * 2, np.float32))
        assert wait_for(lambda: st.accurate.status() and st.accurate.status()[0]["state"] == "unreachable")
        assert not st.accurate.available() and st.snapshot()["accurate_available"] is False   # nothing to wait for
    finally:
        st.stop.set()


def test_qrz_login_described_in_plain_words():
    from hamkit.qrz import describe
    ok, m = describe({"Key": "k", "SubExp": "Fri Jan 24 00:00:00 2027"})
    assert ok and "until Fri Jan 24" in m
    ok, m = describe({"Key": "k", "SubExp": "non-subscriber"})
    assert ok and "no XML Logbook Data subscription" in m
    ok, m = describe({"Error": "Username/password incorrect"})
    assert not ok and "refused" in m


def test_help_card_is_served():
    import urllib.request
    from station.server import STATIC
    html = (STATIC / "card.html").read_text(encoding="utf-8")
    assert "side 1 of 2" in html and "side 2 of 2" in html and "<title>" in html and "<!--DOWNLOAD_QR-->" in html
    assert 'href="/help"' in (STATIC / "index.html").read_text(encoding="utf-8")


def test_station_yaml_with_byte_order_mark_loads(tmp_path):
    """Windows PowerShell 5 writes UTF-8 with a BOM; the station must still read it (a laptop station install, 2026-11-04)."""
    from station.core import load_config
    p = tmp_path / "station.yaml"
    p.write_bytes(b"\xef\xbb\xbf# This station's settings\ncallsign: W9XYZ\nradios: []\n")
    c = load_config(p)
    assert c["callsign"] == "W9XYZ" and c["radios"] == []


def _final_text(tmp_path, texts):
    cfg = copy.deepcopy(CFG); cfg["callsign"] = "W9XYZ"
    eng = engine.FakeEngine(texts, "fake-final")
    st = Station(cfg, lambda: eng, data_dir=tmp_path)
    st.start(listen=False)
    try:
        st.inject(cfg["radios"][0]["id"], np.zeros(16000, np.float32))
        for _ in range(100):
            if st.tx[-1]["status"] == "final":
                break
            time.sleep(0.05)
        return st.tx[-1], eng
    finally:
        st.stop.set()


def test_the_operators_call_planted_by_the_prompt_is_dropped(tmp_path):
    """The live prompt spells the operator's call; Whisper wrote it into another station's turn (2026-11-06)."""
    tx, eng = _final_text(tmp_path, ["W9XYZ, Whiskey Nine X-ray.", "Roger, Springfield. Roger."])
    assert tx["text"] == "Roger, Springfield. Roger." and "W9XYZ" not in tx["callsigns"]
    assert "W9XYZ" not in (eng.last_prompt or "")                  # the second decode had no call in its prompt


def test_the_operators_own_call_is_kept_when_the_second_decode_hears_it_too(tmp_path):
    for second in ("This is W9XYH testing.", "This is Whiskey Niner X-ray Yankee Zulu testing."):
        tx, eng = _final_text(tmp_path, ["This is W9XYZ testing.", second])
        assert tx["text"] == "This is W9XYZ testing." and eng.calls == 2


def test_no_second_decode_without_the_operators_call(tmp_path):
    tx, eng = _final_text(tmp_path, ["Roger, Springfield."])
    assert eng.calls == 1


def test_a_missing_input_that_windows_has_now_is_rescanned_once_a_minute(tmp_path, monkeypatch):
    import sys, types
    from station import core, radios as rmod
    calls = []
    fake = types.SimpleNamespace(_terminate=lambda: calls.append("t"), _initialize=lambda: calls.append("i"))
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    monkeypatch.setattr(rmod, "fresh_inputs", lambda: ["Digirig Lite NET-REC"])
    st = Station(copy.deepcopy(CFG), lambda: engine.FakeEngine(), data_dir=tmp_path)
    monkeypatch.setattr(core.Station, "_rescan_at", 0.0)
    assert st._audio_rescan("Digirig Lite NET-REC") and calls == ["t", "i"]
    assert not st._audio_rescan("Digirig Lite NET-REC")                # not again within a minute
    monkeypatch.setattr(core.Station, "_rescan_at", 0.0)
    assert not st._audio_rescan("Something else") and calls == ["t", "i"]


def test_sidekick_card_is_served_and_linked():
    from station.server import STATIC
    html = (STATIC / "sidekick_card.html").read_text(encoding="utf-8")
    assert "side 1 of 2" in html and "side 2 of 2" in html and "<title>Einstein Card</title>" in html
    assert "Use Einstein" in html and "Set up once" in html and "Transmit test" in html and "Your region" in html
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    assert idx.count('href="/help/sidekick"') == 2                 # Settings -> Station agent, and Einstein's card
    from station.server import HELP_CARDS
    assert HELP_CARDS["/help/sidekick"] == "sidekick_card.html"


def test_help_has_six_cards_each_linking_the_others():
    from station.server import HELP_CARDS, STATIC
    pages = {"/help": "card.html", "/help/sidekick": "sidekick_card.html", "/help/conversation": "conversation_card.html",
             "/help/vara": "vara_card.html", "/help/bandplan": "bandplan_card.html", "/help/adhoc": "adhoc_card.html"}
    for path, src in pages.items():
        assert HELP_CARDS[path] == src
        html = (STATIC / src).read_text(encoding="utf-8")
        nav = html[html.index('<nav class="card-nav"'):html.index("</nav>")]
        assert all(f'href="{p}"' in nav for p in pages)             # Help: every card reaches the others
        assert f'href="{path}" aria-current="page"' in nav
        assert 'href="https://travislhilton.github.io/church-emcomm-wnlk-forms/training/handouts/business-card-avery-5371.html"' in nav   # owner 11-20: the shared card
        assert "side 1 of 2" in html and "side 2 of 2" in html
    conv = (STATIC / "conversation_card.html").read_text(encoding="utf-8")
    assert "Record a Conversation" in conv and "Include conversations" in conv and "conversations only" in conv
    vara = (STATIC / "vara_card.html").read_text(encoding="utf-8")
    assert "Data (Winlink / VARA)" in vara and "Shared with Winlink Express" in vara and "take turns" in vara
    assert "8310" in vara and "Abort" in vara and "encrypted" in vara
    bp = (STATIC / "bandplan_card.html").read_text(encoding="utf-8")
    assert "Find local plans" in bp and "Who speaks first" in bp and "97.305" in bp
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'href="/help/vara"' in idx and idx.count('href="/help/bandplan"') == 2
    ad = (STATIC / "adhoc_card.html").read_text(encoding="utf-8")      # owner 2026-11-16: ad hoc channels card
    assert "445.025" in ad and "8 characters" in ad and "CHIRP" in ad and "Install" in ad and "Export my set" in ad
    assert 'href="/help/adhoc"' in idx and "★ Install" in vara and "Ad hoc channels" in bp


def test_end_button_names_a_conversation_outside_a_net():
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'const w=isNet?"net":"conversation"' in idx and "End ${w}</button>" in idx and "End the ${w} now?" in idx
    assert idx.count("endAsk(rid,key,!!sn)") == 1 and idx.count("endAsk(r.id,key,!!sn)") == 1     # both End buttons
    assert '${c.scheduled?"Net ended":"Ended"} by you' in idx


def test_the_log_always_keeps_a_height_on_a_wide_screen():
    """A busy evening on an iPad in landscape: the radio card and its alerts took the whole column and the log got
    0 px (2026-11-15). In the full-height layout the log keeps a minimum and the column scrolls instead."""
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    block = idx.split("@media (min-width:901px) and (min-height:820px){", 1)[1].split("\n}", 1)[0]
    assert ".rcol>.logbox{flex:1;min-height:min(560px,70dvh)" in block


def test_a_radio_nets_row_opens_its_menu_with_skip_for_that_date():
    """Owner 2026-11-15: skip today's net from the radio's Nets list. The row's menu also closed itself at once (the
    page's click-away handler saw a click outside the menu): a row click no longer closes it."""
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'if(!e.target.closest("#rpick")&&!e.target.closest("[data-rn]"))closePick();' in idx
    assert "data-skipocc" in idx and "/api/alerts/${enc(sk.dataset.skipocc)}/${sk.dataset.v}" in idx


def test_settings_has_a_panel_per_tab_and_links_open_their_tab():
    """Owner 2026-11-15: Settings redesigned into tabs. Every tab has its panel, every field the Save bar saves is on
    one, and the dashboard's links (AI costs, This PC, the xAI key) open Settings on their own tab."""
    import re
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    dlg = idx.split('<dialog id="settings"', 1)[1].split("</dialog>", 1)[0]
    tabs, panels = re.findall(r'data-stab="(\w+)"', dlg), re.findall(r'data-spanel="(\w+)"', dlg)
    assert tabs == panels and len(tabs) == 7
    for name in ("callsign", "name", "grid", "winlink_dir", "winlink_account", "reach_km", "ai_summary", "keep_awake",
                 "keep_weeks"):
        assert f'name="{name}"' in dlg and f"{name}:[" in idx            # in the form, and in SETF (its tab, dirty)
    for el in ("costSet", "pcSet", "keySet", "agentSet", "voiceSet", "grokSet", "lnSet", "learnSet", "alertSet",
               "shareSet", "mgmtKeySet", "setSave", "setErr", "wlNone", "keepNote", "dispTheme", "dispClock"):
        assert f'id="{el}"' in dlg
    assert 'function openCosts(){openSettings("costs")}' in idx and 'function openPC(){openSettings("pc")}' in idx
    assert 'openSettings("ai")' in idx


def test_every_pop_up_has_a_close_at_the_top():
    """Owner 2026-11-16: "For any of the pop up views we need a close link/button added so that the user doesn't have to
    scroll all the way to the bottom": a pinned ✕ is added to every dialog without a header bar, through Esc's path."""
    from station.server import STATIC
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'document.querySelectorAll("dialog").forEach(d=>{if(d.querySelector(":scope>.dhead .x' in html
    assert "function closeDlg(d){const ev=new Event(\"cancel\",{cancelable:true})" in html
    assert ".dlgxw{position:sticky" in html


def test_an_open_dashboard_reloads_on_a_new_build_and_the_band_plan_marks_what_is_tuned(tmp_path):
    """Owner 2026-11-16: the ✕ at the top was installed but an open dashboard kept the old page, so every (re)connect
    compares the page's build (/api/page) and reloads (or offers Reload while a pop-up is open or something is being
    typed). And "when a radio/modem is tuned to a frequency show it in the band plan with an indicator"."""
    import json
    import threading
    import urllib.request
    from station.server import STATIC, serve
    from tests.test_varalink import _st
    st, _ = _st(tmp_path)
    srv = serve(st, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/page") as r:
            page = json.loads(r.read())["page"]
    finally:
        srv.shutdown()
    assert len(page) == 16
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "pageCheck()};" in html and 'location.reload();return}' in html and "A new version of the station" in html
    assert "function bpTuned()" in html and "Tuned now:" in html and "data-bptuned" in html and "data-bpgo" in html
    assert "if($(\"bpDlg\")&&$(\"bpDlg\").open&&BP.d){const sig=bpTunedSig()" in html      # retuning redraws it


def test_band_plan_has_a_full_spectrum_view_and_vara_fm_width():
    """Owner 2026-11-16: "another table that shows the full spectrum with all allocated frequencies and all unplanned
    frequencies that are available for voice and for VARA FM and VARA HF"; VARA FM narrow / wide per modem."""
    from station.server import STATIC
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '["all","Full spectrum"]' in html and "<th>Ad hoc voice</th><th>Ad hoc VARA</th>" in html
    assert 'x.mode==="VARA FM"&&(m.cfg.fm_width!=="wide"||x.wide)' in html and '="fm_width"' in html


def test_a_data_radio_column_is_its_vara_workspace_and_the_header_is_grouped():
    """Owner 2026-11-18: "the management of the station list as well as the chats ... and file xfer ... shown under the
    radio, not on a pop up window", and a full UX pass: the pop-up keeps Modem setup and the by-hand link only; a data
    radio shows no nets strip, Coach / Net board or voice log; header tools are grouped and fold behind Menu on a phone."""
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'vp.dataset.vpanel=r.id' in idx and "function renderVaraPanels()" in idx and "function vPanelHtml(r)" in idx
    assert "vChannel(m,ok)" in idx.split("function vPanelHtml(r)")[1].split("function renderVaraPanels()")[0]
    dlg = idx.split("function renderVaraDlg(){")[1].split("\nasync function varaAct")[0]
    assert "vChannel(" not in dlg and "data-vgopanel" in dlg                  # the chat is not drawn twice
    for one in ('$("vMsg")', '$("vCompose")', '$("vThread")', '$("vPresets")'):   # ids are per radio: two chat modems
        assert one not in idx
    assert ".rcol.data>.logbox,.rcol.data>.rnets" in idx and ".rcol.data .toptabs [data-tab=guide]" in idx
    assert ".vpanel[hidden]{display:none!important}" in idx                    # never under a net radio
    assert 'id="hMenu"' in idx and "header.open .hmore{display:contents}" in idx
    more = idx.split('<span class="hmore" id="hMore">')[1].split("</header>")[0]
    for b in ("openReadout", "openRadios", "openSettings", "nightBtn", "openPhone", "helpbtn"):
        assert b in more
    assert 'id="openNets"' in idx.split('id="hMenu"')[0] and 'id="openBandplan"' in idx.split('id="hMenu"')[0]


def test_settings_sections_fold_and_a_link_to_a_setting_opens_its_section():
    """Owner 2026-11-18: "sections are collapsed by default so that users don't have to scroll through long lists"."""
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'd.className="ssec"' in idx and "let open=i===0" in idx and "if(heads.length<2)return" in idx
    assert "Element.prototype.scrollIntoView=function" in idx and "HTMLElement.prototype.focus=function" in idx
    import re
    titles = set(re.findall(r'<h4 class="sec">([^<]+?) <span', idx))
    hints = idx.split("const SSEC_HINT={")[1].split("};")[0]
    assert len(titles) >= 12 and not [t for t in titles if f'"{t}"' not in hints and t not in ("Storage", "AI costs", "Share settings with another station")]


def test_radios_lists_the_audio_outputs_windows_has_now(tmp_path, monkeypatch):
    """An interface moved to another USB port after the station started must show in Transmit → audio out."""
    from station import ptt, radios as rmod
    monkeypatch.setattr(rmod, "fresh_inputs", lambda: ["Digirig Lite"])
    monkeypatch.setattr(ptt, "outputs", lambda: ["Digirig Lite VARA FM 2", "Speakers"])     # the stale in-process list
    monkeypatch.setattr(ptt, "fresh_outputs", lambda: ["Digirig Lite", "Speakers"])
    monkeypatch.setattr(ptt, "hid_devices", lambda: [])
    st = Station(copy.deepcopy(CFG), lambda: engine.FakeEngine(), data_dir=tmp_path)
    assert st.radio_list()["outputs"] == ["Digirig Lite", "Speakers"]
    monkeypatch.setattr(ptt, "fresh_outputs", lambda: None)                                 # unreadable: the old list
    assert st.radio_list()["outputs"] == ["Digirig Lite VARA FM 2", "Speakers"]


def test_a_radio_card_has_a_settings_button_that_opens_that_radio():
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'data-rset="${esc(r.id)}"' in idx and "⚙ Settings…</button></div>`" in idx          # on every radio's card
    assert 'closest("[data-rset]");if(b)openRadios(b.dataset.rset)' in idx
    assert "async function openRadios(rid)" in idx and '<details class="rad" data-i="${i}"' in idx   # one folded row a radio
    assert ".rcol.data .cardbtns [data-rset]" not in idx                                        # a data radio keeps it


def test_the_dashboard_reloads_the_chat_when_a_file_or_link_test_starts():
    """On the air 2026-11-18: a file went out and no progress showed: the chat was only re-read when the file ended,
    so its line still said "waiting for a link"."""
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    full = idx[idx.index('const full=['):idx.index('].includes(d.event)')]
    for ev in ("file_sending", "file_receiving", "test_started", "test_done", "test_received"):
        assert f'"{ev}"' in full
    assert "function vXfer(" in idx and "data-vstoprx" in idx and 'aria-valuenow="${pc}"' in idx


def test_an_open_dashboard_reloads_after_an_update_unless_something_is_typed():
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    i = idx.index("async function pageCheck()")
    body = idx[i:i + 1600]
    assert 'String(ae.value||"").trim()!==""' in body and "window._pageRetry=setInterval(pageCheck,5000)" in body


def test_a_fold_in_a_vara_panel_stays_open_across_redraws():
    """Owner 2026-11-24: "When I click on the arrow next to 'What Einstein does on the air' an explanation briefly pops up
    and goes away" — the panel is redrawn every few seconds and drew every <details> closed. Each fold in the VARA panels
    and window now carries data-vkeep and is drawn open while the operator has it open."""
    import re
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    vara = idx.split("const VA={")[1].split("\nasync function varaAct")[0]
    folds = re.findall(r"<details[^>]*>", vara)
    assert len(folds) >= 6
    for d in folds:
        assert "data-vkeep=" in d or "data-vsetupd" in d or "data-vdirect" in d, d
        if "data-vkeep=" in d:
            assert "vKeep(" in d, d
    assert 'data-vkeep="ein-' in vara and "What Einstein does on the air" in vara
    assert 'document.addEventListener("toggle",e=>{const d=e.target;if(d.dataset&&d.dataset.vkeep' in idx


def test_vara_message_text_can_be_selected_and_copied():
    """Owner 2026-11-24: "I start the selection in the message and then it jumps outside to other text outside the
    message." The panel's redraw waits while a selection is made in it; the time / status line and buttons are not
    selectable; each message has 📋 Copy (with a fallback for the dashboard over plain http on the LAN)."""
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "if(vSelecting(box)){VA.drawLater=true;continue}" in idx and 'addEventListener("selectionchange"' in idx
    assert '<span class="vtx">${vFmt(it.text,' in idx and "data-vcopy" in idx
    assert ".vb .meta,.vb button,.vb .vxfer{user-select:none" in idx and 'document.execCommand("copy")' in idx
