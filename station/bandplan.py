"""The amateur bands: what each license class may transmit where (FCC Part 97), and what the band plan sets each
part of a band aside for (the ARRL's voluntary band plan). Built in: no search, no network, works in an outage.

Owner 2026-11-15 ("capture any amateur radio band plans for the local area"): this is the national layer; a state's
frequency coordinator refines VHF/UHF (repeater pairs, simplex channels, links) and the area's ARES / RACES plans
name the frequencies used locally: both come from Nets -> Local plans (station/localplans.py) and sit on top.

privileges(f, kind, cls) is the check every transmit path goes through: Sidekick's voice (kind "phone") and VARA chat
and files (kind "data"). US rules only (97.301 / 97.305 / 97.303(h) for 60 m); elsewhere set no class and nothing is
checked. Since 2024 (FCC 23-93) HF data has no symbol-rate limit, only 2.8 kHz bandwidth: VARA HF fits (2.3 / 2.75 kHz).
"""
from __future__ import annotations

CLASSES = ("technician", "general", "advanced", "extra")
KINDS = ("phone", "data", "cw")
SIXTY_M = (5.3305, 5.3465, 5.3570, 5.3715, 5.4035)    # channel centres (USB dial 1.5 kHz below), 2.8 kHz wide

# VHF and up: every class, every kind, except the CW-only bottoms (50.0-50.1, 144.0-144.1) and 219-220 (data only)
_UP = {"phone": [(50.1, 54.0), (144.1, 148.0), (222.0, 225.0), (420.0, 450.0), (902.0, 928.0), (1240.0, 1300.0)],
       "data": [(50.1, 54.0), (144.1, 148.0), (219.0, 220.0), (222.0, 225.0), (420.0, 450.0), (902.0, 928.0),
                (1240.0, 1300.0)],
       "cw": [(50.0, 54.0), (144.0, 148.0), (222.0, 225.0), (420.0, 450.0), (902.0, 928.0), (1240.0, 1300.0)]}

# HF by class (97.301): CW is allowed anywhere in a class's band; "data" is RTTY and data, below the phone segments
_HF = {
    "extra": {"phone": [(1.8, 2.0), (3.6, 4.0), (7.125, 7.3), (14.15, 14.35), (18.11, 18.168), (21.2, 21.45),
                        (24.93, 24.99), (28.3, 29.7)],
              "data": [(1.8, 2.0), (3.5, 3.6), (7.0, 7.125), (10.1, 10.15), (14.0, 14.15), (18.068, 18.11),
                       (21.0, 21.2), (24.89, 24.93), (28.0, 28.3)],
              "cw": [(1.8, 2.0), (3.5, 4.0), (7.0, 7.3), (10.1, 10.15), (14.0, 14.35), (18.068, 18.168),
                     (21.0, 21.45), (24.89, 24.99), (28.0, 29.7)]},
    "advanced": {"phone": [(1.8, 2.0), (3.7, 4.0), (7.125, 7.3), (14.175, 14.35), (18.11, 18.168), (21.225, 21.45),
                           (24.93, 24.99), (28.3, 29.7)],
                 "data": [(1.8, 2.0), (3.525, 3.6), (7.025, 7.125), (10.1, 10.15), (14.025, 14.15), (18.068, 18.11),
                          (21.025, 21.2), (24.89, 24.93), (28.0, 28.3)],
                 "cw": [(1.8, 2.0), (3.525, 4.0), (7.025, 7.3), (10.1, 10.15), (14.025, 14.35), (18.068, 18.168),
                        (21.025, 21.45), (24.89, 24.99), (28.0, 29.7)]},
    "general": {"phone": [(1.8, 2.0), (3.8, 4.0), (7.175, 7.3), (14.225, 14.35), (18.11, 18.168), (21.275, 21.45),
                          (24.93, 24.99), (28.3, 29.7)],
                "data": [(1.8, 2.0), (3.525, 3.6), (7.025, 7.125), (10.1, 10.15), (14.025, 14.15), (18.068, 18.11),
                         (21.025, 21.2), (24.89, 24.93), (28.0, 28.3)],
                "cw": [(1.8, 2.0), (3.525, 4.0), (7.025, 7.3), (10.1, 10.15), (14.025, 14.35), (18.068, 18.168),
                       (21.025, 21.45), (24.89, 24.99), (28.0, 29.7)]},
    "technician": {"phone": [(28.3, 28.5)], "data": [(28.0, 28.3)],
                   "cw": [(3.525, 3.6), (7.025, 7.125), (21.025, 21.2), (28.0, 28.5)]},
}
ALLOC = {c: {k: _HF[c][k] + _UP[k] for k in KINDS} for c in CLASSES}

