

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


def test_sea_water_bounces_the_wire_s_direction_and_the_gray_line():
    """Owner 2026-11-25 ("Add the not done items as well"): "when traveling over water/oceans it can bounce many
    times"; "whether my station or another station is in the gray line (sunset or sunrise)". A ground bounce on sea
    water loses less than one on land (station/landmask.py); a straight wire whose direction is set fires best at
    right angles to itself once it is high enough; sunrise or sunset at an end of the path is named."""
    from datetime import datetime, timezone
    from station import hfprop as H
    from station.landmask import is_land
    assert is_land(38.5, -98.0) and is_land(35.7, 139.7) and not is_land(30.0, -160.0) and not is_land(35.0, -40.0)
    west, japan, east = (37.8, -122.4), (35.7, 139.7), (39.0, -77.0)
    db_sea, n_sea = H.ground_loss(west, japan, 3)                 # across the Pacific: both bounces on water
    db_land, n_land = H.ground_loss(west, east, 3)                # across the continent: both on land
    assert (n_sea, n_land) == (2, 0) and db_sea == 2 * H.SEA_DB < db_land == 2 * H.GROUND_DB
    when = datetime(2026, 11, 25, 0, 0, tzinfo=timezone.utc)
    km = H.great_circle_km(west, japan)
    e = H.estimate(14.2, km, "16:00", "dipole", 12.0, 100, 150, None, when, None, "average", (west, japan))
    assert e["sea"] >= 2 and "on sea water" in e["why"]
    # a dipole 12 m up on 20 m (0.57 wavelength): broadside beats the average, off the ends is far down
    side, avg, end = (H.gain("dipole", 14.2, 12.0, 10, off_broadside=0), H.gain("dipole", 14.2, 12.0, 10),
                      H.gain("dipole", 14.2, 12.0, 10, off_broadside=90))
    assert side > avg > end and side - end >= 15
    assert H.gain("invv", 14.2, 12.0, 10, off_broadside=0) - H.gain("invv", 14.2, 12.0, 10, off_broadside=90) <= 10.1
    low = H.gain("dipole", 3.8, 6.0, 60, off_broadside=90)        # a low wire, a steep angle: the same all round
    assert abs(low - H.gain("dipole", 3.8, 6.0, 60, off_broadside=0)) < 0.5
    brg = H.bearing(west, japan)                                  # ~303 degrees: a wire running that way is end-on
    on = H.estimate(14.2, km, "16:00", "dipole", 12.0, 100, 150, None, when, None, "average", (west, japan), (brg + 90) % 180)
    off = H.estimate(14.2, km, "16:00", "dipole", 12.0, 100, 150, None, when, None, "average", (west, japan), brg % 180)
    assert on["snr_hear"] - off["snr_hear"] >= 8 and "off your wire's broadside" in off["why"]
    r = H.reach_day(14.2, west, japan, "dipole", 12.0, 100, 150, day=when)
    assert r["hours"] and set(r["gray"]) <= set(r["hours"]) and r["sea"] >= 2
    ev = H.sun_events(when, *west)                                # San Francisco: sunrise ~15 UTC, sunset ~01 UTC
    assert len(ev) == 2 and any(14.5 < t < 15.6 for t in ev) and any(0.4 < t < 1.4 for t in ev)
    at = lambda t: when.replace(hour=int(t), minute=int(t % 1 * 60))   # noqa: E731
    g = lambda w: H.estimate(7.1, km, "16:00", "dipole", 12.0, 100, 150, None, w, None, "average", (west, japan))["gray"]   # noqa: E731
    assert g(at(min(ev))) == "your end" and g(at(H.sun_events(when, *japan)[0])) == "their end" and g(at(5.0)) is None   # 9 pm in San Francisco, 2 pm in Tokyo
    assert H.invv_model_height(12, 3) == 11.25 and H.invv_model_height(12, None) == 12
