"""The operator's reserved ad hoc channels (owner 2026-11-16: "split up each frequency range into channel frequencies
and add a button or link to reserve for my ad-hoc and add my reserved ad-hoc frequencies to the band plan with a special
marker ... the ability to export my ad-hoc reserved frequencies to another operator so that they can have the same
reserved ad-hoc set. Do something similar for FM voice").

A reservation is one VHF/UHF FM channel picked from the band plan's Ad hoc VARA or Ad hoc voice list:
    {"freq_mhz": 445.525, "kind": "data" | "voice", "width": "narrow" | "wide" (data only),
     "name": "County ARES VARA simplex" (any length), "alias": "VARA1" (the radio's display, radiochan.ALIAS_MAX)}
It is the operator's own agreement, not a plan's: the band plan shows it with a ★ marker, the ad hoc lists keep it
listed (marked reserved) instead of cutting it out, and a reservation the plans no longer leave open is flagged.

Shared as a file: export() -> {"format": FORMAT, "version": 1, "channels": [...]} (import_() takes the same, from this
station or another), and chirp_csv() for programming a radio's memories with CHIRP (radiochan.py: with the band-plan
channels marked for the radio, in one file).
"""
from __future__ import annotations

import time

from . import bandplan
from .consolidate import EPS, WIDE_GUARD, fm_at
from .radiochan import ALIAS_MAX, alias as _alias, long_name

FORMAT = "hamsidekick-adhoc-channels"
# The radio alias fits the radios' displays (radiochan.ALIAS_MAX: 8, the owner's Baofeng and Quansheng radios; a CHIRP
# export for a shorter display cuts it). Until 2026-11-17 a reservation had one 6-character name: it becomes the alias.
NAME_MAX = ALIAS_MAX
KINDS = ("data", "voice")
MAX = 200


def short_name(text) -> str:
    """A radio alias: upper case, letters, digits, space . / - only, ALIAS_MAX characters."""
    return _alias(text)


def suggest(rows: list[dict], kind: str) -> str:
    """The next free default name: VARA1, VARA2 ... for VARA FM, TAC1, TAC2 ... for voice."""
    base = "VARA" if kind == "data" else "TAC"
    used = {r.get("alias") for r in rows}
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
    al = short_name(raw.get("alias") if raw.get("alias") is not None else raw.get("name"))
    return {"freq_mhz": f, "kind": kind, "width": width if kind == "data" else None, "name": long_name(raw.get("name")),
            "alias": al, "at": float(raw.get("at") or time.time())}


def too_close(rows: list[dict], r: dict) -> dict | None:
    """The nearest other reservation a VARA FM WIDE signal on `r` would overlap (~25 kHz wide: it needs 25 kHz to
    the next channel on 2 m and 1.25 m, 35 kHz on 70 cm, as WIDE_GUARD), or None. Voice reservations count: they are
    signals too. Owner 2026-11-16: two wide reservations 25 kHz apart on 70 cm both looked fine."""
    near = [x for x in rows if not same(x, r) and abs(x["freq_mhz"] - r["freq_mhz"]) > EPS
            and abs(x["freq_mhz"] - r["freq_mhz"]) < WIDE_GUARD(r["freq_mhz"]) - EPS]
    return min(near, key=lambda x: abs(x["freq_mhz"] - r["freq_mhz"])) if near else None


def crowd_note(r: dict, n: dict) -> str:
    return (f"too close to your {n.get('alias') or n.get('name') or 'reservation'} at {n['freq_mhz']:.3f} for VARA FM wide (it needs "
            f"{round(WIDE_GUARD(r['freq_mhz']) * 1000)} kHz): use narrow, or pick a channel further away")


def same(a: dict, b: dict) -> bool:
    return a["kind"] == b["kind"] and abs(a["freq_mhz"] - b["freq_mhz"]) <= EPS


