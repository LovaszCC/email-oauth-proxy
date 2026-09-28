# Email OAuth2 Proxy (web edition)

A headless, single-container IMAP proxy: your mail client logs in with a plain
`LOGIN username password`, the proxy authenticates to Gmail, Office 365 or any
other XOAUTH2-capable IMAP server with OAuth 2.0 and then pipes the session
through untouched. Configuration and the OAuth authorization happen in a small
web UI instead of a config file or desktop popups.

It re-implements the IMAP part of
[simonrob/email-oauth2-proxy](https://github.com/simonrob/email-oauth2-proxy)
for server use. POP3 and SMTP are not supported.

## Quick start

```bash
# 1. generate an encryption key for stored secrets/tokens
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. put it (and an admin password) into docker-compose.yml, then
docker compose up -d --build

# 3. open the web UI
open http://localhost:8080      # user: admin, password: ADMIN_PASSWORD
```

## Registering an OAuth client

You need your own OAuth client id (and usually a secret) with the provider.
Register it as a **desktop / native** application with redirect URI
`http://localhost`.

**Gmail (Google Cloud Console)**

1. APIs & Services → Credentials → Create credentials → OAuth client ID → *Desktop app*.
2. Configure the consent screen; add the scope `https://mail.google.com/`
   (add yourself as a test user while the app is in *Testing*).
3. Note the client id and client secret.

**Office 365 / Outlook (Microsoft Entra)**

1. App registrations → New registration. Under *Redirect URI* choose
   *Public client/native (mobile & desktop)* and enter `http://localhost`.
2. API permissions → Add → Microsoft Graph / Office 365 Exchange Online →
   delegated `IMAP.AccessAsUser.All` and `offline_access`.
3. Note the Application (client) ID. A secret is optional for public clients;
   if you create one, note it as well. For single-tenant apps replace `common`
   in both URLs with your tenant id when using the *Custom* provider.

## Adding and authorizing an account

1. **Add account** → choose the provider preset (Gmail / Office 365 / Custom).
   The IMAP server and OAuth URLs are filled in; paste the client id/secret.
2. **Create and authorize** → **Start authorization**.
3. Open the shown link in your browser and sign in to the mailbox.
4. The browser is redirected to `http://localhost/?code=…&state=…` and shows
   an error page – that is expected. Copy the whole address from the address bar.
5. Paste it into the *Redirect URL* box → **Complete authorization**.
   The account list now shows *Authorized*. Tokens are refreshed automatically.
6. The **Logs** page shows the last lines of the application log (refresh results,
   rejected logins, errors) without shell access.

## Mail client setup

| Setting | Value |
|---|---|
| Server | the Docker host (e.g. `localhost`) |
| Port | `1993` |
| Connection security | none / plain (the proxy talks TLS to the real server) |
| Authentication | normal password |
| Username | the account's email address exactly as entered in the web UI |
| Password | anything – it is ignored |

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `ADMIN_USER` | `admin` | web UI login |
| `ADMIN_PASSWORD` | – | **required** |
| `SECRET_KEY` | – | **required**; Fernet key used to encrypt client secrets and tokens and to sign the session cookie |
| `IMAP_HOST` | `0.0.0.0` | proxy listen address |
| `IMAP_PORT` | `1993` | proxy listen port |
| `WEB_HOST` / `WEB_PORT` | `0.0.0.0` / `8080` | web UI |
| `DATA_DIR` | `/data` | holds `proxy.db` (SQLite) – mount a volume |
| `LOG_LEVEL` | `INFO` | |
| `LOG_BUFFER_SIZE` | `1000` | log lines kept in memory for the **Logs** page |
| `REFRESH_INTERVAL` | `3600` | seconds between background token refresh runs; every authorized account is refreshed before its access token expires, so inactive accounts stay valid |

## Security notes

- **The IMAP password is ignored.** Anyone who can reach port 1993 can read
  every configured mailbox. Bind it to localhost or a trusted LAN only (the
  sample compose file binds `127.0.0.1:1993`).
- Client secrets, access tokens and refresh tokens are stored encrypted with
  `SECRET_KEY`. If you lose or change the key, all accounts must be
  authorized again.
- The web UI uses a signed session cookie; put it behind HTTPS (reverse proxy)
  if it is reachable from outside your machine.
- The proxy verifies the real server's TLS certificate with the system CA store.
- Refresh failures are logged at ERROR (`docker compose logs`) and shown on the
  account list. An expired client secret only needs the secret replaced on the
  Edit page; a revoked grant (`invalid_grant`) needs *Authorize* again.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff format . && ruff check .
pytest --cov            # coverage must stay at 100 %
cp .env.example .env    # then fill in SECRET_KEY / ADMIN_PASSWORD
email-oauth2-proxy-web  # runs on http://localhost:8080, IMAP on 1993
```
