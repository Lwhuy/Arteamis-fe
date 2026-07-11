import base64
from typing import List
from urllib.parse import urlencode

import httpx

from open_notebook.domain.connection import Connection
from open_notebook.domain.connectors import _register
from open_notebook.domain.connectors.base import (
    BaseConnector,
    ConnectorItem,
    ImportedDoc,
    TokenSet,
)

_AUTH = "https://api.notion.com/v1/oauth/authorize"
_TOKEN = "https://api.notion.com/v1/oauth/token"
_SEARCH = "https://api.notion.com/v1/search"
_BLOCKS = "https://api.notion.com/v1/blocks"
_VERSION = "2022-06-28"


class NotionConnector(BaseConnector):
    provider = "notion"
    display_name = "Notion"
    description = "Pages, databases, and workspace content"
    scopes: List[str] = []  # Notion grants page access interactively, no scope strings
    client_id_env = "NOTION_CLIENT_ID"
    client_secret_env = "NOTION_CLIENT_SECRET"

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._env(self.client_id_env),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "owner": "user",
            "state": state,
        }
        return f"{_AUTH}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        basic = base64.b64encode(
            f"{self._env(self.client_id_env)}:{self._env(self.client_secret_env)}".encode()
        ).decode()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_TOKEN, json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            }, headers={"Authorization": f"Basic {basic}",
                        "Content-Type": "application/json"})
            resp.raise_for_status()
            tok = resp.json()
        return TokenSet(
            access_token=tok["access_token"],
            refresh_token=None,  # Notion tokens don't expire
            scopes=[],
            account_label=tok.get("workspace_name") or "Notion",
        )

    def _headers(self, conn: Connection) -> dict:
        return {
            "Authorization": f"Bearer {conn.access_token.get_secret_value()}",
            "Notion-Version": _VERSION,
            "Content-Type": "application/json",
        }

    async def list_items(self, conn: Connection) -> List[ConnectorItem]:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(_SEARCH, json={
                "filter": {"property": "object", "value": "page"},
                "page_size": 100,
            }, headers=self._headers(conn))
            r.raise_for_status()
            results = r.json().get("results", [])
        items: List[ConnectorItem] = []
        for p in results:
            title = self._page_title(p)
            items.append(ConnectorItem(
                id=p["id"], kind="page", title=title,
                modified_at=p.get("last_edited_time")))
        return items

    def _page_title(self, page: dict) -> str:
        props = page.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                parts = prop.get("title", [])
                if parts:
                    return "".join(t.get("plain_text", "") for t in parts) or "Untitled"
        return "Untitled"

    def _rich(self, block: dict, key: str) -> str:
        return "".join(t.get("plain_text", "") for t in block.get(key, {}).get("rich_text", []))

    def _blocks_to_markdown(self, blocks: List[dict]) -> str:
        lines: List[str] = []
        for b in blocks:
            t = b.get("type")
            if t == "heading_1":
                lines.append(f"# {self._rich(b, 'heading_1')}")
            elif t == "heading_2":
                lines.append(f"## {self._rich(b, 'heading_2')}")
            elif t == "heading_3":
                lines.append(f"### {self._rich(b, 'heading_3')}")
            elif t == "bulleted_list_item":
                lines.append(f"- {self._rich(b, 'bulleted_list_item')}")
            elif t == "numbered_list_item":
                lines.append(f"1. {self._rich(b, 'numbered_list_item')}")
            elif t == "paragraph":
                lines.append(self._rich(b, "paragraph"))
        return "\n\n".join(line for line in lines if line is not None)

    async def fetch_content(self, conn: Connection, item: ConnectorItem) -> ImportedDoc:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{_BLOCKS}/{item.id}/children",
                                 params={"page_size": 100}, headers=self._headers(conn))
            r.raise_for_status()
            blocks = r.json().get("results", [])
        return ImportedDoc(title=item.title, content=self._blocks_to_markdown(blocks))


_register(NotionConnector)
