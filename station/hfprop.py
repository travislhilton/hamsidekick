"""Will this HF setup hear a net, and be heard checking in? (Nets -> Find nets; station/netfind.py)

A small sky-wave model, not a forecast. It works out, for the net's frequency, distance and local hour:

  the path    hops of at most ~3,800 km off the F2 layer (300 km up); each hop's takeoff angle from geometry
  the layer   foF2 from the solar flux (NOAA's daily 10.7 cm flux when the PC is online, else a typical 130) and the
              hour (mid-latitudes; season ignored); the MUF = foF2 x the secant of the angle the wave meets the layer
  the losses  free-space spreading over the slanted path, D-layer absorption by day (falls with 1/(f+1.4)^2, grows with
              a low angle), ground reflections between hops, a fixed excess loss, and the band's noise
  the antenna its gain AT THAT TAKEOFF ANGLE: a horizontal antenna's pattern from its height in wavelengths over ground
              (a low dipole fires straight up: NVIS; a high one fires low: distance), a vertical's low-angle pattern
              and ground losses, a whip's poor efficiency on the low bands, a beam only on 20-10 m

"Hear": net control's 100 W into a dipole at 15 m, into this antenna (on HF a weak antenna also hears less band noise,
so a poor receive antenna costs less than it does on transmit). "Check in": this station's power and antenna, heard on
net control's dipole. SNR 12 dB and up = likely, 3-12 = maybe, below = unlikely; the percentage allows for conditions
varying several dB from night to night.

Long paths (owner 2026-11-14: "at certain times of the day I can hear Japan, China, Antarctica, Russia, South
America"): with both ends known, every hop has its own control point on the great circle, each with its own sun
(as ITU-R P.533 does): the path's MUF is the lowest hop's, the D-layer absorption is summed hop by hop (a path half
in darkness loses only on its sunlit half: the gray line), hops through the auroral oval (60-75 deg geomagnetic) lose
more, and the long path round the other side of the earth is tried too. `reach_table` runs that for world regions x
bands x hours: what this station can hear, when, before any search.
"""
from __future__ import annotations

import json
import math
import time
import urllib.request

R = 6371.0
H_F2 = 300.0
H_D = 80.0
MIN_TAKEOFF = 3.0
EXCESS_DB = 6.0              # polarization, defocusing, deviative losses (ITU-R P.533's system loss is ~6-9 dB)
RESIDUAL_K = 650.0           # + K/(f+1.4)^2 once per path: the absorption left at night (E / lower F region): 24 dB
#                              on 80 m, 9 on 40, 3 on 20. Together: 100 W dipoles over 500 km at night on 80 m ~S8, as
#                              before (2026-11-14: the flat 30 dB that did that closed every 20 m DX path)
GROUND_DB = 1.0              # per ground reflection between hops, on land
SEA_DB = 0.3                 # ... on sea water (ground_loss; the land / sea map is station/landmask.py)
GRAY_DEG = 8.0               # the sun within this many degrees of the horizon at an end of the path: the gray line
NCS = {"antenna": "dipole", "height_m": 15.0, "power_w": 100.0}
TYPICAL_SFI = 130.0

# Antenna figures (researched 2026-11-14; NEC-4 models by L. B. Cebik, ARRL Antenna Book, N6LF's QEX ground-system
# measurements, Zavrel QEX 2016, 49:1 transformer loss measurements): every gain is dBi averaged over azimuth.
#   horizontal wires: direct + ground-reflected wave (reflection 0.75 below 8 MHz, 0.85 from 14 MHz; real ground never
#     cancels fully: a 0.04-wave dipole still gives ~-0.5 dBi straight up). Calibrated: dipole 0.2 wave up ~6.4 dBi at
#     the zenith; 0.5 wave ~7 dBi at 28 deg; 1 wave ~8 dBi at 14 deg.
#   inverted V: a dipole at ~0.8 x apex height, -0.7 dB, its end nulls filled (azimuth -1 dB, not -2)
#   end-fed half wave: a dipole at its mean height, 49:1 transformer and feed -1.5 dB (-2 on 80 m)
#   random / long wire + tuner: dipole-like at its height, -3 dB (-5 on 80 m) tuner and coax losses
#   horizontal loop: +0.8 dB over a dipole, nearly round (-0.5); NVIS dipole + reflector: +0.5 dB
#   vertical (16+ radials): peak 0 / +1.5 / +4.5 dBi at 26 / 18 / 5 deg over average / good / salt water ground
#     (poor: -0.5 dBi at 29 deg); 0.25-0.35 dB per degree lost below the peak; cos above; nothing straight up
#   vertical delta loop (corner fed): a vertical pattern, +1.5 dB, peak ~20 deg
#   whip: a vertical pattern with -17 / -11 / -4 dB efficiency on 80 / 40 / 20 m (8 ft class, mobile), a car body
#     still fills high angles to 10 dB under the peak
#   beam: 3-element Yagi 7.7 dBi free space (hex beam 6.5), aimed at the net; useless below 20 m
# id: (label, kind, free-space gain dBi, overall adjustment dB, azimuth penalty dB at low angles)
ANTENNAS = {
    "dipole": ("Dipole (flat)", "h", 2.15, 0.0, -2.0),
    "invv": ("Inverted V", "h", 2.15, -0.7, -1.0),
    "efhw": ("End-fed half wave", "h", 2.15, -1.5, -2.0),
    "random": ("Random or long wire with a tuner", "h", 2.15, -3.0, -1.0),
    "loop": ("Horizontal loop (skyloop)", "h", 2.95, 0.0, -0.5),
    "nvis": ("NVIS antenna (low dipole over a reflector)", "h", 2.15, 0.5, -0.5),
    "vertical": ("Vertical with radials", "v", 0.0, -1.0, 0.0),
    "delta": ("Vertical delta loop or quad (corner fed)", "v", 1.5, 0.0, -1.0),
    "beam": ("Beam / Yagi (20-10 m)", "h", 7.7, 0.0, 0.0),
    "hexbeam": ("Hex beam (20-6 m)", "h", 6.5, 0.0, 0.0),
    "whip": ("Mobile or portable whip", "w", 0.0, -1.0, 0.0),
}
GROUNDS = {"poor": ("Poor (dry, rocky, city)", -0.5, 29.0, 0.35), "average": ("Average", 0.0, 26.0, 0.25),
           "good": ("Good (moist farmland)", 1.5, 18.0, 0.2), "salt": ("Salt water", 4.5, 5.0, 0.05)}
