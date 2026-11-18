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


def test_the_radio_card_names_who_is_on_the_channel(tmp_path):
    """Owner 2026-11-18: "I don't see anything on the dashboard VARA FM 2 radio column showing that a station has
    announced" - the modem's view (the radio card's) carries the stations here and quiet, and unread messages."""
    st, m, v, clk = _chan(tmp_path)
    assert m.view(transcript=False)["on_channel"] == {"on": False, "stations": [], "more": 0, "unread": 0}
    m.act("join", {})
    m._event("cq_heard", {"call": "K7ABC"})
    clk.t += 11 * 60 + 200
    m._event("cq_heard", {"call": "N0CALL"})
    _link(m, v, "N0CALL")
    v.st.update(peer="N0CALL")
    m._event("chat", {"text": "hello", "peer": "N0CALL"})
    oc = m.view(transcript=False)["on_channel"]
    assert oc["on"] and oc["unread"] == 1
    assert [(x["call"], x["state"]) for x in oc["stations"]] == [("N0CALL", "here"), ("K7ABC", "quiet")]
    clk.t += 60 * 60                                                      # gone: off the card (the window keeps it)
    assert m.view(transcript=False)["on_channel"]["stations"] == []


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


def test_a_link_test_is_queued_saved_per_station_and_gives_file_times(tmp_path):
    """Owner 2026-11-18: the link's speed "on demand by the user"; "the user needs to know how long it will take to
    send various sizes of files". VARA FM starts slow and steps up, so a small file is slower per byte than a big one."""
    from station.varachan import estimate_s
    st, m, v, clk = _chan(tmp_path)
    tests = []
    v.link_test = lambda seconds=None: tests.append(seconds) or 7
    m.act("join", {})
    with pytest.raises(ValueError, match="15 to 180"):
        m.act("linktest", {"to": "K7ABC", "seconds": 5})
    m.act("linktest", {"to": "K7ABC", "seconds": 60})
    assert v.calls[-1][:2] == ("connect", "K7ABC")                       # it goes out like a message: over its own link
    with pytest.raises(ValueError, match="already"):
        m.act("linktest", {"to": "K7ABC"})
    clk.t += 5
    _link(m, v, "K7ABC")
    v.st["peer_caps"] = ["+TEST"]
    m.chan.tick()
    assert tests == [60]
    it = m.chan.view()["threads"]["K7ABC"][-1]
    assert it["kind"] == "test" and it["status"] == "sending"
    clk.t += 25
    m.chan.tick()
    assert ("disconnect",) not in v.calls                                # a test under way keeps the link
    # slow start, then faster: 1 kB in the first 10 s, 31 kB by 60 s
    res = {"bytes": 31_000, "s": 60.0, "bps": 4133, "late_bps": 6400, "level": 7, "modem_bps": 7000, "sn": 20.5,
           "partial": False, "curve": [[0.0, 0], [10.0, 1_000], [40.0, 15_000], [60.0, 31_000]]}
    m._event("test_done", {"seq": 7, "result": res})
    ch = m.chan.view()
    it = ch["threads"]["K7ABC"][-1]
    assert it["status"] == "delivered" and it["result"]["bps"] == 4133 and it["result"]["level"] == 7
    r = next(x for x in ch["roster"] if x["call"] == "K7ABC")
    assert r["speed"]["bps"] == 4133 and r["speed"]["setup_s"] == 8.0    # the call took 5 s (+3 for the handshake)
    est = dict(map(tuple, r["est"]))
    assert est[1_000] == 18 and est[10_000] == 8 + 29                    # read off the test's own curve
    assert est[100_000] == round(8 + 60 + 69_000 / 800)                  # beyond it: at the speed the test reached
    assert est[1_000_000] > est[500_000] > est[100_000] and it["est"] == r["est"]
    assert estimate_s(None, 1000) is None and estimate_s({"curve": [[0, 0]], "bytes": 0}, 1000) is None
    # the other side of a test: named in the thread, nothing kept
    m._event("test_received", {"seq": 3, "bytes": 20_000, "s": 40.0, "bps": 4000, "peer": "K7ABC"})
    ch = m.chan.view()
    assert ch["threads"]["K7ABC"][-1]["dir"] == "in" and ch["threads"]["K7ABC"][-1]["kind"] == "test"
    assert next(x for x in ch["roster"] if x["call"] == "K7ABC")["speed_rx"]["bps"] == 4000
    # a station whose program has no link test
    _drop(m, v)
    m.act("linktest", {"to": "N0CALL", "seconds": 30})
    _link(m, v, "N0CALL")
    v.st["peer_caps"] = []
    m.chan.tick()
    it = m.chan.view()["threads"]["N0CALL"][-1]
    assert it["status"] == "failed" and "update" in it["why"] and tests == [60]


