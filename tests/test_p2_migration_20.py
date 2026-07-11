"""Migration 20 (workspace + membership) is well-formed and registered.

DB-free: mirrors the repo's migration-test style — assert the DDL statements
exist and that AsyncMigrationManager wires the 20th up/down migration. A live
SurrealDB up/down round-trip is out of scope for the unit suite.
"""

from pathlib import Path

from open_notebook.database.async_migrate import AsyncMigration, AsyncMigrationManager

MIGRATIONS = Path("open_notebook/database/migrations")


def test_migration_20_files_exist():
    assert (MIGRATIONS / "20.surrealql").exists()
    assert (MIGRATIONS / "20_down.surrealql").exists()


def test_migration_20_defines_workspace_and_membership():
    sql = AsyncMigration.from_file(str(MIGRATIONS / "20.surrealql")).sql
    assert "DEFINE TABLE IF NOT EXISTS workspace SCHEMAFULL" in sql
    assert "DEFINE FIELD IF NOT EXISTS slug ON TABLE workspace TYPE string" in sql
    assert "DEFINE FIELD IF NOT EXISTS kind  ON TABLE workspace TYPE string" in sql or "DEFINE FIELD IF NOT EXISTS kind ON TABLE workspace TYPE string" in sql
    assert "'personal'" in sql and "'company'" in sql
    assert "DEFINE FIELD IF NOT EXISTS owner ON TABLE workspace TYPE record<user>" in sql
    assert "idx_workspace_slug ON TABLE workspace FIELDS slug UNIQUE" in sql
    assert "DEFINE TABLE IF NOT EXISTS membership SCHEMAFULL" in sql
    assert "role      ON TABLE membership TYPE string" in sql or "role ON TABLE membership TYPE string" in sql
    assert "idx_membership_user_workspace ON TABLE membership FIELDS user, workspace UNIQUE" in sql


def test_migration_20_down_removes_tables():
    sql = AsyncMigration.from_file(str(MIGRATIONS / "20_down.surrealql")).sql
    assert "REMOVE TABLE IF EXISTS membership" in sql
    assert "REMOVE TABLE IF EXISTS workspace" in sql


def test_migration_20_is_registered():
    manager = AsyncMigrationManager()
    assert len(manager.up_migrations) == 21
    assert len(manager.down_migrations) == 21
    assert "workspace" in manager.up_migrations[19].sql
    assert "membership" in manager.down_migrations[19].sql
