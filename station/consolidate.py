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
        ("link", r"\blink|(?<!automatic-)(?<!automatic )control|auxiliary|remote base"), ("experimental", r"experiment|test")]
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


def _w(use) -> str:
    return " ".join(re.sub(r"[^0-9a-z.]+", " ", str(use or "").lower()).split()).strip(" .")


def _norm_url(u) -> str:
    u = re.sub(r"^https?://(www\.)?", "", str(u or "").strip().lower()).split("#")[0]
    return u.rstrip("/")


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
    said = set()                                  # (from, to, source, words): a source saying the same thing twice
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
            k = (round(a, 4), round(b, 4), s["id"], _w(use))
            if k in said:
                continue
            said.add(k)
            if b - a > EPS:
                ranges.append((a, b, s["id"], auth, use))
            else:
                points.append({"freq": a, "src": s["id"], "auth": auth, "use": use})
        for f in s.get("frequencies") or []:
            k = (round(float(f["freq_mhz"]), 4), round(float(f["freq_mhz"]), 4), s["id"], _w(f.get("use")))
            if k in said:
                continue
            said.add(k)
            points.append({"freq": f["freq_mhz"], "src": s["id"], "auth": auth, "use": f.get("use"), "ch": f,
                           "url": s.get("url"), "file": s["id"][5:] if str(s["id"]).startswith("file:") else None})
    if kept:
        srcs.append({"id": "kept", "name": "Your plan channels", "authority": "kept", "channels": len(kept)})
        for k in kept:
            f4 = round(float(k["freq_mhz"]), 4)
            # the same channel from the plan it was kept from: one statement, marked as yours
            same = next((p for p in points if round(float(p["freq"]), 4) == f4 and _w(p["use"]) == _w(k.get("use"))
                         and ((p.get("url") and _norm_url(p["url"]) == _norm_url(k.get("source_url")))
                              or (p.get("file") and p["file"] == k.get("file_id")))), None)
            if same:
                same["kept"] = True
                continue
            if any(p["src"] == "kept" and round(float(p["freq"]), 4) == f4 and _w(p["use"]) == _w(k.get("use"))
                   for p in points):
                continue
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
                             "kept": any(p["auth"] == "kept" or p.get("kept") for p in ps), "mode": ch.get("mode"),
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


# ----- open for ad hoc use (owner 2026-11-16: "I also need a way to see unplanned frequency ranges where I can do
# ad hoc VARA sessions and also Voice sessions") -----
# Never: beacons, satellites, repeater inputs / outputs, links, ATV, experimental. Voice also avoids the data segments
# (and on VHF/UHF the weak-signal SSB / CW stretches); VARA goes where a plan sets data aside or no plan names any use
# (unplanned), never HF CW / weak signal.
_NEVER = {"beacon", "satellite", "repeater_in", "repeater_out", "link", "atv", "experimental"}
_AVOID = {"voice": {"data"}, "data": {"weak", "simplex"}}
WIDTH = {"voice": 0.003, "data": 0.003}       # an SSB voice or VARA HF (2.75 kHz) signal on HF, kept inside the stretch


def _guard(f: float) -> float:
    """How far from a channel (a calling frequency, FT8, a repeater, a local plan's channel) an ad hoc QSO stays."""
    return 0.003 if f < 30 else 0.015 if f < 400 else 0.025


def WIDE_GUARD(c: float) -> float:  # noqa: N802
    """How far a VARA FM wide signal stays from another channel: 25 kHz (2 m, 6 m, 1.25 m), 35 kHz on 70 cm."""
    return 0.025 if c < 400 else 0.035


def fm_at(f: float) -> bool:
    """Where the band is used channel by channel in FM: 10 m 29.5+, 6 m 51+, 2 m and up."""
    return 29.5 - EPS <= f <= 29.7 + EPS or 51.0 - EPS <= f <= 54.0 or f >= 144.0


def _fm_step(f: float) -> float:
    """The usual FM simplex channel step: 25 kHz on 70 cm and up, 20 kHz below (2 m, 1.25 m, 6 m, 10 m)."""
    return 0.025 if f >= 400 else 0.02


def _fm_points(band: str, p: dict, chans: list[float], kind: str) -> list[dict]:
    """The free FM simplex frequencies in one open stretch: channel steps from its lower edge, each at least a guard
    (15 kHz on 2 m and 1.25 m, 25 kHz on 70 cm, as in _guard) from every channel any plan names."""
    step = _fm_step(p["from"])
    pts, k = [], 0
    while True:
        f = round(p["from"] + k * step, 4)
        k += 1
        if f > p["to"] + EPS:
            break
        if any(abs(f - c) < (0.015 if c < 400 else 0.025) - EPS for c in chans):
            continue
        # VARA FM wide (the 9600-baud data port) spreads to about 25 kHz: it needs more room than narrow (owner
        # 2026-11-16 "consider bandwidth for WIDE and NARROW"). Voice and narrow: the guard above.
        wide = not any(abs(f - c) < WIDE_GUARD(c) - EPS for c in chans)
        pts.append((f, wide))
    runs: list[list[tuple]] = []
    for f, wide in pts:                                   # neighbouring free channels make one row
        if runs and abs(f - runs[-1][-1][0] - step) <= EPS and (kind == "voice" or runs[-1][-1][1] == wide):
            runs[-1].append((f, wide))
        else:
            runs.append([(f, wide)])
    out = []
    for rw in runs:
        r = [f for f, _ in rw]
        auto = any(x <= r[-1] and y >= r[0] for x, y in bandplan.AUTO_DATA)
        out.append({"band": band, "from": r[0], "to": r[-1], "channel": True, "step": step, "count": len(r),
                    "unplanned": p["unplanned"], "uses": p["uses"], "mode": "FM" if kind == "voice" else "VARA FM",
                    "wide": kind == "data" and rw[0][1],
                    "auto": auto, "note": ("shared with automatic data stations (Winlink gateways, packet): listen "
                                           "first, and move off a gateway's frequency" if auto else "")})
    return out


