"""Auth business logic (routers stay thin, per api/AGENTS.md).

register/login operate on the identity plane only. build_session_payload is
the workspace-aware seam: it ALWAYS auto-provisions the caller's personal
workspace and mints a workspace-scoped access token, so a logged-in user
never holds a bare identity-only session (see build_session_payload docstring).
"""

from typing import Optional

from api.security import create_access_token
from api.workspace_service import ensure_personal_workspace, list_memberships
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


async def build_session_payload(user: User) -> dict:
    """Session payload for register/login/refresh/Google-callback.

    ALWAYS auto-provisions (idempotently) the caller's personal workspace and
    returns a workspace-scoped token for it — a logged-in user never holds a
    bare identity-only session. `needs_onboarding` is repurposed from P1's
    hard-coded placeholder: it no longer gates anything, it only signals
    "no company workspace yet" for an optional, dismissible frontend prompt.
    Every call resets the ACTIVE workspace to Personal (stated default
    decision — see the spec's Open questions) even if the user also owns
    companies; switching to one is a per-session action.
    """
    personal = await ensure_personal_workspace(str(user.id))
    memberships = await list_memberships(str(user.id))
    has_company = any(m["kind"] == "company" for m in memberships)
    access_token = create_access_token(
        user_id=str(user.id), workspace_id=personal.id or "", role="owner"
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "needs_onboarding": not has_company,
        "active_workspace_id": personal.id,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
        },
        "memberships": memberships,
    }
