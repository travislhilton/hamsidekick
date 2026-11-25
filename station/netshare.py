"""Share a net schedule over the air (owner 2026-11-24: "how can we share net schedules this way").

Two files, both made here and sent over VARA by the operator (📅 Send my net schedule) or by Einstein:
* a calendar (.ics, iCalendar): the next weeks of each net as single events, so any phone, Outlook or Google Calendar
  opens it, and a station without HAM Sidekick can use it too;
* a HAM Sidekick net file (.hsnets): the share-settings document (station/portable.py, schema hamsidekick-settings/1)
  with the nets only. The receiving station offers "📅 Add N nets", previews it and imports it the same way as Share
  settings: never deletes, the same name and start time is updated, each net waits for a radio there ("Nets → give it a
  radio") unless one of its radios has the same name.
What travels: each net's name, frequency, mode, repeater offset and tone, start, length, repeat rule, cancellations and
net control. Never: check-in lists, alert times, reach, which radio carries it here, the operator's history.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from . import portable, recur

SUFFIX = ".hsnets"
KEYS = ("name", "freq_mhz", "mode", "start", "duration_min", "ncs", "repeat", "exceptions", "emergency",
        "offset_mhz", "tone_hz")
WEEKS = 8


def export(st, call: str | None = None) -> dict:
    """The .hsnets document: portable's settings file with the nets only (no Einstein, no local names)."""
    radios = {r["id"]: r for r in st.radios.values()}
    used, nets = {}, []
    for n in st.cfg.get("schedule") or []:
        o = {k: copy.deepcopy(n[k]) for k in KEYS if n.get(k) is not None}
        for e in (o.get("exceptions") or {}).values():
            if isinstance(e, dict):
                e.pop("radio", None)
        r = radios.get(n.get("radio"))
        if r:
            used[r["id"]] = {"key": r["id"], "name": r.get("name"), "freq_mhz": r.get("freq_mhz"), "mode": r.get("mode"),
                             "range": portable._range(r.get("freq_mhz"))}
            o["radio"] = r["id"]
        nets.append(o)
    return {"schema": portable.SCHEMA, "kind": "nets", "from": (call or "").upper() or None,
            "exported": datetime.now().isoformat(timespec="seconds"), "identity_included": False,
            "radios": list(used.values()), "nets": nets}


def _esc(t) -> str:
    return re.sub(r"([,;\\])", r"\\\1", str(t or "")).replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> str:
    out, b = [], line.encode("utf-8")
    while len(b) > 74:
        cut = 74
        while cut and (b[cut] & 0xC0) == 0x80:               # never inside a UTF-8 character
            cut -= 1
        out.append(b[:cut].decode("utf-8"))
        b = b" " + b[cut:]
    out.append(b.decode("utf-8"))
    return "\r\n".join(out)


def ics(st, call: str | None = None, weeks: int = WEEKS, now: datetime | None = None) -> str:
    """The next `weeks` of every net as iCalendar events, in the station's local time (floating: shown at the same
    clock time wherever it is opened, as nets are announced)."""
    now = now or datetime.now()
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    who = (call or "").upper() or "HAM Sidekick Station"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//HAM Sidekick Station//nets//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(who + ' nets')}"]
    for n in st.cfg.get("schedule") or []:
        for o in recur.occurrences(n, now - timedelta(hours=3), now + timedelta(weeks=weeks)):
            if o["end"] <= now:
                continue
            f = o.get("freq_mhz") or n.get("freq_mhz")
            where = (f"{f:.3f} MHz" if f else "") + (f" {o.get('mode') or n.get('mode')}" if (o.get("mode") or n.get("mode")) else "")
            if n.get("offset_mhz"):
                where += f", offset {n['offset_mhz']:+g} MHz"
            if n.get("tone_hz"):
                where += f", tone {n['tone_hz']:g} Hz"
            desc = [f"{n.get('name')} on {where}." if where else str(n.get("name"))]
            if n.get("ncs"):
                desc.append(f"Net control: {n['ncs']}.")
            if o.get("note"):
                desc.append(str(o["note"]))
            if o.get("moved"):
                desc.append("Moved from its usual time.")
            desc.append(f"Shared by {who} over amateur radio.")
            uid = re.sub(r"[^\w.-]", "", f"{n.get('id') or n.get('name')}-{o['date']}") + "@hamsidekick"
            lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}",
                      f"DTSTART:{o['start']:%Y%m%dT%H%M%S}", f"DTEND:{o['end']:%Y%m%dT%H%M%S}",
                      f"SUMMARY:{_esc(n.get('name'))}", f"LOCATION:{_esc(where)}",
                      f"DESCRIPTION:{_esc(' '.join(desc))}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def read(path) -> dict:
    """A received .hsnets file, checked: only ever read as data."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raise ValueError("that is not a HAM Sidekick net file") from None
    if not isinstance(doc, dict) or doc.get("schema") != portable.SCHEMA or not isinstance(doc.get("nets"), list):
        raise ValueError("that is not a HAM Sidekick net file")
    return {"schema": doc["schema"], "kind": "nets", "from": str(doc.get("from") or "")[:12] or None,
            "radios": [r for r in doc.get("radios") or [] if isinstance(r, dict)][:20],
            "nets": [n for n in doc["nets"] if isinstance(n, dict)][:200], "identity_included": False}


def summary(path) -> dict | None:
    """For the inbox row: {from, nets, names}."""
    try:
        d = read(path)
    except ValueError:
        return None
    return {"from": d["from"], "nets": len(d["nets"]), "names": [str(n.get("name") or "")[:40] for n in d["nets"]][:12]}


def preview(st, path) -> dict:
    d = read(path)
    return dict(portable.preview(st, d), source=d["from"])


def install(st, path) -> dict:
    d = read(path)
    return dict(portable.apply(st, d), source=d["from"])


def text(path) -> str:
    """What View shows: the nets in plain words."""
    d = read(path)
    out = [f"Net schedule{' from ' + d['from'] if d['from'] else ''}: {len(d['nets'])} nets", ""]
    for n in d["nets"]:
        try:
            when = recur.summary(n)
        except Exception:  # noqa: BLE001 - shown as data whatever it holds
            when = str(n.get("start") or "")
        bits = [f"offset {n['offset_mhz']:+g} MHz" if isinstance(n.get("offset_mhz"), (int, float)) and n["offset_mhz"] else "",
                f"tone {n['tone_hz']:g} Hz" if isinstance(n.get("tone_hz"), (int, float)) and n["tone_hz"] else "",
                f"net control {n['ncs']}" if n.get("ncs") else ""]
        out.append(f"{n.get('name')}: {when}" + "".join(", " + b for b in bits if b))
    return "\n".join(out)
