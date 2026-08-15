"""jsat.tools._patch — minimal unified-diff parser and applier.

Used by `jsat improve` to check that an AI-generated patch actually applies before
it is written into a bundle. Deliberately pure-Python rather than shelling out to
``git apply``/``patch(1)``: the validation sandbox is a bare temp directory (not a
git repo), ``patch`` is absent on Windows, and a small hunk matcher is directly
unit-testable.

Nothing here writes outside the directory it is handed.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


class PatchError(Exception):
    """Raised when a patch is malformed, unsafe, or does not apply."""


@dataclass
class Hunk:
    old_start: int
    lines: list[str] = field(default_factory=list)   # each prefixed ' ', '-', or '+'


@dataclass
class FilePatch:
    path: str                       # always relative, always under the package root
    hunks: list[Hunk] = field(default_factory=list)


def _strip_prefix(raw: str) -> str:
    """Normalize `a/jsat/x.py` / `b/jsat/x.py` / `jsat/x.py` to `jsat/x.py`."""
    token = raw.strip().split("\t")[0].strip()
    for prefix in ("a/", "b/"):
        if token.startswith(prefix):
            token = token[len(prefix):]
    return token


def _validate_path(path: str) -> str:
    """Reject anything that could escape the package directory."""
    if not path or path in ("/dev/null",):
        raise PatchError(f"invalid patch target: {path!r}")
    if path.startswith("/") or path.startswith("~"):
        raise PatchError(f"absolute paths are not allowed: {path!r}")
    if ".." in Path(path).parts:
        raise PatchError(f"path traversal is not allowed: {path!r}")
    if len(path) > 2 and path[1] == ":":
        raise PatchError(f"absolute paths are not allowed: {path!r}")
    if not path.startswith("jsat/"):
        raise PatchError(f"patch may only touch the jsat package: {path!r}")
    return path


def parse_patch(text: str) -> list[FilePatch]:
    """Parse a unified diff. Raises PatchError on anything malformed or unsafe."""
    files: list[FilePatch] = []
    current: FilePatch | None = None
    hunk: Hunk | None = None

    for line in text.splitlines():
        if line.startswith("--- "):
            hunk = None
            continue
        if line.startswith("+++ "):
            path = _validate_path(_strip_prefix(line[4:]))
            current = FilePatch(path=path)
            files.append(current)
            hunk = None
            continue
        if line.startswith("@@"):
            if current is None:
                raise PatchError("hunk header before any file header")
            hunk = Hunk(old_start=_parse_hunk_header(line))
            current.hunks.append(hunk)
            continue
        if hunk is not None:
            if line.startswith(("+", "-", " ")):
                hunk.lines.append(line)
            elif line == "":
                hunk.lines.append(" ")
            # anything else (e.g. "\\ No newline at end of file") is ignored

    if not files:
        raise PatchError("no file headers found in patch")
    if not any(f.hunks for f in files):
        raise PatchError("patch contains no hunks")
    return files


def _parse_hunk_header(line: str) -> int:
    """`@@ -12,7 +12,9 @@` -> 12 (1-based old start)."""
    try:
        old = line.split("@@")[1].strip().split(" ")[0]      # "-12,7"
        return int(old.lstrip("-").split(",")[0])
    except (IndexError, ValueError) as e:
        raise PatchError(f"malformed hunk header: {line!r}") from e


def apply_hunks(original: str, hunks: list[Hunk]) -> str:
    """Apply hunks to file content, verifying every context and removal line."""
    lines = original.splitlines()
    result: list[str] = []
    cursor = 0     # index into `lines` already consumed

    for hunk in hunks:
        start = max(hunk.old_start - 1, 0)
        if start < cursor:
            raise PatchError("overlapping or out-of-order hunks")
        result.extend(lines[cursor:start])
        cursor = start

        for entry in hunk.lines:
            tag, content = entry[0], entry[1:]
            if tag == "+":
                result.append(content)
                continue
            if cursor >= len(lines):
                raise PatchError("hunk extends past end of file")
            if lines[cursor] != content:
                raise PatchError(
                    f"context mismatch at line {cursor + 1}: "
                    f"expected {content!r}, found {lines[cursor]!r}"
                )
            if tag == " ":
                result.append(content)
            cursor += 1     # both ' ' and '-' consume an original line

    result.extend(lines[cursor:])
    return "\n".join(result) + ("\n" if original.endswith("\n") or original else "")


def apply_patch(patch_text: str, root: Path) -> list[str]:
    """Apply a patch to files under ``root``. Returns the relative paths changed.

    ``root`` must be a sandbox copy — this function is never pointed at an
    installed package. Each patched file must still parse as valid Python.
    """
    root = Path(root).resolve()
    changed: list[str] = []

    for file_patch in parse_patch(patch_text):
        target = (root / file_patch.path).resolve()
        if not str(target).startswith(str(root)):
            raise PatchError(f"patch escapes the sandbox: {file_patch.path}")
        if not target.exists():
            raise PatchError(f"patch targets a file that does not exist: {file_patch.path}")

        original = target.read_text(encoding="utf-8")
        patched = apply_hunks(original, file_patch.hunks)

        if target.suffix == ".py":
            try:
                ast.parse(patched)
            except SyntaxError as e:
                raise PatchError(f"patched {file_patch.path} is not valid Python: {e}") from e

        target.write_text(patched, encoding="utf-8")
        changed.append(file_patch.path)

    return changed


def validate_patch(patch_text: str, source_root: Path) -> tuple[bool, str, list[str]]:
    """Dry-run a patch against a throwaway copy of the files it touches.

    Returns ``(ok, message, changed_paths)``. Never modifies ``source_root``.
    """
    import shutil
    import tempfile

    try:
        file_patches = parse_patch(patch_text)
    except PatchError as e:
        return False, str(e), []

    sandbox = Path(tempfile.mkdtemp(prefix="jsat-improve-"))
    try:
        for file_patch in file_patches:
            src = Path(source_root) / Path(file_patch.path).relative_to("jsat")
            if not src.exists():
                return False, f"unknown file: {file_patch.path}", []
            dest = sandbox / file_patch.path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

        changed = apply_patch(patch_text, sandbox)
        return True, "patch applies cleanly", changed
    except PatchError as e:
        return False, str(e), []
    except Exception as e:  # noqa: BLE001 — validation must never crash the caller
        return False, f"validation error: {e}", []
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
