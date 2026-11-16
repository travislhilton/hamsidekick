"""The VARA channel (station/varachan.py). Owner 2026-11-16: announce on joining, keep-alives, grey out a station
whose keep-alive stops, pick a station and chat / send a file, several stations "at once", quick messages."""
import base64

import pytest

from station import varalink
from tests.test_varalink import FakeVara, _st


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


class ChanVara(FakeVara):
    max_file = 5 * 1024 * 1024

    def __init__(self, **kw):
        super().__init__(**kw)
        self.seq = 0
        self.st.update(busy=False, buffer=0, sending=None, peer_proto=None, kind=kw.get("kind"))

    def connect(self, call, via=()):
        super().connect(call, via)
        self.st.update(session="connecting", peer=call)

    def send_chat(self, text):
        super().send_chat(text)
        self.seq += 1
        return self.seq

    def send_file(self, name, data):
        super().send_file(name, data)
        self.seq += 1
        return self.seq


def _chan(tmp_path):
    st, rid = _st(tmp_path, freq=445.525, cls="technician")
    clk = Clock()
    st._vara = varalink.Link(st, factory=ChanVara, clock=clk)
    st.vara.settings({"enabled": True, "radio": rid, "kind": "fm"})
    m = st.vara.modem(rid)
    return st, m, m.vara, clk


def _link(m, v, peer, proto="HSK1"):
    v.st.update(session="connected", peer=peer, peer_proto=proto)
    m._event("connected", {"peer": peer})


def _drop(m, v):
    peer = v.st["peer"]
    v.st.update(session="idle", peer=None, peer_proto=None)
    m._event("disconnected", {"peer": peer, "why": "done"})


def test_join_announces_and_keeps_alive(tmp_path):
    st, m, v, clk = _chan(tmp_path)
    m.act("join", {})
    assert ("listen", True) in v.calls and v.calls[-1] == ("cq",)
    ch = m.chan.view()
    assert ch["on"] and ch["every_min"] == 10 and ch["next_announce_s"] == 600
    clk.t += 599
    m.chan.tick()
    assert v.calls[-1] == ("cq",) and len([c for c in v.calls if c == ("cq",)]) == 1
    clk.t += 2
    m.chan.tick()
    assert len([c for c in v.calls if c == ("cq",)]) == 2                 # the keep-alive
    st.agent.sender.here = False                                          # you left: nothing goes out
    clk.t += 700
    m.chan.tick()
    assert len([c for c in v.calls if c == ("cq",)]) == 2
    with pytest.raises(ValueError):
        m.chan.settings({"every_min": 2})                                  # at least 5 minutes apart
    m.act("leave", {})
    assert not m.chan.view()["on"]


def test_stations_heard_are_here_then_grey_then_gone(tmp_path):
    st, m, v, clk = _chan(tmp_path)
    m._event("cq_heard", {"call": "K7ABC", "bw": None, "via": []})
    r = m.chan.view()["roster"][0]
    assert r["call"] == "K7ABC" and r["state"] == "here"
    clk.t += 10 * 60 + 170
    assert m.chan.view()["roster"][0]["state"] == "here"                  # a late keep-alive: grace
    clk.t += 20
    assert m.chan.view()["roster"][0]["state"] == "quiet"                 # missed: greyed out
    clk.t += 20 * 60
    assert m.chan.view()["roster"][0]["state"] == "gone"
    m._event("cq_heard", {"call": "K7ABC"})
    assert m.chan.view()["roster"][0]["state"] == "here"


