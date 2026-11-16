"""The consolidated band plan for the station's area (dashboard header -> Band plan; owner 2026-11-15: "I need the band
plans to be ingested and shown in a consolidated and reconciled table").

Sources, highest say first for what a frequency is FOR:
  coordinator  the state frequency coordinator's band plan (ingested from its document, localplans.py)
  local        ARES / RACES / ICS-205 / club plans and the operator's own plan files (ingested the same way)
  kept         the plan channels the operator confirmed (Nets -> Plans)
  arrl         the ARRL band plan (built in, bandplan.PLAN)
  fcc          47 CFR 97.301 / 97.305 sub-bands (built in): what is LEGAL, by license class, never outranked

Reconciling:
* Every range from every source is cut at every edge, so each row is a stretch where the same sources say the same
  things. Its "use" is the highest-ranked source's words; every source's words are kept beside it.
* Two sources DISAGREE when their words fall in different kinds of use (repeater outputs vs simplex, weak signal vs
  FM, beacons, satellites...). Words with no recognisable kind never disagree.
* A channel (one frequency) disagrees with the range it sits in the same way, and with another channel on the same
  frequency given a different use. A kept channel outside the operator's privileges, or its repeater input outside
  them, is flagged too.
* Privileges per row: the kinds (phone, data, CW) the operator's class may use across the whole row.
"""
from __future__ import annotations

import re

from . import bandplan

RANK = {"coordinator": 0, "local": 1, "kept": 2, "arrl": 3, "fcc": 4}
AUTH = {"coordinator": "State coordinator", "local": "Local plan", "kept": "Your channel", "arrl": "ARRL band plan",
        "fcc": "FCC rules"}
CATS = [("beacon", r"beacon"), ("satellite", r"satellit|\bsat\b"), ("repeater_in", r"\binputs?\b"),
        ("repeater_out", r"\boutputs?\b|repeater(?!.*input)"), ("simplex", r"simplex|calling|tactical"),
        ("data", r"data|packet|digital|aprs|ft8|ft4|rtty|winlink|psk|vara|dstar|d-star|dmr|fusion|c4fm"),
        ("weak", r"weak|ssb|\bcw\b|eme|meteor|moonbounce|sideband"), ("atv", r"\batv\b|television|video"),
        ("link", r"\blink|control|auxiliary|remote base"), ("experimental", r"experiment|test")]
EPS = 0.00049


def cats(text: str | None) -> set[str]:
    t = (text or "").lower()
    return {k for k, rx in CATS if re.search(rx, t)}


def differ(a: str | None, b: str | None) -> bool:
    ca, cb = cats(a), cats(b)
    return bool(ca and cb and not (ca & cb))


def _fcc_segments() -> list[tuple[float, float, str]]:
    """The widest (Extra) sub-bands by kind: 'CW and data' and 'Phone and image' stretches."""
    out = []
    ex = bandplan.ALLOC["extra"]
    for a, b in ex["cw"]:
        phone = [(x, y) for x, y in ex["phone"] if x < b and y > a]
        cuts = sorted({a, b, *[max(a, x) for x, _ in phone], *[min(b, y) for _, y in phone]})
        for x, y in zip(cuts, cuts[1:]):
            if y - x <= EPS:
                continue
            ph = any(px <= x + EPS and y - EPS <= py for px, py in phone)
            out.append((x, y, "phone, image, CW and data" if ph else "CW and data (no phone)"))
    return out


def _privs(a: float, b: float, cls: str | None) -> dict | None:
    if not cls or cls not in bandplan.ALLOC:
        return None
    if 5.3 <= a <= 5.41:                         # 60 m: channels only
        return {k: cls != "technician" for k in bandplan.KINDS}
    return {k: any(x <= a + EPS and b - EPS <= y for x, y in bandplan.ALLOC[cls][k]) for k in bandplan.KINDS}


