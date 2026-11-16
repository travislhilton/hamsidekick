"""tools/pick_engine.py on a PC where neither OpenVINO nor NVIDIA runs (owner 2026-11-16: Windows 11 on ARM
in a VM, where the x64 OpenVINO crashes): faster-whisper on the CPU is measured and chosen."""
import importlib.util
import types
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _picker():
    spec = importlib.util.spec_from_file_location("pick_engine", ROOT / "tools" / "pick_engine.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_windows_on_arm_skips_openvino_and_picks_faster_whisper_on_the_cpu(tmp_path, monkeypatch):
    pe = _picker()
    monkeypatch.setattr(pe, "windows_arm", lambda: True)
    monkeypatch.setattr(pe, "openvino_devices", lambda: (_ for _ in ()).throw(AssertionError("OpenVINO asked")))
    monkeypatch.setattr(pe, "has_nvidia", lambda: False)
    rtf = {"small.en": 0.43, "base.en": 0.17}
    monkeypatch.setattr(pe, "measure", lambda c, audio: {"rtf": rtf[c["model"]], "text": "K7ABC", "heard_call": True})
    models = tmp_path / "models"
    (models / "whisper-small.en-int8-ov").mkdir(parents=True)
    out = tmp_path / "engine.yaml"
    assert pe._measure_all(types.SimpleNamespace(models=str(models), out=str(out)), None) == 0
    got = yaml.safe_load(out.read_text())
    assert got["final"] == {"engine": "faster-whisper", "device": "cpu", "model": "small.en", "rtf": 0.43}
    assert got["partial"] is None                                     # base.en at 0.17x: too slow for partials
    assert [r["engine"] for r in got["measured"]] == ["faster-whisper", "faster-whisper"]


def test_the_cpu_fallback_is_not_measured_when_an_engine_runs(tmp_path, monkeypatch):
    pe = _picker()
    monkeypatch.setattr(pe, "windows_arm", lambda: False)
    monkeypatch.setattr(pe, "openvino_devices", lambda: ["CPU"])
    monkeypatch.setattr(pe, "has_nvidia", lambda: False)
    monkeypatch.setattr(pe, "measure", lambda c, audio: {"rtf": 0.3, "text": "", "heard_call": True})
    models = tmp_path / "models"
    (models / "whisper-small.en-int8-ov").mkdir(parents=True)
    out = tmp_path / "engine.yaml"
    pe._measure_all(types.SimpleNamespace(models=str(models), out=str(out)), None)
    got = yaml.safe_load(out.read_text())
    assert got["final"]["engine"] == "openvino" and all(r["engine"] == "openvino" for r in got["measured"])
