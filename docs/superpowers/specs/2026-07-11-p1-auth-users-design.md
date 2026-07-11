# P1 — Real Auth + Users — Design Spec
Date: 2026-07-11 · Branch: feat/auth-multitenancy · Status: Draft

## Goal
Replace the single shared-password gate (`PasswordAuthMiddleware` in `api/auth.py`, which compares `Authorization: Bearer <pw>` to `OPEN_NOTEBOOK_PASSWORD`) with real per-user accounts and JWT authentication supporting BOTH email+password AND "Continue with Google". Introduce the identity-plane tables `user` and `auth_identity`, a JWT middleware that authenticates every request from a Bearer token, and a refresh-cookie session lifecycle. P1 ends at an authenticated user holding an **identity token** (no workspace yet). Workspace selection, workspace-scoped access tokens, and onboarding are P2 — this includes personal-workspace auto-provisioning: P1's register/login leaves the user authenticated on an identity token, and P2 attaches the user's default personal workspace. P1 does not add any workspace tables.

## Depends on / Provides
- **Depends on:** nothing (foundation phase). Uses the existing SurrealDB repository layer, `ObjectModel` base, and `AsyncMigrationManager`. Independent of P0 branding.
- **Provides (contracts P2–P6 build on):**
  - Tables `user` and `auth_identity` (identity plane; global, never workspace-scoped).
  - JWT identity token (`{ "sub": <user_id>, "type": "identity", "exp" }`) as the frontend Bearer, stored in Zustand `auth-storage` and auto-injected by `apiClient`.
  - `request.state.user_id` populated by `JWTAuthMiddleware` for downstream routers.
  - Token helpers in `api/security.py` including a `create_access_token(...)` stub P2 fills in for workspace-scoped tokens, plus refresh cookie + `/auth/refresh`.
  - `AuthContext` dataclass (`user_id: str`, `workspace_id: str | None`, `role: str | None`) and `decode_access_token(token) -> AuthContext` in `api/security.py` — the canonical workspace-scoped-token decoder P2's `get_auth_context` and P6's `ScopedRepository`/`require_workspace` consume. The `workspace_id`/`role` claims are populated once P2 implements `create_access_token`; until then the decoder returns them as `None`.
  - `SessionPayload` response shape (`access_token`, `token_type`, `user`, and a `needs_onboarding`/`memberships` surface P2 populates — P1 returns `needs_onboarding: true`, `memberships: []`).
  - `open_notebook/domain/user.py` `User.upsert_with_identity(...)` account-linking helper (Google + email merge by email).

