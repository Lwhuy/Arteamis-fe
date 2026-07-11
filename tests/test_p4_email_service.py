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
async def test_console_debug_log_does_not_leak_raw_invite_token(monkeypatch):
    """The console/DEBUG fallback path used to log.info() the full invite URL,
    which embeds the raw invitation token -- that token grants the same access
    as a password-reset link, so it must never land in application logs. The
    shareable-link RETURN value (used by the API response) is untouched."""
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    monkeypatch.setenv("DEBUG", "true")
    raw_token = "super-secret-invite-token-abc123"
    invite_url = f"http://localhost:3000/invite/{raw_token}"

    logged_messages: list[str] = []
    with patch("api.email_service.logger") as mock_logger:
        mock_logger.info.side_effect = lambda msg, *a, **k: logged_messages.append(msg)
        ok = await email_service.send_invite_email(
            "a@example.com", invite_url, "Acme", None
        )

    assert ok is False  # return-value contract unchanged
    assert logged_messages, "expected an info log for the console/DEBUG fallback"
    for msg in logged_messages:
        assert raw_token not in msg
        assert invite_url not in msg
    # still identifies the invite by recipient, just not by raw token/URL
    assert any("a@example.com" in msg for msg in logged_messages)


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
