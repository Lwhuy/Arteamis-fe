from pathlib import Path


def test_migration_21_defines_visibility_private_default():
    up = Path("open_notebook/database/migrations/21.surrealql").read_text()
    assert "DEFINE FIELD visibility ON source" in up
    assert "'private'" in up  # default
    down = Path("open_notebook/database/migrations/21_down.surrealql").read_text()
    assert "REMOVE FIELD visibility ON source" in down

def test_migration_21_registered():
    src = Path("open_notebook/database/async_migrate.py").read_text()
    assert "21.surrealql" in src and "21_down.surrealql" in src
