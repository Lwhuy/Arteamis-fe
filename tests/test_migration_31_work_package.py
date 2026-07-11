# tests/test_migration_31_work_package.py
from pathlib import Path


def test_migration_31_defines_work_package_and_executes_edge():
    up = Path("open_notebook/database/migrations/31.surrealql").read_text()
    assert "DEFINE TABLE work_package" in up
    assert "DEFINE TABLE IF NOT EXISTS executes" in up
    assert "TYPE RELATION" in up
    assert "FROM work_package TO decision|belief" in up
    for field in ["assignee_kind", "assignee", "status", "agent_brief"]:
        assert field in up
    assert "workspace" in up  # workspace-ready

    down = Path("open_notebook/database/migrations/31_down.surrealql").read_text()
    assert "REMOVE TABLE executes" in down
    assert "REMOVE TABLE work_package" in down


def test_migration_31_registered():
    src = Path("open_notebook/database/async_migrate.py").read_text()
    assert "31.surrealql" in src and "31_down.surrealql" in src
