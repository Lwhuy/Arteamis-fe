# Connectors — Source Integrations (Drive / Slack / Notion) — Design Spec
Date: 2026-07-12 · Branch: feat/auth-multitenancy · Status: Draft

> Standalone feature, orthogonal to the P1–P6 multitenancy roadmap. Not P-numbered
> to avoid colliding with the reserved P-sequence. Designed to slot into the
> `workspace` tenant model later (see "Multitenancy fit") without a breaking change.

## Goal
Add a **Connections** experience so a user can connect external apps (Google Drive,
Slack, Notion) via OAuth, browse what those apps expose, pick items, and **import them
once** as Arteamis sources through the existing async ingestion pipeline. Seven more
apps (SharePoint, Box, Dropbox, Confluence, Microsoft Teams, Gmail, S3) render as
disabled **"Coming soon"** cards. The reference is Quelvio's Sources page; we copy its
OAuth mechanism (single central app per provider, CSRF `state`, offline refresh token,
encrypted token storage) but drop `tenant_id`/`member_id` from `state` because Arteamis
is single-user today.

## Scope (in) / Out of scope
**In:**
- `BaseConnector` interface + three adapters: `gdrive`, `slack`, `notion`.
- `Connection` domain model + table (encrypted tokens) + one DB migration.
- `api/connectors_service.py` + `api/routers/connectors.py` (`/api/connectors`).
- OAuth authorize → callback → token exchange → encrypted persist → redirect.
- Item listing + one-time import into sources via `create_source(..., async_processing=True)`.
- Frontend `/connections` page (new nav item), connector grid, connected list,
  item-picker dialog, disconnect. New TanStack Query hooks. i18n across all 7 locales.
- App OAuth credentials read from `.env` per provider.

**Out (YAGNI for this pass):**
- Automatic/scheduled re-sync; delta sync; dedupe of previously-imported items.
- Multitenancy wiring beyond a nullable `workspace` field (P2/P5/P6 own that).
- Drive folder recursion; Notion database rows; Slack full message history/threads.
- Any of the seven "Coming soon" adapters.
- A manual "Re-sync" button (can be a fast follow; not built now).

## Decisions (locked during brainstorming)
1. **Import model:** one-time import. User connects → picks items → items become sources
   once. No background sync.
2. **OAuth credentials:** one central OAuth app per provider; `CLIENT_ID`/`CLIENT_SECRET`
   from `.env`. Redirect URI fixed per instance. A provider with missing env creds shows
   as `available` but its Connect button is disabled with a hint.
3. **Tenant model:** single-user now. `state` carries only `csrf`. `Connection` carries a
   **nullable `workspace`** field so the later multitenancy work only has to set it.
4. **IA:** a dedicated new page `/connections` with its own nav item. The existing
   `/sources` list page is unchanged.
5. **Per-connector scope:** Drive = files; Notion = pages; Slack = **pinned messages +
   canvases** per channel.
6. **Target notebook:** the import dialog offers an optional notebook selection. Default
   is none — imported sources land in the global source library.

## Architecture

### Connector abstraction
One interface, one adapter per provider. The router/service stays thin; all provider
HTTP logic lives in the adapter so each is unit-testable in isolation. Adding a provider
= adding one adapter file. "Coming soon" providers are registry metadata with no adapter.

```
# open_notebook/domain/connectors/base.py
class BaseConnector(Protocol):
    provider: str                                   # "gdrive" | "slack" | "notion"
    display_name: str
    scopes: list[str]
    def is_configured(self) -> bool                 # env creds present?
    def authorize_url(self, state: str, redirect_uri: str) -> str
    async def exchange_code(self, code, redirect_uri) -> TokenSet
    async def refresh(self, refresh_token: str) -> TokenSet
    async def list_items(self, conn: Connection) -> list[ConnectorItem]
    async def fetch_content(self, conn: Connection, item: ConnectorItem) -> ImportedDoc
```

- `TokenSet`: `access_token`, `refresh_token?`, `expires_at?`, `scopes`, `account_label`.
- `ConnectorItem`: `id`, `kind` (`file|page|channel`), `title`, `subtitle?`, `icon?`,
  `mime?`, `modified_at?`.
- `ImportedDoc`: either `content: str` (→ `source_type="text"`) **or**
  `file_path: str` + `title` (→ `source_type="upload"`, `delete_source=True`).

A `CONNECTOR_REGISTRY` maps provider → adapter class; a separate `COMING_SOON` list holds
the seven metadata-only entries. `GET /api/connectors` merges both.

### Connection domain model
`open_notebook/domain/connection.py`, table `connection`, following the `Credential`
pattern (`ObjectModel`, `encrypt_value`/`decrypt_value` on token fields):

| field | type | notes |
|---|---|---|
| `provider` | str | `gdrive`/`slack`/`notion` |
| `account_label` | str | e.g. connected email / workspace name (display) |
| `access_token` | encrypted str | |
| `refresh_token` | encrypted str \| null | Drive/Notion may omit; Slack tokens don't expire |
| `token_expires_at` | datetime \| null | |
| `scopes` | list[str] | granted scopes |
| `status` | str | `connected` \| `error` |
| `workspace` | record(workspace) \| null | **nullable now**; set by later multitenancy work |
| `created` / `updated` | datetime | from `ObjectModel` |

