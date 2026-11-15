"""The amateur bands built in (station/bandplan.py): FCC Part 97 privileges by class for phone, data and CW, and the
ARRL band plan's segments (owner 2026-11-15: band plans; the national layer under Local plans)."""
from station import bandplan as B


def test_privileges_by_class_and_kind():
    P = B.privileges
    assert P(14.105, "data", "general")[0] is True                       # VARA HF calling: General data segment
    assert P(14.105, "phone", "general")[0] is False                     # ...but no voice there
    assert "CW / data segment" in P(14.105, "phone", "extra")[1]
    assert P(14.230, "data", "extra")[0] is False                        # no data in the HF phone segment
    assert P(14.010, "data", "general")[0] is False and P(14.010, "data", "extra")[0] is True
    assert P(7.200, "phone", "general")[0] is True and P(7.150, "phone", "general")[0] is False
    assert P(10.140, "data", "general")[0] is True and P(10.140, "phone", "extra")[0] is False
    assert P(145.010, "data", "technician")[0] is True and P(146.52, "phone", "technician")[0] is True
    assert P(144.050, "phone", "extra")[0] is False and P(144.050, "cw", "technician")[0] is True
    assert P(28.400, "phone", "technician")[0] is True and P(28.600, "phone", "technician")[0] is False
    assert P(28.100, "data", "technician")[0] is True and P(7.050, "data", "technician")[0] is False
    assert P(5.3305, "data", "general")[0] is True and P(5.3305, "data", "technician")[0] is False
    assert P(5.3290, "phone", "general")[0] is True                      # the USB dial of channel 1
    assert P(3.915, "phone", None)[0] is None and P(None, "phone", "extra")[0] is None


def test_the_band_plan_says_what_a_frequency_is_for():
    s = B.segment(146.52)
    assert s["band"] == "2 m" and "national FM simplex calling" in s["what"]
    assert "APRS" in B.segment(144.39)["what"] and B.segment(144.39)["warn"]
    assert B.segment(14.105)["auto_data"] and "packet" in B.segment(14.105)["what"]
    assert "beacons" in B.segment(14.100)["what"]
    assert B.segment(146.94)["what"] == "FM repeater outputs"


def test_check_refuses_beacons_satellites_and_talking_on_aprs():
    assert B.check(146.52, "FM", "technician")["ok"] is True
    assert B.check(14.100, "DIG", "extra")["ok"] is False                 # NCDXF beacons
    assert B.check(144.39, "FM", "technician")["ok"] is False             # voice on APRS
    assert B.check(145.9, "FM", "technician")["ok"] is False              # satellite subband
    assert B.check(14.105, "VARA", "general")["kind"] == "data"


def test_the_sidekick_check_still_reads_the_same():
    from station.agent import PHONE, privileges
    assert privileges(5.3305, "LSB", "general")[0] is None               # a 60 m channel is USB only
    assert (7.175, 7.3) in PHONE["general"] and all(b < 500 for _, b in PHONE["extra"])


def test_the_table_for_the_dashboard():
    t = {b["band"]: b for b in B.table("general")}
    assert t["20 m"]["mine"]["phone"] == [(14.225, 14.35)] and t["20 m"]["mine"]["data"] == [(14.025, 14.15)]
    assert any(p["from"] == 146.52 for p in t["2 m"]["plan"])
    assert B.table(None)[0]["mine"] is None