def test_a_file_or_test_on_its_way_can_be_cancelled(tmp_path):
    """Owner 2026-11-18: "also need a way to cancel". VARA can only stop what it holds by dropping the link."""
    st, m, v, clk = _chan(tmp_path)
    m.act("join", {})
    m.act("csend", {"to": ["K7ABC"], "name": "big.bin", "data": base64.b64encode(b"x" * 5000).decode()})
    _link(m, v, "K7ABC")
    m.chan.tick()
    it = m.chan.view()["threads"]["K7ABC"][-1]
    assert it["status"] == "sending"
    m.act("cancel", {"id": it["id"]})
    assert v.calls[-1][0] == "abort"
    m._event("file_failed", {"seq": 1, "name": "big.bin", "why": "the link closed before the receipt"})
    _drop(m, v)
    it = m.chan.view()["threads"]["K7ABC"][-1]
    assert it["status"] == "cancelled" and it["why"] == "you cancelled it"      # not "failed", and not sent again
    clk.t += 120
    m.chan.tick()
    assert [c for c in v.calls if c[0] == "connect"] == [v.calls[[c[0] for c in v.calls].index("connect")]]


def test_a_station_is_reached_through_vara_fm_digipeaters(tmp_path):
    """Owner 2026-11-18: "we need to be able to support routing through VARA FM digipeaters ... with proper
    configuration". A path per station (at most two digipeaters), learnt from the way its announcement came, and one
    for your own announcements."""
    from station.varachan import clean_via
    assert clean_via("k7abc-4, n0call-8") == ["K7ABC-4", "N0CALL-8"] and clean_via("") == [] and clean_via("via K7ABC-4") == ["K7ABC-4"]
    for bad, why in (("K7ABC-4 N0CALL-8 W9XYZ-3", "at most 2"), ("NOT!", "not a callsign"), ("K7ABC-4 K7ABC-4", "twice")):
        with pytest.raises(ValueError, match=why):
            clean_via(bad)
    with pytest.raises(ValueError, match="one end"):
        clean_via("K7ABC", me="W9XYZ", to="K7ABC")
    with pytest.raises(ValueError, match="VARA FM only"):
        clean_via("K7ABC-4", kind="hf")
    st, m, v, clk = _chan(tmp_path)
    cqs = []
    v.cq = lambda via=(): cqs.append(list(via))
    m.act("join", {})
    assert cqs == [[]]
    m.act("channel", {"announce_via": "n0call-4"})                       # your announcements go through it too
    m.act("announce", {})
    assert cqs[-1] == ["N0CALL-4"] and m.chan.view()["announce_via"] == ["N0CALL-4"]
    # set by hand: the link is called through it, and waits longer for the answer
    m.act("channel", {"via_for": "K7ABC", "via": "N0CALL-4 N0CALL-8"})
    m.act("csend", {"to": ["K7ABC"], "text": "through the hill"})
    assert v.calls[-1] == ("connect", "K7ABC", ["N0CALL-4", "N0CALL-8"])
    clk.t += 400                                                         # 150 s a hop: 3 x 150 = 450 s here
    m.chan.tick()
    assert not any(c[0] == "abort" for c in v.calls)
    clk.t += 60
    m.chan.tick()
    assert any(c[0] == "abort" for c in v.calls)
    r = next(x for x in m.chan.view()["roster"] if x["call"] == "K7ABC")
    assert r["via"] == ["N0CALL-4", "N0CALL-8"] and r["via_by"] == "you"
    # learnt: an announcement that came through digipeaters gives the way back (reversed); heard direct clears it
    m._event("cq_heard", {"call": "W9XYZ-3", "via": ["N0CALL-8", "N0CALL-4"]})
    r = next(x for x in m.chan.view()["roster"] if x["call"] == "W9XYZ-3")
    assert r["via"] == ["N0CALL-4", "N0CALL-8"] and r["via_by"] == "heard"
    m._event("cq_heard", {"call": "W9XYZ-3", "via": []})
    assert next(x for x in m.chan.view()["roster"] if x["call"] == "W9XYZ-3")["via"] == []
    m._event("cq_heard", {"call": "K7ABC", "via": []})                   # the one you set by hand stays
    assert next(x for x in m.chan.view()["roster"] if x["call"] == "K7ABC")["via"] == ["N0CALL-4", "N0CALL-8"]
    m.act("channel", {"via_for": "K7ABC", "via": ""})                    # empty: direct again
    assert next(x for x in m.chan.view()["roster"] if x["call"] == "K7ABC")["via"] == []


