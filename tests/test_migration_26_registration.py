from open_notebook.database.async_migrate import AsyncMigration, AsyncMigrationManager


def test_migration_26_is_registered_in_both_lists():
    """Migration 26 must be appended to up and down lists (hard-coded, not auto-discovered)."""
    manager = AsyncMigrationManager()
    assert len(manager.up_migrations) == 27
    assert len(manager.down_migrations) == 27


def test_migration_26_defines_brain_tables():
    """Cleaned SQL for migration 26 defines entity + mentions/part_of relations."""
    up = AsyncMigration.from_file("open_notebook/database/migrations/26.surrealql")
    sql = up.sql
    assert "DEFINE TABLE IF NOT EXISTS entity" in sql
    assert "DEFINE FIELD IF NOT EXISTS workspace ON TABLE entity TYPE record<workspace>" in sql
    assert "DEFINE FIELD IF NOT EXISTS normalized_name ON TABLE entity TYPE string" in sql
    assert "DEFINE TABLE IF NOT EXISTS mentions" in sql
    assert "TYPE RELATION FROM source TO entity" in sql
    assert "DEFINE TABLE IF NOT EXISTS part_of" in sql
    # The cleaner drops comment lines: no stray "--" survives.
    assert "--" not in sql

    down = AsyncMigration.from_file("open_notebook/database/migrations/26_down.surrealql")
    assert "REMOVE TABLE IF EXISTS entity" in down.sql
    assert "REMOVE TABLE IF EXISTS mentions" in down.sql
    assert "REMOVE TABLE IF EXISTS part_of" in down.sql