def label(r: dict) -> str:
    """Its words in the band plan."""
    what = "VARA FM" + (" wide" if r.get("width") == "wide" else "") if r["kind"] == "data" else "FM voice"
    nm = r.get("name") or r.get("alias")
    return f"My ad hoc {what}" + (f": {nm}" if nm else "")


def apply(rows: list[dict], body: dict) -> list[dict]:
    """{"add": channel} | {"remove": {freq_mhz, kind}} | {"rename": {freq_mhz, kind, name?, alias?}} | {"width":
    {freq_mhz, kind, width}} | {"clear": kind}."""
    rows = [dict(r) for r in rows]
    if "add" in body:
        r = clean(body["add"])
        if any(same(r, x) for x in rows):
            raise ValueError(f"{r['freq_mhz']:g} is reserved already")
        if len(rows) >= MAX:
            raise ValueError(f"at most {MAX} reserved channels")
        if not r["alias"] or body["add"].get("alias") is None and len(long_name(body["add"].get("name"))) > ALIAS_MAX:
            r["alias"] = suggest(rows, r["kind"])     # a long name is the name; the alias is VARA1 / TAC1 ...
        if r["kind"] == "data" and r["width"] == "wide" and too_close(rows, r):
            r["width"] = "narrow"                     # next to one of my own reservations: wide would overlap it
            r["narrowed"] = crowd_note(r, too_close(rows, r))
        rows.append(r)
    for k in ("remove", "rename", "width"):
        if k in body:
            want = clean(dict(body[k], name="", alias="", width=body[k].get("width")))
            hit = [x for x in rows if same(x, want)]
            if not hit:
                raise ValueError(f"{want['freq_mhz']:g} is not reserved")
            if k == "remove":
                rows = [x for x in rows if not same(x, want)]
            elif k == "rename":
                if "name" in body[k]:
                    hit[0]["name"] = long_name(body[k]["name"])
                if "alias" in body[k]:
                    hit[0]["alias"] = short_name(body[k]["alias"]) or hit[0].get("alias") or suggest(rows, hit[0]["kind"])
            elif want["kind"] == "data":
                hit[0]["width"] = want["width"]
    if body.get("clear") in KINDS:
        rows = [x for x in rows if x["kind"] != body["clear"]]
    return sorted(rows, key=lambda x: (x["kind"], x["freq_mhz"]))


def export(rows: list[dict], callsign: str | None = None, radio: list[dict] | None = None) -> dict:
    """radio: the band-plan channels marked for the radio (radiochan.export_marks), only when the operator ticks it."""
    out = {"format": FORMAT, "version": 2, "exported_at": time.strftime("%Y-%m-%d %H:%M"), "from": callsign or None,
           "channels": [{k: r.get(k) for k in ("freq_mhz", "kind", "width", "name", "alias")} for r in rows]}
    if radio:
        out["radio_channels"] = radio
    return out


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
            if (r["name"] and r["name"] != hit.get("name")) or (r["alias"] and r["alias"] != hit.get("alias")):
                hit["name"] = r["name"] or hit.get("name") or ""
                hit["alias"] = r["alias"] or hit.get("alias")
                rep["renamed"] += 1
            else:
                rep["already"] += 1
            continue
        if len(out) >= MAX:
            rep["skipped"].append(f"{r['freq_mhz']:g}: at most {MAX} reserved channels")
            continue
        if not r["alias"]:
            r["alias"] = suggest(out, r["kind"])
        out.append(r)
        rep["added"] += 1
    return sorted(out, key=lambda x: (x["kind"], x["freq_mhz"])), rep


def chirp_csv(rows: list[dict], profile: str | None = None) -> str:
    """CHIRP's memory CSV of the reservations alone (radiochan.chirp_csv)."""
    from . import radiochan
    return radiochan.chirp_csv(radiochan.listing(rows, [], []), profile or radiochan.DEFAULT_PROFILE)
