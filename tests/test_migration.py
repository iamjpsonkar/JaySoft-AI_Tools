"""Tests for jsat.tools.migration. CI-safe: writes temp .sql files."""
from __future__ import annotations

import pytest

from jsat._models import JSATConfig
from jsat.tools.migration import MigrationTool


class NoOpGraph:
    def node_count(self): return 0
    def edge_count(self): return 0
    def bfs(self, *a, **kw): return iter([])
    def query(self, *a, **kw): return []
    def get_node(self, *a): return None
    def outgoing_edges(self, *a): return []
    def add_node(self, *a, **kw): pass
    def add_edge(self, *a, **kw): pass
    def close(self): pass

@pytest.fixture
def tool(): return MigrationTool(graph=NoOpGraph(), cfg=JSATConfig(), ai=None)

def _sql(tmp_path, sql, name="m.sql"):
    p = tmp_path / name
    p.write_text(sql)
    return p

# Risk
@pytest.mark.ci
def test_create_table_safe(tool, tmp_path):
    assert tool.run(_sql(tmp_path, "CREATE TABLE foo (id INT PRIMARY KEY);")).risk_level == "safe"
@pytest.mark.ci
def test_alter_column_dangerous(tool, tmp_path):
    sql = _sql(tmp_path, "ALTER TABLE orders ALTER COLUMN status TYPE TEXT;")
    assert tool.run(sql).risk_level == "dangerous"
@pytest.mark.ci
def test_drop_table_dangerous(tool, tmp_path):
    assert tool.run(_sql(tmp_path, "DROP TABLE legacy;")).risk_level == "dangerous"

# Lock types
@pytest.mark.ci
def test_create_index_concurrent_lock_none(tool, tmp_path):
    r = tool.run(_sql(tmp_path, "CREATE INDEX CONCURRENTLY idx ON orders(status);"))
    assert r.operations[0].lock_type == "none"
@pytest.mark.ci
def test_alter_column_exclusive_lock(tool, tmp_path):
    r = tool.run(_sql(tmp_path, "ALTER TABLE foo ALTER COLUMN x TYPE TEXT;"))
    assert any(o.lock_type == "AccessExclusiveLock" for o in r.operations)
@pytest.mark.ci
def test_create_table_lock_none(tool, tmp_path):
    r = tool.run(_sql(tmp_path, "CREATE TABLE t (id SERIAL PRIMARY KEY);"))
    assert r.operations[0].lock_type == "none"

# Lock duration
@pytest.mark.ci
def test_lock_estimate_non_negative(tool, tmp_path):
    sql = _sql(tmp_path, "ALTER TABLE t ALTER COLUMN x TYPE TEXT;")
    assert tool.run(sql).lock_estimate_seconds >= 0
@pytest.mark.ci
def test_lock_scales_with_rows(tool, tmp_path):
    sql = "ALTER TABLE orders ALTER COLUMN status TYPE TEXT;"
    small = tool.run(_sql(tmp_path, sql, "s.sql"), table_rows={"orders": 1_000})
    large = tool.run(_sql(tmp_path, sql, "l.sql"), table_rows={"orders": 1_000_000})
    assert large.lock_estimate_seconds > small.lock_estimate_seconds

# Rollback
@pytest.mark.ci
def test_rollback_inline_down(tool, tmp_path):
    sql = "ALTER TABLE t ADD COLUMN x BOOL;\n-- DOWN\nALTER TABLE t DROP COLUMN x;"
    assert tool.run(_sql(tmp_path, sql)).has_rollback is True
@pytest.mark.ci
def test_no_rollback(tool, tmp_path):
    assert tool.run(_sql(tmp_path, "CREATE TABLE logs (id SERIAL);")).has_rollback is False
@pytest.mark.ci
def test_rollback_sibling_file(tool, tmp_path):
    up = _sql(tmp_path, "CREATE TABLE foo (id INT);", "001_up.sql")
    (tmp_path/"001_down.sql").write_text("DROP TABLE foo;")
    assert tool.run(up).has_rollback is True

