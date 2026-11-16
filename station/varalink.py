"""VARA on the station: keyboard chat and file transfer over VARA HF / FM, through the VARA modems on this PC
(station/vara.py speaks to each one).

Owner 2026-11-15: "How can we add chat and file transfer over VARA FM and VARA HF to this tool?", then "build both".
Owner 2026-11-16: "the operator may want to run multiple VARA HF or VARA FM servers depending on their radio
configuration ... one VARA FM for Winlink and a separate radio/VARA FM server for VARA chat and file transfer", and
"we need to support taking turns on the same VARA FM (or VARA HF) service/radio or also support them running as
separate radios/services. We may have multiple VARA sessions".

* ONE MODEM PER DATA RADIO: each radio whose card role is "winlink" (capture never shares its sound card) can have one
  VARA modem: VARA HF or VARA FM at its own TCP ports (a second copy of VARA in its own folder, its own sound card).
  Each modem is used for one of:
    chat     chat & files, this station only: it never steps aside for Winlink Express (Express uses another modem)
    shared   chat & files and Winlink Express TAKE TURNS: while Express is open and no chat is under way, this station
             lets go (station/vara.py); it reconnects when Express closes. "Hand to Winlink Express" lets go at once.
    winlink  Winlink Express only: this station never connects to it (listed so the plan is complete)
  Every modem runs on its own: several chat sessions at once, each with its own log and received files.
* TRANSMITTING (Part 97): every transmission a modem can make for us passes its tx_allowed():
    - its radio's own Transmit switch (Radios... -> Transmit, station/ptt.py),
    - the operator at the dashboard (keyboard or mouse in the last few minutes, as Sidekick's Send mode),
    - the license class's data privileges and the band plan at that radio's frequency (station/bandplan.py).
  Listening (VARA answers calls by itself) is switched off the moment any of those fails. No beacon, no automatic
  relay, no auto-reply: a CQ or a connect is the operator's click. Never encrypted (97.113).
* RECEIVED FILES go to the modem's inbox and are only ever offered as downloads (never opened or run here).
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from . import bandplan

USES = ("chat", "shared", "winlink")
MODEM = {"radio": None, "kind": "hf", "host": "127.0.0.1", "cmd_port": 8300, "data_port": 8301, "bw": None,
         "use": "shared", "enabled": False, "handed_off": False, "fm_width": "narrow"}
PORTS = (8300, 8310, 8320, 8330, 8340, 8350)       # suggested pairs: cmd, cmd + 1
CHECK_S = 5


class Modem:
    """One radio's VARA modem."""

    def __init__(self, link: "Link", rid: str):
        self.link, self.rid = link, rid
        self.vara = None
        self.last_event = None
        self.lock = threading.Lock()

    @property
    def st(self):
        return self.link.st

    def cfg(self) -> dict:
        return self.link.modem_cfg(self.rid)

    def dir(self) -> Path:
        c = self.cfg()
        base = Path(self.st.data) / "vara"
        return base if c.get("legacy_dir") else base / "radios" / self.rid

    # ----- transmit permission -----
    def tx_allowed(self) -> tuple[bool, str]:
        r = (getattr(self.st, "radios", {}) or {}).get(self.rid)
        if not r or r.get("role") != "winlink":
            return False, "the VARA radio is not a data (Winlink) radio"
        if self.cfg().get("use") == "winlink":
            return False, "this modem is for Winlink Express only"
        ok, why = self.st.ptt.allowed(self.rid)
        if not ok:
            return False, why
        agent = getattr(self.st, "agent", None)
        sender = getattr(agent, "sender", None)
        if not (sender and sender.present()):
            return False, "you are not at the dashboard (VARA transmits only with you here)"
        cls = ((getattr(agent, "cfg", None) or {}).get("license_class") or "").lower() or None
        if not cls:
            return False, "set your license class (Settings → Sidekick & AI)"
        f = r.get("freq_mhz")
        if not f:
            return False, "set the radio's frequency so its privileges can be checked"
        chk = bandplan.check(f, "VARA", cls)
        if chk["ok"] is not True:
            return False, chk["why"] or "no data privileges there"
        return True, ""

    # ----- the modem client -----
    def runs(self) -> bool:
        c = self.cfg()
        return bool(c["enabled"] and not c["handed_off"] and c["use"] != "winlink")

    def restart(self):
        with self.lock:
            old, self.vara = self.vara, None
        if old:
            try:
                old.stop()
            except Exception:  # noqa: BLE001
                pass
        c = self.cfg()
        if not self.runs():
            self.link._publish("status", self.rid)
            return
        mk = self.link.factory
        if mk is None:
            from .vara import Vara as mk
        shared = c["use"] == "shared"
        try:
            v = mk(data_dir=self.st.data, log_dir=self.dir(), mycall=getattr(self.st, "me", ""), kind=c["kind"],
                   host=c["host"], cmd_port=c["cmd_port"], data_port=c["data_port"], tx_allowed=self.tx_allowed,
                   bw=c["bw"] if c["kind"] == "hf" else None, on_event=self._event,
                   winlink_open=(lambda: self.link._express()) if shared else (lambda: False))
        except ValueError as e:
            self.last_event = {"name": "error", "error": str(e)}
            self.link._publish("error", self.rid)
            return
        with self.lock:
            self.vara = v
        v.start()

    def stop(self):
        with self.lock:
            v, self.vara = self.vara, None
        if v:
            try:
                v.stop()
            except Exception:  # noqa: BLE001
                pass

    def check(self) -> str | None:
        """Listening stops the moment transmitting is no longer allowed (the operator left, the switch went off)."""
        v = self.vara
        if not v:
            return None
        try:
            s = v.state()
        except Exception:  # noqa: BLE001
            return None
        if not s.get("listening"):
            return None
        ok, why = self.tx_allowed()
        if ok:
            return None
        try:
            v.listen(False)
        except Exception:  # noqa: BLE001
            pass
        self.last_event = {"name": "listen_off", "why": why}
        self.link._publish("listen_off", self.rid)
        return why

    def _event(self, name: str, data: dict):
        if name in ("chat", "chat_sent", "file_received", "file_sent", "file_failed", "file_rejected", "connected",
                    "disconnected", "abort", "watchdog", "cq_heard", "handshake"):
            self.last_event = {"name": name, **{k: v for k, v in (data or {}).items()
                                                if isinstance(v, (str, int, float, bool, type(None)))}}
        self.link._publish(name, self.rid)

    # ----- the view -----
    def view(self, transcript: bool = True) -> dict:
        c = self.cfg()
        v = self.vara
        r = (getattr(self.st, "radios", {}) or {}).get(self.rid) or {}
        ok, why = self.tx_allowed() if c["enabled"] and c["use"] != "winlink" else (False, "")
        s = None
        if v:
            try:
                s = v.state()
            except Exception:  # noqa: BLE001
                s = None
        out = {"radio": self.rid, "name": r.get("name") or self.rid, "freq_mhz": r.get("freq_mhz"), "cfg": c,
               "tx_ok": ok, "tx_why": why, "state": s, "last": self.last_event, "status": self._status(c, s)}
        if transcript:
            out["transcript"] = self.transcript()
            out["inbox"] = self.inbox()
        return out

    def _status(self, c: dict, s: dict | None) -> dict:
        """One word and a sentence for the modem's state, the same on the radio card and in the window."""
        if c["use"] == "winlink":
            return {"key": "winlink", "text": "Winlink Express only: this station never connects to it"}
        if not c["enabled"]:
            return {"key": "off", "text": "Off"}
        if c["handed_off"]:
            return {"key": "express", "text": "Handed to Winlink Express (Take back when you are done)"}
        if not s:
            return {"key": "off", "text": "Starting…"}
        if s.get("link") != "up":
            if c["use"] == "shared" and self.link._express():
                return {"key": "express", "text": "Winlink Express's turn: it is open (this station takes VARA "
                                                  "back when it closes)"}
            return {"key": "down", "text": f"VARA is not answering on {c['host']}:{c['cmd_port']}: is that copy of "
                                           "VARA running? Another program (Winlink Express?) may be using it"}
        if s.get("session") == "connected":
            return {"key": "connected", "text": f"Connected to {s.get('peer')}"}
        if s.get("session") == "connecting":
            return {"key": "connecting", "text": f"Calling {s.get('peer')}…"}
        return {"key": "listening" if s.get("listening") else "ready",
                "text": "Listening for calls" if s.get("listening") else "Ready (not listening)"}

    def transcript(self, n: int = 200) -> list[dict]:
        out = []
        for p in sorted(self.dir().glob("*.jsonl"))[-2:]:
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
            except OSError:
                pass
        return out[-n:]

    def inbox(self) -> list[dict]:
        d = self.dir() / "inbox"
        if not d.is_dir():
            return []
        return [{"name": p.name, "bytes": p.stat().st_size, "at": p.stat().st_mtime}
                for p in sorted(d.iterdir(), key=lambda p: -p.stat().st_mtime) if p.is_file()][:100]

    # ----- the operator's actions -----
    def _v(self):
        c = self.cfg()
        if c["use"] == "winlink":
            raise ValueError("this modem is for Winlink Express only: choose Chat & files or Shared to use it here")
        if not c["enabled"]:
            raise ValueError("switch this VARA modem on first")
        if c["handed_off"]:
            raise ValueError("this VARA modem is with Winlink Express: take it back first")
        if not self.vara:
            raise ValueError("VARA is not running")
        return self.vara

    def act(self, what: str, body: dict):
        from .vara import VaraRefused
        try:
            if what == "connect":
                self._v().connect(str(body.get("call") or "").upper().strip(), body.get("via") or ())
            elif what == "disconnect":
                self._v().disconnect()
            elif what == "abort":
                self._v().abort("operator")
            elif what == "listen":
                self._v().listen(bool(body.get("on")))
            elif what == "cq":
                self._v().cq(body.get("via") or ())
            elif what == "chat":
                self._v().send_chat(str(body.get("text") or ""))
            elif what == "file":
                import base64
                try:
                    data = base64.b64decode(str(body.get("data") or ""), validate=True)
                except ValueError:
                    raise ValueError("the file did not arrive whole: try again") from None
                self._v().send_file(name=str(body.get("name") or "file"), data=data)
            elif what == "handoff":                  # a shared modem: Winlink Express's turn now
                if self.cfg()["use"] != "shared":
                    raise ValueError("only a modem shared with Winlink Express is handed over")
                self.link._update(self.rid, handed_off=True)
                self.restart()
            elif what == "takeback":
                if self.link._express():
                    raise ValueError("Winlink Express is still open: close it first")
                self.link._update(self.rid, handed_off=False)
                self.restart()
            else:
                raise ValueError("unknown VARA action")
        except VaraRefused as e:
            raise ValueError(str(e)) from None


