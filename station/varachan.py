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
            elif name in ("test_started", "file_receiving", "file_progress") and peer:
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
                d["roster"][peer]["unread"] = d["roster"][peer].get("unread", 0) + 1
                self._thread(d, peer).append({"id": uuid.uuid4().hex[:12], "dir": "in", "kind": "chat",
                                              "text": data.get("text"), "at": self.clock(), "status": "received"})
                self.activity_at = self.clock()
            elif name == "file_received" and peer:
                self._heard(d, peer, "link")
                d["roster"][peer]["unread"] = d["roster"][peer].get("unread", 0) + 1
                self._thread(d, peer).append({"id": uuid.uuid4().hex[:12], "dir": "in", "kind": "file",
                                              "name": Path(data["path"]).name if data.get("path") else data.get("name"),
                                              "size": data.get("size"), "at": self.clock(), "status": "received"})
                self.activity_at = self.clock()
            elif name in ("file_sent", "file_failed", "file_rejected") and peer:
                it = self._find(d, peer, "file", data.get("seq"))
                if it and it["status"] != "cancelled":
                    it.update(status="delivered" if name == "file_sent" else "failed", why=data.get("why"))
                    if name == "file_sent" and it.get("link_at"):
                        it["took_s"] = round(self.clock() - it["link_at"], 1)
                self.activity_at = self.clock()
            elif name == "buffer" and peer and data.get("bytes") == 0:
                for it in d["threads"].get(peer, []):            # VARA's ARQ: the other modem has every byte
                    if it["dir"] == "out" and it["kind"] == "chat" and it["status"] == "sent":
                        it["status"] = "delivered"
                self.activity_at = self.clock()
            elif name == "disconnected":
                gone = (data.get("peer") or "").upper() or self.opened
                for it in d["threads"].get(gone or "", []):
                    if it["dir"] == "out" and it["status"] in ("sending", "sent") and it["kind"] == "chat":
                        it["status"] = "queued"                  # the link went before VARA confirmed it
                    elif it["dir"] == "out" and it["status"] == "sending" and it["kind"] == "test":
                        it.update(status="failed", why="the link closed before the test finished")
                if gone and gone == self.opened and not self.linked:
                    self._connecting_failed(d, gone)             # our call was never answered
                self.opened, self.connect_at, self.linked = None, None, False
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
                self._flush(d, v, s, peer, ok)
                waiting = [it for it in d["threads"].get(peer, []) if it["dir"] == "out" and it["status"] == "queued"]
                others = any(it["dir"] == "out" and it["status"] == "queued"
                             for c, th in d["threads"].items() if c != peer for it in th)
                quiet = now - self.activity_at
                for it in d["threads"].get(peer, []):         # VARA said nothing more, and its buffer is empty
                    if it["status"] == "sent" and not s.get("buffer") and now - it.get("link_at", now) > 30:
                        it["status"] = "delivered"
                unconfirmed = any(it["status"] in ("sent", "sending") for it in d["threads"].get(peer, []))
                idle = quiet >= LINGER_S.get(s.get("kind") or "fm", 20) or (others and quiet >= MIN_QUIET_S)
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

    def _next(self, d: dict, now: float) -> str | None:
        best = None
        for c, th in d["threads"].items():
            if self.backoff.get(c, 0) > now:
                continue
            q = [it["at"] for it in th if it["dir"] == "out" and it["status"] == "queued"]
            if q and (best is None or min(q) < best[0]):
                best = (min(q), c)
        return best[1] if best else None

    def _flush(self, d: dict, v, s: dict, peer: str, ok: bool):
        """Send what waits for the station we are linked to (whoever opened the link)."""
        if not ok or not peer:
            return
        for it in d["threads"].get(peer, []):
            if it["dir"] != "out" or it["status"] != "queued":
                continue
            try:
                if it["kind"] == "chat":
                    seq = v.send_chat(it["text"])
                    it.update(status="sent", link_at=self.clock())
                    self.seq_map[(peer, "chat", seq)] = it["id"]
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

    # ----- the view -----
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
                               waiting=sum(1 for it in th if it["dir"] == "out" and it["status"] == "queued"),
                               failed=sum(1 for it in th if it["dir"] == "out" and it["status"] == "failed")))
        order = {"here": 0, "quiet": 1, "unheard": 2, "gone": 3}
        roster.sort(key=lambda r: (not r["linked"], order[r["state"]], -(r.get("heard_at") or 0), r["call"]))
        nxt = None
        if d["on"]:
            nxt = max(0, round((d.get("last_announce") or 0) + d["every_min"] * 60 - now))
        op = (getattr(self.m.st, "_saved", lambda: {})() or {}).get("operator") or {}
        return {"on": d["on"], "every_min": d["every_min"], "next_announce_s": nxt, "presets": d["presets"],
                "pinned": d.get("pinned"), "roster": roster, "announce_via": d.get("announce_via") or [],
                "testing": s.get("testing"), "bitrate": s.get("bitrate"),
                "threads": {c: th[-120:] for c, th in d["threads"].items()},
                "me": {"call": self.m.call(), "name": op.get("name") or "", "grid": op.get("grid") or ""},
                "linger_s": LINGER_S.get(s.get("kind") or self.m.cfg().get("kind", "fm"), 20)}
