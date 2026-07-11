from open_notebook.database.async_migrate import AsyncMigration, AsyncMigrationManager


def test_migration_27_is_registered_in_both_lists():
    """Migration 27 must be appended to up and down lists (hard-coded, not auto-discovered)."""
    manager = AsyncMigrationManager()
    assert len(manager.up_migrations) == 27
    assert len(manager.down_migrations) == 27


def test_migration_27_defines_relates_edge():
    """Cleaned SQL for migration 27 defines the source->source `relates` edge."""
    up = AsyncMigration.from_file("open_notebook/database/migrations/27.surrealql")
    sql = up.sql
    assert "DEFINE TABLE IF NOT EXISTS relates" in sql
    assert "TYPE RELATION IN source OUT source" in sql
    assert 'ASSERT $value IN ["supersedes", "disagrees", "complements", "agrees"]' in sql
    assert "DEFINE FIELD IF NOT EXISTS confidence ON TABLE relates TYPE float" in sql
    assert "DEFINE FIELD IF NOT EXISTS rationale ON TABLE relates TYPE string" in sql
    assert "DEFINE FIELD IF NOT EXISTS workspace ON TABLE relates TYPE record<workspace>" in sql
    assert "DEFINE FIELD IF NOT EXISTS created ON TABLE relates TYPE datetime" in sql
    assert "idx_relates_workspace" in sql
    # The cleaner joins with spaces and drops comment lines: no stray "--" survives.
    assert "--" not in sql

    down = AsyncMigration.from_file("open_notebook/database/migrations/27_down.surrealql")
    assert "REMOVE TABLE IF EXISTS relates" in down.sql
