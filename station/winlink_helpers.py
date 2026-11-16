"""Winlink helpers: put the Winlink window's messages in the Outbox of ANOTHER Windows PC on the network
(owner 2026-11-15: "if I load the dashboard on a different Windows 11 computer running Winlink, could it put the
Winlink messages in the Winlink outbox folder on that computer?").

A web page cannot write into folders on the computer showing it, so a small helper program runs on that PC
(station/winlink_helper.py, installed with install/windows/install-winlink-helper.cmd). It asks this station every
few seconds whether there is anything for it (the station never connects to it, and the browser never talks to it:
no firewall rule on that PC, no browser permission prompts). The Winlink window lists the helpers that asked
recently; the one on the computer the browser runs on (same network address) comes first as "this computer".
The helper builds each message from ITS Winlink Express templates and writes it into ITS Outbox, with the same
code and the same rule as the station's own Outbox (station/winlink.py: Winlink Express must be closed), then
reports what it wrote. Jobs live in memory only: a message is never re-sent after a restart.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime

ONLINE_S = 20          # a helper that asked within this long is online (it asks every 3 s)
TAKE_S = 30            # a job a helper took but did not answer within this long: it is offered again ...
JOB_TIMEOUT_S = 120    # ... and given up after this long (the window says so)
KEEP_JOBS = 50


def _id_ok(s) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{32}", str(s or "")))


class Helpers:
    def __init__(self, st):
        self.st = st
        self.lock = threading.Lock()
        self.seen: dict[str, dict] = {}
        self.jobs: OrderedDict[str, dict] = OrderedDict()

    # ----- the helper's side -----
    def poll(self, body: dict, ip: str) -> dict:
        """POST /api/winlink/helper/poll from a helper: what it is and what it sees; -> the jobs waiting for it."""
        hid = str(body.get("id") or "")
        if not _id_ok(hid):
            raise ValueError("a helper id is 32 hex characters")
        now = time.time()
        installs = []
        for i in body.get("installs") or []:
            if isinstance(i, dict):
                installs.append({"path": str(i.get("path") or "")[:260],
                                 "accounts": [str(a)[:20] for a in (i.get("accounts") or [])][:20],
                                 "active": str(i.get("active") or "")[:20] or None, "templates": bool(i.get("templates"))})
        with self.lock:
            new = hid not in self.seen
            self.seen[hid] = {"id": hid, "name": str(body.get("name") or "Windows PC")[:40], "ip": ip, "at": now,
                              "installs": installs[:5], "express_running": bool(body.get("express_running")),
                              "version": str(body.get("version") or "")[:20]}
            out = []
            for jid, j in self.jobs.items():
                if j["helper"] != hid or j["state"] not in ("queued", "taken"):
                    continue
                if j["state"] == "taken" and now - j["taken_at"] < TAKE_S:
                    continue
                j["state"], j["taken_at"] = "taken", now
                out.append({"job": jid, "to": j["to"], "drafts": j["drafts"], "grid": j["grid"],
                            "install": j["install"], "account": j["account"]})
        if new:
            print(f"{datetime.now():%H:%M:%S} winlink helper: {self.seen[hid]['name']} ({ip}) is asking for messages",
                  flush=True)
        return {"jobs": out, "station": self.st.me}

    def done(self, body: dict) -> dict:
        """POST /api/winlink/helper/done: {id, job, ok, result | error}."""
        hid, jid = str(body.get("id") or ""), str(body.get("job") or "")
        with self.lock:
            j = self.jobs.get(jid)
            if not j or j["helper"] != hid:
                raise LookupError("no such job for this helper")
            if j["state"] in ("written", "error"):
                return {"ok": True}
            name = (self.seen.get(hid) or {}).get("name") or "the other PC"
            if body.get("ok"):
                r = body.get("result") or {}
                j.update(state="written", result={"written": [{"mid": str(w.get("mid"))[:20], "subject": str(w.get("subject"))[:200],
                                                               "to": [str(c)[:12] for c in (w.get("to") or [])][:200]}
                                                              for w in (r.get("written") or []) if isinstance(w, dict)],
                                                  "account": str(r.get("account") or "")[:20],
                                                  "install": str(r.get("install") or "")[:260], "pc": name})
            else:
                j.update(state="error", error=str(body.get("error") or "not written")[:400])
            j["done_at"] = time.time()
            job = dict(j)
        if job["state"] == "written":
            print(f"{datetime.now():%H:%M:%S} winlink: {len(job['result']['written'])} message(s) to "
                  f"{', '.join(job['to'])} in the {job['result']['account']} Outbox on {name}", flush=True)
            if job.get("radio") and job.get("start"):
                try:
                    self.st.history.note_winlink(job["radio"], job["start"], [d.get("form") for d in job["drafts"]],
                                                 job["to"])
                except Exception as e:  # noqa: BLE001
                    print(f"history: {type(e).__name__}: {e}", flush=True)
        else:
            print(f"{datetime.now():%H:%M:%S} winlink: NOT written on {name} ({len(job['drafts'])} message(s) to "
                  f"{', '.join(job['to'])}): {job['error']}", flush=True)
        try:
            self.st.bus.publish("winlink", {"job": self.job(jid)})
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True}

    # ----- the dashboard's side -----
    def list(self, ip: str | None = None) -> list[dict]:
        now = time.time()
        with self.lock:
            hs = [dict(h) for h in self.seen.values()]
        out = []
        for h in hs:
            if now - h["at"] > 24 * 3600:
                continue
            out.append(h | {"online": now - h["at"] <= ONLINE_S, "here": bool(ip) and h["ip"] == ip,
                            "ago_s": round(now - h["at"])})
        out.sort(key=lambda h: (not h["here"], not h["online"], h["name"].lower()))
        return out

    def queue(self, hid: str, to: list[str], drafts: list[dict], grid=None, install=None, account=None,
              radio=None, start=None) -> dict:
        with self.lock:
            h = self.seen.get(hid)
            if not h:
                raise ValueError("that computer's Winlink helper has not been seen: is it installed and running there?")
            if time.time() - h["at"] > ONLINE_S:
                raise ValueError(f"the Winlink helper on {h['name']} is not answering: is that PC on, and the helper "
                                 "running (it starts when you sign in)?")
            jid = uuid.uuid4().hex
            self.jobs[jid] = {"job": jid, "helper": hid, "to": to, "drafts": drafts, "grid": grid, "install": install,
                              "account": account, "radio": radio, "start": start, "state": "queued",
                              "at": time.time(), "taken_at": 0}
            while len(self.jobs) > KEEP_JOBS:
                self.jobs.popitem(last=False)
        print(f"{datetime.now():%H:%M:%S} winlink: {len(drafts)} message(s) to {', '.join(to)} waiting for the helper "
              f"on {h['name']}", flush=True)
        return {"job": jid, "state": "queued", "pc": h["name"]}

    def job(self, jid: str) -> dict:
        with self.lock:
            j = self.jobs.get(jid)
            if not j:
                raise LookupError("no such job")
            if j["state"] in ("queued", "taken") and time.time() - j["at"] > JOB_TIMEOUT_S:
                j.update(state="error", error="the helper did not answer in time: nothing is known to be written. "
                         "Check that PC's Winlink Express Outbox before trying again.", done_at=time.time())
            name = (self.seen.get(j["helper"]) or {}).get("name") or "the other PC"
            return {"job": jid, "state": j["state"], "pc": name, "result": j.get("result"), "error": j.get("error")}
