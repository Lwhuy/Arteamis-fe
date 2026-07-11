"""P6 rollout: /commands/jobs* endpoints previously had NO auth at all -- any
anonymous caller could submit/inspect/enumerate/cancel any background job.

`command` is surreal-commands' own global job-queue table (no native
`workspace` column in any migration 1-23) shared by every command producer in
the app (note embedding, source processing, podcast generation, ...). List/
cancel/debug-registry get at least an authenticated identity (get_identity)
rather than full ScopedRepository scoping, since they don't return job
`result` content.

Submit and status-read are different (P6 rollout jobstatus fix, see the
module-level comment in api/routers/commands.py and
tests/test_jobstatus_workspace_scoping.py): `result` DOES carry per-tenant
content for some producers, so those two now require a full workspace
context (CtxDep, i.e. get_auth_context) instead of bare identity -- submit
stamps the caller's workspace_id onto the job, and status-read 404s on a
cross-workspace job_id. This file keeps the identity-only submit test but
points it at the real dependency (get_auth_context); see
test_jobstatus_workspace_scoping.py for the cross-workspace-404 /
owning-workspace-200 coverage.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.deps import get_auth_context, get_identity
from api.security import AuthContext


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
    def test_submit_job_ok_with_workspace_token(self, mock_submit, client):
        from api.main import app

        # execute_command requires a full workspace context (CtxDep), not
        # bare identity (P6 rollout jobstatus fix) -- see module docstring.
        app.dependency_overrides[get_auth_context] = lambda: AuthContext(
            user_id="user:1", workspace_id="workspace:a", role="owner"
        )
        mock_submit.return_value = "command:new"
        resp = client.post(
            "/api/commands/jobs",
            json={"command": "process_text", "app": "open_notebook", "input": {}},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["job_id"] == "command:new"
        assert mock_submit.await_args.kwargs["workspace_id"] == "workspace:a"

    @patch("api.routers.commands.CommandService.list_command_jobs", new_callable=AsyncMock)
    def test_list_jobs_ok_with_identity(self, mock_list, client):
        from api.main import app

        app.dependency_overrides[get_identity] = lambda: "user:1"
        mock_list.return_value = []
        resp = client.get("/api/commands/jobs")
        assert resp.status_code == 200
