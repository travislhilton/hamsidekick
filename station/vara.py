"""Keyboard chat and file transfer over VARA HF / VARA FM (owner 2026-11-15: "add chat and file transfer over VARA FM
and VARA HF").

VARA (the modem) is driven over its TCP interface, the one Winlink Express, Pat and chat programs use:

  command port (8300)  ASCII lines ending in CR, both ways: we send MYCALL, LISTEN, CHAT ON, CONNECT, CQFRAME...;
                       VARA answers OK / WRONG and reports CONNECTED, DISCONNECTED, BUFFER, PTT ON/OFF, BUSY, SN,
                       PENDING, CANCELPENDING, REGISTERED, IAMALIVE, MISSING SOUNDCARD, CQFRAME (a CQ heard)
  data port (8301)     the connected session's bytes, in whatever chunks the link delivers them

On top of the data port this station speaks its own small, published framing, "HSK1" (docs/VARA.md). It is not
VarAC's protocol (unpublished, and its terms forbid rebuilding it); it talks to other stations running this program,
and a plain VARA terminal still gets readable text.

    HSK1 <call>\\n                                  each side, once, right after CONNECTED
    MSG <seq> <len>\\n<len bytes of UTF-8>          a chat message
    FILE <seq> <name> <size> <sha256>\\n<size bytes>  a file (name percent-encoded, no spaces)
    ACK <seq>\\n | NAK <seq> <reason>\\n              the receiver's answer to a FILE
    TEST <seq> <len>\\n<len bytes>                  link test data (random bytes: thrown away by the receiver)
    TESTEND <seq>\\n -> TESTED <seq> <bytes> <ms>\\n  the end of a link test, and the receiver's count and time

A link test (the operator asks for it: "Test link speed") measures what a file would get: VARA starts slow and steps
its speed up as data flows, so the test feeds random bytes for a set time and records how many the other modem had
taken, second by second. It is sent only to a station whose handshake ends in "+TEST" (HSK1 <call> +TEST).

A station that never sends "HSK1 " is a plain terminal: its bytes are shown as chat lines and our chat goes to it as
plain text lines; files are not offered to it. During a file the modem is set to COMPRESSION FILES, otherwise TEXT.

Received files go to data/vara/inbox/ (a quarantine folder: names cleaned, a size limit, the SHA-256 checked, and an
executable kind given a ".blocked" ending so a double-click never runs it). Everything sent and received is appended
to data/vara/YYYY-MM.jsonl.

Transmitting (Part 97): every transmission this class can cause goes through `tx_allowed()` first, injected by the
station (operator present, the radio's transmit switch on): CONNECT, CQFRAME, LISTEN/CHAT ON (VARA answers calls by
itself while listening), every byte written to the data port (chat, files, and the protocol's own HSK1/ACK/NAK; a
refusal mid-session aborts the link), and a station-keyed PTT. There is no auto-reply, relay or forwarding (the channel's
keep-alive CQ frames, varachan.py, go only while the operator is at the station, at least 5 minutes apart):
only the protocol's handshake and file receipts are sent without a key press, inside a session the operator opened or
accepted by listening. No ENCRYPT command is ever sent (97.113: no messages obscured in meaning); `_cmd` refuses one.

PTT: "vara" (VARA keys the radio itself: its own COM / RA-Board / CAT setting; we only show it) or "station" (VARA's
PTT ON/OFF orders key the radio through the injected `ptt(on)`, the station's Transmitter). A watchdog aborts the link
when the PTT stays on, or a file waits for its receipt, longer than `watchdog_s` (600 s).

One client at a time: VARA serves one program. While Winlink Express is open (`winlink_open()`), this class neither
connects to VARA nor holds it; when Express opens while we are idle, we let go.
"""
from __future__ import annotations

import hashlib
import json
import re
import selectors
import socket
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

CMD_PORT, DATA_PORT = 8300, 8301
KINDS = ("hf", "fm")
PTT_MODES = ("vara", "station")
MAX_FILE = 5 * 1024 * 1024
MAX_CHAT = 4000
MAX_HEADER = 1024
WATCHDOG_S = 600.0
RECONNECT_S = 5.0
BLOCKED = {".exe", ".bat", ".cmd", ".com", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".msi", ".msp", ".scr",
           ".lnk", ".dll", ".hta", ".jar", ".reg", ".cpl", ".pif", ".sys"}
CAPS = "+TEST"                      # after our call in the handshake: what this build understands beyond MSG / FILE
TEST_S, TEST_MIN_S, TEST_MAX_S = 60, 15, 180
TEST_MAX_BYTES = 400_000
TEST_STALE_S = 6.0
OFFER_WAIT_S = 8.0                  # a file follows its notice when the modem has sent the notice, or after this long
TEST_CHUNK = (1024, 16384)          # a test keeps this much ahead of the modem: about 15 s of data at the current speed
CALL_RE = re.compile(r"^[A-Z0-9]{3,7}(-([1-9]|1[0-5]|T|R))?$")


def _same_call(a: str, b: str) -> bool:
    """One station: the same call and SSID (no SSID = -0). Two SSIDs of one callsign are two stations."""
    def n(c):
        c = str(c or "").upper().strip()
        return c[:-2] if c.endswith("-0") else c
    return n(a) == n(b)


class VaraRefused(RuntimeError):
    """An action refused before anything was sent (no transmit permission, not connected, a bad argument)."""


def clean_name(name: str) -> str:
    """A received file name made safe for the inbox: no folders, no odd characters, never empty or hidden."""
    base = re.split(r"[\\/]", str(name or ""))[-1]
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).lstrip(".")[:80] or "file"
    stem, dot, ext = base.rpartition(".")
    if dot and ("." + ext.lower()) in BLOCKED:
        base += ".blocked"
    return base