def open_ranges(table: dict, kind: str) -> list[dict]:
    """Stretches where the operator may start an ad hoc `kind` ("voice" or "data", e.g. VARA) session: inside their
    privileges, set aside by no plan for anything else, clear of every channel. Each: {band, from, to, unplanned
    (no plan names a use there), uses (the plans' words where one does), mode, auto (shared with automatic data
    stations: Winlink gateways), note}. Needs the license class (table["license_class"]); 60 m (channels only) is left
    out."""
    cls = table.get("license_class")
    if not cls or kind not in WIDTH:
        return []
    pk = "phone" if kind == "voice" else "data"
    out = []
    for b in table["bands"]:
        if b["band"] == "60 m":
            continue
        hf = b["to"] <= 30
        if not any(s["authority"] != "fcc" for r in b["rows"] for s in r["statements"]):
            continue                                      # no plan covers the band (33 cm, 23 cm): nothing to say
        pieces = []
        for r in b["rows"]:
            if r["type"] != "range" or not (r.get("privileges") or {}).get(pk):
                continue
            plan = [s for s in r["statements"] if s["authority"] != "fcc"]
            c = set().union(*(cats(s["use"]) for s in plan)) if plan else set()
            if c & _NEVER:
                continue
            if kind == "data" and ((plan and "data" not in c) or (hf and "weak" in c)):
                continue                                  # VARA: where a plan sets data aside, or no plan names a use
                                                          # (owner 2026-11-16: "unplanned" for VARA too); never HF CW
            cw_only = any(re.search(r"\bcw\b", (s["use"] or "").lower())
                          and not re.search(r"ssb|phone|voice|sideband", (s["use"] or "").lower()) for s in plan)
            if kind == "voice" and (c & _AVOID["voice"] or (not hf and "weak" in c) or cw_only):
                continue
            uses = []
            for s in plan:
                if s["use"] and s["use"] not in uses:
                    uses.append(s["use"])
            near = bool(pieces) and abs(pieces[-1]["to"] - r["from"]) <= EPS
            if near and pieces[-1]["uses"] == uses:
                pieces[-1]["to"] = r["to"]
                continue
            if near:
                pieces[-1]["open_hi"] = True
            pieces.append({"from": r["from"], "to": r["to"], "uses": uses, "unplanned": not plan, "open_lo": near})
        chans = sorted(r["from"] for r in b["rows"] if r["type"] == "channel")
        for p in pieces:
            if fm_at(p["from"]):
                if not p["unplanned"]:                    # FM: only where a plan names the use (simplex, local option,
                    out += _fm_points(b["band"], p, chans, kind)   # digital); the gaps between segments border repeaters  # FM is used channel by channel (owner 2026-11-16: 2 m
                continue                                      # showed nothing: its plans name a channel every 20-40 kHz)
            ssb = hf or p["from"] < 51                     # 6 m below 51 MHz is SSB / CW / data, like HF
            w = WIDTH[kind] if ssb else 0
            cuts = [(f - _guard(f), f + _guard(f)) for f in chans]
            if not p["open_lo"]:
                cuts.append((p["from"], p["from"] + w))   # the whole signal inside the stretch
            if not p.get("open_hi"):
                cuts.append((p["to"] - w, p["to"]))
            free, at = [], p["from"]
            for a, z in sorted(cuts):
                if a > at:
                    free.append((at, min(a, p["to"])))
                at = max(at, z)
                if at >= p["to"]:
                    break
            if at < p["to"]:
                free.append((at, p["to"]))
            for a, z in free:
                fm = not ssb or a >= 29.5 and hf          # 10 m FM (repeaters, simplex) is as wide as VHF FM
                if z - a < (0.04 if not ssb else 0.02 if fm else 0.005 if kind == "voice" else 0.002):
                    continue
                mode = ("FM" if fm else "LSB" if a < 10 else "USB") if kind == "voice" and hf else "USB" if kind == "voice" \
                    else "VARA HF (USB dial)" if hf or a < 51 else "VARA FM"
                auto = any(x < z and y > a for x, y in bandplan.AUTO_DATA)
                out.append({"band": b["band"], "from": round(a, 4), "to": round(z, 4), "unplanned": p["unplanned"],
                            "uses": p["uses"], "mode": mode, "auto": auto,
                            "note": ("shared with automatic data stations (Winlink gateways, packet): listen first, and "
                                     "move off a gateway's frequency" if auto else "")})
    return out
