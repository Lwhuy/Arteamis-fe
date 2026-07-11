"""Migration 21 is registered and defines the project governance schema.

Full backfill semantics run against a live SurrealDB on API startup; here we
assert registration + that the SurrealQL declares the expected fields/tables so
a typo or an unregistered file fails fast in CI (no DB required).
"""

from pathlib import Path

from open_notebook.database.async_migrate import AsyncMigration, AsyncMigrationManager

MIGRATIONS = Path("open_notebook/database/migrations")


def test_manager_registers_migration_21():
    mgr = AsyncMigrationManager()
    assert len(mgr.up_migrations) == len(mgr.down_migrations)
    # P1=19, P2=20, P3=21 -> at least 21 registered pairs.
    assert len(mgr.up_migrations) >= 21


def test_migration_21_files_load():
    # Must parse without raising (same loader the manager uses at startup).
    AsyncMigration.from_file(str(MIGRATIONS / "21.surrealql"))
    AsyncMigration.from_file(str(MIGRATIONS / "21_down.surrealql"))


def test_migration_21_declares_project_columns_and_member_table():
    sql = (MIGRATIONS / "21.surrealql").read_text()
    assert "DEFINE FIELD IF NOT EXISTS workspace ON TABLE notebook" in sql
    assert "DEFINE FIELD IF NOT EXISTS owner ON TABLE notebook" in sql
    assert "default_source_scope ON TABLE notebook" in sql
    assert "promoted_from ON TABLE notebook" in sql
    assert "DEFINE TABLE IF NOT EXISTS project_member SCHEMAFULL" in sql
    assert "idx_project_member_unique" in sql
    assert "workspace:personal_default" in sql  # self-seeded backfill lives here


def test_migration_21_down_reverses_it():
    sql = (MIGRATIONS / "21_down.surrealql").read_text()
    assert "REMOVE TABLE IF EXISTS project_member" in sql
    assert "REMOVE FIELD IF EXISTS workspace ON TABLE notebook" in sql
    assert "DELETE workspace:personal_default" in sql
