"""In-process single-use CSRF state store for the OAuth handshake.

State lives ~10 minutes and is consumed exactly once. In-process is fine for a
single-instance deployment; a future multi-process deploy would swap this for a
shared store (Redis/DB) behind the same two functions.
"""
import secrets
import time
from typing import Dict

_TTL_SECONDS = 600
_states: Dict[str, float] = {}


def _purge(now: float) -> None:
    for key in [k for k, exp in _states.items() if exp < now]:
        _states.pop(key, None)


def create_state() -> str:
    now = time.monotonic()
    _purge(now)
    token = secrets.token_urlsafe(32)
    _states[token] = now + _TTL_SECONDS
    return token


def consume_state(state: str) -> bool:
    now = time.monotonic()
    _purge(now)
    return _states.pop(state, None) is not None
