"""Control my other stations from here: the operator at one of their stations is the control operator of another
over the network (remote control, 47 CFR 97.3(a)(39), 97.109(c), 97.213).

Owner 2026-11-21: "I may have [Einstein] turned on at W9XYZ-7 ... and then as an operator I may be on W9XYZ-8 and want
to talk to W9XYZ-7 Einstein ... need sidekick to also work that way on radio voice."

* My other stations: their dashboard addresses (http://192.168.1.20:8091), typed in Settings on this station, kept
  in data/remote.json (never committed). Their state is read here server to server: the calls, each radio's
  frequency, Transmit switch and whether it is on the air, the VARA link, Einstein, the control operator.
* "Control it from here" (ticked in THIS browser, never stored on the server: it is the person at this keyboard):
  while this dashboard is in use, each heartbeat of presence also goes to that station, naming this one. That
  station then counts its control operator as present (sender.PRESENCE_S: 3 minutes without one and it stops
  transmitting by itself, 97.213(b)), so its VARA chat, its voice Send and Einstein's answers at the operator's call
  run as if the operator were at it. 97.213(a): the link is the LAN / Tailscale; (b): the 3-minute limit; the
  stop is here too: ⏹ Stop sends drops any transmission on that station and its VARA link at once, and Transmit
  off switches its transmitters off.
* What it does not do: hear for you. The control operator must be able to monitor the transmissions (the station's
  heard text shows here as it is transcribed); a voice QSO needs that station's audio, which this does not carry.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from pathlib import Path

TIMEOUT_S = 4
URL_RE = re.compile(r"https?://[\w.\-\[\]:]+(:\d{2,5})?/?")
MAX = 8


def brief(st) -> dict:
    """What another of the operator's stations shows about this one (GET /api/station/brief)."""
    radios = []
    ptt = {}
    try:
        ptt = st.ptt.view()
    except Exception:  # noqa: BLE001
        pass
    vara = {}
    try:
        for m in st.vara.data_radios():
            s = st.vara.modem(m["id"]).vara
            vs = s.state() if s else {}
            vara[m["id"]] = {"session": vs.get("session"), "peer": vs.get("peer"), "local": vs.get("local"),
                             "listening": vs.get("listening"), "calls": vs.get("calls") or []}
    except Exception:  # noqa: BLE001
        pass
    ein = {}
    try:
        ein = st.einstein.view().get("radios") or {}
    except Exception:  # noqa: BLE001
        pass
    for rid, r in (getattr(st, "radios", {}) or {}).items():
        p = ptt.get(rid) or {}
        e = ein.get(rid) or {}
        radios.append({"id": rid, "name": r.get("name") or rid, "role": r.get("role"), "freq_mhz": r.get("freq_mhz"),
                       "tx_on": p.get("enabled"), "on_air": p.get("on_air"), "vara": vara.get(rid),
                       "einstein": {"state": e.get("state"), "call": e.get("call"), "why": e.get("why")} if e else None})
    sender = getattr(getattr(st, "agent", None), "sender", None)
    rc = getattr(sender, "remote_from", None)
    calls = []
    try:
        calls = sorted({st.vara.modem(m["id"]).call() for m in st.vara.data_radios()})
    except Exception:  # noqa: BLE001
        pass
    return {"call": calls[0] if calls else str(getattr(st, "me", "") or ""), "calls": calls, "radios": radios,
            "present": bool(sender and sender.present()),
            "controlled_from": rc[0] if rc and time.monotonic() - rc[1] < 200 else None, "at": time.time()}


class Remote:
    def __init__(self, st, fetch=None):
        self.st = st
        self.path = Path(st.data) / "remote.json"
        self.fetch = fetch or _http
        self.lock = threading.Lock()

    def peers(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("peers") or []
        except (OSError, ValueError):
            return []

    def set_peers(self, urls) -> list[dict]:
        out = []
        for u in (urls or [])[:MAX]:
            u = str(u or "").strip().rstrip("/")
            if not u:
                continue
            if not u.startswith("http"):
                u = "http://" + u
            if ":" not in u.split("//", 1)[1]:
                u += ":8091"
            if not URL_RE.fullmatch(u + "/"):
                raise ValueError(f"not a dashboard address: {u} (e.g. http://192.168.1.20:8091)")
            out.append({"url": u})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"peers": out}, indent=1), encoding="utf-8")
        return out

    def _me(self) -> str:
        try:
            return brief(self.st)["call"]
        except Exception:  # noqa: BLE001
            return ""

    def status(self) -> list[dict]:
        res = [None] * len(self.peers())

        def one(i, p):
            try:
                res[i] = dict(self.fetch("GET", p["url"] + "/api/station/brief", None), url=p["url"], ok=True)
            except Exception as e:  # noqa: BLE001
                res[i] = {"url": p["url"], "ok": False, "why": f"cannot reach it ({type(e).__name__})"}
        ts = [threading.Thread(target=one, args=(i, p), daemon=True) for i, p in enumerate(self.peers())]
        for t in ts:
            t.start()
        for t in ts:
            t.join(TIMEOUT_S + 1)
        return [r or {"ok": False, "why": "no answer"} for r in res]

    def act(self, i: int, what: str) -> dict:
        ps = self.peers()
        if not 0 <= int(i) < len(ps):
            raise ValueError("no such station")
        u = ps[int(i)]["url"]
        if what == "presence":
            return self.fetch("POST", u + "/api/agent/presence", {"from": self._me()})
        if what == "stop":                               # every transmission there, and its VARA links
            out = self.fetch("POST", u + "/api/agent/stop/all", {"from": self._me()})
            try:
                b = self.fetch("GET", u + "/api/station/brief", None)
                for r in b.get("radios") or []:
                    if (r.get("vara") or {}).get("session") not in (None, "idle"):
                        self.fetch("POST", u + "/api/vara/abort", {"radio": r["id"]})
            except Exception:  # noqa: BLE001
                pass
            return out
        raise ValueError("unknown action")

    def presence_all(self, idx) -> dict:
        """One heartbeat to each station ticked in this browser."""
        out = {}
        for i in idx or []:
            try:
                self.act(int(i), "presence")
                out[str(i)] = True
            except Exception:  # noqa: BLE001
                out[str(i)] = False
        return out


def _http(method: str, url: str, body):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "User-Agent": "HAM-Sidekick-Station"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read() or b"{}")
