"""jsat.tools.migration — Tool 8: Migration Safety Validator."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from jsat.tools import BaseTool

_LOCK_TYPES: dict[str, tuple[str, int]] = {
    "CREATE INDEX CONCURRENTLY": ("none", 200_000),
    "CREATE INDEX": ("ShareLock", 500_000),
    "ALTER TABLE ADD COLUMN": ("metadata", 300_000),
    "ALTER TABLE ALTER COLUMN": ("AccessExclusiveLock", 60_000),
    "ALTER TABLE RENAME": ("AccessExclusiveLock", 1_000_000),
    "DROP TABLE": ("AccessExclusiveLock", 2_000_000),
    "DROP COLUMN": ("metadata", 400_000),
    "CREATE TABLE": ("none", 1_000_000),
    "CREATE UNIQUE": ("ShareRowExclusiveLock", 200_000),
}
_DANGEROUS = frozenset({"AccessExclusiveLock", "ShareRowExclusiveLock"})
_SAFE_ALTS = {
    "CREATE INDEX": "Use CREATE INDEX CONCURRENTLY to avoid locking reads.",
    "ALTER TABLE ALTER COLUMN": "Add new column, back-fill, rename — avoids table rewrite.",
    "DROP TABLE": "Ensure all FK references are removed first.",
}
_TABLE_RE = re.compile(r"(?:TABLE|INDEX\s+\w+\s+ON)\s+(\w+)", re.IGNORECASE)


@dataclass
class MigrationOperation:
    sql: str
    operation_type: str
    lock_type: str
    estimated_duration_s: float
    is_dangerous: bool
    safe_alternative: str | None


@dataclass
class MigrationReport:
    operations: list[MigrationOperation]
    risk_level: str
    lock_estimate_seconds: float
    has_rollback: bool
    zero_downtime_guide: str | None
    orm_issues: list[str]
    duration_ms: int


class MigrationTool(BaseTool):
    """Validates SQL migration files for lock risk and reversibility."""

    def run(self, migration_file: Path,
            table_rows: dict[str, int] | None = None) -> MigrationReport:
        import structlog
        log = structlog.get_logger(__name__)
        log.info("migration_start", file=str(migration_file))
        t0 = time.monotonic()
        table_rows = table_rows or {}

        sql = migration_file.read_text(errors="ignore")
        raw_ops = self._parse(sql)
        ops = []
        for stmt, op_type in raw_ops:
            lock, rate = _LOCK_TYPES.get(op_type, ("metadata", 100_000))
            table = self._table_name(stmt)
            rows = table_rows.get(table, 0) if table else 0
            dur = rows / rate if rows else 1.0
            dangerous = lock in _DANGEROUS
            ops.append(MigrationOperation(
                sql=stmt, operation_type=op_type, lock_type=lock,
                estimated_duration_s=dur, is_dangerous=dangerous,
                safe_alternative=_SAFE_ALTS.get(op_type) if dangerous else None,
            ))

        risk = "dangerous" if any(o.is_dangerous for o in ops) else \
               "warning" if any(o.lock_type not in ("none", "metadata") for o in ops) else "safe"
        lock_total = sum(o.estimated_duration_s for o in ops)
        rollback = self._has_rollback(migration_file, sql)
        guide = self._zero_downtime_guide(ops)
        orm_issues = self._detect_orm_issues(migration_file, sql)
        duration_ms = round((time.monotonic() - t0) * 1000)

        log.info("migration_orm_issues", count=len(orm_issues))
        log.info("migration_done", risk=risk, lock_s=round(lock_total, 2),
                 has_rollback=rollback, duration_ms=duration_ms)
        return MigrationReport(operations=ops, risk_level=risk,
                               lock_estimate_seconds=round(lock_total, 2),
                               has_rollback=rollback, zero_downtime_guide=guide,
                               orm_issues=orm_issues, duration_ms=duration_ms)

    def _parse(self, sql: str) -> list[tuple[str, str]]:
        cleaned = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
        stmts = [s.strip() for s in cleaned.split(";") if s.strip()]
        results = []
        for stmt in stmts:
            op = self._detect_op_type(stmt)
            results.append((stmt, op))
        return results

    def _detect_op_type(self, sql: str) -> str:
        """Detect the SQL operation type, handling table names between keywords.

        e.g. 'ALTER TABLE orders ALTER COLUMN' → 'ALTER TABLE ALTER COLUMN'
             'CREATE INDEX CONCURRENTLY idx ON t(c)' → 'CREATE INDEX CONCURRENTLY'
        """
        norm = " ".join(sql.upper().split())

        # Direct prefix match (works for CREATE INDEX CONCURRENTLY, DROP TABLE, etc.)
        for key in sorted(_LOCK_TYPES, key=len, reverse=True):
            if norm.startswith(key):
                return key

        # ALTER TABLE <tablename> <action> — strip the table name and retry
        # e.g. "ALTER TABLE orders ALTER COLUMN" → "ALTER TABLE ALTER COLUMN"
        m = re.match(r"^(ALTER\s+TABLE)\s+\w+\s+(.+)", norm)
        if m:
            without_table = f"ALTER TABLE {m.group(2)}"
            for key in sorted(_LOCK_TYPES, key=len, reverse=True):
                if without_table.startswith(key):
                    return key

        # CREATE INDEX <name> ON — strip the index name and retry
        # e.g. "CREATE INDEX idx ON" → "CREATE INDEX"
        m2 = re.match(r"^(CREATE\s+(?:UNIQUE\s+)?INDEX)\s+(?:CONCURRENTLY\s+)?\w+\s+", norm)
        if m2:
            prefix = m2.group(0).rstrip()
            # check if CONCURRENTLY is in the original
            if "CONCURRENTLY" in prefix:
                return "CREATE INDEX CONCURRENTLY"
            if "UNIQUE" in prefix:
                return "CREATE UNIQUE"
            return "CREATE INDEX"

        words = norm.split()
        return " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else "UNKNOWN")

    def _table_name(self, sql: str) -> str | None:
        m = _TABLE_RE.search(sql)
        return m.group(1).lower() if m else None

    def _has_rollback(self, f: Path, sql: str) -> bool:
        if re.search(r"--\s*DOWN\b", sql, re.IGNORECASE):
            return True
        try:
            for sib in f.parent.iterdir():
                if sib != f and "down" in sib.name.lower():
                    return True
        except Exception:
            pass
        return False

    def _detect_orm_issues(self, migration_file: Path, sql: str) -> list[str]:
        issues: list[str] = []

        # Django migration: check atomic = False for long operations
        is_django = (migration_file.parent.name == "migrations"
                     and migration_file.suffix == ".py")
        if is_django:
            try:
                content = migration_file.read_text(errors="ignore")
                has_long_op = any(
                    kw in sql.upper()
                    for kw in ("CREATE INDEX", "ALTER TABLE", "DROP TABLE", "TRUNCATE")
                )
                if has_long_op and "atomic = False" not in content:
                    issues.append(
                        "Django migration: set atomic = False for long-running operations "
                        "to avoid holding a full transaction lock during migration."
                    )
            except Exception:
                pass

        # Multiple locking operations in one migration
        raw_ops = self._parse(sql)
        dangerous = [op for _, op in raw_ops if op in ("ALTER TABLE ALTER COLUMN", "CREATE UNIQUE", "DROP TABLE")]  # noqa: E501
        if len(dangerous) > 1:
            issues.append(
                f"{len(dangerous)} locking operations in a single migration — "
                "consider splitting into separate migrations to reduce downtime risk."
            )

        # FK without accompanying index
        if (re.search(r"\bREFERENCES\b", sql, re.IGNORECASE)
                and not re.search(r"\bCREATE\s+INDEX\b", sql, re.IGNORECASE)):
            issues.append(
                "Foreign key reference detected without a corresponding index — "
                "add an index on the FK column to avoid sequential scans."
            )

        return issues

    def _zero_downtime_guide(self, ops: list[MigrationOperation]) -> str | None:
        dangerous = [o for o in ops if o.is_dangerous]
        if not dangerous:
            return None
        lines = ["# Zero-Downtime Migration Guide", ""]
        for i, op in enumerate(dangerous, 1):
            lines.append(f"## {i}. `{op.operation_type}` — lock: `{op.lock_type}`")
            if op.safe_alternative:
                lines.append(f"**Recommendation:** {op.safe_alternative}")
            lines.append("")
        return "\n".join(lines)
