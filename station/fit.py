"""Can this radio record this net? One answer for the dashboard, the alerts and the net-start logic.

Owner 2026-11-10: one schedule per station PC; each net is assigned to a radio and can be moved to another; radios
are added and removed; the IC-705's single antenna socket holds an HF or a VHF/UHF antenna at the owner's choice.

A radio says what it can hear:
  model    a preset (MODELS): bands and modes. station.yaml / radios.json `model:`; inferred when absent.
  antenna  for a one-socket multi-band radio (IC-705): "hf" | "vu", set on its card (data/operator.json).
  role     "nets" | "winlink" (card; operator.json): a Winlink radio is never used for a net (capture never shares
           the digital-mode audio device).
  cat      a CI-V port (station/cat.py): the station tunes it.

fit(net, radio) -> {"kind", "why"}:
  ready  will be recorded: a CAT radio tunes itself, or a fixed radio is already on the net's frequency
  tune   a fixed radio on another frequency: the pre-net alert asks the operator to tune it
  cant   wrong band (or antenna), no such mode, or a Winlink radio
  none   the net has no radio (kept in the list, not recorded)
status(...) adds "clash": another net on the same radio at the same time in the next CLASH_DAYS days that both can
hear, unless the operator settled it (`beats`: the ids of nets this one wins over; the loser is not listened to or
tuned for when they meet).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import recur

ANALOG_MODES = ("FM", "USB", "LSB", "AM", "CW", "DIG")
# Digital voice (owner 2026-11-27). The RADIO decodes it: the station records the decoded speech from the radio's
# speaker jack or USB audio, exactly as it records FM. So a net in one of these modes needs a radio of that kind,
# and its audio must not come from a data jack (that carries the undecoded signal).
DV_MODES = ("D-STAR", "C4FM", "DMR")
DV_NAME = {"D-STAR": "D-STAR", "C4FM": "Fusion (C4FM)", "DMR": "DMR"}
DV_ACCESS = {"D-STAR": "reflector and module, like REF030 C", "C4FM": "room or reflector and DG-ID, like DG-ID 00",
             "DMR": "talkgroup, time slot and color code, like TG 3100 TS2 CC1"}
ALL_MODES = ANALOG_MODES + DV_MODES
VU = ((144.0, 148.0), (420.0, 450.0))
VU3 = ((144.0, 148.0), (219.0, 225.0), (420.0, 450.0))
MODELS = {
    "vu_fm": {"label": "2 m / 70 cm FM (handheld or mobile)", "bands": VU, "modes": ("FM",)},
    "dstar": {"label": "D-STAR handheld or mobile: FM and D-STAR (TH-D74/D75, ID-52, ID-5100)", "bands": VU3,
              "modes": ("FM", "D-STAR")},
    "fusion": {"label": "Yaesu Fusion handheld or mobile: FM and C4FM (FT5D, FT-70D, FTM-500D)", "bands": VU,
               "modes": ("FM", "C4FM")},
    "dmr": {"label": "DMR handheld or mobile: FM and DMR", "bands": VU3, "modes": ("FM", "DMR")},
    "ic705": {"label": "Icom IC-705 (HF to 70 cm, all modes and D-STAR)", "bands": ((0.03, 199.999999), (400.0, 470.0)),
              "modes": ANALOG_MODES + ("D-STAR",), "antennas": {"hf": ((0.03, 54.0),), "vu": VU}},
    "hf": {"label": "HF transceiver (160-6 m)", "bands": ((1.8, 54.0),), "modes": ANALOG_MODES},
    "any": {"label": "Other (any band, any mode: not checked)", "bands": ((0.0, 100000.0),), "modes": ALL_MODES},
}


def dv_mode(text) -> str | None:
    """The digital voice mode a word or a net's name means: 'DV', 'D Star' -> D-STAR; 'YSF', 'Fusion', 'WIRES-X' ->
    C4FM; 'DMR', 'BrandMeister' -> DMR. None for anything else."""
    import re
    t = str(text or "").upper()
    if re.search(r"\bD[- ]?STAR\b|\bDV\b|\bDPLUS\b", t):
        return "D-STAR"
    if re.search(r"\bC4FM\b|\bFUSION\b|\bYSF\b|\bWIRES[- ]?X\b", t):
        return "C4FM"
    if re.search(r"\bDMR\b|\bBRANDMEISTER\b|\bTGIF\b", t):
        return "DMR"
    return None
ANTENNA_LABEL = {"hf": "HF", "vu": "VHF/UHF"}
CLASH_DAYS = 56


def infer_model(cfg: dict) -> str:
    """A radio set up before models existed: an IC-705 by name, device or CAT; a handheld/FTM/Digirig radio on FM as
    2 m / 70 cm; anything else is not checked."""
    words = " ".join(str(cfg.get(k) or "") for k in ("name", "device", "id")).lower()
    if "705" in words or (cfg.get("cat") and "ic" in words):
        return "ic705"
    if any(w in words for w in ("handheld", "ftm", "baofeng", "wouxun", "ht ")) and str(cfg.get("mode") or "FM") == "FM":
        return "vu_fm"
    return "any"


def band_name(f: float) -> str:
    return "HF" if f < 30 else "6 m" if f < 54 else "2 m" if f < 148 else "1.25 m" if f < 225 else "70 cm" \
        if f < 450 else "UHF"


def fmt(f) -> str:
    return f"{float(f):.3f}" if f else ""


def bands_of(radio: dict) -> tuple:
    m = MODELS.get(radio.get("model") or "any", MODELS["any"])
    ant = radio.get("antenna")
    if m.get("antennas") and ant in m["antennas"]:
        return m["antennas"][ant]
    return m["bands"]


def fit(net: dict, radio: dict | None, has_cat: bool = False) -> dict:
    if not radio:
        return {"kind": "none", "why": "No radio: kept in the list, not recorded"}
    name = radio.get("name") or radio.get("id")
    if radio.get("role") == "winlink":
        return {"kind": "cant", "why": f"{name} is kept for Winlink; nets are never recorded on it"}
    f, mode = net.get("freq_mhz"), (net.get("mode") or "").upper() or None
    m = MODELS.get(radio.get("model") or "any", MODELS["any"])
    if f:
        if not any(a <= f <= b for a, b in bands_of(radio)):
            if m.get("antennas") and any(a <= f <= b for a, b in m["bands"]):
                other = next(k for k, bs in m["antennas"].items() if any(a <= f <= b for a, b in bs))
                return {"kind": "cant", "antenna": other,
                        "why": f"{name} has its {ANTENNA_LABEL.get(radio.get('antenna'), '?')} antenna on; "
                               f"{fmt(f)} MHz ({band_name(f)}) needs the {ANTENNA_LABEL[other]} one"}
            return {"kind": "cant", "why": f"{name} can't receive {fmt(f)} MHz ({band_name(f)})"}
    acc = str(net.get("access") or "").strip()
    if mode in DV_MODES:
        if mode not in m["modes"]:
            return {"kind": "cant", "why": f"{name} can't decode {DV_NAME[mode]}: this net needs a "
                                           f"{DV_NAME[mode].split(' ')[0]} radio (Radios → Radio type)"}
        if radio.get("gate") == "carrier":
            return {"kind": "cant", "why": f"{name}'s audio comes from a data jack, which carries {DV_NAME[mode]} "
                                           "undecoded: take its audio from the speaker jack or USB (Radios → Audio from)"}
    elif mode and mode not in m["modes"]:
        return {"kind": "cant", "why": f"{name} has no {mode}"}
    if not f:
        return {"kind": "ready", "why": f"No frequency given: recorded on whatever {name} is tuned to"}
    if has_cat:
        why = f"Tunes itself to {fmt(f)} {mode or ''} (CAT), and back after".replace("  ", " ")
        if mode in DV_MODES and acc:
            why += f". You set the rest on the radio: {acc}"
        return {"kind": "ready", "why": why}
    on = radio.get("freq_mhz")
    if on and abs(float(on) - float(f)) < 0.0005 and (not mode or mode == radio.get("mode")):
        return {"kind": "ready", "why": f"Already on {fmt(f)}"}
    what = f"{fmt(f)} {mode or ''}".strip() + (f" ({acc})" if mode in DV_MODES and acc else "")
    return {"kind": "tune", "why": f"You tune it to {what}: the alert asks before the net"}


def windows(nets: list[dict], at: datetime, days: int = CLASH_DAYS) -> dict:
    """net id -> [(start, end, date)] for the next `days` days (exceptions applied)."""
    return {n["id"]: [(o["start"], o["end"], o["date"]) for o in recur.occurrences(n, at, at + timedelta(days=days))]
            for n in nets}


def overlap(wa, wb):
    """The first time two nets meet: (date, other start) or None."""
    for s1, e1, d in wa:
        for s2, e2, _ in wb:
            if s1 < e2 and s2 < e1:
                return d, s2
    return None


def statuses(nets: list[dict], radios: dict, at: datetime, has_cat=lambda rid: False) -> dict:
    """net id -> {"kind", "why", "clash": {...} | None, "settled": [...], "fits": {radio id: {...}},
    "suggest": radio id | None}. `fits` answers the radio picker: what each radio would do with this net."""
    win = windows(nets, at)
    fit_on = {(n["id"], rid): fit(n, r, has_cat(rid)) for n in nets for rid, r in radios.items()}

    def meets(n, rid):
        """Nets on `rid` that `n` would meet there, both able to be heard."""
        out = []
        for o in nets:
            if o["id"] == n["id"] or o.get("radio") != rid:
                continue
            if fit_on[(o["id"], rid)]["kind"] not in ("ready", "tune"):
                continue
            hit = overlap(win[n["id"]], win[o["id"]])
            if hit:
                out.append({"id": o["id"], "name": o.get("name"), "date": hit[0],
                            "start": hit[1].strftime("%H:%M")})
        return out

    beats = {n["id"]: set(n.get("beats") or []) for n in nets}
    out = {}
    for n in nets:
        fits = {}
        for rid in radios:
            f = dict(fit_on[(n["id"], rid)])
            if f["kind"] in ("ready", "tune"):
                cl = meets(n, rid)
                if cl:
                    f["clash"] = cl[0]
            fits[rid] = f
        rid = n.get("radio")
        if rid not in radios:
            s = {"kind": "none", "why": fit(n, None)["why"]}
        else:
            s = dict(fits[rid])
            cl = meets(n, rid) if s["kind"] in ("ready", "tune") else []
            open_ = [c for c in cl if c["id"] not in beats[n["id"]] and n["id"] not in beats.get(c["id"], set())]
            s["settled"] = [c | {"wins": c["id"] in beats[n["id"]]} for c in cl if c not in open_]
            s.pop("clash", None)
            if open_:
                s["kind"], s["clash"] = "clash", open_[0]
        if s["kind"] in ("none", "cant", "clash"):
            best = None
            for r2, f in fits.items():
                if r2 == rid or f["kind"] not in ("ready", "tune"):
                    continue
                score = (0 if f.get("clash") else 4) + (2 if f["kind"] == "ready" else 0)
                if best is None or score > best[0]:
                    best = (score, r2)
            s["suggest"] = best[1] if best else None
        s["fits"] = fits
        out[n["id"]] = s
    return out


def loses_at(net: dict, nets: list[dict], at: datetime) -> bool:
    """`net` is on the air (or in its window) at `at` while a net that beats it is too, on the same radio."""
    for o in nets:
        if o.get("radio") != net.get("radio") or net["id"] not in (o.get("beats") or []):
            continue
        for oc in recur.occurrences(o, at - timedelta(days=1), at + timedelta(days=1)):
            if oc["start"] - timedelta(minutes=5) <= at < oc["end"] + timedelta(minutes=5):
                return True
    return False