DEFAULT = {"antenna": "efhw", "height_m": 10.0, "ground": "average"}
OLD_IDS = {"dipole_low": ("dipole", 6.0), "dipole_high": ("dipole", 20.0)}   # the first Find nets build's choices


def band_of(f: float) -> str:
    return "160 m" if f < 2.2 else "80 m" if f < 4.5 else "60 m" if f < 6 else "40 m" if f < 7.5 else "30 m" \
        if f < 11 else "20 m" if f < 15 else "17 m" if f < 19 else "15 m" if f < 22 else "12 m" if f < 25 else "10 m"


# ---------------------------------------------------------------- the antenna -----------------------------------
def _rho(f: float) -> float:
    return 0.75 if f < 8 else 0.85 if f >= 14 else 0.75 + 0.1 * (f - 8) / 6


def _whip_eff(f: float) -> float:
    """dB: an 8 ft class mobile whip, -17 / -11 / -4 dB at 3.9 / 7.2 / 14.2 MHz (log-interpolated)."""
    pts = ((1.9, -24.0), (3.9, -17.0), (7.2, -11.0), (14.2, -4.0), (28.5, -1.0))
    if f <= pts[0][0]:
        return pts[0][1]
    for (f1, g1), (f2, g2) in zip(pts, pts[1:]):
        if f <= f2:
            return g1 + (g2 - g1) * math.log(f / f1) / math.log(f2 / f1)
    return pts[-1][1]


WIRE_FLOOR = {"dipole": 0.1, "invv": 0.32, "efhw": 0.2, "random": 0.25}     # how deep the nulls off the ends go


def gain(antenna: str, f: float, height_m: float, theta: float, ground: str = "average",
         off_broadside: float | None = None) -> float:
    """dBi at elevation `theta` degrees. Averaged over azimuth unless `off_broadside` is given: the angle (0-90
    degrees) between the path and the wire's broadside, for a straight wire whose direction the operator set. A
    wire fires best at right angles to itself at low angles; a low wire (under about 0.15 wavelength) and any wire
    at high angles fire the same all round. A beam is aimed."""
    _, kind, g0, adj, az = ANTENNAS.get(antenna, ANTENNAS[DEFAULT["antenna"]])
    lam = 300.0 / f
    deg = max(0.5, min(90.0, theta))
    th = math.radians(deg)
    if antenna in ("beam", "hexbeam") and f < 13.9:
        return -25.0                                               # a 20-10 m beam is no antenna on 40 or 80 m
    low = max(0.0, min(1.0, (60.0 - deg) / 45.0))                  # end nulls matter at low angles, not overhead
    azp = az * low
    if off_broadside is not None and antenna in WIRE_FLOOR:
        tall = max(0.0, min(1.0, (max(1.0, height_m) / lam - 0.15) / 0.25))
        pat = 20 * math.log10(max(WIRE_FLOOR[antenna], abs(math.cos(math.radians(off_broadside)))))
        azp = low * tall * pat + az * low * (1 - tall)
    if kind == "h":                                                # horizontal over ground: direct + reflected wave
        h = max(1.0, height_m) * (0.8 if antenna == "invv" else 1.0)
        rho = _rho(f)
        h += (0.03 if f < 8 else 0.02) * lam                       # real ground reflects from a little below it
        ph = 4 * math.pi * h / lam * math.sin(th)
        af_db = 10 * math.log10(max(1e-6, 1 + rho * rho - 2 * rho * math.cos(ph)))
        af_db = max(af_db, -2.7) if deg > 45 else af_db            # real ground: a very low wire still radiates up
        extra = (-0.5 if f < 4.5 else 0.0) if antenna == "efhw" else (-2.0 if f < 4.5 else 0.0) if antenna == "random" else 0.0
        return g0 + adj + extra + af_db + azp
    gname, gpk, tpk, roll = GROUNDS.get(ground, GROUNDS["average"])
    if antenna == "delta":
        tpk = min(tpk, 20.0)
    peak = gpk + g0 + adj
    if deg >= tpk:
        g = peak + 20 * math.log10(max(0.03, math.cos(th) / math.cos(math.radians(tpk))))
    else:
        g = peak - roll * (tpk - deg)
    if kind == "w":
        g = max(g, peak - 10.0) + _whip_eff(f)                     # the car body fills high angles
    return g + azp


