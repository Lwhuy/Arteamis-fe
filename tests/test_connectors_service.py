import pytest

from api import connectors_service as svc


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
    monkeypatch.setattr(svc.oauth_state, "consume_state", lambda s: False)
    with pytest.raises(ValueError):
        await svc.handle_callback("gdrive", code="x", state="bad")


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

    command_id = await svc._ingest_doc(ImportedDoc(title="t", content="c"), None)
    assert command_id == "command:123"


@pytest.mark.asyncio
async def test_import_items_rolls_back_source_when_add_to_notebook_fails(monkeypatch):
    """Regression: if source.add_to_notebook() fails (e.g. bad notebook id), the
    half-created Source must be rolled back (deleted), not left orphaned, and
    the item must be reported in failed[] rather than raising out of import_items."""
    from open_notebook.domain.connectors.base import ConnectorItem, ImportedDoc

    delete_calls = {"count": 0}

    class FakeSource:
        def __init__(self, **kwargs):
            self.id = "source:1"
            self.command = None

        async def save(self):
            return None

        async def add_to_notebook(self, notebook_id):
            raise ValueError(f"notebook not found: {notebook_id}")

        async def delete(self):
            delete_calls["count"] += 1

    class FakeAdapter:
        async def list_items(self, conn):
            return [ConnectorItem(id="item1", kind="file", title="t")]

        async def fetch_content(self, conn, item):
            return ImportedDoc(title="t", content="c")

    async def fake_connection_get(connection_id):
        return object()

    monkeypatch.setattr(svc, "Source", FakeSource)
    monkeypatch.setattr(svc, "Asset", lambda **kw: None)
    monkeypatch.setattr(svc, "get_connector", lambda provider: FakeAdapter())
    monkeypatch.setattr(svc.Connection, "get", staticmethod(fake_connection_get))

    result = await svc.import_items(
        "gdrive", "connection:1", ["item1"], notebooks=["notebook:bad"]
    )

    assert result["accepted"] == []
    assert len(result["failed"]) == 1
    assert result["failed"][0]["item_id"] == "item1"
    assert delete_calls["count"] == 1
