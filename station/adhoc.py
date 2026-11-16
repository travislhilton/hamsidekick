"""The operator's reserved ad hoc channels (owner 2026-11-16: "split up each frequency range into channel frequencies
and add a button or link to reserve for my ad-hoc and add my reserved ad-hoc frequencies to the band plan with a special
marker ... the ability to export my ad-hoc reserved frequencies to another operator so that they can have the same
reserved ad-hoc set. Do something similar for FM voice").

A reservation is one VHF/UHF FM channel picked from the band plan's Ad hoc VARA or Ad hoc voice list:
    {"freq_mhz": 445.525, "kind": "data" | "voice", "width": "narrow" | "wide" (data only), "name": "Ad hoc VARA 1"}
It is the operator's own agreement, not a plan's: the band plan shows it with a ★ marker, the ad hoc lists keep it
listed (marked reserved) instead of cutting it out, and a reservation the plans no longer leave open is flagged.

Shared as a file: export() -> {"format": FORMAT, "version": 1, "channels": [...]} (import_() takes the same, from this
station or another), and chirp_csv() for programming a radio's memories with CHIRP.
"""
from __future__ import annotations

import csv
import io
import re
import time

from . import bandplan
from .consolidate import EPS, fm_at

FORMAT = "hamsidekick-adhoc-channels"
# A channel's name fits the shortest radio display that shows names (owner 2026-11-16: "restricted to short so that
# when exported as a CHIRP file the name will fit"). CHIRP's drivers: Baofeng UV-5R / BF-F8HP / UV-82 / UV-5X3 7
# characters, upper case (uv5r.py UV5R_CHARSET); Baofeng WP970I / UV-82III / UV-9R Pro 6 (baofeng_wp970i.py); UV-5RM /
# UV-17 Pro 12; Yaesu FT-60 6; BF-888S / UV-3R none. So 6, from what every one of them accepts.
NAME_MAX = 6
NAME_CHARS = "A-Z0-9 ./-"
KINDS = ("data", "voice")
MAX = 200


def short_name(text) -> str:
    """A name a 6-character radio display shows as typed: upper case, letters, digits, space . / - only."""
    t = re.sub(f"[^{NAME_CHARS}]", "", str(text or "").upper())
    return " ".join(t.split())[:NAME_MAX].strip()


def suggest(rows: list[dict], kind: str) -> str:
    """The next free default name: VARA1, VARA2 ... for VARA FM, TAC1, TAC2 ... for voice."""
    base = "VARA" if kind == "data" else "TAC"
    used = {r.get("name") for r in rows}
    return next(f"{base}{i}" for i in range(1, 1000) if f"{base}{i}" not in used)


def clean(raw: dict) -> dict:
    """One reservation, checked: ValueError says why not."""
    if not isinstance(raw, dict):
        raise ValueError("not a channel")
    try:
        f = round(float(raw.get("freq_mhz")), 4)
    except (TypeError, ValueError):
        raise ValueError("no frequency") from None
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ValueError(f"{f:g}: kind is data (VARA FM) or voice (FM)")
    if not bandplan.band(f) or not fm_at(f) or f < 144.1:          # 144.0-144.1 is CW only (97.305)
        raise ValueError(f"{f:g} MHz: ad hoc channels are VHF / UHF FM channels (2 m, 1.25 m, 70 cm)")
    width = raw.get("width") if raw.get("width") in ("narrow", "wide") else "narrow"
    name = short_name(raw.get("name"))
    return {"freq_mhz": f, "kind": kind, "width": width if kind == "data" else None, "name": name,
            "at": float(raw.get("at") or time.time())}


def same(a: dict, b: dict) -> bool:
    return a["kind"] == b["kind"] and abs(a["freq_mhz"] - b["freq_mhz"]) <= EPS


def label(r: dict) -> str:
    """Its words in the band plan."""
    what = "VARA FM" + (" wide" if r.get("width") == "wide" else "") if r["kind"] == "data" else "FM voice"
    return f"My ad hoc {what}" + (f": {r['name']}" if r.get("name") else "")