def measured_gain(good_km: tuple[float, float], theta: float) -> float:
    """The operator's own antenna, from where they hear stations well ("hops of 400-600 km"): full gain between the
    takeoff angles of those hop lengths, falling off above (too steep: the skip zone close in) and below (too low)."""
    lo, hi = sorted(good_km)
    t_hi, t_lo = takeoff(hi), takeoff(lo)                         # longer hop = lower angle
    g = 2.0
    if theta > t_lo:
        g -= 0.8 * (theta - t_lo)                                 # steeper than the sweet spot: falls fast
    elif theta < t_hi:
        g -= 0.6 * (t_hi - theta)
    return max(-25.0, g)


# ---------------------------------------------------------------- the ionosphere ----------------------------------
def _day(hour: float) -> float:
    return max(0.0, math.sin(math.pi * (hour - 6.0) / 13.0))      # 0 at night, 1 early afternoon (06:00-19:00)


def _f2_day(hour: float) -> float:
    """The F2 layer builds after sunrise and decays for hours after sunset (unlike the D layer, gone at dusk)."""
    h = hour % 24
    if 6 <= h <= 19:
        return _day(h) ** 0.7
    after = (h - 19) if h > 19 else (h + 5)                       # hours since 19:00
    return 0.45 * math.exp(-after / 2.5)


def fof2(hour: float, sfi: float, sun: dict | None = None) -> float:
    night, day = 2.2 + 0.012 * sfi, 3.5 + 0.035 * sfi
    if sun:                                                       # the real sun over the path, and the season
        night, day = night * sun["night_x"], day * sun["day_x"]
        return night + (day - night) * sun["f2"]
    return night + (day - night) * _f2_day(hour)


# ---------------------------------------------------------------- the sun over the path, on the net's date ---------
def solar_zenith(when_utc, lat: float, lon: float) -> float:
    """Degrees from straight up (NOAA's low-precision formula: good to a fraction of a degree)."""
    doy = when_utc.timetuple().tm_yday
    hr = when_utc.hour + when_utc.minute / 60
    g = 2 * math.pi / 365 * (doy - 1 + (hr - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g)
                    - 0.040849 * math.sin(2 * g))
    tst = hr * 60 + eqt + 4 * lon
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    c = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def sun_over(when_utc, lat: float, lon: float) -> dict:
    """What the sun does to the layers at the path's midpoint at the net's time:
    d     D-layer absorption factor: cos(zenith)^0.75 while the sun is up, ~0 after dusk
    f2    F2 ionization factor, from the sun 1.5 h earlier (the layer lags the sun) and decaying for hours after dusk
    day_x / night_x  season: mid-latitude winter days run higher and winter nights lower than summer (the winter anomaly)
    """
    from datetime import timedelta
    z = solar_zenith(when_utc, lat, lon)
    zl = solar_zenith(when_utc - timedelta(hours=1.5), lat, lon)
    d = max(0.0, math.cos(math.radians(z))) ** 0.75
    f2 = max(0.0, math.cos(math.radians(zl))) ** 0.3 if zl < 90 else 0.45 * math.exp(-(zl - 90) / 28)
    # ^0.3: a Chapman layer's peak density goes as cos(zenith)^0.5, foF2 as its square root (was ^0.6, which left
    # winter days at 50 deg N at half their foF2 and closed 15-20 m to Europe at midday)
    doy = when_utc.timetuple().tm_yday
    winter = math.cos(2 * math.pi * (doy - 15) / 365) * (1 if lat >= 0 else -1)   # +1 mid-January (north)
    return {"zenith": z, "d": d, "f2": max(f2, 0.0), "day_x": 1 + 0.15 * winter, "night_x": 1 - 0.25 * winter,
            "sun_up": z < 90}


GEOMAG_POLE = (80.8, -72.6)      # the north geomagnetic pole (IGRF-14 dipole, 2025)
AURORAL_DB = 3.0                 # per hop with its control point in the auroral oval (60-75 deg geomagnetic), quiet sun
POLAR_CAP_DB = 2.0               # per hop inside the polar cap (above 75 deg)
EARTH_KM = 2 * math.pi * R


def geomag_lat(lat: float, lon: float) -> float:
    la, lo = math.radians(lat), math.radians(lon)
    pla, plo = map(math.radians, GEOMAG_POLE)
    return math.degrees(math.asin(math.sin(la) * math.sin(pla) + math.cos(la) * math.cos(pla) * math.cos(lo - plo)))


