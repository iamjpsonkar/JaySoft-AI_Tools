"""Tests for jsat._improve._sanitize — the privacy contract.

These are the most important tests in the self-improvement feature: they assert
that nothing about the user's own codebase can reach a signal record.
"""
from __future__ import annotations

import getpass
import json
from pathlib import Path

import pytest

from jsat._exceptions import ConfigSchemaError, IndexNotFound, ProfileError
from jsat._improve._sanitize import (
    build_record,
    classify_frames,
    classify_message,
    fingerprint,
    jsat_root,
    sanitize_context,
    verify_clean,
)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_IMPROVE_DIR", str(tmp_path / "improve"))


def _raise_and_catch(exc: BaseException) -> BaseException:
    try:
        raise exc
    except BaseException as e:  # noqa: BLE001 — we want the traceback attached
        return e


# ── exception messages must never carry user paths ────────────────────────────

@pytest.mark.ci
def test_index_not_found_drops_user_repo_path():
    exc = _raise_and_catch(IndexNotFound(repo_path="/home/alice/secret-project"))
    record = build_record(kind="crash", source="cli", exc=exc)

    assert record is not None
    blob = json.dumps(record)
    assert "/home/alice" not in blob
    assert "secret-project" not in blob
    assert record["exc_type"] == "IndexNotFound"
    assert record["message_class"] == "No JSAT index found for"


@pytest.mark.ci
def test_unmatched_message_is_dropped_entirely():
    """A non-JSAT message is never stored, even in part."""
    exc = _raise_and_catch(ValueError("failed while parsing /home/bob/app/models.py"))
    record = build_record(kind="crash", source="cli", exc=exc)

    assert record is not None
    blob = json.dumps(record)
    assert "models.py" not in blob
    assert "/home/bob" not in blob
    assert record["message_class"] is None
    assert record["unmatched_message"] is True
    assert record["exc_type"] == "ValueError"


# ── frames ────────────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_frames_are_relative_to_package_and_never_absolute():
    exc = _raise_and_catch(ProfileError("Neo4j requires jsat[team]", required_extra="team"))
    frames = classify_frames(exc)

    assert frames, "expected at least one frame"
    for frame in frames:
        assert not frame.startswith("/")
        assert str(Path.home()) not in frame
        assert frame == "<external>" or frame.startswith("jsat/")


@pytest.mark.ci
def test_external_frames_collapse_to_marker():
    """Frames outside the jsat package are reported as a marker, not a path."""
    exc = _raise_and_catch(ValueError("boom"))
    frames = classify_frames(exc)
    # This test file lives outside the jsat package, so its frame must be masked.
    assert all(str(jsat_root()) not in f for f in frames)
    assert all("test_improve_sanitize" not in f for f in frames)


@pytest.mark.ci
def test_no_exception_yields_no_frames():
    assert classify_frames(None) == []
    assert classify_message(None) == (None, False)


# ── context allowlist ─────────────────────────────────────────────────────────

@pytest.mark.ci
def test_config_schema_error_keeps_field_but_drops_got():
    """`got` is the user's own config value and must never be stored."""
    exc = _raise_and_catch(
        ConfigSchemaError(
            "Invalid config value",
            field="graph.backend", expected="sqlite", got="/home/carol/db",
        )
    )
    record = build_record(kind="crash", source="cli", exc=exc)

    assert record is not None
    detail = record["detail"]
    assert detail.get("expected") == "sqlite"
    assert "/home/carol" not in json.dumps(record)
    # `got` is either absent or reduced to a type marker — never the value itself.
    assert detail.get("got") in (None, "<str>")


@pytest.mark.ci
def test_sanitize_context_reduces_unknown_keys_to_type_markers():
    out = sanitize_context({"provider": "ollama", "path": "/home/dave/x", "count": 3})
    assert out["provider"] == "ollama"
    assert out["count"] == 3
    assert out["path"] == "<str>"  # value dropped, type retained


# ── verify_clean: the adversarial stage ───────────────────────────────────────

@pytest.mark.ci
@pytest.mark.parametrize("payload", [
    {"x": "/etc/passwd"},
    {"x": "~/secrets.txt"},
    {"x": "C:\\Users\\dave\\project"},
    {"x": "AKIAIOSFODNN7EXAMPLE"},
    {"x": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc"},
    {"x": "ghp_" + "a" * 36},
    {"x": "x" * 300},
])
def test_verify_clean_rejects_unsafe_payloads(payload):
    assert verify_clean(payload) is False


@pytest.mark.ci
def test_verify_clean_rejects_home_and_username():
    assert verify_clean({"x": str(Path.home())}) is False
    assert verify_clean({"x": f"user {getpass.getuser()} failed"}) is False


@pytest.mark.ci
def test_verify_clean_rejects_environment_values(monkeypatch):
    monkeypatch.setenv("MY_SECRET_TOKEN", "supersecretvalue123")
    assert verify_clean({"detail": "leaked supersecretvalue123 here"}) is False


@pytest.mark.ci
def test_verify_clean_accepts_jsat_internal_record():
    record = {
        "kind": "crash",
        "frames": ["jsat/tools/indexer.py:parse", "<external>"],
        "exc_type": "IndexNotFound",
        "detail": {"provider": "ollama", "status_code": 404},
    }
    assert verify_clean(record) is True


@pytest.mark.ci
def test_planted_secret_in_detail_drops_whole_record():
    exc = _raise_and_catch(ProfileError("Neo4j requires jsat[team]", required_extra="team"))
    record = build_record(
        kind="crash", source="cli", exc=exc,
        detail={"reason": "AKIAIOSFODNN7EXAMPLE"},
    )
    # Either the value was allowlist-rejected, or the whole record was dropped.
    assert record is None or "AKIAIOSFODNN7EXAMPLE" not in json.dumps(record)


# ── fingerprinting ────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_fingerprint_is_stable_and_discriminating():
    a = fingerprint("crash", "IndexNotFound", "No JSAT index found for", "query", ["jsat/a.py:f"])
    b = fingerprint("crash", "IndexNotFound", "No JSAT index found for", "query", ["jsat/a.py:f"])
    c = fingerprint("crash", "GraphQueryError", "Graph query failed", "query", ["jsat/a.py:f"])
    assert a == b
    assert a != c
    assert len(a) == 16
