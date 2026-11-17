"""Radio channels: what goes into a radio's memories, as one CHIRP file (owner 2026-11-16: "give a short name to any
frequency that is allocated in the overall band plan ... and flag them to be included in a Chirp export. This will
enable the quick creation of a Chirp export to update a radio").

The list is the operator's reserved ad hoc channels (adhoc.py, always on it) and every band-plan channel marked 💾
("put on my radio"). Every entry has a NAME (any length: what it is) and a radio ALIAS (what the radio's display shows,
ALIAS_MAX characters). A mark is kept by frequency and repeater offset, not by the plan row, so a new plan search keeps
it; one the plans no longer list is flagged, never dropped.

CHIRP (File -> Import into the radio's image) takes its memory CSV. The export is for one kind of radio (PROFILES): the
bands and modes it has (the rest are left out, and named); two memories with the same alias are named too.
"""
from __future__ import annotations

import csv
import io
import re
import time

from .consolidate import EPS

# 8 characters: the owner's Baofeng and Quansheng radios (2026-11-17). The export never cuts an alias: an older radio
# that shows fewer (Baofeng UV-5R family 7) is fixed by hand in CHIRP after the import (owner: "stick with 8 on the
# band plan and let the user manually change them after export"). A radio's choice is only its bands and modes.
ALIAS_MAX = 8
ALIAS_CHARS = "A-Z0-9 ./-"
NAME_LONG = 80
MAX = 400
HT = ((136.0, 174.0), (400.0, 520.0))            # 2 m and 70 cm handhelds
PROFILES = {
    "ht": {"label": "Handheld, 2 m + 70 cm FM (Baofeng, Quansheng)", "len": ALIAS_MAX, "bands": HT,
           "modes": ("FM", "NFM")},
    "any": {"label": "Any radio: every band and mode", "len": ALIAS_MAX, "bands": None,
            "modes": ("FM", "NFM", "USB", "LSB", "AM", "CW", "DV")},
}
DEFAULT_PROFILE = "ht"
CTCSS = (67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8, 97.4, 100.0, 103.5, 107.2, 110.9, 114.8,
         118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
         177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5, 203.5, 206.5, 210.7, 218.1, 225.7, 229.1, 233.6,
         241.8, 250.3, 254.1)
CALL_RE = re.compile(r"^[A-Z]{1,2}[0-9][A-Z]{1,4}$")


def alias(text, n: int = ALIAS_MAX) -> str:
    """What a radio display shows as typed: upper case, letters, digits, space . / - only, `n` characters."""
    t = re.sub(f"[^{ALIAS_CHARS}]", "", str(text or "").upper())
    return " ".join(t.split())[:n].strip()


def long_name(text) -> str:
    return " ".join(str(text or "").split())[:NAME_LONG]


def fmt_f(f: float) -> str:
    s = f"{f:.4f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def suggest_alias(row: dict) -> str:
    """A first alias for a band-plan channel: a repeater's or gateway's callsign, else R + its frequency (repeater) or
    the frequency."""
    org = alias(row.get("org") or "").replace(" ", "")
    if CALL_RE.match(org):
        return org[:ALIAS_MAX]
    f = fmt_f(float(row["freq_mhz"]))
    return alias(("R" if row.get("offset_mhz") else "") + f)


def mode_of(f: float, mode) -> str:
    m = str(mode or "").upper().replace(" ", "")
    if m in ("NFM", "FMN", "FM-N", "NARROW"):
        return "NFM"
    if not m:
        return "FM" if f > 30 else "USB"
    if m.startswith("VARAFM") or m in ("FM", "PACKET", "APRS", "FMVOICE"):
        return "FM"
    for k in ("USB", "LSB", "AM", "CW", "DV"):
        if m.startswith(k) or (k == "DV" and m in ("D-STAR", "DSTAR")):
            return k
    return "FM" if f > 30 else "USB"


