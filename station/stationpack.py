"""A station pack: what one station knows about its area, sent to another over VARA and installed there after a
review (owner 2026-11-24: "help an operator update their band plan and schedule from everything I have on my station
... The operator has an option to install the band plan additions and net schedule on their station").

One file, `<CALL>-station-pack.hspack` (gzip-compressed JSON, schema hamsidekick-pack/1), with any of:
* plans: the local plans this station has read into its band plan (localplans.json "ingested"): each plan's title,
  kind, organisation, source link, authority, its band segments and its channels, as read. The other station gets
  them without reading anything itself (no xAI key, no internet). Winlink gateway lists are never sent (each station
  has its own Express list) and the operator's own files (members-only plans added by hand) only when ticked;
* kept: the plan channels the operator kept;
* adhoc: the reserved ad hoc channels (adhoc.export);
* nets: the net schedule (netshare.export: no check-in lists, alerts or radios).
Plus who sent it, when, and the sender's 4-character grid square (the receiving station says so when it is not its own).

A received pack is only ever read as data: every plan, segment and channel goes through the same cleaning as a plan
read here (localplans._clean_segments / _clean_freq), every net through schedule.validate (portable). review() says what
installing would change, item by item; install() applies what the operator ticked: never deletes, backs up first.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from . import localplans as LP
from . import netshare, portable

SCHEMA = "hamsidekick-pack/1"
SUFFIX = ".hspack"
PARTS = ("plans", "kept", "adhoc", "nets")
MAX_BYTES = 2 * 1024 * 1024          # unpacked
MAX_PLANS, MAX_CHANNELS, MAX_SEGMENTS = 40, 400, 400


def _call(st) -> str:
    op = (getattr(st, "_saved", lambda: {})() or {}).get("operator") or {}
    return str(op.get("callsign") or getattr(st, "me", "") or "").upper().strip()


def _grid4(st) -> str:
    op = (getattr(st, "_saved", lambda: {})() or {}).get("operator") or {}
    g = re.sub(r"\s+", "", str(op.get("grid") or ""))[:4]
    return g.upper() if re.fullmatch(r"[A-Ra-r]{2}\d{2}", g) else ""


def _shareable(key: str, e: dict, own_files: bool) -> bool:
    if e.get("excluded") or e.get("error") or key in LP.EXPRESS_KEYS or key.startswith(("search:", "express:")):
        return False
    return own_files or not key.startswith("file:")


def available(st) -> dict:
    """What this station could send, for the Share… panel: counts per part."""
    d = LP._load(st)
    ing = d.get("ingested") or {}
    plans = [{"key": k, "title": e.get("title"), "channels": len(e.get("frequencies") or []),
              "segments": len(e.get("segments") or []), "own_file": k.startswith("file:")}
             for k, e in ing.items() if _shareable(k, e, True)]
    return {"plans": plans, "kept": len(d.get("kept") or []), "adhoc": len(d.get("adhoc") or []),
            "nets": len(st.cfg.get("schedule") or []), "call": _call(st)}


def build(st, parts=PARTS, own_files: bool = False) -> dict:
    parts = [p for p in parts if p in PARTS]
    d = LP._load(st)
    call = _call(st)
    out = {"schema": SCHEMA, "from": call or None, "made": datetime.now().isoformat(timespec="seconds"),
           "area": _grid4(st) or None}
    if "plans" in parts:
        out["plans"] = [{"key": k, "title": e.get("title"), "kind": e.get("kind"), "org": e.get("org"),
                         "date": e.get("date"), "url": e.get("url") if LP._url_ok(e.get("url")) else None,
                         "authority": e.get("authority") or "local", "read_at": e.get("at"),
                         "segments": e.get("segments") or [], "frequencies": e.get("frequencies") or []}
                        for k, e in (d.get("ingested") or {}).items() if _shareable(k, e, own_files)][:MAX_PLANS]
    if "kept" in parts:
        out["kept"] = [{k: f.get(k) for k in ("freq_mhz", "mode", "offset_mhz", "tone_hz", "kind", "use", "priority",
                                               "org", "source_url", "net")} for f in d.get("kept") or []]
    if "adhoc" in parts:
        from . import adhoc
        out["adhoc"] = adhoc.export(LP.Plans._adhoc_rows(d), call or None)
    if "nets" in parts:
        n = netshare.export(st, call)
        out["nets"] = {"radios": n["radios"], "nets": n["nets"]}
    return out


def dumps(doc: dict) -> bytes:
    return gzip.compress(json.dumps(doc, separators=(",", ":")).encode("utf-8"), 9)


def name_for(doc: dict) -> str:
    return f"{re.sub(r'[^A-Z0-9-]', '', str(doc.get('from') or 'STATION').upper()) or 'STATION'}-station-pack{SUFFIX}"


def counts(doc: dict) -> dict:
    return {"plans": len(doc.get("plans") or []),
            "channels": sum(len(p.get("frequencies") or []) for p in doc.get("plans") or []),
            "segments": sum(len(p.get("segments") or []) for p in doc.get("plans") or []),
            "kept": len(doc.get("kept") or []), "adhoc": len((doc.get("adhoc") or {}).get("channels") or []),
            "nets": len((doc.get("nets") or {}).get("nets") or [])}


# ----- receiving: read as data, cleaned -----
def _s(x, n=200) -> str | None:
    t = " ".join(str(x or "").split())[:n]
    return t or None


def _freqs(raw, title, url) -> list[dict]:
    out = []
    for f in (raw if isinstance(raw, list) else [])[:MAX_CHANNELS]:
        if not isinstance(f, dict):
            continue
        g, _ = LP._clean_freq(dict(f, source_url=f.get("source_url") if LP._url_ok(f.get("source_url")) else ""),
                              set(), require_source=False)
        if g:
            g["source_url"], g["source_opened"], g["source_doc"] = (url or g.get("source_url")), bool(url), title
            out.append(g)
    return LP.dedupe(out)


def parse(data: bytes) -> dict:
    """A received pack (gzip or plain JSON), cleaned. Raises ValueError when it is not one."""
    try:
        raw = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
        if len(raw) > MAX_BYTES:
            raise ValueError
        doc = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, EOFError, UnicodeDecodeError):
        raise ValueError("that is not a HAM Sidekick station pack") from None
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ValueError("that is not a HAM Sidekick station pack")
    frm = re.sub(r"[^A-Z0-9/-]", "", str(doc.get("from") or "").upper())[:12] or None
    area = str(doc.get("area") or "").upper()
    out = {"schema": SCHEMA, "from": frm, "made": _s(doc.get("made"), 25),
           "area": area if re.fullmatch(r"[A-R]{2}\d{2}", area) else None}
    if isinstance(doc.get("plans"), list):
        plans = []
        for p in doc["plans"][:MAX_PLANS]:
            if not isinstance(p, dict) or not _s(p.get("title")):
                continue
            title, url = _s(p.get("title"), 160), (p.get("url") if LP._url_ok(p.get("url")) else None)
            try:
                read_at = float(p.get("read_at")) if p.get("read_at") is not None else None
            except (TypeError, ValueError):
                read_at = None
            plans.append({"title": title, "kind": _s(p.get("kind"), 30) if p.get("kind") in LP.DOC_KINDS else "comm_plan",
                          "org": _s(p.get("org"), 80), "date": _s(p.get("date"), 30), "url": url,
                          "authority": p.get("authority") if p.get("authority") in ("coordinator", "local") else "local",
                          "read_at": read_at, "segments": LP._clean_segments((p.get("segments") or [])[:MAX_SEGMENTS]),
                          "frequencies": _freqs(p.get("frequencies"), title, url)})
        out["plans"] = plans
    if isinstance(doc.get("kept"), list):
        out["kept"] = _freqs(doc["kept"], None, None)
        for f in out["kept"]:
            f["source_doc"] = None
    if isinstance(doc.get("adhoc"), dict):
        out["adhoc"] = doc["adhoc"]                       # adhoc.import_ checks and cleans every channel
    if isinstance(doc.get("nets"), dict) and isinstance(doc["nets"].get("nets"), list):
        out["nets"] = {"radios": [r for r in doc["nets"].get("radios") or [] if isinstance(r, dict)][:20],
                       "nets": [n for n in doc["nets"]["nets"] if isinstance(n, dict)][:200]}
    return out


def read(path) -> dict:
    try:
        return parse(Path(path).read_bytes())
    except OSError:
        raise ValueError("that file is no longer in the VARA inbox") from None


def summary(path) -> dict | None:
    """For the inbox row and the chat: who sent it and what is in it."""
    try:
        doc = read(path)
    except ValueError:
        return None
    return dict(counts(doc), **{"from": doc["from"], "area": doc["area"]})


def _plan_key(doc: dict, p: dict) -> str:
    if p.get("url"):
        return p["url"]
    return f"shared:{doc.get('from') or 'station'}:{hashlib.sha1(p['title'].encode()).hexdigest()[:10]}"


def _nets_doc(doc: dict, only=None) -> dict:
    nets = (doc.get("nets") or {}).get("nets") or []
    if only is not None:
        nets = [n for i, n in enumerate(nets) if i in only]
    return {"schema": portable.SCHEMA, "radios": (doc.get("nets") or {}).get("radios") or [], "nets": nets,
            "identity_included": False}


def review(st, doc: dict) -> dict:
    """What installing would do, item by item, without doing it. Each item says whether it is new here, the same as
    what this station has, or different (and which reading is newer), and is ticked by default when it adds something."""
    d = LP._load(st)
    ing = d.get("ingested") or {}
    mine_keys = {LP.same_key(f) for e in ing.values() if not e.get("excluded") and not e.get("error")
                 for f in e.get("frequencies") or []} | {LP.same_key(f) for f in d.get("kept") or []}
    out = {"from": doc.get("from"), "made": doc.get("made"), "area": doc.get("area"), "my_area": _grid4(st) or None}
    out["other_area"] = bool(doc.get("area") and out["my_area"] and doc["area"] != out["my_area"])
    plans = []
    for i, p in enumerate(doc.get("plans") or []):
        key = _plan_key(doc, p)
        have = ing.get(key)
        theirs = {LP.same_key(f) for f in p["frequencies"]}
        new_ch = len(theirs - mine_keys)
        it = {"i": i, "title": p["title"], "org": p.get("org"), "kind": p.get("kind"), "url": p.get("url"),
              "authority": p.get("authority"), "channels": len(p["frequencies"]), "segments": len(p["segments"]),
              "new_channels": new_ch, "read_at": p.get("read_at")}
        if have and not have.get("error"):
            mine = {LP.same_key(f) for f in have.get("frequencies") or []}
            same = mine == theirs and len(have.get("segments") or []) == len(p["segments"])
            it.update(status="same" if same else "differs", have_at=have.get("at"),
                      excluded_here=bool(have.get("excluded")),
                      tick=not same and (p.get("read_at") or 0) > (have.get("at") or 0))
            if not same:
                it["only_theirs"], it["only_mine"] = len(theirs - mine), len(mine - theirs)
        else:
            it.update(status="new", tick=True)
        plans.append(it)
    out["plans"] = plans
    if doc.get("kept") is not None:
        mine = {LP.same_key(f) for f in d.get("kept") or []}
        new = [f for f in doc["kept"] if LP.same_key(f) not in mine]
        out["kept"] = {"total": len(doc["kept"]), "new": len(new),
                       "names": [f"{f['freq_mhz']:g} {f.get('use') or ''}".strip()[:40] for f in new][:20], "tick": bool(new)}
    if doc.get("adhoc") is not None:
        from . import adhoc
        try:
            _, rep = adhoc.import_(LP.Plans._adhoc_rows(d), doc["adhoc"])
            out["adhoc"] = {"total": len(doc["adhoc"].get("channels") or []), "new": rep["added"],
                            "renamed": rep["renamed"], "already": rep["already"], "skipped": rep["skipped"][:5],
                            "tick": bool(rep["added"] or rep["renamed"])}
        except ValueError as e:
            out["adhoc"] = {"error": str(e)}
    if doc.get("nets") is not None:
        nets = []
        for i, n in enumerate(doc["nets"]["nets"]):
            p = portable._plan(st, _nets_doc(doc, {i}), None)
            st_ = "new" if p["add"] else "update" if p["update"] else "same" if p["same"] else "invalid"
            try:
                from . import recur
                when = recur.summary(n)
            except Exception:  # noqa: BLE001
                when = ""
            nets.append({"i": i, "name": _s(n.get("name"), 60), "when": when, "status": st_,
                         "why": p["bad"][0]["why"] if p["bad"] else None, "tick": st_ in ("new", "update")})
        out["nets"] = nets
    return out


def install(st, doc: dict, choice: dict) -> dict:
    """Apply what the operator ticked. choice: {"plans": [i], "kept": bool, "adhoc": bool, "nets": [i]}."""
    choice = choice if isinstance(choice, dict) else {}
    want_plans = {int(i) for i in choice.get("plans") or [] if str(i).isdigit()}
    want_nets = {int(i) for i in choice.get("nets") or [] if str(i).isdigit()}
    frm = doc.get("from") or "another station"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bdir = Path(st.data) / "settings_backups" / (stamp + "-pack")
    lp_path = LP._path(st)
    if lp_path.exists() and (want_plans or choice.get("kept") or choice.get("adhoc")):
        bdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lp_path, bdir / lp_path.name)
    res = {"from": doc.get("from"), "plans": 0, "channels": 0, "kept": 0, "adhoc": None, "nets": None,
           "backup": None}
    plans = _plans(st)
    if want_plans or choice.get("kept"):
        with plans.lock:
            d = LP._load(st)
            ing = d.setdefault("ingested", {})
            for i, p in enumerate(doc.get("plans") or []):
                if i not in want_plans:
                    continue
                key = _plan_key(doc, p)
                ing[key] = {"at": p.get("read_at") or time.time(), "title": p["title"], "kind": p.get("kind"),
                            "org": p.get("org"), "date": p.get("date"), "url": p.get("url") or key,
                            "authority": p.get("authority") or "local", "excluded": False,
                            "segments": copy.deepcopy(p["segments"]), "frequencies": copy.deepcopy(p["frequencies"]),
                            "via": frm, "via_at": time.time()}
                res["plans"] += 1
                res["channels"] += len(p["frequencies"])
            if choice.get("kept") and doc.get("kept"):
                kept = list(d.get("kept") or [])
                have = {LP.same_key(k) for k in kept}
                for f in doc["kept"]:
                    if LP.same_key(f) not in have:
                        kept.append(dict(f, kept_at=time.time(), via=frm))
                        have.add(LP.same_key(f))
                        res["kept"] += 1
                d["kept"] = sorted(kept, key=lambda k: (k["freq_mhz"] > 30, k["freq_mhz"]))
            LP._save(st, d)
    if choice.get("adhoc") and doc.get("adhoc"):
        res["adhoc"] = plans.adhoc_import(doc["adhoc"])["report"]
    if want_nets and doc.get("nets"):
        r = portable.apply(st, _nets_doc(doc, want_nets))
        res["nets"] = {k: r[k] for k in ("added", "updated", "unchanged", "invalid")}
        res["backup"] = r.get("backup")
    res["backup"] = str(bdir) if bdir.exists() else res["backup"]
    try:
        st.bus.publish("localplans", {"pack": doc.get("from")})
    except Exception:  # noqa: BLE001
        pass
    return res


def text(doc: dict) -> str:
    """What View shows: the pack in plain words."""
    c = counts(doc)
    out = [f"Station pack from {doc.get('from') or 'a station'} ({doc.get('made') or ''})"
           + (f", grid square {doc['area']}" if doc.get("area") else ""), ""]
    for p in doc.get("plans") or []:
        out.append(f"Plan: {p['title']}" + (f" ({p['org']})" if p.get("org") else "")
                   + f": {len(p['segments'])} ranges, {len(p['frequencies'])} channels" + (f" · {p['url']}" if p.get("url") else ""))
    if doc.get("kept") is not None:
        out.append(f"Kept channels: {c['kept']}")
    if doc.get("adhoc") is not None:
        out.append(f"Ad hoc channels: {c['adhoc']}")
    for n in (doc.get("nets") or {}).get("nets") or []:
        try:
            from . import recur
            out.append(f"Net: {n.get('name')}: {recur.summary(n)}")
        except Exception:  # noqa: BLE001
            out.append(f"Net: {n.get('name')}")
    return "\n".join(out)


def _plans(st):
    from .server import _plans as P
    return P(st)
