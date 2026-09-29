# UI Redesign (shadcn-style) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the Pico.css look with a shadcn/ui-style design (zinc palette, cards, badges, sidebar) using one hand-written, vendored stylesheet – no build step, no new dependencies.

**Architecture:** `app/static/app.css` holds shadcn design tokens as CSS variables (light + `prefers-color-scheme: dark`) and a small component set (`.btn` variants, `.card`, `.badge` variants, `.input/.select/.textarea`, `.field`, `.table`, `.alert`, `.toast`, `.sidebar`, `.steps`, `.code-block`). Templates switch to these classes; Jinja macros in `app/templates/_ui.html` render repeated pieces (status badge, form field). A tiny inline script adds copy-to-clipboard buttons and auto-dismissing toasts. Pico is deleted.

**Decision (chat, 2026-09-29):** option 1 – own shadcn-style CSS, system font stack (no external font request), dark mode follows OS.

## Context

The web UI works but looks bare ("fapados"). User asked for a shadcn-like look. The app renders Jinja2 server-side without a JS build, so the React shadcn library cannot be used; its visual language is reproduced in CSS instead. Backend, routes and JSON APIs are unchanged → no endpoint-doc/Bruno changes.

Branch `feature/6-ui-redesign` from `main` @ 16bc6c8. Plan renamed to `docs/plans/ui-redesign.md` in Task 1.

## Global Constraints

- No route, form-field name or response-code changes. Existing web tests must keep passing unmodified, except `test_static_served` (Pico → app.css). Strings the tests rely on stay: "No accounts yet", "Needs authorization", "Authorized", "leave blank to keep", "Start authorization", "Restart authorization", `name="redirect_url"` (must NOT appear before an authorization is started), `name="use_pkce"`, `href="/logs"`, `<meta http-equiv="refresh" content="10">` only when auto-refresh is on, and on the Logs page only data rows use `<tr class=`.
- In the authorize page the first occurrence of the authorization URL must be inside an HTML attribute (`tests/test_web_authorize.py::extract_state` slices up to the next `"`).
- All user/provider text stays autoescaped. No external requests (fonts/CDN).
- `ruff format . && ruff check .`, `pytest --cov` 100 %. Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Dark mode legibility (badges, alerts, code blocks) – checked visually in Task 3.
2. Long values (auth URL, error messages, tracebacks) must wrap, never widen the page – `overflow-wrap:anywhere` on `.code-block`, table cells; checked visually at 375 px.
3. Sidebar collapses to a top bar below 768 px – checked visually.
4. Copy button works without HTTPS (clipboard API unavailable on plain http from non-localhost) – fallback to `select()` + `document.execCommand("copy")`.
5. Delete/revoke still ask for confirmation (`onsubmit="return confirm(...)"` kept).

---

### Task 1: Stylesheet, layout, macros (TDD for structural hooks)

**Files:** Create `app/static/app.css`, `app/templates/_ui.html`; Modify `app/templates/base.html`, `app/templates/login.html`; Delete `app/static/pico.min.css`; Modify `pyproject.toml` package-data if needed (`static/*.css` already covers it); Test `tests/test_app.py`, `tests/test_ui.py`.

- [ ] **Step 1:** `mv docs/plans/nifty-skipping-lollipop.md docs/plans/ui-redesign.md`
- [ ] **Step 2: Failing tests**

`tests/test_app.py` – replace `test_static_served`:

```python
async def test_static_served(client):
    response = await client.get("/static/app.css")
    assert response.status_code == 200
    assert "--primary" in response.text
    assert (await client.get("/static/pico.min.css")).status_code == 404
```

`tests/test_ui.py`:

```python
async def test_layout_has_sidebar_navigation(admin):
    body = (await admin.get("/")).text
    assert '<aside class="sidebar"' in body
    for href in ('href="/"', 'href="/logs"', 'href="/accounts/new"'):
        assert href in body
    assert 'aria-current="page"' in body  # active item marked
    assert "/static/app.css" in body


async def test_login_page_is_centered_card_without_sidebar(client):
    body = (await client.get("/login")).text
    assert 'class="auth-card' in body
    assert "sidebar" not in body


async def test_flash_rendered_as_toast(admin):
    from tests.test_forms import VALID

    await admin.post("/accounts", data=VALID)
    body = (await admin.get("/")).text
    assert 'class="toast toast-success"' in body


async def test_status_badges(admin):
    from tests.test_forms import VALID

    await admin.post("/accounts", data=VALID)
    body = (await admin.get("/")).text
    assert 'class="badge badge-warning"' in body and "Needs authorization" in body
```

- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement**
  - `app.css` tokens (`:root`): `--background #fff; --foreground #09090b; --muted #f4f4f5; --muted-foreground #71717a; --card #fff; --border #e4e4e7; --input #e4e4e7; --primary #18181b; --primary-foreground #fafafa; --secondary #f4f4f5; --destructive #dc2626; --success #16a34a; --warning #d97706; --ring #a1a1aa; --radius .5rem`; dark overrides under `@media (prefers-color-scheme: dark)` (`--background #09090b; --foreground #fafafa; --muted #27272a; --card #09090b; --border #27272a; --primary #fafafa; --primary-foreground #18181b …`). Font stack `ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`; mono `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`. Components as listed in Architecture; focus-visible ring `0 0 0 2px var(--background), 0 0 0 4px var(--ring)`.
  - `base.html`: `<link rel="stylesheet" href="/static/app.css">`; when `admin`: `.app-shell` grid = `<aside class="sidebar">` (brand, nav links with inline SVG icons, `aria-current="page"` via `request.url.path`, logout button at bottom) + `<main class="content">`; else a centered `<main class="auth-shell">`. Flash messages → `<div class="toast toast-{{category}}" role="status">` stack, top-right, auto-dismiss after 5 s. Inline `<script>` (≈20 lines): toast dismiss; `[data-copy]` buttons copy the value of `#<target>` with clipboard API + execCommand fallback, show "Copied".
  - `_ui.html` macros: `status_badge(status, last_error=None)`, `field(name, label, values, errors, type="text", required=True, hint=None)`, `page_header(title, subtitle=None, actions=None)` (caller block).
  - `login.html`: `<div class="auth-card card">` with brand, title, inputs `.input`, full-width primary button, error as `.alert.alert-destructive`.
  - `render()` already passes `request` to templates (Starlette), so `request.url.path` is available.
- [ ] **Step 5: Run** `pytest tests/test_ui.py tests/test_app.py tests/test_web_auth.py` → PASS.
- [ ] **Step 6: Commit** `feat(ui): shadcn-style stylesheet, sidebar layout and login card`.

### Task 2: Page templates

**Files:** Modify `app/templates/accounts/list.html`, `accounts/form.html`, `accounts/authorize.html`, `logs.html`; Test `tests/test_ui.py`.

- [ ] **Step 1: Failing tests** (append to `tests/test_ui.py`):

```python
async def test_authorize_page_steps_and_copy_button(admin, app):
    from tests.test_web_authorize import create

    account_id = await create(admin, app)
    body = (await admin.post(f"/accounts/{account_id}/authorize/start")).text
    assert 'class="steps"' in body
    assert 'data-copy="auth-url"' in body
    assert 'id="auth-url"' in body


async def test_account_form_sections(admin):
    body = (await admin.get("/accounts/new")).text
    assert body.count('class="card') >= 3  # account, server, oauth client sections


async def test_logs_page_uses_log_view(admin):
    import logging

    logging.getLogger("app.test.ui").warning("styled")
    body = (await admin.get("/logs")).text
    assert 'class="table log-table"' in body
    assert 'class="badge badge-warning"' in body
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**
  - **list.html:** page header "Accounts" + subtitle + primary "Add account" button; stat cards row (total / authorized / needs attention); `.card` wrapping `.table` (email + host muted underneath, provider, status badge + error text muted/truncated with `title`, token expiry, last login, actions: ghost buttons Authorize / Edit / destructive Delete). Empty state card: icon, "No accounts yet", CTA.
  - **form.html:** header; three `.card` sections – *Account* (email, provider select), *IMAP server* (host, port in 2-col grid), *OAuth client* (client id, secret with hint, authorization URL, token URL, scope, redirect URI, PKCE checkbox as switch-looking checkbox); sticky footer with Cancel (outline, links to `/`) + primary submit. Preset JS unchanged.
  - **authorize.html:** header with email + status badge; error `.alert-destructive`; `.steps` ordered list: (1) Start/Restart button, (2) auth URL in readonly `<input class="input mono" id="auth-url" value="{{ auth_url }}">` + Copy button + "Open" button (`target=_blank`), muted hint about the failing localhost page, (3) paste form (textarea) – step 2/3 only rendered under the same conditions as today; danger zone card with "Remove stored tokens" when authorized/error.
  - **logs.html:** header; filter bar card (inline flex: level select, search input, rows input, auto-refresh checkbox, Apply); meta line muted; `.card` with `<table class="table log-table">`; level as badge (`badge-destructive/warning/secondary`), time mono muted, message `<pre class="log-msg">`; `<thead>` rows have no class.
- [ ] **Step 4: Run** `ruff format . && ruff check . && pytest --cov` → PASS, 100 %.
- [ ] **Step 5: Commit** `feat(ui): restyle accounts, authorize, form and logs pages`.

### Task 3: Visual check + README screenshot note

- [ ] **Step 1:** Run the app locally (`email-oauth2-proxy-web` with temp DATA_DIR), open every page in the browser (Claude in Chrome or headless) at 1280 px and 375 px, light and dark; fix overflow/contrast issues found.
- [ ] **Step 2:** Container build + smoke (`docker build --load`, health, /login 200).
- [ ] **Step 3: Commit** `fix(ui): visual polish` (only if Step 1 changed anything).

## Verification

- `pytest --cov` 100 %, ruff clean.
- Manual: login → accounts list (empty + with account) → add form → authorize (start, copy button, paste) → logs (filters, auto-refresh) in light/dark and on a phone-width viewport.