# 97.221(b): where data may be sent under automatic control (unattended) on HF. The station never does that (every
# transmission is the operator's own click), but the plan shows it so an operator knows where robots answer.
AUTO_DATA = [(3.585, 3.6), (7.1, 7.105), (10.14, 10.15), (14.095, 14.0995), (14.1005, 14.112), (18.105, 18.11),
             (21.09, 21.1), (24.925, 24.93), (28.12, 28.189)]

# The ARRL band plan (voluntary), the parts an operator meets most. (low, high, what). A single frequency: low == high.
PLAN = [
    # 160 m
    (1.8, 1.81, "digital modes"), (1.81, 1.843, "CW"), (1.81, 1.81, "QRP CW calling"), (1.84, 1.84, "FT8"), (1.843, 2.0, "SSB, SSTV and other wideband modes"),
    (1.91, 1.91, "SSB QRP"), (1.995, 2.0, "experimental"),
    # 80 m
    (3.5, 3.51, "CW DX window"), (3.56, 3.56, "QRP CW calling"), (3.57, 3.6, "RTTY / data"), (3.573, 3.573, "FT8"),
    (3.585, 3.6, "automatic-control data (Winlink, packet)"), (3.79, 3.8, "DX window (SSB)"), (3.845, 3.845, "SSTV"),
    (3.885, 3.885, "AM calling"), (3.985, 3.985, "SSB QRP"),
    # 60 m
    (5.3305, 5.3305, "60 m channel 1 (USB dial 5.3305; data and CW at centre)"), (5.3465, 5.3465, "60 m channel 2"),
    (5.357, 5.357, "60 m channel 3"), (5.3715, 5.3715, "60 m channel 4"), (5.4035, 5.4035, "60 m channel 5"),
    # 40 m
    (7.03, 7.03, "QRP CW calling"), (7.04, 7.04, "RTTY / data DX"), (7.074, 7.074, "FT8"), (7.08, 7.125, "RTTY / data"),
    (7.1, 7.105, "automatic-control data (Winlink, packet)"), (7.171, 7.171, "SSTV"), (7.285, 7.285, "SSB QRP"),
    (7.29, 7.29, "AM calling"),
    # 30 m
    (10.13, 10.14, "RTTY / data"), (10.136, 10.136, "FT8"), (10.14, 10.15, "packet / automatic-control data"),
    # 20 m
    (14.06, 14.06, "QRP CW calling"), (14.07, 14.095, "RTTY / data"), (14.074, 14.074, "FT8"),
    (14.095, 14.0995, "packet / automatic-control data"), (14.1, 14.1, "NCDXF/IARU beacons: do not transmit"),
    (14.1005, 14.112, "packet / automatic-control data (VARA HF calling around 14.105)"),
    (14.23, 14.23, "SSTV"), (14.286, 14.286, "AM calling"), (14.3, 14.3, "maritime mobile and emergency traffic nets"),
    # 17 m
    (18.1, 18.105, "RTTY / data (FT8 18.100)"), (18.105, 18.11, "packet / automatic-control data"),
    (18.11, 18.11, "NCDXF/IARU beacons: do not transmit"),
    # 15 m
    (21.06, 21.06, "QRP CW calling"), (21.07, 21.11, "RTTY / data"), (21.074, 21.074, "FT8"),
    (21.09, 21.1, "automatic-control data"), (21.15, 21.15, "NCDXF/IARU beacons: do not transmit"), (21.34, 21.34, "SSTV"),
    # 12 m
    (24.915, 24.915, "FT8"), (24.92, 24.925, "RTTY / data"), (24.925, 24.93, "packet / automatic-control data"),
    (24.93, 24.93, "NCDXF/IARU beacons: do not transmit"),
    # 10 m
    (28.0, 28.07, "CW"), (28.07, 28.15, "RTTY / data"), (28.074, 28.074, "FT8"), (28.12, 28.189, "automatic-control data"),
    (28.15, 28.19, "CW"), (28.2, 28.3, "beacons: do not transmit"), (28.3, 29.3, "phone"), (28.68, 28.68, "SSTV"),
    (29.0, 29.2, "AM"), (29.3, 29.51, "satellite downlinks: do not transmit"), (29.52, 29.58, "FM repeater inputs"),
    (29.6, 29.6, "FM simplex calling"), (29.62, 29.68, "FM repeater outputs"),
    # 6 m
    (50.0, 50.1, "CW and beacons"), (50.1, 50.3, "SSB and CW"), (50.125, 50.125, "SSB DX calling"),
    (50.2, 50.2, "SSB calling"), (50.3, 50.6, "all modes"), (50.313, 50.313, "FT8"), (50.6, 50.8, "digital (non-voice)"),
    (50.8, 51.0, "radio control"), (51.12, 51.48, "FM repeater inputs"), (51.62, 51.98, "FM repeater outputs"),
    (52.0, 52.48, "FM repeater inputs"), (52.5, 52.98, "FM repeater outputs"), (52.525, 52.525, "FM simplex calling"),
    (53.0, 53.48, "FM repeater inputs"), (53.5, 53.98, "FM repeater outputs"),
    # 2 m
    (144.0, 144.1, "CW and EME"), (144.1, 144.275, "weak-signal CW / SSB"), (144.2, 144.2, "SSB calling"),
    (144.275, 144.3, "beacons"), (144.3, 144.5, "satellite / new OSCAR"), (144.39, 144.39, "APRS (data): do not talk here"),
    (144.5, 144.6, "linear translator inputs"), (144.6, 144.9, "FM repeater inputs"),
    (144.9, 145.1, "weak signal and FM simplex"),
    (145.01, 145.09, "packet (data)"), (145.1, 145.2, "linear translator outputs"),
    (145.2, 145.5, "FM repeater outputs"), (145.5, 145.8, "miscellaneous and experimental (some areas: simplex)"),
    (145.8, 146.0, "satellites: do not transmit except to a satellite"), (146.01, 146.37, "FM repeater inputs"),
    (146.4, 146.58, "FM simplex"), (146.52, 146.52, "national FM simplex calling frequency"),
    (146.61, 147.39, "FM repeater outputs"), (147.42, 147.57, "FM simplex"), (147.6, 147.99, "FM repeater inputs"),
    # 1.25 m
    (222.0, 222.15, "weak-signal CW / SSB"), (222.1, 222.1, "SSB calling"), (222.15, 222.25, "local option (weak signal, repeater inputs, control)"), (222.25, 223.38, "FM repeater inputs"),
    (223.4, 223.52, "FM simplex"), (223.5, 223.5, "FM simplex calling"), (223.52, 223.64, "digital / packet"),
    (223.64, 223.7, "links and control"), (223.71, 223.85, "local option"), (223.85, 224.98, "FM repeater outputs"),
    # 70 cm
    (420.0, 426.0, "ATV and repeater links"), (426.0, 432.0, "ATV simplex"), (432.0, 432.07, "EME"), (432.07, 432.1, "weak-signal CW"),
    (432.1, 432.1, "SSB / CW calling"), (432.1, 433.0, "weak-signal mixed modes"), (433.0, 435.0, "auxiliary and repeater links"),
    (435.0, 438.0, "satellites: do not transmit except to a satellite"), (438.0, 444.0, "ATV and repeater links"),
    (442.0, 445.0, "FM repeater inputs and outputs (local option)"), (445.0, 447.0, "shared by local option (simplex in many areas)"),
    (446.0, 446.0, "national FM simplex calling frequency"), (447.0, 450.0, "FM repeater inputs and outputs (local option)"),
]

