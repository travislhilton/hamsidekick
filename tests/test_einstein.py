"""Einstein on the air (station/einstein.py): the AI assistant answering other stations over VARA at its own call,
under automatic control only where Part 97 allows it (owner 2026-11-21)."""
import time

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


def test_switched_on_from_a_dashboard_with_the_internet_only(tmp_path):
    st, rid, m, clk, e = _setup(tmp_path)
    e._key = lambda: None
    with pytest.raises(ValueError, match="xAI key"):
        e.settings({"radio": rid, "on": True})
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
    o.failed("down")                                           # no internet: its call comes off the modem
    assert e.state(rid)["state"] == "waiting" and "internet" in e.state(rid)["why"]
    m.einstein_sync()
    assert m.vara.st["calls"] == ["W9XYZ-7"]


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
    assert "${vEinAct(e,rid)}" in bar
    act = idx.split("function vEinAct(e,rid)")[1].split("\nsetInterval")[0]
    assert "is working" not in act and "asked" in act and "linked to Einstein" in act and 'data-vkeep="einrec-' in act
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
    assert "data-vsendnets" in idx and "📅 Send my net schedule" in idx and '"/api/nets/share/export.ics"' in idx
    assert idx.count("${vNetsBtn(f)}") == 2 and "data-vnetsinst" in idx and '"/api/nets/share/install"' in idx
    ask = idx.split("const V_ASK=[")[1].split("];")[0]
    assert "Local EMCOMM CHIRP file (2m/70cm/ad hoc)" in ask and "Your net schedule as a calendar file" in ask
    assert len("Local EMCOMM CHIRP file (2m/70cm/ad hoc)") <= 40 and len("Your net schedule as a calendar file") <= 40   # not cut
