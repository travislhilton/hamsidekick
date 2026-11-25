"""Einstein on the air (station/einstein.py): the AI assistant answering other stations over VARA at its own call,
under automatic control only where Part 97 allows it (owner 2026-11-21)."""
import time

import re

import pytest

from station import einstein as E
from station import forms, varalink, wx
from tests.test_varachan import ChanVara, Clock, _drop
from tests.test_varalink import _st


class EVara(ChanVara):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.st.update(calls=[kw["mycall"]] + list(kw.get("aux_calls") or []), local=None)
        self.notes = []

    def _tx(self, purpose=None):
        r = self.kw["tx_allowed"](purpose)
        if not r[0]:
            from station.vara import VaraRefused
            raise VaraRefused(r[1])

    def listen(self, on):
        if on:
            self._tx("listen")
        self.calls.append(("listen", on))
        self.st["listening"] = on

    def connect(self, call, via=()):
        self._tx("operator")
        self.calls.append(("connect", call, list(via)))
        self.st.update(session="connecting", peer=call)

    def _data_purpose(self):
        return f"data:{self.st['local']}" if self.st.get("local") else None

    def send_chat(self, text):
        self._tx(self._data_purpose())
        self.calls.append(("chat", text))
        self.seq += 1
        return self.seq

    def send_file(self, name, data):
        self._tx(self._data_purpose())
        self.calls.append(("file", name, data))
        self.seq += 1
        return self.seq

    def send_note(self, line):
        self._tx(self._data_purpose())
        self.notes.append(line)

    def cq(self, via=(), call=None):
        self._tx("operator" if not call or call == self.kw["mycall"] else f"cq:{call}")
        self.calls.append(("cq", call or self.kw["mycall"]))

    def set_calls(self, calls):
        self.st["calls"] = list(calls)
        self.calls.append(("calls", list(calls)))


def _setup(tmp_path, freq=445.525, cls="technician", kind="fm", bw=None, model=None):
    st, rid = _st(tmp_path, freq=freq, cls=cls)
    clk = Clock()
    st._vara = varalink.Link(st, factory=EVara, clock=clk)
    st.vara.settings(dict({"enabled": True, "radio": rid, "kind": kind}, **({"bw": bw} if bw else {})))
    st.me = "W9XYZ"
    st.vara.settings({"radio": rid, "call": "W9XYZ-7"})
    e = E.Einstein(st, clock=clk, ask=model or _model(), fetch=_fetch)
    e._key = lambda: "test-key"
    st._einstein = e
    m = st.vara.modem(rid)
    return st, rid, m, clk, e


def _model(reply="146.520 is the national simplex calling frequency.", tool=None, attach=()):
    def ask(system, user, tools):
        ask.seen = (system, user)
        if tool:
            tools.run(*tool)
        return {"reply": reply, "attach": list(attach), "note_for_operator": ""}, {"tools": []}
    return ask


def _fetch(url):
    if "geocoding" in url:
        return {"results": [{"name": "Springfield", "admin1": "Illinois", "country_code": "US",
                             "latitude": 39.8017, "longitude": -89.6437}]}
    if "/points/" in url:
        return {"properties": {"forecast": "https://api.weather.gov/gridpoints/X/1,2/forecast",
                               "relativeLocation": {"properties": {"city": "Springfield", "state": "IL"}}}}
    if url.endswith("/forecast"):
        return {"properties": {"periods": [{"name": "Tonight", "detailedForecast": "Clear, <b>low</b> 30.",
                                            "temperature": 30, "temperatureUnit": "F", "windSpeed": "5 mph",
                                            "windDirection": "NW"}]}}
    if "alerts" in url:
        return {"features": [{"properties": {"event": "Wind Advisory", "severity": "Moderate",
                                             "headline": "Wind Advisory until 6 PM", "ends": "2026-11-21T18:00"}}]}
    if "k-index" in url:
        return [["time_tag", "Kp"], ["2026-11-21 00:00", "2.33"]]
    if "scales" in url:
        return {"0": {"R": {"Scale": "0"}, "S": {"Scale": "0"}, "G": {"Scale": "1"}}}
    if "f107" in url or "flux" in url:
        return [{"time_tag": "2026-11-21", "flux": 152}]
    raise OSError("no network in tests: " + url)