BANDS = [("160 m", 1.8, 2.0), ("80 m", 3.5, 4.0), ("60 m", 5.33, 5.41), ("40 m", 7.0, 7.3), ("30 m", 10.1, 10.15),
         ("20 m", 14.0, 14.35), ("17 m", 18.068, 18.168), ("15 m", 21.0, 21.45), ("12 m", 24.89, 24.99),
         ("10 m", 28.0, 29.7), ("6 m", 50.0, 54.0), ("2 m", 144.0, 148.0), ("1.25 m", 219.0, 225.0),
         ("70 cm", 420.0, 450.0), ("33 cm", 902.0, 928.0), ("23 cm", 1240.0, 1300.0)]


def band(f) -> str | None:
    f = float(f)
    return next((n for n, a, b in BANDS if a <= f <= b), None)


def kind_of(mode: str | None) -> str:
    """A radio mode -> the 97.305 kind: phone (FM, AM, SSB), data (VARA, packet, FT8, RTTY), cw."""
    m = (mode or "").upper()
    return "cw" if m == "CW" else "data" if m in ("DIG", "DATA", "VARA", "PKT", "RTTY", "FT8", "PSK") else "phone"


def _sixty(f: float, kind: str, cls: str) -> tuple[bool | None, str]:
    if cls == "technician":
        return False, "60 m is not a Technician band"
    for c in SIXTY_M:
        if kind == "phone" and abs(f - (c - 0.0015)) <= 0.0002:
            return True, f"60 m channel {c:.4f} (USB dial {c - 0.0015:.4f})"
        if abs(f - c) <= (0.0016 if kind == "phone" else 0.0002):
            return True, f"60 m channel {c:.4f}" + (" (USB only)" if kind == "phone" else ": data and CW at the centre")
    return False, f"{f:.4f} MHz is not one of the five 60 m channels"


