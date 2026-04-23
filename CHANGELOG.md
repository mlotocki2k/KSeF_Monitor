# Changelog

All notable changes to KSeF Monitor are documented here.

## [0.5.1] — 2026-04-23 (UI auth UX)

### Browser UI auth — V5-12 + V5-13

V5-01 (audit) closed UI bypass and required Bearer auth for everything. With
no browser-friendly login, users had to paste the API token into a localStorage
modal that re-opened on every dashboard 401 — effectively unusable. V5-12 added
a stop-gap cookie that just stored the token; V5-13 replaces it with proper
user accounts.

**V5-13 — first-launch setup wizard, user/pass, DB-backed sessions**

- New tables (`alembic` revision `e0f1g2h34567`):
  - `ui_users` — id, username (unique), password_hash, created_at, last_login_at
  - `ui_sessions` — id (64-char hex), user_id (FK CASCADE), expires_at, created_at, last_accessed_at
- Password hashing: `bcrypt` (12 rounds), constant-time verify, returns False on corrupted hash
- Sessions: 256-bit opaque IDs (`secrets.token_hex(32)`), 7-day rolling TTL — sliding renewal on each authenticated request
- Routes:
  - `GET/POST /ui/setup` — first-launch wizard, locks once any user exists (idempotent guard, race-safe under concurrent submit)
  - `GET/POST /ui/login` — username + password form
  - `POST /ui/logout` — DELETE from `ui_sessions` + clear cookie
  - `GET /ui/account` — show username; `POST /ui/account/password` — change password (revokes all sessions including current)
- Middleware: cookie validates against DB, falls back to Bearer for curl/integrations; unauthenticated `/ui/*` redirects to `/ui/setup` if 0 users else `/ui/login?next=<path>`
- `/ui/setup`, `/ui/login`, `/ui/logout` exempt from auth (else login flow itself is unreachable)
- Open-redirect guard on `next=` (whitelisted to internal `/ui` paths only — blocks `https://evil/x`, `//evil`)
- Brute-force guard: `slowapi` 5/min on `POST /ui/login` and `POST /ui/account/password`, 3/min on `POST /ui/setup`
- Cookie flags: `HttpOnly`, `SameSite=Strict`, `Secure` when scheme is https, `path=/`, `Max-Age=7d`
- HTML templates: new `setup.html`, `account.html`; `login.html` rewritten with username field; `base.html` shows username in navbar + Logout button when session present
- API auth helper `apiCall` (and `downloadFile`, push reveal) in templates use `credentials: 'same-origin'` so the cookie rides browser fetch — no Bearer needed in JS
- localStorage Bearer modal removed entirely (`getToken`, `saveToken`, `clearToken`, `showTokenModal`, `hideTokenModal`, `TOKEN_KEY`, `#token-modal` block)

**Upgrade path from v0.5.0 — zero key regeneration**

- `api.auth_token` from existing config keeps working as Bearer for curl /
  iOS push pairing / integrations — unchanged
- `main.py` bootstrap: when database is initialized, `auth_token` is set
  (≥ 8 chars), and 0 UI users exist → auto-create user `admin` with
  password = the configured `auth_token`. Logs a warning instructing
  the operator to log in and change the password via `/ui/account`.
- Net effect: pull `v0.5.1` image, restart container → log in to UI as
  `admin` / `<your existing token>` → all old API/Bearer flows still work
- For fresh installs (no `auth_token` in config) → `/ui/setup` wizard runs
  on first browser visit (V5-13 default flow)

**V5-12 — interim cookie session (superseded by V5-13)**

- Replaced localStorage Bearer with HttpOnly cookie. Cookie value was the API
  token itself (no DB users yet). Removed in V5-13 — superseded by opaque
  session IDs tied to user rows.

**CLI — `app.user_admin`**

- `python -m app.user_admin list` — list users
- `python -m app.user_admin add <username>` — create user (prompts for password twice)
- `python -m app.user_admin reset-password <username>` — reset (revokes all sessions)
- `python -m app.user_admin delete <username>` — delete (refuses last user; would lock UI to setup wizard, intentional)
- `python -m app.user_admin cleanup-sessions` — purge expired

**Dependencies**

- `bcrypt>=4.2.0,<5.0.0` added to `requirements.txt`

**Tests**

- New `tests/test_ui_user_auth.py`: 49 tests covering hashing, validation, user CRUD, session lifecycle (create/validate/expire/cleanup/sliding renewal), setup wizard (form/POST/lock-after-first-user/race), login flow (success/wrong-password/unknown-user/no-users-bounce/open-redirect/protocol-relative), session auth (cookie grants UI+API, Bearer parity, invalid cookie redirect), logout (DB revocation + cookie clear), account password change (current-required, mismatch-rejected, success-revokes-sessions, unauthenticated-redirect)
- `tests/test_api_auth.py` updated: replaced V5-12 cookie-equals-token tests with `TestUiAuthEndpointsExempt` (login/setup/logout never 401); existing `TestUiAuth` updated for redirect-to-login flow (401→303)
- `tests/test_db_migration.py` head revision bumped from `d9e0f1g2h345` to `e0f1g2h34567`
- 85 of the 85 V5-13 + V5-12 + adjacent tests pass

### Known follow-ups (non-blocking)

- Multi-user admin panel (add/delete other users from UI) — currently CLI-only
- Optional 2FA / TOTP for `/ui/login`
- Session list in account page (revoke individual devices)
- Rotate cookie value on each request (defense in depth against session-fixation if cookie ever leaked over a misconfigured proxy)

---

## [0.5.0] — 2026-04 (security-hardened)

### Security — fixes from audit `20260421_security_audit_docker_v0_5_test_branch.md`

**P1 — HIGH severity closures**