def key(r: dict) -> str:
    if r.get("src") == "adhoc":
        return f"a:{r['kind']}:{r['freq_mhz']:.4f}"
    return f"p:{r['freq_mhz']:.4f}:{(r.get('offset_mhz') or 0):.4f}"


def clean_mark(raw: dict) -> dict:
    """One band-plan channel marked for the radio: ValueError says why not."""
    if not isinstance(raw, dict):
        raise ValueError("not a channel")
    try:
        f = round(float(raw.get("freq_mhz")), 4)
    except (TypeError, ValueError):
        raise ValueError("no frequency") from None
    if not 1.8 <= f <= 1300:
        raise ValueError(f"{f:g} MHz is not an amateur channel a radio memory holds here")
    off = raw.get("offset_mhz")
    try:
        off = round(float(off), 4) if off not in (None, "", 0) else None
    except (TypeError, ValueError):
        off = None
    tone = raw.get("tone_hz")
    try:
        tone = float(tone) if tone not in (None, "") else None
    except (TypeError, ValueError):
        tone = None
    if tone is not None:
        tone = min(CTCSS, key=lambda t: abs(t - tone))
    r = {"src": "plan", "freq_mhz": f, "offset_mhz": off, "tone_hz": tone, "mode": mode_of(f, raw.get("mode")),
         "name": long_name(raw.get("name")), "at": float(raw.get("at") or time.time())}
    r["alias"] = alias(raw.get("alias")) or suggest_alias(dict(raw, freq_mhz=f, offset_mhz=off))
    return r


def apply(marks: list[dict], body: dict) -> list[dict]:
    """{"add": channel} | {"remove": {freq_mhz, offset_mhz}} | {"edit": {freq_mhz, offset_mhz, alias?, name?}}."""
    marks = [dict(m) for m in marks]
    if "add" in body:
        r = clean_mark(body["add"])
        if any(key(m) == key(r) for m in marks):
            raise ValueError(f"{r['freq_mhz']:g} is on your radio list already")
        if len(marks) >= MAX:
            raise ValueError(f"at most {MAX} radio channels")
        marks.append(r)
    for k in ("remove", "edit"):
        if k in body:
            want = clean_mark(dict(body[k], alias="X"))
            hit = [m for m in marks if key(m) == key(want)]
            if not hit:
                raise ValueError(f"{want['freq_mhz']:g} is not on your radio list")
            if k == "remove":
                marks = [m for m in marks if key(m) != key(want)]
            else:
                if "alias" in body[k]:
                    hit[0]["alias"] = alias(body[k]["alias"]) or suggest_alias(hit[0])
                if "name" in body[k]:
                    hit[0]["name"] = long_name(body[k]["name"])
    return marks


def listing(adhoc_rows: list[dict], marks: list[dict], order: list[str], table: dict | None = None) -> list[dict]:
    """Everything for the radio, in memory order: the ad hoc reservations and the marked plan channels. A mark the
    plans no longer list as a channel gets "gone"."""
    chans = []
    for b in (table or {}).get("bands") or []:
        for r in b["rows"]:
            if r["type"] == "channel":
                chans.append(r)
    out = []
    for a in adhoc_rows:
        out.append({"src": "adhoc", "kind": a["kind"], "width": a.get("width"), "freq_mhz": a["freq_mhz"],
                    "offset_mhz": None, "tone_hz": None, "mode": "FM", "alias": a.get("alias") or "",
                    "name": a.get("name") or "", "ok": a.get("ok", True), "why": a.get("why")})
    for m in marks:
        hit = any(abs(c["from"] - m["freq_mhz"]) <= EPS and abs((c.get("offset_mhz") or 0) - (m.get("offset_mhz") or 0))
                  <= EPS for c in chans) if table else True
        out.append(dict(m, ok=hit, why=None if hit else "the band plan no longer lists this channel"))
    pos = {k: i for i, k in enumerate(order or [])}
    for r in out:
        r["key"] = key(r)
    out.sort(key=lambda r: (pos.get(r["key"], 10 ** 6), r["freq_mhz"]))
    return out