def bearing(a: tuple, b: tuple) -> float:
    """Initial great-circle bearing from a to b, degrees from north."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def great_circle_km(a: tuple, b: tuple) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(h)))


def destination(a: tuple, brg: float, km: float) -> tuple:
    la1, lo1, b, d = math.radians(a[0]), math.radians(a[1]), math.radians(brg), km / R
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(b))
    lo2 = lo1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(la1), math.cos(d) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), (math.degrees(lo2) + 540) % 360 - 180


def control_points(a: tuple, b: tuple, n: int, long: bool = False) -> list[tuple]:
    """The midpoint of each of n equal hops from a to b (the long way round when `long`)."""
    d = great_circle_km(a, b)
    brg = bearing(a, b)
    if long:
        d, brg = EARTH_KM - d, (brg + 180) % 360
    return [destination(a, brg, d * (i + 0.5) / n) for i in range(n)]


def ground_points(a: tuple, b: tuple, n: int, long: bool = False) -> list[tuple]:
    """Where the signal comes down and bounces between n hops from a to b (n - 1 points)."""
    d = great_circle_km(a, b)
    brg = bearing(a, b)
    if long:
        d, brg = EARTH_KM - d, (brg + 180) % 360
    return [destination(a, brg, d * i / n) for i in range(1, n)]


def ground_loss(a: tuple, b: tuple, n: int, long: bool = False) -> tuple[float, int]:
    """(dB lost at the ground reflections between n hops, how many of them are on sea water). Sea water is close to
    a mirror at HF; land is not (owner 2026-11-25: "when traveling over water/oceans it can bounce many times")."""
    from .landmask import is_land
    pts = ground_points(a, b, n, long)
    sea = sum(1 for p in pts if not is_land(p[0], p[1]))
    return sea * SEA_DB + (len(pts) - sea) * GROUND_DB, sea


def control(when_utc, lat: float, lon: float) -> dict:
    """sun_over at one hop's control point, plus its geomagnetic latitude and what that does to the layers."""
    c = sun_over(when_utc, lat, lon)
    gm = abs(geomag_lat(lat, lon))
    c["gmlat"] = gm
    c["aurora_db"] = AURORAL_DB if 60 <= gm <= 75 else POLAR_CAP_DB if gm > 75 else 0.0
    # foF2 by latitude: the equatorial anomaly crests (~15 deg geomagnetic) run higher by day, high latitudes lower
    c["lat_x"] = 1.15 if 8 <= gm <= 22 and c["sun_up"] else 0.85 if gm >= 67 else 1.0
    return c


def takeoff(hop_km: float, h: float = H_F2) -> float:
    phi = hop_km / (2 * R)
    if phi < 1e-6:
        return 90.0
    return math.degrees(math.atan((math.cos(phi) - R / (R + h)) / math.sin(phi)))


def hops(km: float) -> tuple[int, float]:
    n = 1
    while takeoff(km / n) < MIN_TAKEOFF:
        n += 1
    return n, takeoff(km / n)


def _sec_at(theta: float, h: float) -> float:
    s = R * math.cos(math.radians(theta)) / (R + h)
    return 1 / math.sqrt(max(1e-4, 1 - s * s))


def path(f: float, km: float, hour: float, sfi: float, n: int | None = None, sun: dict | None = None,
         controls: list[dict] | None = None, ground_db: float | None = None) -> dict:
    """The path over `n` hops (None: the fewest the geometry allows). `controls`: one `control()` per hop (a long
    path): the lowest hop's MUF limits the path, absorption and auroral loss add up hop by hop."""
    if n is None:
        n, th = hops(max(20.0, km))
    else:
        th = takeoff(km / n)
    hop = km / n
    a_unit = _sec_at(th, H_D) * 300.0 * (0.6 + 0.004 * sfi) / (f + 1.4) ** 2
    aurora = 0.0
    if controls:
        fo = min(fof2(hour, sfi, c) * c["lat_x"] for c in controls)
        absorb = sum(a_unit * max(0.05, c["d"]) for c in controls)
        aurora = sum(c["aurora_db"] for c in controls)
    else:
        fo = fof2(hour, sfi, sun)
        absorb = n * a_unit * max(0.05, sun["d"] if sun else _day(hour))
    muf = fo * _sec_at(th, H_F2)
    r = f / muf
    muf_db = 0.0 if r <= 0.9 else 3.0 if r <= 1.0 else 12.0 if r <= 1.1 else None
    slant = n * 2 * math.hypot(hop / 2, H_F2)
    spread = 32.45 + 20 * math.log10(f) + 20 * math.log10(slant)
    residual = RESIDUAL_K / (f + 1.4) ** 2
    loss = (spread + absorb + aurora + residual + (GROUND_DB * (n - 1) if ground_db is None else ground_db)
            + EXCESS_DB + (muf_db or 0.0))
    return {"hops": n, "takeoff": th, "fof2": fo, "muf": muf, "absorb": absorb, "aurora": aurora, "loss": loss,
            "open": muf_db is not None}


def noise_dbm(f: float) -> float:
    """Band noise in an SSB bandwidth, a quiet-residential site: about S5 on 80 m, lower going up."""
    return -100.0 - 27.7 * math.log10(f / 3.9)                    # ITU-R P.372 residential slope


def _word(snr: float | None) -> str:
    return "unlikely" if snr is None or snr < 3 else "likely" if snr >= 12 else "maybe"


def chance_pct(snr: float | None) -> int:
    """A rough probability of copying the net on a given night (conditions vary ~±6 dB night to night)."""
    if snr is None:
        return 2
    return max(2, min(98, round(100 / (1 + math.exp(-(snr - 8) / 4)))))


