"""HAM Sidekick Winlink helper: runs on a Windows PC that has Winlink Express, so the station's Winlink window,
opened in a browser on that PC (or anywhere), can put its messages in THIS PC's Winlink Express Outbox.

    pythonw -m station.winlink_helper --station http://STATIONPC:8091      (install-winlink-helper.cmd sets it up)

It needs only Python's standard library and two files beside it (station/winlink.py, station/lzhuf.py). Every few
seconds it asks the station for messages meant for this PC (it never listens on the network itself), builds each
from this PC's Winlink Express templates, writes it into the Outbox with the station's own code (Winlink Express
must be closed, exactly as on the station; the Data files are backed up first) and tells the station what it wrote.
Settings and a log are kept in %LOCALAPPDATA%\\HAM Sidekick Winlink Helper.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from . import winlink

VERSION = "1"
POLL_S = 3
QUIET_POLL_S = 15       # the station is not answering: ask less often
LOG_MAX = 1_000_000


def home() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "HAM Sidekick Winlink Helper"


def log(msg: str, where: Path | None = None):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    p = (where or home()) / "helper.log"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > LOG_MAX:
            p.replace(p.with_suffix(".old.log"))
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def load_config(where: Path | None = None) -> dict:
    p = (where or home()) / "helper.json"
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    if not cfg.get("id"):
        cfg["id"] = uuid.uuid4().hex
        save_config(cfg, where)
    return cfg


def save_config(cfg: dict, where: Path | None = None):
    p = (where or home()) / "helper.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def pc_name() -> str:
    return os.environ.get("COMPUTERNAME") or platform.node() or socket.gethostname() or "Windows PC"


def installs(cfg: dict) -> list[dict]:
    return [winlink.describe(i) for i in winlink.find_installs([cfg["install"]] if cfg.get("install") else [])]


def write_job(job: dict, cfg: dict, running=None) -> dict:
    """Build the job's forms from this PC's templates and put them in this PC's Outbox (winlink.put_in_outbox)."""
    found = installs(cfg)
    if not found:
        raise FileNotFoundError("Winlink Express is not installed on this PC (no 'RMS Express.exe' found)")
    want = job.get("install") or cfg.get("install")
    inst = next((i for i in found if want and i["path"].lower() == str(want).lower()), found[0])
    account = job.get("account") or cfg.get("account")
    if account not in inst["accounts"]:
        account = inst["active"] if inst["active"] in inst["accounts"] else (inst["accounts"] or [None])[0]
    if not account:
        raise FileNotFoundError(f"no callsign account in {inst['path']}: open Winlink Express once and set it up")
    to = [str(c).upper() for c in job.get("to") or []]
    msgs = []
    for d in job.get("drafts") or []:
        if d.get("form") in winlink.TEMPLATES:
            t = winlink.load_template(inst["path"], d["form"])
            msgs.append(winlink.build(d["form"], t, d.get("values") or {}, account, to, grid=job.get("grid")))
    if not msgs or not to:
        raise ValueError("nothing to write")
    r = winlink.put_in_outbox(inst["path"], account, msgs, check_running=running)
    return {"written": r["written"], "account": r["account"], "install": r["install"]}


def _post(url: str, body: dict, timeout=10) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def once(cfg: dict, post=_post, running=None, where: Path | None = None) -> int:
    """One ask: report this PC, do the jobs waiting for it. -> jobs done."""
    base = cfg["station"].rstrip("/")
    running = running or winlink.express_running
    r = post(base + "/api/winlink/helper/poll", {"id": cfg["id"], "name": cfg.get("name") or pc_name(),
                                                 "version": VERSION, "installs": installs(cfg),
                                                 "express_running": running()})
    n = 0
    for job in r.get("jobs") or []:
        try:
            res = write_job(job, cfg, running)
            post(base + "/api/winlink/helper/done", {"id": cfg["id"], "job": job["job"], "ok": True, "result": res})
            log(f"wrote {len(res['written'])} message(s) to {', '.join(job.get('to') or [])} in the "
                f"{res['account']} Outbox", where)
        except Exception as e:  # noqa: BLE001 - the station shows the reason in its Winlink window
            log(f"NOT written ({len(job.get('drafts') or [])} message(s)): {e}", where)
            post(base + "/api/winlink/helper/done", {"id": cfg["id"], "job": job["job"], "ok": False, "error": str(e)})
        n += 1
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="Put HAM Sidekick Station's Winlink messages in this PC's Outbox")
    ap.add_argument("--station", help="the station's dashboard address, e.g. http://STATIONPC:8091 (remembered)")
    ap.add_argument("--name", help="this PC's name in the station's Winlink window (default: the computer name)")
    ap.add_argument("--install", help="the Winlink Express folder, when not the usual one (remembered)")
    ap.add_argument("--account", help="the callsign account to use (default: Winlink Express's own; remembered)")
    ap.add_argument("--once", action="store_true", help="ask once and exit (a check)")
    a = ap.parse_args(argv)
    cfg = load_config()
    for k in ("station", "name", "install", "account"):
        if getattr(a, k):
            cfg[k] = getattr(a, k)
    save_config(cfg)
    if not cfg.get("station"):
        sys.exit("give the station's address once: --station http://STATIONPC:8091")
    log(f"Winlink helper {VERSION} for {cfg['station']} as {cfg.get('name') or pc_name()}; Winlink Express in "
        f"{', '.join(i['path'] for i in installs(cfg)) or 'NOT FOUND'}")
    if a.once:
        n = once(cfg)
        print(f"the station answered; {n} job(s) done")
        return
    down = False
    while True:
        try:
            once(cfg)
            if down:
                log("the station answers again")
            down = False
            time.sleep(POLL_S)
        except (urllib.error.URLError, OSError, ValueError) as e:
            if not down:
                log(f"the station is not answering ({e}); asking again every {QUIET_POLL_S} s")
            down = True
            time.sleep(QUIET_POLL_S)


if __name__ == "__main__":
    main()