def test_a_file_that_did_not_arrive_is_in_the_message_log(tmp_path):
    st, m, v, clk = _chan(tmp_path)
    m.act("join", {})
    _link(m, v, "K7ABC")
    m._event("file_rejected", {"seq": 1, "name": "big.xlsx", "size": 5000, "done": 2000, "why": "you cancelled it", "peer": "K7ABC"})
    m._event("file_rejected", {"seq": 2, "name": "b.pdf", "size": 900, "done": 100, "peer": "K7ABC",
                               "why": "the link closed before the file was whole (the sender may have cancelled it)"})
    th = [it for it in m.chan.view()["threads"]["K7ABC"] if it["kind"] == "file"]
    assert [(it["dir"], it["status"], it["name"], it["done"]) for it in th] == [("in", "cancelled", "big.xlsx", 2000), ("in", "failed", "b.pdf", 100)]


def test_a_file_arriving_has_its_own_line_in_the_chat_from_the_start(tmp_path):
    """Owner 2026-11-18: "Can we put the file transfer inline in the message log like we do with the sender?" """
    st, m, v, clk = _chan(tmp_path)
    m.act("join", {})
    _link(m, v, "K7ABC")
    m._event("file_receiving", {"seq": 1, "name": "big.xlsx", "size": 5000})
    m._event("file_receiving", {"seq": 1, "name": "big.xlsx", "size": 5000})        # the notice, then the header: one line
    th = m.chan.view()["threads"]["K7ABC"]
    assert [(it["dir"], it["status"], it["name"], it["size"]) for it in th] == [("in", "receiving", "big.xlsx", 5000)]
    clk.t += 40
    m._event("file_received", {"seq": 1, "name": "big.xlsx", "size": 5000, "path": "/x/inbox/20261118-K7ABC-big.xlsx", "peer": "K7ABC"})
    th = m.chan.view()["threads"]["K7ABC"]
    assert len(th) == 1 and th[0]["status"] == "received" and th[0]["name"] == "20261118-K7ABC-big.xlsx" and th[0]["took_s"] == 40
    m._event("file_receiving", {"seq": 2, "name": "b.pdf", "size": 900})
    m._event("file_rejected", {"seq": 2, "name": "b.pdf", "size": 900, "done": 300, "why": "you cancelled it", "peer": "K7ABC"})
    m._event("file_receiving", {"seq": 3, "name": "c.pdf", "size": 900})
    _drop(m, v)
    th = [it for it in m.chan.view()["threads"]["K7ABC"] if it["kind"] == "file"]
    assert [(it["name"], it["status"]) for it in th[1:]] == [("b.pdf", "cancelled"), ("c.pdf", "failed")]


def test_the_sender_is_told_the_receiver_cancelled_so_it_is_not_taken_for_a_link_failure(tmp_path):
    """Owner 2026-11-18: "the sender says that the link closed before the receipt. We should state that it was
    cancelled by the receiver (give receiver SSID) so that we know that it wasn't a VARA FM failure." """
    # the receiver: Cancel logs it and queues a note, which goes over a short link of its own
    st, m, v, clk = _chan(tmp_path)
    notes = []
    v.send_note = notes.append
    m.act("join", {})
    _link(m, v, "W9XYZ-8")
    m._event("file_receiving", {"seq": 1, "name": "big.xlsx", "size": 5000})
    m._event("file_rejected", {"seq": 1, "name": "big.xlsx", "size": 5000, "done": 3050, "why": "you cancelled it", "peer": "W9XYZ-8"})
    _drop(m, v)
    th = m.chan.view()["threads"]["W9XYZ-8"]
    assert [(it["kind"], it["status"]) for it in th] == [("file", "cancelled"), ("note", "queued")]
    clk.t += 5
    m.chan.tick()
    assert v.calls[-1][:2] == ("connect", "W9XYZ-8")
    _link(m, v, "W9XYZ-8")
    m.chan.tick()
    assert notes == ["RXCANCEL big.xlsx 3050 5000"]
    m._event("buffer", {"bytes": 0})
    assert m.chan.view()["threads"]["W9XYZ-8"][-1]["status"] == "delivered"
    # the sender: its file line says who cancelled, and that the link did not fail
    st2, m2, v2, clk2 = _chan(tmp_path / "s")
    m2.act("join", {})
    m2.act("csend", {"to": ["K7ABC-7"], "name": "big.xlsx", "data": base64.b64encode(b"x" * 5000).decode()})
    _link(m2, v2, "K7ABC-7")
    m2.chan.tick()
    m2._event("file_failed", {"seq": 1, "name": "big.xlsx", "why": "the link closed before the receipt"})
    _drop(m2, v2)
    _link(m2, v2, "K7ABC-7")
    m2._event("rx_cancelled", {"name": "big.xlsx", "done": 3050, "size": 5000, "peer": "K7ABC-7"})
    it = m2.chan.view()["threads"]["K7ABC-7"][-1]
    assert it["status"] == "failed" and it["cancelled_by"] == "K7ABC-7"
    assert it["why"] == "cancelled by the operator at K7ABC-7 after 61% had arrived: not a link failure"
