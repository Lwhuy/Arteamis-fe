"""build_session_payload auto-provisions the personal workspace on every call."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.auth_service import build_session_payload
from api.security import decode_access_token


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-p2-session-payload")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")


def _user(user_id="user:1", email="a@example.com", display_name="Ada"):
    return SimpleNamespace(id=user_id, email=email, display_name=display_name)


@pytest.mark.asyncio
@patch("api.auth_service.list_memberships", new_callable=AsyncMock)
@patch("api.auth_service.ensure_personal_workspace", new_callable=AsyncMock)
async def test_session_payload_is_workspace_scoped_for_new_user(
    mock_ensure, mock_list
):
    mock_ensure.return_value = SimpleNamespace(id="workspace:p1", kind="personal")
    mock_list.return_value = [
        {
            "workspace_id": "workspace:p1",
            "name": "Personal",
            "slug": "personal-1",
            "kind": "personal",
            "role": "owner",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }
    ]

    payload = await build_session_payload(_user())

    ctx = decode_access_token(payload["access_token"])
    assert ctx.workspace_id == "workspace:p1"
    assert ctx.role == "owner"
    assert payload["active_workspace_id"] == "workspace:p1"
    assert payload["needs_onboarding"] is True  # no company workspace yet
    assert payload["memberships"] == mock_list.return_value
    mock_ensure.assert_awaited_once_with("user:1")


@pytest.mark.asyncio
@patch("api.auth_service.list_memberships", new_callable=AsyncMock)
@patch("api.auth_service.ensure_personal_workspace", new_callable=AsyncMock)
async def test_session_payload_needs_onboarding_false_once_a_company_exists(
    mock_ensure, mock_list
):
    mock_ensure.return_value = SimpleNamespace(id="workspace:p1", kind="personal")
    mock_list.return_value = [
        {"workspace_id": "workspace:p1", "name": "Personal", "slug": "personal-1", "kind": "personal", "role": "owner", "created": "", "updated": ""},
        {"workspace_id": "workspace:acme", "name": "Acme", "slug": "acme", "kind": "company", "role": "owner", "created": "", "updated": ""},
    ]

    payload = await build_session_payload(_user())

    # Even with a company membership, a fresh login resets the ACTIVE workspace
    # to Personal (the stated default decision) — only the onboarding signal
    # changes, not which workspace is active.
    assert payload["active_workspace_id"] == "workspace:p1"
    assert payload["needs_onboarding"] is False


@pytest.mark.asyncio
@patch("api.auth_service.list_memberships", new_callable=AsyncMock)
@patch("api.auth_service.ensure_personal_workspace", new_callable=AsyncMock)
async def test_session_payload_never_returns_null_active_workspace(
    mock_ensure, mock_list
):
    mock_ensure.return_value = SimpleNamespace(id="workspace:p1", kind="personal")
    mock_list.return_value = []  # defensive: even if the list query races, don't crash

    payload = await build_session_payload(_user())

    assert payload["active_workspace_id"] == "workspace:p1"
    assert payload["memberships"] == []
