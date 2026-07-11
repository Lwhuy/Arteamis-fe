"""Migration 25 registration + content guards (P6 rollout: episode workspace scoping).

`episode` had no `workspace` column at all (schema gap identified by the P6
scoping audit) -- podcasts.py's endpoints were fully unscoped as a result.
This migration adds the column + a supporting index; no backfill is possible
(episode carries no stored link back to the notebook/source it was generated
from), so existing rows are left workspace=NONE (invisible under
workspace-scoped list/get until regenerated) and only new episodes are
stamped going forward.

Renumbered from 24 to 25 during the auth-mt-rollout merge: connectors' branch
independently claimed migration 24 for the `connection` table. Final order is
...23, 24=connection, 25=episode.workspace.
"""
from pathlib import Path

from open_notebook.database.async_migrate import AsyncMigrationManager

MIGRATIONS = Path("open_notebook/database/migrations")


def test_migration_25_registered():
    mgr = AsyncMigrationManager()
    assert len(mgr.up_migrations) == 32
    assert len(mgr.down_migrations) == 32
    assert "workspace" in mgr.up_migrations[24].sql
    assert "episode" in mgr.up_migrations[24].sql


def test_migration_25_up_adds_workspace_field_and_index():
    sql = (MIGRATIONS / "25.surrealql").read_text()
    assert "DEFINE FIELD IF NOT EXISTS workspace ON TABLE episode TYPE option<record<workspace>>" in sql
    assert "idx_episode_workspace" in sql


def test_migration_25_down_removes_field_and_index():
    sql = (MIGRATIONS / "25_down.surrealql").read_text()
    assert "REMOVE FIELD IF EXISTS workspace ON TABLE episode" in sql
    assert "REMOVE INDEX IF EXISTS idx_episode_workspace" in sql


def test_no_inline_comments_in_migration_25():
    # AsyncMigration.from_file() joins non-comment lines with spaces; an inline
    # trailing `-- comment` would comment out the rest of the single-line query.
    for name in ("25.surrealql", "25_down.surrealql"):
        for line in (MIGRATIONS / name).read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("--"):
                assert "--" not in stripped, f"inline comment in {name}: {line!r}"
