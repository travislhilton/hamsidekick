"""The Winlink helper (station/winlink_helper.py) on another PC and the station's side (winlink_helpers.py): owner
2026-11-15, "put the Winlink messages in the Winlink outbox folder on that computer"."""
import copy
import json
import threading
import urllib.request
from pathlib import Path

import pytest

from station import engine, winlink, winlink_helper as H
from station.core import Station
from station.server import serve
from tests.test_winlink import install  # noqa: F401 - the fixture: a fake Winlink Express folder

CFG = {"callsign": "W9XYZ", "radios": [{"id": "a", "name": "FTM", "device": "x", "gate": "carrier", "freq_mhz": 145.9}],
       "schedule": [], "port": 0, "bind": "127.0.0.1", "qrz_online": False}
DRAFT = {"form": "ics213", "values": {"Subjectline": "Shelter status", "Message": "All well at the shelter."}}


@pytest.fixture
def station(tmp_path):
    st = Station(copy.deepcopy(CFG), lambda: engine.FakeEngine(), data_dir=tmp_path / "d")
    srv = serve(st, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield st, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_the_helper_puts_the_message_in_its_own_outbox(station, install, tmp_path, monkeypatch):
    st, base = station
    monkeypatch.setattr(winlink, "DEFAULT_DIR", install)
    cfg = H.load_config(tmp_path / "h") | {"station": base, "name": "SHACK-PC"}
    assert len(cfg["id"]) == 32
    code, r = _post(base + "/api/winlink/send", {"target": cfg["id"], "to": ["K7ABC"], "drafts": [DRAFT]})
    assert code == 400 and "not been seen" in r["error"]          # never asked: nothing queued
    assert H.once(cfg, running=lambda: False, where=tmp_path / "h") == 0
    hs = _get(base + "/api/winlink/helpers")["helpers"]
    assert hs[0]["name"] == "SHACK-PC" and hs[0]["online"] and hs[0]["here"]           # same address as this browser
    assert hs[0]["installs"][0]["accounts"] == ["W9XYZ", "W9XYZ-5"]
    code, q = _post(base + "/api/winlink/send", {"target": cfg["id"], "to": ["k7abc"], "drafts": [DRAFT],
                                                 "account": "W9XYZ"})
    assert code == 200 and q["state"] == "queued" and q["pc"] == "SHACK-PC"
    assert H.once(cfg, running=lambda: False, where=tmp_path / "h") == 1
    j = _get(base + f"/api/winlink/job/{q['job']}")
    assert j["state"] == "written" and j["result"]["account"] == "W9XYZ" and j["result"]["written"][0]["to"] == ["K7ABC"]
    msgs = list((Path(install) / "W9XYZ" / "Messages").glob("*.mime"))
    assert len(msgs) == 1 and b"Shelter status" in msgs[0].read_bytes()
    assert b"Outbox" in (Path(install) / "W9XYZ" / "Data" / "Registry.txt").read_bytes()
    assert H.once(cfg, running=lambda: False, where=tmp_path / "h") == 0                # never written twice


def test_an_open_winlink_express_on_that_pc_is_reported_and_nothing_written(station, install, tmp_path, monkeypatch):
    st, base = station
    monkeypatch.setattr(winlink, "DEFAULT_DIR", install)
    cfg = H.load_config(tmp_path / "h") | {"station": base}
    H.once(cfg, running=lambda: True, where=tmp_path / "h")
    assert _get(base + "/api/winlink/helpers")["helpers"][0]["express_running"]
    _, q = _post(base + "/api/winlink/send", {"target": cfg["id"], "to": ["K7ABC"], "drafts": [DRAFT]})
    H.once(cfg, running=lambda: True, where=tmp_path / "h")
    j = _get(base + f"/api/winlink/job/{q['job']}")
    assert j["state"] == "error" and "Winlink Express is open" in j["error"]
    assert not list((Path(install) / "W9XYZ-5" / "Messages").glob("*.mime"))
    assert "NOT written" in (tmp_path / "h" / "helper.log").read_text(encoding="utf-8")


def test_a_job_is_only_handed_to_its_own_helper_and_ids_are_checked(station):
    st, base = station
    a, b = "a" * 32, "b" * 32
    for hid in (a, b):
        st.wlhelpers.poll({"id": hid, "name": hid[:1]}, "192.168.1.20")
    q = st.wlhelpers.queue(a, ["K7ABC"], [DRAFT])
    assert st.wlhelpers.poll({"id": b}, "192.168.1.20")["jobs"] == []
    assert [j["job"] for j in st.wlhelpers.poll({"id": a}, "192.168.1.20")["jobs"]] == [q["job"]]
    with pytest.raises(LookupError):
        st.wlhelpers.done({"id": b, "job": q["job"], "ok": True})
    code, _ = _post(base + "/api/winlink/helper/poll", {"id": "../../etc"})
    assert code == 400


def test_the_station_serves_the_helper_and_an_installer_with_its_own_address(station):
    st, base = station
    with urllib.request.urlopen(base + "/winlink-helper/install.cmd") as r:
        cmd = r.read().decode()
        assert "attachment" in r.headers["Content-Disposition"]
    assert "/winlink-helper/install.ps1" in cmd and "-Station '" in cmd and "\r\n" in cmd
    for f in ("__init__.py", "winlink.py", "lzhuf.py", "winlink_helper.py"):
        with urllib.request.urlopen(base + "/winlink-helper/files/" + f) as r:
            assert r.status == 200 and r.read()
    with urllib.request.urlopen(base + "/winlink-helper/install.ps1") as r:
        assert b"Register-ScheduledTask -TaskName 'HAM Sidekick Winlink Helper'" in r.read()
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(base + "/winlink-helper/files/core.py")


def test_the_helper_runs_on_the_standard_library_alone(tmp_path):
    """On the other PC only these four files exist: no numpy, no station package beyond them."""
    import shutil
    import subprocess
    import sys
    pkg = tmp_path / "app" / "station"
    pkg.mkdir(parents=True)
    src = Path(H.__file__).parent
    for f in ("__init__.py", "winlink.py", "lzhuf.py", "winlink_helper.py"):
        shutil.copy(src / f, pkg / f)
    r = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.'); import station.winlink_helper as h; "
                        "import station.winlink as w; print(w.fit('a b c d e f', 7))"],
                       cwd=tmp_path / "app", capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "a b..."
