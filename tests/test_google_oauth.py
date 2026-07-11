from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _google_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-abc")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-xyz")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:5055/api/auth/google/callback")


def test_build_authorize_url_contains_expected_params():
    from open_notebook.auth.google import build_authorize_url

    url = build_authorize_url("state-token-123")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=client-abc" in url
    assert "scope=openid+email+profile" in url
    assert "state=state-token-123" in url
    assert "prompt=select_account" in url
    assert "response_type=code" in url


@pytest.mark.asyncio
async def test_exchange_code_for_userinfo(monkeypatch):
    from open_notebook.auth import google as google_mod

    token_resp = MagicMock()
    token_resp.raise_for_status = MagicMock()
    token_resp.json = MagicMock(return_value={"access_token": "ya29.token"})

    info_resp = MagicMock()
    info_resp.raise_for_status = MagicMock()
    info_resp.json = MagicMock(
        return_value={
            "sub": "google-sub-1",
            "email": "user@gmail.com",
            "email_verified": True,
            "name": "User Name",
        }
    )

    client = AsyncMock()
    client.post = AsyncMock(return_value=token_resp)
    client.get = AsyncMock(return_value=info_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(google_mod.httpx, "AsyncClient", MagicMock(return_value=client))

    info = await google_mod.exchange_code_for_userinfo("auth-code-1")
    assert info["sub"] == "google-sub-1"
    assert info["email"] == "user@gmail.com"
    assert info["email_verified"] is True
    client.post.assert_awaited_once()
    client.get.assert_awaited_once()
