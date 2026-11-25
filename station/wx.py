"""Weather and band conditions for Einstein's reports (station/einstein.py), from public sources with no key:

* a place -> (lat, lon): a Maidenhead grid square, a US ZIP (the Census gazetteer already on the station,
  hamkit/zipgeo.py), "lat, lon", or a place name (Open-Meteo's free geocoder; only the name asked for is sent);
* the forecast and active alerts: the US National Weather Service (api.weather.gov) inside the US, Open-Meteo
  elsewhere;
* space weather for HF: NOAA SWPC's planetary K index and NOAA scales, the 10.7 cm flux (station/hfprop.py).

Nothing about the station is sent: a request carries only the place asked for (rounded to 0.01 degree, ~1 km) and a
generic program name. Every function takes `fetch` (url -> parsed JSON) so tests run without the network. Results
are plain dicts; einstein.py words them and puts them in an ICS-213.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

UA = "HAM-Sidekick-Station (amateur radio weather report)"
TIMEOUT_S = 10


def _fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/geo+json, application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read())


def grid_latlon(grid: str) -> tuple[float, float] | None:
    from hamkit.zipgeo import grid_to_latlon
    return grid_to_latlon(grid) if re.fullmatch(r"[A-Ra-r]{2}\d{2}([A-Xa-x]{2})?", str(grid or "").strip()) else None


def place(text: str, fetch=None, zipgeo=None) -> dict | None:
    """{"lat", "lon", "label", "us": bool | None} for a grid square, ZIP, "lat, lon" or a place name; None if unknown."""
    t = " ".join(str(text or "").split())[:80]
    if not t:
        return None
    g = grid_latlon(t)
    if g:
        return {"lat": g[0], "lon": g[1], "label": f"grid {t.upper()}", "us": None}
    m = re.fullmatch(r"(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)", t)
    if m:
        la, lo = float(m.group(1)), float(m.group(2))
        if -90 <= la <= 90 and -180 <= lo <= 180:
            return {"lat": la, "lon": lo, "label": f"{la:.2f}, {lo:.2f}", "us": None}
    if re.fullmatch(r"\d{5}", t):
        try:
            if zipgeo is None:
                from hamkit.zipgeo import ZipGeo
                zipgeo = ZipGeo()
            w = zipgeo.where(t)
        except Exception:  # noqa: BLE001 - no gazetteer on this PC
            w = None
        if w:
            return {"lat": w[0], "lon": w[1], "label": f"ZIP {t}", "us": True}
    name, _, region = t.partition(",")
    q = urllib.parse.urlencode({"name": name.strip(), "count": 10, "language": "en", "format": "json"})
    try:
        res = (fetch or _fetch)("https://geocoding-api.open-meteo.com/v1/search?" + q).get("results") or []
    except Exception:  # noqa: BLE001
        return None
    region = region.strip().lower()
    if region:                                   # "Springfield, IL" / "Springfield, Illinois" / "Paris, France"
        st = US_STATES.get(region.upper(), region)
        res = [r for r in res if st in (str(r.get("admin1", "")).lower(), str(r.get("country", "")).lower(),
                                        str(r.get("country_code", "")).lower())] or res
    if not res:
        return None
    r = res[0]
    label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country_code")) if x)
    return {"lat": float(r["latitude"]), "lon": float(r["longitude"]), "label": label,
            "us": str(r.get("country_code", "")).upper() == "US"}


def forecast(p: dict, fetch=None, periods: int = 4) -> dict:
    """{"source", "place", "periods": [{"name", "text", "temp", "wind"}], "alerts": [{"event", "severity",
    "headline", "until"}]} for a place from place()."""
    fetch = fetch or _fetch
    lat, lon = round(p["lat"], 2), round(p["lon"], 2)
    if p.get("us") is not False:
        try:
            pt = fetch(f"https://api.weather.gov/points/{lat},{lon}")["properties"]
            fc = fetch(pt["forecast"])["properties"]["periods"][:periods]
            al = fetch(f"https://api.weather.gov/alerts/active?point={lat},{lon}").get("features") or []
            rel = (pt.get("relativeLocation") or {}).get("properties") or {}
            where = ", ".join(x for x in (rel.get("city"), rel.get("state")) if x) or p.get("label")
            return {"source": "US National Weather Service (api.weather.gov)", "place": where,
                    "periods": [{"name": x.get("name", ""), "text": x.get("detailedForecast") or x.get("shortForecast", ""),
                                 "temp": f"{x.get('temperature')} {x.get('temperatureUnit', '')}".strip(),
                                 "wind": f"{x.get('windSpeed', '')} {x.get('windDirection', '')}".strip()} for x in fc],
                    "alerts": [{"event": (a.get("properties") or {}).get("event", ""),
                                "severity": (a.get("properties") or {}).get("severity", ""),
                                "headline": (a.get("properties") or {}).get("headline", ""),
                                "until": (a.get("properties") or {}).get("ends") or (a.get("properties") or {}).get("expires", "")}
                               for a in al[:5]]}
        except Exception:  # noqa: BLE001 - outside the NWS area (or it is down): Open-Meteo below
            pass
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
                                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
                                         "wind_speed_10m_max,wind_gusts_10m_max",
                                "current": "temperature_2m,wind_speed_10m,weather_code"})
    d = fetch("https://api.open-meteo.com/v1/forecast?" + q)
    dl = d.get("daily") or {}
    u = d.get("daily_units") or {}
    out = []
    for i, day in enumerate(dl.get("time") or []):
        out.append({"name": day, "text": f"{WMO.get(int(dl['weather_code'][i]), 'weather code ' + str(dl['weather_code'][i]))}; "
                                         f"precipitation {dl['precipitation_sum'][i]} {u.get('precipitation_sum', 'mm')}",
                    "temp": f"high {dl['temperature_2m_max'][i]}, low {dl['temperature_2m_min'][i]} {u.get('temperature_2m_max', '')}",
                    "wind": f"{dl['wind_speed_10m_max'][i]} {u.get('wind_speed_10m_max', '')}, gusts {dl['wind_gusts_10m_max'][i]}"})
    return {"source": "Open-Meteo (open-meteo.com)", "place": p.get("label", ""), "periods": out[:periods], "alerts": []}


_SEV = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}


def alerts(p: dict, fetch=None) -> dict:
    """The active US National Weather Service alerts for a place from place(), most severe first (owner 2026-11-25:
    "What are the urgent weather warnings for my area?"): {"source", "place", "us": bool, "alerts": [{"event",
    "severity", "urgency", "headline", "until", "area", "do"}]}. Outside the US: us False, no alerts (the NWS does not
    cover it). Raises when the NWS cannot be reached."""
    fetch = fetch or _fetch
    lat, lon = round(p["lat"], 2), round(p["lon"], 2)
    where = p.get("label") or f"{lat}, {lon}"
    if p.get("us") is False:
        return {"source": "", "place": where, "us": False, "alerts": []}
    try:
        rel = ((fetch(f"https://api.weather.gov/points/{lat},{lon}")["properties"].get("relativeLocation") or {})
               .get("properties") or {})
        where = ", ".join(x for x in (rel.get("city"), rel.get("state")) if x) or where
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):                         # not a point the NWS covers
            return {"source": "", "place": where, "us": False, "alerts": []}
        raise
    al = fetch(f"https://api.weather.gov/alerts/active?point={lat},{lon}").get("features") or []
    out = []
    for a in al:
        q = a.get("properties") or {}
        do = " ".join(str(q.get("instruction") or "").split())
        out.append({"event": q.get("event", ""), "severity": q.get("severity", ""), "urgency": q.get("urgency", ""),
                    "headline": " ".join(str(q.get("headline") or "").split()),
                    "until": q.get("ends") or q.get("expires") or "", "area": q.get("areaDesc", ""), "do": do})
    out.sort(key=lambda x: _SEV.get(x["severity"], 9))
    return {"source": "US National Weather Service (api.weather.gov)", "place": where, "us": True, "alerts": out[:6]}


# ---- all hazards for a place (owner 2026-11-25: "all emergency alerts like bad weather, earthquakes, flooding, fire,
# chemical spill ... biological hazards and any other hazards"). Feeds checked live 2026-11-25:
#   NWS alerts          weather, flood, tsunami, AND the civil messages authorities issue through it: Hazardous
#                       Materials, Radiological Hazard, Nuclear Power Plant, Civil Danger / Emergency, Local Area
#                       Emergency, Evacuation Immediate, Shelter In Place, Fire Warning, Earthquake Warning, 911 outage
#   USGS earthquakes    fdsnws event query by distance (worldwide)
#   NIFC wildfires      WFIGS current incident locations (US; prescribed burns left out)
#   USGS volcanoes      HANS elevated volcanoes (US)
#   Open-Meteo          US air-quality index (worldwide)
# Not used: FEMA's public IPAWS archive runs about a day behind; CDC's Health Alert Network feed is empty. There is no
# public live feed of chemical or biological releases: they show only when an authority issues an alert.
QUAKE_KM, QUAKE_MAG, QUAKE_H = 160, 3.0, 24
FIRE_KM, VOLCANO_KM, AQI_BAD = 80, 500, 101
CIVIL = re.compile(r"hazardous materials|radiological|nuclear|civil|local area emergency|evacuat|shelter in place|"
                   r"911|law enforcement|child abduction|blue alert|earthquake warning|volcano|fire warning", re.I)
_VOLC: dict[str, tuple[float, float]] = {}


def km_between(a: float, b: float, c: float, d: float) -> float:
    import math
    p, q = math.radians(a), math.radians(c)
    h = math.sin((q - p) / 2) ** 2 + math.cos(p) * math.cos(q) * math.sin(math.radians(d - b) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


def _quakes(lat, lon, fetch, now=None) -> list[dict]:
    from datetime import datetime, timedelta, timezone
    now = now or datetime.now(timezone.utc)
    q = urllib.parse.urlencode({"format": "geojson", "latitude": lat, "longitude": lon, "maxradiuskm": QUAKE_KM,
                                "minmagnitude": QUAKE_MAG, "orderby": "time", "limit": 8,
                                "starttime": (now - timedelta(hours=QUAKE_H)).strftime("%Y-%m-%dT%H:%M:%S")})
    out = []
    for f in fetch("https://earthquake.usgs.gov/fdsnws/event/1/query?" + q).get("features") or []:
        pr, g = f.get("properties") or {}, (f.get("geometry") or {}).get("coordinates") or [None, None]
        out.append({"mag": pr.get("mag"), "where": pr.get("place") or "", "at": (pr.get("time") or 0) / 1000,
                    "tsunami": bool(pr.get("tsunami")),
                    "km": km_between(lat, lon, g[1], g[0]) if g[0] is not None else None})
    return out


def _fires(lat, lon, fetch, now=None) -> list[dict]:
    import time as _t
    now = now or _t.time()
    q = urllib.parse.urlencode({"where": "IncidentTypeCategory='WF'", "geometry": f"{lon},{lat}",
                                "geometryType": "esriGeometryPoint", "inSR": 4326, "outSR": 4326,
                                "spatialRel": "esriSpatialRelIntersects", "distance": FIRE_KM, "units": "esriSRUnit_Kilometer",
                                "outFields": "IncidentName,IncidentSize,PercentContained,FireDiscoveryDateTime,POOCounty",
                                "returnGeometry": "true", "f": "json", "resultRecordCount": 60})
    d = fetch("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Incident_Locations_Current/"
              "FeatureServer/0/query?" + q)
    if d.get("error"):
        raise ValueError(str(d["error"])[:120])
    out = []
    for f in d.get("features") or []:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        size, born = a.get("IncidentSize"), (a.get("FireDiscoveryDateTime") or 0) / 1000
        if not ((size or 0) >= 10 or now - born < 48 * 3600):      # a small old one is out: not news
            continue
        out.append({"name": " ".join(str(a.get("IncidentName") or "").split()).title(), "acres": size,
                    "contained": a.get("PercentContained"), "county": a.get("POOCounty") or "",
                    "km": km_between(lat, lon, g["y"], g["x"]) if "y" in g else None})
    out.sort(key=lambda x: (x["km"] is None, x["km"] or 0))
    return out[:5]


def _volcanoes(lat, lon, fetch) -> list[dict]:
    out = []
    for v in (fetch("https://volcanoes.usgs.gov/hans-public/api/volcano/getElevatedVolcanoes") or [])[:12]:
        n = str(v.get("vnum") or "")
        if n not in _VOLC:
            w = fetch("https://volcanoes.usgs.gov/hans-public/api/volcano/getVolcano/" + urllib.parse.quote(n))
            _VOLC[n] = (float(w["latitude"]), float(w["longitude"]))
        km = km_between(lat, lon, *_VOLC[n])
        if km <= VOLCANO_KM:
            out.append({"name": v.get("volcano_name") or "", "level": str(v.get("alert_level") or "").title(),
                        "color": str(v.get("color_code") or "").lower(), "km": km})
    return out


def _air(lat, lon, fetch) -> dict:
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "current": "us_aqi,pm2_5"})
    c = fetch("https://air-quality-api.open-meteo.com/v1/air-quality?" + q).get("current") or {}
    return {"aqi": c.get("us_aqi"), "pm25": c.get("pm2_5")}


def hazards(p: dict, fetch=None) -> dict:
    """Everything urgent for a place from place(): {"place", "us", "official": [alerts(), each + "civil": bool],
    "quakes", "fires", "volcanoes", "air", "failed": [what could not be reached], "skipped": [what does not cover it]}.
    Each feed is asked on its own, at the same time: one that is down is named, the others still answer."""
    from concurrent.futures import ThreadPoolExecutor
    fetch = fetch or _fetch
    lat, lon = round(p["lat"], 3), round(p["lon"], 3)
    jobs = {"official": lambda: alerts(p, fetch), "quakes": lambda: _quakes(lat, lon, fetch),
            "fires": lambda: _fires(lat, lon, fetch), "volcanoes": lambda: _volcanoes(lat, lon, fetch),
            "air": lambda: _air(lat, lon, fetch)}
    got, failed = {}, []
    with ThreadPoolExecutor(max_workers=5) as ex:
        fut = {k: ex.submit(f) for k, f in jobs.items()}
        for k, f in fut.items():
            try:
                got[k] = f.result(timeout=TIMEOUT_S + 10)
            except Exception:  # noqa: BLE001 - that feed is down or does not cover the place
                failed.append(k)
    off = got.get("official") or {"place": p.get("label") or f"{lat}, {lon}", "us": None, "alerts": []}
    us = off.get("us")
    skipped = [k for k in ("official", "fires", "volcanoes") if us is False]
    for a in off["alerts"]:
        a["civil"] = bool(CIVIL.search(a["event"]))
    off["alerts"].sort(key=lambda x: (_SEV.get(x["severity"], 9), not x["civil"]))
    return {"place": off["place"], "us": us, "official": off["alerts"], "quakes": got.get("quakes") or [],
            "fires": [] if us is False else got.get("fires") or [], "volcanoes": got.get("volcanoes") or [],
            "air": got.get("air") or {}, "failed": [k for k in failed if k not in skipped], "skipped": skipped}


def space(fetch=None, cache: dict | None = None) -> dict:
    """{"sfi", "kp", "scales": "R0 S0 G0", "source"}: what HF propagation is doing now."""
    from . import hfprop
    fetch = fetch or _fetch
    sfi, _ = hfprop.solar_flux(cache if cache is not None else {}, fetch=fetch)
    kp = scales = None
    try:
        rows = fetch("https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json")
        kp = float(rows[-1][1])
    except Exception:  # noqa: BLE001
        pass
    try:
        s = fetch("https://services.swpc.noaa.gov/products/noaa-scales.json")["0"]
        scales = " ".join(f"{k}{(s.get(k) or {}).get('Scale') or 0}" for k in ("R", "S", "G"))
    except Exception:  # noqa: BLE001
        pass
    return {"sfi": sfi, "kp": kp, "scales": scales, "source": "NOAA Space Weather Prediction Center"}


def conditions_words(s: dict) -> str:
    """Space weather in an operator's words."""
    kp, sfi = s.get("kp"), s.get("sfi")
    parts = [f"Solar flux {sfi:.0f}" if sfi else "Solar flux unknown"]
    if kp is not None:
        parts.append(f"planetary K index {kp:.0f} ({'quiet' if kp < 3 else 'unsettled' if kp < 4 else 'active' if kp < 5 else 'storm'})")
    if s.get("scales"):
        parts.append(f"NOAA scales {s['scales']}")
    hint = ("the higher HF bands (15-10 m) should be open in daylight" if (sfi or 0) >= 150 else
            "20 m is the daytime workhorse; 40 and 80 m at night" if (sfi or 0) >= 90 else
            "a low sun: 40 and 80 m are the dependable bands")
    if kp is not None and kp >= 5:
        hint = "a geomagnetic storm: expect HF absorption and poor high-latitude paths; VHF/UHF unaffected"
    return "; ".join(parts) + f". In short: {hint}."


WMO = {0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
       66: "freezing rain", 67: "heavy freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
       80: "rain showers", 81: "heavy rain showers", 82: "violent rain showers", 85: "snow showers",
       86: "heavy snow showers", 95: "thunderstorms", 96: "thunderstorms with hail", 99: "severe thunderstorms with hail"}

US_STATES = {"AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california", "CO": "colorado",
             "CT": "connecticut", "DE": "delaware", "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho",
             "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas", "KY": "kentucky", "LA": "louisiana",
             "ME": "maine", "MD": "maryland", "MA": "massachusetts", "MI": "michigan", "MN": "minnesota",
             "MS": "mississippi", "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
             "NH": "new hampshire", "NJ": "new jersey", "NM": "new mexico", "NY": "new york", "NC": "north carolina",
             "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon", "PA": "pennsylvania",
             "RI": "rhode island", "SC": "south carolina", "SD": "south dakota", "TN": "tennessee", "TX": "texas",
             "UT": "utah", "VT": "vermont", "VA": "virginia", "WA": "washington", "WV": "west virginia",
             "WI": "wisconsin", "WY": "wyoming", "DC": "district of columbia", "PR": "puerto rico"}
