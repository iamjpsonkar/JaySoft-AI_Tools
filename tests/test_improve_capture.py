"""Tests for jsat._improve._capture — gates, fail-safety, and the nudge."""
from __future__ import annotations

import pytest

from jsat._exceptions import IndexNotFound
from jsat._improve import _capture, _store


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_IMPROVE_DIR", str(tmp_path / "improve"))
    monkeypatch.delenv("JSAT_NO_IMPROVE", raising=False)
    monkeypatch.delenv("CI", raising=False)
    _capture._reset_for_tests()
    yield
    _capture._reset_for_tests()


def _boom() -> BaseException:
    try:
        raise IndexNotFound(repo_path="/home/alice/private")
    except BaseException as e:  # noqa: BLE001
        return e


# ── the core guarantee: never raise ───────────────────────────────────────────

@pytest.mark.ci
def test_record_signal_returns_none_and_never_raises():
    assert _capture.record_signal(kind="crash", source="cli", exc=_boom()) is None


@pytest.mark.ci
def test_record_signal_survives_unwritable_store(tmp_path, monkeypatch):
    """A read-only store must not turn into an exception inside an except block."""
    monkeypatch.setenv("JSAT_IMPROVE_DIR", "/proc/nonexistent/cannot-create")
    for _ in range(3):
        _capture.record_signal(kind="crash", source="cli", exc=_boom())
    _capture.flush()  # must not raise


@pytest.mark.ci
def test_record_signal_survives_garbage_input():
    _capture.record_signal(kind="crash", source="cli", exc=None, detail={"a": object()})
    _capture.record_signal(kind="", source="", exc=_boom(), op="x" * 500)


# ── gates ─────────────────────────────────────────────────────────────────────

@pytest.mark.ci
@pytest.mark.parametrize("env", ["JSAT_NO_IMPROVE", "CI"])
def test_env_kill_switches_produce_no_writes(env, monkeypatch):
    monkeypatch.setenv(env, "1")
    for _ in range(5):
        _capture.record_signal(kind="crash", source="cli", exc=_boom())
    _capture.flush()
    assert not (_store.improve_dir() / "signals.jsonl").exists()
    assert _store.read_clusters() == {}


@pytest.mark.ci
@pytest.mark.parametrize("section,field", [("improve", "enabled"), ("privacy", "no_telemetry")])
def test_config_gates_block_persistence(section, field, monkeypatch):
    """improve.enabled=false and privacy.no_telemetry=true each stop all writes."""
    from jsat._models import JSATConfig

    cfg = JSATConfig()
    setattr(getattr(cfg, section), field, field == "no_telemetry")
    _capture.set_config(cfg)

    monkeypatch.setattr(_capture, "_PER_FP_THROTTLE_S", 0.0)
    for _ in range(3):
        _capture.record_signal(kind="crash", source="cli", exc=_boom())
    _capture.flush()
    assert _store.read_clusters() == {}


@pytest.mark.ci
def test_set_config_primes_nudge_thresholds():
    from jsat._models import JSATConfig

    cfg = JSATConfig()
    cfg.improve.nudge_threshold = 42
    _capture.set_config(cfg)
    threshold, _cooldown, _enabled = _capture._nudge_settings()
    assert threshold == 42


@pytest.mark.ci
def test_per_process_cap_is_enforced(monkeypatch):
    monkeypatch.setattr(_capture, "_MAX_PER_PROCESS", 3)
    monkeypatch.setattr(_capture, "_PER_FP_THROTTLE_S", 0.0)
    for _ in range(10):
        _capture.record_signal(kind="crash", source="cli", exc=_boom())
    assert _capture._RECORDED_THIS_PROCESS == 3


# ── buffering and flush ───────────────────────────────────────────────────────

@pytest.mark.ci
def test_signals_persist_and_cluster_on_flush(monkeypatch):
    monkeypatch.setattr(_capture, "_PER_FP_THROTTLE_S", 0.0)
    for _ in range(3):
        _capture.record_signal(kind="crash", source="cli", exc=_boom())
    _capture.flush()

    clusters = _store.read_clusters()
    assert len(clusters) == 1
    cluster = next(iter(clusters.values()))
    assert cluster["count"] == 3
    assert cluster["exc_type"] == "IndexNotFound"


