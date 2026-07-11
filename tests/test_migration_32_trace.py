# tests/test_migration_32_trace.py
from pathlib import Path


def test_migration_32_defines_trace_tables():
    up = Path("open_notebook/database/migrations/32.surrealql").read_text()
    for t in [
        "DEFINE TABLE trace",
        "DEFINE TABLE traced_by",
        "DEFINE TABLE learned_from",
        "DEFINE TABLE updates",
    ]:
        assert t in up, t
    assert "work_package" in up
    assert "workspace" in up  # workspace-ready
    down = Path("open_notebook/database/migrations/32_down.surrealql").read_text()
    assert "REMOVE TABLE trace" in down


def test_migration_32_registered():
    src = Path("open_notebook/database/async_migrate.py").read_text()
    assert "32.surrealql" in src and "32_down.surrealql" in src
