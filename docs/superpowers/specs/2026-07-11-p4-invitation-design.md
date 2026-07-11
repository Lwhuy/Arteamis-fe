# P4 — Invitation Flow (Company + Project) — Design Spec
Date: 2026-07-11 · Branch: feat/auth-multitenancy · Status: Draft

## Goal
Add an invitation system that arteamis-system scaffolded (`membership.status = "invited"`) but never implemented. A company owner/admin can invite a person by email to join either the **company** (with a company role) or a specific **project** (with a project role). Accepting an invite creates/links a `user` and an **active** membership (and, for project invites, a `project_member`). Invite links are delivered by email when email infra is configured; when it is not (the default in Arteamis-fe today — there is no SMTP/Resend code anywhere in `api/` or `open_notebook/`), the create endpoint returns a **shareable link** in the response so the admin can copy/paste it.

## Depends on / Provides
**Depends on:**
- P1 (users/auth): `user` + `auth_identity` tables; identity JWT + company-scoped access token; the `api/security.py` token decoders + `AuthContext`. Also the login/signup pages and `auth-store`.
- P2 (company/membership/RBAC): `company` + `membership` tables; the shared **`api/deps.py`** module with `get_identity` (identity or access token → `user_id`), `get_auth_context` (access token → `AuthContext{user_id, company_id, role}`), and the `require_role("owner","admin")` factory — all reused here, not redefined. Also `POST /auth/switch-company/{company_id}` (mint a company-scoped token after accept) and a company Members view/route this spec extends. **Note:** the members-list endpoint `GET /api/companies/{company_id}/members` is consumed by this spec's Members panel; if P2 does not ship it, P4 adds it alongside the invitations router.
- P3 (project): `project` (repurposed `notebook`) + `project_member` tables, both company-scoped.

**Provides:**
- `invitation` table + `Invitation` domain model.
- Create / list / preview / accept / revoke invitation endpoints (company- and project-scoped branches).
- Email delivery abstraction (`api/email_service.py`, console/resend/smtp, mirrors `arteamis-system/backend/app/auth/email_sender.py`) with shareable-link fallback.
- Frontend: invite dialog + pending-invites list inside the Members panel, and a public accept-invite page/flow.

## Scope (in)
- One `invitation` row models both a company invite (`project` null) and a project invite (`project` set).
- Token generation (raw token in the link) + `token_hash` at rest; 7-day expiry.
- Accept flow for (a) brand-new user who must register/login first, (b) already-logged-in user; email-mismatch rejection.
- RBAC: only company `owner`/`admin` may create/list/revoke; `410` on expired/revoked at accept.

## Out of scope
- Bulk / CSV invites, invite-by-link-without-email (open signup links), seat limits/billing.
- Re-parenting existing members between projects, transferring ownership.
- The tenant-scoping helper and role-gating guards (P6). This spec enforces RBAC per-endpoint via `require_role`; it does not build the global scoping layer.

## Data model changes (SurrealDB migration)
New migration pair, **`22.surrealql` / `22_down.surrealql`** — P4 owns migration 22 in the canonical sequence (current highest on disk is `18`; P1=19, P2=20, P3=21, P4=22, P5=23; P6 adds no migration). Register both in the hard-coded lists `up_migrations` / `down_migrations` in `open_notebook/database/async_migrate.py` (migrations are NOT auto-discovered — see backend AGENTS.md).