def _wait(pred, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _ask(m, v, peer, text):
    """Type to Einstein and wait for its reply (it answers on threads of its own)."""
    n = len([c for c in v.calls if c[0] == "chat"])
    m._event("chat", {"peer": peer, "text": text})
    assert _wait(lambda: len([c for c in v.calls if c[0] == "chat"]) > n and not m.einstein().busy.get((m.rid, peer)))
    time.sleep(0.05)
    return [c[1] for c in v.calls if c[0] == "chat"][-1]


def _link_e(m, v, peer, ecall="W9XYZ-14"):
    v.st.update(session="connected", peer=peer, peer_proto="HSK1", local=ecall)
    m.einstein().on_connected(m.rid, peer)
    m._event("connected", {"peer": peer, "local": ecall})


# ---------------------------------------------------------------- Part 97: where it may run unattended -------------
@pytest.mark.parametrize("f, kind, bw, cls, answer, announce", [
    (445.525, "fm", None, "technician", True, True),          # 97.221(b): 6 m and shorter
    (146.55, "fm", None, "technician", True, True),
    (52.0, "fm", None, "technician", True, True),
    (14.105, "hf", 2300, "general", True, True),              # an HF 97.221(b) segment
    (7.080, "hf", 2300, "general", False, False),             # HF elsewhere, 2300 Hz: never
    (7.080, "hf", 500, "general", True, False),               # 97.221(c): answer only, 500 Hz
    (5.3305, "hf", 500, "general", False, False),             # 60 m: never (97.303(h))
    (7.080, "hf", 500, "technician", False, False),           # no data privileges there
    (445.525, "fm", None, "", False, False),                  # no license class set
])
def test_automatic_control_follows_97_221(f, kind, bw, cls, answer, announce):
    r = E.auto_control(f, kind, bw, cls)
    assert r["answer"][0] is answer and r["announce"][0] is announce


def test_switched_on_from_a_dashboard_and_off_grid_it_still_sends_packs(tmp_path):
    """Owner 2026-11-24: "If Einstein can assemble the pack from the station without the internet that will be good
    for off grid pack sharing". With no internet (or no xAI key) its call stays on the modem and the station's code
    answers PACK, HELP and the owner's commands; any other question is told plainly why not."""
    st, rid, m, clk, e = _setup(tmp_path)
    e._key = lambda: "k"
    st.agent.sender.here = False
    with pytest.raises(ValueError, match="dashboard"):
        e.settings({"radio": rid, "on": True})
    st.agent.sender.here = True
    with pytest.raises(ValueError, match="SSID"):
        e.settings({"radio": rid, "call": "K7ABC-15"})
    with pytest.raises(ValueError, match="own call"):
        e.settings({"radio": rid, "call": "W9XYZ-7"})
    v = e.settings({"radio": rid, "on": True})
    assert v["radios"][rid]["state"] == "answering" and v["radios"][rid]["call"] == "W9XYZ-14"
    from station.online import Online
    st.agent.online["xai"] = o = Online("xai")
    o.failed("down")                                           # no internet: still on the air, for PACK and HELP
    assert e.state(rid)["state"] == "answering" and "PACK" in e.state(rid)["why"]
    m.einstein_sync()
    assert "W9XYZ-14" in m.vara.st["calls"]
    e.ask_model = lambda *a: (_ for _ in ()).throw(AssertionError("no model off grid"))
    m.check()
    v = m.vara
    _link_e(m, v, "K7ABC")
    assert "No internet here right now" in _ask(m, v, "K7ABC", "What is the weather?")
    assert "PACK" in _ask(m, v, "K7ABC", "HELP")
    st.cfg["schedule"] = [{"id": "n1", "name": "Tuesday Net", "freq_mhz": 146.94, "mode": "FM", "start": "19:00",
                           "duration_min": 60, "repeat": {"freq": "weekly", "weekdays": ["Tue"]}}]
    assert "station pack" in _ask(m, v, "K7ABC", "PACK")
    assert _wait(lambda: any(c[0] == "file" and c[1].endswith(".hspack") for c in v.calls))
    e._key = lambda: None                                      # no key at all: the same
    assert e.state(rid)["state"] == "answering" and e.can_switch_on(rid)[0]


def test_with_the_operator_away_only_einsteins_call_answers(tmp_path):
    st, rid, m, clk, e = _setup(tmp_path)
    e.settings({"radio": rid, "on": True})
    v = m.vara
    m.einstein_sync()
    assert v.st["calls"] == ["W9XYZ-7", "W9XYZ-14"]           # both while the operator is here
    st.agent.sender.here = False
    m.check()
    assert v.st["calls"] == ["W9XYZ-14"] and v.st["listening"]  # away: Einstein only, still answering
    assert m.tx_allowed("operator")[0] is False
    assert m.tx_allowed("data:W9XYZ-7")[0] is False             # the operator's call never transmits unattended
    assert m.tx_allowed("data:W9XYZ-14") == (True, "")
    assert m.tx_allowed("cq:W9XYZ-14") == (True, "")
    m.chan.send("K7ABC", "see you at the net")                  # the operator's own message waits for the operator
    m.chan.tick()
    assert not any(c[0] == "connect" for c in v.calls)
    assert ("cq", "W9XYZ-14") in v.calls                       # Einstein announces itself on 70 cm
    st.ptt.on = False                                           # the Transmit switch is off: nothing at all
    assert m.tx_allowed("data:W9XYZ-14")[0] is False


def test_a_session_discloses_answers_and_sends_a_chirp_file(tmp_path):
    chan = [{"freq_mhz": 446.0, "offset_mhz": 0, "tone_hz": 0, "mode": "FM", "alias": "SIMPLX1", "name": "70 cm calling"},
            {"freq_mhz": 147.0, "offset_mhz": 0.6, "tone_hz": 100.0, "mode": "FM", "alias": "RPT", "name": "a repeater"}]
    model = _model("Here is your CHIRP file: two channels.",
                   ("make_chirp", {"source": "custom", "band": "", "radio": "ht", "title": "my plan", "channels": chan}),
                   attach=["f1"])
    st, rid, m, clk, e = _setup(tmp_path, model=model)
    e.settings({"radio": rid, "on": True})
    st.agent.sender.here = False
    m.check()
    v = m.vara
    m.chan.send("K7ABC", "operator's own message")              # must not ride on Einstein's link
    _link_e(m, v, "K7ABC")
    m._event("chat", {"peer": "K7ABC", "text": "Can you make me a CHIRP file?"})
    assert _wait(lambda: any(c[0] == "file" for c in v.calls))
    chats = [c[1] for c in v.calls if c[0] == "chat"]
    assert "automated AI assistant" in chats[0] and "W9XYZ-14" in chats[0] and "W9XYZ" in chats[0]
    assert "CHIRP file" in chats[-1]
    f = next(c for c in v.calls if c[0] == "file")
    assert f[1].startswith("CHIRP-my-plan") and b"446.000000" in f[2] and b"+" in f[2] and b"100.0" in f[2]
    assert not any(c == ("chat", "operator's own message") for c in v.calls)
    assert "WORKING 30" in v.notes
    th = m.chan.view()["threads"]["K7ABC"]
    assert th[1]["to"] == "einstein" and all(it.get("by") == "einstein" for it in th[2:] if it["dir"] == "out")


def test_an_answer_not_ready_before_the_link_closes_waits_for_the_next_link(tmp_path):
    gate = {"go": False}

    def slow(system, user, tools):
        _wait(lambda: gate["go"])
        return {"reply": "The answer.", "attach": [], "note_for_operator": ""}, {}
    st, rid, m, clk, e = _setup(tmp_path, model=slow)
    e.settings({"radio": rid, "on": True})
    v = m.vara
    _link_e(m, v, "K7ABC")
    m._event("chat", {"peer": "K7ABC", "text": "What is a good antenna for 2 m?"})
    _wait(lambda: e.busy.get((rid, "K7ABC")))
    _drop(m, v)
    gate["go"] = True
    _wait(lambda: not e.busy.get((rid, "K7ABC")))
    assert not any(c[0] == "chat" for c in v.calls)
    assert any(it["status"] == "held" for it in m.chan.load()["threads"]["K7ABC"])
    _link_e(m, v, "K7ABC")                                      # it links again: the answer goes
    m.chan.tick()
    assert any(c[0] == "chat" and "The answer." in c[1] for c in v.calls)


def test_part_97_in_code(tmp_path):
    st, rid, m, clk, e = _setup(tmp_path, model=_model("I will relay your message to your wife."))
    e.settings({"radio": rid, "on": True})
    v = m.vara
    _link_e(m, v, "K7ABC")
    m._event("chat", {"peer": "K7ABC", "text": "Tell my wife I'm late"})
    assert _wait(lambda: len([c for c in v.calls if c[0] == "chat"]) >= 1 and not e.busy.get((rid, "K7ABC")))
    last = [c[1] for c in v.calls if c[0] == "chat"][-1]
    assert "can't send that answer" in last and "97.115" in last
    m._event("chat", {"peer": "K7ABC", "text": "There's a fire and someone is injured"})
    assert _wait(lambda: any("911" in c[1] for c in v.calls if c[0] == "chat"))
    assert e.alerts and e.mail(rid)[-1]["kind"] == "alert"
    assert E.text_problems("I will sell it to you, send me the payment") and not E.text_problems(
        "You can buy one from its maker; I can tell you that it costs about 50 dollars.")


def test_the_operator_from_another_station_proves_the_owner_key(tmp_path):
    st, rid, m, clk, e = _setup(tmp_path)
    e.settings({"radio": rid, "on": True})
    e.owner_key = lambda: "KEY-123456-ABCDEF"
    v = m.vara
    e.mail_add(rid, "N0CALL", "please call me after the net")
    _link_e(m, v, "W9XYZ-8")
    assert "operator" in _ask(m, v, "W9XYZ-8", "STATUS")                        # not proved yet: refused
    nonce = e.sessions[(rid, "W9XYZ-8")]["nonce"]
    m._event("auth", {"peer": "W9XYZ-8", "token": E.owner_token("wrong-key", nonce, "W9XYZ-8")})
    assert not e.sessions[(rid, "W9XYZ-8")]["owner"]
    m._event("auth", {"peer": "W9XYZ-8", "token": E.owner_token("KEY-123456-ABCDEF", nonce, "W9XYZ-8")})
    assert e.sessions[(rid, "W9XYZ-8")]["owner"]
    assert "please call me after the net" in _ask(m, v, "W9XYZ-8", "MESSAGES")
    assert "Paused" in _ask(m, v, "W9XYZ-8", "pause")
    assert e.rcfg(rid)["paused"] and not e.answering(rid)
    assert "Resumed" in _ask(m, v, "W9XYZ-8", "RESUME")
    assert e.answering(rid)


def test_the_asker_learns_ai_stations_proves_ownership_and_waits_for_the_answer(tmp_path):
    st, rid, m, clk, e = _setup(tmp_path)
    e.owner_key = lambda: "KEY-123456-ABCDEF"
    v = m.vara
    m._event("cq_heard", {"call": "W9XYZ-8"})
    v.st.update(session="connected", peer="W9XYZ-8", peer_proto="HSK1", local="W9XYZ-7")
    m._event("connected", {"peer": "W9XYZ-8", "local": "W9XYZ-7"})
    m._event("handshake", {"peer": "W9XYZ-8", "caps": ["+TEST", "+AI=W9XYZ-15"]})
    ro = {r["call"]: r for r in m.chan.view()["roster"]}
    assert ro["W9XYZ-8"]["einstein"] == "W9XYZ-15" and ro["W9XYZ-15"]["ai"]["of"] == "W9XYZ-8"
    _drop(m, v)
    m.chan.send("W9XYZ-15", "What is the weather?")
    m.chan.tick()
    v.st.update(session="connected", peer="W9XYZ-15", peer_proto="HSK1", local="W9XYZ-7")
    m._event("connected", {"peer": "W9XYZ-15", "local": "W9XYZ-7"})
    m._event("handshake", {"peer": "W9XYZ-15", "caps": ["+TEST", "+AI", "+OF=W9XYZ-8", "+NAME=EINSTEIN", "+NONCE=ABCD1234"]})
    assert v.notes == [f"AUTH {E.owner_token('KEY-123456-ABCDEF', 'ABCD1234', 'W9XYZ-7')}"]
    m.chan.tick()                                               # the question goes
    clk.t += 60
    m.chan.tick()
    assert not any(c[0] == "disconnect" for c in v.calls)       # an AI station owes an answer: the link stays
    m._event("chat", {"peer": "W9XYZ-15", "text": "Clear tonight."})
    clk.t += 60
    m.chan.tick()
    assert any(c[0] == "disconnect" for c in v.calls)
    assert {r["call"]: r for r in m.chan.view()["roster"]}["W9XYZ-15"]["ai"]["name"] == "Einstein"


# ---------------------------------------------------------------- forms, weather --------------------------------------
def test_forms_are_pages_without_script_and_winlink_data_reads_back():
    h = forms.ics213({"To_Name": "K7ABC", "Subjectline": "<script>alert(1)</script>", "Message": "line 1\nline 2"})
    assert "<script>alert" not in h and "&lt;script&gt;" in h and "default-src 'none'" in h and "GENERAL MESSAGE" in h
    xml = (b'<?xml version="1.0"?><RMS_Express_Form><form_parameters><display_form>ICS213_Initial_Viewer.html'
           b'</display_form><senders_callsign>W9XYZ</senders_callsign></form_parameters><variables>'
           b'<subjectline>Shelter status</subjectline><message>All OK</message></variables></RMS_Express_Form>')
    info = forms.read_winlink_xml(xml)
    assert info["form"] == "ics213" and "Shelter status" in forms.html_for(info)
    assert forms.read_winlink_xml(b'<!DOCTYPE x [<!ENTITY a "b">]><RMS_Express_Form/>') is None
    t = forms.csv_table("Location,Name\r\n1,SIMPLX\r\n", "CHIRP")
    assert "SIMPLX" in t and "1 rows" in t
    p = forms.ics205({"incident": "Drill"}, [{"ch": 1, "name": "VARA1", "rx": "445.525 N"}])
    assert "VARA1" in p and "ICS 205" in p


def test_weather_and_hf_conditions_as_ics213(tmp_path):
    assert wx.place("FN31")["label"] == "grid FN31" and wx.place("39.8, -89.6")["lat"] == 39.8
    p = wx.place("Springfield, IL", fetch=_fetch)
    assert p["us"] and p["label"].startswith("Springfield")
    w = wx.forecast(p, fetch=_fetch)
    assert w["alerts"][0]["event"] == "Wind Advisory" and w["periods"][0]["name"] == "Tonight"
    st, rid, m, clk, e = _setup(tmp_path)
    t = E.Tools(e, rid, "K7ABC", {"log": [], "asker_class": "general", "owner": False})
    out = t.t_weather("Springfield, IL", as_form=True)
    assert "Wind Advisory" in out and "made file f1" in out
    page = t.files["f1"]["data"].decode()
    assert "Weather: Springfield" in page and "&lt;b&gt;low" in page and "K7ABC" in page
    assert "K index 2" in t.t_hf_conditions()


def test_the_band_range_words():
    assert E._band_range("2 m")[:2] == (144.0, 148.0) and E._band_range("70cm")[:2] == (420.0, 450.0)
    assert E._band_range("146.52")[:2] == (144.0, 148.0) and E._band_range("banana")[0] is None


def test_two_of_your_stations_suggest_different_calls(tmp_path):
    st, rid, m, clk, e = _setup(tmp_path)
    assert e.suggest_call(rid) == "W9XYZ-14"                   # W9XYZ-7
    st.vara.settings({"radio": rid, "call": "W9XYZ-8"})
    assert e.suggest_call(rid) == "W9XYZ-15"


# ---------------------------------------------------------------- over HTTP: View, Einstein, my other stations --------
def test_view_einstein_and_my_other_stations_over_http(tmp_path):
    import json as _j
    import threading
    import urllib.request
    from station import remote
    from station.server import serve
    from tests.test_varalink import _post
    st, rid, m, clk, e = _setup(tmp_path)
    inbox = st.data / "vara" / "radios" / rid / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "ICS213-weather.html").write_bytes(b"<p>Wind</p><script>alert(1)</script>")
    (inbox / "CHIRP-plan.csv").write_bytes(b"Location,Name,Frequency\r\n1,SIMPLX,146.520000\r\n")
    (inbox / "run.exe.blocked").write_bytes(b"MZ")
    srv = serve(st, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/vara/view/ICS213-weather.html") as r:
            assert "sandbox" in r.headers["Content-Security-Policy"] and "default-src 'none'" in r.headers["Content-Security-Policy"]
            assert r.headers["Content-Type"].startswith("text/html")
        with urllib.request.urlopen(base + "/api/vara/view/CHIRP-plan.csv") as r:
            assert b"SIMPLX" in r.read()
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/api/vara/view/run.exe.blocked")
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/api/vara/view/..%2Fvara.json")
        v = _post(base, "/api/einstein/settings", {"radio": rid, "on": True})
        assert v["radios"][rid]["state"] == "answering"
        b = _j.loads(urllib.request.urlopen(base + "/api/station/brief").read())
        assert b["radios"][0]["einstein"]["call"] == "W9XYZ-14" and b["present"]
        # this station's "other station" is itself here: presence from it names who sent it
        st.agent.sender.presence = lambda: {"present": True}
        r = remote.Remote(st)
        r.set_peers([base])
        assert r.status()[0]["ok"] and r.status()[0]["calls"]
        r.presence_all([0])
        assert remote.brief(st)["controlled_from"]
        with pytest.raises(ValueError):
            r.set_peers(["not a url at all"])
    finally:
        srv.shutdown()


def test_weather_here_uses_the_whole_grid_locator_not_its_square(tmp_path):
    """Owner 2026-11-24: a 6-character locator came back as the weather of a town in another state — Einstein cut it
    to the 4-character square (1 x 2 degrees), whose middle is far from the station."""
    st, rid, m, clk, e = _setup(tmp_path)
    st._saved = lambda: {"operator": {"grid": "FN31pr"}}
    h = e.here()
    assert abs(h["lat"] - 41.729) < 0.01 and abs(h["lon"] - (-72.708)) < 0.01      # FN31pr, not FN31's middle 41.5, -73
    assert "FN31pr" in h["label"] and e.area() == "grid square FN31pr"
    seen = []
    t = E.Tools(e, rid, "K7ABC", {"log": [], "asker_class": "general", "owner": False})
    t.e.fetch = lambda url: (seen.append(url), _fetch(url))[1]
    t.t_weather("here")
    assert any("/points/41.73,-72.71" in u for u in seen)
    st._saved = lambda: {"operator": {"grid": "FN31"}}
    assert e.area() == "grid square FN31"
    st._saved = lambda: {"operator": {"grid": "fn31pr12"}}                         # 8 characters: the 6 we can read
    assert e.area() == "grid square fn31pr"


def test_the_dashboard_sees_a_question_come_in_einstein_work_and_answer(tmp_path):
    """Owner 2026-11-24: "when a station is running Einstein over VARA chat it would be good to see that a request has
    come into Einstein and that einstein is working on it". state() carries who is linked, the question being worked
    on and its step (a tool's own words), and the last answers; each change goes to the dashboards as a vara event."""
    import threading
    gate, steps = threading.Event(), []

    def model(system, user, tools):
        tools.run("weather", {"place": "Springfield, IL", "as_form": True})
        steps.append(e.state(rid)["working"][0]["step"])
        gate.wait(3)
        return {"reply": "Clear tonight.", "attach": ["f1"], "note_for_operator": ""}, {"tools": []}
    st, rid, m, clk, e = _setup(tmp_path, model=model)
    e.settings({"radio": rid, "on": True})
    m.check()
    v = m.vara
    shown = []
    pub = st.vara._publish
    st.vara._publish = lambda name, r=None: (shown.append(name), pub(name, r))
    _link_e(m, v, "K7ABC")
    assert e.state(rid)["linked"] == ["K7ABC"] and "einstein" in shown
    m._event("chat", {"peer": "K7ABC", "text": "Weather please"})
    assert _wait(lambda: steps)
    w = e.state(rid)["working"]
    assert len(w) == 1 and w[0]["peer"] == "K7ABC" and w[0]["text"] == "Weather please"
    assert steps == ["looking up the weather"]
    gate.set()
    assert _wait(lambda: not e.state(rid)["working"] and e.state(rid)["recent"])
    r = e.state(rid)["recent"][0]
    assert r["outcome"] == "answered" and r["ok"] and r["tools"] == ["weather"] and r["files"][0].startswith("ICS213")
    assert m.chan.view()["einstein"]["recent"][0]["peer"] == "K7ABC"               # what the panel draws
    _ask(m, v, "K7ABC", "HELP")
    assert e.state(rid)["recent"][0]["outcome"] == "answered: its HELP list"
    m._event("disconnected", {"peer": "K7ABC"})
    e.on_disconnected(rid, "K7ABC")
    assert e.state(rid)["linked"] == [] and not e.state(rid)["working"]


def test_einstein_activity_is_drawn_on_the_panel():
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    bar = idx.split("function vEinBar(m,ch)")[1].split("\nfunction ")[0]
    assert "${vEinAct(e,rid)}" in bar and '${vEinAct(e,rid,"recent")}' in bar   # what it answered: in its fold
    act = idx.split("function vEinAct(e,rid,part)")[1].split("\nsetInterval")[0]
    assert "working for" in act and "linked to Einstein" in act and 'data-vkeep="einrec-' in act
    # owner 2026-11-25: what Einstein is doing shows in the conversation, where the question came in
    work = idx.split("function vEinWorking(ch,peer)")[1].split("\nfunction ")[0]
    assert "Einstein is ${esc(j.step)}" in work and "data-vsince" in work and "${vEinWorking(ch,one)}</div>" in idx
    assert '"peer_working","einstein"]' in idx                                   # an einstein event redraws the panel
    assert "is working on your question…" in idx                                 # and the asker sees it in the chat


def test_a_chirp_file_of_the_local_emcomm_channels(tmp_path):
    """Owner 2026-11-24: "a quick request for a CHIRP file for local frequencies including 2m, 70cm EMCOMM repeater and
    simplex frequencies and adhoc frequencies that I have allocated on my bandplan"."""
    def ch(f, use, auth="local", off=None, tone=None, kept=False, mode="FM", org="County ARES"):
        return {"type": "channel", "from": f, "to": f, "use": use, "authority": auth, "offset_mhz": off, "tone_hz": tone,
                "kept": kept, "mode": mode, "org": org}
    table = {"bands": [{"rows": [
        ch(144.39, "APRS national"), ch(145.03, "Packet/Winlink primary"), ch(144.97, "Winlink gateway K7ABC-10"),
        ch(145.15, "D-Star C", off=-0.6), ch(146.94, "Command net", off=-0.6, tone=100.0),
        ch(146.46, "Tac 1"), ch(146.52, "National simplex calling", auth="coordinator", org="State VHF Society"),
        ch(146.56, "Simplex", auth="coordinator", kept=True, org="State VHF Society"),
        ch(146.58, "Simplex", auth="coordinator", org="State VHF Society"),            # not chosen, not kept: out
        ch(144.2, "SSB weak signal calling", auth="coordinator", mode="USB")]},
        {"rows": [ch(446.0, "70 cm calling", auth="coordinator", org=None), ch(449.625, "Linked repeater", off=-5.0, tone=103.5),
                  ch(447.0, "DMR digital", off=-5.0)]},
        {"rows": [ch(7.2, "HF ARES net", mode="LSB")]}]}

    class Plans:
        def consolidated(self):
            return table

        def adhoc(self):
            return [{"kind": "voice", "freq_mhz": 147.42, "alias": "ADHOC1", "name": "ad hoc 1"},
                    {"kind": "data", "freq_mhz": 446.6, "alias": "VARAFM", "name": "ad hoc VARA"}]
    st, rid, m, clk, e = _setup(tmp_path)
    e.plans = lambda: Plans()
    t = E.Tools(e, rid, "K7ABC", {"log": [], "asker_class": "general", "owner": False})
    got = [r["freq_mhz"] for r in t._channels("local", "", None)]
    assert got == [146.94, 146.46, 146.56, 146.52, 147.42, 449.625, 446.0, 446.6]   # per band: rpt, simplex, calling, ad hoc
    assert [r["freq_mhz"] for r in t._channels("local", "70 cm", None)] == [449.625, 446.0, 446.6]
    out = t.t_make_chirp("local", "", "ht", "local EMCOMM")
    assert out.startswith("8 channels") and "made file f1" in out
    csv = t.files["f1"]["data"].decode()
    assert "146.940000" in csv and "103.5" in csv and "144.390000" not in csv and "145.150000" not in csv
    assert t.files["f1"]["name"] == "CHIRP-local-EMCOMM.csv"
    assert "local EMCOMM 2 m and 70 cm" in E.HELP


def test_einstein_sends_the_net_schedule_as_a_calendar_and_a_net_file(tmp_path):
    st, rid, m, clk, e = _setup(tmp_path)
    t = E.Tools(e, rid, "K7ABC", {"log": [], "asker_class": "general", "owner": False})
    st.cfg["schedule"] = []
    assert t.t_make_net_schedule() == "no nets on this station's schedule"
    st.cfg["schedule"] = [{"id": "n1", "name": "Tuesday Net", "freq_mhz": 146.94, "mode": "FM", "start": "19:00",
                           "duration_min": 60, "repeat": {"freq": "weekly", "weekdays": ["Tue"]}}]
    out = t.t_make_net_schedule()
    assert "1 nets" in out and "f1" in out and "f2" in out
    assert t.files["f1"]["name"].endswith("-nets.ics") and t.files["f2"]["name"].endswith("-nets.hsnets")
    assert b"BEGIN:VEVENT" in t.files["f1"]["data"] and b'"kind": "nets"' in t.files["f2"]["data"]
    assert {".ics", ".hsnets"} <= E.SAFE_EXT


def test_a_received_net_file_shows_add_views_and_installs_over_http(tmp_path):
    import json as _j
    import threading
    import urllib.request
    from station import netshare
    from station.server import serve
    from tests.test_varalink import _post
    st, rid, m, clk, e = _setup(tmp_path)
    st.cfg["schedule"] = []
    doc = {"schema": "hamsidekick-settings/1", "kind": "nets", "from": "K7ABC", "radios": [],
           "nets": [{"name": "Thursday ARES Net", "freq_mhz": 146.94, "mode": "FM", "start": "20:00", "duration_min": 30,
                     "repeat": {"freq": "weekly", "weekdays": ["Thu"]}}]}
    inbox = st.data / "vara" / "radios" / rid / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "K7ABC-nets.hsnets").write_text(_j.dumps(doc), encoding="utf-8")
    f = next(x for x in m.view()["inbox"] if x["name"] == "K7ABC-nets.hsnets")
    assert f["nets"] == {"from": "K7ABC", "nets": 1, "names": ["Thursday ARES Net"]}
    srv = serve(st, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/vara/view/K7ABC-nets.hsnets") as r:
            assert b"Thursday ARES Net" in r.read()
        pv = _post(base, "/api/nets/share/preview", {"name": "K7ABC-nets.hsnets"})
        assert pv["nets"]["add"] == 1 and pv["source"] == "K7ABC"
        r = _post(base, "/api/nets/share/install", {"name": "K7ABC-nets.hsnets"})
        assert r["added"] == 1 and any(n["name"] == "Thursday ARES Net" for n in st.cfg["schedule"])
        d = _j.loads(urllib.request.urlopen(base + "/api/nets/share/export").read())
        assert d["kind"] == "nets" and d["nets"][0]["name"] == "Thursday ARES Net"
        cal = urllib.request.urlopen(base + "/api/nets/share/export.ics").read().decode()
        assert "SUMMARY:Thursday ARES Net" in cal
    finally:
        srv.shutdown()
    assert netshare.SUFFIX == ".hsnets"


def test_the_panel_sends_nets_and_offers_add_and_the_quick_requests():
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "data-vshare=" in idx and "📦 Share with" in idx and '"/api/nets/share/export.ics"' in idx
    assert idx.count("${vNetsBtn(f)}") == 2 and "data-vnetsinst" in idx and '"/api/nets/share/install"' in idx
    ask = idx.split("const V_ASK=[")[1].split("]];")[0]                 # owner 2026-11-25: these five, in order
    labels = re.findall(r'\[\"([^"]+)\",\"([^"]+)\",\"(\w+)\"', ask)
    assert [(l, c) for l, c, _ in labels] == [("What can you do?", "HELP"),
        ("📦 Send your station's band plan", "PACK PLAN"), ("📅 Send your station's nets", "PACK NETS"),
        ("Send your weather as ICS-213", "WX213"), ("What are the HF band conditions now?", "HF"),
        ("⚠ What are the emergency alerts for my area?", "ALERTS {grid}"),
        ("What is the weather forecast for my station?", "WX {grid}")]
    assert 'c.replace("{grid}",ch.me.grid||"")' in idx and "Set your grid square in Settings → Station" in idx


def test_news_is_searched_on_the_web_never_answered_with_the_weather(tmp_path):
    """Owner 2026-11-24: asked "What is the latest in the news today?", Einstein answered with the weather and HF
    conditions (it had no way to look news up). Now it searches the web and names the sources; the prompt says never
    to answer one thing with another, and a note for the operator only when asked for one."""
    st, rid, m, clk, e = _setup(tmp_path)
    sent = []

    def web(key, body, timeout):
        sent.append(body)
        return {"output": [{"type": "web_search_call", "action": {"url": "https://apnews.com/article/x"}},
                           {"type": "message", "content": [{"type": "output_text",
                            "text": "**Latest:**\n- Storm moves east (AP) [[1]](https://apnews.com/article/x) see https://x.example/y\n- ARRL announces contest results "
                                    "([ARRL](https://www.arrl.org/news))", "annotations": [{"url": "https://www.arrl.org/news"}]}]}]}
    e.web_post = web
    t = E.Tools(e, rid, "K7ABC", {"log": [], "asker_class": "general", "owner": False})
    assert "search_web" in {s["function"]["name"] for s in t.specs}
    out = t.run("search_web", {"query": "latest news today"})
    assert "Storm moves east (AP)" in out and "http" not in out.split("(searched")[0] and "ARRL announces" in out
    assert "apnews.com" in out and "arrl.org" in out
    assert "**" not in out and "Latest:" in out
    assert sent[0]["tools"] == [{"type": "web_search"}, {"type": "x_search"}] and "latest news today" in sent[0]["input"][0]["content"]
    assert e.state(rid)["working"] == [] and t.calls == ["search_web"]
    e.web_post = lambda *a: (_ for _ in ()).throw(OSError("down"))
    assert "could not be done" in t.run("search_web", {"query": "news"})
    assert "weather is not news" in E.SYSTEM and "answering a question is not a note" in E.SYSTEM
    assert E.TOOL_STEP["search_web"] == "searching the web" and "search the internet" in E.HELP
    assert "whole internet" in E.SYSTEM and "Never say you cannot browse" in E.SYSTEM


def test_one_request_for_a_chirp_file_sends_one_file(tmp_path):
    """Owner 2026-11-24: "Local EMCOMM CHIRP file" sent three files of one name (the model called make_chirp four times
    and attached three). Every CHIRP file attached to one reply becomes one file; a file twice goes once."""
    c2 = [{"freq_mhz": 146.94, "offset_mhz": -0.6, "tone_hz": 100.0, "mode": "FM", "alias": "RPT", "name": "rpt"},
          {"freq_mhz": 146.52, "offset_mhz": 0, "tone_hz": 0, "mode": "FM", "alias": "CALL", "name": "calling"}]
    c70 = [{"freq_mhz": 446.0, "offset_mhz": 0, "tone_hz": 0, "mode": "FM", "alias": "CALL70", "name": "70 calling"},
           {"freq_mhz": 146.52, "offset_mhz": 0, "tone_hz": 0, "mode": "FM", "alias": "CALL", "name": "calling"}]

    def model(system, user, tools):
        for ch in (c2, c70, c2):
            tools.run("make_chirp", {"source": "custom", "band": "", "radio": "ht", "title": "Local EMCOMM", "channels": ch})
        tools.run("make_ics213", {"to": "K7ABC", "subject": "x", "message": "y", "incident": ""})
        return {"reply": "Here is your file.", "attach": ["f1", "f2", "f3", "f4", "f4"], "note_for_operator": ""}, {"tools": []}
    st, rid, m, clk, e = _setup(tmp_path, model=model)
    e.settings({"radio": rid, "on": True})
    st.agent.sender.here = False
    m.check()
    v = m.vara
    _link_e(m, v, "K7ABC")
    m._event("chat", {"peer": "K7ABC", "text": "Local EMCOMM CHIRP file (2m/70cm/ad hoc)"})
    assert _wait(lambda: len([c for c in v.calls if c[0] == "file"]) >= 2)
    time.sleep(0.2)
    sent = [c for c in v.calls if c[0] == "file"]
    assert [c[1] for c in sent] == ["CHIRP-Local-EMCOMM.csv", next(c[1] for c in sent if c[1].startswith("ICS213"))]
    csv = sent[0][2].decode()
    rows = [r for r in csv.splitlines()[1:] if r]
    assert len(rows) == 3 and csv.count("146.520000") == 1 and "446.000000" in csv and rows[2].startswith("3,")
    same = E.one_file_each([{"name": "a.csv", "data": b"1"}, {"name": "a.csv", "data": b"2"}, {"name": "a.csv", "data": b"1"}])
    assert [f["name"] for f in same] == ["a.csv", "a-2.csv"]


def test_a_band_plan_asked_for_comes_as_a_file_and_a_promised_file_is_never_missing(tmp_path):
    """Owner 2026-11-24: asked for the 70 cm band plan, the reply said "Full details in the attached file" and no file
    was ever made. band_plan as_file makes a page; a reply that claims a file sends what the tools made, or says none was."""
    table = {"sources": [{"name": "County ARES plan", "authority": "local"}], "bands": [{"rows": [
        {"type": "segment", "from": 420.0, "to": 450.0, "use": "70 cm", "by": "FCC"},
        {"type": "channel", "from": 449.625, "to": 449.625, "use": "Linked repeater", "offset_mhz": -5.0, "tone_hz": 103.5,
         "by": "County ARES plan"}]}]}

    class Plans:
        def consolidated(self):
            return table
    for claim, make, want in (("Full details in the attached file.", True, "file"),
                              ("Full details in the attached file.", False, "note"),
                              ("70 cm is 420-450 MHz.", False, "none")):
        def model(system, user, tools, make=make, claim=claim):
            tools.run("band_plan", {"band": "70 cm", "as_file": make})
            return {"reply": claim, "attach": [], "note_for_operator": ""}, {"tools": []}
        st, rid, m, clk, e = _setup(tmp_path / want, model=model)
        e.plans = lambda: Plans()
        e.settings({"radio": rid, "on": True})
        st.agent.sender.here = False
        m.check()
        v = m.vara
        _link_e(m, v, "K7ABC")
        m._event("chat", {"peer": "K7ABC", "text": "The band plan for 70 cm for my license"})
        assert _wait(lambda: e.state(rid)["recent"])
        time.sleep(0.2)
        files = [c for c in v.calls if c[0] == "file"]
        last = [c[1] for c in v.calls if c[0] == "chat"][-1]
        if want == "file":
            assert len(files) == 1 and files[0][1].startswith("BandPlan-70-cm") and files[0][1].endswith(".html")
            page = files[0][2].decode()
            assert "449.6250" in page and "-5.000" in page and "County ARES plan" in page and "<script" not in page
        elif want == "note":
            assert not files and "No file was made" in last
        else:
            assert not files and "No file was made" not in last


def test_pack_sends_the_station_pack_by_code_as_the_operator_chose(tmp_path):
    """Owner 2026-11-24: the other operator taps the request for the band plan and nets, it goes to Einstein, it comes
    back, and they can install it. PACK is answered by code (no model), sends one .hspack, follows the owner's share
    choices and goes at most 3 times an hour to one station."""
    from station import stationpack as SP
    from tests.test_stationpack import _sender

    def model(system, user, tools):
        raise AssertionError("PACK never reaches the model")
    st, rid, m, clk, e = _setup(tmp_path, model=model)
    _sender(st)
    st.cfg["schedule"] = [{"id": "n1", "name": "Tuesday Net", "freq_mhz": 146.94, "mode": "FM", "start": "19:00",
                           "duration_min": 60, "repeat": {"freq": "weekly", "weekdays": ["Tue"]}}]
    e.settings({"radio": rid, "on": True})
    st.agent.sender.here = False
    m.check()
    v = m.vara
    _link_e(m, v, "K7ABC")
    reply = _ask(m, v, "K7ABC", "PACK")
    assert _wait(lambda: any(c[0] == "file" for c in v.calls))
    f = next(c for c in v.calls if c[0] == "file")
    assert f[1] == "W9XYZ-station-pack.hspack"
    doc = SP.parse(f[2])
    assert [p["title"] for p in doc["plans"]] == ["County ARES Plan"] and doc["nets"]["nets"][0]["name"] == "Tuesday Net"
    assert "1 local plan (2 channels" in reply and "1 net" in reply and "Review and install" in reply
    assert e.state(rid)["recent"][0]["outcome"] == "answered: sent the station pack"
    e.settings({"share": {"nets": False, "own_files": True}})
    assert e.share() == {"plans": True, "kept": True, "adhoc": True, "nets": False, "own_files": True}
    _ask(m, v, "K7ABC", "pack please")
    doc = SP.parse([c for c in v.calls if c[0] == "file"][-1][2])
    assert "nets" not in doc and len(doc["plans"]) == 2
    _ask(m, v, "K7ABC", "PACK")
    assert "3 times this hour" in _ask(m, v, "K7ABC", "PACK")
    assert len([c for c in v.calls if c[0] == "file"]) == 3
    assert "PACK" in E.HELP


def test_the_quick_requests_are_command_words_answered_without_the_ai_even_off_grid(tmp_path):
    """Owner 2026-11-24: "From our quick selects, what else can we send information for without the AI?" — "go".
    CHIRP, BANDPLAN, ICS205, ICS309, NETS, CALENDAR, CALL and MSG are answered by the station's code: never the model,
    the same every time, with no internet; WX and HF need the internet but not the model; a command word followed by a
    long sentence still goes to the model when it can be reached."""
    table = {"bands": [{"rows": [
        {"type": "range", "from": 144.0, "to": 148.0, "use": "2 m", "by": "FCC"},
        {"type": "channel", "from": 146.94, "to": 146.94, "use": "Command net", "authority": "local", "offset_mhz": -0.6,
         "tone_hz": 100.0, "kept": False, "mode": "FM", "org": "County ARES", "by": "County plan", "alias": "CMD NET"}]},
        {"rows": [{"type": "channel", "from": 449.625, "to": 449.625, "use": "Linked repeater", "authority": "local",
                   "offset_mhz": -5.0, "tone_hz": 103.5, "kept": False, "mode": "FM", "org": "County ARES",
                   "by": "County plan", "alias": "LINK UHF"}]}], "sources": [{"name": "County plan"}]}

    class Plans:
        def consolidated(self):
            return table

        def adhoc(self):
            return [{"kind": "voice", "freq_mhz": 147.42, "alias": "ADHOC1", "name": "ad hoc 1"}]
    asked = []

    def model(system, user, tools):
        asked.append(user)
        return {"reply": "From the model.", "attach": [], "note_for_operator": ""}, {"tools": []}
    st, rid, m, clk, e = _setup(tmp_path, model=model)
    e.plans = lambda: Plans()
    st.cfg["schedule"] = [{"id": "n1", "name": "Tuesday Net", "freq_mhz": 146.94, "mode": "FM", "start": "19:00",
                           "duration_min": 60, "repeat": {"freq": "weekly", "weekdays": ["Tue"]}}]
    e.settings({"radio": rid, "on": True})
    st.agent.sender.here = False
    from station.online import Online
    st.agent.online["xai"] = o = Online("xai")
    o.failed("down")                                          # off grid
    m.check()
    v = m.vara
    _link_e(m, v, "K7ABC")
    files = lambda: [c[1] for c in v.calls if c[0] == "file"]
    r = _ask(m, v, "K7ABC", "CHIRP")
    assert "CMD NET" in r and "LINK UHF" in r and "ADHOC1" in r and "Sending CHIRP-Local-EMCOMM" in r and "attach" not in r
    assert files()[-1].startswith("CHIRP-Local-EMCOMM") and len(files()) == 1
    r = _ask(m, v, "K7ABC", "chirp 70cm")
    assert "LINK UHF" in r and "CMD NET" not in r and len(files()) == 2
    r = _ask(m, v, "K7ABC", "BANDPLAN 70CM")
    assert r.startswith("Band plan for 70 cm") and files()[-1].startswith("BandPlan-70-cm")
    assert "BANDPLAN and a band" in _ask(m, v, "K7ABC", "band plan")
    _ask(m, v, "K7ABC", "ICS-205")
    assert files()[-1].startswith("ICS205-Ad-hoc")
    _ask(m, v, "K7ABC", "ics309")
    assert files()[-1].startswith("ICS309")
    assert "Tuesday Net: 146.940 MHz FM, next" in _ask(m, v, "K7ABC", "NETS")
    _ask(m, v, "K7ABC", "CALENDAR")
    assert files()[-2].endswith(".ics") and files()[-1].endswith(".hsnets")
    assert "note kept for W9XYZ" in _ask(m, v, "K7ABC", "MSG please call me tonight")
    import urllib.error

    def no_net(*a, **k):
        raise urllib.error.URLError("no route to host")
    e.here, e.fetch = (lambda: {"lat": 39.8, "lon": -89.65, "label": "Springfield, IL", "name": "Springfield, IL"}), no_net
    assert "needs the internet" in _ask(m, v, "K7ABC", "WX")
    assert "No internet here right now" in _ask(m, v, "K7ABC", "What is the news?")
    h = _ask(m, v, "K7ABC", "HELP")
    assert "CHIRP 2M" in h and "BANDPLAN 70CM" in h and "WX213" in h
    assert asked == []                                        # the model was never asked
    st.agent.online.pop("xai")                                # online: a long sentence goes to the model
    r = _ask(m, v, "K7ABC", "CHIRP file of every 2 m repeater for my mobile with the tones please")
    assert r.endswith("From the model.") and len(asked) == 1
    assert "(no AI)" in next(x["outcome"] for x in e.state(rid)["recent"] if "CHIRP" in x["outcome"])


def test_pack_plan_and_pack_nets_send_one_part_each(tmp_path):
    """Owner 2026-11-25: "Send your station's band plan" and a new "Send your station's nets": PACK PLAN sends the
    plans, kept and ad hoc channels; PACK NETS the net schedule; PACK both."""
    from station import stationpack as SP
    from tests.test_stationpack import _sender
    st, rid, m, clk, e = _setup(tmp_path)
    _sender(st)
    st.cfg["schedule"] = [{"id": "n1", "name": "Tuesday Net", "freq_mhz": 146.94, "mode": "FM", "start": "19:00",
                           "duration_min": 60, "repeat": {"freq": "weekly", "weekdays": ["Tue"]}}]
    e.settings({"radio": rid, "on": True})
    st.agent.sender.here = False
    m.check()
    v = m.vara
    _link_e(m, v, "K7ABC")
    last = lambda: SP.parse([c for c in v.calls if c[0] == "file"][-1][2])
    r = _ask(m, v, "K7ABC", "PACK PLAN")
    assert "local plan" in r and "net" not in r.split("KB")[0]
    assert _wait(lambda: any(c[0] == "file" for c in v.calls))
    d = last()
    assert d["plans"] and "nets" not in d
    r = _ask(m, v, "K7ABC", "pack nets")
    time.sleep(0.1)
    d = last()
    assert "1 net" in r and d["nets"]["nets"][0]["name"] == "Tuesday Net" and not d.get("plans")


def test_replies_are_laid_out_for_people(tmp_path):
    """Owner 2026-11-25: "all sentences in a response run together, not friendly for human users". A long paragraph
    gets one sentence per line (abbreviations and decimals kept whole); HELP is a list; the prompt asks for the
    answer first, then one point per line; "What can you do?" is answered with HELP by code."""
    r = E.readable("For 70 cm under a General license: all modes. Key segments: 432.0-432.3 MHz weak signal. "
                   "Avoid Mt. Hood 449.625 (-5 MHz). Simplex at 446.0 and 446.5 MHz. Details are in the file.")
    assert r.split("\n") == ["For 70 cm under a General license: all modes.", "Key segments: 432.0-432.3 MHz weak signal.",
                              "Avoid Mt. Hood 449.625 (-5 MHz).", "Simplex at 446.0 and 446.5 MHz.", "Details are in the file."]
    assert E.readable("Short one. Two.") == "Short one. Two." and E.readable("a\nb. C is long " * 20).count("\n") == 20
    assert E.DIRECT_HELP.count("\n- ") >= 10 and "one point per line" in E.SYSTEM
    st, rid, m, clk, e = _setup(tmp_path, model=lambda *a: (_ for _ in ()).throw(AssertionError("no model")))
    e.settings({"radio": rid, "on": True})
    st.agent.sender.here = False
    m.check()
    v = m.vara
    _link_e(m, v, "K7ABC")
    h = _ask(m, v, "K7ABC", "What can you do?")
    assert "- PACK PLAN:" in h and "Type HELP" not in h              # the HELP list itself: no "Type HELP" above it
    r = _ask(m, v, "K7ABC", "NETS")
    assert "Type HELP" not in r


def test_the_chat_is_a_workspace_with_a_focus_view_and_formatted_messages():
    """Owner 2026-11-25 (UX audit): the conversation has a fixed height with the message box always in view (the panel
    grew to 1300 px); ⤢ Focus gives it the whole window; the bars are one line with their settings folded; the path,
    speed test, share and forget are in Link tools; a message is laid out in lines and lists with an AI station's
    identification small above its answer."""
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    # owner 2026-11-25: "nested in 3 scroll bars ... the screen keeps jumping ... collapse everything but the chat log
    # and quick request controls": the panel is as tall as its column, the message log is the only scroller, and the
    # station / Einstein / channel / files are one fold
    assert "function vFit(box)" in idx and "vFit(box);" in idx and ".vpanel .vconv{min-height:0;overflow:hidden" in idx
    assert ".vpanel .vthread{max-height:none;flex:1 1 0" in idx and ".vpanel{overflow:hidden" in idx
    assert '<details class="vstation" data-vkeep="${esc(fk)}"${vKeep(fk)||(m.channel&&!P.on?" open":"")}>' in idx
    assert "data-vaddtoggle" in idx and 'const keepS=[".vros",".vstin",".vtools"]' in idx
    assert "data-vfocus=" in idx and ".vpanel.vfocus{position:fixed;inset:0" in idx and 'localStorage.setItem("vfocus"' in idx
    assert 'data-vkeep="chan-' in idx and 'data-vkeep="tools-' in idx and "<summary>Link tools" in idx
    assert "function vFmt(t,ai)" in idx and 'class="vli"' in idx and 'class="vid"' in idx
    assert "With no internet it stops answering" not in idx and "stays on the air for its command words" in idx


def test_a_new_link_keeps_the_limits_and_identifies_briefly_and_a_pack_is_announced_first(tmp_path):
    """Found on the air 2026-11-25 (each quick request is its own short link): the hourly limits and the conversation
    carry over to the next link; the full identification goes once in 10 minutes and a new link inside that starts
    with the call and name only; PACK's words go out before its file; a list in one sentence becomes a list."""
    from tests.test_stationpack import _sender
    st, rid, m, clk, e = _setup(tmp_path, model=lambda *a: (_ for _ in ()).throw(AssertionError("no model")))
    _sender(st)
    e.settings({"radio": rid, "on": True})
    st.agent.sender.here = False
    m.check()
    v = m.vara
    _link_e(m, v, "K7ABC")
    first = _ask(m, v, "K7ABC", "NETS")
    assert first.startswith("W9XYZ-14 Einstein here: an automated AI assistant")
    for _ in range(2):
        e.on_disconnected(rid, "K7ABC")                          # the link closes after each answer, as on the air
        _link_e(m, v, "K7ABC")                                   # a new link each time
        r = _ask(m, v, "K7ABC", "PACK PLAN")
        assert r.startswith("W9XYZ-14 Einstein:\n") and "automated AI assistant" not in r
    time.sleep(0.2)
    kinds = [c[0] for c in v.calls if c[0] in ("chat", "file")]
    assert kinds[-2:] == ["chat", "file"]                         # the words, then the file
    e.on_disconnected(rid, "K7ABC")
    _link_e(m, v, "K7ABC")
    _ask(m, v, "K7ABC", "PACK PLAN")
    e.on_disconnected(rid, "K7ABC")
    _link_e(m, v, "K7ABC")
    assert "3 times this hour" in _ask(m, v, "K7ABC", "PACK PLAN")   # the limit outlives the links
    clk.t += 700
    _link_e(m, v, "K7ABC")
    assert "automated AI assistant" in _ask(m, v, "K7ABC", "NETS")   # 10 minutes on: the full identification again
    r = E.readable("Top news this week includes Alpha extending the renewals to March because of the delays, Bravo filing "
                   "over 2500 pending applications, Charlie naming amateur radio its backup, and delta released an open "
                   "codec for digital voice without the proprietary chips that it needed before.\nSources: A, B.")
    assert r.split("\n")[0].endswith("includes:") and r.count("\n- ") == 4 and r.endswith("Sources: A, B.")


def test_alerts_gives_every_hazard_for_my_area_and_says_what_is_clear(tmp_path):
    """Owner 2026-11-25: "What are the urgent weather warnings for my area?", then "all emergency alerts like bad
    weather, earthquakes, flooding, fire, chemical spill ... biological hazards and any other hazards". ALERTS [place or
    grid] is answered by code from five public feeds asked at the same time: official warnings most severe first (the
    civil ones too), earthquakes, wildfires (no prescribed burns, no small old ones), volcanoes, bad air; what was
    checked and clear; a feed that is down is named and the rest still answer; all down = "needs the internet"."""
    import urllib.error
    now = time.time()
    feats = [{"properties": {"event": "Wind Advisory", "severity": "Moderate", "urgency": "Expected",
                             "headline": "Wind Advisory until 6 PM", "ends": "2026-11-26T18:00:00-06:00", "instruction": ""}},
             {"properties": {"event": "Hazardous Materials Warning", "severity": "Extreme", "urgency": "Immediate",
                             "headline": "Hazardous Materials Warning issued by County Emergency Management",
                             "ends": "2026-11-26T06:00:00-06:00",
                             "instruction": "Shelter in place.\nClose windows and turn off ventilation."}}]

    def fetch(url):
        if "/points/" in url:
            return {"properties": {"relativeLocation": {"properties": {"city": "Springfield", "state": "IL"}}}}
        if "/alerts/active" in url:
            return {"features": fetch.feats}
        if "earthquake.usgs.gov" in url:
            assert "minmagnitude=3" in url and "maxradiuskm=160" in url
            return {"features": fetch.quakes}
        if "WFIGS_Incident_Locations_Current" in url:
            assert "IncidentTypeCategory%3D%27WF%27" in url                # prescribed burns are not asked for
            return {"features": fetch.fires}
        if "getElevatedVolcanoes" in url:
            return fetch.volc
        if "getVolcano/" in url:
            return {"latitude": 40.6, "longitude": -89.6}
        if "air-quality-api" in url:
            return {"current": {"us_aqi": fetch.aqi, "pm2_5": 9.0}}
        raise AssertionError(url)
    fetch.feats, fetch.volc, fetch.aqi = feats, [], 34
    fetch.quakes = [{"properties": {"mag": 4.2, "place": "12 km NW of Riverton", "time": (now - 3600) * 1000, "tsunami": 0},
                     "geometry": {"coordinates": [-89.9, 40.3, 5]}}]
    fetch.fires = [{"attributes": {"IncidentName": "OAK RIDGE", "IncidentSize": 1250.0, "PercentContained": 30.0,
                                   "FireDiscoveryDateTime": (now - 5 * 86400) * 1000, "POOCounty": "Sangamon"},
                    "geometry": {"x": -89.4, "y": 40.0}},
                   {"attributes": {"IncidentName": "TINY OLD", "IncidentSize": 0.5, "PercentContained": 100.0,
                                   "FireDiscoveryDateTime": (now - 20 * 86400) * 1000, "POOCounty": "Sangamon"},
                    "geometry": {"x": -89.5, "y": 40.0}}]
    st, rid, m, clk, e = _setup(tmp_path, model=lambda *a: (_ for _ in ()).throw(AssertionError("no model")))
    e.fetch = fetch
    e._key = lambda: None                                       # the feeds alone here (the news follow-up has its own test)
    e.settings({"radio": rid, "on": True})
    st.agent.sender.here = False
    m.check()
    v = m.vara
    _link_e(m, v, "K7ABC")
    r = _ask(m, v, "K7ABC", "ALERTS EN50")
    assert "4 emergency alerts for Springfield, IL" in r
    assert r.index("ALERT: Hazardous Materials Warning (Extreme, Immediate) until Thu Nov 26 06:00") < r.index("ALERT: Wind Advisory")
    assert "- What to do: Shelter in place. Close windows and turn off ventilation." in r
    assert "EARTHQUAKE: M4.2, 12 km NW of Riverton," in r and "mi from you" in r
    assert "WILDFIRE: Oak Ridge, 1,250 acres, 30% contained," in r and "(Sangamon County)" in r and "Tiny Old" not in r
    assert "Also checked, clear: volcanoes at raised alert; air quality (US AQI 34)." in r
    assert "No feed reports a chemical or biological release unless an authority has issued an alert" in r
    fetch.feats, fetch.quakes, fetch.fires, fetch.aqi = [], [], [], 162
    fetch.volc = [{"vnum": "1", "volcano_name": "Mount Example", "alert_level": "WATCH", "color_code": "ORANGE"}]
    r = _ask(m, v, "K7ABC", "warnings EN50")
    assert "2 emergency alerts for Springfield, IL" in r and "VOLCANO: Mount Example, Watch (orange)," in r
    assert "AIR QUALITY: unhealthy, US AQI 162" in r and "Also checked, clear: official warnings" in r
    fetch.volc, fetch.aqi = [], 20
    ok = fetch

    def partly(url):
        if "earthquake.usgs.gov" in url:
            raise urllib.error.URLError("down")
        return ok(url)
    e.fetch = partly
    r = _ask(m, v, "K7ABC", "ALERTS EN50")
    assert r.startswith("W9XYZ-14 Einstein:\nNo emergency alerts for Springfield, IL") or "No emergency alerts for Springfield, IL" in r
    assert "Could not be reached now: earthquakes (USGS)." in r and "wildfires within 50 mi" in r

    def down(url):
        raise urllib.error.URLError("no route")
    e.fetch = down
    assert "ALERTS needs the internet here" in _ask(m, v, "K7ABC", "ALERTS EN50")
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '"⚠ What are the emergency alerts for my area?","ALERTS {grid}","net"' in idx
    assert "- ALERTS [place]: emergency alerts" in E.DIRECT_HELP and "(ALERT|EARTHQUAKE|WILDFIRE|VOLCANO|AIR QUALITY):" in idx


def test_alerts_is_followed_by_an_ai_search_of_the_local_news(tmp_path):
    """Owner 2026-11-25: "Perhaps the AI should search the local news for the area as well?". The official feeds go
    out first, by code; then a second message: what local news and local officials reported in the last 24 hours that
    no feed carries (a spill, an evacuation, a boil-water notice), sources named, marked as not official. With no AI
    the first message says the news was not searched, and nothing follows."""
    def fetch(url):
        if "/points/" in url:
            return {"properties": {"relativeLocation": {"properties": {"city": "Springfield", "state": "IL"}}}}
        if "air-quality-api" in url:
            return {"current": {"us_aqi": 30}}
        if "getElevatedVolcanoes" in url:
            return []
        return {"features": []}
    asked = []

    def web(key, body, timeout):
        asked.append(body["input"][0]["content"])
        return {"output": [{"type": "web_search_call", "action": {"url": "https://www.example-courier.com/a"}},
                           {"type": "message", "content": [{"type": "output_text", "text":
                            "2 urgent items:\n- [2026-11-25 06:10] **Boil-water notice** for the east side of Springfield "
                            "after a main break. Authority: City Water Department. Source: "
                            "[Courier](https://www.example-courier.com/a)\n- Gas leak closes Main Street (Courier)",
                            "annotations": []}]}]}
    st, rid, m, clk, e = _setup(tmp_path, model=lambda *a: (_ for _ in ()).throw(AssertionError("no chat model")))
    e.fetch, e.web_post = fetch, web
    e.settings({"radio": rid, "on": True})
    st.agent.sender.here = False
    m.check()
    v = m.vara
    _link_e(m, v, "K7ABC")
    chats = lambda: [c[1] for c in v.calls if c[0] == "chat"]
    n = len(chats())
    m._event("chat", {"peer": "K7ABC", "text": "ALERTS EN50"})
    assert _wait(lambda: len(chats()) >= n + 2 and not e.busy.get((rid, "K7ABC")))
    first, second = chats()[n], chats()[n + 1]
    assert "No emergency alerts for Springfield, IL" in first and first.rstrip().endswith("Local news check follows (AI search).")
    # owner 2026-11-25: "The AI provided alert should be time/date stamped and reference the authority"
    assert re.match(r"Local news check for Springfield, IL, searched \d{4}-\d\d-\d\d \d\d:\d\d local at W9XYZ-7 \(AI search", second)
    assert "not official alerts):" in second
    assert ("- [2026-11-25 06:10] Boil-water notice for the east side of Springfield after a main break. "
            "Authority: City Water Department. Source: Courier") in second
    assert "- [time not stated] Gas leak closes Main Street (Courier). Authority: none named." in second   # marked, never passed off
    assert "[YYYY-MM-DD HH:MM]" in asked[0] and "Authority:" in asked[0] and "Leave out an item" in asked[0]
    assert "http" not in second.split("(searched")[0] and "**" not in second and "example-courier.com" in second
    assert "LAST 24 HOURS ONLY" in asked[0] and "Springfield, IL" in asked[0] and "Do not repeat those" in asked[0]
    assert {"answered: local news check", "answered ALERTS (no AI)"} <= {r["outcome"] for r in e.state(rid)["recent"]}
    e.web_post = lambda *a: {"output": [{"type": "message", "content": [{"type": "output_text", "annotations": [], "text":
        "Nothing urgent found in the last 24 hours.\n\nAll official local sources were checked for the area.\nThe only "
        "new items were a resolved planned outage and a routine repair.\nChecked: County EM, City Water, the Courier"}]}]}
    n = len(chats())
    m._event("chat", {"peer": "K7ABC", "text": "ALERTS EN50"})
    assert _wait(lambda: len(chats()) >= n + 2 and not e.busy.get((rid, "K7ABC")))
    quiet = chats()[n + 1]
    assert quiet.endswith("Nothing urgent found in the last 24 hours.\nChecked: County EM, City Water, the Courier")
    assert "resolved planned outage" not in quiet                # nothing urgent is said in one line
    e._key = lambda: None                                       # no AI: said so, nothing follows
    n = len(chats())
    r = _ask(m, v, "K7ABC", "ALERTS EN50")
    time.sleep(0.3)
    assert "Local news not searched: the AI search is not available here now." in r and len(chats()) == n + 1


def test_in_a_narrow_column_the_quick_requests_are_a_button_and_a_readable_list():
    """Owner 2026-11-25: "there is a horizontal scroll bar ... for quick actions. It is hard to read those actions on a
    horizontal scroll bar ... a better way to select those quick requests in a small space". Narrow: one button opens
    a list above the message box, a request to a line with what it does under it; one tap sends it and closes the
    list (Esc or a click elsewhere too). Wide: the chips. No horizontal scroller."""
    from station.server import STATIC
    idx = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "data-vqtoggle=" in idx and 'class="vqmenu" role="menu"' in idx and 'class="vqrow" role="menuitem" data-vask=' in idx
    assert "sends now · no AI · works off grid" in idx and "needs the internet at their station" in idx
    assert ".vqchips{display:none}" in idx and ".vqbtn,.vqmenu{display:none}" in idx       # narrow: the list; wide: the chips
    assert ".vpanel .vpre{flex-wrap:nowrap;overflow-x:auto" not in idx
    assert "if(VA.qopen){VA.qopen=null;setTimeout(renderVaraPanels,0)}" in idx