def estimate(f: float, km: float | None, start: str, antenna: str, height_m: float, power_w: float,
             sfi: float = TYPICAL_SFI, good_km: tuple | None = None, when_utc=None, mid: tuple | None = None,
             ground: str = "average", ends: tuple | None = None, wire_deg: float | None = None) -> dict:
    """{"chance": hear, "checkin": be heard, "pct_hear", "pct_send", "why", "band", "takeoff", "gain", "muf", "hops",
    "snr_hear", "snr_send"}. `good_km` = (from, to): where the operator hears stations well; it then defines the
    antenna's pattern instead of the model. The best of 1-6 hops is used (a long path may ride several short hops)."""
    if antenna in OLD_IDS:
        antenna, height_m = OLD_IDS[antenna]
    if antenna not in ANTENNAS:
        antenna = DEFAULT["antenna"]
    good = tuple(sorted(float(x) for x in good_km)) if good_km and all(good_km) else None
    if good and f >= RING_MAX_MHZ:
        good = None       # the ring is what the operator hears on 80 / 40 m; above that the antenna is many
        #                   wavelengths higher and fires low (owner 2026-11-25: Japan on 20-10 m with this antenna;
        #                   the ring had forced -21 dBi at 5 degrees on every band)
    hour = int(start[:2]) + int(start[3:5]) / 60 if start and start[:2].isdigit() else 19.0
    d = 400.0 if km is None else max(20.0, float(km))
    n_min, _ = hops(d)
    sun = sun_over(when_utc, mid[0], mid[1]) if when_utc is not None and mid else None
    off = [None]                                   # the path's angle off the wire's broadside (set per way below)
    g_of = (lambda th: measured_gain(good, th)) if good else (
        lambda th: gain(antenna, f, height_m, th, ground, off[0]))
    dbm = lambda w: 10 * math.log10(max(0.1, w) * 1000)          # noqa: E731
    nz = noise_dbm(f)
    best = None
    # both ends known with the net's date: a control point per hop (the short path; past 8,000 km the long path too)
    per_hop = ends is not None and when_utc is not None and None not in (*ends[0], *ends[1])
    ways = [(False, d)] + ([(True, EARTH_KM - d)] if per_hop and d > 8000 else [])
    have_ends = ends is not None and None not in (*ends[0], *ends[1])
    for long_way, dd in ways:
        n0, _ = hops(dd)
        if wire_deg is not None and have_ends:
            brg = (bearing(ends[0], ends[1]) + (180 if long_way else 0)) % 360
            a = abs(((brg - (float(wire_deg) + 90.0)) + 90.0) % 180.0 - 90.0)      # 0 = at right angles to the wire
            off[0] = a
        for n in range(n0, n0 + (6 if not long_way else 3)):
            ctl = [control(when_utc, *pt) for pt in control_points(ends[0], ends[1], n, long_way)] if per_hop else None
            gdb, sea = ground_loss(ends[0], ends[1], n, long_way) if have_ends else (None, 0)
            p = path(f, dd, hour, sfi, n, sun, ctl, gdb)
            p["long"], p["km"], p["sea"], p["off"] = long_way, dd, sea, off[0]
            if not p["open"]:
                if best is None:
                    best = {"p": p, "hear": None, "send": None, "g": g_of(p["takeoff"])}
                continue
            th = p["takeoff"]
            g_me, g_ncs = g_of(th), gain(NCS["antenna"], f, NCS["height_m"], th)
            g_rx = g_me if good or g_me > -6 else -6 + (g_me + 6) * 0.3   # a weak antenna also hears less noise (a
            #                                                                 measured sweet spot already includes that)
            hear = dbm(NCS["power_w"]) + g_ncs + g_rx - p["loss"] - nz
            send = dbm(power_w) + g_me + g_ncs - p["loss"] - nz
            if best is None or best["hear"] is None or hear > best["hear"]:
                best = {"p": p, "hear": hear, "send": send, "g": g_me}
    p, hear, send, g_me = best["p"], best["hear"], best["send"], best["g"]
    d = p.get("km", d)
    th = p["takeoff"]
    name = ANTENNAS[antenna][0]
    hh = f"{int(hour):02d}:{int(round(hour % 1 * 60)):02d}"
    if sun:
        hh += (f" ({when_utc.strftime('%b %d')}, sun {90 - sun['zenith']:.0f}° up over the path)" if sun["sun_up"]
               else f" ({when_utc.strftime('%b %d')}, after dark over the path)")
    ant_words = (f"your antenna (you hear stations well at {good[0]:g}-{good[1]:g} km)" if good else
                 f"your {name.lower()}" + (f" at {height_m:g} m" if ANTENNAS[antenna][1] == "h" else ""))
    if hear is None:
        why = (f"{band_of(f)} at {hh}: the highest usable frequency for {round(d)} km is about {p['muf']:.1f} MHz, so "
               f"{f:.3f} MHz goes through the layer and skips over (solar flux {round(sfi)})")
    else:
        zone = ""
        if good and d < good[0]:
            zone = f" {round(d)} km is closer than your antenna's sweet spot: its signal goes up too steeply."
        elif good and d <= good[1] * p["hops"] and d >= good[0] * p["hops"]:
            zone = " In your antenna's sweet spot."
        why = (f"{band_of(f)} at {hh}, {round(d)} km{' the long way round' if p.get('long') else ''}: "
               f"{p['hops']} hop{'s' if p['hops'] > 1 else ''} of "
               f"{round(d / p['hops'])} km, takeoff {th:.0f}°; highest usable frequency {p['muf']:.1f} MHz (solar flux "
               f"{round(sfi)}); daytime absorption {p['absorb']:.0f} dB"
               + (f"; through the auroral zone {p['aurora']:.0f} dB" if p.get("aurora") else "")
               + (f"; {p['sea']} of {p['hops'] - 1} ground bounce{'s' if p['hops'] != 2 else ''} on sea water"
                  if p.get("sea") else "")
               + f". {ant_words[0].upper() + ant_words[1:]}: "
               f"{g_me:+.0f} dBi at {th:.0f}°.{zone} Signal over noise: hearing {hear:+.0f} dB, checking in with "
               f"{power_w:g} W {send:+.0f} dB")
    gray = None                                    # sunrise or sunset at an end of the path, at this time
    if per_hop:
        me = abs(90 - sun_over(when_utc, *ends[0])["zenith"]) <= GRAY_DEG
        them = abs(90 - sun_over(when_utc, *ends[1])["zenith"]) <= GRAY_DEG
        gray = "both ends" if me and them else "your end" if me else "their end" if them else None
        if gray and hear is not None:
            why += (f". Gray line at {gray} (sunrise or sunset): the daytime absorption is gone there while the "
                    "upper layer still returns the signal")
    if p.get("off") is not None and not good and hear is not None and antenna in WIRE_FLOOR:
        why += f". The path is {p['off']:.0f}° off your wire's broadside"
    return {"chance": _word(hear), "checkin": _word(send), "pct_hear": chance_pct(hear), "pct_send": chance_pct(send),
            "gray": gray, "sea": p.get("sea") or 0, "why": why, "band": band_of(f), "takeoff": round(th), "gain": round(g_me, 1), "muf": round(p["muf"], 1),
            "hops": p["hops"], "km": round(d), "long_path": bool(p.get("long")), "dark": (not sun["sun_up"]) if sun else None, "snr_hear": None if hear is None else round(hear),
            "snr_send": None if send is None else round(send)}


