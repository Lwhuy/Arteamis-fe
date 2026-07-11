"""P6 rollout: /commands/jobs* endpoints previously had NO auth at all -- any
anonymous caller could submit/inspect/enumerate/cancel any background job.

`command` is surreal-commands' own global job-queue table (no `workspace`
column in any migration 1-23) shared by every command producer in the app
(note embedding, source processing, podcast generation, ...) -- it is not
workspace-scoped tenant content, so these endpoints get at least an
authenticated identity (get_identity) rather than full ScopedRepository
scoping. See the module-level `# global:` comment in api/routers/commands.py.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.deps import get_identity


@pytest.fixture
def client():
    from api.main import app

    yield TestClient(app)
    app.dependency_overrides.clear()


class TestCommandsRequireIdentity:
    def test_submit_job_401_without_token(self, client):
        resp = client.post(
            "/api/commands/jobs",
            json={"command": "process_text", "app": "open_notebook", "input": {}},
        )
        assert resp.status_code == 401

    def test_get_job_status_401_without_token(self, client):
        resp = client.get("/api/commands/jobs/command:1")
        assert resp.status_code == 401

    def test_list_jobs_401_without_token(self, client):
        resp = client.get("/api/commands/jobs")
        assert resp.status_code == 401

    def test_cancel_job_401_without_token(self, client):
        resp = client.delete("/api/commands/jobs/command:1")
        assert resp.status_code == 401

    def test_debug_registry_401_without_token(self, client):
        resp = client.get("/api/commands/registry/debug")
        assert resp.status_code == 401


class TestCommandsWithIdentity:
    @patch("api.routers.commands.CommandService.submit_command_job", new_callable=AsyncMock)
    def test_submit_job_ok_with_identity(self, mock_submit, client):
        from api.main import app

        app.dependency_overrides[get_identity] = lambda: "user:1"
        mock_submit.return_value = "command:new"
        resp = client.post(
            "/api/commands/jobs",
            json={"command": "process_text", "app": "open_notebook", "input": {}},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["job_id"] == "command:new"

    @patch("api.routers.commands.CommandService.list_command_jobs", new_callable=AsyncMock)
    def test_list_jobs_ok_with_identity(self, mock_list, client):
        from api.main import app

        app.dependency_overrides[get_identity] = lambda: "user:1"
        mock_list.return_value = []
        resp = client.get("/api/commands/jobs")
        assert resp.status_code == 200
