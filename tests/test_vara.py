"""VARA chat and file transfer (station/vara.py) against fake VARA modems: real localhost sockets on ephemeral ports,
two of them bridged so two stations can talk. The framing is docs/VARA.md."""
import hashlib
import socket
import threading
import time

import pytest

from station import vara as V


class FakeVara:
    """VARA's TCP interface: a command port (CR lines) and a data port. CONNECT links to the partner when it listens;
    data written here comes out at the partner's data port (in `chunk`-byte pieces when set)."""

    def __init__(self):
        self.cmds, self.partner, self.listening, self.chunk = [], None, False, None
        self.cmd_conn = self.data_conn = None
        self.accepted = 0
        self.linked = False
        self.ls = [socket.socket(), socket.socket()]
        for s in self.ls:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 0))
            s.listen(4)
            s.settimeout(0.2)
        self.ports = [s.getsockname()[1] for s in self.ls]
        self.stop = threading.Event()
        for i in (0, 1):
            threading.Thread(target=self._accept, args=(i,), daemon=True).start()

    def _accept(self, i):
        while not self.stop.is_set():
            try:
                c, _ = self.ls[i].accept()
            except OSError:
                continue
            self.accepted += 1
            if i == 0:
                self.cmd_conn = c
                threading.Thread(target=self._read_cmd, args=(c,), daemon=True).start()
            else:
                self.data_conn = c
                threading.Thread(target=self._read_data, args=(c,), daemon=True).start()

    def push(self, line):
        for _ in range(100):
            if self.cmd_conn:
                break
            time.sleep(0.01)
        self.cmd_conn.sendall((line + "\r").encode())

    def _read_cmd(self, c):
        buf = b""
        while True:
            try:
                b = c.recv(4096)
            except OSError:
                return
            if not b:
                return
            buf += b
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                self._cmd(line.decode())

    def _cmd(self, line):
        self.cmds.append(line)
        w = line.split()
        self.push("OK")
        k = w[0]
        if line in ("CHAT ON", "LISTEN ON"):
            self.listening = True
        elif line == "LISTEN OFF":
            self.listening = False
        elif k == "CONNECT" and self.partner and self.partner.listening:
            self.linked = self.partner.linked = True
            msg = f"CONNECTED {w[1]} {w[2]} 2300"
            self.push(msg)
            self.partner.push(msg)
        elif k in ("DISCONNECT", "ABORT") and self.linked:
            self.linked = self.partner.linked = False
            self.push("DISCONNECTED")
            self.partner.push("DISCONNECTED")
        elif k == "CQFRAME" and self.partner:
            self.partner.push(" ".join(["CQFRAME"] + w[1:]))

    def _read_data(self, c):
        while True:
            try:
                b = c.recv(65536)
            except OSError:
                return
            if not b:
                return
            if self.linked and self.partner and self.partner.data_conn:
                self.push(f"BUFFER {len(b)}")
                n = self.chunk or len(b)
                for i in range(0, len(b), n):
                    self.partner.data_conn.sendall(b[i:i + n])
                self.push("BUFFER 0")

    def close(self):
        self.stop.set()
        for s in [*self.ls, self.cmd_conn, self.data_conn]:
            if s:
                try:
                    s.close()
                except OSError:
                    pass


