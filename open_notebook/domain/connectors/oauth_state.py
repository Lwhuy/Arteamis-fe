"""In-process single-use CSRF state store for the OAuth handshake.

State lives ~10 minutes and is consumed exactly once. In-process is fine for a
single-instance deployment; a future multi-process deploy would swap this for a
shared store (Redis/DB) behind the same two functions.

The stored value carries the workspace_id + user_id of the request that
initiated the OAuth flow, so the (unauthenticated) provider callback can
recover which workspace/user to attribute the resulting connection to.
"""
import secrets
import time
from typing import Dict, Optional, Tuple

_TTL_SECONDS = 600
_states: Dict[str, Tuple[str, str, float]] = {}


def _purge(now: float) -> None:
    for key in [k for k, (_, _, exp) in _states.items() if exp < now]:
        _states.pop(key, None)


def create_state(workspace_id: str, user_id: str) -> str:
    now = time.monotonic()
    _purge(now)
    token = secrets.token_urlsafe(32)
    _states[token] = (workspace_id, user_id, now + _TTL_SECONDS)
    return token


def consume_state(state: str) -> Optional[Tuple[str, str]]:
    now = time.monotonic()
    _purge(now)
    entry = _states.pop(state, None)
    if entry is None:
        return None
    workspace_id, user_id, _ = entry
    return (workspace_id, user_id)