- **V5-01** narrow API auth whitelist from pattern-match (`/ui/**`, `/api/v1/invoices/**/pdf|xml`, `/api/v1/push/devices`, `/api/v1/monitor/ksef-status`) to exact-match `{/docs, /redoc, /openapi.json, /api/v1/monitor/health}`. `api.ui_public=true` config opt-in re-enables `/ui` bypass for legacy reverse-proxy deployments.
- **V5-02** mask `pairing_code` in unauthenticated `/ui/push` and `/api/v1/push/setup` — now shows `X…Y` preview only. Plaintext code + QR moved behind auth-gated `GET /api/v1/push/pairing`. Pairing code widened from 32-bit → 64-bit (`secrets.token_hex(8)`).
- **V5-03** `/api/v1/invoices/{ksef}/pdf|xml` auth bypass removed; `ksef_number` validated via Pydantic `KsefNumberPath` regex at path-param layer (422 on mismatch); `Content-Disposition` filename uses `urllib.parse.quote()`.
- **V5-04** supply chain pinning:
  - `urllib3>=2.6.0,<3.0.0` (closes CVE-2025-66418 CVSS 8.9, CVE-2025-66471)
  - `starlette>=0.49.1,<1.0.0` (closes CVE-2025-62727; caps below 1.0 for Python 3.9 compat)
  - `python-multipart>=0.0.22,<1.0.0` (closes CVE-2024-53981, CVE-2026-40347, CVE-2026-24486)
  - `cryptography==46.0.7` unified across `pyproject.toml` and `requirements.txt` (closes CVE-2026-39892)
  - New `requirements.lock` built with `pip-compile --generate-hashes`; Dockerfile installs via `pip install --require-hashes`.
  - CI adds `pip-audit --strict` against lockfile and `trivy image` scan of the built container (exit-code 1 on CRITICAL/HIGH).
  - **Known follow-up:** lockfile was compiled under Python 3.12 in the dev sandbox; regenerate under Python 3.11 (matching Dockerfile base) before tagging release.

**P2 — MEDIUM severity closures**

- **V5-05** security headers expanded: `Content-Security-Policy` (default-src 'self', frame-ancestors 'none'), `Strict-Transport-Security`, `Referrer-Policy`, `Permissions-Policy`.
- **V5-06** per-endpoint `slowapi` rate limits on all mutating routes and invoice downloads: `/monitor/trigger` 2/min, `/initial-load/start` 1/hr, `/push/regenerate` 5/hr, `/push/reset` 1/hr, `/invoices/{}/pdf|xml` 30/min. All limits overridable in `api.rate_limit` config.
- **V5-07** shared SSRF guard `app._ssrf_guard.is_safe_public_url` applied to webhook notifier (existing) and CIRFMF PDF generator URL (new — rejects private/loopback/link-local/multicast/reserved IPs).
- **V5-08** `xhtml2pdf.pisa.CreatePDF` passes `link_callback` that allows only `data:` URIs and bundled template paths — blocks SSRF/LFI through user-customized PDF templates.
- **V5-09 / V5-12** version string unified to `0.5.0`, single-source via `app.__version__` (was split across `"2.0.0"`, `"0.4.0"`, and literal strings).

**P2 — hardening**

- **V5-10** Tailwind CSS self-hosted (`app/ui/static/tailwind.min.css`, built from scanned templates — 15 KB vs. 3 MB CDN snapshot). CDN dependency removed from `base.html`. Cache-busting via `?v={version}` query string. Build reproducibility: `app/ui/tailwind.config.js`, `tailwind.input.css`, `README.md` with regen command.

**P3 — backlog / defense in depth**

- **V5-11** initial-load job `StartJobRequest` rejects date ranges > 5 years (1826 days) via Pydantic `model_validator`.
- **v0.4 F-06** Jinja2 autoescape extension-driven — `_jinja_autoescape(name)` callable enables autoescape for `.html*`, `.json.j2`, `.xml*`. Shipped JSON templates wrapped in `{% autoescape false %}` to preserve explicit `|json_escape` behavior; user-customized `.json.j2` templates that omit the filter now get HTML-style escaping as a safety net.
- **v0.4 F-07** `_migrate_schema` runtime `ALTER TABLE` f-string loop replaced by `alembic.command.upgrade(head)` / `stamp(head)` detection based on `alembic_version` table presence. Warning logged when stamping a non-pristine DB (operator should run `alembic stamp <rev>; alembic upgrade head` manually for v0.4 → v0.5 column-level migrations).
- **v0.4 F-09** `entrypoint.sh` rootless mode: when `id -u` ≠ 0, skip `usermod`/`groupmod`/`chown` dance, do best-effort template seeding, `exec python main.py` directly (supports Podman rootless, userns-remap, rootless Docker).

### Known follow-ups (non-blocking)

1. **Regenerate `requirements.lock` under Python 3.11** — current lockfile was built with Python 3.12. Plan specified 3.11 to match Dockerfile base. Depends on Docker Desktop availability in the build environment.
2. **Tighten CSP `script-src 'unsafe-inline'`** — move `push.html` reveal JS to `app/ui/static/push.js` and switch CSP to hashed/nonce-based script allowlist.
3. **Unify slowapi limiter module location** — `app/api/_limiter.py` sibling-to-API works, but `app/_limiter.py` (beside `_ssrf_guard.py`) would be more consistent.

### Test results

`pytest tests/` reports **626 passed / 2 skipped / 15 pre-existing failures** (Prometheus + timezone tests unrelated to audit). All new tests for V5-01…V5-11 pass (+13 net new tests).

---

## [0.4.0] — 2026-02

_See git history for the v0.4 baseline. The v0.4 → v0.5 security delta is documented above._