`open_notebook/database/migrations/22.surrealql`:
```surql
-- Migration 22: Invitations (company + project scoped)
DEFINE TABLE IF NOT EXISTS invitation SCHEMALESS;

DEFINE FIELD IF NOT EXISTS company    ON TABLE invitation TYPE record<company>;
DEFINE FIELD IF NOT EXISTS email      ON TABLE invitation TYPE string
  ASSERT string::is::email($value);
DEFINE FIELD IF NOT EXISTS role       ON TABLE invitation TYPE string
  ASSERT $value IN ["owner","admin","member"];
-- The physical project table stays named `notebook` (P3 repurpose-in-place);
-- it is exposed as "project" at the API/UI. There is NO physical `project` table.
DEFINE FIELD IF NOT EXISTS project    ON TABLE invitation TYPE option<record<notebook>>;
DEFINE FIELD IF NOT EXISTS token_hash ON TABLE invitation TYPE string;
DEFINE FIELD IF NOT EXISTS status     ON TABLE invitation TYPE string
  ASSERT $value IN ["pending","accepted","revoked","expired"] DEFAULT "pending";
DEFINE FIELD IF NOT EXISTS invited_by ON TABLE invitation TYPE record<user>;
DEFINE FIELD IF NOT EXISTS expires_at ON TABLE invitation TYPE datetime;
DEFINE FIELD IF NOT EXISTS created    ON TABLE invitation TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS updated    ON TABLE invitation TYPE option<datetime>;

-- Accept looks up by token_hash; must be unique + indexed.
DEFINE INDEX IF NOT EXISTS idx_invitation_token_hash ON TABLE invitation FIELDS token_hash UNIQUE;
-- Listing pending invites for a company, and the duplicate-pending guard.
DEFINE INDEX IF NOT EXISTS idx_invitation_company_status ON TABLE invitation FIELDS company, status;
DEFINE INDEX IF NOT EXISTS idx_invitation_company_email ON TABLE invitation FIELDS company, email;
```
`open_notebook/database/migrations/22_down.surrealql`:
```surql
REMOVE TABLE IF EXISTS invitation;
```
Notes: `email`/`role` are stored raw so the invite is scoped to an email even before that email has a `user`. `role` holds the **company** role for company invites (`admin`/`member`; `owner` is never invited) and the **project** role for project invites (`admin`/`member`). SCHEMALESS matches the existing tables (e.g. `notebook`); ASSERTs give cheap validation.

## Backend: endpoints, services, domain models (file paths)

### Domain model — `open_notebook/domain/invitation.py` (new)
`Invitation(ObjectModel)` subclassing `open_notebook/domain/base.py`:
- `table_name: ClassVar[str] = "invitation"`
- `nullable_fields = {"project"}` (so a company invite persists `project = None` via `_prepare_save_data`).
- Fields: `company: str`, `email: str`, `role: str`, `project: Optional[str] = None`, `token_hash: str`, `status: str = "pending"`, `invited_by: str`, `expires_at: datetime`.
- Helpers: `is_expired(self) -> bool` (`expires_at < datetime.now(tz)`); `classmethod async def get_by_token_hash(cls, token_hash) -> Optional["Invitation"]` via `repo_query("SELECT * FROM invitation WHERE token_hash = $h LIMIT 1", {...})`.
- Persistence via inherited `save()` / `delete()`; all DB access `await`-ed through `repo_*` helpers.

