"""The VARA channel: who is on the frequency, and chat / files with any of them (owner 2026-11-16: "when a station
connects it should announce itself ... keep alive ... greyed out if the keep alive isn't received ... select a
connected session and do the chat or file send with that station ... connect to multiple stations at once on the same
VARA session ... preset buttons with short messages").

What VARA can and cannot do decides the design:

* VARA (HF and FM) is a point-to-point ARQ modem: ONE link at a time per copy of VARA. Being linked to several
  stations at once is impossible on one modem (VarAC has the same limit). So the channel works like a group chat on
  top of short links: a message to K7ABC is queued, the station links to K7ABC when the frequency is clear, sends what
  is waiting (both ways: the other side sends what it has for us on the same link), and lets the link go after a
  short quiet spell. Messages to several stations go out one link after another. "Keep the link open" holds one link
  for a back-and-forth.
* The only frame VARA sends without a link is the CQ frame (CQFRAME: the callsign, nothing else). Joining the channel
  sends one ("announce"), and one more every `every_min` minutes while you stay (the keep-alive). Every CQ frame heard,
  and every link with a station, marks it "here"; a station not heard for one interval and a grace is "quiet" (grey),
  after three intervals "gone" (moved under Earlier). Leaving cannot be announced (no frame says it): it shows as quiet.
* Part 97: nothing here transmits without the operator at the station and the radio's transmit switch on
  (Modem.tx_allowed, checked again by Vara before every frame): announcements, keep-alives, listening and queued
  messages pause the moment you leave and resume when you are back. Queued messages go only because you pressed
  Send. Keep-alives are at least 5 minutes apart.

State (roster, threads, settings) is kept in the modem's folder as channel.json.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

EVERY = {"fm": 10, "hf": 15}       # minutes between keep-alives
MIN_EVERY, MAX_EVERY = 5, 60
GRACE_S = 180                      # a keep-alive may be late by this much before the station greys out
LINGER_S = {"fm": 20, "hf": 40}    # a link we opened closes after this long with nothing to send
MIN_QUIET_S = 5                    # with others waiting, a link is let go after this long with nothing moving
CONNECT_TIMEOUT_S = 150
TRIES = 3
BACKOFF_S = 30
KEEP = 300                         # messages kept per station
PRESETS = ["{them} de {me}: hello, how copy?", "Copy you fine. S/N {sn} dB here.", "Roger, QSL.",
           "Stand by, back in a few minutes.", "Please say again.", "Name {name}, grid {grid}.",
           "Any traffic for me?", "Thanks for the contact. 73 de {me}."]


MAX_DIGIS = 2                      # VARA FM relays a link, or an announcement, through at most two digipeaters


def clean_via(v, kind: str = "fm", me: str = "", to: str = "") -> list[str]:
    """A digipeater path as the operator typed it ("K7ABC-4, N0CALL-8"): callsigns, at most two, VARA FM only."""
    from .vara import CALL_RE
    words = [w for w in re.split(r"[\s,>]+", " ".join(v) if isinstance(v, (list, tuple)) else str(v or "")) if w]
    words = [w.upper() for w in words if w.lower() != "via"]
    if not words:
        return []
    if kind != "fm":
        raise ValueError("digipeaters are VARA FM only")
    if len(words) > MAX_DIGIS:
        raise ValueError(f"VARA FM goes through at most {MAX_DIGIS} digipeaters")
    for w in words:
        if not CALL_RE.match(w):
            raise ValueError(f"{w} is not a callsign")
        if w in (me.upper(), to.upper()):
            raise ValueError(f"{w} is one end of the link, not a digipeater on the way")
    if len(set(words)) != len(words):
        raise ValueError("the same digipeater twice")
    return words


EST_SIZES = (1_000, 10_000, 50_000, 100_000, 500_000, 1_000_000)
SETUP_S = 8.0                      # calling a station and the handshake, before the first byte, when never measured


def estimate_s(speed: dict | None, size: int) -> float | None:
    """Seconds to send `size` bytes to a station, from its last link test (owner 2026-11-18: "the user needs to know
    how long it will take to send various sizes of files"). VARA starts slow and steps up, so a small file gets the
    slow start: up to the size the test reached, the time is read off the test's own curve; beyond it, the rest goes
    at the speed the test had reached. Compression is not counted: text usually goes faster than this."""
    if not speed or not speed.get("curve") or speed.get("bytes", 0) <= 0:
        return None
    setup = float(speed.get("setup_s") or SETUP_S)
    curve = speed["curve"]
    if size <= curve[-1][1]:
        for (t0, b0), (t1, b1) in zip(curve, curve[1:]):
            if size <= b1:
                return setup + t0 + (t1 - t0) * (size - b0) / max(1, b1 - b0)
    late = max(speed.get("late_bps") or 0, speed.get("bps") or 0, 1) / 8
    return setup + curve[-1][0] + (size - curve[-1][1]) / late


EINSTEIN_IDLE_S = 300          # Einstein lets a link go after this long with nothing said (the asker opened it)
AI_WAIT_S = 150                # the asker keeps its link open this long for an AI station's answer


ASKS_MAX = 12


def clean_asks(raw) -> list[dict]:
    """The operator's own quick requests for AI stations (owner 2026-11-25: "let the user add requests to the Quick
    requests"): [{"label": the button's words (may be empty: the text is shown), "text": what is sent, "now": sent
    by one tap (False = put in the message box to finish, e.g. "MSG ")}], each text once, at most ASKS_MAX."""
    out, seen = [], set()
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict):
            continue
        now = a.get("now", True) is not False
        text = " ".join(str(a.get("text") or "").split())[:300]
        if not text:
            continue
        if not now:
            text += " "                                   # a request to finish typing keeps its space ("MSG ")
        k = text.strip().lower()
        if k in seen:
            continue
        seen.add(k)
        out.append({"label": " ".join(str(a.get("label") or "").split())[:40], "text": text, "now": now})
    return out[:ASKS_MAX]


class Channel:
    def __init__(self, modem, clock=time.time):
        self.m, self.clock = modem, clock
        self.lock = threading.RLock()
        self.opened = None             # the station we linked to (we close that link when it goes quiet)
        self.connect_at = None
        self.activity_at = 0.0
        self.seq_map: dict[tuple, str] = {}      # (peer, "chat"|"file", seq) -> message id
        self.backoff: dict[str, float] = {}
        self.linked = False
        self.last_peer = None
        self.dirty = False
        self.local = None              # our call on the link now (the operator's, or Einstein's: station/einstein.py)

    # ----- storage -----
    def _path(self) -> Path:
        return self.m.dir() / "channel.json"

    def load(self) -> dict:
        try:
            d = json.loads(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        d.setdefault("on", False)
        d.setdefault("every_min", EVERY[self.m.cfg().get("kind", "fm")])
        d.setdefault("presets", list(PRESETS))
        d.setdefault("roster", {})
        d.setdefault("threads", {})
        d.setdefault("last_announce", 0)
        d.setdefault("pinned", None)
        d.setdefault("e_last_announce", 0)
        return d

    def save(self, d: dict):
        p = self._path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        tmp.replace(p)
        self.dirty = True

    def _files(self) -> Path:
        return self.m.dir() / "outbox"

    # ----- presence -----
    def presence(self, r: dict, every_min: int, now: float) -> str:
        age = now - (r.get("heard_at") or 0)
        if age <= every_min * 60 + GRACE_S:
            return "here"
        if age <= 3 * every_min * 60:
            return "quiet"
        return "gone"

    def _heard(self, d: dict, call: str, how: str, **kw):
        if not call:
            return
        call = call.upper()
        r = d["roster"].setdefault(call, {"call": call, "first_at": self.clock(), "unread": 0})
        r.update(heard_at=self.clock(), how=how, **kw)

    # ----- the operator's actions -----
    def _vara(self):
        return self.m._v()                   # on, not Winlink Express's turn, VARA running (else ValueError: why)

    def join(self) -> dict:
        v = self._vara()
        v.listen(True)                       # refused (with why) when transmitting is not allowed now
        with self.lock:
            d = self.load()
            d["on"] = True
            self.save(d)
        self.announce()
        return self.view()

    def leave(self) -> dict:
        with self.lock:
            d = self.load()
            d["on"], d["pinned"] = False, None
            self.save(d)
        v = self.m.vara
        if v:
            try:
                if v.state().get("listening"):
                    v.listen(False)
            except Exception:  # noqa: BLE001
                pass
        return self.view()

    def announce(self):
        v = self._vara()
        s = v.state()
        if s.get("session") != "idle":
            raise ValueError("in a link now: the keep-alive goes when it ends")
        v.cq(self.load().get("announce_via") or ())
        with self.lock:
            d = self.load()
            d["last_announce"] = self.clock()
            self.save(d)

    def settings(self, body: dict) -> dict:
        with self.lock:
            d = self.load()
            if "every_min" in body:
                try:
                    n = int(body["every_min"])
                except (TypeError, ValueError):
                    raise ValueError("minutes between keep-alives: a number") from None
                if not MIN_EVERY <= n <= MAX_EVERY:
                    raise ValueError(f"keep-alives are {MIN_EVERY} to {MAX_EVERY} minutes apart")
                d["every_min"] = n
            if "presets" in body:
                ps = [" ".join(str(p).split())[:120] for p in body["presets"] or [] if str(p).strip()][:12]
                d["presets"] = ps or list(PRESETS)
            if "asks" in body:                            # the operator's own quick requests for AI stations
                d["asks"] = clean_asks(body["asks"])
            if "forget" in body:
                c = str(body["forget"]).upper()
                d["roster"].pop(c, None)
                d["threads"].pop(c, None)
            if "read" in body:
                r = d["roster"].get(str(body["read"]).upper())
                if r:
                    r["unread"] = 0
            kind = self.m.cfg().get("kind", "fm")
            if "via_for" in body:                                # the digipeaters on the way to one station
                c = str(body["via_for"] or "").upper()
                from .vara import CALL_RE
                if not CALL_RE.match(c):
                    raise ValueError("choose a station first")
                r = d["roster"].setdefault(c, {"call": c, "first_at": self.clock(), "unread": 0, "heard_at": None})
                via = clean_via(body.get("via"), kind, self.m.call(), c)
                if via != (r.get("via") or []):
                    r["speed"] = None                            # measured over the old path
                r.update(via=via, via_by="you" if via or body.get("direct") else None)
            if "announce_via" in body:                           # ... and for your own announcements
                d["announce_via"] = clean_via(body["announce_via"], kind, self.m.call())
            if "pin" in body:
                d["pinned"] = str(body["pin"]).upper() if body["pin"] else None
            self.save(d)
        return self.view()

    def send(self, to, text: str | None = None, name: str | None = None, data: bytes | None = None) -> dict:
        """Queue a message (or a file) for one or several stations: each goes out over its own link, in turn."""
        from .vara import CALL_RE, MAX_CHAT, clean_name
        calls = []
        for c in ([to] if isinstance(to, str) else list(to or [])):
            c = str(c or "").strip().upper()
            if not CALL_RE.match(c):
                raise ValueError(f"{c or 'that'} is not a callsign")
            if c not in calls:
                calls.append(c)
        if not calls:
            raise ValueError("choose who to send it to")
        if data is None:
            text = str(text or "").replace("\r\n", "\n").strip()
            if not text:
                raise ValueError("nothing to send")
            if len(text) > MAX_CHAT:
                raise ValueError(f"a message is at most {MAX_CHAT} characters")
        else:
            if len(data) > self._vara().max_file:
                raise ValueError(f"a file is at most {self._vara().max_file // 1024} KB over VARA")
            name = clean_name(name or "file")
            self._files().mkdir(parents=True, exist_ok=True)
        with self.lock:
            d = self.load()
            for c in calls:
                mid = uuid.uuid4().hex[:12]
                item = {"id": mid, "dir": "out", "at": self.clock(), "status": "queued", "tries": 0}
                if data is None:
                    item.update(kind="chat", text=text)
                else:
                    (self._files() / mid).write_bytes(data)
                    item.update(kind="file", name=name, size=len(data))
                self._thread(d, c).append(item)
                d["roster"].setdefault(c, {"call": c, "first_at": self.clock(), "unread": 0, "heard_at": None})
            self.save(d)
        self.tick()
        return self.view()

    def test(self, to, seconds=None) -> dict:
        """Queue a link speed test to one station: it goes out like a message, over its own link."""
        from .vara import CALL_RE, TEST_MAX_S, TEST_MIN_S, TEST_S
        c = str(to or "").strip().upper()
        if not CALL_RE.match(c):
            raise ValueError("choose one station to test the link to")
        try:
            secs = int(seconds or TEST_S)
        except (TypeError, ValueError):
            raise ValueError("how long: a number of seconds") from None
        if not TEST_MIN_S <= secs <= TEST_MAX_S:
            raise ValueError(f"a link test runs {TEST_MIN_S} to {TEST_MAX_S} seconds")
        with self.lock:
            d = self.load()
            th = self._thread(d, c)
            if any(it["dir"] == "out" and it.get("kind") == "test" and it["status"] in ("queued", "sending") for it in th):
                raise ValueError(f"a link test to {c} is already waiting")
            th.append({"id": uuid.uuid4().hex[:12], "dir": "out", "at": self.clock(), "status": "queued", "tries": 0,
                       "kind": "test", "seconds": secs})
            d["roster"].setdefault(c, {"call": c, "first_at": self.clock(), "unread": 0, "heard_at": None})
            self.save(d)
        self.tick()
        return self.view()

    def retry(self, mid: str) -> dict:
        with self.lock:
            d = self.load()
            for c, th in d["threads"].items():
                for it in th:
                    if it["id"] == mid and it["dir"] == "out" and it["status"] in ("failed", "queued"):
                        it.update(status="queued", tries=0, why=None)
                        self.backoff.pop(c, None)
            self.save(d)
        self.tick()
        return self.view()

    def cancel(self, mid: str) -> dict:
        drop = False
        with self.lock:
            d = self.load()
            for th in d["threads"].values():
                for it in th:
                    if it["id"] == mid and it["status"] in ("queued", "failed"):
                        it.update(status="cancelled")
                    elif it["id"] == mid and it["status"] == "sending" and it["dir"] == "out":
                        it.update(status="cancelled", why="you cancelled it")     # a file or a link test on its way:
                        drop = True                                               # VARA can only stop it by dropping the link
            self.save(d)
        if drop:
            try:
                self._vara().abort("the operator cancelled the transfer")
            except Exception:  # noqa: BLE001
                pass
        return self.view()

    def close_link(self) -> dict:
        v = self._vara()
        with self.lock:
            d = self.load()
            d["pinned"] = None
            self.save(d)
        v.disconnect()
        return self.view()

    # ----- VARA -> the channel -----
    def _thread(self, d: dict, call: str) -> list:
        th = d["threads"].setdefault(call, [])
        if len(th) > KEEP:
            del th[:len(th) - KEEP]
        return th

    def _rx_line(self, d: dict, peer: str, data: dict, status: str) -> dict:
        """The chat line of a file that is arriving from `peer`: the one still "receiving" with this name, or a new one."""
        th = self._thread(d, peer)
        it = next((x for x in reversed(th) if x["dir"] == "in" and x.get("kind") == "file"
                   and x["status"] == "receiving" and x.get("name") == data.get("name")), None)
        if it is None:
            it = {"id": uuid.uuid4().hex[:12], "dir": "in", "kind": "file", "name": data.get("name"),
                  "size": data.get("size"), "at": self.clock()}
            th.append(it)
        it.update(status=status, size=data.get("size") or it.get("size"))
        return it

    def _find(self, d: dict, peer: str, kind: str, seq) -> dict | None:
        mid = self.seq_map.get((peer, kind, seq))
        for it in d["threads"].get(peer, []):
            if it["id"] == mid:
                return it
        return None

    def on_event(self, name: str, data: dict):
        data = data or {}
        with self.lock:
            d = self.load()
            v = self.m.vara
            peer = (data.get("peer") or (v.state().get("peer") if v else None) or self.last_peer or "").upper() or None
            changed = True
            if name == "cq_heard":
                self._heard(d, data.get("call"), "announce")
                r = d["roster"].get((data.get("call") or "").upper())
                back = [x for x in reversed(data.get("via") or []) if x][:MAX_DIGIS]
                if r is not None:                                # the way its announcement came is the way back to it
                    r["heard_via"] = back
                    if r.get("via_by") != "you" and (r.get("via") or []) != back:
                        r.update(via=back, via_by="heard" if back else None, speed=None)
            elif name == "connected":
                self.linked = True
                self.last_peer = peer
                self.local = (data.get("local") or "").upper() or None
                if self._is_einstein(self.local):
                    for it in d["threads"].get(peer or "", []):  # answers kept since its last link
                        if it.get("by") == "einstein" and it["status"] == "held":
                            it["status"] = "queued"
                self._heard(d, peer, "link")
                if self.opened != peer and data.get("via") is not None:      # it called us: its path, backwards, is ours
                    r, back = d["roster"][peer], [x for x in reversed(data.get("via") or []) if x][:MAX_DIGIS]
                    if r.get("via_by") != "you" and (r.get("via") or []) != back:
                        r.update(via=back, via_by="heard" if back else None, speed=None)
                if self.opened == peer and self.connect_at:      # how long the call took: part of every file's time
                    d["roster"][peer]["setup_s"] = round(self.clock() - self.connect_at + 3, 1)
                self.activity_at = self.clock()
                self.backoff.pop(peer or "", None)
            elif name == "sn" and peer:
                self._heard(d, peer, "link", sn=data.get("sn"))
            elif name == "bitrate" and peer:
                self._heard(d, peer, "link", **{"bps_" + data.get("way", "tx"): data.get("bps")})
            elif name in ("test_started", "file_progress") and peer:
                self.activity_at = self.clock()
            elif name in ("test_done", "test_failed") and peer:
                it = self._find(d, peer, "test", data.get("seq"))
                res = data.get("result")
                if res:
                    res = dict(res, at=self.clock(), setup_s=d["roster"].get(peer, {}).get("setup_s") or SETUP_S)
                    self._heard(d, peer, "link", speed=res)
                if it and it["status"] == "cancelled":
                    it = None
                if it:
                    it.update(status="delivered" if res else "failed", why=data.get("why") if not res or res.get("partial") else None)
                    if res:
                        it["result"] = {k: res.get(k) for k in ("bytes", "s", "bps", "late_bps", "level", "modem_bps",
                                                                "sn", "partial")}
                        it["est"] = [[n, round(estimate_s(res, n))] for n in EST_SIZES]
                self.activity_at = self.clock()
            elif name == "test_received" and peer:
                self._heard(d, peer, "link", speed_rx={"bps": data.get("bps"), "bytes": data.get("bytes"),
                                                       "s": data.get("s"), "at": self.clock()})
                self._thread(d, peer).append({"id": uuid.uuid4().hex[:12], "dir": "in", "kind": "test",
                                              "at": self.clock(), "status": "received",
                                              "result": {"bytes": data.get("bytes"), "s": data.get("s"),
                                                         "bps": data.get("bps")}})
                self.activity_at = self.clock()
            elif name == "chat" and peer:
                self._heard(d, peer, "link")
                to_e = self._is_einstein(self.local)
                if not to_e:
                    d["roster"][peer]["unread"] = d["roster"][peer].get("unread", 0) + 1
                self._thread(d, peer).append(dict({"id": uuid.uuid4().hex[:12], "dir": "in", "kind": "chat",
                                                   "text": data.get("text"), "at": self.clock(), "status": "received"},
                                                  **({"to": "einstein"} if to_e else {})))
                r = d["roster"][peer]
                r.pop("working_until", None)
                self.activity_at = self.clock()
                if to_e:
                    self.save(d)
                    e = self.m.einstein()
                    threading.Thread(target=e.on_chat, args=(self.m.rid, peer, data.get("text"), self._einstein_send(peer)),
                                     daemon=True, name="einstein-in").start()
                    return
            elif name == "handshake" and peer:
                self._heard(d, peer, "link")
                self._learn_ai(d, peer, data.get("caps") or [])
            elif name == "auth" and peer:
                if self._is_einstein(self.local):
                    self.m.einstein().on_auth(self.m.rid, peer, data.get("token"))
                changed = False
            elif name == "peer_working" and peer:
                self._heard(d, peer, "link", working_until=self.clock() + min(180, int(data.get("s") or 30)))
                self.activity_at = self.clock()
            elif name == "file_receiving" and peer:              # a file is arriving: its line in the chat, with progress
                self._heard(d, peer, "link")
                self._rx_line(d, peer, data, status="receiving")
                self.activity_at = self.clock()
            elif name == "file_received" and peer:
                self._heard(d, peer, "link")
                d["roster"][peer]["unread"] = d["roster"][peer].get("unread", 0) + 1
                it = self._rx_line(d, peer, data, status="received")
                it["name"] = Path(data["path"]).name if data.get("path") else data.get("name")
                if it.get("at"):
                    it["took_s"] = round(self.clock() - it["at"], 1)
                self.activity_at = self.clock()
            elif name == "file_rejected" and peer:               # a file that was arriving and did not: say so in the log
                self._heard(d, peer, "link")
                it = self._rx_line(d, peer, data,
                                   status="cancelled" if data.get("why") == "you cancelled it" else "failed")
                it.update(done=data.get("done"), why=data.get("why"))
                if it["status"] == "cancelled":                  # tell the sender it was you, not the link: a note
                    self._thread(d, peer).append({               # that goes over a short link of its own
                        "id": uuid.uuid4().hex[:12], "dir": "out", "at": self.clock(), "status": "queued", "tries": 0,
                        "kind": "note", "note": "rxcancel", "name": data.get("name"),
                        "done": int(data.get("done") or 0), "size": int(data.get("size") or 0)})
                self.activity_at = self.clock()
            elif name == "rx_cancelled" and peer:                # ... and at the sender: that file's line says so
                size, done = int(data.get("size") or 0), int(data.get("done") or 0)
                why = (f"cancelled by the operator at {peer} after {100 * done // max(1, size)}% had arrived: "
                       f"not a link failure")
                it = next((x for x in reversed(d["threads"].get(peer, [])) if x["dir"] == "out" and x.get("kind") == "file"
                           and x.get("name") == data.get("name") and x["status"] in ("failed", "sending")), None)
                if it:
                    it.update(status="failed", why=why, cancelled_by=peer)
                else:
                    self._thread(d, peer).append({"id": uuid.uuid4().hex[:12], "dir": "in", "kind": "chat",
                                                  "at": self.clock(), "status": "received",
                                                  "text": f"{data.get('name')}: {why}"})
                self.activity_at = self.clock()
            elif name in ("file_sent", "file_failed") and peer:
                it = self._find(d, peer, "file", data.get("seq"))
                if it and it["status"] != "cancelled":
                    it.update(status="delivered" if name == "file_sent" else "failed", why=data.get("why"))
                    if name == "file_sent" and it.get("link_at"):
                        it["took_s"] = round(self.clock() - it["link_at"], 1)
                self.activity_at = self.clock()
            elif name == "buffer" and peer and data.get("bytes") == 0:
                for it in d["threads"].get(peer, []):            # VARA's ARQ: the other modem has every byte
                    if it["dir"] == "out" and it["kind"] in ("chat", "note") and it["status"] == "sent":
                        it["status"] = "delivered"
                self.activity_at = self.clock()
            elif name == "disconnected":
                gone = (data.get("peer") or "").upper() or self.opened
                for it in d["threads"].get(gone or "", []):      # a line still "receiving": the link went
                    if it["dir"] == "in" and it["status"] == "receiving":
                        it.update(status="failed", why="the link closed before the file was whole")
                for it in d["threads"].get(gone or "", []):
                    if it["dir"] == "out" and it["status"] in ("sending", "sent") and it["kind"] in ("chat", "note"):
                        it["status"] = "queued"                  # the link went before VARA confirmed it
                    elif it["dir"] == "out" and it["status"] == "sending" and it["kind"] == "test":
                        it.update(status="failed", why="the link closed before the test finished")
                if gone and gone == self.opened and not self.linked:
                    self._connecting_failed(d, gone)             # our call was never answered
                if self._is_einstein(self.local) and gone:
                    try:
                        self.m.einstein().on_disconnected(self.m.rid, gone)
                    except Exception:  # noqa: BLE001
                        pass
                    for it in d["threads"].get(gone, []):        # not sent: kept for its next link to Einstein
                        if it.get("by") == "einstein" and it["status"] in ("queued", "sending"):
                            it["status"] = "held"
                self.opened, self.connect_at, self.linked, self.local = None, None, False, None
                if d.get("pinned") == gone:
                    d["pinned"] = None
            else:
                changed = False
            if changed:
                self.save(d)

    def _connecting_failed(self, d: dict, call: str) -> bool:
        """A link we asked for never came up: count a try on what waits for that station; give up after TRIES."""
        hit = False
        for it in d["threads"].get(call, []):
            if it["dir"] == "out" and it["status"] == "queued":
                it["tries"] = it.get("tries", 0) + 1
                hit = True
                if it["tries"] >= TRIES:
                    it.update(status="failed", why=f"{call} did not answer ({TRIES} tries)")
        self.backoff[call] = self.clock() + BACKOFF_S * (1 + len(self.backoff))
        return hit

    # ----- the clock: keep-alives, the queue, closing quiet links -----
    def tick(self):
        v = self.m.vara
        if not v:
            return
        try:
            s = v.state()
        except Exception:  # noqa: BLE001
            return
        if s.get("link") != "up":
            return
        ok, _ = self.m.tx_allowed()
        now = self.clock()
        with self.lock:
            d = self.load()
            if d["on"] and ok and not s.get("listening") and s.get("session") == "idle":
                try:
                    v.listen(True)                               # you are back: answer calls again
                except Exception:  # noqa: BLE001
                    pass
            session = s.get("session")
            if session == "connected":
                peer = (s.get("peer") or "").upper()
                local = (s.get("local") or "").upper()
                if self._is_einstein(local):                     # Einstein's link: its own answers only
                    eok = self.m.tx_allowed(f"data:{local}")[0]
                    self._flush(d, v, s, peer, eok, only="einstein")
                    quiet = now - self.activity_at
                    e = self.m.einstein()
                    if quiet >= EINSTEIN_IDLE_S and not (e and e.busy.get((self.m.rid, peer))) \
                            and not s.get("sending") and not s.get("buffer") and not s.get("receiving"):
                        try:
                            v.disconnect()                       # a link left open with nothing said: let it go
                        except Exception:  # noqa: BLE001
                            pass
                    self.save(d)
                    return
                self._flush(d, v, s, peer, ok, only="operator")
                waiting = [it for it in d["threads"].get(peer, []) if it["dir"] == "out" and it["status"] == "queued"]
                others = any(it["dir"] == "out" and it["status"] == "queued"
                             for c, th in d["threads"].items() if c != peer for it in th)
                quiet = now - self.activity_at
                for it in d["threads"].get(peer, []):         # VARA said nothing more, and its buffer is empty
                    if it["status"] == "sent" and not s.get("buffer") and now - it.get("link_at", now) > 30:
                        it["status"] = "delivered"
                unconfirmed = any(it["status"] in ("sent", "sending") for it in d["threads"].get(peer, []))
                idle = quiet >= LINGER_S.get(s.get("kind") or "fm", 20) or (others and quiet >= MIN_QUIET_S)
                if self._ai_owes(d, peer, now):
                    idle = False                                 # an AI station is still working on our question
                if (self.opened == peer and d.get("pinned") != peer and not waiting and not unconfirmed
                        and not s.get("sending") and not s.get("buffer") and idle):
                    try:
                        v.disconnect()                           # quiet: let the frequency go
                    except Exception:  # noqa: BLE001
                        pass
                self.save(d)
                return
            if session == "connecting":
                hops = len((d["roster"].get(self.opened or "") or {}).get("via") or [])
                if self.connect_at and now - self.connect_at > CONNECT_TIMEOUT_S * (1 + hops):
                    try:
                        v.abort("no answer")
                    except Exception:  # noqa: BLE001
                        pass
                    if self.opened:
                        self._connecting_failed(d, self.opened)
                    self.opened, self.connect_at = None, None
                    self.save(d)
                return
            if not ok or s.get("busy"):
                if not s.get("busy"):
                    self._einstein_announce(d, v, s, now)        # you left: Einstein may still announce itself
                return                                           # you left, or someone is on the frequency
            nxt = self._next(d, now)
            if nxt:
                try:
                    v.connect(nxt, (d["roster"].get(nxt) or {}).get("via") or ())
                    self.opened, self.connect_at = nxt, now
                except Exception as e:  # noqa: BLE001
                    for it in d["threads"].get(nxt, []):
                        if it["dir"] == "out" and it["status"] == "queued":
                            it["why"] = str(e)
                    self.backoff[nxt] = now + BACKOFF_S
                self.save(d)
                return
            if d["on"] and now - (d.get("last_announce") or 0) >= d["every_min"] * 60:
                try:
                    self.announce()
                except Exception:  # noqa: BLE001
                    pass
            self._einstein_announce(d, v, s, now)

    def _next(self, d: dict, now: float) -> str | None:
        best = None
        for c, th in d["threads"].items():
            if self.backoff.get(c, 0) > now:
                continue
            q = [it["at"] for it in th if it["dir"] == "out" and it["status"] == "queued"]
            if q and (best is None or min(q) < best[0]):
                best = (min(q), c)
        return best[1] if best else None

    def _flush(self, d: dict, v, s: dict, peer: str, ok: bool, only: str = "operator"):
        """Send what waits for the station we are linked to (whoever opened the link). On Einstein's link only
        Einstein's own answers go; on the operator's, only the operator's."""
        if not ok or not peer:
            return
        for it in d["threads"].get(peer, []):
            if it["dir"] != "out" or it["status"] != "queued":
                continue
            if (it.get("by") == "einstein") != (only == "einstein"):
                continue
            try:
                if it["kind"] == "chat":
                    seq = v.send_chat(it["text"])
                    it.update(status="sent", link_at=self.clock())
                    self.seq_map[(peer, "chat", seq)] = it["id"]
                elif it["kind"] == "note":
                    if s.get("peer_proto") is None:
                        return                                   # after the handshake
                    if s.get("peer_proto") == "raw":
                        it.update(status="cancelled", why="a plain VARA terminal: no note")
                        continue
                    import urllib.parse
                    v.send_note(f"RXCANCEL {urllib.parse.quote(it.get('name') or 'file', safe='')} "
                                f"{it.get('done', 0)} {it.get('size', 0)}")
                    it.update(status="sent", link_at=self.clock())
                elif it["kind"] == "test":
                    if s.get("sending") or s.get("testing") or s.get("peer_proto") is None:
                        return                                   # after the handshake, and nothing else under way
                    if s.get("peer_proto") == "raw" or "+TEST" not in (s.get("peer_caps") or []):
                        it.update(status="failed", why=f"{peer}'s program has no link test (a plain VARA terminal, "
                                                       f"or an older HAM Sidekick): it needs an update")
                        continue
                    seq = v.link_test(it.get("seconds"))
                    it.update(status="sending", link_at=self.clock())
                    self.seq_map[(peer, "test", seq)] = it["id"]
                    self.activity_at = self.clock()
                    return
                else:
                    if s.get("testing"):
                        return
                    if s.get("sending") or s.get("peer_proto") is None:
                        return                                   # one file at a time; after the handshake
                    if s.get("peer_proto") == "raw":
                        it.update(status="failed", why=f"{peer} runs a plain VARA terminal: files need this program")
                        continue
                    data = (self._files() / it["id"]).read_bytes()
                    seq = v.send_file(name=it["name"], data=data)
                    it.update(status="sending", link_at=self.clock())
                    self.seq_map[(peer, "file", seq)] = it["id"]
                    self.activity_at = self.clock()
                    return
                self.activity_at = self.clock()
            except Exception as e:  # noqa: BLE001
                it["why"] = str(e)
                return

    # ----- Einstein (station/einstein.py) -----
    def _is_einstein(self, local) -> bool:
        e = self.m.einstein()
        try:
            return bool(local and e is not None and local.upper() == e.call(self.m.rid).upper())
        except Exception:  # noqa: BLE001
            return False

    def _einstein_send(self, peer: str):
        """What Einstein puts on the link: queued as its own lines in that station's thread, sent by _flush on this
        link (or kept, "held", for the station's next link if this one has closed)."""
        def send(text=None, name=None, data=None, note=None):
            v = self.m.vara
            s = v.state() if v else {}
            here = (s.get("session") == "connected" and (s.get("peer") or "").upper() == peer
                    and self._is_einstein(s.get("local")))
            if note:
                if here and s.get("peer_proto") == "HSK1":
                    try:
                        v.send_note(note)
                    except Exception:  # noqa: BLE001
                        pass
                return
            with self.lock:
                d = self.load()
                it = {"id": uuid.uuid4().hex[:12], "dir": "out", "at": self.clock(), "status": "queued" if here else "held",
                      "tries": 0, "by": "einstein"}
                if name is not None:
                    from .vara import clean_name
                    it.update(kind="file", name=clean_name(name), size=len(data or b""))
                    f = self._files() / it["id"]
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(data or b"")
                else:
                    it.update(kind="chat", text=str(text or ""))
                self._thread(d, peer).append(it)
                if here:
                    s = v.state()
                    self._flush(d, v, s, peer, self.m.tx_allowed(f"data:{s.get('local')}")[0], only="einstein")
                    self.activity_at = self.clock()
                self.save(d)
        return send

    def _learn_ai(self, d: dict, peer: str, caps: list):
        """What a station's handshake says about AI stations: "+AI +OF=<call> +NAME=<name>" (it is one) or
        "+AI=<call>" (its operator's Einstein answers at that call). Then, as the asker: prove we are its operator."""
        r = d["roster"].get(peer)
        if r is None:
            return
        kv = {}
        for c in caps:
            k, _, val = str(c).lstrip("+").partition("=")
            kv[k.upper()] = val
        if "AI" in kv and not kv["AI"]:
            r["ai"] = {"of": kv.get("OF") or None, "name": (kv.get("NAME") or "AI").replace("_", " ").title()}
        elif kv.get("AI"):
            from .vara import CALL_RE
            ac = kv["AI"].split(":")[0].upper()
            if CALL_RE.match(ac):
                r["einstein"] = ac
                a = d["roster"].setdefault(ac, {"call": ac, "first_at": self.clock(), "unread": 0, "heard_at": None})
                a.setdefault("ai", {"of": peer, "name": "AI"})
        nonce = kv.get("NONCE")
        if "AI" in kv and nonce and not kv["AI"]:
            from .einstein import base, owner_token
            mine = self.m.call()
            e = self.m.einstein()
            key = e.owner_key() if e is not None else None
            if key and base(peer) == base(mine):
                try:
                    self.m.vara.send_note(f"AUTH {owner_token(key, nonce, mine)}")
                    r["owner"] = True
                except Exception:  # noqa: BLE001
                    pass

    def _ai_owes(self, d: dict, peer: str, now: float) -> bool:
        r = d["roster"].get(peer) or {}
        if not r.get("ai"):
            return False
        if (r.get("working_until") or 0) > now:
            return True
        th = d["threads"].get(peer, [])
        last_in = max((it["at"] for it in th if it["dir"] == "in"), default=0)
        last_q = max((it["at"] for it in th if it["dir"] == "out" and it.get("kind") == "chat"), default=0)
        return last_q > last_in and now - last_q < AI_WAIT_S

    def _einstein_announce(self, d: dict, v, s: dict, now: float):
        e = self.m.einstein()
        if e is None or s.get("session") != "idle" or s.get("busy"):
            return
        try:
            if not e.answering(self.m.rid) or not e.rules(self.m.rid)["announce"][0]:
                return
            if now - (d.get("e_last_announce") or 0) < d["every_min"] * 60:
                return
            v.cq(d.get("announce_via") or (), call=e.call(self.m.rid))
            d["e_last_announce"] = now
            self.save(d)
        except Exception:  # noqa: BLE001
            pass

    # ----- the view -----
    def _einstein_view(self):
        e = self.m.einstein()
        try:
            return e.state(self.m.rid) if e is not None else None
        except Exception:  # noqa: BLE001
            return None

    def summary(self) -> dict:
        """For the radio card: on the channel or not, who is here or quiet, unread messages (owner 2026-11-18: "I don't
        see anything on the dashboard ... radio column showing that a station has announced")."""
        d = self.load()
        now = self.clock()
        ros = [{"call": c, "state": self.presence(r, d["every_min"], now), "heard_at": r.get("heard_at"),
                "unread": r.get("unread", 0)} for c, r in d["roster"].items() if r.get("heard_at")]
        ros = [r for r in ros if r["state"] != "gone"]
        ros.sort(key=lambda r: (r["state"] != "here", -(r["heard_at"] or 0)))
        return {"on": d["on"], "stations": ros[:8], "more": max(0, len(ros) - 8),
                "unread": sum(r.get("unread", 0) for r in d["roster"].values())}

    def view(self) -> dict:
        d = self.load()
        now = self.clock()
        v = self.m.vara
        s = v.state() if v else {}
        roster = []
        for c, r in d["roster"].items():
            th = d["threads"].get(c, [])
            sp = r.get("speed")
            r = dict(r, est=[[n, round(estimate_s(sp, n))] for n in EST_SIZES] if sp else None)
            roster.append(dict(r, state=self.presence(r, d["every_min"], now) if r.get("heard_at") else "unheard",
                               age_s=round(now - r["heard_at"]) if r.get("heard_at") else None,
                               linked=(s.get("session") == "connected" and (s.get("peer") or "").upper() == c),
                               waiting=sum(1 for it in th if it["dir"] == "out" and it["status"] in ("queued", "sent")),
                               failed=sum(1 for it in th if it["dir"] == "out" and it["status"] == "failed")))
        by = {r["call"]: r for r in roster}
        for r in roster:
            r["working_s"] = max(0, round((r.get("working_until") or 0) - now))
            par = by.get((r.get("ai") or {}).get("of") or "")
            if par and r["state"] in ("unheard", "gone") and par["state"] in ("here", "quiet"):
                r["state"] = par["state"]                         # an AI station is where its operator's station is
        order = {"here": 0, "quiet": 1, "unheard": 2, "gone": 3}
        roster.sort(key=lambda r: (not r["linked"], order[r["state"]], -(r.get("heard_at") or 0), r["call"]))
        nxt = None
        if d["on"]:
            nxt = max(0, round((d.get("last_announce") or 0) + d["every_min"] * 60 - now))
        op = (getattr(self.m.st, "_saved", lambda: {})() or {}).get("operator") or {}
        return {"on": d["on"], "every_min": d["every_min"], "next_announce_s": nxt, "presets": d["presets"],
                "asks": d.get("asks") or [], "asks_max": ASKS_MAX,
                "pinned": d.get("pinned"), "roster": roster, "announce_via": d.get("announce_via") or [],
                "testing": s.get("testing"), "bitrate": s.get("bitrate"),
                "threads": {c: th[-120:] for c, th in d["threads"].items()},
                "me": {"call": self.m.call(), "name": op.get("name") or "", "grid": op.get("grid") or ""},
                "local": s.get("local"),
                "einstein": self._einstein_view(),
                "linger_s": LINGER_S.get(s.get("kind") or self.m.cfg().get("kind", "fm"), 20)}
