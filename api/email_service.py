"""Invitation email delivery. Provider chosen by EMAIL_PROVIDER.

There is no email infrastructure elsewhere in Arteamis-fe, so `console` is the
default and it does NOT deliver: it returns False, which makes the invitation
endpoint return a copyable shareable link instead. `resend` and `smtp` do real
delivery. A delivery failure is logged and returns False (fall back to the
link) — it never raises into the request path.

Mirrors the provider-selection pattern of
arteamis-system/backend/app/auth/email_sender.py (there used for single-purpose
OTP delivery; here adapted to a generic invite email with a workspace/project
context line).
"""

import os
from typing import Optional, Tuple

import httpx
from loguru import logger


def _provider() -> str:
    return os.getenv("EMAIL_PROVIDER", "console").strip().lower()


def _subject_and_body(
    workspace_name: str, project_name: Optional[str], invite_url: str
) -> Tuple[str, str]:
    where = (
        f'the "{project_name}" project in {workspace_name}'
        if project_name
        else workspace_name
    )
    subject = f"You're invited to {workspace_name} on Arteamis"
    body = (
        f"You have been invited to join {where} on Arteamis.\n\n"
        f"Accept your invitation here:\n{invite_url}\n\n"
        f"This link expires in 7 days. If you did not expect this, you can ignore this email."
    )
    return subject, body


async def _send_resend(to_email: str, subject: str, body: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {os.getenv('RESEND_API_KEY')}"},
            json={
                "from": os.getenv("EMAIL_FROM"),
                "to": [to_email],
                "subject": subject,
                "text": body,
            },
        )
        resp.raise_for_status()


async def _send_smtp(to_email: str, subject: str, body: str) -> None:
    import smtplib
    from email.mime.text import MIMEText

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.getenv("EMAIL_FROM", "")
    msg["To"] = to_email
    host = os.getenv("SMTP_HOST", "localhost")
    port = int(os.getenv("SMTP_PORT", "587"))
    # smtplib is blocking; acceptable for a low-volume invite send.
    with smtplib.SMTP(host, port) as server:
        server.starttls()
        user = os.getenv("SMTP_USER")
        if user:
            server.login(user, os.getenv("SMTP_PASSWORD", ""))
        server.send_message(msg)


async def send_invite_email(
    to_email: str,
    invite_url: str,
    workspace_name: str,
    project_name: Optional[str] = None,
) -> bool:
    """Return True only when the email was actually delivered."""
    provider = _provider()
    subject, body = _subject_and_body(workspace_name, project_name, invite_url)
    try:
        if provider == "resend":
            await _send_resend(to_email, subject, body)
            return True
        if provider == "smtp":
            await _send_smtp(to_email, subject, body)
            return True
        # console (default): do not deliver; only log the link in DEBUG dev.
        if os.getenv("DEBUG", "").lower() in ("1", "true", "yes"):
            logger.info(f"[invite] {to_email} -> {invite_url}")
        return False
    except Exception as e:
        logger.warning(f"Invite email delivery failed for {to_email}: {e}")
        return False
