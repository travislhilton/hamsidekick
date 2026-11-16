"""VARA on the station (station/varalink.py, owner 2026-11-15 "build both"; 2026-11-16 one modem per data radio,
"taking turns" with Winlink Express or separate): only on data (Winlink) radios, transmitting only with its Transmit
switch on, the operator present and data privileges at its frequency; listening stops when any of that fails;
Winlink Express handoff; received files offered as downloads only."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from station import varalink
from station.server import serve
from tests.test_agent import _station
from tests.test_history import _post


class FakeVara:
    made = []

    def __init__(self, **kw):
        self.kw, self.calls, self.started, self.stopped = kw, [], False, False
        self.st = {"link": "up", "session": "idle", "listening": False, "peer": None}
        FakeVara.made.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def state(self):
        return dict(self.st)

    def _tx(self):
        ok, why = self.kw["tx_allowed"]()
        if not ok:
            from station.vara import VaraRefused
            raise VaraRefused(why)

    def listen(self, on):
        if on:
            self._tx()
        self.calls.append(("listen", on))
        self.st["listening"] = on

    def connect(self, call, via=()):
        self._tx()
        self.calls.append(("connect", call, list(via)))

    def send_chat(self, text):
        self._tx()
        self.calls.append(("chat", text))

    def send_file(self, name, data):
        self._tx()
        self.calls.append(("file", name, data))

    def cq(self, via=()):
        self._tx()
        self.calls.append(("cq",))

    def disconnect(self):
        self.calls.append(("disconnect",))

    def abort(self, why):
        self.calls.append(("abort", why))


class Ptt:
    def __init__(self):
        self.on = True

    def allowed(self, rid):
        return (True, "") if self.on else (False, "transmit is switched off for this radio (Radios… → Transmit)")


class Sender:
    here = True

    def present(self):
        return self.here


def _st(tmp_path, freq=7.103, cls="general", role="winlink"):
    st = _station(tmp_path)
    rid = next(iter(st.radios))
    st.radios[rid].update(role=role, freq_mhz=freq)
    st.ptt = Ptt()
    st.agent.sender = Sender()
    st.agent.cfg["license_class"] = cls
    st.me = "W9XYZ"
    st._vara = varalink.Link(st, factory=FakeVara)
    return st, rid


def test_vara_runs_only_on_the_winlink_radio(tmp_path):
    st, rid = _st(tmp_path, role="nets")
    with pytest.raises(ValueError, match="Winlink"):
        st.vara.settings({"enabled": True, "radio": rid})
    st.radios[rid]["role"] = "winlink"
    v = st.vara.settings({"enabled": True, "kind": "hf", "bw": 500})
    assert v["modems"][0]["cfg"]["radio"] == rid and FakeVara.made[-1].started
    assert FakeVara.made[-1].kw["mycall"] == "W9XYZ" and FakeVara.made[-1].kw["bw"] == 500
    with pytest.raises(ValueError, match="bandwidth"):
        st.vara.settings({"bw": 1000})


@pytest.mark.parametrize("change, why", [
    (lambda st, rid: setattr(st.ptt, "on", False), "switched off"),
    (lambda st, rid: setattr(st.agent.sender, "here", False), "not at the dashboard"),
    (lambda st, rid: st.agent.cfg.update(license_class=""), "license class"),
    (lambda st, rid: st.agent.cfg.update(license_class="technician"), ""),          # 40 m data: not a Technician's
    (lambda st, rid: st.radios[rid].update(freq_mhz=None), "frequency"),
])
def test_every_transmission_needs_switch_presence_and_privileges(tmp_path, change, why):
    st, rid = _st(tmp_path)
    st.vara.settings({"enabled": True})
    assert st.vara.modem(rid).tx_allowed() == (True, "")
    st.vara.act("connect", {"call": "k7abc"})
    change(st, rid)
    ok, said = st.vara.modem(rid).tx_allowed()
    assert not ok and why in said
    with pytest.raises(ValueError):
        st.vara.act("chat", {"text": "hello"})
    assert FakeVara.made[-1].calls == [("connect", "K7ABC", [])]


def test_listening_stops_when_the_operator_leaves(tmp_path):
    st, rid = _st(tmp_path)
    st.vara.settings({"enabled": True})
    st.vara.act("listen", {"on": True})
    assert st.vara.check() == {rid: None}
    st.agent.sender.here = False
    assert "not at the dashboard" in st.vara.check()[rid]
    assert FakeVara.made[-1].calls[-1] == ("listen", False) and st.vara.modem(rid).last_event["name"] == "listen_off"


def test_handoff_to_winlink_express_and_back(tmp_path, monkeypatch):
    st, rid = _st(tmp_path)
    st.vara.settings({"enabled": True})
    first = FakeVara.made[-1]
    v = st.vara.act("handoff", {})["modems"][0]
    assert first.stopped and v["state"] is None and v["cfg"]["handed_off"] and v["status"]["key"] == "express"
    with pytest.raises(ValueError, match="Winlink Express"):
        st.vara.act("chat", {"text": "x"})
    monkeypatch.setattr(st.vara, "_express", lambda: True)
    with pytest.raises(ValueError, match="still open"):
        st.vara.act("takeback", {})
    monkeypatch.setattr(st.vara, "_express", lambda: False)
    v = st.vara.act("takeback", {})["modems"][0]
    assert not v["cfg"]["handed_off"] and FakeVara.made[-1] is not first and FakeVara.made[-1].started


def test_vara_over_http_and_received_files_are_downloads(tmp_path):
    st, rid = _st(tmp_path)
    inbox = st.data / "vara" / "radios" / rid / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "20261115-1200-K7ABC-map.html").write_bytes(b"<script>alert(1)</script>")
    srv = serve(st, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        v = _post(base, "/api/vara/settings", {"enabled": True, "radio": rid})
        assert v["modems"][0]["tx_ok"] and v["modems"][0]["inbox"][0]["name"].endswith("map.html")
        _post(base, "/api/vara/connect", {"call": "K7ABC"})
        import base64
        _post(base, "/api/vara/file", {"name": "plan.pdf", "data": base64.b64encode(b"%PDF").decode()})
        _post(base, "/api/vara/chat", {"text": "73"})
        assert [c[0] for c in FakeVara.made[-1].calls] == ["connect", "file", "chat"]
        with urllib.request.urlopen(base + "/api/vara/inbox/20261115-1200-K7ABC-map.html") as r:
            assert r.headers["Content-Type"] == "application/octet-stream"
            assert r.headers["Content-Disposition"].startswith("attachment")
            assert r.headers["X-Content-Type-Options"] == "nosniff"
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/api/vara/inbox/..%2Fvara.json")
        with urllib.request.urlopen(base + "/api/vara") as r:
            assert json.loads(r.read())["modems"][0]["cfg"]["enabled"]
    finally:
        srv.shutdown()


def _two(tmp_path):
    """A station with two data radios: FTM (VARA FM) and IC (VARA HF)."""
    st, a = _st(tmp_path, freq=145.07)
    b = "ic2"
    st.radios[a]["name"] = "FTM-150R"
    st.radios[b] = dict(st.radios[a], id=b, name="IC-705", role="winlink", freq_mhz=14.13)
    return st, a, b


def test_two_modems_on_two_radios_run_at_once_each_with_its_own_ports_log_and_turn(tmp_path, monkeypatch):
    """Owner 2026-11-16: one VARA FM for Winlink Express and a separate radio / VARA for chat and files; several VARA
    sessions at once; a modem shared with Winlink Express takes turns."""
    FakeVara.made.clear()
    st, a, b = _two(tmp_path)
    v = st.vara.settings({"radio": a, "kind": "fm", "use": "shared", "enabled": True})
    assert v["modems"][0]["cfg"]["cmd_port"] == 8300
    v = st.vara.settings({"radio": b, "kind": "hf", "use": "chat", "enabled": True})
    m = {x["radio"]: x for x in v["modems"]}
    assert (m[b]["cfg"]["cmd_port"], m[b]["cfg"]["data_port"]) == (8310, 8311)      # the next free pair, suggested
    fa, fb = FakeVara.made[-2], FakeVara.made[-1]
    assert (fa.kw["cmd_port"], fb.kw["cmd_port"]) == (8300, 8310) and fa.kw["kind"] == "fm"
    monkeypatch.setattr(st.vara, "_express", lambda: True)
    assert fa.kw["winlink_open"]() is True                    # shared: steps aside while Winlink Express is open
    assert fb.kw["winlink_open"]() is False                   # chat only: Express uses another modem
    assert fa.kw["log_dir"] != fb.kw["log_dir"]
    st.vara.act("connect", {"radio": a, "call": "K7ABC"})
    st.vara.act("connect", {"radio": b, "call": "N0CALL"})     # two sessions at once
    assert fa.calls == [("connect", "K7ABC", [])] and fb.calls == [("connect", "N0CALL", [])]
    with pytest.raises(ValueError, match="already FTM"):
        st.vara.settings({"radio": b, "cmd_port": 8300})       # each copy of VARA needs its own ports
    with pytest.raises(ValueError, match="which radio"):
        st.vara.act("chat", {"text": "x"})                      # two modems: the radio is named
    with pytest.raises(ValueError, match="only a modem shared"):
        st.vara.act("handoff", {"radio": b})
    st.radios[b]["freq_mhz"] = 14.20                           # phone segment: no data for a General
    assert not st.vara.modem(b).tx_allowed()[0] and st.vara.modem(a).tx_allowed()[0]


def test_a_winlink_express_only_modem_is_never_opened(tmp_path):
    FakeVara.made.clear()
    st, a, b = _two(tmp_path)
    v = st.vara.settings({"radio": a, "kind": "fm", "use": "winlink", "enabled": True})
    assert FakeVara.made == [] and v["modems"][0]["status"]["key"] == "winlink"
    with pytest.raises(ValueError, match="Winlink Express only"):
        st.vara.act("connect", {"radio": a, "call": "K7ABC"})
    v = st.vara.settings({"radio": a, "remove": True})
    assert v["modems"] == [] and [r["modem"] for r in v["radios"]] == [False, False]


def test_the_one_modem_from_before_becomes_a_shared_modem(tmp_path):
    st, rid = _st(tmp_path)
    (st.data / "vara.json").write_text(json.dumps({"enabled": True, "radio": rid, "kind": "fm", "cmd_port": 8400,
                                                   "data_port": 8401, "handed_off": False}))
    m = st.vara.view()["modems"][0]
    assert m["cfg"]["use"] == "shared" and m["cfg"]["cmd_port"] == 8400 and m["cfg"]["enabled"]
    assert st.vara.modem(rid).dir() == st.data / "vara"        # its log and received files stay where they were


def test_a_vara_fm_modem_says_narrow_or_wide(tmp_path):
    st, rid = _st(tmp_path, freq=145.07)
    v = st.vara.settings({"radio": rid, "kind": "fm", "fm_width": "wide", "enabled": True})
    assert v["modems"][0]["cfg"]["fm_width"] == "wide"
    with pytest.raises(ValueError, match="narrow or wide"):
        st.vara.settings({"radio": rid, "fm_width": "medium"})
