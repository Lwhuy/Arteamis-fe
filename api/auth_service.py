"""Auth business logic (routers stay thin, per api/AGENTS.md).

register/login operate on the identity plane only; workspace selection and
workspace-scoped tokens arrive in P2 (build_session_payload's workspace-aware
branch). Personal-workspace auto-provisioning is done in P2, not P1 — P1's
register/login leaves the user authenticated on an identity token only.
"""

from typing import Optional

from api.security import create_identity_token
from open_notebook.domain.user import _PH, AuthIdentity, User
from open_notebook.exceptions import AuthenticationError, DuplicateResourceError

# Generic message: never reveal whether the email exists or the password was
# the wrong part (prevents user enumeration).
_INVALID_CREDENTIALS = "Invalid email or password"

# Timing side-channel guard: without this, an unknown email short-circuits
# before any argon2 verify runs, while a known email + wrong password pays
# the full argon2 cost (tens-hundreds of ms). That latency gap re-enables
# user enumeration despite the identical error message above. _DUMMY_USER
# carries a fixed, precomputed hash so the unknown-email branch can run a
# throwaway verify_password() of comparable cost. Reuses the module-level
# _PH hasher from open_notebook.domain.user (no second PasswordHasher).
_DUMMY_PASSWORD_HASH = _PH.hash("dummy-password-for-timing")
_DUMMY_USER = User(email="timing-dummy@example.invalid", password_hash=_DUMMY_PASSWORD_HASH)


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
        # Pay the same argon2 cost as the wrong-password branch below so
        # response latency doesn't reveal whether the account exists.
        try:
            await _DUMMY_USER.verify_password(password)
        except Exception:
            pass
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
