

def test_the_antenna_decides_the_reach_not_a_fixed_circle():
    """Owner 2026-11-25: a Plans search "only looked within 373 mi ... inside the first bounce off of the ionosphere";
    "this antenna can also communicate with Japan on 20m, 17m, 15m ... during the day". The footprint has a skip zone
    and further hops; a "heard well" ring shapes 80 / 40 m only (it had forced -21 dBi at low angles on every band,
    so no DX was ever possible); an inverted V's ends lower its effective height; the best of the day uses the real sun."""
    from station import hfprop as H
    foot = {r["band"]: r for r in H.footprint("invv", 6.0, 50, 88, (644, 966))}
    assert foot["40 m"]["night"][0][0] >= 800                      # 40 m after dark: nothing lands inside ~500 mi
    assert foot["40 m"]["night"][0][1] > 1500 and foot["40 m"]["day"][0][0] < 500
    assert foot["20 m"]["day"][0][0] >= 1000 and foot["20 m"]["night"] == []      # 20 m: a day band with a skip zone
    assert H.regional_km(list(foot.values())) > 1500               # far past 373 mi (600 km)
    home, tokyo = (40.0, -112.0), (35.7, 139.7)
    with_ring = H.reach_day(18.13, home, tokyo, "invv", 9.0, 100, 180, (644, 966))
    no_ring = H.reach_day(18.13, home, tokyo, "invv", 9.0, 100, 180, None)
    assert with_ring["pct"] == no_ring["pct"] >= 80 and no_ring["hours"]     # the ring does not touch 17 m
    assert all(h in (22, 0, 2, 4, 6) for h in no_ring["hours"])     # their afternoon / evening: the real opening
    assert H.reach_day(18.13, home, tokyo, "invv", 9.0, 100, 70)["pct"] < 60    # a quiet sun closes it
    lo = H.estimate(3.8, 800, "01:00", "invv", 6.0, 50, 88, (644, 966))
    assert "sweet spot" in lo["why"] or "you hear stations well" in lo["why"]     # ... and still shapes 40 m
    assert H.invv_height(12, 3) == 9.0 and H.invv_height(12, None) == 12 and H.invv_height(6, 9) == 6
    assert H.hours_words([0, 2, 4, 14, 22]) == "22-06, 14-16 UTC" and H.hours_words(list(range(0, 24, 2))) == "all day"
