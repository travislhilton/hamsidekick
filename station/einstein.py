"""Einstein on the air: the station's AI assistant answering other amateurs over VARA, at a call of its own.

Owner 2026-11-21: "add the sidekick capability to VARA chat sessions ... I should be able to turn on my W9XYZ Einstein
AI agent if I have internet access. If not it should be disabled ... it should show up as a separate operator below my
W9XYZ operator in the VARA user list. A remote operator should be able to ask it anything and it should reply in line
with all ARRL rules ... create and send files such as a Chirp file ... weather report or any report ... in the Winlink
ICS formatted forms ... I may have [it] turned on at W9XYZ-7 ... and then as an operator I may be on W9XYZ-8 and want
to talk to W9XYZ-7 Einstein."

THE DESIGN
* Einstein answers at ITS OWN CALL: the station's base call with an SSID of its own (Modem setup; W9XYZ-15 by
  default, never one of this station's other calls). VARA takes several calls on one modem (MYCALL a b), so the
  operator's call and Einstein's share the radio: a station that connects to W9XYZ-15 talks to Einstein, one that
  connects to W9XYZ-7 talks to the operator. Other stations list it as its own station, under the operator's
  ("+AI" in its HSK1 handshake says what it is and whose; docs/VARA.md). A plain VARA terminal can talk to it too.
* AUTOMATIC CONTROL, inside Part 97 (47 CFR 97.109(d), 97.221): with the operator away, the station keeps answering
  ONLY at Einstein's call, as an automatically controlled digital station:
    - 6 m and shorter (>= 50 MHz) where the license class has data privileges: answers and announces (97.221(b));
    - the HF segments of 97.221(b) (bandplan.AUTO_DATA): answers and announces;
    - any other HF data frequency: only answers a station that calls it (97.221(c)(1)) and only on VARA HF 500 Hz
      (97.221(c)(2)); 60 m never (97.303(h)). Never announces there.
  It never opens a link: everything it sends goes on the link the other station opened (an answer that is not ready
  when that link closes waits for the station's next link). The operator's own call is answered only while the
  operator is at a dashboard (local, or remote over the network: 97.213). The operator's Transmit switch, license
  class and the radio's frequency gate everything, as for the operator.
* ONLY WITH THE INTERNET: switched on by the operator (at a dashboard) with the xAI key set; while the xAI service
  cannot be reached Einstein's call is taken off the modem (nobody is answered by a robot that cannot think) and comes
  back by itself when it can.
* WHAT IT DOES (tools the model calls; everything is made by code, the model only chooses): answers anything; the
  area's band plan for the asker's license class (FCC database, offline); CHIRP memory files (the station's radio
  list, the area band plan's channels, the ad hoc channels, or channels the asker lists); ICS-213 reports (weather
  from the NWS / Open-Meteo, HF conditions from NOAA SWPC, or any text), an ICS-205 radio plan, an ICS-309 log of the
  session (station/forms.py: a page any browser opens, plus Winlink Express form data when Express is on this PC);
  the station's nets; a callsign's public FCC entry; the library (only when the operator shares it); a note for the
  control operator.
* PART 97 IN CODE (the model cannot talk its way past): the first message of every session discloses that it is an
  automated assistant and names the station and control operator; the call every 10 minutes; replies checked for
  indecent language, codes, business, third-party traffic and claiming to be a person (agent.py's checks); files are
  plain text, CSV, HTML or XML made here, never encrypted or compressed; only licensed amateurs are answered (the FCC
  database for US calls, a valid prefix otherwise); an emergency gets the 911 / emergency-net advice at once and the
  control operator is alerted; per-station and daily limits; the operator sees everything it sends.
* THE OPERATOR, FROM ANOTHER STATION ON THE AIR: a station with the same base call that proves it holds the
  operator's OWNER KEY (the same key typed on each of the operator's stations; a per-link challenge, answered with an
  HMAC in the clear: authentication, not a cipher, like Winlink's secure login) may also send STATUS, MESSAGES,
  PAUSE and RESUME.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets as _rand
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

from . import bandplan, forms

DEFAULT_SSID = 15
SSIDS = (15, 14, 13, 12, 11, 10, 9)
REPLY_CHARS = 1500            # one reply on the air (a file for anything longer)
PER_STATION_HOUR = 20         # questions from one station per hour
FILES_PER_HOUR = 8            # files to one station per hour
PER_DAY = 300                 # questions answered per day, all stations
FILE_MAX = 64 * 1024          # one file Einstein makes
ID_EVERY_S = 600              # 97.119(a)
MODEL_TIMEOUT_S = 90
HOLD_S = 6 * 3600             # an answer kept for a station whose link closed before it was ready
PROBE_S = 60
OWNER_KEY = "EINSTEIN_OWNER_KEY"
MAIL_KEEP = 200

EMERGENCY = re.compile(r"\b(mayday|emergency|emergencies|injur\w*|bleeding|unconscious|not breathing|heart attack|"
                       r"stroke|trapped|life[- ]threatening|fire|drowning|overdose|911|help me|need help now)\b", re.I)
# Business on the air: dealing, not talking about products (a typed answer may say where a Digirig is sold).
_BUSINESS = re.compile(r"\b(for sale by me|i (will|can|'ll) (sell|buy|order) (it|one|this|that)? ?(for|to) you|send (me )?"
                       r"(the )?payment|venmo|paypal me|cash ?app|wire (me|the) money|my (store|shop|business) (sells|has))\b",
                       re.I)
_THIRD = re.compile(r"\b(i('ll| will| can) (relay|pass|forward|deliver|e-?mail|text|phone) (your|the|this|a) "
                    r"(message|traffic|note)|i('ll| will) (e-?mail|text|call|phone) (him|her|them|your \w+))\b", re.I)
SAFE_EXT = {".txt", ".csv", ".html", ".xml", ".md", ".json", ".hsadhoc", ".hsnets", ".ics"}


def base(call: str) -> str:
    return str(call or "").upper().split("-")[0]


def auto_control(freq_mhz, vara_kind: str, bw, license_class) -> dict:
    """Where this station may answer / announce with nobody at a control point (97.109(d), 97.221).
    {"answer": (ok, why), "announce": (ok, why)}"""
    if not freq_mhz:
        no = (False, "set the radio's frequency: automatic control depends on it")
        return {"answer": no, "announce": no}
    f = float(freq_mhz)
    if not license_class:
        no = (False, "set your license class (Settings → Einstein & AI)")
        return {"answer": no, "announce": no}
    chk = bandplan.check(f, "VARA", license_class)
    if chk["ok"] is not True:
        no = (False, chk["why"] or "no data privileges there")
        return {"answer": no, "announce": no}
    if f >= 50.0:
        yes = (True, "97.221(b): automatic control of data on 6 m and shorter")
        return {"answer": yes, "announce": yes}
    if any(a <= f <= b for a, b in bandplan.AUTO_DATA):
        yes = (True, "97.221(b): an HF automatic-control data segment")
        return {"answer": yes, "announce": yes}
    if 5.3 <= f <= 5.45:
        no = (False, "60 m: no automatic control (97.303(h))")
        return {"answer": no, "announce": no}
    if vara_kind == "hf" and int(bw or 0) == 500:
        return {"answer": (True, "97.221(c): answering a station that calls, 500 Hz"),
                "announce": (False, "97.221(c): outside the automatic-control segments it may only answer, never call")}
    no = (False, "HF outside the automatic-control segments: only VARA HF 500 Hz may answer there (97.221(c)); "
                 "choose 500 Hz, a 97.221(b) segment, or 6 m and up")
    return {"answer": no, "announce": no}


def disclosure(name: str, ecall: str, of: str, op_call: str) -> str:
    return (f"{ecall} {name} here: an automated AI assistant at amateur station {of}; the station's licensee and "
            f"control operator is {op_call}. Type HELP for what I can do.")


HELP = ("I can: answer questions (radio, emergency comms, technical, anything); send a CHIRP file of channels "
        "(\"CHIRP file of the local EMCOMM 2 m and 70 cm channels\": repeaters, simplex and ad hoc; or \"the 2 m "
        "simplex channels for a Baofeng\"); give the band plan here for your license class; "
        "weather or HF conditions as an ICS-213 report (\"weather for Springfield, IL as an ICS-213\"); make an "
        "ICS-205 radio plan or an ICS-309 log of our session; list this station's nets or send them as a calendar file (and a HAM Sidekick net file to add them to your schedule); look up a callsign; take a "
        "note for the control operator (\"leave a message for the operator: ...\"). Files arrive after my reply; "
        "on HAM Sidekick Station open them with View. Send PACK for this station's band plan and nets to install on yours \
(PACK works with no internet too). Ask me anything: I can search the internet (news, events, facts, a web page).")
OWNER_HELP = " As the station's operator you can also send STATUS, MESSAGES, PAUSE or RESUME."

SYSTEM = """You are {name}, an AI assistant answering licensed radio amateurs over a VARA {kind} keyboard link, at \
station {ecall} (part of amateur station {of}; licensee and control operator {op_call}). {asker} is linked to you now \
({asker_info}). Everything you write is transmitted by amateur radio, in the clear, under FCC Part 97 and good \
amateur practice.

Help like an expert, friendly ham: answer anything well (radio, technical, emergency communications, general \
knowledge), and use your tools to make files when asked: CHIRP memory files, ICS forms (ICS-213 general message for \
any report, ICS-205 radio plan, ICS-309 log of this session), weather and HF-conditions reports. A file follows your \
reply on this link: name it in your reply. Use the tools' results as facts; never invent frequencies, forecasts or \
license data. You can reach the whole internet through search_web (the web and X, live, and any page by its address): \
use it for any question whose answer is current, local, specific or something you are not sure of (news, events, \
sports, schedules, products and specs, places, people in the public eye, how-to, a page they name), and name the \
sources. Never say you cannot browse. Only say a file is attached when a tool made it and its id is in attach. \
Never answer one thing with another (weather is not news): if nothing can do \
what was asked, say so.