# ---------------------------------------------------------------- today's solar flux ------------------------------
# ---- what the antenna reaches, without a fixed circle (owner 2026-11-25: a Plans search "only looked within 373 mi
# ... inside the first bounce off of the ionosphere ... Rework how the physics are calculated and work up the HF net
# search based on the physics for the antenna") ----
def invv_height(apex_m: float, ends_m: float | None) -> float:
    """An inverted V radiates from where its current is: mostly near the apex. Its effective height is about a third
    of the way down from the apex to the ends (the usual rule of thumb; a flat dipole is its own height)."""
    if ends_m is None or ends_m >= apex_m:
        return float(apex_m)
    return round(apex_m - (apex_m - max(0.0, ends_m)) / 3.0, 2)


def invv_model_height(apex_m: float, ends_m: float | None) -> float:
    """The height to give gain() for an inverted V: with the ends known, its effective height (gain() takes 0.8 of
    an inverted V's height when it knows only the apex, so that is undone here)."""
    return float(apex_m) if ends_m is None or ends_m >= apex_m else round(invv_height(apex_m, ends_m) / 0.8, 2)


FOOT_BANDS = (("160 m", 1.9), ("80 m", 3.8), ("40 m", 7.18), ("20 m", 14.25), ("17 m", 18.13), ("15 m", 21.3),
              ("10 m", 28.4))
FOOT_KM = tuple(range(50, 800, 50)) + tuple(range(800, 3200, 100)) + tuple(range(3200, 12001, 400))
RING_MAX_MHZ = 10.0                     # a "heard well from..to" ring shapes 160-40 m only
REACH_PCT, REACH_SEND_PCT = 60, 50      # "reaches": heard this often, and likely to be heard checking in


def footprint(antenna: str, height_m: float, power_w: float, sfi: float = TYPICAL_SFI, good_km: tuple | None = None,
              ground: str = "average") -> list[dict]:
    """Where this setup's signal lands, band by band, by day (local 13:00) and night (01:00):
    [{"band", "mhz", "day": [[from_km, to_km], ...], "night": [...]}]. The gap before the first stretch is the skip
    zone (the frequency goes through the layer at steep angles, or the antenna fires too low / too high for it);
    later stretches are more hops. An empty list: the band is closed, or absorbed, at that time."""
    out = []
    for band, f in FOOT_BANDS:
        row = {"band": band, "mhz": f}
        for name, hr in (("day", "13:00"), ("night", "01:00")):
            runs: list[list[int]] = []
            prev = None
            for d in FOOT_KM:
                e = estimate(f, d, hr, antenna, height_m, power_w, sfi, good_km, ground=ground)
                ok = e["pct_hear"] >= REACH_PCT and e["pct_send"] >= REACH_SEND_PCT
                if ok and prev is not None and runs and runs[-1][1] == prev:
                    runs[-1][1] = d
                elif ok:
                    runs.append([d, d])
                prev = d
            row[name] = [r for r in runs if r[1] > r[0] or r[0] >= 800]
        out.append(row)
    return out


def regional_km(foot: list[dict]) -> int | None:
    """How far "regional" is for this setup: the far edge of the first stretch on its best low band (80 / 40 m by
    night, 40 / 20 m by day), where state and regional nets meet."""
    far = [r[name][0][1] for r in foot for name in ("day", "night")
           if r["band"] in ("80 m", "40 m", "20 m") and r[name]]
    return int(max(far)) if far else None