def build(cls: str | None, sources: list[dict], kept: list[dict] | None = None) -> dict:
    """sources: [{"id", "name", "authority": coordinator | local, "segments": [{"from_mhz", "to_mhz", "use"}],
    "frequencies": [channel dicts]}]. kept: the confirmed plan channels. -> {"bands": [...], "sources": [...]}"""
    cls = (cls or "").lower() or None
    srcs = [{"id": "fcc", "name": "FCC rules (97.301, 97.305)", "authority": "fcc"},
            {"id": "arrl", "name": "ARRL band plan", "authority": "arrl"}]
    ranges, points = [], []
    for a, b, w in _fcc_segments():
        ranges.append((a, b, "fcc", "fcc", w))
    for a, b, w in bandplan.PLAN:
        (ranges if b - a > EPS else points).append((a, b, "arrl", "arrl", w) if b - a > EPS else
                                                   {"freq": a, "src": "arrl", "auth": "arrl", "use": w})
    for s in sources:
        auth = s.get("authority") if s.get("authority") in ("coordinator", "local") else "local"
        srcs.append({"id": s["id"], "name": s["name"], "authority": auth, "url": s.get("url"),
                     "segments": len(s.get("segments") or []), "channels": len(s.get("frequencies") or [])})
        for g in s.get("segments") or []:
            try:
                a, b = float(g["from_mhz"]), float(g.get("to_mhz") or g["from_mhz"])
            except (KeyError, TypeError, ValueError):
                continue
            a, b = min(a, b), max(a, b)
            if not bandplan.band(a) or not bandplan.band(b):
                continue
            use = " ".join(str(g.get("use") or "").split())[:120]
            if b - a > EPS:
                ranges.append((a, b, s["id"], auth, use))
            else:
                points.append({"freq": a, "src": s["id"], "auth": auth, "use": use})
        for f in s.get("frequencies") or []:
            points.append({"freq": f["freq_mhz"], "src": s["id"], "auth": auth, "use": f.get("use"), "ch": f})
    if kept:
        srcs.append({"id": "kept", "name": "Your plan channels", "authority": "kept", "channels": len(kept)})
        for k in kept:
            points.append({"freq": k["freq_mhz"], "src": "kept", "auth": "kept", "use": k.get("use"), "ch": k})
    names = {s["id"]: s["name"] for s in srcs}

    bands = []
    for bname, lo, hi in bandplan.BANDS:
        mine = [r for r in ranges if r[0] < hi + EPS and r[1] > lo - EPS]
        cls_edges = {x for c in bandplan.CLASSES for k in bandplan.KINDS for seg in bandplan.ALLOC[c][k] for x in seg
                     if lo < x < hi and not 5.3 <= x <= 5.41}         # where any class's privileges change
        edges = sorted({max(lo, min(hi, x)) for r in mine for x in r[:2]} | {lo, hi} | cls_edges)
        rows = []
        for a, b in zip(edges, edges[1:]):
            if b - a <= EPS:
                continue
            says = sorted({(r[3], r[2], r[4]) for r in mine if r[0] <= a + EPS and b - EPS <= r[1]},
                          key=lambda x: (RANK[x[0]], x[1]))
            pv = _privs(a, b, cls)
            if rows and rows[-1]["_says"] == says and rows[-1]["_pv"] == pv and abs(rows[-1]["to"] - a) <= EPS:
                rows[-1]["to"] = b
                continue
            rows.append({"type": "range", "from": a, "to": b, "_says": says, "_pv": pv})
        out_rows = []
        for r in rows:
            says = r.pop("_says")
            r.pop("_pv")
            st = [{"source": names.get(sid, sid), "authority": au, "use": w} for au, sid, w in says]
            plan = [x for x in st if x["authority"] != "fcc"]
            top = plan[0] if plan else (st[0] if st else None)
            flags = []
            for i, x in enumerate(plan):
                for y in plan[i + 1:]:
                    if x["source"] != y["source"] and differ(x["use"], y["use"]):
                        flags.append(f"{x['source']} says “{x['use']}”; {y['source']} says “{y['use']}”")
            r.update(use=top["use"] if top else None, by=top["source"] if top else None,
                     authority=top["authority"] if top else None, statements=st, flags=flags,
                     privileges=_privs(r["from"], r["to"], cls))
            out_rows.append(r)
        # channels: one row per frequency, every source's words kept
        chans = {}
        for p in points:
            f = float(p["freq"])
            if not (lo - EPS <= f <= hi + EPS):
                continue
            key = round(f, 4)
            chans.setdefault(key, []).append(p)
        for f, ps in sorted(chans.items()):
            ps.sort(key=lambda p: RANK[p["auth"]])
            top = ps[0]
            ch = next((p["ch"] for p in ps if p.get("ch")), None) or {}
            st = [{"source": names.get(p["src"], p["src"]), "authority": p["auth"], "use": p["use"]} for p in ps]
            flags = []
            for i, x in enumerate(st):
                for y in st[i + 1:]:
                    if x["source"] != y["source"] and x["use"] and y["use"] and differ(x["use"], y["use"]):
                        flags.append(f"{x['source']} says “{x['use']}”; {y['source']} says “{y['use']}”")
            inside = next((r for r in out_rows if r["from"] - EPS <= f <= r["to"] + EPS and r["authority"] != "fcc"),
                          None)
            if inside and top["auth"] != "arrl" and top["use"] and differ(top["use"], inside["use"]) and not cats(top["use"]) & {"beacon"}:
                flags.append(f"sits in {inside['from']:g}–{inside['to']:g}, which {inside['by']} sets aside for "
                             f"“{inside['use']}”")
            priv = None
            if cls:
                mode = ch.get("mode") or ("FM" if f > 30 else "USB")
                c = bandplan.check(f, mode, cls)
                priv = c["ok"]
                if c["ok"] is False and any(p["auth"] in ("kept", "coordinator", "local") for p in ps):
                    flags.append(f"outside your privileges: {c['why']}")
                off = ch.get("offset_mhz")
                if off:
                    ci = bandplan.privileges(f + off, bandplan.kind_of(mode), cls)
                    if ci[0] is False:
                        flags.append(f"its input {f + off:.4f} is outside your privileges")
            out_rows.append({"type": "channel", "from": f, "to": f, "use": top["use"], "by": names.get(top["src"]),
                             "authority": top["auth"], "statements": st, "flags": flags, "privileges": priv,
                             "kept": any(p["auth"] == "kept" for p in ps), "mode": ch.get("mode"),
                             "offset_mhz": ch.get("offset_mhz"), "tone_hz": ch.get("tone_hz"),
                             "priority": ch.get("priority"), "org": ch.get("org"), "source_url": ch.get("source_url")})
        out_rows.sort(key=lambda r: (r["from"], r["type"] == "channel"))
        bands.append({"band": bname, "from": lo, "to": hi, "rows": out_rows,
                      "flags": sum(len(r["flags"]) for r in out_rows),
                      "local": any(s["authority"] in ("coordinator", "local", "kept") for r in out_rows
                                   for s in r["statements"])})
    return {"license_class": cls, "bands": bands, "sources": srcs}


def lookup(table: dict, freq_mhz) -> dict | None:
    """The consolidated word on one frequency: the channel row if there is one, else the narrowest range row."""
    if not freq_mhz or not table:
        return None
    f = float(freq_mhz)
    for b in table["bands"]:
        if b["from"] - EPS <= f <= b["to"] + EPS:
            ch = next((r for r in b["rows"] if r["type"] == "channel" and abs(r["from"] - f) <= 0.0025), None)
            rng = [r for r in b["rows"] if r["type"] == "range" and r["from"] - EPS <= f <= r["to"] + EPS]
            return {"band": b["band"], "channel": ch, "range": rng[0] if rng else None}
    return None