def wait(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class Station:
    def __init__(self, tmp, call, fake, **kw):
        self.events, self.tx = [], [True]
        self.fake = fake
        self.v = V.Vara(tmp / call, call, host="127.0.0.1", cmd_port=fake.ports[0], data_port=fake.ports[1],
                        tx_allowed=lambda: (self.tx[0], "the operator is away"), winlink_open=kw.pop("winlink_open",
                                                                                                    lambda: False),
                        on_event=lambda n, d: self.events.append((n, d)), reconnect_s=0.1, tick_s=0.05, **kw)

    def got(self, name):
        return [d for n, d in self.events if n == name]


@pytest.fixture
def pair(tmp_path):
    a, b = FakeVara(), FakeVara()
    a.partner, b.partner = b, a
    A, B = Station(tmp_path, "W9XYZ", a), Station(tmp_path, "K7ABC", b)
    A.v.start()
    B.v.start()
    assert wait(lambda: A.v.state()["link"] == "up" and B.v.state()["link"] == "up")
    yield A, B
    A.v.stop()
    B.v.stop()
    a.close()
    b.close()
    assert not any("ENCRYPT" in c.upper() for c in a.cmds + b.cmds)       # Part 97.113: never


def _link(A, B):
    B.v.listen(True)
    assert wait(lambda: B.fake.listening)                                    # the fake modem applied CHAT ON
    A.v.connect("K7ABC")
    assert wait(lambda: A.v.state()["peer_proto"] == "HSK1" and B.v.state()["peer_proto"] == "HSK1")


def test_setup_commands_and_status_parsing(pair):
    A, _ = pair
    assert wait(lambda: "CWID ON" in A.fake.cmds)
    assert A.fake.cmds[:5] == ["MYCALL W9XYZ", "LISTEN OFF", "COMPRESSION TEXT", "P2P SESSION", "CWID ON"]
    for line in ("BUSY ON", "SN 12.5", "IAMALIVE", "REGISTERED W9XYZ", "PTT ON", "CQFRAME K7ABC 500", "PENDING"):
        A.fake.push(line)
    assert wait(lambda: A.got("cq_heard") and A.v.state()["session"] == "pending")
    s = A.v.state()
    assert s["busy"] and s["sn"] == 12.5 and s["alive_at"] and s["registered"] == "W9XYZ" and s["ptt"]
    assert s["busy_at"] and s["ptt_at"]        # when VARA last keyed / heard something: shown after an announcement
    assert s["cq_heard"][0]["call"] == "K7ABC" and s["cq_heard"][0]["bw"] == 500
    A.fake.push("CANCELPENDING")
    A.fake.push("MISSING SOUNDCARD")
    assert wait(lambda: not A.v.state()["soundcard_ok"])
    assert A.v.state()["session"] == "idle" and "sound card" in A.v.state()["error"]


def test_chat_round_trip_and_the_transcript(pair, tmp_path):
    A, B = pair
    _link(A, B)
    assert A.v.state()["peer"] == "K7ABC" and B.v.state()["peer"] == "W9XYZ"
    A.v.send_chat("Good evening, ünïcode ok\nsecond line")
    assert wait(lambda: B.got("chat"))
    assert B.got("chat")[0]["text"] == "Good evening, ünïcode ok\nsecond line" and not B.got("chat")[0]["raw"]
    B.v.send_chat("73")
    assert wait(lambda: A.got("chat") and A.got("chat")[0]["text"] == "73")
    log = next((tmp_path / "K7ABC" / "vara").glob("*.jsonl")).read_text()
    assert '"dir": "in"' in log and "Good evening" in log
    A.v.disconnect()
    assert wait(lambda: A.got("disconnected") and B.got("disconnected"))
    assert wait(lambda: "LISTEN OFF" in A.fake.cmds[5:])                   # CONNECT had turned listening on


def test_a_file_arrives_checked_in_the_inbox(pair, tmp_path):
    A, B = pair
    _link(A, B)
    data = bytes(range(256)) * 400
    seq = A.v.send_file(name="ICS-213 report.pdf", data=data)
    assert wait(lambda: A.got("file_sent"))
    got = B.got("file_received")[0]
    assert got["sha256"] == hashlib.sha256(data).hexdigest() and got["name"] == "ICS-213_report.pdf"
    assert open(got["path"], "rb").read() == data and "/vara/inbox/" in got["path"].replace("\\", "/")
    assert A.got("file_sent")[0]["seq"] == seq
    i = A.fake.cmds.index("COMPRESSION FILES")
    assert wait(lambda: "COMPRESSION TEXT" in A.fake.cmds[i:])               # back to text once the receipt came


def test_a_corrupted_or_oversized_file_is_refused(pair, tmp_path):
    A, B = pair
    _link(A, B)
    A.v._data(b"FILE 9 x.txt 3 " + b"0" * 64 + b"\nabc")                    # the wrong checksum
    assert wait(lambda: B.got("file_rejected"))
    assert "checksum" in B.got("file_rejected")[0]["why"]
    assert not list((tmp_path / "K7ABC" / "vara" / "inbox").glob("*x.txt")) if (tmp_path / "K7ABC" / "vara" / "inbox").exists() else True
    B.v.max_file = 10
    A.v.max_file = 100
    A.v.send_file(name="big.bin", data=b"y" * 50)
    assert wait(lambda: A.got("file_failed"))
    assert "too large" in A.got("file_failed")[0]["why"]
    A.v.send_chat("still talking")                                          # the stream stays in step after it
    assert wait(lambda: any(c["text"] == "still talking" for c in B.got("chat")))


def test_bytes_arriving_one_at_a_time(pair):
    A, B = pair
    _link(A, B)
    A.fake.chunk = 1
    A.v.send_chat("slow link")
    A.v.send_file(name="n.txt", data=b"hello world" * 30)
    assert wait(lambda: B.got("chat") and B.got("file_received"), 5)
    assert B.got("chat")[0]["text"] == "slow link"


def test_nothing_transmits_without_permission(pair):
    A, B = pair
    A.tx[0] = False
    for act in (lambda: A.v.connect("K7ABC"), A.v.cq, lambda: A.v.listen(True)):
        with pytest.raises(V.VaraRefused, match="away"):
            act()
    assert not any(c.startswith(("CONNECT", "CQFRAME", "CHAT ON")) for c in A.fake.cmds)
    A.tx[0] = True
    _link(A, B)
    A.tx[0] = False                                                          # the operator left mid-session
    with pytest.raises(V.VaraRefused, match="away"):
        A.v.send_chat("hello")                                               # refused, nothing sent
    assert "ABORT" not in A.fake.cmds
    B.v.send_file(name="r.txt", data=b"report")                             # A's receipt would transmit: abort
    assert wait(lambda: "ABORT" in A.fake.cmds)
    assert wait(lambda: A.got("disconnected"))


def test_abort_drops_the_link(pair):
    A, B = pair
    _link(A, B)
    A.v.abort()
    assert wait(lambda: A.got("disconnected") and B.got("disconnected"))
    assert "ABORT" in A.fake.cmds and A.v.state()["session"] == "idle"


def test_station_keyed_ptt_follows_vara_with_a_watchdog(tmp_path):
    fake = FakeVara()
    keyed = []
    clock = [1000.0]
    S = Station(tmp_path, "W9XYZ", fake, ptt=keyed.append, ptt_mode="station", clock=lambda: clock[0])
    S.v.tick_s = 60
    S.v.start()
    try:
        assert wait(lambda: S.v.state()["link"] == "up")
        fake.push("PTT ON")
        assert wait(lambda: keyed == [True])
        fake.push("PTT OFF")
        assert wait(lambda: keyed == [True, False])
        fake.push("PTT ON")
        assert wait(lambda: keyed[-1] is True)
        assert S.v.watchdog(now=clock[0] + 601) and "600" in S.got("watchdog")[0]["why"]
        assert keyed[-1] is False and wait(lambda: "ABORT" in fake.cmds)
        S.tx[0] = False                                                      # VARA asks to key with no permission
        n = len(keyed)
        fake.push("PTT ON")
        assert wait(lambda: fake.cmds.count("ABORT") == 2)
        assert True not in keyed[n:]
    finally:
        S.v.stop()
        fake.close()


def test_never_encrypt_and_names_are_cleaned():
    v = V.Vara("/tmp/unused", "W9XYZ", winlink_open=lambda: False)
    with pytest.raises(V.VaraRefused, match="97.113"):
        v._cmd("ENCRYPT ON")
    assert V.clean_name("../../Windows/evil.exe") == "evil.exe.blocked"
    assert V.clean_name(".hidden") == "hidden" and V.clean_name("") == "file"
    assert V.clean_name("a b/c?.txt") == "c_.txt"
    with pytest.raises(ValueError):
        V.Vara("/tmp/unused", "not a call", winlink_open=lambda: False)


def test_winlink_express_open_keeps_us_off_vara(tmp_path):
    fake = FakeVara()
    S = Station(tmp_path, "W9XYZ", fake, winlink_open=lambda: True)
    S.v.start()
    try:
        time.sleep(0.3)
        assert fake.accepted == 0
        ok, why = S.v.available()
        assert not ok and "Winlink Express" in why
        with pytest.raises(V.VaraRefused, match="Winlink Express"):
            S.v.connect("K7ABC")
    finally:
        S.v.stop()
        fake.close()


def test_a_plain_vara_terminal_gets_text_and_no_files(pair):
    A, B = pair
    B.v.listen(True)
    assert wait(lambda: B.fake.listening)
    A.v.connect("K7ABC")
    assert wait(lambda: B.v.state()["session"] == "connected")
    B.v._data(b"hello from a plain terminal\r\n")                            # no HSK1 first: a plain terminal
    assert wait(lambda: A.got("chat"))
    c = A.got("chat")[0]
    assert c["raw"] and c["text"] == "hello from a plain terminal" and A.v.state()["peer_proto"] == "raw"
    with pytest.raises(V.VaraRefused, match="handshake"):
        A.v.send_file(name="x.txt", data=b"x")


def test_two_ssids_of_one_callsign_are_two_stations(tmp_path):
    """Owner 2026-11-17: W9XYZ-8 on one station, W9XYZ-7 on the other. A call from W9XYZ-7 to W9XYZ-8 is from the
    other station: the peer is W9XYZ-7 and it came in (it was once taken for our own outgoing call: same base call)."""
    assert V._same_call("W9XYZ", "W9XYZ-0") and not V._same_call("W9XYZ-7", "W9XYZ-8")
    v = V.Vara(tmp_path, "W9XYZ-8", winlink_open=lambda: False)
    got = []
    v.on_event = lambda name, data: got.append((name, data))
    v._on_status("CONNECTED W9XYZ-7 W9XYZ-8 2300")
    assert v.state()["peer"] == "W9XYZ-7" and ("connected", {"peer": "W9XYZ-7", "via": [], "bw": 2300}) in got
    v._on_status("DISCONNECTED")
    v._on_status("CONNECTED W9XYZ-8 W9XYZ-7 2300")             # our own call out
    assert v.state()["peer"] == "W9XYZ-7"
    import json
    log = next((tmp_path / "vara").glob("*.jsonl")).read_text().splitlines()
    assert [json.loads(x)["dir"] for x in log if json.loads(x)["kind"] == "connected"] == ["in", "out"]
