# Deployment guide

Target: one Linux host (VM, NAS, Raspberry Pi…) running Docker. The proxy is a
single container; state lives in one named volume (`/data`, SQLite).

## 1. Prerequisites

- Docker Engine 24+ with the Compose plugin (`docker compose version`).
- Outbound HTTPS to the mail provider (`imap.gmail.com:993`,
  `outlook.office365.com:993`, token endpoints on 443).
- A place to run the web UI safely: it must not be exposed to the internet
  without HTTPS + a strong admin password (see §5).
- OAuth client credentials from your provider (README → *Registering an OAuth client*).

## 2. Get the code

```bash
git clone git@github.com:LovaszCC/email-oauth-proxy.git
cd email-oauth-proxy
```

## 3. Configure

Generate the encryption key once and keep it safe – it protects every stored
client secret and token, and losing it means re-authorizing every account:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# no local python? use the image:
docker run --rm python:3.12-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
```

Put secrets in a `.env` file next to `docker-compose.yml` (git-ignored) and let
Compose read them instead of editing the YAML:

```bash
cat > .env <<'ENV'
ADMIN_USER=admin
ADMIN_PASSWORD=<long random password>
SECRET_KEY=<the Fernet key from above>
LOG_LEVEL=INFO
ENV
chmod 600 .env
```

Then change the `environment:` block of `docker-compose.yml` to reference them:

```yaml
    environment:
      ADMIN_USER: ${ADMIN_USER}
      ADMIN_PASSWORD: ${ADMIN_PASSWORD}
      SECRET_KEY: ${SECRET_KEY}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
```

Ports (defaults in `docker-compose.yml`):

| Host port | Purpose | Recommendation |
|---|---|---|
| `8080` | web UI | bind to `127.0.0.1:8080` and put a TLS reverse proxy in front, or restrict by firewall |
| `127.0.0.1:1993` | IMAP for mail clients | keep on localhost / LAN only – **the IMAP password is ignored**, anyone reaching this port can read the mailboxes |

If mail clients run on other LAN machines, change `127.0.0.1:1993:1993` to
`<LAN-IP>:1993:1993` and firewall it to those machines.

## 4. First start

```bash
docker compose up -d --build
docker compose logs -f          # wait for "IMAP proxy listening on 0.0.0.0:1993"
curl -s http://127.0.0.1:8080/api/health
# {"status":"ok","imap_listening":true,"accounts_total":0,"accounts_authorized":0}
```

Open `http://<host>:8080`, log in, **Add account**, then follow the
authorization flow (README → *Adding and authorizing an account*). The
authorization link opens on *your* browser; the redirect to
`http://localhost/?code=…` fails to load – copy that address and paste it back.

Point the mail client at `<host>:1993`, no TLS, normal password, username =
account email, password = anything.

## 5. HTTPS for the web UI (recommended)

Example with Caddy on the same host (automatic Let's Encrypt):

```
# /etc/caddy/Caddyfile
mailproxy.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

With nginx:

```nginx
server {
    listen 443 ssl;
    server_name mailproxy.example.com;
    ssl_certificate     /etc/letsencrypt/live/mailproxy.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mailproxy.example.com/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

In both cases change the compose port to `127.0.0.1:8080:8080`. Consider
adding basic auth or IP allow-listing at the reverse proxy: the admin login
has no rate limiting.

## 6. Backup and restore

Everything is in the `proxy-data` volume (`proxy.db`) plus `.env`
(`SECRET_KEY`). Back up both; the database is useless without the key.

```bash
# backup
docker compose stop
docker run --rm -v email-oauth-proxy_proxy-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/proxy-data-$(date +%F).tgz -C /data .
docker compose start

# restore
docker compose down
docker volume create email-oauth-proxy_proxy-data
docker run --rm -v email-oauth-proxy_proxy-data:/data -v "$PWD":/backup alpine \
  sh -c "cd /data && tar xzf /backup/proxy-data-YYYY-MM-DD.tgz"
docker compose up -d
```

(The volume name is `<project-dir>_proxy-data`; check with `docker volume ls`.)

## 7. Upgrade

```bash
git pull
docker compose up -d --build
```

Schema is created on start (`create_all`); there are no migrations yet. Stopping
the container disconnects mail clients cleanly – they reconnect on their own.

## 8. Operations cheat sheet

| Need | Command |
|---|---|
| Logs | `docker compose logs -f --tail=200` |
| More detail | set `LOG_LEVEL=DEBUG`, `docker compose up -d` |
| Health | `curl -s http://127.0.0.1:8080/api/health` (also the Docker `HEALTHCHECK`) |
| Test IMAP path | `printf 'A1 CAPABILITY\r\nA2 LOGOUT\r\n' \| nc 127.0.0.1 1993` |
| Rotate admin password | edit `.env`, `docker compose up -d` |
| Account stuck in *Error* | open the account → *Authorize* → *Start authorization* again; the error text on the list page says why (refresh rejected, upstream rejected, …) |

## 9. Troubleshooting

- **Client says "authentication failed"** – account status in the UI: *Needs
  authorization* → authorize it; *Error* → read the message. `Unknown account`
  in the client means the username does not match the email stored in the UI.
- **Gmail: no refresh token after authorizing** – the Google client must be a
  *Desktop app* and the consent prompt must be shown; the proxy sends
  `access_type=offline&prompt=consent` automatically. Remove the app from
  <https://myaccount.google.com/permissions> and authorize again.
- **Office 365: `AADSTS…` errors** – for single-tenant apps use the *Custom*
  provider and replace `common` with your tenant id in both URLs.
- **Container restarts, health failing** – `docker compose logs`; a missing
  `SECRET_KEY`/`ADMIN_PASSWORD` or an invalid Fernet key aborts startup with a
  clear message.
- **Permission denied on /data** – only when bind-mounting a host directory
  instead of the named volume: `chown -R 10001:10001 <dir>  (user `emailproxy`)`.
