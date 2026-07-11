"""P6 rollout jobstatus fix: the last cross-tenant leak found in the rollout
review.

GET /commands/jobs/{job_id} (api/routers/commands.py) and
GET /podcasts/jobs/{job_id} (api/routers/podcasts.py) previously returned
CommandService.get_command_status(job_id).result verbatim to ANY caller
holding an active-workspace token, with NO ownership check on job_id. For
podcast-generation jobs, `result` carries real tenant content (transcript,
outline, audio_file_path) -- a caller in workspace B could read workspace A's
podcast job result merely by supplying its job_id. This violated the
rollout's no-existence-oracle principle in the opposite direction: not "can
this caller tell if the resource exists", but "can this caller read another
tenant's resource at all".

Fix: the submitting workspace is now stamped into the command row's
`context` field at submission (`context` bypasses the target command's
per-command Pydantic input-schema validation that `args` goes through, so it
persists uniformly for every command -- see
CommandService.submit_command_job's docstring). Both status endpoints now
check it via CommandService.get_command_status_for_workspace, 404ing (never
403 -- no existence oracle) on any mismatch, a missing job, or a job with no
stored workspace at all.

No live DB: patch api.command_service.repo_query (its raw row source) and
override api.deps.get_auth_context, matching the pattern in
tests/test_podcasts_router_scoping.py.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.deps import get_auth_context
from api.security import AuthContext

SECRET_RESULT = {
    "success": True,
    "episode_id": "episode:1",
    "audio_file_path": "/data/podcasts/episodes/abc/final.mp3",
    "transcript": {"transcript": [{"speaker": "Host", "text": "workspace A secret"}]},
    "outline": {"segments": ["workspace A outline secret"]},
}


def _ctx(workspace_id="workspace:a", role="owner", user_id="user:1"):
    return AuthContext(user_id=user_id, workspace_id=workspace_id, role=role)


@pytest.fixture
def client():
    from api.main import app

    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _override(app, ctx):
    app.dependency_overrides[get_auth_context] = lambda: ctx


def _command_row(workspace_id="workspace:a", result=None, context=None, status="completed"):
    row = {
        "id": "command:job1",
        "status": status,
        "result": SECRET_RESULT if result is None else result,
        "error_message": None,
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
        "context": {"workspace_id": workspace_id} if context is None else context,
        "args": {},
    }
    return [row]


class TestCommandJobStatusScoping:
    @patch("api.command_service.repo_query", new_callable=AsyncMock)
    def test_cross_workspace_job_id_is_404_not_result(self, mock_q, client):
        from api.main import app

        _override(app, _ctx(workspace_id="workspace:b"))
        mock_q.return_value = _command_row(workspace_id="workspace:a")

        resp = client.get("/api/commands/jobs/command:job1")

        assert resp.status_code == 404
        assert "workspace A secret" not in resp.text
        assert "audio_file_path" not in resp.text

    @patch("api.command_service.repo_query", new_callable=AsyncMock)
    def test_owning_workspace_gets_result(self, mock_q, client):
        from api.main import app

        _override(app, _ctx(workspace_id="workspace:a"))
        mock_q.return_value = _command_row(workspace_id="workspace:a")

        resp = client.get("/api/commands/jobs/command:job1")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["result"]["transcript"]["transcript"][0]["text"] == "workspace A secret"
        assert body["status"] == "completed"

    @patch("api.command_service.repo_query", new_callable=AsyncMock)
    def test_job_with_no_stored_workspace_is_404(self, mock_q, client):
        """A job submitted before this fix (or via a path with no active
        workspace) has no oracle either -- fail closed, not open."""
        from api.main import app

        _override(app, _ctx(workspace_id="workspace:a"))
        mock_q.return_value = _command_row(workspace_id="workspace:a", context={})

        resp = client.get("/api/commands/jobs/command:job1")

        assert resp.status_code == 404

    @patch("api.command_service.repo_query", new_callable=AsyncMock)
    def test_missing_job_is_404(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []

        resp = client.get("/api/commands/jobs/command:nope")

        assert resp.status_code == 404

    def test_get_job_status_401_without_token(self, client):
        resp = client.get("/api/commands/jobs/command:1")
        assert resp.status_code == 401


class TestPodcastJobStatusScoping:
    @patch("api.command_service.repo_query", new_callable=AsyncMock)
    def test_cross_workspace_job_id_is_404_not_result(self, mock_q, client):
        from api.main import app

        _override(app, _ctx(workspace_id="workspace:b"))
        mock_q.return_value = _command_row(workspace_id="workspace:a")

        resp = client.get("/api/podcasts/jobs/command:job1")

        assert resp.status_code == 404
        assert "workspace A secret" not in resp.text
        assert "audio_file_path" not in resp.text

    @patch("api.command_service.repo_query", new_callable=AsyncMock)
    def test_owning_workspace_gets_result(self, mock_q, client):
        from api.main import app

        _override(app, _ctx(workspace_id="workspace:a"))
        mock_q.return_value = _command_row(workspace_id="workspace:a")

        resp = client.get("/api/podcasts/jobs/command:job1")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["result"]["transcript"]["transcript"][0]["text"] == "workspace A secret"

    @patch("api.command_service.repo_query", new_callable=AsyncMock)
    def test_job_with_no_stored_workspace_is_404(self, mock_q, client):
        from api.main import app

        _override(app, _ctx(workspace_id="workspace:a"))
        mock_q.return_value = _command_row(workspace_id="workspace:a", context={})

        resp = client.get("/api/podcasts/jobs/command:job1")

        assert resp.status_code == 404

    def test_get_job_status_401_without_token(self, client):
        resp = client.get("/api/podcasts/jobs/command:1")
        assert resp.status_code == 401


class TestSubmitCommandJobStampsWorkspace:
    @patch("api.routers.commands.CommandService.submit_command_job", new_callable=AsyncMock)
    def test_submit_stamps_caller_workspace(self, mock_submit, client):
        from api.main import app

        _override(app, _ctx(workspace_id="workspace:a"))
        mock_submit.return_value = "command:new"

        resp = client.post(
            "/api/commands/jobs",
            json={"command": "process_text", "app": "open_notebook", "input": {}},
        )

        assert resp.status_code == 200, resp.text
        assert mock_submit.await_args.kwargs["workspace_id"] == "workspace:a"

    def test_submit_job_403_without_active_workspace(self, client):
        from api.main import app

        _override(app, _ctx(workspace_id=None, role=None))

        resp = client.post(
            "/api/commands/jobs",
            json={"command": "process_text", "app": "open_notebook", "input": {}},
        )

        assert resp.status_code == 403


class TestPodcastServiceStampsWorkspaceContext:
    @pytest.mark.asyncio
    async def test_submit_generation_job_passes_workspace_via_context(self):
        from api.podcast_service import PodcastService

        with (
            patch("api.podcast_service.submit_command") as mock_submit,
            patch(
                "api.podcast_service.EpisodeProfile.get_by_name",
                new=AsyncMock(return_value=object()),
            ),
            patch(
                "api.podcast_service.SpeakerProfile.get_by_name",
                new=AsyncMock(return_value=object()),
            ),
        ):
            mock_submit.return_value = "command:new"
            await PodcastService.submit_generation_job(
                episode_profile_name="default",
                speaker_profile_name="default",
                episode_name="Ep",
                content="hello",
                workspace_id="workspace:a",
            )

        args, _kwargs = mock_submit.call_args
        # submit_command(app, command, args, context) -- context is the 4th
        # positional arg.
        assert args[3] == {"workspace_id": "workspace:a"}


class TestCommandServiceContextPersistence:
    @pytest.mark.asyncio
    async def test_submit_command_job_passes_workspace_id_via_context(self):
        from api.command_service import CommandService

        with patch("api.command_service.submit_command") as mock_submit:
            mock_submit.return_value = "command:new"
            await CommandService.submit_command_job(
                "open_notebook",
                "process_text",
                {"text": "hi"},
                workspace_id="workspace:a",
            )

        args, kwargs = mock_submit.call_args
        # submit_command(app, command, args, context) -- context is the 4th
        # positional arg.
        context = args[3] if len(args) > 3 else kwargs.get("context")
        assert context == {"workspace_id": "workspace:a"}

    @pytest.mark.asyncio
    async def test_submit_command_job_merges_explicit_context(self):
        from api.command_service import CommandService

        with patch("api.command_service.submit_command") as mock_submit:
            mock_submit.return_value = "command:new"
            await CommandService.submit_command_job(
                "open_notebook",
                "process_text",
                {"text": "hi"},
                context={"trace_id": "abc"},
                workspace_id="workspace:a",
            )

        args, kwargs = mock_submit.call_args
        context = args[3] if len(args) > 3 else kwargs.get("context")
        assert context == {"trace_id": "abc", "workspace_id": "workspace:a"}

    @pytest.mark.asyncio
    async def test_get_command_status_for_workspace_missing_job_raises_not_found(self):
        from api.command_service import CommandService
        from open_notebook.exceptions import NotFoundError

        with patch("api.command_service.repo_query", new=AsyncMock(return_value=[])):
            with pytest.raises(NotFoundError):
                await CommandService.get_command_status_for_workspace(
                    "command:nope", "workspace:a"
                )

    @pytest.mark.asyncio
    async def test_get_command_status_for_workspace_mismatch_raises_not_found(self):
        from api.command_service import CommandService
        from open_notebook.exceptions import NotFoundError

        with patch(
            "api.command_service.repo_query",
            new=AsyncMock(return_value=_command_row(workspace_id="workspace:other")),
        ):
            with pytest.raises(NotFoundError):
                await CommandService.get_command_status_for_workspace(
                    "command:job1", "workspace:mine"
                )

    @pytest.mark.asyncio
    async def test_get_command_status_for_workspace_match_returns_result(self):
        from api.command_service import CommandService

        with patch(
            "api.command_service.repo_query",
            new=AsyncMock(return_value=_command_row(workspace_id="workspace:a")),
        ):
            data = await CommandService.get_command_status_for_workspace(
                "command:job1", "workspace:a"
            )
        assert data["result"] == SECRET_RESULT
        assert data["status"] == "completed"
