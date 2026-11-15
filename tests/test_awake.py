from station import awake
from station.awake import KeepAwake, wanted


def test_held_while_a_radio_listens():
    want, why = wanted("listening", [{"id": "a", "paused": True}, {"id": "b", "name": "FTM", "paused": False}], [])
    assert want and "FTM" in why


def test_released_when_every_radio_is_paused_and_nothing_queued():
    assert wanted("listening", [{"id": "a", "paused": True}], [{"state": "done"}]) == (False, "every radio paused")


def test_held_while_the_accurate_pass_has_work():
    assert wanted("listening", [{"id": "a", "paused": True}], [{"state": "running"}])[0]
    assert wanted("listening", [], [{"state": "queued"}])[0]


def test_every_radio_paused_lets_go_on_every_mode():
    """Owner 2026-11-14: "performance mode should turn off if all radios are on pause"."""
    paused = [{"id": "a", "paused": True}, {"id": "b", "paused": True}]
    for mode in ("traffic", "listening", "always"):
        assert wanted(mode, paused, [{"state": "done"}], busy=True, net_on="ARES", viewer=True) == \
            (False, "every radio paused")
        assert wanted(mode, paused, [{"state": "running"}])[0]           # the accurate pass finishes at full speed
        assert wanted(mode, paused, [{"state": "queued"}])[0]
    assert not wanted("off", paused, [{"state": "running"}])[0]


def test_modes():
    assert wanted("always", [], [])[0] is True
    assert wanted("always", [{"id": "a", "paused": False}], [])[0] is True
    assert wanted("off", [{"id": "a", "paused": False}], [{"state": "running"}])[0] is False


def test_keep_awake_is_a_noop_off_windows(monkeypatch):
    k = KeepAwake()
    k.ok = False
    assert k.set(True) is False and k.held is False


def test_installer_and_station_use_the_same_plan_guid():
    from pathlib import Path
    from station.awake import STATION_PLAN
    ps1 = (Path(__file__).resolve().parent.parent / "install" / "windows" / "install.ps1").read_text()
    assert f"$hn = '{STATION_PLAN}'" in ps1


def _plan(tmp_path, active, saved=None):
    """A PowerPlan with Windows replaced by a dict (no ctypes)."""
    import json
    p = awake.PowerPlan.__new__(awake.PowerPlan)
    p.snapshot = tmp_path / "snap.json"
    if saved:
        p.snapshot.write_text(json.dumps(saved))
    p.state = {"plan": active, "overlay": awake.BEST_PERFORMANCE}
    p.active = lambda: p.state["plan"]
    p.own_mode = lambda: "own-mode"
    p.set = lambda plan, overlay: p.state.update(plan=plan, overlay=overlay)
    return p


def test_restore_puts_back_the_saved_plan(tmp_path):
    p = _plan(tmp_path, awake.STATION_PLAN, {"plan": "my-plan", "overlay": "x"})
    assert p.restore()["plan"] == "my-plan" and p.state == {"plan": "my-plan", "overlay": "own-mode"}
    assert not p.snapshot.exists()


def test_restore_unsticks_the_station_plan_when_nothing_was_saved(tmp_path):
    p = _plan(tmp_path, awake.STATION_PLAN)
    assert p.restore()["plan"] == awake.BALANCED and p.state == {"plan": awake.BALANCED, "overlay": "own-mode"}
    q = _plan(tmp_path, "my-plan")                       # the operator's own plan: left alone
    assert q.restore() is None and q.state["plan"] == "my-plan"


def test_traffic_mode_holds_only_around_traffic_and_nets():
    on = [{"id": "a", "name": "Net radio", "paused": False}]
    assert wanted("traffic", on, []) == (False, "listening, no traffic")          # radio on all night: screen may sleep
    assert wanted("traffic", on, [], busy=True)[0]
    assert wanted("traffic", on, [], quiet_s=120)[0] and not wanted("traffic", on, [], quiet_s=700)[0]
    assert wanted("traffic", on, [], quiet_s=700, quiet_min=15)[0]
    assert wanted("traffic", on, [], net_on="Test net") == (True, "net on the air: Test net")
    assert wanted("traffic", [{"id": "a", "paused": True}], [], busy=True)[0] is False
    assert wanted("traffic", [], [{"state": "running"}])[0]


def test_listening_mode_unchanged():
    assert wanted("listening", [{"id": "a", "paused": False}], [], quiet_s=9999)[0]


def test_the_dashboard_shows_performance_mode_and_hears_when_it_changes(tmp_path):
    """Owner 2026-11-14: "show performance mode status on the dashboard" (header: ⚡ Performance mode / off)."""
    from tests.test_netsummary import _station
    st, _ = _station(tmp_path)

    class Fake:
        ok, held = True, False

        def set(self, want):
            changed, self.held = want != self.held, want
            return changed
    st.awake = Fake()
    sent = []
    pub = st.bus.publish
    st.bus.publish = lambda kind, d: (sent.append((kind, d)) if kind == "pc" else None) or pub(kind, d)
    st.awake_mode = "always"
    st._keep_awake_tick()
    assert sent[-1] == ("pc", {"awake": {"on": True, "why": "keep_awake: always", "mode": "always", "can": True}})
    assert st.snapshot()["pc"]["awake"]["on"] is True
    n = len(sent)
    st._keep_awake_tick()
    assert len(sent) == n                                                 # unchanged: nothing sent
    for rid in list(st.radios):
        st.set_paused(rid, True)
    st._keep_awake_tick()
    assert sent[-1][1]["awake"]["on"] is False and sent[-1][1]["awake"]["why"] == "every radio paused"
