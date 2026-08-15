"""jsat._sessions — read/write the session files JSAT skills use to resume work.

Until now the session format documented in the README (and instructed in every
skill's markdown) existed only as prose telling the *AI* to hand-write the file.
That meant no two skills produced quite the same thing and `--continue` had
nothing reliable to read. This module implements that format once, so skills,
the CLI, and `--continue` all agree.

The on-disk format is unchanged and stays human-editable:

    ---
    skill: magic
    task: add retry logic
    created: 2026-08-15T09:00:00Z
    status: in_progress
    ---

    ## Steps
    - [x] status (finding: 1307 nodes)
    - [ ] blast-radius

    ## Findings
    **status:** 1307 nodes, 5668 edges

stdlib-only, and every parse is tolerant: a hand-edited or partially written
file still loads rather than raising.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_STATUSES = ("in_progress", "completed", "abandoned")

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_STEP_RE = re.compile(r"^- \[( |x)\] (.+)$", re.MULTILINE)


def sessions_dir() -> Path:
    """Where session files live.

    Flat and repo-agnostic (``~/.jsat/sessions/``) to match what the skills and
    README already document — a session is about a task, not about one checkout.
    ``$JSAT_SESSIONS_DIR`` overrides, which is what the tests use.
    """
    override = os.environ.get("JSAT_SESSIONS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".jsat" / "sessions"


def slugify(text: str, words: int = 4) -> str:
    """First few words, lowercased and hyphenated — matches the documented naming."""
    cleaned = re.sub(r"[^a-z0-9\s-]", "", text.lower())
    parts = [p for p in cleaned.split() if p][:words]
    return "-".join(parts) or "session"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M", time.localtime())


@dataclass
class Step:
    name: str
    done: bool = False
    finding: str = ""

    def render(self) -> str:
        box = "x" if self.done else " "
        suffix = f" (finding: {self.finding})" if self.done and self.finding else ""
        return f"- [{box}] {self.name}{suffix}"


@dataclass
class Session:
    skill: str
    task: str
    path: Path
    status: str = "in_progress"
    created: str = field(default_factory=_now_iso)
    steps: list[Step] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    # ── derived ───────────────────────────────────────────────────────────────

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.steps if s.done)

    @property
    def next_step(self) -> Step | None:
        """First incomplete step — where ``--continue`` resumes."""
        return next((s for s in self.steps if not s.done), None)

    # ── mutation ──────────────────────────────────────────────────────────────

    def complete_step(self, name: str, finding: str = "") -> bool:
        """Mark a step done. Returns False if no such step."""
        for step in self.steps:
            if step.name == name and not step.done:
                step.done = True
                step.finding = finding.strip()
                if finding.strip():
                    self.findings.append(f"**{name}:** {finding.strip()}")
                self.save()
                return True
        return False

    def finish(self, status: str = "completed") -> None:
        self.status = status if status in SCHEMA_STATUSES else "completed"
        self.save()

    # ── persistence ───────────────────────────────────────────────────────────

    def render(self) -> str:
        steps = "\n".join(s.render() for s in self.steps) or "(no steps)"
        findings = "\n".join(self.findings) or "(populated as steps complete)"
        return (
            "---\n"
            f"skill: {self.skill}\n"
            f"task: {self.task}\n"
            f"created: {self.created}\n"
            f"status: {self.status}\n"
            "---\n\n"
            "## Steps\n"
            f"{steps}\n\n"
            "## Findings\n"
            f"{findings}\n"
        )

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".md.tmp")
        tmp.write_text(self.render(), encoding="utf-8")
        os.replace(tmp, self.path)
        return self.path


def create(skill: str, task: str, steps: list[str] | None = None) -> Session:
    """Start a session file named ``<skill>-<slug>-<YYYYMMDD-HHMM>.md``."""
    path = sessions_dir() / f"{skill}-{slugify(task)}-{_stamp()}.md"
    session = Session(
        skill=skill, task=task, path=path,
        steps=[Step(name=s) for s in (steps or [])],
    )
    session.save()
    return session


def load(path: str | Path) -> Session | None:
    """Parse a session file. Returns None if unreadable — never raises."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return None

    meta: dict[str, str] = {}
    match = _FRONTMATTER_RE.match(text)
    if match:
        for line in match.group(1).splitlines():
            key, _, value = line.partition(":")
            if _:
                meta[key.strip()] = value.strip()

    steps: list[Step] = []
    steps_block = _section(text, "Steps")
    for done, label in _STEP_RE.findall(steps_block):
        name, finding = label, ""
        if " (finding: " in label and label.endswith(")"):
            name, _, rest = label.partition(" (finding: ")
            finding = rest[:-1]
        steps.append(Step(name=name.strip(), done=done == "x", finding=finding))

    findings = [
        ln for ln in _section(text, "Findings").splitlines()
        if ln.strip() and not ln.startswith("(")
    ]

    return Session(
        skill=meta.get("skill", "unknown"),
        task=meta.get("task", ""),
        path=p,
        status=meta.get("status", "in_progress"),
        created=meta.get("created", ""),
        steps=steps,
        findings=findings,
    )


def _section(text: str, heading: str) -> str:
    """Body of a ``## <heading>`` section, up to the next ``##``."""
    marker = f"## {heading}"
    if marker not in text:
        return ""
    body = text.split(marker, 1)[1]
    return body.split("\n## ", 1)[0]


def list_sessions(
    skill: str | None = None, status: str | None = None, limit: int = 50
) -> list[Session]:
    """Sessions newest first, optionally filtered by skill and/or status."""
    root = sessions_dir()
    if not root.exists():
        return []
    out: list[Session] = []
    for path in sorted(root.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        if "-actions-" in path.name:
            continue  # actions files are a separate artifact
        session = load(path)
        if session is None:
            continue
        if skill and session.skill != skill:
            continue
        if status and session.status != status:
            continue
        out.append(session)
        if len(out) >= limit:
            break
    return out


def latest(skill: str | None = None, status: str = "in_progress") -> Session | None:
    """Most recent matching session — what ``--continue`` resumes."""
    found = list_sessions(skill=skill, status=status, limit=1)
    return found[0] if found else None


def prune(keep: int = 50, completed_only: bool = True) -> int:
    """Delete old session files, newest ``keep`` retained. Returns count removed."""
    root = sessions_dir()
    if not root.exists():
        return 0
    candidates = sorted(root.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for path in candidates[keep:]:
        if completed_only:
            session = load(path)
            if session is not None and session.status == "in_progress":
                continue
        try:
            path.unlink()
            removed += 1
        except Exception:
            pass
    return removed
