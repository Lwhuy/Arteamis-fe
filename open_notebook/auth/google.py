"""Google OAuth 2.0 authorization-code exchange (port of arteamis-system).

build_authorize_url starts the flow; exchange_code_for_userinfo completes it and
returns the verified profile. Tests monkeypatch exchange_code_for_userinfo.
"""

import urllib.parse

import httpx

from api.auth_config import get_auth_config

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def build_authorize_url(state: str) -> str:
    cfg = get_auth_config()
    params = {
        "client_id": cfg.google_client_id or "",
        "redirect_uri": cfg.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


async def exchange_code_for_userinfo(code: str) -> dict:
    """Exchange an authorization code for the user's Google profile.

    Returns a dict with at least `sub`, `email`, `email_verified`, and `name`.
    Raises httpx.HTTPStatusError on a failed exchange.
    """
    cfg = get_auth_config()
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            _TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": cfg.google_client_id or "",
                "client_secret": cfg.google_client_secret or "",
                "redirect_uri": cfg.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        info_resp = await client.get(
            _USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
        )
        info_resp.raise_for_status()
        return info_resp.json()
