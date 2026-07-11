from typing import List
from urllib.parse import urlencode

import httpx
from loguru import logger

from open_notebook.domain.connection import Connection
from open_notebook.domain.connectors import _register
from open_notebook.domain.connectors.base import (
    BaseConnector,
    ConnectorItem,
    ImportedDoc,
    TokenSet,
)

_AUTH = "https://slack.com/oauth/v2/authorize"
_TOKEN = "https://slack.com/api/oauth.v2.access"
_API = "https://slack.com/api"
_SCOPES = ["channels:read", "channels:history", "pins:read", "files:read"]

_MAX_ITEMS = 500


class SlackConnector(BaseConnector):
    provider = "slack"
    display_name = "Slack"
    description = "Pinned messages, canvases, bookmarks, and knowledge artifacts"
    scopes = _SCOPES
    client_id_env = "SLACK_CLIENT_ID"
    client_secret_env = "SLACK_CLIENT_SECRET"

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._env(self.client_id_env),
            "redirect_uri": redirect_uri,
            "scope": ",".join(self.scopes),
            "state": state,
        }
        return f"{_AUTH}?{urlencode(params, safe=':,')}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_TOKEN, data={
                "code": code,
                "client_id": self._env(self.client_id_env),
                "client_secret": self._env(self.client_secret_env),
                "redirect_uri": redirect_uri,
            })
            resp.raise_for_status()
            tok = resp.json()
        if not tok.get("ok"):
            raise ValueError(f"Slack OAuth failed: {tok.get('error')}")
        token = tok.get("access_token") or tok["authed_user"]["access_token"]
        return TokenSet(
            access_token=token,
            refresh_token=None,  # Slack bot tokens do not expire
            scopes=self.scopes,
            account_label=tok.get("team", {}).get("name", "Slack"),
        )

    async def list_items(self, conn: Connection) -> List[ConnectorItem]:
        token = conn.access_token.get_secret_value()
        params = {"types": "public_channel", "limit": 200}
        items: List[ConnectorItem] = []
        capped = False
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                r = await client.get(f"{_API}/conversations.list",
                                     params=params,
                                     headers={"Authorization": f"Bearer {token}"})
                r.raise_for_status()
                data = r.json()
                if not data.get("ok"):
                    raise ValueError(f"Slack conversations.list failed: {data.get('error')}")
                items.extend(
                    ConnectorItem(id=ch["id"], kind="channel", title=f"#{ch['name']}")
                    for ch in data.get("channels", [])
                )
                next_cursor = data.get("response_metadata", {}).get("next_cursor")
                if next_cursor and len(items) < _MAX_ITEMS:
                    params = {**params, "cursor": next_cursor}
                    continue
                if next_cursor and len(items) >= _MAX_ITEMS:
                    capped = True
                break
        if capped:
            logger.warning(f"slack list_items capped at {_MAX_ITEMS} items")
        return items[:_MAX_ITEMS]

    def _render_pins(self, pins: List[dict]) -> str:
        out = []
        for p in pins:
            msg = p.get("message") or {}
            text = msg.get("text")
            if text:
                out.append(text)
        return "\n\n---\n\n".join(out)

    async def fetch_content(self, conn: Connection, item: ConnectorItem) -> ImportedDoc:
        token = conn.access_token.get_secret_value()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{_API}/pins.list",
                                 params={"channel": item.id},
                                 headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            data = r.json()
        if not data.get("ok"):
            raise ValueError(f"Slack pins.list failed: {data.get('error')}")
        content = self._render_pins(data.get("items", []))
        return ImportedDoc(title=f"Slack {item.title} — pinned", content=content or "(no pinned content)")


_register(SlackConnector)
