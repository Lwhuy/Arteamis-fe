import pytest

from api import connectors_service as svc
from api.source_permissions import PermissionContext


def _ctx(user_id="user:1", workspace_id="workspace:1", workspace_role="owner"):
    return PermissionContext(
        user_id=user_id, workspace_id=workspace_id, workspace_role=workspace_role
    )


def test_list_connectors_marks_coming_soon(monkeypatch):
    monkeypatch.delenv("GDRIVE_CLIENT_ID", raising=False)
    result = {c["provider"]: c for c in svc.list_connectors()}
    assert result["s3"]["status"] == "coming_soon"
    # gdrive present, but not configured (no env) and not connected
    assert result["gdrive"]["status"] == "available"


def test_redirect_uri_uses_api_url(monkeypatch):
    monkeypatch.setenv("CONNECTORS_API_URL", "https://api.example.com")
    assert svc.redirect_uri_for("gdrive") == "https://api.example.com/api/connectors/gdrive/callback"


@pytest.mark.asyncio
async def test_handle_callback_rejects_bad_state(monkeypatch):
    monkeypatch.setattr(svc.oauth_state, "consume_state", lambda s: None)
    with pytest.raises(ValueError):
        await svc.handle_callback("gdrive", code="x", state="bad")


def test_build_authorize_url_uses_ctx_ids(monkeypatch):
    captured = {}

    def fake_create_state(workspace_id, user_id):
        captured["workspace_id"] = workspace_id
        captured["user_id"] = user_id
        return "state-token"

    monkeypatch.setenv("GDRIVE_CLIENT_ID", "id")
    monkeypatch.setenv("GDRIVE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(svc.oauth_state, "create_state", fake_create_state)

    ctx = _ctx(user_id="user:7", workspace_id="workspace:9")
    svc.build_authorize_url("gdrive", ctx)

    assert captured == {"workspace_id": "workspace:9", "user_id": "user:7"}


@pytest.mark.asyncio
async def test_ingest_doc_without_notebooks_builds_valid_command(monkeypatch):
    """Regression: notebooks=None must normalize to [] so the real
    SourceProcessingInput (notebook_ids: List[str], non-optional) validates.
    Constructs SourceProcessingInput for real — only Source/CommandService mocked."""
    from open_notebook.domain.connectors.base import ImportedDoc

    class FakeSource:
        def __init__(self, **kwargs):
            self.id = "source:1"
            self.command = None

        async def save(self):
            return None

        async def add_to_notebook(self, notebook_id):
            return None

        async def delete(self):
            return None

    async def fake_submit(app, command, payload):
        # If the bug were present, SourceProcessingInput(notebook_ids=None) would
        # have raised before reaching here; getting here proves normalization worked.
        assert payload["notebook_ids"] == []
        return "command:123"

    monkeypatch.setattr(svc, "Source", FakeSource)
    monkeypatch.setattr(svc, "Asset", lambda **kw: None)
    monkeypatch.setattr(svc.CommandService, "submit_command_job", staticmethod(fake_submit))
    monkeypatch.setattr(svc, "ensure_record_id", lambda x: x)

    command_id = await svc._ingest_doc(
        ImportedDoc(title="t", content="c"), None, owner="user:1", scope="personal"
    )
    assert command_id == "command:123"


@pytest.mark.asyncio
async def test_ingest_doc_sets_owner_and_scope(monkeypatch):
    """Imported sources must carry owner + scope so P5 permission checks
    (Source now REQUIRES owner/scope) resolve visibility correctly instead of
    the source becoming invisible/mis-scoped."""
    from open_notebook.domain.connectors.base import ImportedDoc

    captured = {}

    class FakeSource:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.id = "source:1"
            self.command = None

        async def save(self):
            return None

        async def add_to_notebook(self, notebook_id):
            return None

        async def delete(self):
            return None

    async def fake_submit(app, command, payload):
        return "command:123"

    monkeypatch.setattr(svc, "Source", FakeSource)
    monkeypatch.setattr(svc, "Asset", lambda **kw: None)
    monkeypatch.setattr(svc.CommandService, "submit_command_job", staticmethod(fake_submit))
    monkeypatch.setattr(svc, "ensure_record_id", lambda x: x)

    await svc._ingest_doc(
        ImportedDoc(title="t", content="c"), None, owner="user:42", scope="personal"
    )

    assert captured["owner"] == "user:42"
    assert captured["scope"] == "personal"


class FakeProject:
    """Stand-in for open_notebook.domain.notebook.Project, matching the
    fields the Fix-1 validation in import_items reads: workspace and
    default_source_scope."""

    def __init__(self, workspace="workspace:1", default_source_scope="project"):
        self.workspace = workspace
        self.default_source_scope = default_source_scope


@pytest.mark.asyncio
async def test_import_items_rolls_back_source_when_add_to_notebook_fails(monkeypatch):
    """Regression: if source.add_to_notebook() fails for a notebook that DID
    pass the upfront workspace/role validation (e.g. a transient relate()
    failure), the half-created Source must be rolled back (deleted), not left
    orphaned, and the item must be reported in failed[] rather than raising
    out of import_items."""
    from open_notebook.domain.connectors.base import ConnectorItem, ImportedDoc

    delete_calls = {"count": 0}

    class FakeSource:
        def __init__(self, **kwargs):
            self.id = "source:1"
            self.command = None

        async def save(self):
            return None

        async def add_to_notebook(self, notebook_id):
            raise ValueError(f"failed to relate notebook: {notebook_id}")

        async def delete(self):
            delete_calls["count"] += 1

    class FakeAdapter:
        async def list_items(self, conn):
            return [ConnectorItem(id="item1", kind="file", title="t")]

        async def fetch_content(self, conn, item):
            return ImportedDoc(title="t", content="c")

    class FakeConnection:
        workspace = "workspace:1"

    async def fake_connection_get(connection_id):
        return FakeConnection()

    async def fake_project_get(notebook_id):
        return FakeProject(workspace="workspace:1")

    monkeypatch.setattr(svc, "Source", FakeSource)
    monkeypatch.setattr(svc, "Asset", lambda **kw: None)
    monkeypatch.setattr(svc, "get_connector", lambda provider: FakeAdapter())
    monkeypatch.setattr(svc.Connection, "get", staticmethod(fake_connection_get))
    monkeypatch.setattr(svc, "Project", type("P", (), {"get": staticmethod(fake_project_get)}))

    ctx = _ctx(workspace_id="workspace:1", workspace_role="owner")
    result = await svc.import_items(
        "gdrive", "connection:1", ["item1"], ["notebook:good"], ctx
    )

    assert result["accepted"] == []
    assert len(result["failed"]) == 1
    assert result["failed"][0]["item_id"] == "item1"
    assert delete_calls["count"] == 1


@pytest.mark.asyncio
async def test_import_items_requires_at_least_one_notebook(monkeypatch):
    """Fix 2: under P5 a source is only visible via a reference edge to a
    notebook in the workspace. An import with no target notebook would create
    an invisible, workspace-unbound source -- reject it up front."""
    class FakeConnection:
        workspace = "workspace:1"

    async def fake_connection_get(connection_id):
        return FakeConnection()

    ingest_calls = {"count": 0}

    async def fake_ingest_doc(*args, **kwargs):
        ingest_calls["count"] += 1
        return "command:123"

    monkeypatch.setattr(svc.Connection, "get", staticmethod(fake_connection_get))
    monkeypatch.setattr(svc, "_ingest_doc", fake_ingest_doc)

    ctx = _ctx(workspace_id="workspace:1")

    with pytest.raises(ValueError):
        await svc.import_items("gdrive", "connection:1", ["item1"], [], ctx)
    assert ingest_calls["count"] == 0

    with pytest.raises(ValueError):
        await svc.import_items("gdrive", "connection:1", ["item1"], None, ctx)
    assert ingest_calls["count"] == 0


@pytest.mark.asyncio
async def test_import_items_raises_when_notebook_in_other_workspace(monkeypatch):
    """Fix 1 (CRITICAL): a notebook belonging to a different workspace than the
    caller's must never be usable as an import target, even if the connection
    itself is in the caller's workspace."""
    from open_notebook.domain.connectors.base import ConnectorItem, ImportedDoc

    class FakeConnection:
        workspace = "workspace:1"

    async def fake_connection_get(connection_id):
        return FakeConnection()

    async def fake_project_get(notebook_id):
        return FakeProject(workspace="workspace:other")

    class FakeAdapter:
        async def list_items(self, conn):
            return [ConnectorItem(id="item1", kind="file", title="t")]

        async def fetch_content(self, conn, item):
            return ImportedDoc(title="t", content="c")

    ingest_calls = {"count": 0}

    async def fake_ingest_doc(*args, **kwargs):
        ingest_calls["count"] += 1
        return "command:123"

    monkeypatch.setattr(svc, "get_connector", lambda provider: FakeAdapter())
    monkeypatch.setattr(svc.Connection, "get", staticmethod(fake_connection_get))
    monkeypatch.setattr(svc, "Project", type("P", (), {"get": staticmethod(fake_project_get)}))
    monkeypatch.setattr(svc, "_ingest_doc", fake_ingest_doc)

    ctx = _ctx(workspace_id="workspace:1")

    with pytest.raises(ValueError):
        await svc.import_items(
            "gdrive", "connection:1", ["item1"], ["notebook:foreign"], ctx
        )
    assert ingest_calls["count"] == 0


@pytest.mark.asyncio
async def test_import_items_raises_when_notebook_missing(monkeypatch):
    """Project.get returning None (deleted/never-existed notebook) must raise,
    not silently skip."""
    class FakeConnection:
        workspace = "workspace:1"

    async def fake_connection_get(connection_id):
        return FakeConnection()

    async def fake_project_get(notebook_id):
        return None

    monkeypatch.setattr(svc.Connection, "get", staticmethod(fake_connection_get))
    monkeypatch.setattr(svc, "Project", type("P", (), {"get": staticmethod(fake_project_get)}))

    ctx = _ctx(workspace_id="workspace:1")

    with pytest.raises(ValueError):
        await svc.import_items(
            "gdrive", "connection:1", ["item1"], ["notebook:missing"], ctx
        )


@pytest.mark.asyncio
async def test_import_items_raises_when_caller_not_a_project_member(monkeypatch):
    """Fix 1: a notebook in the caller's own workspace but a project they are
    not admin/member of must still be rejected (mirrors the sources router)."""
    from open_notebook.domain.connectors.base import ConnectorItem, ImportedDoc

    class FakeConnection:
        workspace = "workspace:1"

    async def fake_connection_get(connection_id):
        return FakeConnection()

    async def fake_project_get(notebook_id):
        return FakeProject(workspace="workspace:1")

    class FakeAdapter:
        async def list_items(self, conn):
            return [ConnectorItem(id="item1", kind="file", title="t")]

        async def fetch_content(self, conn, item):
            return ImportedDoc(title="t", content="c")

    monkeypatch.setattr(svc, "get_connector", lambda provider: FakeAdapter())
    monkeypatch.setattr(svc.Connection, "get", staticmethod(fake_connection_get))
    monkeypatch.setattr(svc, "Project", type("P", (), {"get": staticmethod(fake_project_get)}))

    # workspace_role "member" (not owner/admin) forces the real project_role()
    # DB lookup path in PermissionContext; patch it to simulate no membership row.
    ctx = _ctx(workspace_id="workspace:1", workspace_role="member")

    async def fake_project_role(self, project_id):
        return None

    monkeypatch.setattr(PermissionContext, "project_role", fake_project_role)

    with pytest.raises(ValueError):
        await svc.import_items(
            "gdrive", "connection:1", ["item1"], ["notebook:proj"], ctx
        )


@pytest.mark.asyncio
async def test_import_items_ingests_with_resolved_scope_and_owner(monkeypatch):
    """Fix 1: a valid in-workspace notebook with the caller as a member results
    in the source being ingested with owner=ctx.user_id and scope resolved
    from the project's default_source_scope (not hard-coded 'personal')."""
    from open_notebook.domain.connectors.base import ConnectorItem, ImportedDoc

    captured = {}

    class FakeAdapter:
        async def list_items(self, conn):
            return [ConnectorItem(id="item1", kind="file", title="t")]

        async def fetch_content(self, conn, item):
            return ImportedDoc(title="t", content="c")

    class FakeConnection:
        workspace = "workspace:1"

    async def fake_connection_get(connection_id):
        return FakeConnection()

    async def fake_project_get(notebook_id):
        return FakeProject(workspace="workspace:1", default_source_scope="company")

    async def fake_ingest_doc(doc, notebooks, owner, scope):
        captured["doc"] = doc
        captured["notebooks"] = notebooks
        captured["owner"] = owner
        captured["scope"] = scope
        return "command:123"

    monkeypatch.setattr(svc, "get_connector", lambda provider: FakeAdapter())
    monkeypatch.setattr(svc.Connection, "get", staticmethod(fake_connection_get))
    monkeypatch.setattr(svc, "Project", type("P", (), {"get": staticmethod(fake_project_get)}))
    monkeypatch.setattr(svc, "_ingest_doc", fake_ingest_doc)

    ctx = _ctx(user_id="user:42", workspace_id="workspace:1", workspace_role="member")

    async def fake_project_role(self, project_id):
        return "member"

    monkeypatch.setattr(PermissionContext, "project_role", fake_project_role)

    result = await svc.import_items(
        "gdrive", "connection:1", ["item1"], ["notebook:proj"], ctx
    )

    assert result["accepted"] == ["item1"]
    assert captured["owner"] == "user:42"
    assert captured["scope"] == "company"
    assert captured["notebooks"] == ["notebook:proj"]


@pytest.mark.asyncio
async def test_import_items_fail_closed_when_connection_workspace_none(monkeypatch):
    """Fix 3 (MINOR, fail-closed): a connection with workspace=None must never
    pass the workspace check, regardless of ctx.workspace_id."""
    class FakeConnection:
        workspace = None

    async def fake_connection_get(connection_id):
        return FakeConnection()

    monkeypatch.setattr(svc.Connection, "get", staticmethod(fake_connection_get))

    ctx = _ctx(workspace_id="workspace:1")

    with pytest.raises(ValueError):
        await svc.import_items(
            "gdrive", "connection:1", ["item1"], ["notebook:proj"], ctx
        )


@pytest.mark.asyncio
async def test_import_items_raises_on_cross_workspace_connection(monkeypatch):
    """Security: a connection belonging to a different workspace must never be
    usable to import into the caller's workspace."""
    class FakeConnection:
        workspace = "workspace:other"

    async def fake_connection_get(connection_id):
        return FakeConnection()

    monkeypatch.setattr(svc.Connection, "get", staticmethod(fake_connection_get))

    ctx = _ctx(workspace_id="workspace:mine")

    with pytest.raises(ValueError):
        await svc.import_items("gdrive", "connection:1", ["item1"], None, ctx)


@pytest.mark.asyncio
async def test_list_items_raises_on_cross_workspace_connection(monkeypatch):
    class FakeConnection:
        workspace = "workspace:other"

    async def fake_connection_get(connection_id):
        return FakeConnection()

    monkeypatch.setattr(svc.Connection, "get", staticmethod(fake_connection_get))

    ctx = _ctx(workspace_id="workspace:mine")

    with pytest.raises(ValueError):
        await svc.list_items("gdrive", "connection:1", ctx)


@pytest.mark.asyncio
async def test_disconnect_raises_on_cross_workspace_connection(monkeypatch):
    class FakeConnection:
        workspace = "workspace:other"

    async def fake_connection_get(connection_id):
        return FakeConnection()

    monkeypatch.setattr(svc.Connection, "get", staticmethod(fake_connection_get))

    ctx = _ctx(workspace_id="workspace:mine")

    with pytest.raises(ValueError):
        await svc.disconnect("connection:1", ctx)