### Service — `api/invitation_service.py` (new; routers stay thin per api/AGENTS.md)
- `generate_token() -> tuple[str, str]`: `raw = secrets.token_urlsafe(32)`; `token_hash = hashlib.sha256(raw.encode()).hexdigest()`. Return `(raw, token_hash)`. Only the hash is stored; the raw token exists only in the link.
- `build_invite_url(raw_token) -> str`: `f"{APP_BASE_URL}/invite/{raw_token}"`, where `APP_BASE_URL = os.getenv("OPEN_NOTEBOOK_APP_URL", "http://localhost:3000")` (env read via `os.getenv`, matching `api/main.py`'s `CORS_ORIGINS` pattern).
- `create_invitation(company_id, inviter_user_id, email, role, project_id) -> tuple[Invitation, str]`: validates (see RBAC + Error handling), rotates any existing pending invite for the same `(company,email,project)`, persists, returns `(invitation, raw_token)`.
- `accept_invitation(raw_token, user_id) -> AcceptResult`: the accept state machine (below).
- `expire_if_needed(inv)`: if `pending` and past `expires_at`, set `status="expired"`, `save()`, and signal 410 to the caller.

### Email — `api/email_service.py` (new; mirrors `arteamis-system/.../auth/email_sender.py`)
`async def send_invite_email(to_email, invite_url, company_name, project_name) -> bool` returning `True` when actually delivered:
- Provider chosen by `os.getenv("EMAIL_PROVIDER", "console")` ∈ `console|resend|smtp`.
- `console` (default): log the URL when `DEBUG`, return `False` (not delivered) → triggers the shareable-link fallback.
- `resend`: POST `https://api.resend.com/emails` with `RESEND_API_KEY` / `EMAIL_FROM` (copy the `_send_resend` shape), return `True`.
- `smtp`: `smtplib.SMTP` with `SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD` (copy `_send_smtp`), return `True`.
Never raise on a delivery failure into the request path beyond logging; a failed send falls back to returning the link.

### Schemas — add to `api/models.py` (Pydantic, alongside existing `*Create`/`*Response`)
- `InvitationCreate`: `email: EmailStr`, `role: Literal["admin","member"]`, `project_id: Optional[str] = None`.
- `InvitationResponse`: `id`, `email`, `role`, `project_id: Optional[str]`, `project_name: Optional[str]`, `status`, `invited_by`, `expires_at`, `created`.
- `InvitationCreateResponse`: `invitation: InvitationResponse`, `email_sent: bool`, `share_url: Optional[str]` (present only when `email_sent is False`).
- `InvitationPreviewResponse` (public, no secrets): `company_name`, `role`, `email`, `project_name: Optional[str]`, `status`, `expired: bool`.
- `AcceptInvitationResponse`: `company_id`, `role`, `project_id: Optional[str]`, `membership_status: "active"`.

### Router — `api/routers/invitations.py` (new; registered in `api/main.py` under the `/api` prefix like the other routers)
| Method + path | Auth dep | Purpose |
|---|---|---|
| `POST /api/companies/{company_id}/invitations` | `require_role("owner","admin")` | Create a company or project invite; send email or return `share_url`. `201`. |
| `GET  /api/companies/{company_id}/invitations` | `require_role("owner","admin")` | List invites (query `?status=pending`). Powers the Members panel's pending list. |
| `POST /api/companies/{company_id}/invitations/{invitation_id}/revoke` | `require_role("owner","admin")` | Set `status="revoked"`. `200`. |
| `GET  /api/invitations/{token}` | **public (no auth)** | Preview by raw token for the accept page (returns `InvitationPreviewResponse`; `410` if expired/revoked). |
| `POST /api/invitations/{token}/accept` | `Depends(get_identity)` | Accept as the logged-in user (identity or access token). |

Route-ordering note: the accept/preview routes are token-scoped and unauthenticated, so they live on `/api/invitations/...` (not under `/companies/...`) to keep them reachable before a company is active. `get_identity` accepts the identity token a brand-new user holds right after signup (they have no company yet), matching arteamis-system's `get_identity`.

### Company-invite vs project-invite branching (in `create_invitation`)
- `project_id is None` → **company invite.** Validate `role ∈ {admin, member}`. `409` if an **active** `membership` already exists for that email's user in the company.
- `project_id` set → **project invite.** Load the `project`; `404`/`403` if it does not belong to `{company_id}`. `role` is the **project** role (`admin|member`). `409` if that email's user is already an active `project_member` of the project.
Both branches: reject if a `pending` invite already exists for the same `(company, email, project)` by **rotating** it — overwrite `token_hash`/`expires_at` on the existing row and re-send, rather than creating duplicates.

### Accept state machine (`accept_invitation`)
1. `inv = Invitation.get_by_token_hash(sha256(raw))`; not found → `404`.
2. `inv.status != "pending"` → `410` (already accepted, revoked, or expired). If `pending` but past `expires_at` → `expire_if_needed` then `410`.
3. Load the accepting `user` (by `user_id`). If `user.email.lower() != inv.email.lower()` → `403` "This invitation was sent to a different email."
4. **Company membership**: upsert `membership(user, company)`. If none → create `status="active"` with `role = inv.role` for a company invite, or `role="member"` for a project invite (so the invitee can enter the company shell). If a `revoked` membership exists → reactivate to `active`. If already `active` → leave as-is (idempotent; do not downgrade an existing higher role).
5. **Project membership** (project invite only): upsert `project_member(user, project)` `status="active"` with `role = inv.role`.
6. `inv.status = "accepted"`; `inv.save()`.
7. Return `AcceptInvitationResponse`. The frontend then calls P2's `POST /auth/switch-company/{company_id}` to obtain a company-scoped access token and enter the company.

## Frontend: routes, components, hooks, stores, i18n keys (file paths)

### API module — `frontend/src/lib/api/invitations.ts` (new; uses the single `apiClient`, never a 2nd axios instance)
`invitationsApi = { list(companyId, params?), create(companyId, data), revoke(companyId, invitationId), preview(token), accept(token) }`, each `apiClient.get/post` returning `response.data`, following the shape of `frontend/src/lib/api/notebooks.ts`. Types added to `frontend/src/lib/types/api.ts` (`InvitationResponse`, `InvitationCreateResponse`, `InvitationPreviewResponse`, `AcceptInvitationResponse`, request bodies).

### Hooks — `frontend/src/lib/hooks/use-invitations.ts` (new; TanStack Query, mirrors `use-notebooks.ts`)
- `useInvitations(companyId, status?)` — query, key `[...QUERY_KEYS.invitations(companyId), { status }]` (add `invitations` to `QUERY_KEYS` in `frontend/src/lib/api/query-client.ts`).
- `useCreateInvitation(companyId)` — mutation; on success invalidate the invitations + members queries and `toast` success (sonner via `useToast`). On success the caller reads `share_url`: if present, show a "copy link" affordance (email wasn't sent).
- `useRevokeInvitation(companyId)` — mutation; invalidate + toast.
- `useInvitationPreview(token)` — query on the accept page, `enabled: !!token`.
- `useAcceptInvitation()` — mutation; on success call the P2 switch-company action then route into the company.
- Errors surface through the existing `getApiErrorKey(error, ...)` + `t(...)` pattern; add `410` handling to `frontend/src/lib/utils/error-handler.ts` mapping to `apiErrors.invitationExpired`.

### Components
- `frontend/src/components/members/members-panel.tsx` (new) — rendered inside P2's company Members route/settings tab. Lists active members (from `GET /companies/{id}/members`) + a "Pending invitations" section (this spec's list) with role badges and a Revoke action (uses `ui/alert-dialog.tsx` to confirm). Owner/admin only; the "Invite" button is hidden for `member` role.
- `frontend/src/components/members/invite-dialog.tsx` (new) — built on `frontend/src/components/ui/dialog.tsx`; fields: email (`ui/input`), role (`ui/select`: Admin/Member), and an optional "Invite to a specific project" toggle → project `ui/select` (company projects from P3). On submit → `useCreateInvitation`. If the response has `share_url`, swap the dialog body to a read-only URL + "Copy link" button (the fallback path); otherwise show "Invitation emailed". Parent clears form state on close (dialogs don't auto-reset — frontend AGENTS.md).

### Accept-invite page — `frontend/src/app/(auth)/invite/[token]/page.tsx` (new, public route)
1. Calls `useInvitationPreview(token)`. On `410`/expired → render an "invitation expired or revoked" state with a link to `/login`.
2. Reads auth state from `auth-store`:
   - **Logged-in user** → show company/project + role, an "Accept invitation" button → `useAcceptInvitation`. On email mismatch (`403`) show the mismatch message and a "Sign in with the invited email" link.
   - **Brand-new / logged-out user** → CTA "Create account" and "Sign in", both routing to P1's `/login` / `/signup` with `?next=/invite/{token}` and the invitation email **prefilled and locked** (so the accepted account's email matches `inv.email`, avoiding the `403`). After auth completes, P1 redirects back to this page, which is now in the logged-in branch and auto-triggers (or offers) accept.

### i18n — add an `invitations` section (+ the two `apiErrors` keys) to ALL 7 enforced locales
Files: `frontend/src/lib/locales/{en-US,pt-BR,zh-CN,zh-TW,ja-JP,ru-RU,bn-IN}/index.ts` (each exports a nested object; add a top-level `invitations: {...}` block beside `notebooks`). Keys (every string via `t('invitations.key')`):
`invitations.title`, `.pending`, `.members`, `.inviteButton`, `.emailLabel`, `.roleLabel`, `.roleAdmin`, `.roleMember`, `.projectScopeToggle`, `.projectLabel`, `.sendInvite`, `.emailedSuccess`, `.copyLinkTitle`, `.copyLink`, `.copied`, `.revoke`, `.revokeConfirm`, `.revokeSuccess`, `.acceptTitle`, `.acceptButton`, `.acceptSuccess`, `.emailMismatch`, `.expiredTitle`, `.expiredBody`, `.createAccountCta`, `.signInCta`, plus `apiErrors.invitationExpired` and `apiErrors.emailMismatch`. (Missing keys silently fall back to en-US, so all 7 must be added — frontend AGENTS.md.)

## Permissions / RBAC rules
| Action | company owner | company admin | company member | non-member / logged-out |
|---|---|---|---|---|
| Create company invite | Yes | Yes | 403 | 401 |
| Create project invite (project in their company) | Yes | Yes | 403 | 401 |
| List invitations | Yes | Yes | 403 | 401 |
| Revoke invitation | Yes | Yes | 403 | 401 |
| Preview invite by token | Yes | Yes | Yes | Yes (public, no secrets) |
| Accept invite (email matches) | n/a | n/a | Yes | must sign in first |
Notes: `owner` is never an invitable role (transfer-ownership is a separate, out-of-scope action). Project invites are gated at the **company** owner/admin level to match P3's decision that project creation/management is an owner/admin action; a project `admin` who is only a company `member` cannot invite through this endpoint (revisit in a later phase if needed).

## Error handling (per the brief's contract; body `{"detail": "..."}`)
- `401` — no/invalid token on a protected endpoint → frontend clears `auth-storage`, redirect `/login`.
- `403` — caller is a company `member`/outsider on create/list/revoke; or accept email mismatch.
- `404` — unknown `invitation_id`; unknown token on accept; project not found for a project invite.
- `409` — invitee already an active member (company invite) or active project_member (project invite).
- `410` — accept/preview of an `expired` or `revoked` (or already `accepted`) invitation. `expire_if_needed` lazily flips a past-due `pending` to `expired` before returning 410.
- `422` — invalid `role` / bad email (Pydantic + the SurrealQL ASSERTs are the second line of defense).
- Domain errors raised via `open_notebook.exceptions` where a mapping exists (`NotFoundError`→404, `InvalidInputError`→400); `403`/`409`/`410` are raised as `HTTPException(status_code=...)` in the router since there is no domain-exception mapping for them (consistent with the brief's explicit status contract).

## Testing (concrete cases) — `tests/` (`uv run pytest`) + frontend (`npm run test`)
Backend (`tests/test_p4_invitations.py`):
1. Owner creates a company invite → `201`, row `status="pending"`, `token_hash` stored and `!= raw token`, `expires_at ≈ now + 7d`.
2. `EMAIL_PROVIDER` unset → response `email_sent=False` and `share_url` is a `/invite/<token>` URL (fallback). With `EMAIL_PROVIDER=resend` (mocked httpx) → `email_sent=True`, `share_url is None`.
3. Company `member` and outsider get `403` on create/list/revoke; missing token → `401` (RBAC via `require_role`).
4. Accept as a brand-new user (signup with the invited email) → `membership` active with the invited role; invite `status="accepted"`.
5. Accept as an existing logged-in user with a **different** email → `403`, invite stays `pending`.
6. Accept an expired invite → `expire_if_needed` flips it, returns `410`; accept a revoked invite → `410`; double-accept → `410`.
7. Project invite: accept creates BOTH an active company `membership` (`member`) and a `project_member` with the invited project role. Duplicate active project_member → `409`.
8. Re-inviting the same email+scope while a pending invite exists rotates the token (old raw token no longer resolves) instead of creating a second row.
9. Preview endpoint is reachable without auth and never returns `token_hash`/`invited_by` secrets.
10. Tenant-leakage guard (mirror arteamis-system `test_X3_suite1_tenant_leakage`): an owner of company A cannot list/revoke company B's invitations (`403`/`404`).

Frontend (vitest): invite dialog renders the copy-link fallback when `share_url` is returned; accept page shows expired state on `410`; logged-out accept routes to `/login?next=...`. Plus `npm run lint` and `npm run build`, and the locale-completeness check (all 7 locales carry the new keys).

## Open questions / risks
- **Token in URL / logs**: the raw token grants acceptance for anyone with the invited email; it appears in the link and possibly server logs. Mitigations here: store only the hash, 7-day expiry, single-use (flip to `accepted`), and never log the raw token in non-DEBUG. A future phase could shorten expiry or add an email round-trip.
- **Migration numbering** is fixed at `22` (P1=19, P2=20, P3=21, P4=22, P5=23); register it in `async_migrate.py` after P1–P3's migrations.
- **Company vs project role field overload**: `role` means a company role for company invites and a project role for project invites. Documented above; acceptable because both use the `admin|member` vocabulary, but worth a code comment on the model to prevent misuse.
- **Email-locked signup** for brand-new users depends on P1's signup accepting a prefilled/locked email + `next` redirect. If P1 does not support locking, accept can still reject mismatches with `403`; UX degrades but stays correct.
- No resend-invite endpoint in scope (rotation-on-recreate covers the common case); add an explicit `POST .../resend` later if admins ask for it.
