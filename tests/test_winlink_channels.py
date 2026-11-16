"""Winlink RMS gateways near the station, from Winlink Express's own channel list (station/winlink_channels.py; owner
2026-11-16: "select VARA or VARA FM ... service codes PUBLIC EMCOMM. Use the Grid Square value to determine distance
from the station"). Calls here are examples only."""
from pathlib import Path

from station import localplans as LP
from station import winlink_channels as wc
from tests.test_localplans import _plans

HERE = (39.80, -89.65)                     # Springfield, IL (the repo's example place)
VHF = ("﻿K7ABC-10|EM59mt|145050000|1200|51|PUBLIC\r\n"     # VARA FM, ~50 km: in
       "K7ABC-10|EM59mt|145050000|9600|52|PUBLIC\r\n"            # same gateway and frequency, VARA FM wide: one row
       "N0CALL-10|EM59ht|145070000|1200|0|PUBLIC\r\n"            # packet: not VARA
       "W9XYZ-10|EM59gt|440950000|9600|52|EMCOMM\r\n"            # EMCOMM, near: in
       "W9XYZ-11|EM59gt|145090000|1200|51|MARS\r\n"              # another service: out
       "K7ABC-12|EN61aa|145030000|1200|51|PUBLIC\r\n"            # Chicago area, ~250 km: out
       "garbage line\r\n")
HF = ("N0CALL|EM59gt|7102500|50|00-23|PUBLIC\r\n"
      "N0CALL|EM59gt|7102500|54|00-23|PUBLIC\r\n"
      "N0CALL|EM59gt|3592500|43|00-23|PUBLIC\r\n"                 # ARDOP: out
      "W9XYZ|EM48ss|14105000|53|12-23|PUBLIC\r\n")


def _express(tmp_path) -> Path:
    inst = tmp_path / "RMS Express"
    d = inst / "W9XYZ" / "Data"
    d.mkdir(parents=True)
    (d / wc.VHF_FILE).write_text(VHF, encoding="utf-8")
    (d / wc.HF_FILE).write_text(HF, encoding="utf-8")
    (inst / "RMS Express.exe").write_bytes(b"")
    return inst


def test_only_vara_gateways_with_public_or_emcomm_codes_within_reach_nearest_first(tmp_path):
    inst = _express(tmp_path)
    f = wc.files([str(inst)])
    v = wc.near(f["vhf"], False, HERE, 80)
    assert [(r["call"], r["freq_mhz"]) for r in v] == [("W9XYZ-10", 440.95), ("K7ABC-10", 145.05)]
    assert v[1]["modes"] == ["VARA FM", "VARA FM wide"] and v[0]["service"] == "EMCOMM" and v[0]["km"] < v[1]["km"]
    h = wc.near(f["hf"], True, HERE, 600)
    assert [(r["call"], r["freq_mhz"], r["modes"]) for r in h][0] == ("N0CALL", 7.1025, ["VARA HF", "VARA HF 2750"])
    assert all(r["freq_mhz"] != 3.5925 for r in h) and h[-1]["hours"] == "12-23"
    use = wc.as_frequencies(v, "t")[1]["use"]
    assert use.startswith("Winlink gateway K7ABC-10 (VARA FM / VARA FM wide), ") and "mi " in use and "grid EM59mt" in use


def test_the_gateways_go_into_the_band_plan_from_express_and_hf_is_only_offered(tmp_path, monkeypatch):
    inst = _express(tmp_path)
    st, p, _, _ = _plans(tmp_path)
    st.where = lambda: HERE
    monkeypatch.setattr(p, "_installs", lambda: [str(inst)])
    s = p.state()
    gws = {g["key"]: g for g in s["gateways"]}
    vhf, hf = gws["express:vhf"], gws["express:hf"]
    assert vhf["band"]["in"] and not hf["band"]["in"]                    # VHF/UHF in; VARA HF offered, unticked
    assert "50 mi" in vhf["title"] and [g["gateway"]["call"] for g in vhf["list"]] == ["W9XYZ-10", "K7ABC-10"]
    t = p.consolidated()
    rows = [r for b in t["bands"] for r in b["rows"] if r["type"] == "channel" and "Winlink gateway" in (r["use"] or "")]
    assert {round(r["from"], 3) for r in rows} == {145.05, 440.95}
    p.choose("express:hf", True)
    assert p.state()["gateways"][1]["band"]["in"]
    p.settings({"km": 300})                                                # a wider reach rebuilds the list
    assert "186 mi" in {g["key"]: g for g in p.state()["gateways"]}["express:vhf"]["title"]
    assert len({g["key"]: g for g in p.state()["gateways"]}["express:vhf"]["list"]) == 3