def privileges(freq_mhz, kind: str, license_class: str | None) -> tuple[bool | None, str]:
    """(ok, why) for transmitting `kind` (phone / data / cw) on freq_mhz. None = can't tell (no frequency, no class)."""
    if not freq_mhz:
        return None, "no frequency known"
    if not license_class:
        return None, "the operator's license class is not set (Settings → Station agent)"
    cls = str(license_class).lower()
    if cls not in ALLOC:
        return None, f"unknown license class {license_class!r}"
    kind = kind if kind in KINDS else "phone"
    f = float(freq_mhz)
    if 5.3 <= f <= 5.41:
        return _sixty(f, kind, cls)
    if any(a <= f <= b for a, b in ALLOC[cls][kind]):
        return True, f"{f:.3f} MHz is inside {cls.title()} {kind} privileges"
    if any(a <= f <= b for a, b in ALLOC[cls]["cw"]) and kind != "cw":
        where = "the CW / data segment" if kind == "phone" else "the phone segment"
        return False, f"{f:.3f} MHz is in {where}: no {kind} there for a {cls.title()} (97.305)"
    return False, f"{f:.3f} MHz is outside {cls.title()} privileges (97.301)"


def segment(freq_mhz) -> dict | None:
    """What the band plan sets this frequency aside for: the most specific entry, and every entry it falls in.
    {"band", "what", "all": [...], "auto_data": bool, "warn": bool (beacons, satellites, APRS: do not talk there)}."""
    if not freq_mhz:
        return None
    f = float(freq_mhz)
    hits = [(b - a, w) for a, b, w in PLAN if a - 0.0005 <= f <= b + 0.0005]
    hits.sort()
    whats = [w for _, w in hits]
    return {"band": band(f), "what": whats[0] if whats else None, "all": whats,
            "auto_data": any(a <= f <= b for a, b in AUTO_DATA),
            "warn": any("do not" in w for w in whats)}


def check(freq_mhz, mode: str | None, license_class: str | None) -> dict:
    """Everything a transmit path wants to know: {"ok": True/False/None, "why", "kind", "segment"}. ok is False for a
    frequency outside the class's privileges, and also for one the band plan reserves (beacons, satellite, APRS)."""
    kind = kind_of(mode)
    ok, why = privileges(freq_mhz, kind, license_class)
    seg = segment(freq_mhz)
    if ok and seg and seg["warn"] and not (kind == "data" and "APRS" in (seg["what"] or "")):
        ok, why = False, f"{why}, but the band plan says: {seg['what']}"
    return {"ok": ok, "why": why, "kind": kind, "segment": seg}


def table(license_class: str | None = None) -> list[dict]:
    """The bands for the dashboard's band plan view: each band's edges, this class's phone / data / CW segments in
    it, and the band plan entries."""
    out = []
    cls = (license_class or "").lower()
    for name, a, b in BANDS:
        mine = {k: [(x, y) for x, y in ALLOC[cls][k] if a <= x and y <= b] for k in KINDS} if cls in ALLOC else None
        if name == "60 m" and cls in ALLOC and cls != "technician":
            mine = {k: [(c - 0.0014, c + 0.0014) for c in SIXTY_M] for k in KINDS}
        out.append({"band": name, "from": a, "to": b, "mine": mine,
                    "plan": [{"from": x, "to": y, "what": w} for x, y, w in PLAN if a <= x <= b]})
    return out
