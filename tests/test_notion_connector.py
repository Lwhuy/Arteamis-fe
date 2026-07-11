from unittest.mock import AsyncMock, MagicMock

import pytest

from open_notebook.domain.connectors import notion as notion_mod
from open_notebook.domain.connectors.notion import NotionConnector


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


def _page(page_id, title):
    return {
        "id": page_id,
        "last_edited_time": "2024-01-01T00:00:00Z",
        "properties": {"title": {"type": "title", "title": [{"plain_text": title}]}},
    }


def test_authorize_url_shape(monkeypatch):
    monkeypatch.setenv("NOTION_CLIENT_ID", "cid")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "sec")
    url = NotionConnector().authorize_url("ST", "http://localhost:5055/api/connectors/notion/callback")
    assert "api.notion.com/v1/oauth/authorize" in url
    assert "owner=user" in url
    assert "state=ST" in url


def test_blocks_to_markdown_renders_headings_and_paragraphs():
    blocks = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Title"}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hello world"}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "point"}]}},
    ]
    md = NotionConnector()._blocks_to_markdown(blocks)
    assert "# Title" in md
    assert "Hello world" in md
    assert "- point" in md


@pytest.mark.asyncio
async def test_list_items_follows_next_cursor(monkeypatch):
    page1 = _resp({
        "results": [_page("p1", "First")],
        "has_more": True,
        "next_cursor": "CURSOR1",
    })
    page2 = _resp({
        "results": [_page("p2", "Second")],
        "has_more": False,
        "next_cursor": None,
    })

    client = AsyncMock()
    client.post = AsyncMock(side_effect=[page1, page2])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(notion_mod.httpx, "AsyncClient", MagicMock(return_value=client))

    items = await NotionConnector().list_items(FakeConnection())

    assert [i.id for i in items] == ["p1", "p2"]
    assert client.post.await_count == 2
    first_call_kwargs = client.post.await_args_list[0].kwargs
    second_call_kwargs = client.post.await_args_list[1].kwargs
    assert "start_cursor" not in first_call_kwargs["json"]
    assert second_call_kwargs["json"]["start_cursor"] == "CURSOR1"