@pytest.mark.ci
def test_throttled_repeats_are_counted_not_lost():
    """A tight retry loop costs one record but the full count is preserved."""
    for _ in range(20):
        _capture.record_signal(kind="crash", source="cli", exc=_boom())
    _capture.flush()

    cluster = next(iter(_store.read_clusters().values()))
    assert cluster["count"] == 20


@pytest.mark.ci
def test_flush_is_idempotent_when_empty():
    _capture.flush()
    _capture.flush()
    assert _store.read_clusters() == {}


# ── the crash net must ignore normal control flow ─────────────────────────────

@pytest.mark.ci
@pytest.mark.parametrize("exc", [SystemExit(1), KeyboardInterrupt()])
def test_main_does_not_record_normal_exits(exc, monkeypatch):
    """Regression: `typer.Exit(1)` raises SystemExit, so every ordinary user error
    (unknown provider, bad flag) was being recorded as a JSAT crash and burying
    real defects."""
    import jsat.cli as cli

    def boom():
        raise exc

    monkeypatch.setattr(cli, "app", boom)
    with pytest.raises(type(exc)):
        cli.main()
    _capture.flush()
    assert _store.read_clusters() == {}


@pytest.mark.ci
def test_main_records_genuine_crashes(monkeypatch):
    import jsat.cli as cli

    def boom():
        raise RuntimeError("something actually broke")

    monkeypatch.setattr(cli, "app", boom)
    with pytest.raises(RuntimeError):
        cli.main()
    _capture.flush()

    clusters = _store.read_clusters()
    assert len(clusters) == 1
    assert next(iter(clusters.values()))["exc_type"] == "RuntimeError"


# ── the nudge ─────────────────────────────────────────────────────────────────

def _seed_cluster(count=5, reported=False):
    clusters = _store.merge_cluster({}, {
        "fingerprint": "fp1", "kind": "crash", "exc_type": "IndexNotFound",
        "message_class": None, "op": "query", "frames": [], "ts": "2026-08-15T09:00:00Z",
        "jsat_version": "0.4.7", "source": "cli", "detail": {},
    }, count=count)
    clusters["fp1"]["reported"] = reported
    _store.write_clusters(clusters)


def _force_tty(monkeypatch, value=True):
    monkeypatch.setattr("sys.stdout.isatty", lambda: value, raising=False)
    monkeypatch.setattr("sys.stderr.isatty", lambda: value, raising=False)


@pytest.mark.ci
def test_nudge_prints_one_line_to_stderr(monkeypatch, capsys):
    _seed_cluster()
    _force_tty(monkeypatch)
    _capture._maybe_nudge()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "jsat improve" in captured.err
    assert len([ln for ln in captured.err.splitlines() if ln.strip()]) == 1


@pytest.mark.ci
def test_nudge_silent_when_not_a_tty(monkeypatch, capsys):
    _seed_cluster()
    _force_tty(monkeypatch, value=False)
    _capture._maybe_nudge()
    assert capsys.readouterr().err == ""


@pytest.mark.ci
def test_nudge_silent_in_mcp_mode(monkeypatch, capsys):
    """Stray stdout/stderr writes would corrupt JSON-RPC on stdio."""
    _seed_cluster()
    _force_tty(monkeypatch)
    _capture.set_mode("mcp")
    _capture._maybe_nudge()
    assert capsys.readouterr().err == ""


@pytest.mark.ci
def test_nudge_silent_when_suppressed(monkeypatch, capsys):
    _seed_cluster()
    _force_tty(monkeypatch)
    _capture.suppress_nudge()
    _capture._maybe_nudge()
    assert capsys.readouterr().err == ""


@pytest.mark.ci
def test_nudge_silent_below_threshold(monkeypatch, capsys):
    _seed_cluster(count=1)
    _force_tty(monkeypatch)
    _capture._maybe_nudge()
    assert capsys.readouterr().err == ""


@pytest.mark.ci
def test_nudge_silent_when_already_reported(monkeypatch, capsys):
    _seed_cluster(reported=True)
    _force_tty(monkeypatch)
    _capture._maybe_nudge()
    assert capsys.readouterr().err == ""


@pytest.mark.ci
def test_nudge_respects_cooldown(monkeypatch, capsys):
    _seed_cluster()
    _force_tty(monkeypatch)
    _capture._maybe_nudge()
    capsys.readouterr()
    _capture._maybe_nudge()  # immediately again
    assert capsys.readouterr().err == ""
