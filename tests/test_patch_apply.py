"""Tests for jsat.tools._patch — diff parsing, path safety, and application."""
from __future__ import annotations

import pytest

from jsat.tools._patch import (
    PatchError,
    apply_hunks,
    apply_patch,
    parse_patch,
    validate_patch,
)

_ORIGINAL = "def f():\n    return 1\n\n\ndef g():\n    return 2\n"

_GOOD_PATCH = """--- a/jsat/demo.py
+++ b/jsat/demo.py
@@ -1,2 +1,2 @@
 def f():
-    return 1
+    return 42
"""


@pytest.mark.ci
def test_parse_extracts_path_and_hunks():
    patches = parse_patch(_GOOD_PATCH)
    assert len(patches) == 1
    assert patches[0].path == "jsat/demo.py"
    assert len(patches[0].hunks) == 1


@pytest.mark.ci
def test_apply_hunks_replaces_line():
    out = apply_hunks(_ORIGINAL, parse_patch(_GOOD_PATCH)[0].hunks)
    assert "return 42" in out
    assert "return 1" not in out
    assert "def g():" in out  # untouched tail preserved


@pytest.mark.ci
def test_context_mismatch_is_rejected():
    with pytest.raises(PatchError, match="context mismatch"):
        apply_hunks("def f():\n    return 999\n", parse_patch(_GOOD_PATCH)[0].hunks)


# ── path safety: the sandbox-escape guards ────────────────────────────────────

@pytest.mark.ci
@pytest.mark.parametrize("target", [
    "../../etc/passwd",
    "/etc/passwd",
    "~/.ssh/id_rsa",
    "docs/readme.md",          # outside the jsat package
    "jsat/../../../etc/shadow",
])
def test_unsafe_paths_are_rejected(target):
    patch = f"--- a/{target}\n+++ b/{target}\n@@ -1,1 +1,1 @@\n-a\n+b\n"
    with pytest.raises(PatchError):
        parse_patch(patch)


@pytest.mark.ci
def test_patch_without_hunks_is_rejected():
    with pytest.raises(PatchError, match="no hunks"):
        parse_patch("--- a/jsat/x.py\n+++ b/jsat/x.py\n")


@pytest.mark.ci
def test_empty_patch_is_rejected():
    with pytest.raises(PatchError, match="no file headers"):
        parse_patch("this is prose, not a diff")


# ── application against a real tree ───────────────────────────────────────────

@pytest.mark.ci
def test_apply_patch_writes_file(tmp_path):
    target = tmp_path / "jsat" / "demo.py"
    target.parent.mkdir(parents=True)
    target.write_text(_ORIGINAL)

    changed = apply_patch(_GOOD_PATCH, tmp_path)
    assert changed == ["jsat/demo.py"]
    assert "return 42" in target.read_text()


@pytest.mark.ci
def test_apply_patch_rejects_syntax_breaking_result(tmp_path):
    target = tmp_path / "jsat" / "demo.py"
    target.parent.mkdir(parents=True)
    target.write_text(_ORIGINAL)

    broken = (
        "--- a/jsat/demo.py\n+++ b/jsat/demo.py\n"
        "@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return (((\n"
    )
    with pytest.raises(PatchError, match="not valid Python"):
        apply_patch(broken, tmp_path)
    assert "return 1" in target.read_text()  # unchanged on failure


@pytest.mark.ci
def test_apply_patch_rejects_missing_file(tmp_path):
    with pytest.raises(PatchError, match="does not exist"):
        apply_patch(_GOOD_PATCH, tmp_path)


# ── validate_patch never touches the source tree ──────────────────────────────

@pytest.mark.ci
def test_validate_patch_leaves_source_untouched(tmp_path):
    source = tmp_path / "pkg"
    source.mkdir()
    (source / "demo.py").write_text(_ORIGINAL)

    ok, message, changed = validate_patch(_GOOD_PATCH, source)
    assert ok is True, message
    assert changed == ["jsat/demo.py"]
    # The real file must be byte-identical — validation happens in a temp copy.
    assert (source / "demo.py").read_text() == _ORIGINAL


@pytest.mark.ci
def test_validate_patch_reports_failure_without_raising(tmp_path):
    source = tmp_path / "pkg"
    source.mkdir()
    (source / "demo.py").write_text("totally different content\n")

    ok, message, _ = validate_patch(_GOOD_PATCH, source)
    assert ok is False
    assert "context mismatch" in message
