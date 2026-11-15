"""transcribe/gpu.py: Whisper holds the GPU only while it is used (2026-11-10).

The MLX cache was never handed back, so the server grew to 43 GB between restarts; the model now also unloads when
the requests stop. MLX and mlx_whisper are faked here: no GPU, no model."""
import threading

import pytest

from transcribe import gpu


class FakeMx:
    def __init__(self):
        self.cleared = 0
        self.limit = None

    def clear_cache(self):
        self.cleared += 1

    def set_cache_limit(self, n):
        self.limit = n

    def get_active_memory(self):
        return 3 * 2**30

    def get_cache_memory(self):
        return 0


class FakeHolder:
    model = object()
    model_path = "mlx-community/whisper-large-v3-mlx"


@pytest.fixture
def fakes(monkeypatch):
    mx, holder = FakeMx(), FakeHolder
    holder.model, holder.model_path = object(), "mlx-community/whisper-large-v3-mlx"
    monkeypatch.setattr(gpu, "_mx", lambda: mx)
    monkeypatch.setattr(gpu, "_holder", lambda: holder)
    monkeypatch.setattr(gpu, "IDLE_UNLOAD_S", 600.0)
    monkeypatch.setattr(gpu, "_last_used", 0.0)
    return mx, holder


def test_every_decode_hands_the_cache_back_even_when_it_fails(fakes):
    mx, _ = fakes
    with gpu.using():
        pass
    with pytest.raises(RuntimeError):
        with gpu.using():
            raise RuntimeError("decode failed")
    assert mx.cleared == 2
    assert not gpu.lock.locked()


def test_the_cache_is_capped_at_start_up(fakes, monkeypatch):
    mx, _ = fakes
    monkeypatch.setattr(gpu, "CACHE_LIMIT_GB", 4.0)
    gpu.configure()
    assert mx.limit == 4 * 2**30


def test_the_model_stays_while_requests_keep_coming(fakes):
    _, holder = fakes
    with gpu.using():
        pass
    t = gpu._last_used
    assert not gpu.unload_if_idle(now=t + 599)
    assert holder.model is not None


def test_the_model_unloads_after_the_idle_time_and_the_cache_goes_with_it(fakes):
    mx, holder = fakes
    with gpu.using():
        pass
    t, cleared = gpu._last_used, mx.cleared
    assert gpu.unload_if_idle(now=t + 601)
    assert holder.model is None and holder.model_path is None
    assert mx.cleared == cleared + 1
    assert not gpu.loaded()
    assert not gpu.unload_if_idle(now=t + 1200), "nothing left to unload"


def test_nothing_unloads_before_the_first_request_or_when_disabled(fakes, monkeypatch):
    _, holder = fakes
    assert not gpu.unload_if_idle(now=10**9), "no request yet: the clock has not started"
    with gpu.using():
        pass
    monkeypatch.setattr(gpu, "IDLE_UNLOAD_S", 0.0)
    assert not gpu.unload_if_idle(now=gpu._last_used + 10**6)
    assert holder.model is not None


def test_an_unload_waits_for_a_running_decode(fakes):
    """The unload takes the decode lock: it can never pull the model out from under a decode."""
    _, holder = fakes
    with gpu.using():
        pass
    later = gpu._last_used + 601
    result = {}
    with gpu.lock:
        t = threading.Thread(target=lambda: result.update(done=gpu.unload_if_idle(now=later)))
        t.start()
        t.join(0.2)
        assert t.is_alive() and holder.model is not None
    t.join(2)
    assert result["done"] and holder.model is None


def test_health_says_whether_whisper_is_loaded(fakes):
    s = gpu.status()
    assert s["whisper_loaded"] is True and s["idle_unload_s"] == 600.0
    assert s["gpu_active_gb"] == 3.0 and s["gpu_cache_gb"] == 0.0


def test_without_mlx_everything_is_a_no_op(monkeypatch):
    monkeypatch.setattr(gpu, "_mx", lambda: None)
    monkeypatch.setattr(gpu, "_holder", lambda: None)
    gpu.configure()
    with gpu.using():
        pass
    assert not gpu.loaded()
    assert not gpu.unload_if_idle(now=10**9)
    assert gpu.status()["whisper_loaded"] is False


def test_every_decode_on_the_server_goes_through_the_gpu_lock():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "transcribe" / "server.py").read_text()
    assert src.count("with gpu.using(f\"") == 3, "/accurate, /accurate/context and /transcribe"
    assert "_accurate_lock" not in src
    assert "gpu.start_idle_watcher()" in src and "gpu.configure()" in src and "gpu.start_watchdog()" in src


def test_a_decode_that_never_ends_says_not_ok_then_restarts_the_service(fakes, monkeypatch):
    """2026-11-15: one decode ran 30 h holding the lock; /health still said ok, so every station's upload timed out."""
    monkeypatch.setattr(gpu, "STUCK_S", 1200.0)
    monkeypatch.setattr(gpu, "STUCK_EXIT_S", 1500.0)
    exits = []
    assert gpu.busy_s() is None and not gpu.stuck() and not gpu.watchdog_check(exit=exits.append)
    with gpu.using("context final 840 s audio, 30 clips, both"):
        t0 = gpu._busy[0]
        assert not gpu.stuck(t0 + 600) and gpu.stuck(t0 + 1300)
        assert not gpu.watchdog_check(t0 + 1300, exit=exits.append)
        assert gpu.watchdog_check(t0 + 1600, exit=exits.append) and exits == [70]
        assert gpu.status()["busy_s"] is not None
    assert gpu.busy_s() is None and gpu.status()["stuck"] is False


def test_health_is_not_ok_while_a_decode_is_stuck(monkeypatch):
    from transcribe import server
    monkeypatch.setattr(server.gpu, "status", lambda: {"stuck": True, "busy_s": 5000})
    assert server.health()["ok"] is False
    monkeypatch.setattr(server.gpu, "status", lambda: {"stuck": False, "busy_s": None})
    assert server.health()["ok"] is True
