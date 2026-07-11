# Connectors — OAuth App Setup Guide (Google Drive / Slack / Notion)

How to register the OAuth apps and fill `.env` so the **Connections** page can connect to third-party apps and import data.

- Redirect URIs below use the **dev-local** API origin `http://localhost:5055`.
  For a real deployment, replace `http://localhost:5055` with your API's public HTTPS origin.
- A provider whose `CLIENT_ID`/`CLIENT_SECRET` are missing still shows on the page, but its **Connect** button is disabled — so you can wire providers in one at a time.
- After editing `.env`, **restart the API** (`make api`) so the new vars load.

## Common `.env` keys (set once)

```dotenv
CONNECTORS_API_URL=http://localhost:5055     # where OAuth callbacks land (the API)
CONNECTORS_APP_URL=http://localhost:3000     # where the user returns after connecting (the frontend)
```

---

## 1. Google Drive — Google Cloud Console

Console: https://console.cloud.google.com

1. Create (or select) a project.
2. **APIs & Services → Library** → search **"Google Drive API"** → **Enable**.
3. **APIs & Services → OAuth consent screen**:
   - User type **External** → Create.
   - Fill App name, User support email, Developer email → Save.
   - **Scopes** → add `.../auth/drive.readonly` and `.../auth/drive.metadata.readonly`.
   - **Test users** → add your Google email (while the app is in *Testing* mode).
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type **Web application**.
   - **Authorized redirect URIs** → add:
     `http://localhost:5055/api/connectors/gdrive/callback`
   - Create → copy **Client ID** + **Client secret**.
5. `.env`:
   ```dotenv
   GDRIVE_CLIENT_ID=...
   GDRIVE_CLIENT_SECRET=...
   ```

> The flow requests `access_type=offline` + `prompt=consent` to obtain a refresh token. In *Testing* mode the refresh token can expire after 7 days — fine for dev; publish the app for stability.

### Google Drive checklist
- [ ] Project created / selected
- [ ] Google Drive API enabled
- [ ] OAuth consent screen configured (External)
- [ ] Scopes added: `drive.readonly`, `drive.metadata.readonly`
- [ ] Your email added as a Test user
- [ ] OAuth client ID (Web application) created
- [ ] Redirect URI added: `http://localhost:5055/api/connectors/gdrive/callback`
- [ ] `GDRIVE_CLIENT_ID` set in `.env`
- [ ] `GDRIVE_CLIENT_SECRET` set in `.env`

---

## 2. Slack — api.slack.com/apps

Console: https://api.slack.com/apps

1. **Create New App → From scratch** → name + pick your workspace.
2. **OAuth & Permissions → Redirect URLs → Add**:
   `http://localhost:5055/api/connectors/slack/callback` → **Save URLs**.
   (Slack allows `http://localhost`; a real domain must be HTTPS.)
3. **OAuth & Permissions → Scopes → Bot Token Scopes** → add:
   `channels:read`, `channels:history`, `pins:read`, `files:read`
   (`files:read` covers canvases).
4. **Basic Information → App Credentials** → copy **Client ID** + **Client Secret**.
5. `.env`:
   ```dotenv
   SLACK_CLIENT_ID=...
   SLACK_CLIENT_SECRET=...
   ```

> "Install to Workspace" happens automatically when you click **Connect** (that IS the OAuth flow).

### Slack checklist
- [ ] App created (From scratch) in the right workspace
- [ ] Redirect URL added: `http://localhost:5055/api/connectors/slack/callback`
- [ ] Bot Token Scopes added: `channels:read`, `channels:history`, `pins:read`, `files:read`
- [ ] `SLACK_CLIENT_ID` set in `.env`
- [ ] `SLACK_CLIENT_SECRET` set in `.env`

---

## 3. Notion — notion.so/my-integrations

Console: https://www.notion.so/my-integrations

1. **New integration**.
2. Choose type **Public** (required for the OAuth flow; *Internal* uses a direct token, no OAuth).
   - Fill name (and logo/company/website if required).
   - **Redirect URIs** → add:
     `http://localhost:5055/api/connectors/notion/callback`
3. Under **OAuth Domain & URIs / Secrets**, copy **OAuth Client ID** + **Client Secret**.
4. `.env`:
   ```dotenv
   NOTION_CLIENT_ID=...
   NOTION_CLIENT_SECRET=...
   ```

> On connect, Notion asks you to pick which pages/databases to grant — only the ones you select become importable.

### Notion checklist
- [ ] Public integration created
- [ ] Redirect URI added: `http://localhost:5055/api/connectors/notion/callback`
- [ ] `NOTION_CLIENT_ID` set in `.env`
- [ ] `NOTION_CLIENT_SECRET` set in `.env`

---

## Final checklist (all providers)

- [ ] `CONNECTORS_API_URL` set in `.env`
- [ ] `CONNECTORS_APP_URL` set in `.env`
- [ ] At least one provider's `CLIENT_ID` + `CLIENT_SECRET` set
- [ ] API restarted (`make api`) after editing `.env`
- [ ] Full stack up: `make database && make api && make worker-start && make frontend`
      (the **worker is required** — imports are async jobs)
- [ ] Open `http://localhost:3000/connections` → configured providers show **Connect** enabled

## Redirect URI reference (copy-paste)

| Provider | Redirect URI (dev) |
|---|---|
| Google Drive | `http://localhost:5055/api/connectors/gdrive/callback` |
| Slack | `http://localhost:5055/api/connectors/slack/callback` |
| Notion | `http://localhost:5055/api/connectors/notion/callback` |

Pattern for any environment: `{CONNECTORS_API_URL}/api/connectors/{provider}/callback`
where `{provider}` is one of `gdrive`, `slack`, `notion`.
