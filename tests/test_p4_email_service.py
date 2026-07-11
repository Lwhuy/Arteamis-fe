from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api import email_service


@pytest.mark.asyncio
async def test_console_provider_returns_false(monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    ok = await email_service.send_invite_email(
        "a@example.com", "http://localhost:3000/invite/tok", "Acme", None
    )
    assert ok is False  # not delivered -> caller falls back to a share link


@pytest.mark.asyncio
async def test_resend_provider_posts_and_returns_true(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@acme.test")

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("api.email_service.httpx.AsyncClient", return_value=client):
        ok = await email_service.send_invite_email(
            "a@example.com", "http://localhost:3000/invite/tok", "Acme", "Roadmap"
        )
    assert ok is True
    client.post.assert_awaited_once()
    args, kwargs = client.post.call_args
    assert args[0] == "https://api.resend.com/emails"
    assert kwargs["json"]["to"] == ["a@example.com"]


@pytest.mark.asyncio
async def test_resend_failure_is_swallowed_and_returns_false(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@acme.test")
    with patch("api.email_service.httpx.AsyncClient", side_effect=RuntimeError("boom")):
        ok = await email_service.send_invite_email(
            "a@example.com", "http://x/invite/t", "Acme", None
        )
    assert ok is False  # never raises into the request path
