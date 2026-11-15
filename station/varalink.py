"""VARA on the station (Radios -> the Winlink radio -> Keyboard): keyboard chat and file transfer over VARA HF / FM,
through the VARA modem the operator already runs for Winlink Express (station/vara.py speaks to it).

Owner 2026-11-15: "How can we add chat and file transfer over VARA FM and VARA HF to this tool?", then "build both".

* ONE RADIO: the radio whose card role is "winlink" (capture never shares the VARA sound card). Off until switched on.
* TRANSMITTING (Part 97): every transmission VARA can make for us passes tx_allowed():
    - the radio's own Transmit switch (Radios... -> Transmit, station/ptt.py),
    - the operator at the dashboard (keyboard or mouse in the last few minutes, as Sidekick's Send mode),
    - the license class's data privileges and the band plan at the radio's frequency (station/bandplan.py).
  Listening (VARA answers calls by itself) is switched off here the moment any of those fails. No beacon, no
  automatic relay, no auto-reply: a CQ or a connect is the operator's click. Never encrypted (97.113).
* WINLINK EXPRESS HANDOFF: VARA serves one program. "Hand VARA to Winlink Express" lets go of it; while Express is
  open this station never takes VARA back; "Take VARA back" reconnects.
* RECEIVED FILES go to data/vara/inbox/ and are only ever offered as downloads (never opened or run here).
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from . import bandplan

DEFAULTS = {"enabled": False, "radio": None, "kind": "hf", "host": "127.0.0.1", "cmd_port": 8300, "data_port": 8301,
            "bw": None, "handed_off": False}
CHECK_S = 5


class Link:
    def __init__(self, st, factory=None, clock=time.time):
        self.st = st
        self.factory = factory            # (**kwargs) -> a Vara-like object; None = station.vara.Vara
        self.clock = clock
        self.vara = None
        self.lock = threading.Lock()
        self.last_event = None
        self.stop_ev = threading.Event()
        self._checker = None

    # ----- settings -----
    def _path(self) -> Path:
        return Path(self.st.data) / "vara.json"

    def cfg(self) -> dict:
        try:
            return DEFAULTS | json.loads(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return dict(DEFAULTS)

    def _save(self, c: dict):
        self._path().parent.mkdir(parents=True, exist_ok=True)
        self._path().write_text(json.dumps(c, indent=1), encoding="utf-8")

    def winlink_radios(self) -> list[dict]:
        return [{"id": rid, "name": r.get("name") or rid} for rid, r in (getattr(self.st, "radios", {}) or {}).items()
                if r.get("role") == "winlink"]

    def settings(self, body: dict) -> dict:
        c = self.cfg()
        if "radio" in body:
            if body["radio"] and body["radio"] not in {r["id"] for r in self.winlink_radios()}:
                raise ValueError("VARA runs only on a radio whose role is Winlink (Radios… → the radio → Role)")
            c["radio"] = body["radio"] or None
        if "kind" in body:
            if body["kind"] not in ("hf", "fm"):
                raise ValueError("VARA HF or VARA FM")
            c["kind"] = body["kind"]
        for k in ("cmd_port", "data_port"):
            if k in body:
                v = int(body[k])
                if not 1024 <= v <= 65535:
                    raise ValueError("a port is 1024 to 65535")
                c[k] = v
        if "host" in body:
            h = str(body["host"] or "").strip()
            if not re.fullmatch(r"[\w.-]{1,100}", h):
                raise ValueError("the VARA host is a name or address")
            c["host"] = h
        if "bw" in body:
            if body["bw"] not in (None, "", 500, 2300, 2750):
                raise ValueError("VARA HF bandwidth is 500, 2300 or 2750 Hz")
            c["bw"] = body["bw"] or None
        if "enabled" in body:
            c["enabled"] = bool(body["enabled"])
            if c["enabled"] and not c["radio"]:
                ws = self.winlink_radios()
                if len(ws) != 1:
                    raise ValueError("choose the Winlink radio VARA is connected to")
                c["radio"] = ws[0]["id"]
        self._save(c)
        self.restart()
        return self.view()

    # ----- transmit permission -----
    def tx_allowed(self) -> tuple[bool, str]:
        c = self.cfg()
        rid = c.get("radio")
        r = (getattr(self.st, "radios", {}) or {}).get(rid)
        if not r or r.get("role") != "winlink":
            return False, "the VARA radio is not a Winlink radio"
        ok, why = self.st.ptt.allowed(rid)
        if not ok:
            return False, why
        agent = getattr(self.st, "agent", None)
        sender = getattr(agent, "sender", None)
        if not (sender and sender.present()):
            return False, "you are not at the dashboard (VARA transmits only with you here)"
        cls = ((getattr(agent, "cfg", None) or {}).get("license_class") or "").lower() or None
        if not cls:
            return False, "set your license class (Settings → Station agent)"
        f = r.get("freq_mhz")
        if not f:
            return False, "set the radio's frequency so its privileges can be checked"
        chk = bandplan.check(f, "VARA", cls)
        if chk["ok"] is not True:
            return False, chk["why"] or "no data privileges there"
        return True, ""

    # ----- the modem client -----
    def restart(self):
        with self.lock:
            old, self.vara = self.vara, None
        if old:
            try:
                old.stop()
            except Exception:  # noqa: BLE001
                pass
        c = self.cfg()
        if not c["enabled"] or c["handed_off"] or not c["radio"]:
            self._publish("status")
            return
        mk = self.factory
        if mk is None:
            from .vara import Vara as mk
        try:
            v = mk(data_dir=self.st.data, mycall=getattr(self.st, "me", ""), kind=c["kind"], host=c["host"],
                   cmd_port=c["cmd_port"], data_port=c["data_port"], tx_allowed=self.tx_allowed,
                   bw=c["bw"] if c["kind"] == "hf" else None, on_event=self._event)
        except ValueError as e:
            self.last_event = {"name": "error", "error": str(e)}
            self._publish("error")
            return
        with self.lock:
            self.vara = v
        v.start()
        self._ensure_checker()

    def _ensure_checker(self):
        if self._checker and self._checker.is_alive():
            return
        self._checker = threading.Thread(target=self._check_loop, daemon=True, name="vara-check")
        self._checker.start()

    def _check_loop(self):
        while not self.stop_ev.wait(CHECK_S):
            self.check()

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
        self._publish("listen_off")
        return why

    def stop(self):
        self.stop_ev.set()
        if self.vara:
            try:
                self.vara.stop()
            except Exception:  # noqa: BLE001
                pass

    def _event(self, name: str, data: dict):
        if name in ("chat", "chat_sent", "file_received", "file_sent", "file_failed", "file_rejected", "connected",
                    "disconnected", "abort", "watchdog", "cq_heard", "handshake"):
            self.last_event = {"name": name, **{k: v for k, v in (data or {}).items() if isinstance(v, (str, int, float, bool, type(None)))}}
        self._publish(name)

    def _publish(self, name: str):
        try:
            self.st.publish("vara", {"event": name, "vara": self.view(transcript=False)})
        except Exception:  # noqa: BLE001
            pass

    # ----- the view -----
    def view(self, transcript: bool = True) -> dict:
        c = self.cfg()
        v = self.vara
        ok, why = self.tx_allowed() if c["radio"] else (False, "")
        out = {"cfg": c, "radios": self.winlink_radios(), "tx_ok": ok, "tx_why": why,
               "state": v.state() if v else None, "last": self.last_event,
               "express_running": self._express()}
        if transcript:
            out["transcript"] = self.transcript()
            out["inbox"] = self.inbox()
        return out

    def _express(self) -> bool:
        try:
            from .winlink import express_running
            return bool(express_running())
        except Exception:  # noqa: BLE001
            return False

    def transcript(self, n: int = 200) -> list[dict]:
        d = Path(self.st.data) / "vara"
        out = []
        for p in sorted(d.glob("*.jsonl"))[-2:]:
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
        d = Path(self.st.data) / "vara" / "inbox"
        if not d.is_dir():
            return []
        return [{"name": p.name, "bytes": p.stat().st_size, "at": p.stat().st_mtime}
                for p in sorted(d.iterdir(), key=lambda p: -p.stat().st_mtime) if p.is_file()][:100]

    def inbox_file(self, name: str) -> Path | None:
        if not re.fullmatch(r"[\w .@()+,=-]{1,200}", name or "") or name.startswith("."):
            return None
        p = Path(self.st.data) / "vara" / "inbox" / name
        return p if p.is_file() else None

    # ----- the operator's actions -----
    def _v(self):
        if not self.cfg()["enabled"]:
            raise ValueError("switch VARA on first")
        if self.cfg()["handed_off"]:
            raise ValueError("VARA is with Winlink Express: take it back first")
        if not self.vara:
            raise ValueError("VARA is not running")
        return self.vara

    def act(self, what: str, body: dict) -> dict:
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
            elif what == "handoff":                  # let go of VARA so Winlink Express can use it
                c = self.cfg()
                c["handed_off"] = True
                self._save(c)
                self.restart()
            elif what == "takeback":
                if self._express():
                    raise ValueError("Winlink Express is still open: close it first")
                c = self.cfg()
                c["handed_off"] = False
                self._save(c)
                self.restart()
            else:
                raise ValueError("unknown VARA action")
        except VaraRefused as e:
            raise ValueError(str(e)) from None
        return self.view()
