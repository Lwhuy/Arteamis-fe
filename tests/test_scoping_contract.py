# tests/test_scoping_contract.py
"""Contract guard: a migrated scoped router/service must never call the raw
repo_* helpers or ObjectModel.get/save/delete for a workspace-scoped table — it
must go through the request-injected ScopedRepository (CtxDep). This is the
"developers must not be able to forget the scope" backstop: a regression fails
CI, not production.

MIGRATED_MODULES lists files already converted to ScopedRepository. As each
later phase migrates a router, it appends the file here. `raw()` call sites are
allowed (audited escape hatch) and are excluded by the regex below — but (T3
hardening) every such raw call site must ALSO prove it is workspace-filtered:
either its query text contains `workspace`, or it carries an explicit
`# scoped-raw:` justification comment explaining why the id(s) involved were
already workspace-verified before the raw call. A bare `repo_query()` call
outside of `ScopedRepository.raw()` (e.g. api/deps.py's PermissionContext,
which is deliberately not a ScopedRepository) may also opt into this same
audited-raw-call treatment by carrying a `# scoped-raw:` marker in its call
block — that is the ONLY way such a call is exempted from the banned-token
check below.
"""
import re
from pathlib import Path

# Files converted onto ScopedRepository (grows as phases migrate their routers).
# api/deps.py is included for PermissionContext.project_role's raw `repo_query`
# call — it bypasses ScopedRepository (PermissionContext is deliberately
# lightweight, not a ScopedRepository instance) and was previously invisible to
# this guard entirely.
MIGRATED_MODULES = {
    "api/routers/projects.py",
    "api/deps.py",
    "api/routers/notes.py",
    "api/routers/chat.py",
    "api/routers/podcasts.py",
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

# Call sites that are audited raw access: ScopedRepository's own `.raw(` hatch,
# plus any bare `repo_query(`/`repo_create(`/`repo_update(`/`repo_delete(` call
# that carries a `# scoped-raw:` marker inside its call parentheses (the
# api/deps.py escape hatch for code that isn't a ScopedRepository instance).
_RAW_DOT_CALL = re.compile(r"\.raw\s*(\()")
_BARE_REPO_CALL = re.compile(r"\brepo_(?:query|create|update|delete)\s*(\()")

# A justification comment must carry real explanatory text, not just the bare
# marker — require at least 10 non-whitespace characters after the colon, ON
# THE SAME LINE (`[ \t]*`, not `\s*`, so this can't cross a newline onto the
# following query-text line and count that as "justification").
_JUSTIFICATION = re.compile(r"#\s*scoped-raw:[ \t]*\S.{9,}")


def _call_block(src: str, open_paren_idx: int) -> str:
    """Return the substring from `open_paren_idx` (the '(' character) through
    its matching ')', via simple depth counting. Lightweight/regex-adjacent:
    good enough for our own well-formed call sites, where parens appearing
    inside query-string literals (e.g. `count(<-reference.in)`) are themselves
    balanced."""
    depth = 0
    for i in range(open_paren_idx, len(src)):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                return src[open_paren_idx : i + 1]
    return src[open_paren_idx:]  # unterminated; shouldn't happen in valid source


def _is_marked_raw_call(src: str, match: "re.Match[str]") -> bool:
    """True if a bare repo_*( call at `match` carries a `# scoped-raw:` marker
    inside its own call block — the audited-raw-call opt-in for code that
    doesn't go through a ScopedRepository instance."""
    block = _call_block(src, match.start(1))
    return "# scoped-raw:" in block


def _is_comment_line(src: str, pos: int) -> bool:
    """True if `pos` falls on a line that is itself a comment (starts with
    `#` once stripped) — so a `.raw(` mention inside a docstring/comment
    explaining the pattern isn't mistaken for an actual call site."""
    start = src.rfind("\n", 0, pos) + 1
    end = src.find("\n", pos)
    line = src[start : end if end != -1 else len(src)]
    return line.strip().startswith("#")


def _find_raw_call_blocks(src: str) -> list[str]:
    """Every audited raw call's full call-block text: `.raw(...)` calls (always
    audited) plus bare `repo_*(...)` calls that opt in via a `# scoped-raw:`
    marker. Matches on comment-only lines are ignored (not real call sites)."""
    blocks = [
        _call_block(src, m.start(1))
        for m in _RAW_DOT_CALL.finditer(src)
        if not _is_comment_line(src, m.start())
    ]
    for m in _BARE_REPO_CALL.finditer(src):
        if _is_comment_line(src, m.start()):
            continue
        block = _call_block(src, m.start(1))
        if "# scoped-raw:" in block:
            blocks.append(block)
    return blocks


def _block_query_text(block: str) -> str:
    """The call block with comment-only lines stripped, so a `workspace`
    mention inside a `# scoped-raw:` comment doesn't count as (a) — only the
    actual query/code text does."""
    return "\n".join(
        line for line in block.splitlines() if not line.strip().startswith("#")
    )


def test_migrated_scoped_routers_have_no_raw_repo_calls():
    offenders = []
    for rel in sorted(MIGRATED_MODULES):
        path = _REPO_ROOT / rel
        assert path.exists(), f"MIGRATED_MODULES lists a missing file: {rel}"
        src = path.read_text(encoding="utf-8")
        for pattern in _BANNED:
            for m in pattern.finditer(src):
                start = src.rfind("\n", 0, m.start()) + 1
                line = src[start : src.find("\n", m.start())]
                if ".raw(" in line:
                    continue  # ScopedRepository's own audited hatch
                # Bare repo_*( call: allowed only if it opts into the audited
                # raw-call treatment via a `# scoped-raw:` marker in its block.
                paren_idx = src.find("(", m.start())
                if paren_idx != -1 and "# scoped-raw:" in _call_block(src, paren_idx):
                    continue
                offenders.append(f"{rel}: {line.strip()!r} matched {pattern.pattern}")
    assert not offenders, (
        "Raw scoped-table access found in migrated router(s):\n" + "\n".join(offenders)
    )


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


# ── FIX #2: every audited raw call must prove a workspace filter ───────────
# Unit tests for the checker logic itself, against fabricated source strings
# (fast, no filesystem dependency on the shape of real routers), followed by
# an integration test over the real MIGRATED_MODULES files.

def test_call_block_extracts_balanced_parens():
    src = "x = repo.raw(\n    'SELECT * FROM notebook WHERE workspace = $workspace_id'\n)"
    idx = src.index("(")
    block = _call_block(src, idx)
    assert block.startswith("(") and block.endswith(")")
    assert "workspace_id" in block


def test_checker_flags_raw_call_with_no_workspace_and_no_justification():
    src = (
        "async def f(repo):\n"
        "    rows = await repo.raw(\n"
        "        'DELETE FROM widget WHERE id = $id',\n"
        "        {'id': wid},\n"
        "    )\n"
    )
    blocks = _find_raw_call_blocks(src)
    assert len(blocks) == 1
    query_text = _block_query_text(blocks[0])
    assert "workspace" not in query_text
    assert not _JUSTIFICATION.search(blocks[0])


def test_checker_passes_raw_call_with_workspace_in_query():
    src = (
        "async def f(repo):\n"
        "    rows = await repo.raw(\n"
        "        'SELECT * FROM notebook WHERE workspace = $workspace_id',\n"
        "    )\n"
    )
    blocks = _find_raw_call_blocks(src)
    assert len(blocks) == 1
    assert "workspace" in _block_query_text(blocks[0])


def test_checker_passes_raw_call_with_no_workspace_but_justified():
    src = (
        "async def f(repo):\n"
        "    rows = await repo.raw(\n"
        "        # scoped-raw: id already workspace-verified by repo.get() above\n"
        "        'DELETE project_member WHERE project = $rid',\n"
        "        {'rid': rid},\n"
        "    )\n"
    )
    blocks = _find_raw_call_blocks(src)
    assert len(blocks) == 1
    assert "workspace" not in _block_query_text(blocks[0])
    assert _JUSTIFICATION.search(blocks[0])


def test_checker_flags_marker_with_no_real_justification_text():
    """A bare `# scoped-raw:` marker with no actual explanation is NOT a valid
    justification — it must not be usable as a lazy bypass."""
    src = (
        "async def f(repo):\n"
        "    rows = await repo.raw(\n"
        "        # scoped-raw:\n"
        "        'DELETE FROM widget WHERE id = $id',\n"
        "    )\n"
    )
    blocks = _find_raw_call_blocks(src)
    assert len(blocks) == 1
    assert "workspace" not in _block_query_text(blocks[0])
    assert not _JUSTIFICATION.search(blocks[0])


def test_checker_recognizes_marked_bare_repo_query_call():
    """api/deps.py's PermissionContext.project_role isn't a ScopedRepository, so
    it calls the bare `repo_query()` function — it opts into the audited-raw
    treatment via a `# scoped-raw:` marker in its call block, same as `.raw()`."""
    src = (
        "async def project_role(self, project_id):\n"
        "    rows = await repo_query(\n"
        "        # scoped-raw: project_member lookup filters by workspace natively\n"
        "        'SELECT role FROM project_member WHERE workspace = $workspace',\n"
        "        {'workspace': self.workspace_id},\n"
        "    )\n"
    )
    blocks = _find_raw_call_blocks(src)
    assert len(blocks) == 1
    assert "workspace" in _block_query_text(blocks[0])


def test_checker_ignores_dot_raw_mention_inside_a_comment():
    """A comment merely explaining/mentioning `.raw()` (e.g. 'can't go through
    the ScopedRepository raw escape hatch') must not be mistaken for a call
    site — regression guard for the api/deps.py justification comment."""
    src = (
        "async def f():\n"
        "    # this can't go through repo.raw() here, it's not a ScopedRepository\n"
        "    rows = await repo_query('SELECT * FROM widget', {})\n"
    )
    assert _find_raw_call_blocks(src) == []


def test_checker_ignores_unmarked_bare_repo_query_call():
    """An unmarked bare `repo_query()` call is NOT an audited raw call — it is
    caught by the banned-token test above instead, not silently exempted here."""
    src = "rows = await repo_query('SELECT * FROM widget', {})\n"
    assert _find_raw_call_blocks(src) == []


def test_raw_calls_in_migrated_modules_are_workspace_filtered_or_justified():
    offenders = []
    for rel in sorted(MIGRATED_MODULES):
        path = _REPO_ROOT / rel
        src = path.read_text(encoding="utf-8")
        for block in _find_raw_call_blocks(src):
            query_text = _block_query_text(block)
            if "workspace" in query_text:
                continue  # (a) query text itself carries a workspace filter
            if _JUSTIFICATION.search(block):
                continue  # (b) explicit justification comment
            snippet = next(
                (ln.strip() for ln in block.splitlines() if ln.strip()), block.strip()
            )[:100]
            offenders.append(f"{rel}: raw call has no workspace filter and no justification: {snippet!r}")
    assert not offenders, (
        "Unfiltered/unjustified raw call(s) found — every `.raw()`/audited "
        "repo_query() call must either filter by `workspace` in its query text "
        "or carry a `# scoped-raw: <reason>` justification comment:\n"
        + "\n".join(offenders)
    )
