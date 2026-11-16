"""Local plans (Nets -> Plans): the area's clubs, the state coordinator's band plan and the ARES / RACES
communications plans, found by an xAI web search, confirmed by the operator, and kept on this PC for an outage.

Owner 2026-11-15: "capture any amateur radio band plans for the local area ... find all local amateur radio clubs and
the ARES and RACES EMCOMM communication plans and band plans", then "build both".

* THE SEARCH (one xAI web search, ~$0.20-0.50, up to two minutes): clubs and EMCOMM groups within `km` of the
  station, the state's frequency coordinator and its VHF/UHF band plan, county / section ARES plans, RACES plans and
  published ICS-205s. It returns clubs, documents and frequencies, each with the page it came from.
* NOTHING IS TRUSTED UNTIL CONFIRMED. Found frequencies are proposals; the operator ticks the ones to keep (a
  "plan channel": what it is for, whose plan, the source). A new search says what is new and what a kept channel's
  plan no longer lists. Many ARES / RACES plans are members-only on purpose: only public pages are read, nothing ever
  signs in. A restricted plan the operator has can be added as a file: its frequencies are read the same way.
* OFFLINE COPIES. Each public plan document (PDF, or a web page as text) is saved under data/localplans/ with the date
  it was fetched, at most MAX_DOC_BYTES; the dashboard serves them back as downloads, so the plan is there with the
  internet down.
* USED BY THE STATION. label(freq) names a kept channel and the band plan's use of a frequency (station/bandplan.py):
  the radio cards show it, and Sidekick's context includes it. A channel with a published net schedule can be added
  to the schedule in one step.

Not automatic: a re-check costs money, so the page says when the last search is over a month old; it never searches
by itself. Only a rounded position (about 10 km) is sent, as with Find nets.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.request
from pathlib import Path

from . import bandplan, netfind

DEFAULT_KM = 80
MAX_DOC_BYTES = 20 * 1024 ** 2
STALE_S = 30 * 86400
TIMEOUT_S = 300
MODEL = netfind.MODEL
DOC_KINDS = {"band_plan": "Band plan", "ares_plan": "ARES plan", "races_plan": "RACES plan", "ics205": "ICS-205",
             "comm_plan": "Communications plan", "repeater_list": "Repeater list", "other": "Other"}
FREQ_KINDS = {"repeater": "Repeater", "simplex": "Simplex", "hf_net": "HF net", "winlink": "Winlink gateway",
              "aprs": "APRS", "packet": "Packet", "link": "Link", "other": "Other"}
OFFLINE_KINDS = ("band_plan", "ares_plan", "races_plan", "ics205", "comm_plan")

_SHAPE = (
    "Answer ONLY with a JSON object, no prose:\n"
    "{\"clubs\": [{\"name\": str, \"url\": str, \"area\": str, \"meets\": str or null, \"emcomm\": bool (an ARES, RACES,"
    " emergency-management or Skywarn group), \"repeaters\": [str] (as published, e.g. '146.940 -0.6 PL 103.5')}],\n"
    " \"documents\": [{\"title\": str, \"url\": str (the document itself: a PDF or page), \"kind\": one of "
    + " ".join(DOC_KINDS) + ", \"org\": str, \"date\": str or null (as dated on it), \"public\": bool (readable without"
    " signing in)}],\n"
    " \"frequencies\": [{\"freq_mhz\": number (the listening / output frequency), \"mode\": one of FM USB LSB AM CW DIG,"
    " \"offset_mhz\": number or null, \"tone_hz\": number or null, \"kind\": one of " + " ".join(FREQ_KINDS)
    + ", \"use\": str (what the plan uses it for, e.g. 'County ARES primary', 'Tactical simplex 2', 'Section HF net'),"
    " \"priority\": \"primary\" | \"alternate\" | \"backup\" | null, \"org\": str, \"source_url\": str (the page or"
    " document that lists it), \"net\": null or {\"name\": str, \"weekdays\": [\"Mon\"..\"Sun\"], \"start\": \"HH:MM\","
    " \"time_zone\": \"local\" | \"UTC\", \"utc_offset_hours\": number, \"repeat\": \"weekly\" | \"monthly\","
    " \"nth\": [1-5 or -1]} (when the plan or page gives a regular net there)}]}")


def _prompt(loc: dict, km: int) -> str:
    return ("You gather the local amateur radio emergency-communications picture for a station near "
            + netfind._where_words(loc) + ". Only report what you found on a page, with that page's URL; never guess "
            "a frequency, offset or tone. Prefer documents dated in the last three years and say the date.\n"
            f"1. Clubs and groups within about {km} km: amateur radio clubs, county / district ARES groups, RACES or "
            "county emergency-management radio groups, Skywarn spotter groups, CERT and hospital radio groups, "
            "repeater associations. The ARRL's affiliated-club search, ARRL section pages and county emergency "
            "management pages are good starting points.\n"
            "2. The state's VHF/UHF frequency coordinator (the body listed by the National Frequency Coordinators' "
            "Council for that state) and its published band plan.\n"
            "3. Communications plans: county and section ARES emergency communications plans, county RACES plans, "
            "published ICS-205 radio plans, and the frequencies they assign (primary and alternate repeaters, "
            "simplex and tactical channels, linked systems, Winlink gateways, HF emergency nets). Only public "
            "documents: never a members-only or signed-in page.\n" + _SHAPE)


def _extract_prompt(name: str, text: str) -> tuple[str, str]:
    sys = ("You read an amateur radio band plan or communications plan. List (1) its band plan SEGMENTS: each range "
           "of frequencies and what the plan sets it aside for (e.g. '146.61-147.39 FM repeater outputs', "
           "'144.90-145.10 packet', '147.42-147.57 FM simplex'), a single-frequency entry as from = to; and (2) every "
           "FREQUENCY (channel) it assigns to a use, repeater, net or group. Only what the document says; never add or "
           "guess. Answer ONLY with a JSON object, no prose:\n"
           "{\"segments\": [{\"from_mhz\": number, \"to_mhz\": number, \"use\": str}],\n"
           + ' "frequencies"' + _SHAPE.split('\n "frequencies"', 1)[1].replace("source_url\": str (the page or document that lists it)",
                                               "source_url\": \"\""))
    return sys, f"The document ({name}):\n\n{text[:60000]}"


def _clean_segments(raw) -> list[dict]:
    out = []
    for g in raw or []:
        if not isinstance(g, dict):
            continue
        a, b = netfind._num(g.get("from_mhz")), netfind._num(g.get("to_mhz"))
        b = b if b is not None else a
        use = " ".join(str(g.get("use") or "").split())[:120]
        if a is None or not use:
            continue
        a, b = min(a, b), max(a, b)
        if not bandplan.band(a) or not bandplan.band(b) or b - a > 60:
            continue
        out.append({"from_mhz": round(a, 4), "to_mhz": round(b, 4), "use": use})
    return out[:600]


def _post(key: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request("https://api.x.ai/v1/responses", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    from . import aicost
    return aicost.xai_json(req, timeout, "local_plans", body.get("model") or "")


def _fetch(url: str, cap: int = MAX_DOC_BYTES) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "HAM-Sidekick-Station (local plans copy)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(cap + 1)
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if len(data) > cap:
        raise ValueError(f"larger than {cap // 1024 ** 2} MB")
    return data, ctype


def _url_ok(u) -> bool:
    return isinstance(u, str) and u.lower().startswith(("http://", "https://")) and len(u) < 500


def _fid(f: dict) -> str:
    return "p" + hashlib.sha1(json.dumps([round(f["freq_mhz"], 4), f.get("offset_mhz"), f.get("tone_hz"),
                                          (f.get("use") or "").casefold()]).encode()).hexdigest()[:8]


def _clean_freq(raw, seen: set[str], require_source: bool = True) -> tuple[dict | None, str]:
    if not isinstance(raw, dict):
        return None, "not a frequency"
    f = netfind._num(raw.get("freq_mhz"))
    use = " ".join(str(raw.get("use") or "").split())[:100]
    src = str(raw.get("source_url") or "").strip()
    if not f or not (1.8 <= f <= 1300):
        return None, f"{use or '?'}: no amateur frequency"
    if require_source and not _url_ok(src):
        return None, f"{use or f}: no source page"
    mode = str(raw.get("mode") or "").upper()
    mode = mode if mode in netfind.MODES else ("FM" if f > 30 else "LSB" if f < 10 else "USB")
    off, tone = netfind._num(raw.get("offset_mhz")), netfind._num(raw.get("tone_hz"))
    out = {"freq_mhz": round(f, 4), "mode": mode, "offset_mhz": off if off is not None and -10 <= off <= 10 else None,
           "tone_hz": tone if tone is not None and 60 <= tone <= 260 else None,
           "kind": raw.get("kind") if raw.get("kind") in FREQ_KINDS else "other", "use": use or "(no use given)",
           "priority": raw.get("priority") if raw.get("priority") in ("primary", "alternate", "backup") else None,
           "org": " ".join(str(raw.get("org") or "").split())[:80] or None, "source_url": src[:500] or None,
           "source_opened": netfind._norm_url(src) in seen if src else False,
           "net": raw.get("net") if isinstance(raw.get("net"), dict) else None}
    seg = bandplan.segment(f)
    out["band"] = seg["band"] if seg else None
    out["plan_says"] = seg["what"] if seg else None
    out["id"] = _fid(out)
    return out, ""


def _path(st) -> Path:
    return Path(st.data) / "localplans.json"


def _load(st) -> dict:
    try:
        return json.loads(_path(st).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(st, d: dict):
    p = _path(st)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    tmp.replace(p)


class Plans:
    def __init__(self, st, post=None, fetch=None, extract=None):
        self.st = st
        self.post = post or _post
        self.fetch = fetch or _fetch
        self.extract = extract                       # (key, system, user) -> dict; None = agent.call_xai
        self.lock = threading.Lock()
        self.busy = False
        self.saving = False
        self.copy_lock = threading.Lock()

    def docdir(self) -> Path:
        return Path(self.st.data) / "localplans"

    def key(self):
        return netfind.Finder.key(self)

    def _class(self) -> str | None:
        a = getattr(self.st, "agent", None)
        return (getattr(a, "cfg", None) or {}).get("license_class") or None

    # ----- the view -----
    def state(self) -> dict:
        d = _load(self.st)
        last = d.get("last") or {}
        kept = d.get("kept") or []
        kept_ids = {k["id"] for k in kept}
        found = [dict(f, kept=f["id"] in kept_ids) for f in last.get("frequencies") or []]
        docs = d.get("docs") or {}
        for x in last.get("documents") or []:
            x["saved"] = docs.get(x["url"])
        return {"key": bool(self.key()), "location": netfind.location(self.st), "km": d.get("km", DEFAULT_KM),
                "busy": self.busy, "saving": self.saving, "at": last.get("at"),
                "stale": bool(last.get("at")) and time.time() - last["at"] > STALE_S,
                "clubs": last.get("clubs") or [], "documents": last.get("documents") or [], "frequencies": found,
                "left_out": last.get("left_out") or [], "error": last.get("error"), "cost_usd": last.get("cost_usd"),
                "changes": last.get("changes") or {}, "kept": kept, "files": d.get("files") or [],
                "license_class": self._class(), "doc_kinds": DOC_KINDS, "freq_kinds": FREQ_KINDS}

    def settings(self, body: dict) -> dict:
        with self.lock:
            d = _load(self.st)
            if "km" in body:
                km = netfind._num(body.get("km"))
                if not km or not 5 <= km <= 400:
                    raise ValueError("distance must be 5 to 400 km")
                d["km"] = int(km)
            _save(self.st, d)
        return self.state()

    # ----- the search -----
    def search(self, body: dict | None = None) -> dict:
        if body and "km" in body:
            self.settings({"km": body["km"]})
        key = self.key()
        if not key:
            raise ValueError("set the xAI key first (Settings -> Station agent)")
        loc = netfind.location(self.st)
        if not loc:
            raise ValueError("say where the station is: a grid square in Settings, this PC's location, or an address "
                             "(Nets -> Find nets)")
        with self.lock:
            if self.busy:
                raise ValueError("a search is already running")
            self.busy = True
        try:
            d = _load(self.st)
            km = int(d.get("km", DEFAULT_KM))
            req = {"model": MODEL, "max_tool_calls": 40, "tools": [{"type": "web_search"}],
                   "input": [{"role": "user", "content": _prompt(loc, km)}]}
            try:
                resp = self.post(key, req, TIMEOUT_S)
            except Exception as e:  # noqa: BLE001
                raise ValueError(f"the search failed ({getattr(e, 'code', None) or type(e).__name__}): try again") from e
            text, seen = netfind._text_and_sources(resp)
            try:
                obj = self._json(text)
            except ValueError:
                obj = {}
            clubs = [c for c in (self._club(x) for x in obj.get("clubs") or []) if c]
            docs = [x for x in (self._doc(x, seen) for x in obj.get("documents") or []) if x]
            freqs, out, ids = [], [], set()
            for raw in obj.get("frequencies") or []:
                f, why = _clean_freq(raw, seen)
                if f and f["id"] not in ids:
                    ids.add(f["id"])
                    freqs.append(f)
                elif why:
                    out.append(why)
            kept = d.get("kept") or []
            prev = {f["id"] for f in (d.get("last") or {}).get("frequencies") or []}
            changes = {"new": [f["id"] for f in freqs if prev and f["id"] not in prev],
                       "gone": [k["id"] for k in kept if k.get("source_url") and k["id"] not in ids
                                and any(netfind._norm_url(k["source_url"]) == netfind._norm_url(x["url"]) for x in docs)]}
            ticks = (resp.get("usage") or {}).get("cost_in_usd_ticks")
            last = {"at": time.time(), "clubs": clubs, "documents": docs, "frequencies": freqs, "left_out": out[:60],
                    "changes": changes, "cost_usd": round(ticks / 1e10, 3) if isinstance(ticks, (int, float)) else None,
                    "error": None if (clubs or docs or freqs) else "the search found nothing with a source page"}
            with self.lock:
                d = _load(self.st)
                d["last"] = last
                _save(self.st, d)
            print(f"localplans: {len(clubs)} clubs, {len(docs)} documents, {len(freqs)} frequencies", flush=True)
        finally:
            self.busy = False
        self.save_copies(background=True)
        return self.state()

    @staticmethod
    def _json(text: str) -> dict:
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        raw = m.group(1) if m else text
        i = raw.find("{")
        if i < 0:
            raise ValueError("no JSON")
        obj, _ = json.JSONDecoder().raw_decode(raw[i:])
        return obj if isinstance(obj, dict) else {}

    @staticmethod
    def _club(x) -> dict | None:
        if not isinstance(x, dict) or not str(x.get("name") or "").strip():
            return None
        return {"name": " ".join(str(x["name"]).split())[:100], "url": x.get("url") if _url_ok(x.get("url")) else None,
                "area": str(x.get("area") or "")[:80], "meets": (str(x.get("meets") or "")[:120] or None),
                "emcomm": bool(x.get("emcomm")),
                "repeaters": [str(r)[:60] for r in (x.get("repeaters") or []) if isinstance(r, (str, int, float))][:8]}

    @staticmethod
    def _doc(x, seen) -> dict | None:
        if not isinstance(x, dict) or not _url_ok(x.get("url")):
            return None
        return {"title": " ".join(str(x.get("title") or x["url"]).split())[:140], "url": x["url"],
                "kind": x.get("kind") if x.get("kind") in DOC_KINDS else "other",
                "org": str(x.get("org") or "")[:80] or None, "date": str(x.get("date") or "")[:40] or None,
                "public": x.get("public") is not False, "opened": netfind._norm_url(x["url"]) in seen}

    # ----- offline copies -----
    def save_copies(self, background: bool = False, urls: list[str] | None = None):
        """Fetch each public plan document (PDF as is, a page as text) into data/localplans/. Already saved: kept."""
        self.saving = True
        if background:
            threading.Thread(target=self._save_copies, args=(urls,), daemon=True, name="localplans-copies").start()
            return
        self._save_copies(urls)

    def _save_copies(self, urls=None):
        from . import knowledge
        with self.copy_lock:                         # one at a time: a second run finds the first one's copies
            self._copies(urls, knowledge)
            if self.key():
                try:
                    self.ingest()                    # read each saved plan into the consolidated band plan
                except Exception as e:  # noqa: BLE001
                    print(f"localplans: ingest failed: {e}", flush=True)

    def _copies(self, urls, knowledge):
        try:
            d = _load(self.st)
            docs = d.get("docs") or {}
            todo = [x for x in (d.get("last") or {}).get("documents") or []
                    if x.get("public") and (x["url"] in (urls or []) or (urls is None and x["kind"] in OFFLINE_KINDS))
                    and not (docs.get(x["url"]) or {}).get("path")]
            for x in todo:
                rec = {"at": time.time(), "title": x["title"], "kind": x["kind"]}
                try:
                    data, ctype = self.fetch(x["url"])
                    sid = hashlib.sha1(x["url"].encode()).hexdigest()[:12]
                    self.docdir().mkdir(parents=True, exist_ok=True)
                    if data[:5] == b"%PDF-" or ctype == "application/pdf":
                        name, kind = f"{sid}.pdf", "application/pdf"
                        (self.docdir() / name).write_bytes(data)
                    else:
                        if "html" not in ctype and "text" not in ctype and ctype:
                            raise ValueError(f"not a page or a PDF ({ctype})")
                        title, body = knowledge.html_to_text(knowledge._decode(data))
                        name, kind = f"{sid}.txt", "text/plain"
                        (self.docdir() / name).write_text(f"{x['title']}\n{x['url']}\nSaved {time.strftime('%Y-%m-%d')}"
                                                          f"\n\n{body}", encoding="utf-8")
                    rec.update(path=name, type=kind, bytes=(self.docdir() / name).stat().st_size, id=sid)
                except Exception as e:  # noqa: BLE001 - one document never stops the rest
                    rec["error"] = f"{type(e).__name__}: {e}"[:160]
                with self.lock:
                    d = _load(self.st)
                    d.setdefault("docs", {})[x["url"]] = rec
                    _save(self.st, d)
        finally:
            self.saving = False

    # ----- ingesting: each saved plan read into segments and channels (consolidate.py) -----
    def _text_of(self, path: Path) -> str:
        from . import knowledge
        if path.suffix == ".txt":
            return path.read_text(encoding="utf-8", errors="replace")
        return knowledge.extract(path.name, path.read_bytes())

    def _read_plan(self, key: str, name: str, path: Path) -> tuple[list[dict], list[dict], list[str]]:
        sys_, user = _extract_prompt(name, self._text_of(path))
        obj = self._call_extract(key, sys_, user)
        freqs, out = [], []
        for raw in obj.get("frequencies") or []:
            f, why = _clean_freq(dict(raw if isinstance(raw, dict) else {}, source_url=""), set(),
                                 require_source=False)
            if f:
                freqs.append(f)
            elif why:
                out.append(why)
        return _clean_segments(obj.get("segments")), freqs, out

    def ingest(self, force: bool = False, keys: list[str] | None = None) -> dict:
        """Read every saved public plan (not yet read, or `force`) with xAI: its band segments and channels go into
        the consolidated band plan; its channels are also offered under Frequencies found (with the document as the
        source). One call per document."""
        key = self.key()
        if not key:
            raise ValueError("set the xAI key first (Settings -> Station agent): it reads the plans")
        d = _load(self.st)
        docs = d.get("docs") or {}
        meta = {x["url"]: x for x in (d.get("last") or {}).get("documents") or []}
        done = d.get("ingested") or {}
        todo = [(u, rec) for u, rec in docs.items() if rec.get("path") and (force or u not in done
                                                                            or done[u].get("error"))
                and (keys is None or u in keys)]
        for url, rec in todo[:20]:
            m = meta.get(url) or {}
            ent = {"at": time.time(), "title": rec.get("title") or m.get("title") or url, "kind": rec.get("kind"),
                   "org": m.get("org"), "date": m.get("date"), "url": url,
                   "authority": (done.get(url) or {}).get("authority")
                   or ("coordinator" if rec.get("kind") == "band_plan" else "local"),
                   "excluded": (done.get(url) or {}).get("excluded", False)}
            try:
                segs, freqs, _ = self._read_plan(key, ent["title"], self.docdir() / rec["path"])
                for f in freqs:
                    f["source_url"], f["source_opened"], f["source_doc"] = url, True, ent["title"]
                    f["org"] = f.get("org") or ent["org"]
                ent.update(segments=segs, frequencies=freqs)
            except Exception as e:  # noqa: BLE001 - one document never stops the rest
                ent["error"] = f"{type(e).__name__}: {e}"[:160]
            with self.lock:
                d = _load(self.st)
                d.setdefault("ingested", {})[url] = ent
                last = d.setdefault("last", {"at": None, "clubs": [], "documents": [], "frequencies": []})
                have = {f["id"] for f in last.get("frequencies") or []}
                last["frequencies"] = (last.get("frequencies") or []) + [f for f in ent.get("frequencies") or []
                                                                          if f["id"] not in have]
                _save(self.st, d)
            print(f"localplans: read {ent['title'][:60]}: {len(ent.get('segments') or [])} segments, "
                  f"{len(ent.get('frequencies') or [])} channels{' (' + ent['error'] + ')' if ent.get('error') else ''}",
                  flush=True)
        return self.state()

    def set_source(self, key: str, excluded=None, authority=None) -> dict:
        """The operator's say on one ingested plan: leave it out of the band plan, or name it the coordinator's."""
        with self.lock:
            d = _load(self.st)
            ent = (d.get("ingested") or {}).get(key)
            if not ent:
                raise ValueError("no such plan")
            if excluded is not None:
                ent["excluded"] = bool(excluded)
            if authority is not None:
                if authority not in ("coordinator", "local"):
                    raise ValueError("a plan is the state coordinator's or a local plan")
                ent["authority"] = authority
            _save(self.st, d)
        return self.state()

    def consolidated(self) -> dict:
        """The consolidated, reconciled band plan for this area (consolidate.py)."""
        from . import consolidate
        d = _load(self.st)
        sources = [{"id": k, "name": e.get("title") + (f" ({e['org']})" if e.get("org") else ""),
                    "authority": e.get("authority") or "local", "url": e.get("url"),
                    "segments": e.get("segments") or [], "frequencies": e.get("frequencies") or []}
                   for k, e in (d.get("ingested") or {}).items() if not e.get("excluded") and not e.get("error")]
        t = consolidate.build(self._class(), sources, d.get("kept") or [])
        t["read"] = [{"key": k, "title": e.get("title"), "org": e.get("org"), "kind": e.get("kind"),
                      "authority": e.get("authority"), "excluded": bool(e.get("excluded")), "error": e.get("error"),
                      "segments": len(e.get("segments") or []), "channels": len(e.get("frequencies") or []),
                      "at": e.get("at"), "url": e.get("url")} for k, e in (d.get("ingested") or {}).items()]
        t["unread"] = len([u for u, r in (d.get("docs") or {}).items() if r.get("path")
                           and u not in (d.get("ingested") or {})])
        t["location"] = (netfind.location(self.st) or {}).get("label")
        t["searched_at"] = (d.get("last") or {}).get("at")
        t["key"] = bool(self.key())
        return t

    def doc_file(self, sid: str) -> tuple[Path, str, str] | None:
        """(path, content type, download name) of a saved copy or file, by its id."""
        if not re.fullmatch(r"[0-9a-f]{12}", sid or ""):
            return None
        d = _load(self.st)
        for rec in list((d.get("docs") or {}).values()) + list(d.get("files") or []):
            if rec.get("id") == sid and rec.get("path"):
                p = self.docdir() / rec["path"]
                if p.is_file():
                    nice = re.sub(r"[^\w .-]+", "", rec.get("title") or sid)[:80].strip() or sid
                    return p, rec.get("type") or "application/octet-stream", nice + Path(rec["path"]).suffix
        return None

    # ----- the operator's own plan file -----
    def add_file(self, name: str, data: bytes) -> dict:
        """A plan the operator has (a members-only ARES plan, an ICS-205): kept offline, its frequencies proposed."""
        from . import knowledge
        name = Path(str(name or "plan")).name[:120]
        if len(data) > MAX_DOC_BYTES:
            raise ValueError(f"the file is larger than {MAX_DOC_BYTES // 1024 ** 2} MB")
        if Path(name).suffix.lower() not in (".pdf", ".txt", ".docx", ".html", ".htm", ".csv"):
            raise ValueError("add a PDF, Word (.docx), text, CSV or web page file")
        text = knowledge.extract(name, data)
        key = self.key()
        if not key:
            raise ValueError("set the xAI key first (Settings -> Station agent): it reads the frequencies")
        sid = hashlib.sha1(data).hexdigest()[:12]
        self.docdir().mkdir(parents=True, exist_ok=True)
        stored = f"{sid}{Path(name).suffix.lower()}"
        (self.docdir() / stored).write_bytes(data)
        sys_, user = _extract_prompt(name, text)
        obj = self._call_extract(key, sys_, user)
        segs = _clean_segments(obj.get("segments"))
        freqs, out = [], []
        for raw in obj.get("frequencies") or []:
            f, why = _clean_freq(dict(raw if isinstance(raw, dict) else {}, source_url=""), set(),
                                 require_source=False)
            if f:
                f["source_file"] = name
                f["file_id"] = sid
                freqs.append(f)
            elif why:
                out.append(why)
        ctype = {".pdf": "application/pdf", ".txt": "text/plain", ".csv": "text/plain"}.get(Path(name).suffix.lower(),
                                                                                         "application/octet-stream")
        with self.lock:
            d = _load(self.st)
            files = [x for x in d.get("files") or [] if x.get("id") != sid]
            files.append({"id": sid, "title": Path(name).stem, "name": name, "path": stored, "type": ctype,
                          "at": time.time(), "found": len(freqs)})
            d["files"] = files
            prev = (d.get("ingested") or {}).get(f"file:{sid}") or {}
            d.setdefault("ingested", {})[f"file:{sid}"] = {
                "at": time.time(), "title": Path(name).stem, "kind": "your file", "org": None, "url": None,
                "authority": prev.get("authority") or "local", "excluded": prev.get("excluded", False),
                "segments": segs, "frequencies": freqs}
            last = d.setdefault("last", {"at": None, "clubs": [], "documents": [], "frequencies": []})
            have = {f["id"] for f in last.get("frequencies") or []}
            last["frequencies"] = (last.get("frequencies") or []) + [f for f in freqs if f["id"] not in have]
            last["left_out"] = (last.get("left_out") or []) + out
            _save(self.st, d)
        return self.state() | {"added_file": name, "found": len(freqs)}

    def _call_extract(self, key, system, user) -> dict:
        if self.extract:
            return self.extract(key, system, user)
        from . import agent
        schema = {"type": "object", "properties": {"frequencies": {"type": "array", "items": {"type": "object"}}},
                  "required": ["frequencies"], "additionalProperties": True}
        try:
            out, _ = agent.call_xai(key, MODEL, system, user, timeout=180, schema=schema, max_tokens=8000,
                                    name="local_plans")
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"reading the file failed ({getattr(e, 'code', None) or type(e).__name__})") from e
        return out if isinstance(out, dict) else {}

    # ----- confirming -----
    def keep(self, ids) -> dict:
        want = {str(i) for i in ids or []}
        if not want:
            raise ValueError("tick the frequencies to keep")
        with self.lock:
            d = _load(self.st)
            found = {f["id"]: f for f in (d.get("last") or {}).get("frequencies") or []}
            kept = {k["id"]: k for k in d.get("kept") or []}
            for i in want:
                if i in found:
                    kept[i] = dict(found[i], kept_at=time.time())
            d["kept"] = sorted(kept.values(), key=lambda k: (k["freq_mhz"] > 30, k["freq_mhz"]))
            _save(self.st, d)
        return self.state()

    def drop(self, ids) -> dict:
        want = {str(i) for i in ids or []}
        with self.lock:
            d = _load(self.st)
            d["kept"] = [k for k in d.get("kept") or [] if k["id"] not in want]
            _save(self.st, d)
        return self.state()

    def add_net(self, fid: str, radio: str | None = None) -> dict:
        """A kept channel whose plan gives a regular net: onto the schedule (as Find nets adds one)."""
        d = _load(self.st)
        k = next((x for x in d.get("kept") or [] if x["id"] == fid), None)
        if not k or not k.get("net"):
            raise ValueError("that channel has no net schedule in its plan")
        n = k["net"]
        raw = {"name": n.get("name") or k["use"], "freq_mhz": k["freq_mhz"], "mode": k["mode"],
               "offset_mhz": k.get("offset_mhz"), "tone_hz": k.get("tone_hz"), "repeat": n.get("repeat") or "weekly",
               "weekdays": n.get("weekdays") or [], "nth": n.get("nth") or [], "start": n.get("start"),
               "time_zone": n.get("time_zone") or "local", "utc_offset_hours": n.get("utc_offset_hours"),
               "emergency": k["kind"] != "other", "source_url": k.get("source_url") or "https://example.invalid/"}
        from . import fit
        net, why = netfind._clean(raw, set(), {"HF": True, "VU": True}, 10 ** 6, 10 ** 6, list(fit.ALL_MODES))
        if not net:
            raise ValueError(why or "the plan's net could not be read")
        body = {x: net[x] for x in ("name", "freq_mhz", "mode", "start", "duration_min", "repeat", "offset_mhz",
                                    "tone_hz", "emergency") if net.get(x) is not None}
        body["radio"] = radio or None
        if k.get("source_url"):
            body["source"] = k["source_url"]
        self.st.nets.add(body)
        return self.state() | {"added": body["name"], "schedule": self.st.nets.list().get("schedule")}

    # ----- used by the station -----
    def label(self, freq_mhz, mode: str | None = None) -> dict | None:
        """A frequency as the plans see it: {"channel": the kept plan channel or None, "plan": the band plan's use,
        "band"}. A repeater channel matches its output, or its input (output + offset)."""
        if not freq_mhz:
            return None
        f = float(freq_mhz)
        ch = None
        for k in _load(self.st).get("kept") or []:
            if abs(k["freq_mhz"] - f) <= 0.0025 or (k.get("offset_mhz") and abs(k["freq_mhz"] + k["offset_mhz"] - f) <= 0.0025):
                ch = {"use": k["use"], "org": k.get("org"), "priority": k.get("priority"), "kind": k["kind"]}
                break
        seg = bandplan.segment(f)
        plan, by = (seg["what"] if seg else None), "ARRL band plan"
        try:
            from . import consolidate
            hit = consolidate.lookup(self.consolidated(), f)
            rng, chn = (hit or {}).get("range"), (hit or {}).get("channel")
            row = chn if chn and not chn.get("kept") else rng if rng and rng.get("authority") != "fcc" else None
            if row and row.get("use"):
                plan, by = row["use"], row.get("by")
        except Exception:  # noqa: BLE001
            pass
        return {"channel": ch, "plan": plan, "by": by, "band": seg["band"] if seg else None,
                "warn": bool(seg and seg["warn"])}
