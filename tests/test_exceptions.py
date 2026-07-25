"""Tests for jsat._exceptions. No external deps required — always runs in CI."""
import pytest
from jsat._exceptions import (
    JSATError, ConfigFileNotFound, IndexNotFound, IndexOutOfDate,
    AIRateLimitError, AIAuthError, ProfileError, ImportVersionMismatch,
    SkillNotFound,
)


@pytest.mark.ci
def test_jsat_error_base():
    err = JSATError("something failed", code=42, source="test")
    assert str(err) == "something failed"
    assert err.context == {"code": 42, "source": "test"}


@pytest.mark.ci
def test_config_file_not_found_default_message():
    err = ConfigFileNotFound(path="/tmp/missing.yaml")
    assert "/tmp/missing.yaml" in str(err)
    assert err.path == "/tmp/missing.yaml"


@pytest.mark.ci
def test_index_not_found_default_message():
    err = IndexNotFound(repo_path="/my/repo")
    assert "jsat index" in str(err)
    assert err.repo_path == "/my/repo"


@pytest.mark.ci
def test_index_out_of_date():
    err = IndexOutOfDate(current_commit="abc123", index_commit="def456")
    assert "abc123"[:8] in str(err) or "abc" in str(err)
    assert err.current_commit == "abc123"
    assert err.index_commit == "def456"


@pytest.mark.ci
def test_ai_rate_limit_no_retry_after():
    err = AIRateLimitError(provider="anthropic")
    assert "anthropic" in str(err)
    assert err.retry_after is None


@pytest.mark.ci
def test_ai_rate_limit_with_retry_after():
    err = AIRateLimitError(provider="openai", retry_after=60)
    assert err.retry_after == 60


@pytest.mark.ci
def test_ai_auth_error_default_message():
    err = AIAuthError(provider="anthropic")
    assert "anthropic" in str(err).lower()
    assert "api key" in str(err).lower() or "authentication" in str(err).lower()


@pytest.mark.ci
def test_profile_error_default_message():
    err = ProfileError(required_extra="team")
    assert "jsat[team]" in str(err)
    assert err.required_extra == "team"


@pytest.mark.ci
def test_profile_error_custom_message():
    err = ProfileError("Need team features", required_extra="team")
    assert str(err) == "Need team features"


@pytest.mark.ci
def test_import_version_mismatch():
    err = ImportVersionMismatch(export_version="0.1.0", current_version="0.2.0")
    assert "0.1.0" in str(err)
    assert "0.2.0" in str(err)
    assert "--migrate" in str(err)


@pytest.mark.ci
def test_skill_not_found():
    err = SkillNotFound(name="blast-radius")
    assert "blast-radius" in str(err)
    assert err.name == "blast-radius"


@pytest.mark.ci
def test_exception_repr():
    err = JSATError("test", key="val")
    r = repr(err)
    assert "JSATError" in r
    assert "test" in r
