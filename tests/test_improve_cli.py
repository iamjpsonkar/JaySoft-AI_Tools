"""Tests for `jsat improve` — bundling, AI degradation, and the anti-self-patch guard."""
from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jsat._improve import _capture, _store
from jsat.cli import app
from jsat.tools import improve as improve_tool

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_IMPROVE_DIR", str(tmp_path / "improve"))
    monkeypatch.delenv("JSAT_NO_IMPROVE", raising=False)
    monkeypatch.delenv("CI", raising=False)
    _capture._reset_for_tests()
    yield
    _capture._reset_for_tests()


def _seed(count=4, exc_type="IndexNotFound", frames=None):
    clusters = _store.merge_cluster({}, {
        "fingerprint": "abcd1234deadbeef", "kind": "crash", "exc_type": exc_type,
        "message_class": "No JSAT index found for", "op": "query",
        "frames": frames if frames is not None else ["jsat/_core.py:index"],
        "ts": "2026-08-15T09:00:00Z", "jsat_version": "0.4.7",
        "source": "cli", "detail": {},
    }, count=count)
    _store.write_clusters(clusters)
    return clusters["abcd1234deadbeef"]


class _StubAI:
    """Minimal provider double."""

    def __init__(self, response="", available=True, raises=False):
        self._response, self._available, self._raises = response, available, raises

    def is_available(self):
        return self._available

    def complete(self, prompt, max_tokens=2048, temperature=0.1):
        if self._raises:
            raise RuntimeError("provider exploded")
        return self._response


# ── listing ───────────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_list_on_empty_store_exits_zero():
    result = runner.invoke(app, ["improve", "--list"])
    assert result.exit_code == 0
    assert "No issues recorded" in result.output


@pytest.mark.ci
def test_list_renders_seeded_cluster():
    _seed()
    result = runner.invoke(app, ["improve", "--list"])
    assert result.exit_code == 0
    assert "abcd1234" in result.output
    assert "IndexNotFound" in result.output


@pytest.mark.ci
def test_unknown_id_exits_one():
    _seed()
    result = runner.invoke(app, ["improve", "--id", "nosuchid"])
    assert result.exit_code == 1


# ── AI degradation ────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_unavailable_ai_yields_diagnosis_only_not_an_error():
    """NoOpProvider.complete() raises, so this path must be guarded."""
    cluster = _seed()
    analysis, diff, status, changed = improve_tool.diagnose(cluster, _StubAI(available=False))
    assert status == "no_ai"
    assert (analysis, diff, changed) == ("", "", [])


@pytest.mark.ci
def test_raising_ai_is_caught():
    cluster = _seed()
    _analysis, _diff, status, _changed = improve_tool.diagnose(cluster, _StubAI(raises=True))
    assert status == "ai_error"


@pytest.mark.ci
def test_prose_response_without_diff_is_no_patch():
    cluster = _seed()
    ai = _StubAI(response="I think the problem is complicated.")
    _analysis, diff, status, _changed = improve_tool.diagnose(cluster, ai)
    assert status == "no_patch"
    assert diff == ""


@pytest.mark.ci
def test_unappliable_patch_is_reported_not_applied():
    cluster = _seed()
    ai = _StubAI(response=(
        "```analysis\nRoot cause here.\n```\n\n"
        "```diff\n--- a/jsat/_core.py\n+++ b/jsat/_core.py\n"
        "@@ -1,2 +1,2 @@\n this context does not exist\n-nope\n+yes\n```\n"
    ))
    _analysis, _diff, status, changed = improve_tool.diagnose(cluster, ai)
    assert status == "did_not_apply"
    assert changed == []


# ── the critical safety guarantee ─────────────────────────────────────────────