Migration: a new numbered `.surrealql` creating the `connection` table. **Migration number
= next free number at implementation time.** The P2–P6 roadmap reserves 20+; pick the
first unused number after those reservations rather than hardcoding one here.

### Backend endpoints (`/api/connectors`)
| Method + path | Purpose |
|---|---|
| `GET /api/connectors` | List all connectors with status: `connected` / `configured` / `available` / `coming_soon`. Includes connected accounts. |
| `GET /api/connectors/{provider}/authorize` | Generate `state={csrf}` (stored server-side, short TTL), return provider consent URL (`access_type=offline`, `prompt=consent`, readonly scopes). |
| `GET /api/connectors/{provider}/callback?code&state` | Verify `csrf`, `exchange_code`, persist encrypted `Connection`, redirect to `/connections?connected={provider}` (or `?error=...`). |
| `GET /api/connectors/{provider}/items?connection_id` | Return `list_items` for the picker. |
| `POST /api/connectors/{provider}/import` | Body: `connection_id`, `item_ids[]`, optional `notebooks[]`. For each item, `fetch_content` → `create_source(..., async_processing=True)`. Returns per-item accepted/failed. |
| `DELETE /api/connectors/connections/{id}` | Delete the connection and its tokens. |

The callback path is added to the password-middleware `excluded_paths` (providers redirect
without a Bearer header). CSRF `state` closes the resulting open-callback gap.

### Per-connector behaviour
| Connector | `list_items` | `fetch_content` → source |
|---|---|---|
| **Google Drive** | Files the user can read (name, mime, modified); multi-select. Scopes: `drive.readonly`, `drive.metadata.readonly`. | Google Docs/Sheets/Slides → export to text/markdown (`source_type="text"`); other files (PDF, etc.) → download bytes to temp → `source_type="upload"`, `delete_source=True`. |
| **Notion** | Pages/databases granted to the integration. | Page → fetch blocks → convert to markdown → `source_type="text"`. Databases listed but rows not expanded (out of scope). |
| **Slack** | Channels the token can access. | **Pinned messages + canvases** of each selected channel, concatenated into one `source_type="text"` source per channel. No full-history pagination. |

## Frontend — `/connections`
- New nav item **Connections** (`/connections`) in the "collect" group of `AppSidebar`;
  `/sources` untouched. i18n key `navigation.connections` in all 7 locales.
- Page layout mirrors the Quelvio mockup:
  - **Connected sources** — cards for existing `Connection`s (account label, provider icon,
    `⋮` menu → Disconnect with confirm).
  - **Add more** — grid of connector cards. `available`/`configured` cards are clickable
    (start OAuth). `coming_soon` cards are dimmed with a "COMING SOON" badge. A `available`
    card whose env creds are missing shows Connect disabled + a hint tooltip.
  - Clicking a connectable card hits `/authorize` and navigates to the returned consent URL.
- **Item-picker dialog** — opens after a successful connect (and re-openable from a connected
  card): searchable checkbox list from `/items`, optional target-notebook selector, Import
  button → `/import`, then a toast and processing indicator.
- Hooks (TanStack Query, via `apiClient`, following existing hook shape):
  `useConnectors()`, `useConnectionItems(provider, connectionId)`,
  `useImportItems()`, `useDisconnect()`. Mutations invalidate `['connectors']` and show
  sonner toasts.

## Error handling
- OAuth denial / bad `state` / exchange failure → redirect `/connections?error=<code>` +
  toast; never persist a partial connection.
- Access token expired at list/import time → `refresh()` once (Drive/Notion); Slack tokens
  don't expire. Refresh failure → mark connection `status="error"`, prompt reconnect.
- Import is per-item resilient: a failing item does not abort the batch; the response reports
  which items were accepted vs failed, surfaced in the toast/UI.

## Security
- Tokens encrypted at rest with `OPEN_NOTEBOOK_ENCRYPTION_KEY` (reuse `encrypt_value`).
- `state` is a server-generated CSRF nonce with a short TTL; callback rejects unknown/expired
  state.
- Readonly OAuth scopes only.
- No secrets committed; app creds live only in `.env`.

## Testing
- Adapter unit tests: mock provider HTTP (`authorize_url`, `exchange_code`, `list_items`,
  `fetch_content`, `refresh`). No real provider calls.
- Service/router tests: mock the adapter; assert state/CSRF handling, encrypted persistence,
  per-item import result shaping, disconnect.
- Frontend component tests: connectors page (states: connected / available / configured /
  coming_soon / creds-missing) and the item-picker dialog.

## Multitenancy fit (future, not built now)
`Connection.workspace` is nullable today. When P2 (workspace/membership) and P5/P6
(source-scope + `ScopedRepository`) land: set `workspace` on create from
`AuthContext.workspace_id`, scope `GET /api/connectors` connected list by workspace, and let
imported sources inherit the same workspace. This mirrors Quelvio's `state.tenant_id` /
`member_id` — deferred cleanly rather than stubbed.

## Env configuration
```
GDRIVE_CLIENT_ID / GDRIVE_CLIENT_SECRET
SLACK_CLIENT_ID  / SLACK_CLIENT_SECRET
NOTION_CLIENT_ID / NOTION_CLIENT_SECRET
CONNECTORS_REDIRECT_BASE   # e.g. https://api.example.com ; callback = {base}/api/connectors/{provider}/callback
```