def reach_day(f: float, home: tuple, there: tuple, antenna: str, height_m: float, power_w: float,
              sfi: float = TYPICAL_SFI, good_km: tuple | None = None, ground: str = "average", day=None,
              wire_deg: float | None = None) -> dict:
    """The best this setup does to one place on one frequency over a day, every 2 hours UTC, with the real sun over
    each hop (so sunrise and sunset, the gray line, count): {"pct" (the worse of hearing and being heard, at the
    best hour), "hours": [UTC hours it reaches], "km", "hops", "why"}."""
    from datetime import datetime, timezone
    day = day or datetime.now(timezone.utc)
    km = great_circle_km(home, there)
    mid = control_points(home, there, 1)[0] if km > 50 else home
    best, hours, gray = None, [], []
    for h in range(0, 24, 2):
        when = day.replace(hour=h, minute=0, second=0, microsecond=0)
        local = (h + mid[1] / 15.0) % 24
        e = estimate(f, km, f"{int(local):02d}:{int(local % 1 * 60):02d}", antenna, height_m, power_w, sfi, good_km,
                     when, mid, ground, (home, there), wire_deg)
        pct = min(e["pct_hear"], e["pct_send"])
        if e["pct_hear"] >= REACH_PCT and e["pct_send"] >= REACH_SEND_PCT:
            hours.append(h)
        if best is None or pct > best[0]:
            best = (pct, e)
    twilight = sun_events(day, *home) + sun_events(day, *there)   # each end's sunrise and sunset: the gray line
    gray = [h for h in hours if any(h <= t < h + 2 for t in twilight)]
    return {"pct": best[0], "hours": hours, "gray": gray, "km": round(km), "hops": best[1]["hops"],
            "sea": best[1].get("sea") or 0, "why": best[1]["why"], "band": best[1]["band"]}


def sun_events(day, lat: float, lon: float) -> list[float]:
    """The UTC hours (decimal) of sunrise and sunset at a place on this UTC day (none in polar day or night)."""
    out, prev = [], None
    base = day.replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta
    for i in range(0, 24 * 6 + 1):                                # every 10 minutes
        up = sun_over(base + timedelta(minutes=10 * i), lat, lon)["zenith"] < 90.0
        if prev is not None and up != prev:
            out.append(round(i / 6.0, 2) % 24)
        prev = up
    return out


def hours_words(hours: list[int]) -> str:
    """[0, 2, 4, 14] -> "00-06, 14-16 UTC" (2-hour steps)."""
    if not hours:
        return ""
    if len(hours) == 12:
        return "all day"
    runs = []
    for h in sorted(hours):
        if runs and h == runs[-1][1]:
            runs[-1][1] = h + 2
        else:
            runs.append([h, h + 2])
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][1] == 24:      # wraps midnight
        runs[0][0] = runs.pop()[0]
    return ", ".join(f"{a:02d}-{b % 24:02d}" for a, b in runs) + " UTC"


SFI_URL = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"


def solar_flux(cache: dict, fetch=None, max_age_s: float = 12 * 3600) -> tuple[float, str]:
    """(10.7 cm flux, where it came from). `cache` is a dict kept by the caller ({"sfi", "at"}); NOAA's public feed
    (no key, nothing about the station sent) is read at most twice a day; offline -> the last value or 130."""
    if cache.get("sfi") and time.time() - cache.get("at", 0) < max_age_s:
        return float(cache["sfi"]), "NOAA, today"
    try:
        rows = (fetch or _fetch)(SFI_URL)
        vals = [r for r in rows if isinstance(r, dict) and r.get("flux")]
        vals.sort(key=lambda r: str(r.get("time_tag") or ""))
        v = float(vals[-1]["flux"])
        if 50 <= v <= 400:
            cache.update(sfi=round(v), at=time.time())
            return float(round(v)), "NOAA, today"
    except Exception:  # noqa: BLE001 - offline: the model still runs
        pass
    if cache.get("sfi"):
        return float(cache["sfi"]), "NOAA, last known"
    return TYPICAL_SFI, "typical (offline)"


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "HAM-Sidekick-Station"})
    with urllib.request.urlopen(req, timeout=6) as r:
        return json.loads(r.read())