class Vara:
    def __init__(self, data_dir, mycall: str, kind: str = "hf", host: str = "127.0.0.1", cmd_port: int = CMD_PORT,
                 data_port: int = DATA_PORT, tx_allowed=None, ptt=None, ptt_mode: str = "vara",
                 winlink_open=None, on_event=None, bw: int | None = None, max_file: int = MAX_FILE,
                 watchdog_s: float = WATCHDOG_S, reconnect_s: float = RECONNECT_S, clock=time.time,
                 tick_s: float = 0.5, log_dir=None):
        call = str(mycall or "").strip().upper()
        if not CALL_RE.match(call):
            raise ValueError("set your callsign first (3-7 letters and digits, an optional -SSID)")
        if kind not in KINDS:
            raise ValueError("VARA kind is hf or fm")
        if ptt_mode not in PTT_MODES:
            raise ValueError("PTT is keyed by vara or by the station")
        if ptt_mode == "station" and ptt is None:
            raise ValueError("PTT by the station needs the station's transmitter")
        if bw is not None and bw not in (500, 2300, 2750):
            raise ValueError("VARA HF bandwidth is 500, 2300 or 2750 Hz")
        self.dir = Path(log_dir) if log_dir else Path(data_dir) / "vara"     # one folder per modem (varalink.py)
        self.mycall, self.kind, self.host, self.ports = call, kind, host, (int(cmd_port), int(data_port))
        self.tx_allowed = tx_allowed or (lambda: (False, "transmitting is not allowed"))
        self.ptt, self.ptt_mode = ptt, ptt_mode
        if winlink_open is None:
            from .winlink import express_running as winlink_open
        self.winlink_open = winlink_open
        self.on_event = on_event or (lambda name, data: None)
        self.bw, self.max_file, self.watchdog_s = bw, int(max_file), float(watchdog_s)
        self.reconnect_s, self.clock, self.tick_s = float(reconnect_s), clock, float(tick_s)
        self.lock = threading.RLock()
        self.wlock = threading.Lock()
        self.stop_ev = threading.Event()
        self.cmd_sock = self.data_sock = None
        self._cmd_buf = b""
        self._threads: list[threading.Thread] = []
        self.listening = False
        self.st = {"link": "down", "session": "idle", "peer": None, "via": [], "bw": None, "buffer": 0,
                   "ptt": False, "busy": False, "sn": None, "registered": None, "alive_at": None,
                   "soundcard_ok": True, "last_reply": None, "last_cmd": None, "listening": False,
                   "peer_proto": None, "sending": None, "cq_heard": [], "error": None, "kind": kind,
                   "peer_caps": [], "bitrate": {}, "testing": None, "receiving": None, "test_rx": None,
                   "mycall": call, "ptt_mode": ptt_mode,
                   "ptt_at": None, "busy_at": None, "cq_at": None}   # last PTT ON / BUSY ON / our CQ frame: did VARA key, hear
        self._reset_session()

    # ------------------------------------------------------------------ public ---------------------------------
    def state(self) -> dict:
        with self.lock:
            s = dict(self.st)
            s["cq_heard"] = list(s["cq_heard"])
            s["sending"] = dict(s["sending"]) if s["sending"] else None
            return s

    def available(self) -> tuple[bool, str]:
        if self._winlink():
            return False, "Winlink Express is open and uses VARA: close it first"
        if self.st["link"] != "up":
            return False, self.st["error"] or "VARA is not running (start VARA, then wait a few seconds)"
        return True, ""

    def start(self):
        if any(t.is_alive() for t in self._threads):
            return
        self.stop_ev.clear()
        self._threads = [threading.Thread(target=self._run, name="vara-link", daemon=True),
                         threading.Thread(target=self._ticker, name="vara-watchdog", daemon=True)]
        for t in self._threads:
            t.start()

    def stop(self):
        self.stop_ev.set()
        self._ptt(False)
        self._close()
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(2)

    def listen(self, on: bool):
        """Answer calls (VARA answers by itself while listening, so this needs transmit permission) or stop."""
        self._need_link()
        if on:
            self._need_tx()
            self._cmd("CHAT ON")                         # CHAT ON includes LISTEN ON (VARA's own spec)
            self._cmd("LISTEN CQ")                       # ... and report the CQ frames heard (CQFRAME <call>): with plain
            # LISTEN ON VARA answers calls but says nothing of announcements (2026-11-18: two stations announced on
            # one frequency, VARA's own ping worked both ways, neither roster showed the other)
        else:
            self._cmd("LISTEN OFF")
        with self.lock:
            self.listening = self.st["listening"] = bool(on)
        self._emit("status", self.state())

    def connect(self, dest: str, via=()):
        dest = str(dest or "").strip().upper()
        via = [str(v).strip().upper() for v in via or () if str(v).strip()]
        if not CALL_RE.match(dest) or any(not CALL_RE.match(v) for v in via):
            raise VaraRefused("that is not a callsign")
        if via and self.kind != "fm":
            raise VaraRefused("digipeaters are VARA FM only")
        self._need_link()
        if self.st["session"] != "idle":
            raise VaraRefused("already in a session: disconnect first")
        self._need_tx()
        self._cmd("CHAT ON")                             # keyboard timing (and listening, for the answer)
        with self.lock:
            self.st["session"], self.st["peer"], self.st["via"] = "connecting", dest, via
        self._cmd(f"CONNECT {self.mycall} {dest}" + (" via " + " ".join(via) if via else ""))
        self._log({"kind": "call", "dir": "out", "peer": dest, "via": via})
        self._emit("status", self.state())

    def disconnect(self):
        self._need_link()
        self._cmd("DISCONNECT")

    def abort(self, why: str = "operator"):
        """Drop the link at once (VARA's dirty disconnect) and let go of the PTT."""
        try:
            self._cmd("ABORT")
        except Exception:  # noqa: BLE001 - abort must never raise
            pass
        self._ptt(False)
        self._log({"kind": "abort", "why": why})
        self._emit("abort", {"why": why})

    def cq(self, via=()):
        self._need_link()
        self._need_tx()
        if self.kind == "hf":
            self._cmd(f"CQFRAME {self.mycall} {self.bw or 2300}")
        else:
            self._cmd(f"CQFRAME {self.mycall}" + "".join(" " + str(v).upper() for v in via or ()))
        with self.lock:
            self.st["cq_at"] = self.clock()
        self._log({"kind": "cq", "dir": "out"})

    def send_chat(self, text: str) -> int:
        text = str(text or "").replace("\r\n", "\n").strip()
        if not text:
            raise VaraRefused("nothing to send")
        if len(text) > MAX_CHAT:
            raise VaraRefused(f"a message is at most {MAX_CHAT} characters")
        self._need_session()
        with self.lock:
            seq = self._next_seq()
            raw = self.st["peer_proto"] == "raw"
        body = text.encode("utf-8")
        frame = (text.replace("\n", "\r\n") + "\r\n").encode("utf-8") if raw else \
            f"MSG {seq} {len(body)}\n".encode() + body
        self._data(frame)
        self._log({"kind": "chat", "dir": "out", "peer": self.st["peer"], "seq": seq, "text": text})
        self._emit("chat_sent", {"seq": seq, "text": text})
        return seq

    def send_file(self, path=None, name: str | None = None, data: bytes | None = None) -> int:
        if data is None:
            p = Path(path)
            if not p.is_file():
                raise VaraRefused("no such file")
            if p.stat().st_size > self.max_file:
                raise VaraRefused(f"a file is at most {self.max_file // 1024} KB over VARA")
            data, name = p.read_bytes(), name or p.name
        if len(data) > self.max_file:
            raise VaraRefused(f"a file is at most {self.max_file // 1024} KB over VARA")
        name = clean_name(name or "file")
        self._need_session()
        if self.st["peer_proto"] != "HSK1":
            raise VaraRefused("the other station has not answered with this program's handshake: files need it")
        sha = hashlib.sha256(data).hexdigest()
        with self.lock:
            seq = self._next_seq()
            self.out_files[seq] = {"seq": seq, "name": name, "size": len(data), "sha256": sha, "at": self.clock()}
            self.st["sending"] = {"seq": seq, "name": name, "size": len(data), "left": len(data), "at": self.clock(),
                                  "done": 0, "bps": None, "eta_s": None, "elapsed_s": 0}
        # First a short notice, so the other operator sees at once what is coming and how big it is (on the air
        # 2026-11-18 the receiver learnt of a 137 KB file only when VARA handed over its first block, over a minute
        # in). The file itself follows when the modem has sent the notice (or after OFFER_WAIT_S).
        q = urllib.parse.quote(name, safe="")
        with self.lock:
            self.offer = {"seq": seq, "at": self.clock(),
                          "frame": f"FILE {seq} {q} {len(data)} {sha}\n".encode() + data}
        self._data(f"OFFER {seq} {q} {len(data)}\n".encode())
        self._log({"kind": "file", "dir": "out", "peer": self.st["peer"], "seq": seq, "name": name,
                   "size": len(data), "sha256": sha})
        self._emit("file_sending", {"seq": seq, "name": name, "size": len(data)})
        return seq

    def _file_go(self, from_buffer: bool = False):
        """Send the file a notice was sent for: when VARA's buffer is empty again, or after OFFER_WAIT_S."""
        with self.lock:
            o = self.offer
            if not o:
                return
            now = self.clock()
            empty = from_buffer and not self.st["buffer"] and now - o["at"] >= 0.3
            if not empty and now - o["at"] < OFFER_WAIT_S:
                return
            self.offer = None
            if self.st["sending"]:
                self.st["sending"]["at"] = now                     # the speed is counted from the file's first byte
                self.st["sending"].pop("hist", None)
        try:
            self._cmd("COMPRESSION FILES")
            self._data(o["frame"])
        except (OSError, VaraRefused):
            pass

    @staticmethod
    def _progress(x: dict, done: int, now: float):
        """A transfer's numbers for the operator: bytes done, the speed over the last 30 s or so, the time left. Both
        ends work them out the same way, each from the bytes it has itself: the receiver's are a block behind the
        sender's (VARA hands data over a block at a time)."""
        h = x.setdefault("hist", [[x.get("at", now), 0]])
        if done > h[-1][1]:
            h.append([now, done])
        while len(h) > 2 and h[1][0] <= now - 30:
            h.pop(0)
        span = now - h[0][0]
        rate = (done - h[0][1]) / span if span >= 2 and done > h[0][1] else None      # bytes a second
        x.update(done=done, bps=round(rate * 8) if rate else None,
                 eta_s=round((x["size"] - done) / rate) if rate else None, elapsed_s=round(now - x.get("at", now)))

    def link_test(self, seconds: float = TEST_S) -> int:
        """Feed random bytes to the linked station for `seconds`, and time them (see the module's notes)."""
        import os
        seconds = max(TEST_MIN_S, min(TEST_MAX_S, float(seconds or TEST_S)))
        self._need_session()
        if self.st["peer_proto"] != "HSK1" or "+TEST" not in self.st["peer_caps"]:
            raise VaraRefused("the other station's program is older than the link test: it needs an update")
        with self.lock:
            if self.test or self.st["sending"]:
                raise VaraRefused("something is being sent on this link already")
            seq = self._next_seq()
            now = self.clock()
            self.test = {"seq": seq, "start": now, "max_s": seconds, "sent": 0, "feeding": True, "ended": False,
                         "curve": [[0.0, 0]], "write_at": 0.0, "buffer_at": 0.0, "rand": os.urandom, "levels": [], "bps": [],
                         "end_at": None, "sn": []}
            self.st["testing"] = {"seq": seq, "s": 0, "bytes": 0, "max_s": seconds}
        try:
            self._data(f"TESTING {seq} {int(seconds)}\n".encode())   # the other operator sees it, and for how long
        except (OSError, VaraRefused):
            pass
        self._cmd("COMPRESSION FILES")
        self._log({"kind": "test", "dir": "out", "peer": self.st["peer"], "seq": seq, "seconds": seconds})
        self._emit("test_started", {"seq": seq, "seconds": seconds})
        self._test_feed()
        return seq

    def _test_feed(self, from_buffer: bool = False):
        """Top the modem up while the test runs; when its time is up let the modem empty, then ask for the count."""
        with self.lock:
            t = self.test
            if not t or t["ended"]:
                return
            now = self.clock()
            el = now - t["start"]
            buf = int(self.st["buffer"] or 0)
            # Is VARA's BUFFER count newer than our last write? On the air its line came over a second after the
            # write, and the old "0" made every byte look delivered: 106 KB went in at once. A line counts when it
            # comes 0.3 s or more after the write; with no line at all for TEST_STALE_S the last count is taken.
            if from_buffer and now - t["write_at"] >= 0.3:
                t["buffer_at"] = now
            fresh = t["buffer_at"] > t["write_at"] or now - t["write_at"] >= TEST_STALE_S
            if fresh:
                done = max(t["curve"][-1][1], min(t["sent"], t["sent"] - buf))
                if done > t["curve"][-1][1]:
                    t["curve"].append([round(el, 1), done])
                self.st["testing"].update(s=round(el), bytes=done)
            done = t["curve"][-1][1]
            write = None
            if t["feeding"]:
                if el >= t["max_s"] or t["sent"] >= TEST_MAX_BYTES:
                    t["feeding"] = False
                else:
                    back = next((p for p in reversed(t["curve"]) if p[0] <= el - 10), t["curve"][0])
                    rate = (done - back[1]) / max(1.0, el - back[0])            # bytes a second, lately
                    ahead = int(max(TEST_CHUNK[0], min(TEST_CHUNK[1], rate * 15)))
                    left = t["sent"] - done
                    if t["sent"] == 0 or (fresh and left < ahead / 2):
                        n = max(256, min(ahead - left, TEST_MAX_BYTES - t["sent"]))
                        head = f"TEST {t['seq']} {n}\n".encode()
                        write = head + t["rand"](n)
                        t["sent"] += len(write)
                        t["write_at"] = now
            if not t["feeding"] and write is None and fresh and done >= t["sent"]:
                t["ended"], t["end_at"] = True, now
                write = f"TESTEND {t['seq']}\n".encode()
        if write:
            try:
                self._data(write)
            except (OSError, VaraRefused):
                pass

    def _test_result(self, t: dict, partial: bool = False, rx_ms: int | None = None) -> dict:
        """What the test measured: the bytes the other modem took over time, and the speeds VARA named."""
        curve = t["curve"]
        total, secs = curve[-1][1], max(0.1, curve[-1][0])
        if len(curve) > 40:                                         # thin it: the shape, not every BUFFER line
            step = len(curve) / 40
            curve = [curve[int(i * step)] for i in range(40)] + [curve[-1]]
        back = next((p for p in reversed(curve) if p[0] <= secs * 2 / 3), curve[0])
        late = (total - back[1]) / max(0.1, secs - back[0])         # bytes a second over the last third: the speed reached
        return {"bytes": total, "s": round(secs, 1), "bps": round(total * 8 / secs), "late_bps": round(late * 8),
                "curve": curve, "level": max(t["levels"], default=None), "modem_bps": max(t["bps"], default=None),
                "sn": round(sum(t["sn"]) / len(t["sn"]), 1) if t["sn"] else None, "partial": partial,
                "rx_ms": rx_ms, "bw": self.st.get("bw"), "kind": self.kind}

    # ------------------------------------------------------------------ guards ---------------------------------
    def _need_link(self):
        ok, why = self.available()
        if not ok:
            raise VaraRefused(why)

    def _need_tx(self):
        r = self.tx_allowed()
        ok, why = (r, "") if isinstance(r, bool) else (bool(r[0]), r[1] if len(r) > 1 else "")
        if not ok:
            raise VaraRefused(why or "transmitting is not allowed now")

    def _need_session(self):
        self._need_link()
        if self.st["session"] != "connected":
            raise VaraRefused("not connected to a station")
        self._need_tx()

    def _winlink(self) -> bool:
        try:
            return bool(self.winlink_open())
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------ the sockets ----------------------------
    def _cmd(self, line: str):
        if "ENCRYPT" in line.upper():
            raise VaraRefused("encryption is not allowed on amateur radio (Part 97.113)")
        s = self.cmd_sock
        if s is None:
            raise VaraRefused("VARA is not running")
        with self.wlock:
            s.sendall((line + "\r").encode("ascii", "replace"))
        self._raw(">", line)
        with self.lock:
            self.st["last_cmd"] = line

    def _data(self, b: bytes):
        """Every byte to the other station: transmit permission first; refused mid-session = the link is aborted."""
        r = self.tx_allowed()
        ok = r if isinstance(r, bool) else bool(r[0])
        if not ok:
            self.abort("transmitting is no longer allowed")
            raise VaraRefused((r[1] if not isinstance(r, bool) and len(r) > 1 else "") or "transmitting is not allowed")
        s = self.data_sock
        if s is None:
            raise VaraRefused("VARA is not running")
        with self.wlock:
            s.sendall(b)

    def _open(self) -> bool:
        try:
            c = socket.create_connection((self.host, self.ports[0]), timeout=3)
            d = socket.create_connection((self.host, self.ports[1]), timeout=3)
        except OSError as e:
            with self.lock:
                self.st["error"] = f"VARA is not running ({type(e).__name__})"
            return False
        c.settimeout(None)
        d.settimeout(None)
        self.cmd_sock, self.data_sock = c, d
        self._cmd_buf = b""
        with self.lock:
            self.st.update(link="up", error=None)
        self._cmd(f"MYCALL {self.mycall}")
        self._cmd("LISTEN ON" if self.listening else "LISTEN OFF")
        self._cmd("COMPRESSION TEXT")
        if self.kind == "hf":
            self._cmd("P2P SESSION")
            self._cmd("CWID ON")                                   # newer VARA; an older one answers WRONG
            if self.bw:
                self._cmd(f"BW{self.bw}")
        self._emit("status", self.state())
        return True

    def _close(self):
        for s in (self.cmd_sock, self.data_sock):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        self.cmd_sock = self.data_sock = None
        was = self.st["link"]
        with self.lock:
            self.st["link"] = "down"
        if self.st["session"] != "idle":
            self._ended("VARA closed")
        if was == "up":
            self._emit("status", self.state())

    def _run(self):
        while not self.stop_ev.is_set():
            if self._winlink():
                with self.lock:
                    self.st["error"] = "Winlink Express is open and uses VARA"
                self.stop_ev.wait(self.reconnect_s)
                continue
            if not self._open():
                self.stop_ev.wait(self.reconnect_s)
                continue
            sel = selectors.DefaultSelector()
            sel.register(self.cmd_sock, selectors.EVENT_READ, "cmd")
            sel.register(self.data_sock, selectors.EVENT_READ, "data")
            last_wl = time.monotonic()
            try:
                while not self.stop_ev.is_set():
                    for key, _ in sel.select(timeout=0.2):
                        try:
                            chunk = key.fileobj.recv(65536)
                        except OSError:
                            chunk = b""
                        if not chunk:
                            raise ConnectionError("VARA closed the connection")
                        (self._on_cmd_bytes if key.data == "cmd" else self._on_data)(chunk)
                    if time.monotonic() - last_wl > self.reconnect_s:      # Express opened while we were idle: let go
                        last_wl = time.monotonic()
                        if self.st["session"] == "idle" and self._winlink():
                            raise ConnectionError("Winlink Express opened")
            except (ConnectionError, OSError) as e:
                with self.lock:
                    self.st["error"] = str(e)
            finally:
                sel.close()
                self._ptt(False)
                self._close()
            self.stop_ev.wait(self.reconnect_s)

    # ------------------------------------------------------------------ VARA -> us -----------------------------
    def _on_cmd_bytes(self, chunk: bytes):
        self._cmd_buf += chunk
        while True:
            m = re.search(rb"[\r\n]", self._cmd_buf)
            if not m:
                if len(self._cmd_buf) > MAX_HEADER:
                    self._cmd_buf = b""
                return
            line, self._cmd_buf = self._cmd_buf[:m.start()], self._cmd_buf[m.end():]
            line = line.decode("ascii", "replace").strip()
            if line:
                self._on_status(line)

    def _raw(self, way: str, line: str):
        """VARA's command port, word for word (raw.log in the modem's folder, last ~200 KB): what VARA really says
        when something on the air does not show up here. IAMALIVE is left out."""
        if line.upper().startswith("IAMALIVE"):
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            p = self.dir / "raw.log"
            if p.exists() and p.stat().st_size > 200_000:
                p.replace(self.dir / "raw.1.log")
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.fromtimestamp(self.clock()):%Y-%m-%d %H:%M:%S} {way} {line}\n")
        except OSError:
            pass

    def _on_status(self, line: str):
        self._raw("<", line)
        w = line.split()
        k = w[0].upper()
        if k == "CONNECTED" and len(w) >= 3:
            src, dst = w[1].upper(), w[2].upper()
            rest = w[3:]
            via = []
            if rest and rest[0].lower() == "via":
                via = [x.upper() for x in rest[1:] if not x.isdigit()]
            bw = next((int(x) for x in reversed(rest) if x.isdigit()), None)
            out = _same_call(src, self.mycall)        # W9XYZ-7 calling W9XYZ-8: different stations, same base call
            peer = dst if out else src
            with self.lock:                          # bytes may already be here (two sockets): keep the buffer;
                self.st.update(session="connected", peer=peer, via=via, bw=bw,   # the last session's end cleared it
                               peer_proto=self.st["peer_proto"])
                self.session_at = self.clock()
            self._log({"kind": "connected", "peer": peer, "via": via, "bw": bw,
                       "dir": "out" if out else "in"})
            self._emit("connected", {"peer": peer, "via": via, "bw": bw})
            try:
                self._data(f"HSK1 {self.mycall} {CAPS}\n".encode())
            except VaraRefused:
                pass
        elif k == "DISCONNECTED":
            self._ended("disconnected")
        elif k == "BUFFER" and len(w) > 1 and w[1].isdigit():
            n = int(w[1])
            with self.lock:
                self.st["buffer"] = n
                if self.st["sending"]:
                    x = self.st["sending"]
                    x["left"] = min(x["size"], n) if not self.offer else x["size"]
                    if not self.offer and self.clock() - x["at"] >= 0.3:   # a BUFFER line from before the file went lies
                        self._progress(x, x["size"] - x["left"], self.clock())
            self._emit("buffer", {"bytes": n, "sending": self.state()["sending"]})
            self._test_feed(from_buffer=True)
            self._file_go(from_buffer=True)
        elif k == "BITRATE" and len(w) >= 3:                       # "BITRATE (4)  1415 bps TX": VARA's speed level now
            try:
                level, bps = int(w[1].strip("()")), int(w[2])
            except ValueError:
                return
            way = "rx" if w[-1].upper() == "RX" else "tx"
            with self.lock:
                self.st["bitrate"] = dict(self.st["bitrate"], **{way: bps, way + "_level": level, "at": self.clock()})
                if self.test and way == "tx":
                    self.test["levels"].append(level)
                    self.test["bps"].append(bps)
            self._emit("bitrate", {"way": way, "bps": bps, "level": level})
        elif k == "PTT" and len(w) > 1:
            on = w[1].upper() == "ON"
            if on and self.ptt_mode == "station":
                r = self.tx_allowed()
                if not (r if isinstance(r, bool) else bool(r[0])):
                    self.abort("VARA wanted to transmit but transmitting is not allowed")
                    return
            with self.lock:
                self.st["ptt"] = on
                self.ptt_on_at = self.clock() if on else None
                if on:
                    self.st["ptt_at"] = self.clock()
            self._ptt(on)
            self._emit("ptt", {"on": on})
        elif k == "BUSY" and len(w) > 1:
            with self.lock:
                self.st["busy"] = w[1].upper() == "ON"
                if self.st["busy"]:
                    self.st["busy_at"] = self.clock()
            self._emit("busy", {"on": self.st["busy"]})
        elif k == "SN" and len(w) > 1:
            try:
                v = float(w[1])
            except ValueError:
                return
            with self.lock:
                self.st["sn"] = v
                if self.test:
                    self.test["sn"].append(v)
            self._emit("sn", {"sn": v})
        elif k == "IAMALIVE":
            with self.lock:
                self.st["alive_at"] = self.clock()
        elif k == "MISSING" and len(w) > 1 and w[1].upper() == "SOUNDCARD":
            with self.lock:
                self.st["soundcard_ok"] = False
                self.st["error"] = "VARA lost the sound card (often RF or high SWR): restart the PC"
            self._ptt(False)
            self._emit("soundcard", {"ok": False})
        elif k == "CQFRAME" and len(w) > 1:
            bw = next((int(x) for x in w[2:] if x.isdigit()), None)
            heard = {"call": w[1].upper(), "bw": bw, "via": [x.upper() for x in w[2:] if not x.isdigit()],
                     "at": self.clock()}
            with self.lock:
                self.st["cq_heard"] = ([heard] + [h for h in self.st["cq_heard"] if h["call"] != heard["call"]])[:20]
            self._log({"kind": "cq", "dir": "in", "peer": heard["call"]})
            self._emit("cq_heard", heard)
        elif k in ("PENDING", "CANCELPENDING"):
            with self.lock:
                if self.st["session"] == "idle" and k == "PENDING":
                    self.st["session"] = "pending"
                elif self.st["session"] == "pending" and k == "CANCELPENDING":
                    self.st["session"] = "idle"
            self._emit(k.lower(), {})
        elif k == "REGISTERED" and len(w) > 1:
            with self.lock:
                self.st["registered"] = w[1].upper()
        elif k == "LINK" and len(w) > 1:
            with self.lock:
                self.st["registered"] = self.st["registered"] if w[1].upper() == "REGISTERED" else None
        elif k in ("OK", "WRONG"):
            with self.lock:
                self.st["last_reply"] = k
            if k == "WRONG":
                self._emit("wrong", {"command": self.st["last_cmd"]})
        else:
            self._emit("vara", {"line": line})

    def _ended(self, why: str):
        with self.lock:
            peer = self.st["peer"]
            out = list(self.out_files.values())
            partial = self.pending
            test = self.test
            res = self._test_result(test, partial=True) if test and test["curve"][-1][1] >= 2000 else None
            self._reset_session()
            self.st.update(session="idle", peer=None, via=[], bw=None, peer_proto=None, sending=None, buffer=0,
                           peer_caps=[], bitrate={}, testing=None, receiving=None, test_rx=None)
        if test:
            self._emit("test_done" if res else "test_failed",
                       {"seq": test["seq"], "result": res, "why": "the link closed before the test finished"})
        for f in out:
            self._emit("file_failed", {"seq": f["seq"], "name": f["name"], "why": "the link closed before the receipt"})
        if partial and partial.get("kind") == "file":
            self._emit("file_rejected", {"seq": partial["seq"], "name": partial["name"], "why": "the link closed"})
        self._log({"kind": "disconnected", "peer": peer, "why": why})
        self._emit("disconnected", {"peer": peer, "why": why})
        if not self.listening and self.cmd_sock is not None:
            try:
                self._cmd("LISTEN OFF")                         # CONNECT turned CHAT ON (and listening) on
            except (OSError, VaraRefused):
                pass

    # ------------------------------------------------------------------ the other station -> us ----------------
    def _reset_session(self):
        self.buf = bytearray()
        self.mode = "start"                     # start | hsk | raw
        self.pending = None                     # a MSG / FILE body being read
        self.out_files: dict[int, dict] = {}
        self.seq = 0
        self.session_at = None
        self.ptt_on_at = None
        self.offer = None                       # a file whose notice is on its way: the file follows
        self.test = None                        # a link test we are sending
        self.rx_test = None                     # ... or receiving

    def _next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def _on_data(self, chunk: bytes):
        with self.lock:
            self.buf += chunk
        while self._step():
            pass

    def _step(self) -> bool:
        """Handle what the buffer holds. True when something was consumed (call again)."""
        b = self.buf
        if self.pending:
            p = self.pending
            take = min(p["need"], len(b))
            if not take:
                return False
            if not p.get("discard"):
                p["body"] += b[:take]
            elif p["kind"] == "test":
                p["size_in"] = p.get("size_in", 0) + take
            p["need"] -= take
            del b[:take]
            rx = self.st["receiving"] if p["kind"] == "file" else None
            if rx:
                now = self.clock()
                with self.lock:
                    self._progress(rx, p["size"] - p["need"], now)
                if p["need"] and now - rx["said_at"] >= 1:        # tell the dashboard about once a second
                    rx["said_at"] = now
                    self._emit("file_progress", {"seq": p["seq"], "done": rx["done"], "size": p["size"]})
            if p["need"] == 0:
                self.pending = None
                self._finish(p)
            return True
        if not b:
            return False
        if self.mode == "start":
            head = bytes(b[:5])
            if head == b"HSK1 "[:len(head)] and len(head) < 5:
                return False
            self.mode = "hsk" if head == b"HSK1 " else "raw"
            if self.mode == "raw":                  # "HSK1" is said once its whole line is here (it names what the
                with self.lock:                     # other program can do): over a slow link the line comes in pieces
                    self.st["peer_proto"] = "raw"
            return True
        if self.mode == "raw":
            m = re.search(rb"[\r\n]", b)
            if not m:
                if len(b) > MAX_CHAT:
                    text, self.buf = bytes(b).decode("utf-8", "replace"), bytearray()
                    self._chat_in(None, text)
                    return True
                return False
            line = bytes(b[:m.start()])
            del b[:m.end()]
            text = line.decode("utf-8", "replace").strip()
            if text:
                self._chat_in(None, text)
            return True
        nl = b.find(b"\n")
        if nl < 0:
            if len(b) > MAX_HEADER:
                self._emit("protocol", {"why": "a header line too long: dropped"})
                del b[:]
            return False
        line = bytes(b[:nl]).decode("utf-8", "replace").strip()
        del b[:nl + 1]
        self._header(line)
        return True

    def _header(self, line: str):
        w = line.split()
        if not w:
            return
        k = w[0].upper()
        try:
            if k == "HSK1":
                with self.lock:
                    self.st["peer_caps"] = [x.upper() for x in w[2:] if x.startswith("+")][:8]
                    self.st["peer_proto"] = "HSK1"
                self._emit("handshake", {"peer": w[1].upper() if len(w) > 1 else None, "caps": self.st["peer_caps"]})
            elif k == "OFFER" and len(w) == 4:                     # a file is coming: say so now, with its size
                name, size = clean_name(urllib.parse.unquote(w[2])), int(w[3])
                with self.lock:
                    self.st["receiving"] = {"seq": int(w[1]), "name": name, "size": max(0, size), "at": self.clock(),
                                            "done": 0, "bps": None, "eta_s": None, "elapsed_s": 0,
                                            "said_at": self.clock()}
                self._emit("file_receiving", {"seq": int(w[1]), "name": name, "size": size})
            elif k == "TESTING" and len(w) == 3:                   # a link test is coming, for this many seconds
                with self.lock:
                    self.st["test_rx"] = {"bytes": 0, "s": 0, "max_s": int(float(w[2]))}
                self._emit("test_receiving", {"seq": int(w[1])})
            elif k == "TEST" and len(w) == 3:
                n = int(w[2])
                if not 0 < n <= 4 * TEST_CHUNK[1]:
                    raise ValueError("bad TEST length")
                if not self.rx_test or self.rx_test["seq"] != int(w[1]):
                    self.rx_test = {"seq": int(w[1]), "bytes": 0, "at": self.clock()}
                    self._emit("test_receiving", {"seq": int(w[1])})
                self.rx_test["bytes"] += len(line) + 1
                with self.lock:                                  # shown on this station: the frequency is in use
                    self.st["test_rx"] = dict(self.st["test_rx"] or {}, bytes=self.rx_test["bytes"],
                                              s=round(self.clock() - self.rx_test["at"]))
                self.pending = {"kind": "test", "seq": int(w[1]), "need": n, "body": bytearray(), "discard": "test"}
            elif k == "TESTEND" and len(w) == 2:
                r, self.rx_test = self.rx_test, None
                with self.lock:
                    self.st["test_rx"] = None
                if r and r["seq"] == int(w[1]):
                    ms = int((self.clock() - r["at"]) * 1000)
                    try:
                        self._data(f"TESTED {r['seq']} {r['bytes']} {ms}\n".encode())
                    except VaraRefused:
                        pass
                    info = {"seq": r["seq"], "bytes": r["bytes"], "s": round(ms / 1000, 1), "peer": self.st["peer"],
                            "bps": round(r["bytes"] * 8000 / max(1, ms))}
                    self._log({"kind": "test", "dir": "in", **info})
                    self._emit("test_received", info)
            elif k == "TESTED" and len(w) == 4:
                with self.lock:
                    t, self.test = self.test, None
                    self.st["testing"] = None
                if t and t["seq"] == int(w[1]):
                    try:
                        self._cmd("COMPRESSION TEXT")
                    except (OSError, VaraRefused):
                        pass
                    res = self._test_result(t, rx_ms=int(w[3]))
                    self._log({"kind": "test", "dir": "out", "peer": self.st["peer"], "seq": t["seq"],
                               **{k2: v for k2, v in res.items() if k2 != "curve"}})
                    self._emit("test_done", {"seq": t["seq"], "result": res})
            elif k == "MSG" and len(w) == 3:
                n = int(w[2])
                if not 0 <= n <= MAX_CHAT * 4:
                    raise ValueError("chat too long")
                self.pending = {"kind": "msg", "seq": int(w[1]), "need": n, "body": bytearray()}
                if n == 0:
                    p, self.pending = self.pending, None
                    self._finish(p)
            elif k == "FILE" and len(w) == 5:
                seq, size, sha = int(w[1]), int(w[3]), w[4].lower()
                name = clean_name(urllib.parse.unquote(w[2]))
                if size < 0 or not re.fullmatch(r"[0-9a-f]{64}", sha):
                    raise ValueError("bad FILE header")
                p = {"kind": "file", "seq": seq, "name": name, "size": size, "sha256": sha, "need": size,
                     "body": bytearray()}
                if size > self.max_file:
                    p["discard"] = f"too large ({size} bytes; this station takes up to {self.max_file})"
                self.pending = p
                with self.lock:
                    old = self.st["receiving"]
                    if not (old and old.get("seq") == seq):         # no notice came first (an older program)
                        self.st["receiving"] = {"seq": seq, "name": name, "size": size, "at": self.clock(),
                                                "done": 0, "bps": None, "eta_s": None, "elapsed_s": 0,
                                                "said_at": self.clock()}
                if not (old and old.get("seq") == seq):
                    self._emit("file_receiving", {"seq": seq, "name": name, "size": size})
                if size == 0:
                    self.pending = None
                    self._finish(p)
            elif k in ("ACK", "NAK") and len(w) >= 2:
                self._receipt(k == "ACK", int(w[1]), " ".join(w[2:]))
            else:
                self._emit("protocol", {"why": f"unknown line: {line[:60]}"})
        except ValueError as e:
            self._emit("protocol", {"why": f"{e}: {line[:60]}"})

    def _finish(self, p: dict):
        if p["kind"] == "test":
            if self.rx_test:
                self.rx_test["bytes"] += p.get("size_in", 0)
            return
        if p["kind"] == "msg":
            self._chat_in(p["seq"], bytes(p["body"]).decode("utf-8", "replace"))
            return
        with self.lock:
            self.st["receiving"] = None
        if p.get("discard"):
            return self._reject(p, p["discard"])
        body = bytes(p["body"])
        if hashlib.sha256(body).hexdigest() != p["sha256"]:
            return self._reject(p, "checksum mismatch")
        inbox = self.dir / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromtimestamp(self.clock()).strftime("%Y%m%d-%H%M%S")
        peer = re.sub(r"[^A-Z0-9-]", "", str(self.st["peer"] or "unknown"))
        dest = inbox / f"{stamp}-{peer}-{p['name']}"
        i = 1
        while dest.exists():
            dest = inbox / f"{stamp}-{peer}-{i}-{p['name']}"
            i += 1
        dest.write_bytes(body)
        try:
            self._data(f"ACK {p['seq']}\n".encode())
        except VaraRefused:
            pass
        info = {"seq": p["seq"], "name": p["name"], "size": len(body), "sha256": p["sha256"], "path": str(dest),
                "peer": self.st["peer"]}
        self._log({"kind": "file", "dir": "in", **info})
        self._emit("file_received", info)

    def _reject(self, p: dict, why: str):
        try:
            self._data(f"NAK {p['seq']} {why}\n".encode())
        except VaraRefused:
            pass
        self._log({"kind": "file", "dir": "in", "seq": p["seq"], "name": p["name"], "rejected": why,
                   "peer": self.st["peer"]})
        self._emit("file_rejected", {"seq": p["seq"], "name": p["name"], "why": why})

    def _chat_in(self, seq, text: str):
        self._log({"kind": "chat", "dir": "in", "peer": self.st["peer"], "seq": seq, "text": text})
        self._emit("chat", {"seq": seq, "text": text, "peer": self.st["peer"], "raw": seq is None})

    def _receipt(self, ok: bool, seq: int, why: str):
        with self.lock:
            f = self.out_files.pop(seq, None)
            if self.st["sending"] and self.st["sending"]["seq"] == seq:
                self.st["sending"] = None
            more = bool(self.out_files)
        if f is None:
            return
        if not more:
            try:
                self._cmd("COMPRESSION TEXT")
            except (OSError, VaraRefused):
                pass
        self._log({"kind": "receipt", "seq": seq, "ok": ok, "why": why or None, "peer": self.st["peer"]})
        self._emit("file_sent" if ok else "file_failed", {"seq": seq, "name": f["name"], "why": why or None})

    # ------------------------------------------------------------------ PTT, watchdog, log -----------------------
    def _ptt(self, on: bool):
        if self.ptt_mode != "station" or self.ptt is None:
            return
        try:
            self.ptt(bool(on))
        except Exception as e:  # noqa: BLE001 - a PTT failure ends the link, never the station
            with self.lock:
                self.st["error"] = f"PTT: {type(e).__name__}: {e}"
            if on:
                try:
                    self._cmd("ABORT")
                except (OSError, VaraRefused):
                    pass

    def watchdog(self, now: float | None = None) -> str | None:
        """Abort when the PTT has been on, or a file has waited for its receipt, longer than watchdog_s. Returns why."""
        now = self.clock() if now is None else now
        why = None
        with self.lock:
            if self.ptt_on_at is not None and now - self.ptt_on_at > self.watchdog_s:
                why = f"the transmitter was on for over {self.watchdog_s:.0f} s"
            elif any(now - f["at"] > self.watchdog_s for f in self.out_files.values()):
                why = f"a file waited over {self.watchdog_s:.0f} s for its receipt"
            elif self.test and now - self.test["start"] > self.test["max_s"] + self.watchdog_s:
                why = "a link test did not finish"
            if why:
                self.ptt_on_at = None
                self.st["ptt"] = False
        if why:
            self.abort(why)
            self._emit("watchdog", {"why": why})
        return why

    def _ticker(self):
        while not self.stop_ev.wait(self.tick_s):
            try:
                self.watchdog()
                self._test_feed()
                self._file_go()
            except Exception:  # noqa: BLE001
                pass

    def _log(self, entry: dict):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            t = datetime.fromtimestamp(self.clock())
            with open(self.dir / f"{t:%Y-%m}.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": t.isoformat(timespec="seconds"), **entry}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _emit(self, name: str, data: dict):
        try:
            self.on_event(name, data)
        except Exception:  # noqa: BLE001 - a listener never stops the link
            pass
