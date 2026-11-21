"""ICS forms as files a receiving station opens in any browser, and as Winlink Express form data.

Einstein (station/einstein.py) answers a request for a report ("weather for the shelter", "a radio plan for Saturday's
drill") with a form, sent over VARA as a file. Two shapes of one form:

* HTML (`<form>-<subject>.html`): one self-contained page, no script, no outside link, styles inline, laid out like the
  printed ICS form and printable on US Letter. It opens in any browser; the receiving HAM Sidekick Station shows it
  in a sandboxed viewer (scripts can never run: station/server.py /api/vara/view).
* Winlink form data (`RMS_Express_Form_<viewer>.xml`): the XML Winlink Express attaches to a form message. Written
  only when Winlink Express's own templates are on this PC (its viewer name and field names come from them,
  station/winlink.py), so Express shows it with its own viewer. The receiving station renders the same XML as the HTML
  page (read_winlink_xml + html_for).

Every value is escaped; nothing a model wrote becomes markup. Forms carry no personal details beyond what the
operator or the asker put in them.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime

FORMS = {"ics213": "ICS 213 General Message", "ics205": "ICS 205 Incident Radio Communications Plan",
         "ics309": "ICS 309 Communications Log"}
VIEWERS = {"ics213": "ICS213", "ics205": "ICS205", "ics309": "309"}     # how a Winlink viewer name says which form

_CSS = """body{font:14px/1.35 Arial,Helvetica,sans-serif;color:#111;background:#f4f4f4;margin:0;padding:16px}
.f{max-width:8in;margin:0 auto;background:#fff;border:2px solid #111;padding:0}
h1{font-size:18px;margin:0;padding:8px 10px;border-bottom:2px solid #111;display:flex;justify-content:space-between}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #111;padding:4px 6px;vertical-align:top;text-align:left}
th{background:#e8e8e8;font-size:12px}.l{font-size:11px;font-weight:bold;display:block;text-transform:uppercase}
.msg{white-space:pre-wrap;min-height:2.5in}.note{font-size:11px;color:#444;padding:6px 10px}
.ex{background:#111;color:#fff;text-align:center;font-weight:bold;padding:3px}
@media print{body{background:#fff;padding:0}.f{border-width:1px}}
@page{size:letter;margin:.5in}"""


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _page(title: str, body: str, note: str = "") -> str:
    return ("<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
            f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{_e(title)}</title>"
            f"<style>{_CSS}</style></head><body><div class=\"f\">{body}"
            + (f"<div class=\"note\">{_e(note)}</div>" if note else "") + "</div></body></html>\n")


def _cell(label: str, value, span: int = 1, cls: str = "") -> str:
    return (f"<td{f' colspan={span}' if span > 1 else ''}><span class=\"l\">{_e(label)}</span>"
            f"<div{f' class={cls}' if cls else ''}>{_e(value)}</div></td>")


def ics213(v: dict, note: str = "") -> str:
    """ICS-213 General Message. v uses Winlink's field names (station/ics.py): inc_name, To_Name, fm_name,
    Subjectline, Mdate, mtime, Message, Approved_Name, Approved_PosTitle, IsExercise; Reply/Replyby optional."""
    g = lambda k: v.get(k) or v.get(k.lower()) or ""     # noqa: E731
    ex = g("IsExercise")
    body = (f"<h1><span>GENERAL MESSAGE (ICS 213)</span></h1>" + (f"<div class=\"ex\">{_e(ex)}</div>" if ex else "")
            + "<table><tr>" + _cell("1. Incident name (optional)", g("inc_name"), 2) + "</tr><tr>"
            + _cell("2. To (name and position)", g("To_Name"), 2) + "</tr><tr>"
            + _cell("3. From (name and position)", g("fm_name"), 2) + "</tr><tr>"
            + _cell("4. Subject", g("Subjectline")) + _cell("5. Date", g("Mdate")) + "</tr><tr>"
            + _cell("6. Time", g("mtime"), 2) + "</tr><tr>"
            + _cell("7. Message", g("Message"), 2, "msg") + "</tr><tr>"
            + _cell("8. Approved by (name, position/title)", " · ".join(x for x in (g("Approved_Name"), g("Approved_PosTitle")) if x), 2)
            + "</tr>" + ((("<tr>" + _cell("9. Reply", g("Reply"), 2, "msg") + "</tr><tr>"
                         + _cell("10. Replied by", g("Replyby"), 2) + "</tr>")) if g("Reply") else "")
            + "</table>")
    return _page(f"ICS 213: {g('Subjectline')}", body, note)


def ics205(v: dict, channels: list[dict], note: str = "") -> str:
    """ICS-205 Incident Radio Communications Plan. v: incident, prepared (date/time), period, prepared_by,
    instructions. channels: [{zone, ch, function, name, assignment, rx, rx_tone, tx, tx_tone, mode, remarks}]."""
    cols = [("zone", "Zone grp."), ("ch", "Ch #"), ("function", "Function"), ("name", "Channel name/ trunked radio "
            "system talkgroup"), ("assignment", "Assignment"), ("rx", "RX freq N or W"), ("rx_tone", "RX tone/NAC"),
            ("tx", "TX freq N or W"), ("tx_tone", "TX tone/NAC"), ("mode", "Mode (A, D or M)"), ("remarks", "Remarks")]
    rows = "".join("<tr>" + "".join(f"<td>{_e(c.get(k, ''))}</td>" for k, _ in cols) + "</tr>" for c in channels)
    body = ("<h1><span>INCIDENT RADIO COMMUNICATIONS PLAN (ICS 205)</span></h1><table><tr>"
            + _cell("1. Incident name", v.get("incident", "")) + _cell("2. Date/time prepared", v.get("prepared", ""))
            + _cell("3. Operational period", v.get("period", "")) + "</tr></table><table><tr><th colspan="
            f"{len(cols)}>4. Basic radio channel use</th></tr><tr>"
            + "".join(f"<th>{_e(t)}</th>" for _, t in cols) + "</tr>" + rows + "</table><table><tr>"
            + _cell("5. Special instructions", v.get("instructions", ""), 1, "msg") + "</tr><tr>"
            + _cell("6. Prepared by (communications unit leader)", v.get("prepared_by", "")) + "</tr></table>")
    return _page(f"ICS 205: {v.get('incident', '')}", body, note)


def ics309(v: dict, rows: list[dict], note: str = "") -> str:
    """ICS-309 Communications Log. v: incident, period, operator (name, call), station_id. rows: [{time, from, to,
    sub}] (Winlink's field names, station/ics.py)."""
    body = ("<h1><span>COMMUNICATIONS LOG (ICS 309)</span></h1><table><tr>"
            + _cell("1. Incident name", v.get("incident", "")) + _cell("2. Operational period", v.get("period", ""))
            + "</tr><tr>" + _cell("3. Radio operator (name, call sign)", v.get("operator", ""))
            + _cell("4. Station ID", v.get("station_id", "")) + "</tr></table><table><tr><th>Time</th><th>From</th>"
            "<th>To</th><th>Subject</th></tr>"
            + "".join(f"<tr><td>{_e(r.get('time'))}</td><td>{_e(r.get('from'))}</td><td>{_e(r.get('to'))}</td>"
                      f"<td>{_e(r.get('sub'))}</td></tr>" for r in rows) + "</table>")
    return _page(f"ICS 309: {v.get('incident', '')}", body, note)


# ---------------------------------------------------------------- Winlink form data ---------------------------------
def winlink_xml(form: str, values: dict, sender: str, install: str | None = None, grid: str = "",
                now: datetime | None = None) -> tuple[str, bytes] | None:
    """(file name, bytes) of Winlink Express's form data for `form` (ics213 / ics309), with the viewer and field names
    from Express's own template on this PC; None without Winlink Express (then only the HTML page goes)."""
    from . import winlink
    try:
        install = install or next(iter(winlink.find_installs()), None)
        if not install or form not in winlink.TEMPLATES:
            return None
        t = winlink.load_template(install, form)
    except (OSError, KeyError, StopIteration):
        return None
    now = now or datetime.utcnow()
    vs = {"msgsender": sender, "msgsubject": values.get("Subjectline", ""), "msgbody": "", "msgp2p": "True"}
    vs |= {k.lower(): str(v) for k, v in values.items()}
    x = ET.Element("RMS_Express_Form")
    p = ET.SubElement(x, "form_parameters")
    for k, v in (("xml_file_version", "1.0"), ("rms_express_version", winlink.EXPRESS_VERSION),
                 ("submission_datetime", now.strftime("%Y%m%d%H%M%S")), ("senders_callsign", sender),
                 ("grid_square", grid.upper()), ("display_form", t["viewer"]),
                 ("reply_template", t.get("replytemplate", ""))):
        ET.SubElement(p, k).text = v
    var = ET.SubElement(x, "variables")
    for k, v in vs.items():
        if re.fullmatch(r"[a-z_][a-z0-9_]*", k):
            ET.SubElement(var, k).text = v
    data = b'<?xml version="1.0"?>\r\n' + ET.tostring(x, encoding="utf-8")
    return f"RMS_Express_Form_{t['viewer'].rsplit('.', 1)[0]}.xml", data


def read_winlink_xml(data: bytes) -> dict | None:
    """{form, sender, variables} from Winlink form data, or None if it is not that. Never resolves entities or
    fetches anything (ElementTree does neither)."""
    if len(data) > 512 * 1024 or b"<!ENTITY" in data or b"<!DOCTYPE" in data:
        return None
    try:
        x = ET.fromstring(data)
    except ET.ParseError:
        return None
    if x.tag != "RMS_Express_Form":
        return None
    p = {e.tag: (e.text or "") for e in (x.find("form_parameters") or [])}
    var = {e.tag: (e.text or "") for e in (x.find("variables") or [])}
    viewer = p.get("display_form", "")
    form = next((f for f, k in VIEWERS.items() if k.lower() in viewer.lower()), None)
    return {"form": form, "viewer": viewer, "sender": p.get("senders_callsign", ""), "variables": var}


def html_for(info: dict) -> str:
    """A received Winlink form shown as its page; a form this program does not draw is shown as its fields."""
    v = info.get("variables") or {}
    ci = {k.lower(): val for k, val in v.items()}
    if info.get("form") == "ics213":
        keys = ("inc_name", "To_Name", "fm_name", "Subjectline", "Mdate", "mtime", "Message", "Approved_Name",
                "Approved_PosTitle", "IsExercise", "Reply", "Replyby")
        return ics213({k: ci.get(k.lower(), "") for k in keys}, f"Winlink form data from {info.get('sender', '')}")
    if info.get("form") == "ics309":
        rows = [{"time": ci.get(f"time{i}", ""), "from": ci.get(f"from{i}", ""), "to": ci.get(f"to{i}", ""),
                 "sub": ci.get(f"sub{i}", "")} for i in range(1, 31) if ci.get(f"time{i}") or ci.get(f"sub{i}")]
        return ics309({"incident": ci.get("title", ""), "period": ci.get("activitydatetime1", ""),
                       "operator": ci.get("opname", ""), "station_id": ci.get("operid", "")}, rows,
                      f"Winlink form data from {info.get('sender', '')}")
    body = (f"<h1><span>{_e(info.get('viewer') or 'Winlink form')}</span></h1><table>"
            + "".join(f"<tr><th>{_e(k)}</th><td class=\"msg\" style=\"min-height:0\">{_e(val)}</td></tr>"
                      for k, val in v.items() if val) + "</table>")
    return _page(info.get("viewer") or "Winlink form", body, f"Winlink form data from {info.get('sender', '')}")


def csv_table(text: str, title: str) -> str:
    """A CSV (a CHIRP file) as a readable table page."""
    import csv
    import io
    rows = list(csv.reader(io.StringIO(text)))[:1000]
    if not rows:
        return _page(title, f"<h1><span>{_e(title)}</span></h1><p class=note>empty</p>")
    head, rest = rows[0], rows[1:]
    body = (f"<h1><span>{_e(title)}</span><span style=\"font-weight:normal;font-size:12px\">{len(rest)} rows</span></h1>"
            "<div style=\"overflow-x:auto\"><table><tr>" + "".join(f"<th>{_e(h)}</th>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r) + "</tr>" for r in rest) + "</table></div>")
    return _page(title, body, "Load it into a radio with CHIRP: File → Import (download the .csv first).")


def text_page(text: str, title: str) -> str:
    return _page(title, f"<h1><span>{_e(title)}</span></h1><div class=\"msg\" style=\"padding:10px;min-height:0\">"
                        f"{_e(text)}</div>")


def slug(s: str, n: int = 40) -> str:
    return (re.sub(r"[^A-Za-z0-9]+", "-", str(s or "")).strip("-")[:n].strip("-") or "form")
