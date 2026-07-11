import asyncio
from datetime import datetime, timezone
from typing import ClassVar, Literal, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from loguru import logger
from pydantic import field_validator

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.base import ObjectModel
from open_notebook.exceptions import DatabaseOperationError, InvalidInputError

# Module-level hasher: argon2 defaults are memory-hard and safe. Reused across
# calls (creating a PasswordHasher per hash is wasteful). Hash/verify are
# CPU-bound and synchronous, so callers run them via asyncio.to_thread.
_PH = PasswordHasher()


class User(ObjectModel):
    table_name: ClassVar[str] = "user"
    nullable_fields: ClassVar[set[str]] = {"password_hash", "display_name", "avatar_url"}
    email: str
    display_name: Optional[str] = None
    password_hash: Optional[str] = None
    avatar_url: Optional[str] = None

    @staticmethod
    def normalize_email(raw: str) -> str:
        return (raw or "").strip().lower()

    @field_validator("email")
    @classmethod
    def _normalize_email_field(cls, v: str) -> str:
        normalized = User.normalize_email(v)
        if not normalized:
            raise InvalidInputError("Email cannot be empty")
        return normalized

    async def set_password(self, raw: str) -> None:
        if not raw:
            raise InvalidInputError("Password cannot be empty")
        self.password_hash = await asyncio.to_thread(_PH.hash, raw)

    async def verify_password(self, raw: str) -> bool:
        if not self.password_hash:
            return False  # Google-only account: no password set.
        try:
            await asyncio.to_thread(_PH.verify, self.password_hash, raw)
            return True
        except VerifyMismatchError:
            return False
        except Exception as e:
            logger.warning(f"Password verify error for user {self.id}: {e}")
            return False

    @classmethod
    async def get_by_email(cls, email: str) -> Optional["User"]:
        normalized = cls.normalize_email(email)
        result = await repo_query(
            "SELECT * FROM user WHERE email = $email", {"email": normalized}
        )
        return cls(**result[0]) if result else None

    @classmethod
    async def get_by_identity(cls, provider: str, subject: str) -> Optional["User"]:
        result = await repo_query(
            """
            SELECT * FROM user WHERE id IN (
                SELECT VALUE user FROM auth_identity
                WHERE provider = $provider AND provider_subject = $subject
            )
            """,
            {"provider": provider, "subject": subject},
        )
        return cls(**result[0]) if result else None

    @classmethod
    async def upsert_with_identity(
        cls,
        provider: str,
        subject: str,
        email: str,
        display_name: Optional[str] = None,
    ) -> "User":
        """Find-or-create the user for this identity, then ensure the link.

        Matching order: (provider, subject) identity → user by email → new user.
        Keeps ONE account when the same verified email signs in via both Google
        and email+password.
        """
        normalized = cls.normalize_email(email)

        # 1. Existing identity → stamp last_login and return its user.
        existing = await cls.get_by_identity(provider, subject)
        if existing is not None:
            try:
                await repo_query(
                    """
                    UPDATE auth_identity SET last_login_at = time::now()
                    WHERE provider = $provider AND provider_subject = $subject
                    """,
                    {"provider": provider, "subject": subject},
                )
            except Exception as e:
                logger.warning(f"Failed to stamp last_login_at: {e}")
            return existing

        # 2. Existing user by email, else 3. create a new user.
        user = await cls.get_by_email(normalized)
        if user is None:
            user = cls(email=normalized, display_name=display_name)
            await user.save()

        # Link the new identity.
        identity = AuthIdentity(
            provider=provider,
            provider_subject=subject,
            user=user.id or "",
            email=normalized,
            last_login_at=datetime.now(timezone.utc),
        )
        try:
            await identity.save()
        except Exception as e:
            logger.error(f"Failed to link auth_identity for user {user.id}: {e}")
            raise DatabaseOperationError(e)
        return user


class AuthIdentity(ObjectModel):
    table_name: ClassVar[str] = "auth_identity"
    nullable_fields: ClassVar[set[str]] = {"email", "last_login_at"}
    provider: Literal["email_password", "google"]
    provider_subject: str
    user: str
    email: Optional[str] = None
    last_login_at: Optional[datetime] = None

    def _prepare_save_data(self) -> dict:
        """Coerce the `user` link to a RecordID so the SCHEMAFULL record<user>
        field validates (mirrors Source.command handling)."""
        data = super()._prepare_save_data()
        if data.get("user") is not None:
            data["user"] = ensure_record_id(data["user"])
        return data
