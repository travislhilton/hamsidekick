"""The operator's units for distances (owner 2026-11-25: "a global setting for user preference for distances in mi or
km and then everything should be calculated and displayed accordingly. Default to km units").

Everything is kept in kilometres and metres; this converts only what is shown or typed. Settings -> Station -> Units:
"km" (kilometres and metres, the default) or "mi" (miles and feet).
"""
from __future__ import annotations

KM_PER_MI = 1.609344
M_PER_FT = 0.3048
UNITS = ("km", "mi")


def of(st) -> str:
    """This station's choice ("km" unless the operator chose "mi")."""
    try:
        u = st.units()
    except Exception:  # noqa: BLE001
        u = None
    return u if u in UNITS else "km"


def num(km, unit: str = "km") -> float:
    return float(km) / KM_PER_MI if unit == "mi" else float(km)


def dist(km, unit: str = "km", nd: int = 0) -> str:
    """"1,243 mi" / "2,000 km" (None -> "distance unknown")."""
    if km is None:
        return "distance unknown"
    return f"{num(km, unit):,.{nd}f} {unit}"


def round_to(km, unit: str = "km", step: int = 5) -> str:
    """A round figure for a limit ("within 100 mi" for 160 km)."""
    return f"{round(num(km, unit) / step) * step:,} {unit}"


def to_km(value, unit: str = "km") -> float:
    return float(value) * KM_PER_MI if unit == "mi" else float(value)


def height(m, unit: str = "km") -> str:
    return f"{float(m) / M_PER_FT:.0f} ft" if unit == "mi" else f"{float(m):g} m"