# Zero-downtime guide
@pytest.mark.ci
def test_guide_for_dangerous(tool, tmp_path):
    r = tool.run(_sql(tmp_path, "ALTER TABLE orders ALTER COLUMN status TYPE TEXT;"))
    assert r.zero_downtime_guide and "Recommendation" in r.zero_downtime_guide
@pytest.mark.ci
def test_no_guide_for_safe(tool, tmp_path):
    r = tool.run(_sql(tmp_path, "CREATE TABLE safe_tbl (id INT PRIMARY KEY);"))
    assert r.zero_downtime_guide is None or not r.zero_downtime_guide.strip()

# Operations
@pytest.mark.ci
def test_one_statement_one_op(tool, tmp_path):
    assert len(tool.run(_sql(tmp_path, "CREATE TABLE foo (id INT);")).operations) == 1
@pytest.mark.ci
def test_three_statements_three_ops(tool, tmp_path):
    sql = "CREATE TABLE a(id INT);\nCREATE TABLE b(id INT);\nCREATE TABLE c(id INT);"
    assert len(tool.run(_sql(tmp_path, sql)).operations) == 3
@pytest.mark.ci
def test_block_comment_ignored(tool, tmp_path):
    assert len(tool.run(_sql(tmp_path, "/* cmt */ CREATE TABLE x (id INT);")).operations) == 1

# ADD COLUMN NOT NULL DEFAULT reclassification (full-table-rewrite class, not metadata)
@pytest.mark.ci
def test_add_column_not_null_default_is_high_risk_lock(tool, tmp_path):
    sql = _sql(tmp_path, "ALTER TABLE foo ADD COLUMN bar INT NOT NULL DEFAULT 0;")
    r = tool.run(sql)
    op = r.operations[0]
    assert op.lock_type == "AccessExclusiveLock"
    assert op.is_dangerous is True
    assert r.risk_level == "dangerous"

@pytest.mark.ci
def test_add_column_nullable_stays_metadata_safe(tool, tmp_path):
    sql = _sql(tmp_path, "ALTER TABLE foo ADD COLUMN bar INT;")
    r = tool.run(sql)
    op = r.operations[0]
    assert op.lock_type == "metadata"
    assert op.is_dangerous is False

@pytest.mark.ci
def test_add_column_default_without_not_null_stays_metadata(tool, tmp_path):
    # DEFAULT alone (nullable) does not force a full-table rewrite.
    sql = _sql(tmp_path, "ALTER TABLE foo ADD COLUMN bar INT DEFAULT 0;")
    r = tool.run(sql)
    assert r.operations[0].lock_type == "metadata"

# Table name detection
@pytest.mark.ci
def test_table_name_alter(tool):
    assert tool._table_name("ALTER TABLE orders ALTER COLUMN x TYPE TEXT") == "orders"
@pytest.mark.ci
def test_table_name_create(tool):
    assert tool._table_name("CREATE TABLE payments (id SERIAL)") == "payments"
@pytest.mark.ci
def test_table_name_drop(tool):
    assert tool._table_name("DROP TABLE legacy_orders") == "legacy_orders"
@pytest.mark.ci
def test_table_name_none(tool): assert tool._table_name("SELECT 1") is None

# Meta
@pytest.mark.ci
def test_duration_non_negative(tool, tmp_path):
    assert tool.run(_sql(tmp_path, "CREATE TABLE t(id INT);")).duration_ms >= 0
@pytest.mark.ci
def test_orm_issues_is_list(tool, tmp_path):
    assert isinstance(tool.run(_sql(tmp_path, "CREATE TABLE t(id INT);")).orm_issues, list)
@pytest.mark.ci
def test_dangerous_has_safe_alt(tool, tmp_path):
    sql = _sql(tmp_path, "ALTER TABLE t ALTER COLUMN x TYPE TEXT;")
    ops = [o for o in tool.run(sql).operations if o.is_dangerous]
    assert all(o.safe_alternative for o in ops)
