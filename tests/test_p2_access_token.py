"""create_access_token mints a workspace-scoped token decode_access_token reads."""

import os

# Ensure a JWT secret exists before importing the security module (it reads
# config at import time). Mirrors tests/conftest.py's env-first pattern.
os.environ.setdefault("JWT_SECRET", "test-secret-p2-access-token")

import pytest

from api.security import create_access_token, decode_access_token
from open_notebook.exceptions import AuthenticationError


def test_access_token_round_trips_workspace_and_role():
    token = create_access_token(
        user_id="user:abc", workspace_id="workspace:xyz", role="owner"
    )
    ctx = decode_access_token(token)
    assert ctx.user_id == "user:abc"
    assert ctx.workspace_id == "workspace:xyz"
    assert ctx.role == "owner"


def test_access_token_rejects_non_user_subject():
    with pytest.raises(AuthenticationError):
        create_access_token(user_id="abc", workspace_id="workspace:xyz", role="owner")


def test_access_token_rejects_non_workspace_scope():
    with pytest.raises(AuthenticationError):
        create_access_token(user_id="user:abc", workspace_id="xyz", role="owner")


def test_access_token_round_trips_personal_workspace():
    # No special-case for a personal workspace id — same claim shape either way.
    token = create_access_token(
        user_id="user:abc", workspace_id="workspace:personal-abc", role="owner"
    )
    ctx = decode_access_token(token)
    assert ctx.workspace_id == "workspace:personal-abc"
