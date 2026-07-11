"""Auth business logic (routers stay thin, per api/AGENTS.md).

register/login operate on the identity plane only; workspace selection and
workspace-scoped tokens arrive in P2 (build_session_payload's workspace-aware
branch). Personal-workspace auto-provisioning is done in P2, not P1 — P1's
register/login leaves the user authenticated on an identity token only.
"""

from typing import Optional

from api.security import create_identity_token
from open_notebook.domain.user import AuthIdentity, User
from open_notebook.exceptions import AuthenticationError, DuplicateResourceError

# Generic message: never reveal whether the email exists or the password was
# the wrong part (prevents user enumeration).
_INVALID_CREDENTIALS = "Invalid email or password"


async def register(email: str, password: str, display_name: Optional[str]) -> User:
    normalized = User.normalize_email(email)
    if await User.get_by_email(normalized) is not None:
        raise DuplicateResourceError("Email already registered")

    user = User(email=normalized, display_name=display_name)
    await user.set_password(password)
    await user.save()

    identity = AuthIdentity(
        provider="email_password",
        provider_subject=normalized,
        user=user.id or "",
        email=normalized,
    )
    await identity.save()
    return user


async def login(email: str, password: str) -> User:
    user = await User.get_by_email(email)
    if user is None:
        raise AuthenticationError(_INVALID_CREDENTIALS)
    if not await user.verify_password(password):
        raise AuthenticationError(_INVALID_CREDENTIALS)
    return user


def build_session_payload(user: User) -> dict:
    """The body returned after any successful register/login/refresh.

    P1 always issues an identity token (no workspace yet). P2 replaces the
    needs_onboarding/memberships/active_workspace_id surface with the real,
    workspace-aware branch WITHOUT changing this response shape — this is
    where P2 attaches the user's auto-provisioned default personal workspace
    (not done in P1).
    """
    return {
        "access_token": create_identity_token(user.id or ""),
        "token_type": "bearer",
        "needs_onboarding": True,
        "active_workspace_id": None,
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
        },
        "memberships": [],
    }
