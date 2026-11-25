"""Share a net schedule over the air (station/netshare.py; owner 2026-11-24: "how can we share net schedules this way")."""
import json
from datetime import datetime

from station import netshare as N
from tests.test_portable import _two


def test_the_net_file_carries_the_nets_only_and_adds_on_the_other_station(tmp_path):
    a, b = _two(tmp_path)
    a.nets.add({"name": "Regulars Net", "freq_mhz": 147.2, "offset_mhz": 0.6, "mode": "FM", "start": "20:00",
                "duration_min": 30, "repeat": {"freq": "weekly", "weekdays": ["Wed"]}, "alert_min": 15,
                "checkins": ["K7ABC"]})
    d = N.export(a, "W9XYZ")
    txt = json.dumps(d)
    assert d["kind"] == "nets" and d["from"] == "W9XYZ" and len(d["nets"]) == len(a.cfg["schedule"])
    assert "checkins" not in txt and "alert_min" not in txt and "sidekick" not in d and "local_names" not in d
    assert "license_class" not in txt and "Pat" not in txt
    p = tmp_path / ("W9XYZ-nets" + N.SUFFIX)
    p.write_text(txt, encoding="utf-8")
    s = N.summary(p)
    assert s["from"] == "W9XYZ" and s["nets"] == len(d["nets"]) and "Tuesday Net" in s["names"]
    before = json.dumps(b.cfg.get("schedule"))
    pv = N.preview(b, p)
    assert pv["source"] == "W9XYZ" and pv["nets"]["add"] >= 2 and json.dumps(b.cfg.get("schedule")) == before
    agent_before = json.dumps(b.agent.cfg, sort_keys=True)
    r = N.install(b, p)
    names = {n["name"] for n in b.cfg["schedule"]}
    assert {"Tuesday Net", "No Radio Net"} <= names and r["added"] >= 2 and r["source"] == "W9XYZ"
    assert json.dumps(b.agent.cfg, sort_keys=True) == agent_before                # Einstein's settings never travel
    assert N.install(b, p)["added"] == 0                                         # again: nothing new
    assert "Tuesday Net" in N.text(p) and "146.940 MHz" in N.text(p)


def test_a_file_that_is_not_a_net_file_is_refused(tmp_path):
    p = tmp_path / "x.hsnets"
    p.write_text('{"schema": "something else", "nets": []}', encoding="utf-8")
    assert N.summary(p) is None
    p.write_text("not json", encoding="utf-8")
    try:
        N.read(p)
        raise AssertionError("read a bad file")
    except ValueError as e:
        assert "not a HAM Sidekick net file" in str(e)


def test_the_calendar_has_each_meeting_of_the_next_weeks(tmp_path):
    a, _ = _two(tmp_path)
    cal = N.ics(a, "W9XYZ", weeks=4, now=datetime(2026, 11, 24, 12, 0))
    assert cal.startswith("BEGIN:VCALENDAR\r\n") and cal.endswith("END:VCALENDAR\r\n")
    ev = cal.split("BEGIN:VEVENT")[1:]
    tue = [e for e in ev if "SUMMARY:Tuesday Net" in e]
    assert len(tue) == 4 and "DTSTART:20261124T190000" in tue[0] and "DTEND:20261124T200000" in tue[0]
    assert "146.940 MHz FM" in tue[0] and "tone 100 Hz" in tue[0]
    assert all(len(line.encode()) <= 75 for line in cal.split("\r\n"))
    uids = [line for line in cal.split("\r\n") if line.startswith("UID:")]
    assert len(uids) == len(set(uids))