def test_an_old_or_missing_channel_list_asks_the_operator_to_update_it(tmp_path, monkeypatch):
    """Owner 2026-11-16: "if the list in Winlink has not been updated recently or not updated yet (new instance) ask
    the user to update their Winlink Channel Selection"."""
    import os
    import time
    inst = _express(tmp_path)
    st, p, _, _ = _plans(tmp_path)
    st.where = lambda: HERE
    monkeypatch.setattr(p, "_installs", lambda: [str(inst)])
    assert p.state()["winlink_list"]["ask"] is False                     # both lists fresh
    hf = next(inst.glob("*/Data/" + wc.HF_FILE))
    nine = time.time() - 9 * 86400 - 60
    os.utime(hf, (nine, nine))
    assert p.state()["winlink_list"]["ask"] is False                     # 9 days: fine (owner: "10 days")
    old = time.time() - 11 * 86400 - 60
    os.utime(hf, (old, old))
    n = p.state()["winlink_list"]
    assert n["ask"] and {k["kind"]: (k["stale"], k["days"]) for k in n["kinds"]} == {"vhf": (False, 0), "hf": (True, 11)}
    hf.unlink()                                                          # a new Express: never downloaded
    n = p.consolidated()["winlink_list"]
    assert n["ask"] and next(k for k in n["kinds"] if k["kind"] == "hf")["missing"]
    p.settings({"list_snooze": True})                                     # "Remind me in a week"
    assert p.state()["winlink_list"]["ask"] is False
    monkeypatch.setattr(p, "_installs", lambda: [])                       # no Winlink Express on this PC: nothing asked
    assert p.state()["winlink_list"] is None


def test_the_page_asks_for_the_update_in_plans_and_the_band_plan():
    from station.server import STATIC
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "Please update Winlink Express's RMS channel list" in html and "Update Table Via Internet" in html
    assert html.count("wlListNote(d.winlink_list)") == 2 and "data-wlsnooze" in html


def test_a_new_list_from_express_is_picked_up_by_itself(tmp_path, monkeypatch):
    """Owner 2026-11-16: "update the Winlink Channel Selection whenever they want and the band plan should
    automatically pick it up": the watcher sees the new file and tells open dashboards."""
    import os
    import threading
    import time
    inst = _express(tmp_path)
    st, p, _, _ = _plans(tmp_path)
    st.where = lambda: HERE
    told = []
    st.publish = lambda kind, data: told.append((kind, data))
    monkeypatch.setattr(p, "_installs", lambda: [str(inst)])
    p.state()
    vhf = next(inst.glob("*/Data/" + wc.VHF_FILE))
    vhf.write_text(VHF + "N0CALL-10|EM59ht|145090000|1200|51|PUBLIC\r\n", encoding="utf-8")
    later = time.time() + 5
    os.utime(vhf, (later, later))
    stop = threading.Event()
    th = threading.Thread(target=p.watch_express, args=(stop, 0.05), daemon=True)
    th.start()
    deadline = time.time() + 3
    while not told and time.time() < deadline:
        time.sleep(0.05)
    stop.set()
    assert told and told[0] == ("localplans", {"gateways": True})
    calls = {g["gateway"]["call"] for g in {x["key"]: x for x in p.state()["gateways"]}["express:vhf"]["list"]}
    assert "N0CALL-10" in calls


def test_each_list_reminder_is_optional(tmp_path, monkeypatch):
    """Owner 2026-11-16: "make the VARA HF and VARA FM Winlink channel selection updates optional. An operator may not
    be using Winlink or VARA FM at all"."""
    import os
    import time
    import pytest
    inst = _express(tmp_path)
    st, p, _, _ = _plans(tmp_path)
    st.where = lambda: HERE
    monkeypatch.setattr(p, "_installs", lambda: [str(inst)])
    old = time.time() - 40 * 86400
    for f in inst.glob("*/Data/*.dat"):
        os.utime(f, (old, old))
    assert p.state()["winlink_list"]["ask"]                                # both old, both reminded by default
    p.settings({"list_remind": {"hf": False}})
    n = p.state()["winlink_list"]
    assert n["ask"] and {k["kind"]: k["remind"] for k in n["kinds"]} == {"vhf": True, "hf": False}
    p.settings({"list_remind": {"vhf": False}})                             # not using Winlink at all
    assert p.state()["winlink_list"]["ask"] is False
    p.settings({"list_remind": {"hf": True}})                               # Settings → Winlink turns it back on
    assert p.consolidated()["winlink_list"]["ask"]
    with pytest.raises(ValueError):
        p.settings({"list_remind": {"uhf": True}})
    from station.server import STATIC
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="wlListSet"' in html and "data-wlremind" in html and "data-wloff" in html
