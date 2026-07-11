import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import List, Optional
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

_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN = "https://oauth2.googleapis.com/token"
_FILES = "https://www.googleapis.com/drive/v3/files"

# Google-native mime -> export mime. Everything else is downloaded as-is.
_EXPORT = {
    "application/vnd.google-apps.document": "text/markdown",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


class GDriveConnector(BaseConnector):
    provider = "gdrive"
    display_name = "Google Drive"
    description = "Native connector with file-level permissions"
    scopes = [
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    ]
    client_id_env = "GDRIVE_CLIENT_ID"
    client_secret_env = "GDRIVE_CLIENT_SECRET"

    def _export_mime(self, mime: str) -> Optional[str]:
        return _EXPORT.get(mime)

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._env(self.client_id_env),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{_AUTH}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_TOKEN, data={
                "code": code,
                "client_id": self._env(self.client_id_env),
                "client_secret": self._env(self.client_secret_env),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
            resp.raise_for_status()
            tok = resp.json()
        label = await self._account_email(tok["access_token"])
        return TokenSet(
            access_token=tok["access_token"],
            refresh_token=tok.get("refresh_token"),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=tok.get("expires_in", 3600)),
            scopes=self.scopes,
            account_label=label,
        )

    async def refresh(self, refresh_token: str) -> TokenSet:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_TOKEN, data={
                "refresh_token": refresh_token,
                "client_id": self._env(self.client_id_env),
                "client_secret": self._env(self.client_secret_env),
                "grant_type": "refresh_token",
            })
            resp.raise_for_status()
            tok = resp.json()
        return TokenSet(
            access_token=tok["access_token"],
            refresh_token=refresh_token,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=tok.get("expires_in", 3600)),
            scopes=self.scopes,
        )

    async def _account_email(self, access_token: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if r.status_code == 200:
                    return r.json().get("email", "Google Drive")
        except Exception:  # noqa: BLE001 — label is cosmetic; never fail connect over it
            pass
        return "Google Drive"

    async def list_items(self, conn: Connection) -> List[ConnectorItem]:
        token = conn.access_token.get_secret_value()
        params = {
            "pageSize": 100,
            "fields": "files(id,name,mimeType,modifiedTime)",
            "q": "trashed = false and mimeType != 'application/vnd.google-apps.folder'",
            "orderBy": "modifiedTime desc",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(_FILES, params=params,
                                  headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            files = r.json().get("files", [])
        return [
            ConnectorItem(id=f["id"], kind="file", title=f["name"],
                          mime=f.get("mimeType"), modified_at=f.get("modifiedTime"))
            for f in files
        ]

    async def fetch_content(self, conn: Connection, item: ConnectorItem) -> ImportedDoc:
        token = conn.access_token.get_secret_value()
        headers = {"Authorization": f"Bearer {token}"}
        export_mime = self._export_mime(item.mime or "")
        async with httpx.AsyncClient(timeout=60) as client:
            if export_mime:
                r = await client.get(f"{_FILES}/{item.id}/export",
                                     params={"mimeType": export_mime}, headers=headers)
                r.raise_for_status()
                return ImportedDoc(title=item.title, content=r.text)
            # Binary/other: download bytes to a temp file for upload ingestion.
            r = await client.get(f"{_FILES}/{item.id}", params={"alt": "media"}, headers=headers)
            r.raise_for_status()
            suffix = os.path.splitext(item.title)[1] or ""
            fd, path = tempfile.mkstemp(suffix=suffix)
            with os.fdopen(fd, "wb") as fh:
                fh.write(r.content)
            return ImportedDoc(title=item.title, file_path=path)


_register(GDriveConnector)