def move(order: list[str], keys: list[str], k: str, by: int) -> list[str]:
    """The memory order with entry `k` moved `by` places (keys: the list as shown now)."""
    cur = list(keys)
    if k not in cur:
        return cur
    i = cur.index(k)
    j = max(0, min(len(cur) - 1, i + by))
    cur.insert(j, cur.pop(i))
    return cur


def _step(f: float) -> str:
    khz = round(f * 1000, 3)
    for s in (5.0, 6.25, 12.5, 2.5):
        if abs(khz / s - round(khz / s)) < 1e-6:
            return f"{s:.2f}"
    return "5.00"


def plan(items: list[dict], profile: str = DEFAULT_PROFILE) -> dict:
    """What a CHIRP export for this kind of radio holds: {"rows": [...with "chirp_name"], "left_out": [why],
    "shortened": [..], "dups": [..]}."""
    p = PROFILES.get(profile) or PROFILES[DEFAULT_PROFILE]
    rows, left, short, seen, dups = [], [], [], {}, []
    for r in items:
        f = r["freq_mhz"]
        what = fmt_f(f) + " MHz" + (f" ({r['alias']})" if r.get("alias") and r["alias"] != fmt_f(f) else "")
        if p["bands"] and not any(lo <= f <= hi for lo, hi in p["bands"]):
            left.append(f"{what}: not a band this radio has")
            continue
        if r["mode"] not in p["modes"]:
            left.append(f"{what}: {r['mode']} is not a mode this radio has")
            continue
        nm = alias(r["alias"], p["len"]) if p["len"] else ""
        if p["len"] and len(r["alias"]) > p["len"]:
            short.append(f"{r['alias']} → {nm}")
        if nm:
            if nm in seen:
                dups.append(f"{nm}: {fmt_f(seen[nm])} and {fmt_f(f)} MHz")
            seen.setdefault(nm, f)
        rows.append(dict(r, chirp_name=nm))
    return {"rows": rows, "left_out": left, "shortened": short, "dups": dups, "profile": profile,
            "label": p["label"], "len": p["len"]}


def chirp_csv(items: list[dict], profile: str = DEFAULT_PROFILE, start: int = 1) -> str:
    """CHIRP's memory CSV, memories numbered from `start` in the list's order."""
    cols = ["Location", "Name", "Frequency", "Duplex", "Offset", "Tone", "rToneFreq", "cToneFreq", "DtcsCode",
            "DtcsPolarity", "Mode", "TStep", "Skip", "Comment", "URCALL", "RPT1CALL", "RPT2CALL", "DVCODE"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(cols)
    for i, r in enumerate(plan(items, profile)["rows"]):
        off = r.get("offset_mhz") or 0
        tone = r.get("tone_hz")
        w.writerow([start + i, r["chirp_name"], f"{r['freq_mhz']:.6f}", "+" if off > 0 else "-" if off < 0 else "",
                    f"{abs(off):.6f}", "Tone" if tone else "", f"{tone:.1f}" if tone else "88.5",
                    f"{tone:.1f}" if tone else "88.5", "023", "NN", r["mode"], _step(r["freq_mhz"]), "",
                    (r.get("name") or "")[:60], "", "", "", ""])
    return buf.getvalue()


def export_marks(marks: list[dict]) -> list[dict]:
    return [{k: m.get(k) for k in ("freq_mhz", "offset_mhz", "tone_hz", "mode", "alias", "name")} for m in marks]


def import_marks(marks: list[dict], incoming) -> tuple[list[dict], int]:
    """Another operator's 💾 channels merged into mine (in their ad hoc file): -> (marks, added)."""
    out, added = [dict(m) for m in marks], 0
    for raw in (incoming or [])[:MAX]:
        try:
            r = clean_mark(dict(raw, at=None) if isinstance(raw, dict) else raw)
        except ValueError:
            continue
        if any(key(m) == key(r) for m in out) or len(out) >= MAX:
            continue
        out.append(r)
        added += 1
    return out, added
