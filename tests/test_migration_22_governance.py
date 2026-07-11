from pathlib import Path

def test_migration_22_defines_governance_tables():
    up = Path("open_notebook/database/migrations/22.surrealql").read_text()
    for t in ["DEFINE TABLE proposal", "DEFINE TABLE belief", "DEFINE TABLE audit_event",
              "DEFINE TABLE derived_from", "DEFINE TABLE promotes_to"]:
        assert t in up, t
    assert "workspace" in up  # workspace-ready
    down = Path("open_notebook/database/migrations/22_down.surrealql").read_text()
    assert "REMOVE TABLE proposal" in down and "REMOVE TABLE belief" in down

def test_migration_22_registered():
    src = Path("open_notebook/database/async_migrate.py").read_text()
    assert "22.surrealql" in src and "22_down.surrealql" in src
