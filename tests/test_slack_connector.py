from unittest.mock import AsyncMock, MagicMock

import pytest

from open_notebook.domain.connectors import slack as slack_mod
from open_notebook.domain.connectors.slack import SlackConnector


class FakeAccessToken:
    def get_secret_value(self):
        return "tok-123"


class FakeConnection:
    access_token = FakeAccessToken()


def _resp(json_data):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json = MagicMock(return_value=json_data)
    return r


def test_authorize_url_uses_v2_and_scopes(monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "cid")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "sec")
    url = SlackConnector().authorize_url("ST", "http://localhost:5055/api/connectors/slack/callback")
    assert "slack.com/oauth/v2/authorize" in url
    assert "pins:read" in url
    assert "state=ST" in url


def test_render_pins_concatenates_message_text():
    pins = [
        {"message": {"text": "first pinned", "user": "U1"}},
        {"message": {"text": "second pinned", "user": "U2"}},
    ]
    out = SlackConnector()._render_pins(pins)
    assert "first pinned" in out and "second pinned" in out


@pytest.mark.asyncio
async def test_list_items_follows_next_cursor(monkeypatch):
    page1 = _resp({
        "ok": True,
        "channels": [{"id": "C1", "name": "general"}],
        "response_metadata": {"next_cursor": "CURSOR1"},
    })
    page2 = _resp({
        "ok": True,
        "channels": [{"id": "C2", "name": "random"}],
        "response_metadata": {"next_cursor": ""},
    })

    client = AsyncMock()
    client.get = AsyncMock(side_effect=[page1, page2])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(slack_mod.httpx, "AsyncClient", MagicMock(return_value=client))

    items = await SlackConnector().list_items(FakeConnection())

    assert [i.id for i in items] == ["C1", "C2"]
    assert client.get.await_count == 2
    first_call_kwargs = client.get.await_args_list[0].kwargs
    second_call_kwargs = client.get.await_args_list[1].kwargs
    assert "cursor" not in first_call_kwargs["params"]
    assert second_call_kwargs["params"]["cursor"] == "CURSOR1"