def apply(rows: list[dict], body: dict) -> list[dict]:
    """{"add": channel} | {"remove": {freq_mhz, kind}} | {"rename": {freq_mhz, kind, name}} | {"width": {freq_mhz,
    kind, width}} | {"clear": kind}."""
    rows = [dict(r) for r in rows]
    if "add" in body:
        r = clean(body["add"])
        if any(same(r, x) for x in rows):
            raise ValueError(f"{r['freq_mhz']:g} is reserved already")
        if len(rows) >= MAX:
            raise ValueError(f"at most {MAX} reserved channels")
        if not r["name"]:
            r["name"] = suggest(rows, r["kind"])
        rows.append(r)
    for k in ("remove", "rename", "width"):
        if k in body:
            want = clean(dict(body[k], name="", width=body[k].get("width")))
            hit = [x for x in rows if same(x, want)]
            if not hit:
                raise ValueError(f"{want['freq_mhz']:g} is not reserved")
            if k == "remove":
                rows = [x for x in rows if not same(x, want)]
            elif k == "rename":
                hit[0]["name"] = short_name(body[k].get("name"))
            elif want["kind"] == "data":
                hit[0]["width"] = want["width"]
    if body.get("clear") in KINDS:
        rows = [x for x in rows if x["kind"] != body["clear"]]
    return sorted(rows, key=lambda x: (x["kind"], x["freq_mhz"]))


def export(rows: list[dict], callsign: str | None = None) -> dict:
    return {"format": FORMAT, "version": 1, "exported_at": time.strftime("%Y-%m-%d %H:%M"),
            "from": callsign or None,
            "channels": [{k: r.get(k) for k in ("freq_mhz", "kind", "width", "name")} for r in rows]}


def import_(rows: list[dict], obj, replace: bool = False) -> tuple[list[dict], dict]:
    """Another operator's (or this station's) export merged in: -> (rows, {added, renamed, already, skipped: [why]})."""
    if not isinstance(obj, dict) or obj.get("format") != FORMAT or not isinstance(obj.get("channels"), list):
        raise ValueError("that is not a HAM Sidekick ad hoc channels file (Export makes one)")
    out = [] if replace else [dict(r) for r in rows]
    rep = {"added": 0, "renamed": 0, "already": 0, "skipped": []}
    for raw in obj["channels"][:MAX * 2]:
        try:
            r = clean(dict(raw, at=None) if isinstance(raw, dict) else raw)
        except ValueError as e:
            rep["skipped"].append(str(e))
            continue
        hit = next((x for x in out if same(x, r)), None)
        if hit:
            if r["name"] and r["name"] != hit.get("name"):
                hit["name"] = r["name"]
                rep["renamed"] += 1
            else:
                rep["already"] += 1
            continue
        if len(out) >= MAX:
            rep["skipped"].append(f"{r['freq_mhz']:g}: at most {MAX} reserved channels")
            continue
        out.append(r)
        rep["added"] += 1
    return sorted(out, key=lambda x: (x["kind"], x["freq_mhz"])), rep


def chirp_csv(rows: list[dict]) -> str:
    """CHIRP's memory CSV (File -> Import into a radio's image): simplex FM, no tone, named for the radio's display."""
    cols = ["Location", "Name", "Frequency", "Duplex", "Offset", "Tone", "rToneFreq", "cToneFreq", "DtcsCode",
            "DtcsPolarity", "Mode", "TStep", "Skip", "Comment", "URCALL", "RPT1CALL", "RPT2CALL", "DVCODE"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(cols)
    for i, r in enumerate(sorted(rows, key=lambda x: (x["kind"] != "voice", x["freq_mhz"]))):
        short = r.get("name") or f"{r['freq_mhz']:.2f}"[:NAME_MAX]
        w.writerow([i, short, f"{r['freq_mhz']:.6f}", "", "0.000000", "", "88.5", "88.5", "023", "NN", "FM",
                    "5.00" if r["freq_mhz"] < 400 else "25.00", "", label(r), "", "", "", ""])
    return buf.getvalue()
