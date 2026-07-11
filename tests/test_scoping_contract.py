# tests/test_scoping_contract.py
"""Contract guard: a migrated scoped router/service must never call the raw
repo_* helpers or ObjectModel.get/save/delete for a workspace-scoped table — it
must go through the request-injected ScopedRepository (CtxDep). This is the
"developers must not be able to forget the scope" backstop: a regression fails
CI, not production.

MIGRATED_MODULES lists files already converted to ScopedRepository. As each
later phase migrates a router, it appends the file here. `raw()` call sites are
allowed (audited escape hatch) and are excluded by the regex below.
"""
import re
from pathlib import Path

# Files converted onto ScopedRepository (grows as phases migrate their routers).
MIGRATED_MODULES = {
    "api/routers/projects.py",
}

# Banned tokens: raw scoped-table access outside ScopedRepository.
_BANNED = [
    re.compile(r"\brepo_query\s*\("),
    re.compile(r"\brepo_create\s*\("),
    re.compile(r"\brepo_update\s*\("),
    re.compile(r"\brepo_delete\s*\("),
    re.compile(r"\bProject\.get\b"),
    re.compile(r"\bNotebook\.get\b"),
    re.compile(r"\bSource\.get\b"),
    re.compile(r"\bProject\.get_all\b"),
    re.compile(r"\bNotebook\.get_all\b"),
]

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _strip_scoped_raw_lines(src: str) -> str:
    """Drop lines that are part of a `repo.raw(` / `self.raw(` / `.raw(` call so
    the audited escape hatch does not trip the raw-repo_query guard. We only strip
    the `repo_query`-equivalent inside ScopedRepository.raw usage, identified by a
    `# scoped-raw:` marker on or above the call."""
    out_lines = []
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if "# scoped-raw:" in line:
            out_lines.append("")  # neutralize the marker line
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def test_migrated_scoped_routers_have_no_raw_repo_calls():
    offenders = []
    for rel in sorted(MIGRATED_MODULES):
        path = _REPO_ROOT / rel
        assert path.exists(), f"MIGRATED_MODULES lists a missing file: {rel}"
        src = _strip_scoped_raw_lines(path.read_text(encoding="utf-8"))
        for pattern in _BANNED:
            for m in pattern.finditer(src):
                # allow `repo.raw(` and `.raw(` — that's ScopedRepository's own hatch
                start = src.rfind("\n", 0, m.start()) + 1
                line = src[start : src.find("\n", m.start())]
                if ".raw(" in line:
                    continue
                offenders.append(f"{rel}: {line.strip()!r} matched {pattern.pattern}")
    assert not offenders, "Raw scoped-table access found in migrated router(s):\n" + "\n".join(offenders)


def test_migrated_modules_all_exist():
    for rel in MIGRATED_MODULES:
        assert (_REPO_ROOT / rel).exists(), f"{rel} not found"


def test_scoping_module_has_no_kind_literals():
    """Belt-and-suspenders alongside test_scoping_unit's reflection test: the
    scoping module's source must never mention "personal"/"company" — those
    words belong in the frontend and in P4's invitation guard, not here."""
    src = (_REPO_ROOT / "open_notebook/database/scoping.py").read_text(encoding="utf-8")
    for token in ('"personal"', "'personal'", '"company"', "'company'"):
        assert token not in src, f"scoping.py must not branch on kind literal {token!r}"