class Link:
    """Every VARA modem on this station (station.vara)."""

    def __init__(self, st, factory=None, clock=time.time):
        self.st = st
        self.factory = factory            # (**kwargs) -> a Vara-like object; None = station.vara.Vara
        self.clock = clock
        self.lock = threading.RLock()
        self.modems: dict[str, Modem] = {}
        self.stop_ev = threading.Event()
        self._checker = None
        self._express_at, self._express_val = 0.0, False

    # ----- settings (data/vara.json: {"modems": {radio id: modem}}) -----
    def _path(self) -> Path:
        return Path(self.st.data) / "vara.json"

    def _load(self) -> dict:
        try:
            d = json.loads(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        if "modems" not in d:                        # before 2026-11-16: one modem, handed over by hand (= shared)
            mods = {}
            if d.get("radio"):
                mods[d["radio"]] = MODEM | {k: d[k] for k in MODEM if k in d} | {"use": "shared", "legacy_dir": True}
            d = {"modems": mods}
        return d

    def _save(self, d: dict):
        self._path().parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path().with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        tmp.replace(self._path())

    def modem_cfg(self, rid: str) -> dict:
        return MODEM | (self._load()["modems"].get(rid) or {}) | {"radio": rid}

    def _update(self, rid: str, **kw):
        with self.lock:
            d = self._load()
            d["modems"][rid] = self.modem_cfg(rid) | kw
            self._save(d)

    def data_radios(self) -> list[dict]:
        return [{"id": rid, "name": r.get("name") or rid} for rid, r in (getattr(self.st, "radios", {}) or {}).items()
                if r.get("role") == "winlink"]

    winlink_radios = data_radios

    def modem(self, rid: str | None) -> Modem:
        mods = self._load()["modems"]
        if not rid:
            if len(mods) == 1:
                rid = next(iter(mods))
            else:
                raise ValueError("say which radio's VARA modem")
        if rid not in mods and rid not in {r["id"] for r in self.data_radios()}:
            raise ValueError("no VARA modem on that radio")
        with self.lock:
            if rid not in self.modems:
                self.modems[rid] = Modem(self, rid)
            return self.modems[rid]

    def any_enabled(self) -> bool:
        return any(m.get("enabled") for m in self._load()["modems"].values())

    def suggest_ports(self) -> tuple[int, int]:
        used = {m.get("cmd_port") for m in self._load()["modems"].values()} | \
               {m.get("data_port") for m in self._load()["modems"].values()}
        for p in PORTS:
            if p not in used and p + 1 not in used:
                return p, p + 1
        return 8400, 8401

    def settings(self, body: dict) -> dict:
        """One modem's settings: {radio, kind, host, cmd_port, data_port, bw, use, enabled} or {radio, remove}."""
        data = {r["id"] for r in self.data_radios()}
        rid = body.get("radio")
        if not rid:
            if len(data) != 1:
                raise ValueError("choose the data radio this VARA modem is connected to")
            rid = next(iter(data))
        mods = self._load()["modems"]
        if rid not in data and not (body.get("remove") and rid in mods):
            raise ValueError("VARA runs only on a data radio: Radios… → the radio → Role: Winlink / data")
        if body.get("remove"):
            self.modem(rid).stop()
            with self.lock:
                d = self._load()
                d["modems"].pop(rid, None)
                self._save(d)
                self.modems.pop(rid, None)
            self._publish("removed", rid)
            return self.view()
        new = rid not in mods
        c = self.modem_cfg(rid)
        if new and "cmd_port" not in body:
            c["cmd_port"], c["data_port"] = self.suggest_ports()
        if "kind" in body:
            if body["kind"] not in ("hf", "fm"):
                raise ValueError("VARA HF or VARA FM")
            c["kind"] = body["kind"]
        if "use" in body:
            if body["use"] not in USES:
                raise ValueError("a VARA modem is for chat & files, shared with Winlink Express, or Winlink Express")
            c["use"] = body["use"]
            if c["use"] != "shared":
                c["handed_off"] = False
        for k in ("cmd_port", "data_port"):
            if k in body:
                try:
                    v = int(body[k])
                except (TypeError, ValueError):
                    raise ValueError("a port is a number, 1024 to 65535") from None
                if not 1024 <= v <= 65535:
                    raise ValueError("a port is 1024 to 65535")
                c[k] = v
        if "cmd_port" in body and "data_port" not in body:
            c["data_port"] = c["cmd_port"] + 1               # VARA's data port is always the next one
        if c["cmd_port"] == c["data_port"]:
            raise ValueError("the command and data ports differ (VARA uses two: e.g. 8300 and 8301)")
        if "host" in body:
            h = str(body["host"] or "").strip()
            if not re.fullmatch(r"[\w.-]{1,100}", h):
                raise ValueError("the VARA host is a name or address")
            c["host"] = h
        if "bw" in body:
            if body["bw"] not in (None, "", 500, 2300, 2750):
                raise ValueError("VARA HF bandwidth is 500, 2300 or 2750 Hz")
            c["bw"] = body["bw"] or None
        if "fm_width" in body:                               # VARA FM narrow / wide, as set in VARA FM itself
            if body["fm_width"] not in ("narrow", "wide"):
                raise ValueError("VARA FM is narrow or wide")
            c["fm_width"] = body["fm_width"]
        if "enabled" in body:
            c["enabled"] = bool(body["enabled"])
        for orid, o in mods.items():                         # two modems never share a port on one host
            if orid != rid and o.get("host", "127.0.0.1") == c["host"] and \
                    {o.get("cmd_port"), o.get("data_port")} & {c["cmd_port"], c["data_port"]}:
                name = next((r["name"] for r in self.data_radios() if r["id"] == orid), orid)
                raise ValueError(f"ports {c['cmd_port']}/{c['data_port']} are already {name}'s VARA modem: each copy "
                                 f"of VARA needs its own (try {self.suggest_ports()[0]}/{self.suggest_ports()[1]})")
        with self.lock:
            d = self._load()
            d["modems"][rid] = {k: c[k] for k in list(MODEM) + (["legacy_dir"] if c.get("legacy_dir") else [])
                                if k != "radio"} | {"radio": rid}
            self._save(d)
        self.modem(rid).restart()
        self._ensure_checker()
        return self.view()

    # ----- running -----
    def restart(self):
        """Start every modem that is switched on (the station's start)."""
        for rid in list(self._load()["modems"]):
            if rid in {r["id"] for r in self.data_radios()}:
                self.modem(rid).restart()
        self._ensure_checker()

    def stop(self):
        self.stop_ev.set()
        for m in list(self.modems.values()):
            m.stop()

    def _ensure_checker(self):
        if self._checker and self._checker.is_alive():
            return
        self._checker = threading.Thread(target=self._check_loop, daemon=True, name="vara-check")
        self._checker.start()

    def _check_loop(self):
        while not self.stop_ev.wait(CHECK_S):
            self.check()

    def check(self) -> dict:
        return {rid: m.check() for rid, m in list(self.modems.items())}

    def _express(self) -> bool:
        now = time.monotonic()                       # asked by every modem every few seconds: once is enough
        if now - self._express_at > 3:
            try:
                from .winlink import express_running
                self._express_val = bool(express_running())
            except Exception:  # noqa: BLE001
                self._express_val = False
            self._express_at = now
        return self._express_val

    def _publish(self, name: str, rid: str | None = None):
        try:
            m = self.modems.get(rid) if rid else None
            self.st.publish("vara", {"event": name, "radio": rid, "modem": m.view(transcript=False) if m else None})
        except Exception:  # noqa: BLE001
            pass

    # ----- the view -----
    def view(self, transcript: bool = True) -> dict:
        mods = self._load()["modems"]
        data = self.data_radios()
        out = [self.modem(rid).view(transcript) for rid in mods if rid in {r["id"] for r in data}]
        return {"modems": out, "radios": [r | {"modem": r["id"] in mods} for r in data],
                "express_running": self._express(), "suggest_ports": list(self.suggest_ports())}

    def inbox_file(self, name: str) -> Path | None:
        if not re.fullmatch(r"[\w .@()+,=-]{1,200}", name or "") or name.startswith("."):
            return None
        for rid in self._load()["modems"]:
            p = self.modem(rid).dir() / "inbox" / name
            if p.is_file():
                return p
        p = Path(self.st.data) / "vara" / "inbox" / name
        return p if p.is_file() else None

    def act(self, what: str, body: dict) -> dict:
        self.modem(body.get("radio")).act(what, body)
        return self.view()