# ---------------------------------------------------------------- what this station can hear around the world -----
# Each region: a few places it is heard from (the best of them counts), and what to look for there. The coordinates
# are cities and research stations, public; they stand for the region in the path model, nothing more.
REGIONS = {
    "japan": ("Japan", ((35.7, 139.7), (43.1, 141.4), (33.6, 130.4)), "JARL and Japanese clubs' nets, English-language nets"),
    "china": ("China, Taiwan and Hong Kong", ((39.9, 116.4), (31.2, 121.5), (25.0, 121.5), (22.3, 114.2)),
              "CRAC, CTARL and HARTS nets"),
    "korea": ("Korea", ((37.6, 127.0), (35.2, 129.1)), "KARL nets"),
    "se_asia": ("Southeast Asia and the Philippines", ((14.6, 121.0), (1.35, 103.8), (13.8, 100.5), (-6.2, 106.8)),
                "PARA, ORARI, RAST and regional nets"),
    "india": ("India and South Asia", ((28.6, 77.2), (19.1, 72.9), (13.1, 80.3)), "ARSI and Indian nets"),
    "russia_w": ("European Russia", ((55.75, 37.6), (59.9, 30.3), (56.8, 60.6)), "SRR and Russian nets"),
    "russia_e": ("Siberia and the Russian Far East", ((55.0, 82.9), (52.3, 104.3), (43.1, 131.9), (64.7, 177.5)),
                 "SRR and Far East nets"),
    "europe": ("Europe", ((51.5, -0.1), (50.1, 8.7), (48.9, 2.35), (41.9, 12.5), (59.3, 18.1), (52.2, 21.0)),
               "national society nets (RSGB, DARC, REF, ARI, SSA, PZK), Europe-wide and English-language nets"),
    "mideast": ("Middle East", ((25.2, 55.3), (31.8, 35.2), (24.7, 46.7)), "regional and English-language nets"),
    "africa": ("Africa", ((-26.2, 28.0), (-33.9, 18.4), (-1.3, 36.8), (6.5, 3.4), (30.0, 31.2)),
               "SARL, ARRL-affiliated and African nets"),
    "s_america": ("South America", ((-34.6, -58.4), (-23.5, -46.6), (-12.0, -77.0), (4.7, -74.1), (-33.4, -70.7)),
                  "LABRE, RCA and Latin American nets (Spanish / Portuguese / English)"),
    "caribbean": ("Caribbean and Central America", ((18.5, -66.1), (18.0, -76.8), (19.4, -99.1), (9.9, -84.1)),
                  "Caribbean emergency (CEWN), hurricane and regional nets"),
    "antarctica": ("Antarctica", ((-77.8, 166.7), (-64.8, -64.0), (-62.2, -58.9), (-67.6, 62.9)),
                   "Antarctic base and expedition schedules, the Antarctic net"),
    "australia": ("Australia", ((-33.9, 151.2), (-37.8, 145.0), (-31.95, 115.9), (-27.5, 153.0)), "WIA and Australian nets"),
    "nz_pacific": ("New Zealand and the Pacific", ((-36.8, 174.8), (-41.3, 174.8), (-17.7, 168.3), (-18.1, 178.4)),
                   "NZART, Pacific island and maritime nets"),
    "hawaii": ("Hawaii", ((21.3, -157.9), (19.7, -155.1)), "Hawaii nets and Pacific maritime nets"),
    "alaska": ("Alaska and the Arctic", ((61.2, -149.9), (64.8, -147.7), (71.3, -156.8)), "Alaska and Arctic nets"),
}
DX_BANDS = (("160 m", 1.9), ("80 m", 3.8), ("40 m", 7.18), ("20 m", 14.25), ("17 m", 18.13), ("15 m", 21.3),
            ("12 m", 24.95), ("10 m", 28.45))
DX_MIN_PCT = 60                 # a window: the hours this station hears the region at least this often
NEAR_KM = 2500                  # a region this close is the regional search's, not the worldwide one's


def reach_table(home: tuple, antenna: str, height_m: float, power_w: float, sfi: float = TYPICAL_SFI,
                ground: str = "average", good_km: tuple | None = None, day=None, min_pct: int = DX_MIN_PCT) -> list[dict]:
    """For each region: the bands and UTC hours (on `day`, default today) this station probably hears it, with the
    chance of being heard back. [{"id", "label", "km", "windows": [{"band", "mhz", "from", "to" (UTC hour, exclusive),
    "best", "send"}]}], the regions with the most and best windows first; regions closer than NEAR_KM left out."""
    from datetime import date, datetime, timezone
    day = day or date.today()
    out = []
    for rid, (label, pts, _) in REGIONS.items():
        kms = [great_circle_km(home, p) for p in pts]
        if min(kms) < NEAR_KM:
            continue
        wins = []
        for band, f in DX_BANDS:
            hear, send = [0] * 24, [0] * 24
            for h in range(24):
                when = datetime(day.year, day.month, day.day, h, 30, tzinfo=timezone.utc)
                for p, km in zip(pts, kms):
                    e = estimate(f, km, f"{h:02d}:30", antenna, height_m, power_w, sfi, good_km, when, None, ground,
                                 (home, p))
                    if e["pct_hear"] > hear[h]:
                        hear[h], send[h] = e["pct_hear"], e["pct_send"]
            on = [x >= min_pct for x in hear]
            if all(on):
                wins.append({"band": band, "mhz": f, "from": 0, "to": 24, "best": max(hear), "send": max(send)})
                continue
            start = next((i for i in range(24) if not on[i]), 0)     # walk round the clock from a closed hour
            run = []
            for k in range(1, 25):
                i = (start + k) % 24
                if on[i]:
                    run.append(i)
                if run and (not on[i] or k == 24):
                    wins.append({"band": band, "mhz": f, "from": run[0], "to": (run[-1] + 1) % 24 or 24,
                                 "best": max(hear[j] for j in run), "send": max(send[j] for j in run)})
                    run = []
        wins.sort(key=lambda w: (-w["best"], -((w["to"] - w["from"]) % 24)))
        out.append({"id": rid, "label": label, "km": round(min(kms)), "windows": wins})
    out.sort(key=lambda r: (-len(r["windows"]), -max([w["best"] for w in r["windows"]] or [0]), r["km"]))
    return out
