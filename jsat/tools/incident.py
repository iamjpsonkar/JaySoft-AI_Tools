"""jsat.tools.incident — Tool 7: Incident Investigation Helper."""
from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

from jsat._call_context import checkpoint
from jsat.tools import BaseTool

if TYPE_CHECKING:
    from jsat._models import IncidentReport


class IncidentTool(BaseTool):
    """Scores recent git commits as root-cause hypotheses for an incident."""

    # Scoring weights (from plan.md Section E3)
    W_RECENCY   = 0.35
    W_BLAST     = 0.25
    W_FREQUENCY = 0.15
    W_PATTERN   = 0.25
    LAMBDA      = 0.1    # recency decay per hour
    MAX_BLAST   = 50
    MAX_FREQ    = 10

    def run(
        self,
        description: str,
        since: str = "72h",
        services: list[str] | None = None,
    ) -> IncidentReport:
        import structlog

        from jsat._models import Hypothesis, IncidentReport

        log = structlog.get_logger(__name__)
        log.info("incident_start", description=description[:80], since=since,
                 services=services)
        t0 = time.monotonic()

        checkpoint(f"incident: fetching git commits from last {since}")
        commits = self._recent_commits(since)
        log.info("incident_commits_found", count=len(commits))
        checkpoint(f"incident: found {len(commits)} commit(s) in range")

        capped = commits[:20]
        checkpoint(f"incident: scoring {len(capped)} candidate commit(s)")
        hypotheses: list[Hypothesis] = []
        for i, commit in enumerate(capped, 1):
            if i == 1 or i % 5 == 0:
                checkpoint(f"incident: scoring commit {i}/{len(capped)} — {commit['hash'][:8]} {commit['summary'][:50]}")
            score = self._score(commit, description, commits)
            hypotheses.append(Hypothesis(
                score=round(score, 3),
                commit_hash=commit["hash"],
                commit_summary=commit["summary"],
                author=commit["author"],
                timestamp=commit["timestamp"],
                evidence=self._evidence(commit, description),
                recommended_action=(
                    f"Investigate commit {commit['hash'][:8]}: {commit['summary'][:60]}"
                ),
            ))

        checkpoint(f"incident: sorting {len(hypotheses)} hypotheses by score")
        hypotheses.sort(key=lambda h: h.score, reverse=True)
        if hypotheses:
            top = hypotheses[0]
            checkpoint(
                f"incident: top hypothesis — {top.commit_hash[:8]} "
                f"score={top.score:.3f} '{top.commit_summary[:60]}'"
            )

        checkpoint("incident: generating mitigation steps")
        duration_ms = round((time.monotonic() - t0) * 1000)
        log.info("incident_done", hypotheses=len(hypotheses), duration_ms=duration_ms)
        top_score = f"{hypotheses[0].score:.3f}" if hypotheses else "n/a"
        checkpoint(
            f"incident: DONE — {len(hypotheses)} hypotheses ranked, "
            f"top score={top_score}, {duration_ms}ms"
        )

        return IncidentReport(
            description=description,
            hypotheses=hypotheses[:5],
            mitigation_steps=self._mitigations(hypotheses[:3]),
            duration_ms=duration_ms,
        )

    def _recent_commits(self, since: str) -> list[dict]:
        try:
            import git
            repo = git.Repo(".", search_parent_directories=True)
            hours = self._parse_hours(since)
            from datetime import datetime, timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            commits = []
            for c in repo.iter_commits(since=cutoff.isoformat()):
                commits.append({
                    "hash": c.hexsha,
                    "summary": c.summary,
                    "author": str(c.author),
                    "timestamp": c.authored_datetime.isoformat(),
                    "files": list(c.stats.files.keys()),
                    "authored_datetime": c.authored_datetime,
                })
            return commits
        except Exception as e:
            import structlog
            structlog.get_logger(__name__).warning("incident_git_error", error=str(e))
            return []

    def _score(self, commit: dict, description: str, all_commits: list[dict] | None = None) -> float:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        authored = commit.get("authored_datetime", now)
        if hasattr(authored, "tzinfo") and authored.tzinfo is None:
            from datetime import timezone as tz
            authored = authored.replace(tzinfo=tz.utc)
        hours_ago = max(0, (now - authored).total_seconds() / 3600)
        recency = math.exp(-self.LAMBDA * hours_ago)

        # Blast radius: count changed files
        blast = min(len(commit.get("files", [])), self.MAX_BLAST) / self.MAX_BLAST

        # Frequency: fraction of commits by the same author that touch the same files
        freq = self._author_file_frequency(commit, all_commits or [])

        # Pattern: simple keyword overlap
        desc_words = set(description.lower().split())
        summary_words = set(commit["summary"].lower().split())
        overlap = len(desc_words & summary_words)
        pattern = min(overlap / max(len(desc_words), 1), 1.0)

        return (self.W_RECENCY * recency + self.W_BLAST * blast +
                self.W_FREQUENCY * freq + self.W_PATTERN * pattern)

    def _author_file_frequency(self, commit: dict, all_commits: list[dict]) -> float:
        """Fraction of commits by the same author that touch the same files."""
        author = commit.get("author", "")
        changed = set(commit.get("files", []))
        if not author or not changed:
            return 0.1
        overlap_count = sum(
            1 for c in all_commits
            if c.get("author") == author and set(c.get("files", [])) & changed
        )
        return min(overlap_count, self.MAX_FREQ) / self.MAX_FREQ

    def _evidence(self, commit: dict, description: str) -> list[str]:
        ev = [f"Commit {commit['hash'][:8]} by {commit['author']} at {commit['timestamp'][:16]}"]
        files = commit.get("files", [])
        if files:
            ev.append(f"Changed {len(files)} file(s): {', '.join(files[:3])}")
        desc_words = set(description.lower().split())
        summary_words = set(commit["summary"].lower().split())
        matched = desc_words & summary_words
        if matched:
            ev.append(f"Keyword overlap with incident description: {', '.join(sorted(matched)[:5])}")
        return ev

    def _mitigations(self, top: list) -> list[str]:
        if not top:
            return ["No recent commits found — check infrastructure changes"]
        return [
            f"Investigate commit {h.commit_hash[:8]}: {h.commit_summary[:60]}"
            for h in top
        ] + ["Check deployment logs around the incident time",
             "Review config changes in the last 24h"]

    def _parse_hours(self, since: str) -> float:
        since = since.strip().lower()
        if since.endswith("h"):
            return float(since[:-1])
        if since.endswith("d"):
            return float(since[:-1]) * 24
        return 72.0  # default
