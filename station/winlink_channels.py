"""Winlink RMS gateways near this station, from Winlink Express's own channel list on this PC.

Owner 2026-11-16: "You can find the Winlink RMS gateways list here. Be sure to select VARA or VARA FM to filter the list,
also search by service codes PUBLIC EMCOMM. Use the Grid Square value to determine distance from the station."

The Winlink website's list sits behind a bot check and its web API needs a developer key, so the station reads the
copy Winlink Express keeps (Express → Open Session → Channel Selection → "Update Table Via Internet" refreshes it):
    <Express folder>\\<callsign>\\Data\\RMS VHF Channels.dat   callsign|grid|frequency Hz|baud|mode|service code
    <Express folder>\\<callsign>\\Data\\RMS Channels.dat       callsign|grid|frequency Hz|mode|hours (UTC)|service code
Only VARA channels are kept (Winlink's channel mode numbers: 50 VARA HF, 53 VARA HF 500, 54 VARA HF 2750, 51 VARA FM,
52 VARA FM wide: in the list 51 is always 1200 baud and 52 always 9600), only the service codes asked for (PUBLIC,
EMCOMM), and the distance is from the centre of the gateway's grid square to the station (station.where()).
"""
from __future__ import annotations

import math
from pathlib import Path

VARA = {51: "VARA FM", 52: "VARA FM wide", 50: "VARA HF", 53: "VARA HF 500", 54: "VARA HF 2750"}
SERVICE_CODES = ("PUBLIC", "EMCOMM")
VHF_FILE, HF_FILE = "RMS VHF Channels.dat", "RMS Channels.dat"
_DIRS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def parse(text: str, hf: bool) -> list[dict]:
    """Every VARA channel in one channel-list file: {call, grid, freq_mhz, mode, mode_code, baud, hours, service}."""
    out = []
    for line in text.lstrip("﻿").splitlines():
        f = [x.strip() for x in line.split("|")]
        if len(f) < 6:
            continue
        try:
            hz = int(f[2])
            code = int(f[3] if hf else f[4])
        except ValueError:
            continue
        if code not in VARA or not hz:
            continue
        out.append({"call": f[0].upper(), "grid": f[1], "freq_mhz": round(hz / 1e6, 4), "mode": VARA[code],
                    "mode_code": code, "baud": None if hf else (int(f[3]) if f[3].isdigit() else None),
                    "hours": f[4] if hf else None, "service": f[5].upper()})
    return out


def files(installs: list[str]) -> dict[str, Path]:
    """The newest copy of each list among the Express folders' callsign accounts: {"vhf": path, "hf": path}."""
    best: dict[str, Path] = {}
    for inst in installs:
        for kind, name in (("vhf", VHF_FILE), ("hf", HF_FILE)):
            for p in Path(inst).glob(f"*/Data/{name}"):
                try:
                    if kind not in best or p.stat().st_mtime > best[kind].stat().st_mtime:
                        best[kind] = p
                except OSError:
                    pass
    return best


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, h)))


def bearing(a: tuple[float, float], b: tuple[float, float]) -> str:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return _DIRS[round((math.degrees(math.atan2(y, x)) % 360) / 45) % 8]


def near(path: Path, hf: bool, where: tuple[float, float], km: float,
         services=SERVICE_CODES) -> list[dict]:
    """The VARA gateways in one list within `km` of `where`, nearest first, one row per gateway and frequency (its
    VARA modes together)."""
    from hamkit.zipgeo import grid_to_latlon
    rows: dict[tuple, dict] = {}
    for c in parse(path.read_text(encoding="utf-8-sig", errors="replace"), hf):
        if c["service"] not in services:
            continue
        p = grid_to_latlon(c["grid"][:6] if len(c["grid"]) >= 6 else c["grid"][:4])
        if not p:
            continue
        d = km_between(where, p)
        if d > km:
            continue
        k = (c["call"], c["freq_mhz"])
        r = rows.get(k)
        if r:
            if c["mode"] not in r["modes"]:
                r["modes"].append(c["mode"])
            continue
        rows[k] = dict(c, modes=[c["mode"]], km=round(d, 1), dir=bearing(where, p))
    return sorted(rows.values(), key=lambda r: (r["km"], r["call"], -r["freq_mhz"]))


def as_frequencies(rows: list[dict], title: str) -> list[dict]:
    """Gateways as band-plan channels (localplans' frequency shape: kind "winlink")."""
    out = []
    for r in rows:
        mi = r["km"] / 1.609
        out.append({"freq_mhz": r["freq_mhz"], "mode": "FM" if r["freq_mhz"] > 30 else "USB", "offset_mhz": None,
                    "tone_hz": None, "kind": "winlink", "priority": None, "org": r["call"], "source_url": None,
                    "source_opened": False, "net": None, "source_doc": title,
                    "use": f"Winlink gateway {r['call']} ({' / '.join(r['modes'])}), {mi:.0f} mi {r['dir']}, "
                           f"grid {r['grid']}" + (f", {r['hours']} UTC" if r.get("hours") and r["hours"] != "00-23"
                                                  else "") + (" · EMCOMM" if r["service"] == "EMCOMM" else "")
                           + (f" · reach {r['reach']['pct']}% {r['reach']['when']}, {r['reach']['hops']} hop"
                              f"{'s' if r['reach']['hops'] != 1 else ''}" if r.get("reach") else ""),
                    "gateway": dict({k: r[k] for k in ("call", "grid", "km", "dir", "modes", "service", "hours")},
                                    **({"reach": r["reach"]} if r.get("reach") else {}))})
    return out
