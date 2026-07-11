from pathlib import Path

def test_migration_20_defines_visibility_private_default():
    up = Path("open_notebook/database/migrations/20.surrealql").read_text()
    assert "DEFINE FIELD visibility ON source" in up
    assert "'private'" in up  # default
    down = Path("open_notebook/database/migrations/20_down.surrealql").read_text()
    assert "REMOVE FIELD visibility ON source" in down

def test_migration_20_registered():
    src = Path("open_notebook/database/async_migrate.py").read_text()
    assert "20.surrealql" in src and "20_down.surrealql" in src
