"""Workspace-scoped /podcasts router tests (P6 rollout).

`episode` gained a native (optional) `workspace` column in migration 24 -- it
had NO workspace column at all before this rollout, so every endpoint was
fully unscoped: any caller could list/get/stream/retry/delete any episode by
id, and generate_podcast's `notebook_id` was passed straight through to
Notebook.get() (api/podcast_service.py) with no ownership check, letting a
caller exfiltrate another workspace's notebook content into their own
episode. These tests exercise the fix with no live DB: override
api.deps.get_auth_context and patch open_notebook.database.scoping.repo_query.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.deps import get_auth_context
from api.security import AuthContext


def _ctx(role="owner", workspace_id="workspace:a", user_id="user:1"):
    return AuthContext(user_id=user_id, workspace_id=workspace_id, role=role)


@pytest.fixture
def client():
    from api.main import app

    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _override(app, ctx):
    app.dependency_overrides[get_auth_context] = lambda: ctx


class TestPodcastsRequireWorkspace:
    def test_list_episodes_401_without_token(self, client):
        resp = client.get("/api/podcasts/episodes")
        assert resp.status_code == 401


class TestGeneratePodcast:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_cross_workspace_notebook_id_is_404(self, mock_q, client):
        """The real leak this rollout closes: previously notebook_id was
        passed straight to an unscoped Notebook.get(), letting a caller pull
        another workspace's notebook content into their own podcast
        episode."""
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []  # repo.get(notebook_id) ownership check finds nothing
        resp = client.post(
            "/api/podcasts/generate",
            json={
                "episode_profile": "default",
                "speaker_profile": "default",
                "episode_name": "Ep1",
                "notebook_id": "notebook:other-workspace",
            },
        )
        assert resp.status_code == 404

    @patch("api.routers.podcasts.PodcastService.submit_generation_job", new_callable=AsyncMock)
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_own_notebook_id_submits_and_stamps_workspace(self, mock_q, mock_submit, client):
        from api.main import app

        _override(app, _ctx(workspace_id="workspace:a"))
        mock_q.return_value = [{"id": "notebook:1", "workspace": "workspace:a"}]
        mock_submit.return_value = "command:new"
        resp = client.post(
            "/api/podcasts/generate",
            json={
                "episode_profile": "default",
                "speaker_profile": "default",
                "episode_name": "Ep1",
                "notebook_id": "notebook:1",
            },
        )
        assert resp.status_code == 200, resp.text
        assert mock_submit.await_args.kwargs["workspace_id"] == "workspace:a"

    @patch("api.routers.podcasts.PodcastService.submit_generation_job", new_callable=AsyncMock)
    def test_no_notebook_id_skips_ownership_check_but_still_stamps_workspace(self, mock_submit, client):
        from api.main import app

        _override(app, _ctx(workspace_id="workspace:a"))
        mock_submit.return_value = "command:new"
        resp = client.post(
            "/api/podcasts/generate",
            json={
                "episode_profile": "default",
                "speaker_profile": "default",
                "episode_name": "Ep1",
                "content": "raw text",
            },
        )
        assert resp.status_code == 200, resp.text
        assert mock_submit.await_args.kwargs["workspace_id"] == "workspace:a"


def _episode_row(**over):
    base = dict(
        id="episode:1",
        name="Ep",
        episode_profile={"name": "default"},
        speaker_profile={"name": "default"},
        briefing="b",
        content="c",
        audio_file=None,
        transcript=None,
        outline=None,
        command=None,
        workspace="workspace:a",
        created="2026-01-01T00:00:00",
    )
    base.update(over)
    return base


class TestEpisodeDetail:
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_get_cross_workspace_episode_is_404(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []
        resp = client.get("/api/podcasts/episodes/episode:1")
        assert resp.status_code == 404

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_get_own_episode_ok(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = [_episode_row()]
        resp = client.get("/api/podcasts/episodes/episode:1")
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == "episode:1"

    @patch("open_notebook.domain.base.repo_delete", new_callable=AsyncMock)
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_delete_cross_workspace_episode_is_404(self, mock_q, mock_delete, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []
        resp = client.delete("/api/podcasts/episodes/episode:1")
        assert resp.status_code == 404
        mock_delete.assert_not_awaited()

    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_retry_cross_workspace_episode_is_404(self, mock_q, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = []
        resp = client.post("/api/podcasts/episodes/episode:1/retry")
        assert resp.status_code == 404


class TestListEpisodesScoping:
    @patch("api.routers.podcasts.PodcastEpisode.get_job_details_for_commands", new_callable=AsyncMock)
    @patch("open_notebook.database.scoping.repo_query", new_callable=AsyncMock)
    def test_list_scopes_by_workspace(self, mock_q, mock_batch, client):
        from api.main import app

        _override(app, _ctx())
        mock_q.return_value = [_episode_row(audio_file="/tmp/x.mp3")]
        mock_batch.return_value = {}
        resp = client.get("/api/podcasts/episodes")
        assert resp.status_code == 200, resp.text
        query = mock_q.await_args_list[0].args[0]
        assert "workspace = $workspace_id" in query
