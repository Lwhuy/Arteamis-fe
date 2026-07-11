import importlib

import pytest


def test_migration_19_is_registered_in_both_lists():
    """Migration 19 must be appended to up and down lists (hard-coded, not auto-discovered)."""
    from open_notebook.database.async_migrate import AsyncMigrationManager

    manager = AsyncMigrationManager()
    # Final main has migrations 1-23 (P4's 22 + P5's 23 both registered).
    assert len(manager.up_migrations) == 24
    assert len(manager.down_migrations) == 24


def test_migration_19_defines_identity_tables():
    """The cleaned SQL for migration 19 defines the user + auth_identity tables and unique indexes."""
    from open_notebook.database.async_migrate import AsyncMigration

    up = AsyncMigration.from_file("open_notebook/database/migrations/19.surrealql")
    sql = up.sql
    assert "DEFINE TABLE IF NOT EXISTS user SCHEMAFULL" in sql
    assert "DEFINE TABLE IF NOT EXISTS auth_identity SCHEMAFULL" in sql
    assert "DEFINE INDEX IF NOT EXISTS idx_user_email ON TABLE user FIELDS email UNIQUE" in sql
    assert "idx_auth_identity_unique" in sql
    # The cleaner joins with spaces and drops comment lines: no stray "--" survives.
    assert "--" not in sql

    down = AsyncMigration.from_file("open_notebook/database/migrations/19_down.surrealql")
    assert "REMOVE TABLE IF EXISTS auth_identity" in down.sql
    assert "REMOVE TABLE IF EXISTS user" in down.sql


@pytest.mark.parametrize("module_name", ["jose", "argon2", "email_validator"])
def test_new_dependencies_importable(module_name):
    """The three new packages must be installed so later tasks can import them."""
    assert importlib.import_module(module_name) is not None
