"""P4 migration 22 must exist and be registered in the hard-coded manager lists."""

from pathlib import Path

MIGRATIONS = Path("open_notebook/database/migrations")


def test_migration_22_files_exist_with_schema():
    up = (MIGRATIONS / "22.surrealql").read_text()
    down = (MIGRATIONS / "22_down.surrealql").read_text()

    assert "DEFINE TABLE IF NOT EXISTS invitation" in up
    assert "record<workspace>" in up  # invitation links a workspace, not a company
    assert "token_hash" in up
    assert "idx_invitation_token_hash" in up and "UNIQUE" in up
    assert "idx_invitation_workspace_status" in up
    assert "idx_invitation_workspace_email" in up
    assert "option<record<notebook>>" in up  # project link points at the physical notebook table
    assert "REMOVE TABLE IF EXISTS invitation" in down


def test_migration_22_registered_in_manager():
    src = Path("open_notebook/database/async_migrate.py").read_text()
    assert "22.surrealql" in src
    assert "22_down.surrealql" in src