Rules (the station also enforces them in code and will not send a reply that breaks one):
- Plain language: no codes or ciphers, no obscene or indecent words, no song lyrics.
- No business: never buy, sell, advertise, quote prices to sell, or arrange anything for pay or for anyone's employer \
(factual product information is fine).
- No third-party traffic: never pass a message to or from anyone who is not the licensed amateur on this link; you \
cannot e-mail, text, phone or post. The one message you take is a note for {op_call} (leave_message).
- Never claim to be a person.
- Anyone in danger: tell them to call 911 (or their local emergency number) or use a local emergency net or repeater, \
and that {op_call} has been alerted. Never give medical or legal instructions as fact.
- Never give out {op_call}'s private details (address, phone, e-mail, exact location); the station's area: {area}.
- Short replies for the air: under {chars} characters, plain text, no markdown tables (make a file for long material).
- Say plainly when a tool found nothing or you are unsure.
Now: {now}. Return JSON: reply (the text to send), attach (ids of files your tools made to send with it), \
note_for_operator ("" unless they ask to leave {op_call} a message or something needs {op_call}'s attention; \
answering a question is not a note)."""

SCHEMA = {"type": "object", "properties": {"reply": {"type": "string"}, "attach": {"type": "array", "items": {"type": "string"}},
                                           "note_for_operator": {"type": "string"}},
          "required": ["reply", "attach", "note_for_operator"], "additionalProperties": False}


def text_problems(text: str) -> list[str]:
    """The Part 97 content checks of agent.py, on a typed reply."""
    from . import agent as A
    out = []
    for rx, why in ((A._OBSCENE, "indecent word (97.113(a)(4))"), (_BUSINESS, "business (97.113(a)(2),(3))"),
                    (_THIRD, "a relayed message (97.115)"), (A._PERSON, "claims to be a person (97.113(a)(4))")):
        if rx.search(text or ""):
            out.append(why)
    if re.search(r"(?:\b[A-Z]{5}\b\s+){4,}", text or ""):           # five-letter groups: looks like a cipher
        out.append("cipher-like groups (97.113(a)(4))")
    return out


# ---------------------------------------------------------------- the tools ------------------------------------------
NOT_VOICE = re.compile(r"packet|aprs|winlink|gateway|d-?star|dmr|fusion|ysf|p25|digital|weak.?signal|ssb|\bcw\b|"
                       r"beacon|satellite|not available|input to|repeater input|data", re.I)
CALLING_MHZ = {146.52, 446.0, 223.5}              # the national FM simplex calling channels

CLAIMS_FILE = re.compile(r"\battach(?:ed|ment)\b|\bfile name:|\bfile (?:follows|is on its way|is coming|sent)\b|"
                         r"\bin the (?:attached |enclosed )?(?:file|csv|form|page)\b|\bsee the (?:file|csv|form)\b", re.I)
WEB_MODEL = "grok-4.20-0309-non-reasoning"
WEB_TIMEOUT_S = 60


def _web_post(key: str, body: dict, timeout: float) -> dict:
    import urllib.request
    req = urllib.request.Request("https://api.x.ai/v1/responses", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    from . import aicost
    return aicost.xai_json(req, timeout, "einstein_web", body.get("model") or "")


PACKS_PER_HOUR = 3
# Command words the station's code answers (Einstein._direct): no AI, so the same every time, free, and off grid for
# all but WX / HF (the internet, not the AI). A word may stand first in a message: "CHIRP 2M", "WX213", "MSG …".
DIRECT_RE = re.compile(r"\s*(CHIRP|BAND\s*PLAN|ICS[\s-]?205|ICS[\s-]?309|NETS|CALENDAR|CAL|MSG|MESSAGE|WX\s*213|WX|"
                       r"HF\s*213|HF|CALL|LOOKUP)\b[\s:,-]*(.*)", re.I | re.S)
ASK_HELP = ("Or ask me anything in words (radio, emergency comms, technical; I search the internet for news, facts "
            "or a web page). Files arrive after my reply; on HAM Sidekick Station open them with View.")
DIRECT_ALIAS = {"CAL": "CALENDAR", "MESSAGE": "MSG", "LOOKUP": "CALL"}
DIRECT_HELP = ("Command words (answered by this station without the AI; all but WX and HF work with no internet): "
               "PACK (band plan + nets to install), CHIRP or CHIRP 2M / 70CM (local EMCOMM channels for a handheld), "
               "BANDPLAN 70CM (any band, for your license), ICS205 (ad hoc channels), ICS309 (this session's log), NETS, "
               "CALENDAR (nets as a calendar file), CALL K7ABC (callbook), MSG your note (for the operator), "
               "WX or WX213 [place] (weather, as an ICS-213), HF or HF213 (band conditions). ")
OFFLINE_WHY = "no internet: answers its command words (PACK, CHIRP, BANDPLAN, NETS …) and your owner-key commands only"
OFFLINE_SAY = ("No internet here right now, so I can't answer questions in words. My command words still work: PACK, "
               "CHIRP, BANDPLAN 70CM, ICS205, ICS309, NETS, CALENDAR, CALL, MSG. HELP says what each sends.")
SHARE_DEFAULT = {"plans": True, "kept": True, "adhoc": True, "nets": True, "own_files": False}

TOOL_STEP = {"band_plan": "reading the band plan", "weather": "looking up the weather", "hf_conditions":
             "looking up HF conditions", "make_chirp": "making a CHIRP file", "make_ics213": "writing an ICS-213",
             "make_ics205": "making an ICS-205 radio plan", "make_ics309": "making an ICS-309 log",
             "nets": "looking at the nets", "make_net_schedule": "making the net schedule files", "lookup_call": "looking up a call", "leave_message": "taking a note for you",
             "search_library": "searching the library", "search_web": "searching the web"}


class Tools:
    """The tools the model may call for one question. Files made are kept in self.files until the reply names them."""

    def __init__(self, e: "Einstein", rid: str, peer: str, sess: dict):
        self.e, self.rid, self.peer, self.sess = e, rid, peer, sess
        self.files: dict[str, dict] = {}
        self.calls: list[str] = []
        self.alerted = False
        S = _spec
        self.specs = [
            S("band_plan", "The band plan for this station's area for one band or frequency (e.g. '2 m', '70 cm', "
              "'40 m', '146.52'): the plan's segments and channels and what the asker's license class may use. "
              "as_file true also makes it a page (a table with what their license allows on each row) to attach: "
              "use it whenever they ask for the band plan.",
              {"band": {"type": "string"}, "as_file": {"type": "boolean"}}, ["band", "as_file"]),
            S("weather", "Forecast and active alerts for a place (a town with state or country, a US ZIP, a grid "
              "square, 'lat, lon', or 'here' for this station's area). as_form true also makes an ICS-213 file.",
              {"place": {"type": "string"}, "as_form": {"type": "boolean"}}, ["place", "as_form"]),
            S("hf_conditions", "Space weather now (solar flux, K index, NOAA scales) and what it means for HF. "
              "as_form true also makes an ICS-213 file.", {"as_form": {"type": "boolean"}}, ["as_form"]),
            S("make_chirp", "Make a CHIRP memory CSV. source: 'local' (the area's EMCOMM channels for a handheld: "
              "2 m and 70 cm FM voice repeaters and simplex from the local ARES / RACES / club plans, the calling "
              "channel, and this station's reserved ad hoc channels; band empty = both bands; use it for 'local' or "
              "'EMCOMM' channels), 'radio_list' (this station's radio channels), 'band_plan' (every channel in the "
              "area plan, optionally one band), 'adhoc' (reserved ad hoc channels) or 'custom' (the channels given). "
              "radio: 'ht' (2 m / 70 cm handheld: Baofeng, Quansheng) or 'any'. One call makes one file with every band "
              "asked for: call it once per request (several CHIRP files attached to one reply are merged into one).",
              {"source": {"type": "string", "enum": ["local", "radio_list", "band_plan", "adhoc", "custom"]},
               "band": {"type": "string"}, "radio": {"type": "string", "enum": ["ht", "any"]},
               "title": {"type": "string"},
               "channels": {"type": "array", "items": _CHAN}}, ["source", "band", "radio", "title", "channels"]),
            S("make_ics213", "An ICS-213 General Message for any report or message to the asker.",
              {"to": {"type": "string"}, "subject": {"type": "string"}, "message": {"type": "string"},
               "incident": {"type": "string"}}, ["to", "subject", "message", "incident"]),
            S("make_ics205", "An ICS-205 Incident Radio Communications Plan. source 'adhoc', 'radio_list' or "
              "'band_plan' fills the channels from this station; 'custom' uses the channels given.",
              {"incident": {"type": "string"}, "period": {"type": "string"},
               "source": {"type": "string", "enum": ["adhoc", "radio_list", "band_plan", "custom"]},
               "band": {"type": "string"}, "channels": {"type": "array", "items": _CHAN},
               "instructions": {"type": "string"}}, ["incident", "period", "source", "band", "channels", "instructions"]),
            S("make_ics309", "An ICS-309 Communications Log of this VARA session.", {"incident": {"type": "string"}},
              ["incident"]),
            S("nets", "This station's scheduled nets and when they meet next.", {}, []),
            S("make_net_schedule", "This station's net schedule as two files: a calendar (.ics, the next 8 weeks; any "
              "phone or computer calendar opens it) and a HAM Sidekick net file (.hsnets; another HAM Sidekick station "
              "adds the nets to its schedule). Attach both.", {}, []),
            S("lookup_call", "A callsign's public FCC (US) or country entry: name, license class, city and state.",
              {"call": {"type": "string"}}, ["call"]),
            S("search_web", "The whole internet, live: searches the web and X and reads pages, then answers. Use it for "
              "any question you cannot answer for certain from what you know: news and headlines (world, national, "
              "local, amateur radio), events, sports, schedules, products and specs, places, public figures, how-to, "
              "or a page whose address the asker gives. Returns a short answer with the sources' names. query: the "
              "question, in words (include any address given).", {"query": {"type": "string"}}, ["query"]),
            S("leave_message", "Take a note for the station's control operator (the only message you may take).",
              {"text": {"type": "string"}}, ["text"]),
        ]
        if e.cfg.get("share_library") or sess.get("owner"):
            self.specs.append(S("search_library", "Search this station's library (its manual and the operator's "
                                "documents) for a topic.", {"query": {"type": "string"}}, ["query"]))

    def run(self, name: str, arguments) -> str:
        self.calls.append(str(name))
        self.e._step(self.rid, self.peer, TOOL_STEP.get(str(name), "using " + str(name)))
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
            fn = getattr(self, "t_" + str(name), None)
            if not fn or name not in {s["function"]["name"] for s in self.specs}:
                return f"unknown tool {name!r}"
            return str(fn(**args))[:6000]
        except Exception as e:  # noqa: BLE001 - said to the model, never raised
            return f"tool failed ({type(e).__name__}: {str(e)[:160]}): say it could not be done"

    # ----- files -----
    def _file(self, name: str, data: bytes, what: str) -> str:
        if len(data) > self.e.cfg.get("file_max", FILE_MAX):
            return f"not made: {len(data) // 1024} KB is more than this station sends ({FILE_MAX // 1024} KB); ask for less"
        fid = f"f{len(self.files) + 1}"
        self.files[fid] = {"name": name, "data": data, "what": what}
        chirp, self._chirp_next = getattr(self, "_chirp_next", None), None
        if chirp:
            self.files[fid]["chirp"] = chirp
        est = self.e.airtime_s(self.rid, self.peer, len(data))
        return (f"made file {fid}: {name} ({len(data) / 1024:.1f} KB"
                + (f", about {est:.0f} s on this link" if est else "") + f"). Put \"{fid}\" in attach to send it.")

    # ----- tools -----
    def t_band_plan(self, band: str = "", as_file: bool = False) -> str:
        lo, hi, label = _band_range(band)
        if lo is None:
            return "unknown band: say e.g. '2 m', '70 cm', '40 m' or a frequency in MHz"
        t = self.e.plans().consolidated()
        cls = self.sess.get("asker_class")
        srcs = [s["name"] for s in t.get("sources", []) if s.get("authority") not in ("adhoc",)][:12]
        lines = [f"Band plan for {label} in this station's area (from: {', '.join(srcs[:6]) or 'ARRL/FCC'})"]
        page = []
        for b in t.get("bands") or []:
            for r in b["rows"]:
                if r["to"] < lo or r["from"] > hi:
                    continue
                f = f"{r['from']:.4f}" if r["type"] == "channel" else f"{r['from']:.3f}-{r['to']:.3f}"
                extra = ""
                if r.get("offset_mhz"):
                    extra += f" offset {r['offset_mhz']:+.3f}"
                if r.get("tone_hz"):
                    extra += f" tone {r['tone_hz']}"
                if len(lines) <= 60:
                    lines.append(f"{f} MHz {r['type']}: {r.get('use') or ''}{extra}" + (f" [{r['by']}]" if r.get("by") else ""))
                if as_file:
                    mid = r["from"] if r["type"] == "channel" else (r["from"] + r["to"]) / 2
                    you = (", ".join(k for k in ("phone", "data", "cw") if bandplan.privileges(mid, k, cls)[0]) or "no")\
                        if cls else "license class not known"
                    page.append({"freq": f, "type": r["type"], "use": r.get("use") or "", "extra": extra.strip(),
                                 "by": r.get("by") or "", "you": you})
        if cls:
            p = [k for k in ("phone", "data", "cw") if bandplan.privileges((lo + hi) / 2, k, cls)[0]]
            lines.append(f"{self.peer} holds a {cls.title()} license: {', '.join(p) or 'no'} privileges in the middle "
                         f"of this range (check each edge).")
        if as_file and page:
            who = (f"For {self.peer}, {cls.title()} class: the You may column is what that license allows on each row "
                   "(check each edge of a range)." if cls else f"For {self.peer}: license class not known.")
            html_ = forms.band_plan_page(f"Band plan {label}", page, who, srcs,
                                         f"Sent over VARA by {self.e.call(self.rid)} for {self.e.op_call(self.rid)}, "
                                         f"{datetime.now():%Y-%m-%d}. The plans are each organisation's; this is a summary.")
            lines.append(self._file(f"BandPlan-{forms.slug(band)}{('-' + cls.title()) if cls else ''}.html",
                                    html_.encode(), "band plan " + label))
        return "\n".join(lines)

    def t_weather(self, place: str = "", as_form: bool = False) -> str:
        from . import wx
        p = self.e.here() if str(place).strip().lower() in ("", "here", "your area", "there") else wx.place(place, fetch=self.e.fetch)
        if not p:
            return "unknown place: ask for a town with its state or country, a ZIP, or a grid square"
        w = wx.forecast(p, fetch=self.e.fetch)
        text = (f"Weather for {w['place']} ({w['source']}, {datetime.now():%Y-%m-%d %H:%M} local at {self.e.of(self.rid)}):\n"
                + "".join(f"ALERT: {a['event']} ({a['severity']}): {a['headline']}\n" for a in w["alerts"])
                + "".join(f"{x['name']}: {x['text']} Temp {x['temp']}. Wind {x['wind']}.\n" for x in w["periods"]))
        if as_form:
            return text + "\n" + self._form213("Weather: " + w["place"], text, "Weather report")
        return text

    def t_hf_conditions(self, as_form: bool = False) -> str:
        from . import wx
        s = wx.space(fetch=self.e.fetch)
        text = f"HF conditions {datetime.utcnow():%Y-%m-%d %H:%M} UTC ({s['source']}): {wx.conditions_words(s)}"
        if as_form:
            return text + "\n" + self._form213("HF conditions", text, "Propagation report")
        return text

    def _form213(self, subject: str, message: str, incident: str) -> str:
        ecall, name = self.e.call(self.rid), self.e.name()
        v = {"inc_name": incident, "To_Name": self.peer, "fm_name": f"{name} (automated assistant), {ecall}",
             "Subjectline": subject[:90], "Mdate": f"{datetime.now():%Y-%m-%d}", "mtime": f"{datetime.now():%H:%M}",
             "Message": message, "Approved_Name": f"{name}, automated assistant",
             "Approved_PosTitle": f"for {self.e.op_call(self.rid)}, control operator", "IsExercise": ""}
        out = self._file(f"ICS213-{forms.slug(subject)}.html", forms.ics213(v, f"Sent over VARA by {ecall}").encode(),
                         "ICS-213 " + subject)
        xml = forms.winlink_xml("ics213", v, ecall)
        if xml:
            out += " " + self._file(xml[0], xml[1], "Winlink Express form data for the same ICS-213 (optional)")
        return out

    def t_make_ics213(self, to: str = "", subject: str = "", message: str = "", incident: str = "") -> str:
        problems = text_problems(message)
        if problems:
            return "not made: " + "; ".join(problems)
        return self._form213(subject or "Message", message, incident or "")

    def _channels(self, source: str, band: str, custom) -> list[dict]:
        from . import radiochan as R
        P = self.e.plans()
        if source == "custom":
            out = []
            for c in custom or []:
                try:
                    f = float(c.get("freq_mhz"))
                except (TypeError, ValueError):
                    continue
                off = c.get("offset_mhz")
                out.append({"freq_mhz": f, "offset_mhz": float(off) if off not in (None, "") else None,
                            "tone_hz": float(c["tone_hz"]) if c.get("tone_hz") not in (None, "", 0) else None,
                            "mode": R.mode_of(f, c.get("mode")), "alias": R.alias(c.get("alias") or R.fmt_f(f)),
                            "name": R.long_name(c.get("name") or "")})
            return out[:R.MAX]
        if source == "local":
            return self._local(P, band)
        if source == "adhoc":
            items = [r for r in R.listing(P.adhoc(), [], []) if r["src"] == "adhoc"]
        elif source == "radio_list":
            t = P.consolidated()
            items = (t.get("radio") or {}).get("channels") or []
        else:
            t = P.consolidated()
            items = []
            for b in t.get("bands") or []:
                for r in b["rows"]:
                    if r["type"] == "channel":
                        items.append({"freq_mhz": r["from"], "offset_mhz": r.get("offset_mhz"), "tone_hz": r.get("tone_hz"),
                                      "mode": R.mode_of(r["from"], r.get("mode")),
                                      "alias": r.get("alias") or R.suggest_alias({"freq_mhz": r["from"],
                                                                "offset_mhz": r.get("offset_mhz"), "name": r.get("use")}),
                                      "name": R.long_name(r.get("use") or "")})
        lo, hi, _ = _band_range(band) if band else (None, None, None)
        if lo is not None:
            items = [r for r in items if lo <= r["freq_mhz"] <= hi]
        return items

    def _local(self, P, band: str) -> list[dict]:
        """The area's EMCOMM channels for a handheld (owner 2026-11-24: "a quick request for a CHIRP file for local
        frequencies including 2m, 70cm EMCOMM repeater and simplex frequencies and adhoc frequencies that I have
        allocated on my bandplan"). Per band: the FM voice repeaters, then simplex, from the local plans the operator
        chose (ARES, RACES, ICS-205, club) and the channels they kept; the national calling channel; then the operator's
        reserved ad hoc channels. Never packet, APRS, Winlink gateways, digital voice or weak-signal calling."""
        from . import radiochan as R
        bands = [band] if band else ["2 m", "70 cm"]
        rngs = [r[:2] for r in (_band_range(b) for b in bands) if r[0] is not None]
        if not rngs:
            return []
        out = []
        t = P.consolidated()
        rows = [r for b in t.get("bands") or [] for r in b["rows"] if r["type"] == "channel"]
        ad = [r for r in R.listing(P.adhoc(), [], []) if r["src"] == "adhoc"]
        for lo, hi in rngs:
            rep_, simp, call_ = [], [], []
            for r in rows:
                f = r["from"]
                if not lo <= f <= hi or NOT_VOICE.search(str(r.get("use") or "")) or \
                        R.mode_of(f, r.get("mode")) not in ("FM", "NFM"):
                    continue
                local = r.get("authority") == "local" or r.get("kept")
                if not local and f not in CALLING_MHZ:
                    continue
                it = {"freq_mhz": f, "offset_mhz": r.get("offset_mhz"), "tone_hz": r.get("tone_hz"),
                      "mode": R.mode_of(f, r.get("mode")),
                      "alias": r.get("alias") or R.suggest_alias({"freq_mhz": f, "offset_mhz": r.get("offset_mhz"),
                                                                  "name": r.get("use"), "org": r.get("org")}),
                      "name": R.long_name(r.get("use") or "")}
                (rep_ if r.get("offset_mhz") else simp if local else call_).append(it)
            out += rep_ + simp + call_ + [a for a in ad if lo <= a["freq_mhz"] <= hi]
        return out[:R.MAX]

    def t_make_chirp(self, source: str = "band_plan", band: str = "", radio: str = "ht", title: str = "",
                     channels=None) -> str:
        from . import radiochan as R
        items = self._channels(source, band, channels)
        if not items:
            return "no channels found for that: say which band, or list the channels"
        p = R.plan(items, radio if radio in R.PROFILES else R.DEFAULT_PROFILE)
        prof = radio if radio in R.PROFILES else R.DEFAULT_PROFILE
        csv = R.chirp_csv(items, prof, 1)
        name = f"CHIRP-{forms.slug(title or (source + '-' + band))}.csv"
        self._chirp_next = {"items": items, "profile": prof}
        notes = []
        if p["left_out"]:
            notes.append(f"left out (not for this radio): {'; '.join(p['left_out'][:6])}")
        if p["clash_short"]:
            notes.append(f"read alike on a 7-character display: {'; '.join(p['clash_short'][:4])}")
        return (f"{len(p['rows'])} channels: " + ", ".join(f"{r['chirp_name']} {R.fmt_f(r['freq_mhz'])}" for r in p["rows"][:30])
                + (". " + ". ".join(notes) if notes else "") + ". Import in CHIRP: File > Import. "
                + self._file(name, csv.encode(), "CHIRP memory file"))

    def t_make_ics205(self, incident: str = "", period: str = "", source: str = "adhoc", band: str = "",
                      channels=None, instructions: str = "") -> str:
        items = self._channels(source, band, channels)
        if not items:
            return "no channels for the plan: say which, or list them"
        rows = []
        for i, r in enumerate(items[:40], 1):
            off = r.get("offset_mhz") or 0
            tone = f"{r['tone_hz']:.1f}" if r.get("tone_hz") else ""
            rows.append({"ch": i, "function": "Tactical" if not off else "Repeater", "name": r.get("alias", ""),
                         "assignment": r.get("name", ""), "rx": f"{r['freq_mhz']:.4f} N", "rx_tone": tone,
                         "tx": f"{r['freq_mhz'] + off:.4f} N", "tx_tone": tone,
                         "mode": "D" if "VARA" in str(r.get("name", "")).upper() else "A", "remarks": ""})
        ecall = self.e.call(self.rid)
        html_ = forms.ics205({"incident": incident, "prepared": f"{datetime.now():%Y-%m-%d %H:%M}", "period": period,
                              "prepared_by": f"{self.e.name()} (automated assistant), {ecall}, for {self.e.op_call(self.rid)}",
                              "instructions": instructions}, rows, f"Sent over VARA by {ecall}")
        return f"{len(rows)} channels in the plan. " + self._file(f"ICS205-{forms.slug(incident)}.html", html_.encode(),
                                                                   "ICS-205 " + incident)

    def t_make_ics309(self, incident: str = "") -> str:
        from .winlink import fit
        ecall = self.e.call(self.rid)
        rows = [{"time": datetime.fromtimestamp(m["at"]).strftime("%Y-%m-%d %H:%M"),
                 "from": self.peer if m["role"] == "asker" else ecall, "to": ecall if m["role"] == "asker" else self.peer,
                 "sub": fit(m["text"], 90)} for m in self.sess["log"]]
        h = forms.ics309({"incident": incident or "VARA session", "period": rows[0]["time"] if rows else "",
                          "operator": f"{self.e.name()} (automated), {ecall}", "station_id": ecall}, rows)
        return self._file(f"ICS309-{forms.slug(incident or 'session')}.html", h.encode(), "ICS-309 log")

    def t_nets(self) -> str:
        from . import recur
        out = []
        now = datetime.now()
        for n in (self.e.st.cfg.get("schedule") or [])[:30]:
            nxt = [o for o in recur.upcoming(n, now, 2) if o["start"] > now][:1]
            f = n.get("freq_mhz")
            out.append(f"{n.get('name')}: {f'{f:.3f} MHz ' if f else ''}{n.get('mode') or ''}"
                       + (f", next {nxt[0]['start']:%a %b %d %H:%M} local" if nxt else ""))
        return "\n".join(out) or "no nets on this station's schedule"

    def t_search_web(self, query: str = "") -> str:
        """A live web search (xAI's web_search), summarised short for the air with its sources named. Neutral: the
        news as reported, no opinion of its own."""
        q = " ".join(str(query or "").split())[:300]
        if not q:
            return "say what to look up"
        key = self.e._key()
        if not key:
            return "no xAI key on this station: web search is not available"
        from . import netfind
        body = {"model": WEB_MODEL, "max_tool_calls": 10, "tools": [{"type": "web_search"}, {"type": "x_search"}],
                "input": [{"role": "user", "content": f"Today is {datetime.now():%A %Y-%m-%d}, local time. A radio "
                          f"amateur asked: {q}\nSearch the web (and X when it helps; open any page they named) and "
                          "answer from what you find now. Short for the air: the answer first, then at most 6 one-line "
                          "points, each naming its source (e.g. AP, Reuters, BBC, ARRL, the maker, the local paper). "
                          "News as reported, neutral, no opinion. Plain text: no markdown, no links, under 900 "
                          "characters."}]}
        try:
            d = (self.e.web_post or _web_post)(key, body, WEB_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            return f"the web search failed ({getattr(e, 'code', None) or type(e).__name__}): say it could not be done"
        text, seen = netfind._text_and_sources(d)
        text = re.sub(r"\[\[\d+\]\]\([^)]*\)|\[([^\]]+)\]\(https?://[^)]+\)", r"\1", text or "")   # links out
        text = re.sub(r"https?://\S+", "", re.sub(r"\*\*|__|^#+\s*", "", text, flags=re.M)).strip()      # markdown out
        if not text:
            return "the web search found nothing: say so"
        sites = sorted({u.split("/")[0] for u in seen if u})[:8]
        return text[:1500] + (f"\n(searched: {', '.join(sites)})" if sites else "")

    def t_make_net_schedule(self) -> str:
        from . import netshare
        call = self.e.op_call(self.rid)
        nets = netshare.export(self.e.st, call)
        if not nets["nets"]:
            return "no nets on this station's schedule"
        a = self._file(f"{call}-nets.ics", netshare.ics(self.e.st, call).encode(), "net calendar")
        b = self._file(f"{call}-nets{netshare.SUFFIX}", json.dumps(nets, indent=1).encode(), "HAM Sidekick net file")
        return f"{len(nets['nets'])} nets. " + a + " " + b

    def t_lookup_call(self, call: str = "") -> str:
        cb = getattr(self.e.st, "callbook", None)
        c = str(call or "").upper().strip()
        if not cb or not re.fullmatch(r"[A-Z0-9]{3,7}(-\d{1,2})?", c):
            return "no callbook on this station, or not a callsign"
        card = cb.card(base(c))
        keep = {k: card.get(k) for k in ("call", "name", "license_class", "license_status", "city", "state",
                                         "country", "expires") if card.get(k)}
        return json.dumps(keep) if len(keep) > 1 else f"{c}: not found in the FCC database or the country list"

    def t_leave_message(self, text: str = "") -> str:
        self.e.mail_add(self.rid, self.peer, str(text)[:1000])
        return f"note kept for {self.e.op_call(self.rid)}"

    def t_search_library(self, query: str = "") -> str:
        a = getattr(self.e.st, "agent", None)
        out = a.library().context_for(str(query)[:300], 4000) if a else ""
        return out or "nothing in the library on that"


_CHAN = {"type": "object", "properties": {"freq_mhz": {"type": "number"}, "offset_mhz": {"type": "number"},
                                          "tone_hz": {"type": "number"}, "mode": {"type": "string"},
                                          "alias": {"type": "string"}, "name": {"type": "string"}},
         "required": ["freq_mhz", "offset_mhz", "tone_hz", "mode", "alias", "name"], "additionalProperties": False}


def _spec(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": required, "additionalProperties": False}}}


_BANDS = {"160": (1.8, 2.0), "80": (3.5, 4.0), "60": (5.33, 5.41), "40": (7.0, 7.3), "30": (10.1, 10.15),
          "20": (14.0, 14.35), "17": (18.068, 18.168), "15": (21.0, 21.45), "12": (24.89, 24.99), "10": (28.0, 29.7),
          "6": (50.0, 54.0), "2": (144.0, 148.0), "1.25": (222.0, 225.0), "220": (222.0, 225.0), "70": (420.0, 450.0),
          "440": (420.0, 450.0), "33": (902.0, 928.0), "23": (1240.0, 1300.0)}


def _band_word(text: str) -> str:
    """'2m', '70 CM', '440', '220', '6 meters' in a command's words -> the band as _band_range reads it ('' = none)."""
    t = str(text or "").lower()
    m = re.search(r"\b(160|80|60|40|30|20|17|15|12|10|6|2|1\.25|70|33|23)\s*(m|cm|meters?|metres?)\b|\b(440|220|1\.25)\b", t)
    if not m:
        return ""
    if m.group(3):
        return {"440": "70 cm", "220": "1.25 m", "1.25": "1.25 m"}[m.group(3)]
    return f"{m.group(1)} {'cm' if m.group(2) == 'cm' else 'm'}"


def _call_words(js: str) -> str:
    try:
        d = json.loads(js)
    except ValueError:
        return js
    where = ", ".join(x for x in (d.get("city"), d.get("state"), d.get("country")) if x)
    return (f"{d.get('call')}: {d.get('name') or ''}" + (f", {d['license_class']}" if d.get("license_class") else "")
            + (f" ({d['license_status']})" if d.get("license_status") else "") + (f", {where}" if where else "")
            + (f", expires {d['expires']}" if d.get("expires") else "") + " (this station's callbook)").replace(": ,", ":")


def _band_range(band: str):
    s = str(band or "").lower().replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(m|cm|mhz)?", s)
    if not m:
        return None, None, None
    n, unit = m.group(1), m.group(2)
    if unit == "mhz" or (unit is None and n not in _BANDS):
        f = float(n)
        for lo, hi in _BANDS.values():
            if lo <= f <= hi:
                return lo, hi, f"{f} MHz ({lo}-{hi})"
        return None, None, None
    key = n if unit != "cm" else {"70": "70", "33": "33", "23": "23"}.get(n, n)
    if key in _BANDS:
        lo, hi = _BANDS[key]
        return lo, hi, f"{n} {'cm' if unit == 'cm' else 'm'}"
    return None, None, None


# ---------------------------------------------------------------- Einstein ------------------------------------------
class Einstein:
    """Per station; per data radio its own call and switch. Settings in data/einstein.json (never committed)."""

    def __init__(self, station, clock=time.time, ask=None, fetch=None):
        self.st, self.clock = station, clock
        self.ask_model = ask                     # tests: (system, user, tools) -> (out dict, usage)
        self.fetch = fetch
        self.web_post = None                     # tests: (key, body, timeout) -> an xAI responses reply
        self.path = Path(station.data) / "einstein.json"
        self.lock = threading.RLock()
        self.cfg = {"radios": {}, "share_library": False, "file_max": FILE_MAX, "per_hour": PER_STATION_HOUR}
        try:
            self.cfg.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        self.sessions: dict[tuple, dict] = {}
        self.held: dict[tuple, list] = {}
        self.day: deque = deque()
        self.busy: dict[tuple, bool] = {}
        self._probe_stop = threading.Event()
        self._probing = False
        self.alerts: deque = deque(maxlen=20)
        self.now: dict[tuple, dict] = {}         # (rid, peer) -> the question being worked on (the dashboard shows it)
        self.recent: dict[str, deque] = {}      # rid -> the last questions and what became of them

    # ----- settings -----
    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cfg, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def rcfg(self, rid: str) -> dict:
        return dict({"on": False, "call": None, "paused": None}, **(self.cfg["radios"].get(rid) or {}))

    def share(self) -> dict:
        """What Einstein sends for PACK: the owner's choice (Settings → Einstein & AI), by default all but own files."""
        return dict(SHARE_DEFAULT, **{k: bool(v) for k, v in (self.cfg.get("share") or {}).items() if k in SHARE_DEFAULT})

    def name(self) -> str:
        a = getattr(self.st, "agent", None)
        return getattr(a, "name", None) or "Einstein"

    def _modem(self, rid):
        return self.st.vara.modem(rid)

    def of(self, rid: str) -> str:
        """The operator's call on this radio's modem (W9XYZ-7)."""
        try:
            return self._modem(rid).call()
        except Exception:  # noqa: BLE001
            return str(getattr(self.st, "me", "") or "N0CALL").upper()

    def op_call(self, rid: str) -> str:
        return base(self.of(rid)) or "N0CALL"

    def call(self, rid: str) -> str:
        c = self.rcfg(rid).get("call")
        return c or self.suggest_call(rid)

    def suggest_call(self, rid: str) -> str:
        b = base(self.of(rid))
        taken = set()
        try:
            for m in self.st.vara.data_radios():
                taken.add(self._modem(m["id"]).call().upper())
                c = self.rcfg(m["id"]).get("call")
                if c and m["id"] != rid:
                    taken.add(c.upper())
            taken |= set((self._modem(rid).chan.load().get("roster") or {}).keys())
        except Exception:  # noqa: BLE001
            pass
        try:                                     # W9XYZ-7 -> -14, W9XYZ-8 -> -15: two of your stations never suggest one call
            own = int(self.of(rid).split("-")[1])
        except (IndexError, ValueError):
            own = 0
        first = own + 7 if 9 <= own + 7 <= 15 else DEFAULT_SSID
        for n in (first,) + SSIDS:
            if f"{b}-{n}" not in taken:
                return f"{b}-{n}"
        return f"{b}-{DEFAULT_SSID}"

    def settings(self, body: dict) -> dict:
        from .vara import CALL_RE
        rid = body.get("radio")
        with self.lock:
            if "share_library" in body:
                self.cfg["share_library"] = bool(body["share_library"])
            if isinstance(body.get("share"), dict):          # what PACK sends (station/stationpack.py)
                self.cfg["share"] = {k: bool(body["share"].get(k, v)) for k, v in self.share().items()}
                self._save()
            if rid:
                r = dict(self.cfg["radios"].get(rid) or {})
                if "call" in body:
                    c = str(body["call"] or "").strip().upper() or None
                    if c:
                        if not CALL_RE.match(c) or "-" not in c:
                            raise ValueError("Einstein's call is your call with an SSID of its own, e.g. W9XYZ-15")
                        if base(c) != base(self.of(rid)):
                            raise ValueError(f"Einstein's call must be {base(self.of(rid))} with an SSID: the "
                                             f"station's licensee answers for it")
                        if c == self.of(rid).upper():
                            raise ValueError("that is your own call on this modem: give Einstein another SSID")
                    r["call"] = c
                if "on" in body:
                    if body["on"]:
                        ok, why = self.can_switch_on(rid)
                        if not ok:
                            raise ValueError(why)
                        r["paused"] = None
                    r["on"] = bool(body["on"])
                self.cfg["radios"][rid] = r
            self._save()
        if rid:
            try:
                self._modem(rid).einstein_sync()
            except Exception:  # noqa: BLE001
                pass
        if any(self.rcfg(r)["on"] for r in self.cfg["radios"]):
            self.start_probe()
        return self.view()

    def owner_key(self) -> str | None:
        from . import secrets
        return secrets.read(self.st.root, OWNER_KEY)

    def set_owner_key(self, value: str | None) -> dict:
        from . import secrets
        v = str(value or "").strip()
        if v and not re.fullmatch(r"[A-Za-z0-9-]{16,64}", v):
            raise ValueError("the owner key is 16 to 64 letters, digits or dashes (make one here, type it on your "
                             "other stations)")
        secrets.write(self.st.root, OWNER_KEY, v or None)
        return {"set": bool(v)}

    @staticmethod
    def new_owner_key() -> str:
        a = _rand.token_hex(12).upper()
        return "-".join(a[i:i + 6] for i in range(0, 24, 6))

    # ----- may it run? -----
    def _key(self) -> str | None:
        from . import secrets
        return secrets.read(self.st.root, "XAI_API_KEY")

    def online(self) -> tuple[bool, str]:
        if not self._key():
            return False, "needs the xAI key (Settings → Einstein & AI)"
        a = getattr(self.st, "agent", None)
        on = (getattr(a, "online", {}) or {}).get("xai")
        if on is not None and on.online is False:
            return False, "no internet: xAI cannot be reached (it comes back by itself)"
        return True, ""

    def rules(self, rid: str) -> dict:
        m = self._modem(rid)
        c = m.cfg()
        r = (getattr(self.st, "radios", {}) or {}).get(rid) or {}
        cls = ((getattr(getattr(self.st, "agent", None), "cfg", None) or {}).get("license_class") or "").lower() or None
        return auto_control(r.get("freq_mhz"), c.get("kind"), c.get("bw"), cls)

    def can_switch_on(self, rid: str) -> tuple[bool, str]:
        m = self._modem(rid)
        c = m.cfg()
        if not c.get("enabled") or c.get("use") == "winlink":
            return False, "set up this radio's VARA modem for chat first (Set up the VARA modem…)"
        ok, why = m.operator_ok()
        if not ok:
            return False, "switch Einstein on from a dashboard with transmitting allowed: " + why
        ok, why = self.rules(rid)["answer"]
        if not ok:
            return False, why
        return True, ""

    def active(self, rid: str) -> bool:
        """Switched on, not paused, and the radio/frequency/switch still allow it (internet aside)."""
        rc = self.rcfg(rid)
        if not rc["on"] or rc.get("paused"):
            return False
        m = self._modem(rid)
        ok, _ = m.base_ok()
        return bool(ok and self.rules(rid)["answer"][0])

    def answering(self, rid: str) -> bool:
        """Its call is on the modem: active. With no internet (or no xAI key) it stays on the air for what the station's
        code answers by itself: PACK, HELP and the owner's commands (owner 2026-11-24: "If Einstein can assemble the
        pack from the station without the internet that will be good for off grid pack sharing")."""
        return self.active(rid)

    def state(self, rid: str) -> dict:
        rc = self.rcfg(rid)
        ok_on, why_on = self.online()
        r = self.rules(rid)
        word = ("off" if not rc["on"] else "paused" if rc.get("paused") else
                "answering" if self.answering(rid) else "waiting")
        why = ("" if word == "off" else ("" if ok_on else OFFLINE_WHY) if word == "answering" else
               rc.get("paused") if word == "paused" else
               r["answer"][1] if not r["answer"][0] else self._modem(rid).base_ok()[1])
        return {"on": rc["on"], "call": self.call(rid), "call_set": bool(rc.get("call")), "state": word, "why": why,
                "announce": r["announce"], "answer": r["answer"], "can_on": self.can_switch_on(rid),
                "unread": sum(1 for x in self.mail(rid) if not x.get("read")),
                "linked": sorted(p for (r_, p) in list(self.sessions) if r_ == rid),
                "working": [dict(v, peer=p) for (r_, p), v in sorted(list(self.now.items()), key=lambda x: x[1]["at"])
                            if r_ == rid],
                "recent": list(self.recent.get(rid) or [])[::-1], "clock": self.clock()}

    # ----- what Einstein is doing, for the dashboard (owner 2026-11-24: "see that a request has come into Einstein and
    # that einstein is working on it") -----
    def _show(self, rid):
        try:
            self.st.vara._publish("einstein", rid)
        except Exception:  # noqa: BLE001
            pass

    def _step(self, rid, peer, step: str):
        with self.lock:
            j = self.now.get((rid, peer))
            if j is not None:
                j["step"] = step
        self._show(rid)

    def _done(self, rid, peer, text, outcome: str, ok: bool = True, tools=(), files=(), started=None):
        with self.lock:
            j = self.now.pop((rid, peer), None)
            at = (j or {}).get("at") or started or self.clock()
            self.recent.setdefault(rid, deque(maxlen=12)).append(
                {"peer": peer, "text": str(text)[:200], "at": at, "took_s": round(self.clock() - at, 1),
                 "outcome": outcome, "ok": ok, "tools": list(tools), "files": list(files)})
        self._show(rid)

    def view(self) -> dict:
        out = {"name": self.name(), "share_library": bool(self.cfg.get("share_library")), "share": self.share(),
               "owner_key_set": bool(self.owner_key()), "radios": {}, "alerts": list(self.alerts)}
        try:
            for m in self.st.vara.data_radios():
                out["radios"][m["id"]] = self.state(m["id"])
        except Exception:  # noqa: BLE001
            pass
        return out

    # ----- the internet probe -----
    def start_probe(self):
        if self._probing:
            return
        self._probing = True

        def loop():
            while not self._probe_stop.wait(PROBE_S):
                try:
                    self.probe()
                except Exception as e:  # noqa: BLE001
                    print(f"einstein probe: {type(e).__name__}: {e}", flush=True)
        threading.Thread(target=loop, daemon=True, name="einstein-probe").start()

    def probe(self):
        if not any(self.rcfg(r)["on"] for r in self.cfg["radios"]):
            return
        key = self._key()
        a = getattr(self.st, "agent", None)
        if not key or a is None:
            return
        from .online import Online, is_network_error
        on = a.online.setdefault("xai", Online("xai"))
        before = on.online
        import urllib.request
        try:
            with urllib.request.urlopen(urllib.request.Request("https://api.x.ai/v1/models",
                                                               headers={"Authorization": f"Bearer {key}"}), timeout=8):
                pass
            on.ok()
        except Exception as e:  # noqa: BLE001
            (on.failed if is_network_error(e) else (lambda _e: on.ok()))(e)
        if on.online != before:
            for rid in list(self.cfg["radios"]):
                try:
                    self._modem(rid).einstein_sync()
                except Exception:  # noqa: BLE001
                    pass

    # ----- where is "here" (rounded) -----
    def here(self) -> dict | None:
        from . import wx
        g = self._grid()
        ll = wx.grid_latlon(g) if g else None
        return {"lat": ll[0], "lon": ll[1], "label": f"this station's area (grid {g})", "us": None} if ll else None

    def area(self) -> str:
        g = self._grid()
        return f"grid square {g}" if g else "not given"

    def _grid(self) -> str:
        """The operator's locator as set (FN31pr), at most 6 characters. The 4-character square is 1 x 2 degrees: its
        middle can be another state (owner 2026-11-24: a 6-character locator, weather came back for a town in the next state)."""
        g = re.sub(r"\s+", "", str(((self.st._saved() or {}).get("operator") or {}).get("grid") or ""))
        return g[:6] if re.fullmatch(r"[A-Ra-r]{2}\d{2}([A-Xa-x]{2})?", g[:6]) else g[:4]

    def plans(self):
        from .server import _plans
        return _plans(self.st)

    def airtime_s(self, rid, peer, size) -> float | None:
        from .varachan import estimate_s
        try:
            sp = ((self._modem(rid).chan.load().get("roster") or {}).get(peer) or {}).get("speed")
            return estimate_s(sp, size) if sp else None
        except Exception:  # noqa: BLE001
            return None

    # ----- the operator's notes -----
    def _mail_path(self, rid) -> Path:
        return Path(self.st.data) / "einstein" / f"{rid}-notes.json"

    def mail(self, rid) -> list[dict]:
        try:
            return json.loads(self._mail_path(rid).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def mail_add(self, rid, peer, text, kind="note"):
        p = self._mail_path(rid)
        p.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            ms = self.mail(rid) + [{"id": uuid.uuid4().hex[:10], "from": peer, "text": text, "kind": kind,
                                    "at": self.clock(), "read": False}]
            p.write_text(json.dumps(ms[-MAIL_KEEP:], indent=1), encoding="utf-8")
        self._publish(rid)

    def mail_read(self, rid, ids=None) -> list[dict]:
        with self.lock:
            ms = self.mail(rid)
            for m in ms:
                if ids is None or m["id"] in ids:
                    m["read"] = True
            self._mail_path(rid).parent.mkdir(parents=True, exist_ok=True)
            self._mail_path(rid).write_text(json.dumps(ms, indent=1), encoding="utf-8")
        return ms

    def _publish(self, rid=None):
        try:
            self.st.bus.publish("einstein", self.view())
        except Exception:  # noqa: BLE001
            pass

    def _log(self, rid, entry):
        p = Path(self.st.data) / "einstein" / f"{rid}-{datetime.now():%Y-%m}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(dict(entry, at=datetime.now().isoformat(timespec="seconds"))) + "\n")

    # ----- the link (called by the modem's channel, station/varachan.py) -----
    def handshake_caps(self, rid: str) -> str:
        """Words after Einstein's call in its HSK1 handshake (docs/VARA.md)."""
        return f"+TEST +AI +OF={self.of(rid)} +NAME={re.sub(r'[^A-Za-z0-9]+', '_', self.name())[:20]}"

    def parent_caps(self, rid: str) -> str:
        """Words the operator's own call adds while Einstein answers: where to find it."""
        return f"+AI={self.call(rid)}" if self.answering(rid) else ""

    def on_connected(self, rid, peer, link_id=None) -> str:
        """A station linked to Einstein's call: a new session; returns the per-link challenge (+NONCE=...)."""
        nonce = _rand.token_hex(8).upper()
        with self.lock:
            self.sessions[(rid, peer)] = {"at": self.clock(), "nonce": nonce, "owner": False, "disclosed": False,
                                          "last_id": 0, "log": [], "asked": deque(), "files": deque(),
                                          "history": [], "asker_class": None, "checked": None}
        self._log(rid, {"kind": "link", "peer": peer})
        self._show(rid)
        return nonce

    def on_auth(self, rid, peer, token: str):
        s = self.sessions.get((rid, peer))
        key = self.owner_key()
        if not s or not key or base(peer) != base(self.of(rid)):
            return
        want = owner_token(key, s["nonce"], peer)
        if hmac.compare_digest(want, str(token or "").strip().lower()):
            s["owner"] = True
            self._log(rid, {"kind": "owner", "peer": peer})

    def on_disconnected(self, rid, peer):
        with self.lock:
            self.sessions.pop((rid, peer), None)
        self._show(rid)

    def on_chat(self, rid: str, peer: str, text: str, send):
        """A message typed to Einstein. send(text=None, name=None, data=None) puts something on this link (and keeps
        it for the station's next link when this one has closed)."""
        text = str(text or "").strip()[:4000]
        if not text:
            return
        s = self.sessions.get((rid, peer)) or self.sessions.setdefault((rid, peer), {
            "at": self.clock(), "nonce": "", "owner": False, "disclosed": False, "last_id": 0, "log": [],
            "asked": deque(), "files": deque(), "history": [], "asker_class": None, "checked": None})
        s["log"].append({"role": "asker", "text": text, "at": self.clock()})
        self._log(rid, {"kind": "in", "peer": peer, "text": text})
        out = []
        t0 = self.clock()
        if not self.busy.get((rid, peer)):
            with self.lock:
                self.now[(rid, peer)] = {"text": text[:200], "at": t0, "step": "reading the question"}
            self._show(rid)

        def quick(outcome, ok=True):
            if not self.busy.get((rid, peer)):
                self._done(rid, peer, text, outcome, ok=ok, started=t0)

        def say(t):
            t = self._wrap(rid, peer, s, t)
            s["log"].append({"role": "einstein", "text": t, "at": self.clock()})
            self._log(rid, {"kind": "out", "peer": peer, "text": t})
            send(text=t)
            out.append(t)
        if s["checked"] is None:
            s["checked"] = self._licensed(peer, s)
        if s["checked"] is not True:
            say(f"Sorry {peer}: {s['checked']} I answer licensed amateurs only (Part 97).")
            quick("turned away: " + str(s["checked"]), ok=False)
            return
        if EMERGENCY.search(text):
            self.alerts.appendleft({"rid": rid, "peer": peer, "text": text[:300], "at": self.clock()})
            self.mail_add(rid, peer, "EMERGENCY? " + text[:900], kind="alert")
            say("If anyone is in danger, call 911 (or your local emergency number) now, or call on your local "
                f"emergency net or repeater. I am an automated station and cannot send help; I have alerted "
                f"{self.op_call(rid)}, the control operator.")
        cmd = text.strip().upper()
        if re.match(r"PACK\b", cmd):                 # owner 2026-11-24: the band plan and nets, to install there
            say(self._pack(rid, peer, send))
            quick("answered: sent the station pack" if s.get("pack_sent") else "answered PACK: nothing to send", ok=True)
            return
        if cmd in ("HELP", "?", "MENU"):
            say(DIRECT_HELP + ASK_HELP + (OWNER_HELP if s["owner"] else ""))
            quick("answered: its HELP list")
            return
        if cmd in ("STATUS", "MESSAGES", "PAUSE", "RESUME"):
            if not s["owner"]:
                say(f"{cmd} is for this station's operator, from one of their own stations with the owner key set.")
                quick(f"turned away: {cmd} needs the owner key", ok=False)
                return
            say(self._owner(rid, cmd))
            quick(f"answered your {cmd} (owner key)")
            return
        if self._direct(rid, peer, s, text, send, say, t0):   # owner 2026-11-24: quick requests answered without the AI
            return
        now = self.clock()
        while s["asked"] and now - s["asked"][0] > 3600:
            s["asked"].popleft()
        while self.day and now - self.day[0] > 86400:
            self.day.popleft()
        if len(s["asked"]) >= int(self.cfg.get("per_hour") or PER_STATION_HOUR) and not s["owner"]:
            say(f"That is {len(s['asked'])} questions this hour, my limit for one station: try again later.")
            quick("turned away: its limit of questions an hour", ok=False)
            return
        if len(self.day) >= PER_DAY:
            say("I have answered my limit of questions for today: try again tomorrow.")
            quick("turned away: the day's limit of questions", ok=False)
            return
        if not self.online()[0]:                     # off grid: what the station's code does needs no internet
            say(OFFLINE_SAY)
            quick("not answered: no internet here (its command words still work)", ok=False)
            return
        if self.busy.get((rid, peer)):
            say("Still working on your last question: one at a time, please.")
            return
        s["asked"].append(now)
        self.day.append(now)
        send(note="WORKING 30")
        self.busy[(rid, peer)] = True
        self._step(rid, peer, "thinking")
        threading.Thread(target=self._think, args=(rid, peer, s, text, send), daemon=True,
                         name=f"einstein-{peer}").start()

    def _pack(self, rid, peer, send) -> str:
        """PACK: this station's band plan (the local plans read here, kept channels, ad hoc channels) and net schedule
        as one station pack, as the operator chose in Settings; made by code, no model, the same every time. The
        file follows the reply; a HAM Sidekick station shows 📦 Review and install… on it."""
        from . import stationpack as SP
        sh = self.share()
        parts = [k for k in SP.PARTS if sh.get(k)]
        s = self.sessions.get((rid, peer)) or {}
        s["pack_sent"] = False
        now = self.clock()
        sent = [t for t in s.get("packs") or [] if now - t < 3600]
        if len(sent) >= PACKS_PER_HOUR and not s.get("owner"):
            return f"I sent you the station pack {len(sent)} times this hour: it has not changed since; try later."
        if not parts:
            return f"{self.op_call(rid)} shares nothing this way: ask them on the air."
        doc = SP.build(self.st, parts, bool(sh.get("own_files")))
        c = SP.counts(doc)
        if not any(c[k] for k in ("plans", "kept", "adhoc", "nets")):
            return "This station has no band plan or nets to share yet."
        data = SP.dumps(doc)
        if len(data) > self.cfg.get("file_max", FILE_MAX):
            return f"The station pack is {len(data) // 1024} KB, more than I send ({FILE_MAX // 1024} KB)."
        est = self.airtime_s(rid, peer, len(data))
        what = ", ".join(x for x in (
            f"{c['plans']} local plan{'s' if c['plans'] != 1 else ''} ({c['channels']} channels, {c['segments']} ranges)" if c["plans"] else "",
            f"{c['kept']} kept channel{'s' if c['kept'] != 1 else ''}" if c["kept"] else "",
            f"{c['adhoc']} ad hoc channel{'s' if c['adhoc'] != 1 else ''}" if c["adhoc"] else "",
            f"{c['nets']} net{'s' if c['nets'] != 1 else ''}" if c["nets"] else "") if x)
        send(name=SP.name_for(doc), data=data)
        s["pack_sent"] = True
        s["packs"] = sent + [now]
        self._log(rid, {"kind": "pack", "peer": peer, "bytes": len(data), "counts": c})
        return (f"Sending {base(self.of(rid))}'s station pack: {what}. {len(data) / 1024:.1f} KB"
                + (f", about {est:.0f} s" if est else "") + ". On HAM Sidekick Station open it with 📦 Review and "
                "install: you choose what goes into your band plan and schedule; nothing of yours is deleted.")

    def _send_files(self, s, files, send):
        now = self.clock()
        while s["files"] and now - s["files"][0] > 3600:
            s["files"].popleft()
        for f in files:
            if len(s["files"]) >= FILES_PER_HOUR and not s["owner"]:
                send(text=f"(not sending {f['name']}: {FILES_PER_HOUR} files an hour is my limit)")
                break
            if Path(f["name"]).suffix.lower() not in SAFE_EXT:
                continue
            s["files"].append(now)
            send(name=f["name"], data=f["data"])

    def _direct(self, rid, peer, s, text, send, say, t0) -> bool:
        """A command word answered by the station's code, never the model (owner 2026-11-24: "From our quick selects,
        what else can we send information for without the AI?" — "go"): the same every time, free, quick, and off grid
        for all but WX and HF (they need the internet, not the AI). A command word followed by a long sentence goes to
        the model when it is reachable (it may want something the word alone does not say)."""
        m = DIRECT_RE.match(text)
        if not m:
            return False
        word = re.sub(r"[\s-]", "", m.group(1).upper())
        word = DIRECT_ALIAS.get(word, word)
        rest = " ".join(m.group(2).split())
        online = self.online()[0]
        if word == "CALL" and not re.fullmatch(r"[A-Za-z0-9]{3,7}(-\d{1,2})?", rest):
            return False                                  # "call me later": a sentence, not a lookup
        if word != "MSG" and len(rest.split()) > (6 if word in ("WX", "WX213") else 4) and online:
            return False
        if word == "MSG" and not rest:
            say("MSG and your note, e.g. MSG please call me on 146.520 tonight.")
            self._done(rid, peer, text, "answered: how to use MSG", started=t0)
            return True
        tools = Tools(self, rid, peer, s)
        band = _band_word(rest)
        try:
            if word == "CHIRP":
                out = tools.t_make_chirp(source="local", band=band, radio="ht",
                                         title="Local EMCOMM " + (band or "2m-70cm-adhoc"))
            elif word == "BANDPLAN":
                if not band:
                    say("BANDPLAN and a band, e.g. BANDPLAN 2M, BANDPLAN 70CM or BANDPLAN 40M.")
                    self._done(rid, peer, text, "answered: how to use BANDPLAN", started=t0)
                    return True
                out = tools.t_band_plan(band, as_file=True)
                lines = out.split("\n")
                out = "\n".join([lines[0]] + [x for x in lines[1:] if "license" in x or "made file" in x])
            elif word == "ICS205":
                out = tools.t_make_ics205(incident=rest or "Ad hoc channels", source="adhoc")
            elif word == "ICS309":
                out = tools.t_make_ics309(incident=rest)
            elif word == "NETS":
                out = tools.t_nets()
            elif word == "CALENDAR":
                out = tools.t_make_net_schedule()
            elif word == "MSG":
                out = tools.t_leave_message(rest) + ". 73"
            elif word == "CALL":
                out = _call_words(tools.t_lookup_call(rest))
            elif word in ("WX", "WX213"):
                out = tools.t_weather(rest or "here", as_form=word == "WX213")
            else:                                         # HF, HF213
                out = tools.t_hf_conditions(as_form=word == "HF213")
        except Exception as e:  # noqa: BLE001
            net = word in ("WX", "WX213", "HF", "HF213")
            self._log(rid, {"kind": "error", "peer": peer, "error": f"{word}: {type(e).__name__}: {str(e)[:200]}"})
            say(f"{word} needs the internet here, and it cannot be reached now." if net
                else f"Sorry, {word} did not work just now ({type(e).__name__}); {self.op_call(rid)} can follow up.")
            self._done(rid, peer, text, f"could not answer {word}", ok=False, started=t0)
            return True
        files = one_file_each(list(tools.files.values()))
        reply = re.sub(r"made file f\d+: (.+?)\. Put \"f\d+\" in attach to send it\.", r"Sending \1.", out)
        bad = text_problems(reply)
        if bad:
            reply, files = "I can't send that on amateur radio (" + "; ".join(bad) + ").", []
        if len(reply) > REPLY_CHARS:
            reply = reply[:REPLY_CHARS - 40].rsplit(" ", 1)[0] + " … (the file has it all)" if files else \
                reply[:REPLY_CHARS - 4].rsplit(" ", 1)[0] + " …"
        s["history"] += [{"role": "asker", "text": text}, {"role": "einstein", "text": reply}]
        say(reply)
        self._log(rid, {"kind": "direct", "peer": peer, "word": word, "files": [f["name"] for f in files]})
        self._send_files(s, files, send)
        self._done(rid, peer, text, f"answered {word} (no AI)", tools=tools.calls or [word.lower()],
                   files=[f["name"] for f in files], started=t0)
        return True

    def _wrap(self, rid, peer, s, text) -> str:
        """Disclosure first, then the call every 10 minutes (97.119(a), 97.113(a)(4)), as code, never the model."""
        ecall = self.call(rid)
        if not s["disclosed"]:
            s["disclosed"] = True
            s["last_id"] = self.clock()
            return disclosure(self.name(), ecall, self.of(rid), self.op_call(rid)) + "\n" + text
        if self.clock() - s["last_id"] >= ID_EVERY_S:
            s["last_id"] = self.clock()
            return text + f"\nde {ecall}"
        return text

    def _licensed(self, peer: str, s: dict):
        from .vara import CALL_RE
        if not CALL_RE.match(peer):
            return "that is not a callsign."
        cb = getattr(self.st, "callbook", None)
        if cb is None:
            return True
        b = base(peer)
        try:
            from .callbook import US
            if US.match(b):
                if not getattr(cb, "con", None):
                    return True
                f = cb.fcc(b)
                if not f:
                    return f"{b} is not in the FCC database here."
                if f.get("valid") is False:
                    return f"{b}'s license is not active in the FCC database here."
                s["asker_class"] = str(f.get("class_name") or "").lower() or None
                return True
            return True if cb.country(b) or not getattr(cb, "cty", None) else f"{b} has no known country prefix."
        except Exception:  # noqa: BLE001
            return True

    def _owner(self, rid, cmd) -> str:
        if cmd == "STATUS":
            st = self.state(rid)
            r = (getattr(self.st, "radios", {}) or {}).get(rid) or {}
            return (f"{self.call(rid)}: {st['state']}{' (' + st['why'] + ')' if st['why'] else ''}; "
                    f"{r.get('freq_mhz') or '?'} MHz; {len(self.day)} questions in 24 h; {st['unread']} unread notes; "
                    f"sessions now: {', '.join(p for (r_, p) in self.sessions if r_ == rid) or 'none'}.")
        if cmd == "MESSAGES":
            ms = [m for m in self.mail(rid) if not m.get("read")][-10:]
            if not ms:
                return "No unread notes."
            self.mail_read(rid, {m["id"] for m in ms})
            return "\n".join(f"{datetime.fromtimestamp(m['at']):%m-%d %H:%M} {m['from']}: {m['text']}" for m in ms)
        if cmd == "PAUSE":
            r = dict(self.cfg["radios"].get(rid) or {})
            r["paused"] = "paused from the air by its operator"
            self.cfg["radios"][rid] = r
            self._save()
            threading.Timer(5.0, lambda: self._modem(rid).einstein_sync()).start()   # after this reply has gone
            self._publish(rid)
            return f"Paused: {self.call(rid)} stops answering when this link closes. RESUME from your station."
        if cmd == "RESUME":
            r = dict(self.cfg["radios"].get(rid) or {})
            r["paused"] = None
            self.cfg["radios"][rid] = r
            self._save()
            self._modem(rid).einstein_sync()
            self._publish(rid)
            return f"Resumed: {self.call(rid)} answers again ({self.state(rid)['state']})."
        return ""

    def _think(self, rid, peer, s, text, send):
        try:
            tools = Tools(self, rid, peer, s)
            r = (getattr(self.st, "radios", {}) or {}).get(rid) or {}
            info = f"{s['asker_class'].title()} class license" if s.get("asker_class") else "license class not known"
            if s["owner"]:
                info += "; this is the station's own operator, from another of their stations"
            system = SYSTEM.format(name=self.name(), kind=("HF" if self._modem(rid).cfg().get("kind") == "hf" else "FM"),
                                   ecall=self.call(rid), of=self.of(rid), op_call=self.op_call(rid), asker=peer,
                                   asker_info=info, area=self.area(), chars=REPLY_CHARS,
                                   now=f"{datetime.now():%A %Y-%m-%d %H:%M} local, at {r.get('freq_mhz') or '?'} MHz")
            hist = s["history"][-12:]
            user = "\n".join([*(f"{'They' if m['role'] == 'asker' else 'You'}: {m['text']}" for m in hist),
                              f"They ({peer}): {text}"])
            out, usage = (self.ask_model or self._ask)(system, user, tools)
            self._step(rid, peer, "writing the answer")
            reply = str(out.get("reply") or "").strip()[:REPLY_CHARS * 2]
            bad = text_problems(reply)
            if bad:
                self._log(rid, {"kind": "blocked", "peer": peer, "text": reply, "why": bad})
                reply = ("I can't send that answer on amateur radio (" + "; ".join(bad) + "). Ask me another way, "
                         f"or {self.op_call(rid)} can follow up.")
                files = []
            else:
                files = one_file_each([tools.files[f] for f in dict.fromkeys(out.get("attach") or []) if f in tools.files])
                if not files and CLAIMS_FILE.search(reply):   # owner 2026-11-24: "said there was a band plan file. It was never sent"
                    if tools.files:
                        files = one_file_each(list(tools.files.values()))
                    else:
                        reply += "\n(No file was made with this answer: ask me for it as a file.)"
            if len(reply) > REPLY_CHARS:
                reply = reply[:REPLY_CHARS - 40].rsplit(" ", 1)[0] + " … (ask for it as a file for the rest)"
            note = str(out.get("note_for_operator") or "").strip()
            if note:
                self._log(rid, {"kind": "note", "peer": peer, "text": note})
            s["history"] += [{"role": "asker", "text": text}, {"role": "einstein", "text": reply}]
            reply = self._wrap(rid, peer, s, reply or "(no answer)")
            s["log"].append({"role": "einstein", "text": reply, "at": self.clock()})
            self._log(rid, {"kind": "out", "peer": peer, "text": reply, "tools": tools.calls,
                            "files": [f["name"] for f in files]})
            self._step(rid, peer, "sending the answer" + (f" and {len(files)} file{'s' if len(files) != 1 else ''}"
                                                          if files else ""))
            send(text=reply)
            self._done(rid, peer, text, "blocked: " + "; ".join(bad) if bad else "answered", ok=not bad,
                       tools=tools.calls, files=[f["name"] for f in files])
            self._send_files(s, files, send)
        except Exception as e:  # noqa: BLE001
            self._log(rid, {"kind": "error", "peer": peer, "error": f"{type(e).__name__}: {str(e)[:200]}"})
            self._done(rid, peer, text, "could not answer: " + ("no internet" if "URLError" in type(e).__name__
                                                                  else f"{type(e).__name__}: {str(e)[:80]}"), ok=False)
            try:
                send(text=self._wrap(rid, peer, s, "Sorry, I could not work that out just now "
                                     f"({'no internet' if 'URLError' in type(e).__name__ else 'an error'}); "
                                     f"{self.op_call(rid)} can follow up."))
            except Exception:  # noqa: BLE001
                pass
        finally:
            self.busy[(rid, peer)] = False
            if (rid, peer) in self.now:                   # never left showing "working"
                self._done(rid, peer, text, "answered")

    def _ask(self, system, user, tools):
        from .agent import call_xai_tools
        key = self._key()
        if not key:
            raise RuntimeError("no xAI key")
        a = getattr(self.st, "agent", None)
        model = ((getattr(a, "cfg", None) or {}).get("einstein_model") or "grok-4.20-0309-non-reasoning")
        return call_xai_tools(key, model, system, user, tools, timeout=MODEL_TIMEOUT_S, schema=SCHEMA,
                              max_tokens=2500, name="einstein", rounds=5)

    # ----- answers kept for a station whose link closed -----
    def hold(self, rid, peer, item: dict):
        with self.lock:
            self.held.setdefault((rid, peer), []).append(dict(item, at=self.clock()))

    def take_held(self, rid, peer) -> list[dict]:
        with self.lock:
            xs = [x for x in self.held.pop((rid, peer), []) if self.clock() - x["at"] < HOLD_S]
        return xs


def one_file_each(files: list[dict]) -> list[dict]:
    """What goes on the air for one reply (owner 2026-11-24: one request for a CHIRP file sent three files of one name):
    every CHIRP file attached becomes ONE file (their channels in order, each channel once, numbered from 1, named as
    the first); a file attached twice goes once; two different files of one name get -2, -3."""
    from . import radiochan as R
    chirps = [f for f in files if f.get("chirp")]
    if len(chirps) > 1:
        items, seen = [], set()
        for f in chirps:
            for it in f["chirp"]["items"]:
                k = (round(float(it["freq_mhz"]), 4), it.get("offset_mhz") or None, it.get("tone_hz") or None)
                if k not in seen:
                    seen.add(k)
                    items.append(it)
        prof = "ht" if all(f["chirp"]["profile"] == "ht" for f in chirps) else "any"
        merged = dict(chirps[0], data=R.chirp_csv(items[:R.MAX], prof, 1).encode(),
                      chirp={"items": items[:R.MAX], "profile": prof}, merged=len(chirps))
        files = [merged if f is chirps[0] else f for f in files if f is chirps[0] or not f.get("chirp")]
    out, names, bodies = [], {}, set()
    for f in files:
        h = hashlib.sha256(f["data"]).hexdigest()
        if h in bodies:
            continue
        bodies.add(h)
        n = names.get(f["name"].lower(), 0) + 1
        names[f["name"].lower()] = n
        if n > 1:
            stem, dot, ext = f["name"].rpartition(".")
            f = dict(f, name=f"{stem}-{n}.{ext}" if dot else f"{f['name']}-{n}")
        out.append(f)
    return out


def owner_token(key: str, nonce: str, call: str) -> str:
    """The owner's answer to a link's challenge: HMAC-SHA256(key, nonce:CALL), first 32 hex digits. Sent in the clear:
    it proves the sender holds the key without saying it, and hides nothing of the message (97.113(a)(4))."""
    return hmac.new(str(key).encode(), f"{nonce.upper()}:{str(call).upper()}".encode(), hashlib.sha256).hexdigest()[:32]
