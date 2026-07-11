"""Migration 23 registration + content guards (P5 source permissions, v2 3-scope)."""
from pathlib import Path

from open_notebook.database.async_migrate import AsyncMigrationManager

MIGRATIONS = Path("open_notebook/database/migrations")


def test_migration_23_registered():
    mgr = AsyncMigrationManager()
    # This branch (feat/auth-mt-p5) has no migration 22 file (it lives on a
    # separate branch) -> 1-21 + 23 = 22 entries registered, numbering gap at 22.
    assert len(mgr.up_migrations) == 22
    assert len(mgr.down_migrations) == 22


def test_migration_23_up_defines_owner_scope_promoted_from_and_search_fns():
    sql = (MIGRATIONS / "23.surrealql").read_text()
    assert "DEFINE FIELD IF NOT EXISTS owner ON TABLE source" in sql
    assert "DEFINE FIELD IF NOT EXISTS scope ON TABLE source" in sql
    assert "DEFINE FIELD IF NOT EXISTS promoted_from ON TABLE source" in sql
    assert "'personal', 'project', 'company'" in sql
    assert "idx_source_scope" in sql
    assert "idx_source_owner" in sql
    # search functions gain the $viewer_source_ids allow-list param
    assert "$viewer_source_ids: array<record<source>>" in sql
    assert sql.count("DEFINE FUNCTION IF NOT EXISTS fn::text_search") == 1
    assert sql.count("DEFINE FUNCTION IF NOT EXISTS fn::vector_search") == 1


def test_migration_23_down_removes_fields_and_restores_legacy_fns():
    sql = (MIGRATIONS / "23_down.surrealql").read_text()
    assert "REMOVE FIELD IF EXISTS scope ON TABLE source" in sql
    assert "REMOVE FIELD IF EXISTS owner ON TABLE source" in sql
    assert "REMOVE FIELD IF EXISTS promoted_from ON TABLE source" in sql
    # down restores the pre-P5 4-arg / 5-arg signatures (no $viewer_source_ids)
    assert "$viewer_source_ids" not in sql
    assert "DEFINE FUNCTION IF NOT EXISTS fn::text_search" in sql
    assert "DEFINE FUNCTION IF NOT EXISTS fn::vector_search" in sql


def test_no_inline_comments_in_migration_23():
    # AsyncMigration.from_file() joins non-comment lines with spaces; an inline
    # trailing `-- comment` would comment out the rest of the single-line query.
    for name in ("23.surrealql", "23_down.surrealql"):
        for line in (MIGRATIONS / name).read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("--"):
                assert "--" not in stripped, f"inline comment in {name}: {line!r}"