@pytest.mark.ci
def test_improve_never_opens_installed_package_for_writing(monkeypatch, tmp_path):
    """A full improve run must not write anywhere under the installed jsat package."""
    import jsat

    package_root = Path(jsat.__file__).resolve().parent
    violations: list[str] = []

    real_open = builtins.open
    real_write_text = Path.write_text
    real_write_bytes = Path.write_bytes

    def _guard(path, mode="r"):
        if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
            try:
                resolved = Path(path).resolve()
                if str(resolved).startswith(str(package_root)):
                    violations.append(str(resolved))
            except Exception:
                pass

    def fake_open(file, mode="r", *args, **kwargs):
        _guard(file, mode)
        return real_open(file, mode, *args, **kwargs)

    def fake_write_text(self, *args, **kwargs):
        _guard(self, "w")
        return real_write_text(self, *args, **kwargs)

    def fake_write_bytes(self, *args, **kwargs):
        _guard(self, "wb")
        return real_write_bytes(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(Path, "write_text", fake_write_text)
    monkeypatch.setattr(Path, "write_bytes", fake_write_bytes)

    cluster = _seed()
    # A patch that WOULD apply cleanly if it were ever written to the real package.
    target = package_root / "_improve" / "_store.py"
    first_line = target.read_text(encoding="utf-8").splitlines()[0]
    ai = _StubAI(response=(
        "```analysis\nfix\n```\n\n"
        f"```diff\n--- a/jsat/_improve/_store.py\n+++ b/jsat/_improve/_store.py\n"
        f"@@ -1,1 +1,1 @@\n-{first_line}\n+{first_line} EDITED\n```\n"
    ))
    analysis, diff, status, changed = improve_tool.diagnose(cluster, ai)
    improve_tool.write_bundle(cluster, analysis, diff, status, changed)

    assert violations == [], f"wrote inside the installed package: {violations}"
    # And the real file is untouched.
    assert "EDITED" not in target.read_text(encoding="utf-8")


@pytest.mark.ci
def test_safe_write_blocks_package_targets():
    import jsat

    with pytest.raises(ValueError, match="refusing to write"):
        _store._safe_write(Path(jsat.__file__).resolve().parent / "x.py", "nope")


# ── bundle contents ───────────────────────────────────────────────────────────

@pytest.mark.ci
def test_bundle_has_manifest_and_marks_cluster_reported():
    cluster = _seed()
    bundle = improve_tool.write_bundle(cluster, "analysis text", "", "no_ai", [])
    improve_tool.mark_reported(cluster["fingerprint"], bundle.name)

    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["patch_status"] == "no_ai"
    assert manifest["cluster"]["fingerprint"] == cluster["fingerprint"]
    assert (bundle / "issue.md").exists()
    assert _store.read_clusters()[cluster["fingerprint"]]["reported"] is True


@pytest.mark.ci
def test_issue_url_stays_under_limit_and_prefills():
    cluster = _seed()
    url = improve_tool.issue_url("owner/repo", cluster, "x" * 50_000)
    assert url.startswith("https://github.com/owner/repo/issues/new?")
    assert len(url) <= 6000
    assert "improve" in url


@pytest.mark.ci
def test_report_url_never_contains_the_local_bundle_path():
    """Regression: the bundle path embeds the username and must not be published."""
    from jsat._improve._sanitize import verify_clean

    cluster = _seed()
    bundle = improve_tool.write_bundle(cluster, "clean analysis", "", "no_patch", [])
    result = runner.invoke(app, ["improve", "--id", cluster["fingerprint"][:8],
                                 "--report", "--dry-run"])

    assert str(bundle) not in result.output
    assert str(Path.home()) not in result.output.replace("\n", "")
    # And the body that would be posted passes the privacy filter.
    assert verify_clean((bundle / "issue.md").read_text())


@pytest.mark.ci
def test_bundle_withholds_files_failing_the_privacy_filter():
    """AI output is untrusted and is re-verified before being written."""
    cluster = _seed()
    leaky = f"the user's home is {Path.home()} and here is a key AKIAIOSFODNN7EXAMPLE"
    bundle = improve_tool.write_bundle(cluster, leaky, "", "no_patch", [])

    written = (bundle / "analysis.md").read_text()
    assert "AKIAIOSFODNN7EXAMPLE" not in written
    assert str(Path.home()) not in written
    assert "withheld" in written
