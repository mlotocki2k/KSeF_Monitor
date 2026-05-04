# Changelog

All notable changes to KSeF Monitor are documented here.

## [0.5.2] — 2026-05-04 (UI auth security audit remediation)

Closes 14 findings from `audit/20260504_security_audit_v0_5_1_ui_auth.md`
(focused review of V5-12/V5-13/V5-14 UI auth surface added in 0.5.1 that
hadn't gone through the v0.5.0 audit cycle). 0 CRITICAL, 0 HIGH originally;
6 MEDIUM, 6 LOW, 5 INFO. All addressed.

### Session security

- **U-01** Cookie `Secure` flag now honors `X-Forwarded-Proto` and
  exposes `api.cookie_secure_mode` (`auto` | `always` | `never`). Behind
  a TLS-terminating reverse proxy `request.url.scheme` stays `http`; the
  pre-fix path stripped `Secure` despite the user-facing connection
  being HTTPS.
- **U-04** Opt-in session UA fingerprint binding via
  `api.session_strict_binding`. SHA-256(User-Agent) stored in new
  nullable `ui_sessions.ua_hash` column; mismatch revokes the session
  and bounces to `/ui/login`. Pre-existing rows without `ua_hash` are
  grandfathered (graceful enable on running deployments).
- **U-09** Absolute session lifetime cap of 30 days (`SESSION_ABSOLUTE_LIFETIME`)
  enforced regardless of sliding renewal. Caps the value of a stolen
  cookie even on always-active accounts.
- **U-12** Audit log surface: session create, revoke, absolute-cap eviction,
  failed-login lockout — username_len rather than raw username (U-08
  partial mitigation).

### Authentication strength

- **U-02** SHA-256 + base64 pre-hash for passwords >72 bytes — closes
  bcrypt's silent-truncation collision risk and makes the codebase
  bcrypt-5.0-ready (5.0 raises `ValueError` on >72B otherwise → DoS on
  upgrade for users with long passwords). bcrypt 4.x continues to work.
- **U-03** Per-username brute-force lockout (new `ui_login_attempts`
  table): 5 fails in a 15-minute sliding window → 15-minute lockout.
  `is_login_locked` checked before bcrypt to avoid burning CPU on
  hot-locked accounts and to deny the timing oracle.
- **U-07** Constant-time login: bcrypt always runs (against a
  pre-computed dummy hash when the username does not exist), defeating
  the timing-based username enumeration probe.
- **U-11** Password strength: top-100 breach blocklist (rockyou top-100,
  NIST SP 800-63B guidance, in-process — no corpus dependency) + reject
  passwords containing the username (≥3 chars, case-insensitive).

### Setup wizard hardening

- **U-06** New `create_first_admin_atomic(db, username, password)`
  helper uses `BEGIN IMMEDIATE` to acquire the SQLite RESERVED lock
  eagerly, closing the TOCTOU window between `count_users()` and
  `create_user()` that previously allowed two simultaneous setup POSTs
  to both succeed and create twin admin accounts.

### Web hardening

- **U-05** CSP `script-src` now uses a per-request nonce (16-byte
  `secrets.token_urlsafe`) instead of `'unsafe-inline'`. All inline
  `<script>` tags in `app/ui/templates/*.html` carry
  `nonce="{{ request.state.csp_nonce }}"`. `style-src 'unsafe-inline'`
  remains as a documented carryover (Tailwind utility deltas).
- **U-10** `_safe_next()` strict prefix check: rejects `/ui-attacker/…`
  paths (must be exactly `/ui` or start with `/ui/`).

### Code quality

- **U-13** `count_users()` uses `COUNT(*)` instead of materializing all
  row IDs.
- **U-15** `resolve_ui_session` catches only `(OperationalError,
  DBAPIError)` instead of bare `Exception` — DB hiccups still degrade
  gracefully but genuine programming errors propagate to the 500
  handler instead of being silently swallowed.
- **U-17** Username lookup, lockout keying, and login flow all
  case-insensitive (`func.lower`) — `admin` / `Admin` / `ADMIN` resolve
  to the same row, share the same brute-force counter, and cannot
  exist as separate accounts.

### Migrations

- `f1a2b3c45678` — phase6: `ui_login_attempts`
- `g2b3c4d56789` — phase7: `ui_sessions.ua_hash` (nullable)

### Test count

- `tests/test_ui_user_auth.py`: 91 cases (was 57).
- New classes: `TestUsernameCaseInsensitive` (3), `TestLoginLockout` (7),
  `TestCookieSecureFlag` (6), `TestSessionUaBinding` (6),
  `TestCspNonce` (3); plus extensions to `TestPasswordHashing`,
  `TestSetupWizard`, `TestSessionLifecycle`, `TestValidation`.
- `tests/test_db_migration.py`: head ref bumped to `g2b3c4d56789`.

### Bonus

- `chore: sync spec/openapi.json with KSeF production (2026-04-23 build)` —
  RR enum cleanup, 16-hex validation tightening, build bump
  `20260422.4 → 20260423.2`.
- `ci(deps): respect wontfix label` — `check-requirements-updates.yml`
  no longer auto-reopens issues marked wontfix when the same intentionally
  pinned packages stay outdated; novel packages still create a fresh
  alert (closes recurring noise from issue #28).

---

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

### Fixes on top of V5-13 (same 0.5.1)

**V5-14 — `/ui/account` broken when auth_token empty or `ui_public=true`**

- Bug: session state (`request.state.ui_user_id` / `ui_username`) was only
  populated inside the auth middleware. That middleware was either skipped
  (`auth_token` empty, dev mode) or short-circuited (`ui_public=true`,
  reverse-proxy mode) → navbar showed no account/logout links, and
  `/ui/account` redirected to `/ui/login` in a loop.
- Fix: split into two middleware layers.
  - `resolve_ui_session` — always runs (registered last → outermost in
    Starlette). Reads `mksef_session` cookie, calls `validate_session`,
    populates `request.state` for downstream handlers.
  - `verify_auth` — only registered when `auth_token` is set. Now a
    pure gate: accept if `ui_user_id` already set by resolver, else Bearer,
    else redirect/401. No longer owns cookie validation.
- Templates: Jinja `{% if ui_username %}` now evaluates truthy under every
  config permutation → navbar account + logout always render for logged-in
  users, `/ui/account` form renders instead of redirecting.
- Regression tests: 4 new in `tests/test_ui_user_auth.py::TestSessionResolver`
  covering `ui_public=true` + account, navbar visibility with ui_public,
  no-auth-token + account, password change revoke under ui_public.

**V5-15 — Dark theme + iOS app visual alignment**

- Palette aligned with iOS `Assets.xcassets` dark appearance values:
  `--app-bg: #0B1A3E` (deep navy), `--card-bg: #1A2B50`, `--accent: #007AFF`
  (Apple blue), status colors from iOS system (green `#34C759`, orange
  `#FF9500`, red `#FF3B30`).
- Dark-only; `<meta name="color-scheme" content="dark">`. Tailwind base
  utilities overridden with `!important` in a single `<style>` block so
  prebuilt `tailwind.min.css` doesn't need to regenerate.
- iOS app icon reused: `app/ui/static/icon-64.png` (navbar), `icon-128.png`
  (apple-touch-icon), `favicon.png` (32x32). Source:
  `monitor_ksef_ios/.../AppIcon.appiconset/icon_dark_1024.png`, resized
  with `sips`. Inline SVG logos in `base.html`, `login.html`, `setup.html`
  replaced with `<img>` tags.
- Footer version string reads `{{ ui_version }}` (was hard-coded `v0.5`).

**V5-16 — `POST /api/v1/monitor/trigger` returned "Trigger failed"**

- Bug: router called `monitor.scheduler.force_next_run()` — a phantom API.
  `Scheduler` exposes `should_run()` / `wait_until_next_run()`, not
  `force_next_run`. Every UI "Sprawdź" click raised `AttributeError` →
  caught and returned `{"triggered": false, "message": "Trigger failed"}`.
- Fix: call `monitor.trigger_check()` (already exists in `InvoiceMonitor`,
  flips `_manual_trigger = True` — same path used by the `SIGUSR1` CLI
  signal). Removes the scheduler-existence check.
- Tests: `tests/test_api_monitor.py::TestTriggerEndpoint` asserts
  `monitor.trigger_check.assert_called_once()`; `tests/test_api_rate_limit.py`
  `_make_app` mock updated likewise.

**V5-17 — PDF footer stamped `KSeF Monitor v0.3` on every invoice**

- Bug: both PDF renderers had the version hard-coded as `v0.3`, never
  updated since the 0.3 release. Every invoice generated — by ReportLab
  fallback or xhtml2pdf primary — carried the stale stamp.
- Fix: single source of truth via `app.__version__`.
  - `app/invoice_pdf_generator.py:1002` (ReportLab): f-string reads
    `_APP_VERSION`.
  - `app/invoice_pdf_template.py:304`: adds `app_version` to Jinja context.
  - `app/templates/invoice_pdf.html.j2:817`: footer uses `{{ app_version }}`.
- On test branch the footer now reads `v0.5.1`. After merge to main, it
  will follow whatever `app/__init__.py` declares.

### Known follow-ups (non-blocking)

- Multi-user admin panel (add/delete other users from UI) — currently CLI-only
- Optional 2FA / TOTP for `/ui/login`
- Session list in account page (revoke individual devices)
- Rotate cookie value on each request (defense in depth against session-fixation if cookie ever leaked over a misconfigured proxy)
- Light-mode toggle (currently dark-only to match iOS default theme)

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
