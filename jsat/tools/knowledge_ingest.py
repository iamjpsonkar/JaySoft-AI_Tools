"""jsat.tools.knowledge_ingest — Standalone ingestion helper for common knowledge sources.

Scans repositories for well-known knowledge files and converts them into
structured entries suitable for KnowledgeTool.add().

Public API:
    scan_repo(repo_path)         -> list[IngestRecord]
    ingest_claude_md(path)       -> list[IngestRecord]
    ingest_adr(path)             -> list[IngestRecord]
    ingest_markdown(path)        -> list[IngestRecord]

An IngestRecord is a (text, category) pair ready to pass to KnowledgeTool.add().
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass
class IngestRecord:
    """A single knowledge entry ready to be added to KnowledgeTool."""
    text: str
    category: str
    source_path: str
    title: str = ""

    def __post_init__(self) -> None:
        # Basic sanity: trim leading/trailing whitespace
        self.text = self.text.strip()


# ── Section parsers ───────────────────────────────────────────────────────────

def ingest_claude_md(path: Path) -> list[IngestRecord]:
    """Parse a CLAUDE.md file into structured IngestRecords.

    CLAUDE.md typically has H1/H2 sections such as:
        # Overview
        # Rules
        ## Logging
        ## Secrets
        # Working directories
    Each top-level section becomes one IngestRecord in the 'claude_md' category.
    """
    import structlog
    log = structlog.get_logger(__name__)

    path = Path(path)
    if not path.exists():
        log.warning("ingest_claude_md_missing", path=str(path))
        return []

    log.info("ingest_claude_md_start", path=str(path))
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        log.error("ingest_claude_md_read_error", path=str(path), error=str(exc))
        return []

    records: list[IngestRecord] = []
    source = str(path)

    # Pull the overall CLAUDE.md as a single entry first (for holistic queries)
    records.append(IngestRecord(
        text=text,
        category="claude_md",
        source_path=source,
        title="CLAUDE.md (full)",
    ))

    # Also split by H2 sections for granular retrieval
    for section_text, heading in _split_headings(text, max_level=2):
        if len(section_text.strip()) < 30:
            continue
        records.append(IngestRecord(
            text=section_text,
            category="claude_md",
            source_path=source,
            title=heading.strip("# ").strip(),
        ))

    log.info("ingest_claude_md_done", path=str(path), records=len(records))
    return records


def ingest_adr(path: Path) -> list[IngestRecord]:
    """Parse an Architecture Decision Record (ADR) markdown file.

    Standard ADR format (Nygard / MADR):
        # ADR-0001: Title
        ## Status
        ## Context
        ## Decision
        ## Consequences
        ## Alternatives Considered

    Returns a list with typically 1–6 IngestRecords:
      - one for the full ADR (category='adr')
      - one per section (category='adr_section')
    """
    import structlog
    log = structlog.get_logger(__name__)

    path = Path(path)
    if not path.exists():
        log.warning("ingest_adr_missing", path=str(path))
        return []

    log.info("ingest_adr_start", path=str(path))
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        log.error("ingest_adr_read_error", path=str(path), error=str(exc))
        return []

    records: list[IngestRecord] = []
    source = str(path)

    # Extract ADR title from first H1
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    adr_title = title_match.group(1).strip() if title_match else path.stem

    # Extract ADR number if present in file name or title (e.g. "adr-0012" or "ADR-0012:")
    adr_num_match = re.search(r"\b(\d{3,4})\b", path.stem + " " + adr_title)
    adr_num = adr_num_match.group(1) if adr_num_match else ""

    # Full ADR as single entry
    records.append(IngestRecord(
        text=text,
        category="adr",
        source_path=source,
        title=adr_title,
    ))

    # Standard ADR sections: extract and store individually
    adr_sections = ["status", "context", "decision", "consequences",
                    "alternatives", "rationale", "references"]
    for section_text, heading in _split_headings(text, max_level=2):
        if len(section_text.strip()) < 20:
            continue
        heading_lower = heading.strip("# ").strip().lower()
        # Tag section-level records
        section_cat = "adr_section"
        if any(s in heading_lower for s in adr_sections):
            section_cat = f"adr_{heading_lower.split()[0]}"
        entry_title = (
            f"ADR-{adr_num}: {adr_title} — {heading.strip('# ').strip()}"
            if adr_num
            else f"{adr_title} — {heading.strip('# ').strip()}"
        )
        records.append(IngestRecord(
            text=section_text,
            category=section_cat,
            source_path=source,
            title=entry_title,
        ))

    log.info("ingest_adr_done", path=str(path), adr_title=adr_title, records=len(records))
    return records


def ingest_markdown(path: Path, category: str = "general") -> list[IngestRecord]:
    """Generic markdown ingestion: split by H1/H2 headings.

    Used for runbooks, incident reports, Confluence exports, etc.
    """
    import structlog
    log = structlog.get_logger(__name__)

    path = Path(path)
    if not path.exists():
        log.warning("ingest_markdown_missing", path=str(path))
        return []

    log.info("ingest_markdown_start", path=str(path), category=category)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        log.error("ingest_markdown_read_error", path=str(path), error=str(exc))
        return []

    records: list[IngestRecord] = []
    source = str(path)

    # Always include the full document
    records.append(IngestRecord(text=text, category=category,
                                source_path=source, title=path.stem))

    # Plus each section
    for section_text, heading in _split_headings(text, max_level=2):
        if len(section_text.strip()) < 30:
            continue
        records.append(IngestRecord(
            text=section_text,
            category=category,
            source_path=source,
            title=heading.strip("# ").strip(),
        ))

    log.info("ingest_markdown_done", path=str(path), records=len(records))
    return records


# ── Repository scanner ────────────────────────────────────────────────────────

def scan_repo(repo_path: Path) -> list[IngestRecord]:
    """Scan a repository directory for known knowledge sources.

    Looks for:
    - CLAUDE.md (and .claude/CLAUDE.md)
    - docs/decisions/*.md
    - docs/adr/*.md, docs/adrs/*.md
    - docs/runbooks/*.md
    - docs/incidents/*.md, postmortems/*.md
    - docs/**/*.md (generic)

    Returns all IngestRecords found, deduplicated by source path.
    """
    import structlog
    log = structlog.get_logger(__name__)

    repo_path = Path(repo_path)
    if not repo_path.exists():
        log.warning("scan_repo_missing", path=str(repo_path))
        return []

    log.info("scan_repo_start", path=str(repo_path))
    seen_paths: set[str] = set()
    all_records: list[IngestRecord] = []

    def _add(records: list[IngestRecord]) -> None:
        for r in records:
            if r.source_path not in seen_paths and r.text:
                seen_paths.add(r.source_path)
                all_records.append(r)

    # ── 1. CLAUDE.md files ──────────────────────────────────────────────────
    for pattern in ("CLAUDE.md", ".claude/CLAUDE.md", "**/CLAUDE.md"):
        for p in repo_path.glob(pattern):
            _add(ingest_claude_md(p))

    # ── 2. ADR directories ──────────────────────────────────────────────────
    adr_patterns = [
        "docs/adr/*.md",
        "docs/adrs/*.md",
        "docs/decisions/*.md",
        "architecture/decisions/*.md",
        "adr/*.md",
        "ADR/*.md",
    ]
    for pattern in adr_patterns:
        for p in repo_path.glob(pattern):
            _add(ingest_adr(p))

    # ── 3. Runbooks ─────────────────────────────────────────────────────────
    runbook_patterns = [
        "docs/runbooks/*.md",
        "runbooks/*.md",
        "docs/playbooks/*.md",
    ]
    for pattern in runbook_patterns:
        for p in repo_path.glob(pattern):
            _add(ingest_markdown(p, category="runbook"))

    # ── 4. Incident / postmortem reports ────────────────────────────────────
    incident_patterns = [
        "docs/incidents/*.md",
        "postmortems/*.md",
        "incidents/*.md",
        "docs/postmortems/*.md",
    ]
    for pattern in incident_patterns:
        for p in repo_path.glob(pattern):
            _add(ingest_markdown(p, category="incident"))

    # ── 5. Generic docs/**/*.md (not yet ingested) ──────────────────────────
    for p in repo_path.glob("docs/**/*.md"):
        if str(p) not in seen_paths:
            cat = _guess_doc_category(p)
            _add(ingest_markdown(p, category=cat))

    log.info("scan_repo_done", path=str(repo_path), total_records=len(all_records),
             unique_files=len(seen_paths))
    return all_records


# ── Helpers ───────────────────────────────────────────────────────────────────

def _split_headings(text: str, max_level: int = 2) -> Iterator[tuple[str, str]]:
    """Yield (section_text, heading) pairs split at markdown headings up to max_level."""
    pattern = r"(?m)^(#{1," + str(max_level) + r"} .+)$"
    parts = re.split(pattern, text)
    heading = ""
    for part in parts:
        if re.match(r"^#{1," + str(max_level) + r"} ", part):
            heading = part
        else:
            combined = f"{heading}\n{part}".strip() if heading else part.strip()
            if combined:
                yield combined, heading


def _guess_doc_category(path: Path) -> str:
    """Infer category from path components.

    Priority order: incident/postmortem > runbook > adr/decision > api > changelog > general.
    Incident is checked first because a file like ``postmortems/2024-01.md`` would
    otherwise match the ADR date-prefix heuristic.
    """
    name = path.name.lower()
    parent = str(path.parent).lower()

    # Incident / postmortem — checked before ADR to avoid false positives on date prefixes
    if "incident" in parent or "postmortem" in parent or "incident" in name or "postmortem" in name:
        return "incident"
    if "runbook" in parent or "runbook" in name or "playbook" in name:
        return "runbook"
    # ADR: explicit directory name or conventional date-prefix (only in adr/decision dirs)
    if "adr" in parent or "decision" in parent:
        return "adr"
    # Date-prefix heuristic only when not already classified as incident
    if re.match(r"\d{4}-", name) and not any(w in parent for w in ("incident", "postmortem")):
        return "adr"
    if "changelog" in name or "change" in name:
        return "changelog"
    if "api" in parent or "api" in name:
        return "api_doc"
    return "general"
