from pathlib import Path


def test_migration_30_defines_decision_rule_tables():
    up = Path("open_notebook/database/migrations/30.surrealql").read_text()
    for t in ["DEFINE TABLE decision", "DEFINE TABLE rule", "DEFINE TABLE supports"]:
        assert t in up, t
    assert "workspace" in up  # workspace-ready
    assert "TYPE RELATION" in up  # supports is an edge table
    down = Path("open_notebook/database/migrations/30_down.surrealql").read_text()
    assert "REMOVE TABLE decision" in down
    assert "REMOVE TABLE rule" in down
    assert "REMOVE TABLE supports" in down


def test_migration_30_registered():
    src = Path("open_notebook/database/async_migrate.py").read_text()
    assert "30.surrealql" in src and "30_down.surrealql" in src
