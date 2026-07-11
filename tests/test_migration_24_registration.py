def test_migration_24_is_registered_in_both_lists():
    """Migration 24 (connection) must be appended to up and down lists
    (hard-coded, not auto-discovered)."""
    from open_notebook.database.async_migrate import AsyncMigrationManager

    manager = AsyncMigrationManager()
    # Final total after auth-mt-rollout merge: 1-23 (P0-P6) + 24 (connectors) + 25 (rollout: episode.workspace).
    assert len(manager.up_migrations) == 32
    assert len(manager.down_migrations) == 32


def test_migration_24_defines_connection_table():
    """The cleaned SQL for migration 24 defines the connection table."""
    from open_notebook.database.async_migrate import AsyncMigration

    up = AsyncMigration.from_file("open_notebook/database/migrations/24.surrealql")
    sql = up.sql
    assert "DEFINE TABLE IF NOT EXISTS connection SCHEMAFULL" in sql
    assert "idx_connection_provider" in sql
    # The cleaner joins with spaces and drops comment lines: no stray "--" survives.
    assert "--" not in sql

    down = AsyncMigration.from_file("open_notebook/database/migrations/24_down.surrealql")
    assert "REMOVE TABLE IF EXISTS connection" in down.sql