## Scope
**In scope**
- Migration 19: `user`, `auth_identity` tables + unique indexes.
- Domain models `User`, `AuthIdentity` (`open_notebook/domain/user.py`).
- Password hashing (argon2) + JWT + Google OAuth code-exchange helpers.
- Endpoints: `POST /auth/register`, `POST /auth/login`, `GET /auth/google/start`, `GET /auth/google/callback`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`. Rework existing `GET /auth/status`.
- `JWTAuthMiddleware` replacing `PasswordAuthMiddleware`.
- Frontend: rewrite `LoginForm` (email/password + Google button), new signup page, rewrite `auth-store` to hold a real JWT + user, refresh-on-401 handling, cookie-hydration bootstrap.
- i18n keys added to all 14 locales in the `resources` map (7 enforced translations + 7 English fallback).

**Out of scope (later phases)**
- `workspace`, `membership`, `invitation`, workspace-scoped access tokens, `/auth/switch-workspace`, onboarding wizard (P2). This includes personal-workspace auto-provisioning (P2 attaches the default personal workspace after P1's register/login); P1 does not create any workspace tables.
- `notebook`→`project` repurposing (P3), invitations (P4), source permissions (P5), app-layer tenant scoping (P6).
- Passwordless email OTP (arteamis-system uses it; product decision here is email+password + Google only — do NOT port `/auth/otp/*`).
- Email verification / password reset flows (note as future work in Open questions).

## Data model changes (SurrealDB migration 19)
New files (mirror the `IF NOT EXISTS` + `SCHEMAFULL` conventions of `open_notebook/database/migrations/1.surrealql` and the index style of `18.surrealql`):

`open_notebook/database/migrations/19.surrealql`
```surql
-- Migration 19: Identity plane — real users + auth identities (P1 auth).

DEFINE TABLE IF NOT EXISTS user SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS email         ON TABLE user TYPE string;
DEFINE FIELD IF NOT EXISTS display_name  ON TABLE user TYPE option<string>;
DEFINE FIELD IF NOT EXISTS password_hash ON TABLE user TYPE option<string>;
DEFINE FIELD IF NOT EXISTS avatar_url    ON TABLE user TYPE option<string>;
DEFINE FIELD IF NOT EXISTS created ON user DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON user DEFAULT time::now() VALUE time::now();
-- Case-insensitive uniqueness: email is normalized to lower-case in the app layer
-- before save (see User.normalize_email), so a plain UNIQUE index is sufficient.
DEFINE INDEX IF NOT EXISTS idx_user_email ON TABLE user FIELDS email UNIQUE;

DEFINE TABLE IF NOT EXISTS auth_identity SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS provider         ON TABLE auth_identity TYPE string
    ASSERT $value IN ["email_password", "google"];
DEFINE FIELD IF NOT EXISTS provider_subject ON TABLE auth_identity TYPE string;
DEFINE FIELD IF NOT EXISTS user             ON TABLE auth_identity TYPE record<user>;
DEFINE FIELD IF NOT EXISTS email            ON TABLE auth_identity TYPE option<string>;
DEFINE FIELD IF NOT EXISTS last_login_at    ON TABLE auth_identity TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS created ON auth_identity DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON auth_identity DEFAULT time::now() VALUE time::now();
DEFINE INDEX IF NOT EXISTS idx_auth_identity_unique
    ON TABLE auth_identity FIELDS provider, provider_subject UNIQUE;
DEFINE INDEX IF NOT EXISTS idx_auth_identity_user ON TABLE auth_identity FIELDS user;
```

`open_notebook/database/migrations/19_down.surrealql`
```surql
REMOVE TABLE IF EXISTS auth_identity;
REMOVE TABLE IF EXISTS user;
```

**Manager wiring (mandatory — migrations are hard-coded, not auto-discovered):** append to both lists in `open_notebook/database/async_migrate.py` `AsyncMigrationManager.__init__`:
`AsyncMigration.from_file("open_notebook/database/migrations/19.surrealql")` to `up_migrations` and `..."19_down.surrealql"` to `down_migrations`. Runs automatically on API startup.

Note on the SurrealQL cleaner: `AsyncMigration.from_file` strips lines beginning with `--` and joins the rest with spaces, so keep each statement `;`-terminated and never place code after an inline `--` comment on the same line.

## Backend: endpoints, services, domain models (file paths)

### Libraries & where secrets come from
- **Password hashing: argon2** via the `argon2-cffi` package (`argon2.PasswordHasher`). Chosen over bcrypt: memory-hard, no 72-byte silent truncation, sensible modern defaults, actively maintained (avoids the unmaintained `passlib` shim). Hashing/verify are CPU-bound and synchronous — call them through `await asyncio.to_thread(...)` so the async event loop is never blocked (repo rule: async-first). Add `argon2-cffi` to `pyproject.toml` dependencies.
- **JWT: `python-jose[cryptography]`** (`from jose import jwt, JWTError`) — matches arteamis-system `backend/app/core/security.py` so the token logic is a near-faithful port; HS256, symmetric secret. Add `python-jose[cryptography]` to `pyproject.toml`. (PyJWT is a viable alternative but jose keeps the port 1:1.)
- **Google OAuth: `httpx`** — already a dependency (`httpx[socks]>=0.27.0` in `pyproject.toml`); no new package.
- **Config / secrets** — new module `api/auth_config.py` reading env once at import. Secrets go through the existing `open_notebook.utils.encryption.get_secret_from_env` (supports the Docker `*_FILE` pattern), non-secrets through `os.getenv`:
  - `JWT_SECRET` (via `get_secret_from_env`) — **required to enable auth**; when unset, auth is disabled (dev parity with today's "no password" behavior). `JWT_ALGORITHM` (default `HS256`).
  - `ACCESS_TOKEN_EXPIRE_MINUTES` (default 15), `REFRESH_TOKEN_EXPIRE_DAYS` (default 30).
  - `REFRESH_COOKIE_NAME` (default `arteamis_refresh`), `COOKIE_SECURE` (default true; set false for local http), `COOKIE_SAMESITE` (default `lax`).
  - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (via `get_secret_from_env`), `GOOGLE_REDIRECT_URI` (default `http://localhost:5055/api/auth/google/callback`).
  - `FRONTEND_URL` (default `http://localhost:3000`) — where `/auth/google/callback` redirects after setting the cookie.

### Retiring the `OPEN_NOTEBOOK_PASSWORD` gate
- Delete `PasswordAuthMiddleware` from `api/auth.py`; add `JWTAuthMiddleware` (same file) with the same `excluded_paths` list currently registered in `api/main.py` (`/`, `/health`, `/docs`, `/openapi.json`, `/redoc`, `/api/auth/status`, `/api/config`) plus the new public auth endpoints: `/api/auth/register`, `/api/auth/login`, `/api/auth/google/start`, `/api/auth/google/callback`, `/api/auth/refresh`, `/api/auth/logout`. Keep the OPTIONS/CORS-preflight bypass.
- Behavior: if `JWT_SECRET` is unset → pass through (auth disabled, dev mode). Else require `Authorization: Bearer <jwt>`; decode via `decode_identity_token` (accepts identity **or** future workspace-scoped access tokens); on success set `request.state.user_id`; on missing/invalid/expired token return `401 {"detail": ...}` with `WWW-Authenticate: Bearer` (same JSON error shape as today).
- `OPEN_NOTEBOOK_PASSWORD` / `_FILE` are no longer read. Retirement note for operators (goes in the PR description + `.env.example`): the shared-password gate is removed; there is no data migration (no prior users existed) — operators self-register the first account via `POST /auth/register` (or Google). Document the swap of env vars (`OPEN_NOTEBOOK_PASSWORD` → `JWT_SECRET` + Google vars).
- `api/main.py`: swap `app.add_middleware(PasswordAuthMiddleware, ...)` for `JWTAuthMiddleware` (identical excluded-paths call site, ordering unchanged — still added before `MaxBodySizeMiddleware` and CORS). Router registration line `app.include_router(auth.router, prefix="/api", ...)` is unchanged.

### `api/security.py` (new) — token helpers (port of arteamis-system `core/security.py`)
- `create_identity_token(user_id) -> str` — `{ "sub": user_id, "type": "identity", "exp": now + ACCESS_TOKEN_EXPIRE_MINUTES }`.
- `decode_identity_token(token) -> str` — returns `sub`; accepts identity or (future) workspace-scoped access tokens; raises `AuthenticationError` on `JWTError`/`KeyError`/expiry.
- `create_refresh_token(user_id)` / `decode_refresh_token(token)` — `type == "refresh"`, `exp = now + REFRESH_TOKEN_EXPIRE_DAYS`.
- `create_access_token(user_id, workspace_id, role, ...)` — **stub raising `NotImplementedError` in P1** (documented handoff to P2; keeps the two-token seam explicit). SurrealDB record ids are strings like `user:abc`, not UUIDs, so drop arteamis-system's `_require_uuid` validator; validate instead that `sub` is a non-empty string matching `^user:`.
- `AuthContext` dataclass (`user_id`, `workspace_id: str | None`, `role: str | None`) + `decode_access_token(token) -> AuthContext` — decode the full workspace-scoped claim set (`sub`, `workspace_id`, `role`) into a typed context. Defined here so P2's `get_auth_context` (in `api/deps.py`) and P6's `require_workspace`/`ScopedRepository` share one decoder. In P1, `workspace_id`/`role` are always `None` (no access token is minted yet); P2's `create_access_token` populates them.

### `open_notebook/domain/user.py` (new)
Subclass `ObjectModel` (mirrors `open_notebook/domain/notebook.py`).
- `class User(ObjectModel)` — `table_name = "user"`; fields `email: str`, `display_name: Optional[str]`, `password_hash: Optional[str]`, `avatar_url: Optional[str]`; `nullable_fields = {"password_hash", "display_name", "avatar_url"}` (so `_prepare_save_data` persists an explicit null password for Google-only users). `@field_validator("email")` lower-cases/strips and rejects empty. Methods:
  - `set_password(self, raw) / verify_password(self, raw) -> bool` via `asyncio.to_thread(argon2 hasher...)`; `verify_password` returns False when `password_hash` is None (Google-only account).
  - `@classmethod async get_by_email(cls, email) -> Optional[User]` (`SELECT * FROM user WHERE email = $email` through `repo_query`).
  - `@classmethod async get_by_identity(cls, provider, subject) -> Optional[User]` (join via `auth_identity`).
  - `@classmethod async upsert_with_identity(cls, provider, subject, email, display_name=None) -> User` — port of arteamis-system `upsert_user_with_identity`: match order (provider,subject) identity → user by email → create new; then ensure an `AuthIdentity` link + stamp `last_login_at`. This is what links Google + email under one account by email.
- `class AuthIdentity(ObjectModel)` — `table_name = "auth_identity"`; fields `provider: Literal["email_password","google"]`, `provider_subject: str`, `user: str` (record link), `email: Optional[str]`, `last_login_at: Optional[datetime]`.

### `api/auth_service.py` (new) — business logic (routers stay thin, per `api/AGENTS.md`)
- `register(email, password, display_name) -> User`: reject if `get_by_email` exists → `DuplicateResourceError` (409); else create `User` with hashed password + an `email_password` `AuthIdentity` (`provider_subject = email`).
- `login(email, password) -> User`: `get_by_email`; `verify_password`; on failure → `AuthenticationError` (401, generic "Invalid email or password" — do not reveal which).
- `build_session_payload(user) -> dict`: returns `{ access_token: create_identity_token(user.id), token_type: "bearer", needs_onboarding: True, active_workspace_id: None, user: {id, email, display_name}, memberships: [] }` (P2 replaces this with the workspace-aware branch: personal-workspace auto-provisioning happens in P2, not P1 — P2 attaches the user's default personal workspace and populates `active_workspace_id`/`memberships`).
- Google helpers imported from `open_notebook/auth/google.py`.

### `open_notebook/auth/google.py` (new) — OAuth code exchange (port of arteamis-system `auth/google.py`)
- `build_authorize_url(state) -> str` (scope `openid email profile`, `prompt=select_account`).
- `async exchange_code_for_userinfo(code) -> dict` via `httpx.AsyncClient` (token endpoint → userinfo). Returns `sub`, `email`, `email_verified`, `name`.

### `api/routers/auth.py` (rewrite) — endpoints
All under existing `APIRouter(prefix="/auth")`, mounted at `/api`. Refresh cookie set via `response.set_cookie(REFRESH_COOKIE_NAME, create_refresh_token(user.id), httponly=True, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE, path="/")`.

| Method + path | Auth | Behavior |
|---|---|---|
| `POST /auth/register` | public | body `{email, password, display_name?}` → `auth_service.register` → set refresh cookie → 201 `SessionPayload`. |
| `POST /auth/login` | public | body `{email, password}` → `auth_service.login` → set refresh cookie → 200 `SessionPayload`. |
| `GET /auth/google/start` | public | make `state`, set short-lived httpOnly `arteamis_oauth_state` cookie, `RedirectResponse` to `build_authorize_url(state)`. |
| `GET /auth/google/callback` | public | verify `state` cookie (`secrets.compare_digest`, else 400); `exchange_code_for_userinfo`; require `email_verified in (True,"true")` else 400 (prevents unverified-email account takeover); `User.upsert_with_identity("google", sub, email, name)`; set refresh cookie; delete state cookie; `RedirectResponse` to `{FRONTEND_URL}/notebooks`. |
| `POST /auth/refresh` | refresh cookie | read `REFRESH_COOKIE_NAME`; `decode_refresh_token` (401 if missing/invalid); load user (401 if gone); re-set refresh cookie (sliding expiry); return `SessionPayload`. |
| `POST /auth/logout` | public | `response.delete_cookie(REFRESH_COOKIE_NAME, path="/")` → `{status:"logged_out"}`. |
| `GET /auth/me` | Bearer (identity) | from `request.state.user_id` (or a `get_identity` dependency), load user → `{ user, memberships: [] }` (404 if user gone). |
| `GET /auth/status` | public | replace password-based check: `{"auth_enabled": bool(JWT_SECRET), "message": ...}` so the existing frontend `checkAuthRequired()` keeps working. |

### `api/models.py` — Pydantic schemas (append)
`RegisterRequest {email: EmailStr, password: str (min_length 8), display_name: str | None}`, `LoginRequest {email: EmailStr, password: str}`, `AuthUser {id, email, display_name}`, `SessionPayload {access_token, token_type, needs_onboarding, active_workspace_id: str|None, user: AuthUser, memberships: list}`, `MeResponse {user: AuthUser, memberships: list}`. (`EmailStr` needs `pydantic[email]`/`email-validator`; add to `pyproject.toml` if absent.)

### New exception + handler (409)
`open_notebook/exceptions.py` has no conflict type. Add `class DuplicateResourceError(OpenNotebookError)` and register a handler in `api/main.py` returning `409 {"detail": str(exc)}` with `_cors_headers(request)` (mirrors the existing typed-exception handlers). Satisfies the brief's "409 duplicate email" contract without raising a bare `HTTPException` (forbidden by `api/AGENTS.md`).

## Frontend: routes, components, hooks, stores, i18n keys (file paths)
All HTTP stays on the single `apiClient` (`frontend/src/lib/api/client.ts`); the Google flow uses full-page navigation, not fetch.

### `frontend/src/lib/api/client.ts` (edit)
- Keep the request interceptor's Bearer-from-`localStorage['auth-storage']` `state.token` injection **unchanged** — the JWT lives in the same `token` slot, so existing behavior keeps working with zero interceptor changes.
- Response interceptor: on `401`, attempt a one-shot `POST /api/auth/refresh` (with credentials) via a **dedicated axios call / raw fetch using `credentials:'include'`** (guarded by a module flag to avoid infinite loops and to de-dupe concurrent 401s). On success, write the new `access_token` + user into the store and retry the original request once; on failure, `localStorage.removeItem('auth-storage')` + `window.location.href = '/login'` (current behavior). The refresh call must send the cookie: either set `withCredentials: true` on the refresh request specifically, or use `fetch(..., {credentials:'include'})`. **CORS caveat (document + `.env.example`):** the refresh cookie only survives cross-origin when the backend sets `CORS_ORIGINS` to the explicit frontend origin (not `*`) — `api/main.py` only enables `allow_credentials` for non-wildcard origins. Leave the base client `withCredentials: false`.

### `frontend/src/lib/stores/auth-store.ts` (rewrite)
Replace the "authenticate by hitting `/api/notebooks` with the password as the Bearer" logic with real endpoints. Persisted (`partialize`) fields: `token`, `user`, `isAuthenticated`. New/changed actions:
- `register(email, password, displayName)` → `POST /auth/register` → store `access_token`+`user`.
- `login(email, password)` → `POST /auth/login` → store token+user.
- `loginWithGoogle()` → `window.location.href = <apiUrl>/api/auth/google/start` (full-page redirect).
- `refresh()` → `POST /auth/refresh` (credentials include) → store token+user; used for cookie hydration (returning users + Google returnee) and by the 401 interceptor.
- `fetchMe()` → `GET /auth/me`.
- `logout()` → `POST /auth/logout` then clear token/user + `localStorage.removeItem('auth-storage')`.
- Keep `hasHydrated`, `setHasHydrated`, `checkAuthRequired` (still reads `/auth/status`), and the `name: 'auth-storage'` key (must stay — `apiClient` reads that exact key). Preserve the SSR `hasHydrated` guard.

### `frontend/src/lib/hooks/use-auth.ts` (edit)
Keep the hook's external shape but expose `register`, `login(email,password)`, `loginWithGoogle`, `logout`. On successful login/register, honor `sessionStorage['redirectAfterLogin']` else `router.push('/notebooks')` (P2 will branch on `needs_onboarding`). Add a mount bootstrap that, when there is no persisted token, calls `refresh()` once to pick up a valid refresh cookie (covers the Google callback landing on `/notebooks` and returning sessions).

### `frontend/src/lib/types/auth.ts` (edit)
Replace `LoginCredentials {password}` with `LoginCredentials {email, password}`, add `RegisterCredentials {email, password, displayName?}`, `AuthUser {id, email, display_name}`, `SessionPayload`. Extend `AuthState` with `user: AuthUser | null`.

### Components / routes
- `frontend/src/components/auth/LoginForm.tsx` (rewrite): email + password inputs, "Sign In" submit → `login`, a "Continue with Google" button → `loginWithGoogle`, an "or" divider, and a link to `/signup`. Keep the existing connection-error/diagnostic card and the `hasHydrated`/`checkAuthRequired` guards. Reuse `Button`, `Input`, `Card` primitives; all strings via `t(...)`.
- `frontend/src/components/auth/SignupForm.tsx` (new): display_name + email + password (+ confirm) inputs → `register`; Google button; link back to `/login`.
- `frontend/src/app/(auth)/signup/page.tsx` (new): renders `<ErrorBoundary><SignupForm/></ErrorBoundary>` (mirrors `frontend/src/app/(auth)/login/page.tsx`).
- `frontend/src/app/(auth)/login/page.tsx`: unchanged wrapper.

### i18n keys (add to ALL 14 locales in the `resources` map under `frontend/src/lib/locales/<loc>/index.ts`, `auth` section: 7 enforced translations `en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN` + 7 English-fallback locales `it-IT, fr-FR, ca-ES, es-ES, de-DE, pl-PL, tr-TR`)
Existing keys reused: `signIn`, `signingIn`, `passwordPlaceholder`, `connectErrorHint`. Update `loginTitle`/`loginDesc` copy. New keys:
`emailPlaceholder`, `displayNamePlaceholder`, `confirmPasswordPlaceholder`, `continueWithGoogle`, `orWithEmail`, `signupTitle`, `signupDesc`, `createAccount`, `creatingAccount`, `haveAccount`, `noAccount`, `signInLink`, `signUpLink`, `invalidCredentials`, `emailInUse`, `passwordTooShort`, `passwordsDontMatch`, `googleError`.
(en-US is the fallback; missing keys silently fall back, but the locale parity test requires the key set to match across all 14 locales, so all 14 must be populated — the 7 enforced locales with real translations, the other 7 with English fallback values — per `frontend/AGENTS.md`.)

## Permissions / RBAC rules
P1 has no roles yet (roles arrive with `membership` in P2). Access rules are auth-state only:

| Action | Who |
|---|---|
| `POST /auth/register` | anyone (public) |
| `POST /auth/login` | anyone with valid email+password |
| `GET /auth/google/start` · `GET /auth/google/callback` | anyone (OAuth handshake) |
| `POST /auth/refresh` | holder of a valid refresh cookie |
| `POST /auth/logout` | anyone (idempotent cookie clear) |
| `GET /auth/me` | any authenticated user (valid Bearer identity token) |
| every other `/api/*` route | any authenticated user (JWTAuthMiddleware); when `JWT_SECRET` unset, open (dev mode) |

Account-linking rule (explicit): Google and email+password sign-ins for the **same verified email** resolve to one `user` (via `upsert_with_identity`). Google email is trusted for matching only when `email_verified` is true.

## Error handling (per brief contract, `{"detail": "..."}`)
- **400** `InvalidInputError` — malformed body, invalid OAuth `state`, unverified/absent Google email.
- **401** `AuthenticationError` — bad credentials (generic message), missing/invalid/expired Bearer, missing/invalid refresh cookie. Frontend interceptor: try one refresh, else clear `auth-storage` + redirect `/login`.
- **409** `DuplicateResourceError` — email already registered.
- **404** — `/auth/me` when the user record is gone.
- **429** — recommend rate-limiting `login`/`register` (see risks); not built-in.
Typed exceptions only (global handlers in `api/main.py` map them) — no bare `HTTPException` for domain errors.

## Testing (concrete cases)
Backend (`uv run pytest tests/`; `RecordModel` singletons need `clear_instance()` — N/A here, but clean the `user`/`auth_identity` tables between tests):
- `register` creates user + `email_password` identity; password stored as argon2 hash (never plaintext, never returned).
- Duplicate email → 409; login wrong password → 401 generic; login unknown email → 401 (no user enumeration).
- Login success → identity token whose `decode_identity_token` yields the user id; `type == "identity"`.
- Google callback: valid state + verified email → user created and `google` identity linked; invalid state → 400; `email_verified` false → 400; **same email via Google then email/password (or vice-versa) resolves to one `user` with two `auth_identity` rows** (account linking).
- `refresh`: valid cookie → new token + rotated cookie; missing/invalid cookie → 401. `logout` clears the cookie.
- `JWTAuthMiddleware`: no token → 401 on a protected route; valid identity token → passes and `request.state.user_id` set; expired token → 401; `JWT_SECRET` unset → open pass-through.
- Migration 19 up/down round-trips; unique indexes reject duplicate email and duplicate `(provider, provider_subject)`.

Frontend (`npm run test`, `npm run lint`, `npm run build`):
- `auth-store` login/register store token+user; logout clears store and `auth-storage`.
- `apiClient` 401 → refresh attempt → retry-once → on refresh failure redirect `/login`.
- `LoginForm`/`SignupForm` render, submit, and surface field errors via `t(...)`.
- All new i18n keys exist in every one of the 7 enforced locales (extend the locale sync test in `frontend/src/lib/locales/index.test.ts`).

## Open questions / risks
- **`python-jose` maintenance / `argon2-cffi` build:** jose is lightly maintained (PyJWT is the fallback if it becomes a problem); `argon2-cffi` ships wheels but confirm it builds in the Docker image.
- **Refresh cookie cross-origin:** requires explicit `CORS_ORIGINS` (non-wildcard) so `allow_credentials` is on; wildcard/default dev config breaks refresh. Must be called out in `.env.example` and docs. Alternative if this bites: same-origin proxy in P6.
- **Google `redirect_uri`:** must exactly match the Google Cloud console entry and `GOOGLE_REDIRECT_URI` (default points at the API `/api/auth/google/callback`); mismatch is the most common OAuth failure.
- **No rate limiting** on `login`/`register` (repo has none built in) → brute-force/enumeration exposure; recommend adding a limiter or documenting reverse-proxy throttling.
- **Not in P1 (flag for backlog):** email verification for `email_password` signups, password reset, and refresh-token revocation/rotation-family invalidation (current refresh is stateless — logout clears the cookie but a stolen refresh token stays valid until expiry).
- **`needs_onboarding`/`memberships` seam:** P1 hard-codes `needs_onboarding: true` / `memberships: []`; P2 must fill `build_session_payload` and the `create_access_token` stub without breaking the P1 response shape. Note: personal-workspace auto-provisioning is done in P2, not P1 — P1's register/login intentionally leaves the user authenticated on an identity token only (acceptable), and P2 attaches the user's default personal workspace on top of this contract. P1 adds no workspace tables.