def test_one_message_to_two_stations_goes_link_by_link(tmp_path):
    st, m, v, clk = _chan(tmp_path)
    m.act("csend", {"to": ["K7ABC", "N0CALL"], "text": "Net at 1900, all welcome"})
    assert v.calls[-1] == ("connect", "K7ABC", [])                        # the oldest waiting station first
    _link(m, v, "K7ABC")
    m.chan.tick()
    assert v.calls[-1] == ("chat", "Net at 1900, all welcome")
    th = m.chan.view()["threads"]
    assert th["K7ABC"][0]["status"] == "sent" and th["N0CALL"][0]["status"] == "queued"
    m._event("buffer", {"bytes": 0})
    assert m.chan.view()["threads"]["K7ABC"][0]["status"] == "delivered"
    m._event("chat", {"seq": 1, "text": "QSL, see you there", "peer": "K7ABC"})
    m.chan.tick()
    assert v.calls[-1] != ("disconnect",)                                  # never mid-exchange
    clk.t += 6
    m.chan.tick()                                                          # another station waits: let go now
    assert v.calls[-1] == ("disconnect",)
    _drop(m, v)
    m.chan.tick()
    assert v.calls[-1] == ("connect", "N0CALL", [])
    v.st.update(session="idle", peer=None)
    m._event("disconnected", {"peer": "N0CALL", "why": "no answer"})       # never answered
    it = m.chan.view()["threads"]["N0CALL"][0]
    assert it["status"] == "queued" and it["tries"] == 1
    for _ in range(2):
        clk.t += 400
        m.chan.tick()
        v.st.update(session="idle", peer=None)
        m._event("disconnected", {"peer": "N0CALL"})
    it = m.chan.view()["threads"]["N0CALL"][0]
    assert it["status"] == "failed" and "did not answer" in it["why"]
    roster = {r["call"]: r for r in m.chan.view()["roster"]}
    assert roster["K7ABC"]["unread"] == 1 and roster["N0CALL"]["failed"] == 1
    m.act("retry", {"id": it["id"]})
    assert v.calls[-1] == ("connect", "N0CALL", [])


def test_a_link_we_opened_closes_when_quiet_unless_kept_open(tmp_path):
    st, m, v, clk = _chan(tmp_path)
    m.act("csend", {"to": "K7ABC", "text": "hello"})
    _link(m, v, "K7ABC")
    m.chan.tick()
    m._event("buffer", {"bytes": 0})
    m.act("channel", {"pin": "K7ABC"})                                     # Keep the link open
    clk.t += 120
    m.chan.tick()
    assert v.calls[-1] != ("disconnect",)
    m.act("channel", {"pin": None})
    m.chan.tick()
    assert v.calls[-1] == ("disconnect",)


def test_files_and_a_link_someone_else_opened(tmp_path):
    st, m, v, clk = _chan(tmp_path)
    data = base64.b64encode(b"ICS-213 text").decode()
    m.act("csend", {"to": "K7ABC", "name": "msg.txt", "data": data})
    v.st.update(session="idle")
    v.calls.clear()
    clk.t += 5
    m.chan.opened = None                                                    # K7ABC calls us first
    v.st.update(session="connected", peer="K7ABC", peer_proto=None)
    m._event("connected", {"peer": "K7ABC"})
    m.chan.tick()
    assert not any(c[0] == "file" for c in v.calls)                       # waits for the handshake
    v.st["peer_proto"] = "HSK1"
    m.chan.tick()
    assert [c[:2] for c in v.calls if c[0] == "file"] == [("file", "msg.txt")]
    m._event("file_sent", {"seq": v.seq, "name": "msg.txt"})
    assert m.chan.view()["threads"]["K7ABC"][0]["status"] == "delivered"
    clk.t += 300
    m.chan.tick()
    assert ("disconnect",) not in v.calls                                  # their link: they close it
    m._event("file_received", {"seq": 1, "name": "map.png", "size": 10, "path": "/x/20261116-K7ABC-map.png",
                               "peer": "K7ABC"})
    assert m.chan.view()["threads"]["K7ABC"][-1]["name"] == "20261116-K7ABC-map.png"


def test_presets_and_http(tmp_path):
    import json
    import threading
    import urllib.request
    from station.server import serve
    from tests.test_history import _post
    st, m, v, clk = _chan(tmp_path)
    ch = m.chan.view()
    assert any("{them}" in p for p in ch["presets"]) and ch["me"]["call"] == "W9XYZ"
    m.chan.settings({"presets": ["QRV on 445.525", "  ", "73"]})
    assert m.chan.view()["presets"] == ["QRV on 445.525", "73"]
    srv = serve(st, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        r = _post(base, "/api/vara/join", {"radio": m.rid})
        assert r["modems"][0]["channel"]["on"]
        r = _post(base, "/api/vara/csend", {"radio": m.rid, "to": ["K7ABC"], "text": "hi"})
        assert r["modems"][0]["channel"]["threads"]["K7ABC"][0]["text"] == "hi"
        with urllib.request.urlopen(base + "/api/vara") as h:
            assert json.loads(h.read())["modems"][0]["channel"]["roster"][0]["call"] == "K7ABC"
    finally:
        srv.shutdown()
