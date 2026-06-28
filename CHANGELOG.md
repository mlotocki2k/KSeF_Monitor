# Changelog

All notable changes to KSeF Monitor are documented here.

## [0.6.0] (unreleased) — certificate login, UPO, Lightweight Polling, schema coverage

### Certificate login, UPO, Lightweight Polling, API 2.6.1 (2026-06-28)

**Authentication**
- Certificate login (XAdES-BES, RSA-SHA256) as an alternative to the KSeF token —
  `ksef.auth_method="certificate"` + a `.p12`/`.pfx`; signs `AuthTokenRequest` →
  `POST /auth/xades-signature`. Web UI upload at `/ui/certificate`. Certificate
  validity is checked before auth. See `docs/KSEF_CERTIFICATE_AUTH.md`.
- `publicKeyId` sent in `/auth/ksef-token` for KSeF v2.5.0 public-key rotation.
- `X-Error-Format: problem-details` requested so 400/429 return `problem+json`.

**UPO (Urzędowe Poświadczenie Odbioru)**
- Download UPO for sales invoices (Subject1) in a separate phase
  (`monitoring.fetch_upo`): resolves the session, downloads + SHA-256-verifies
  `/sessions/{ref}/invoices/ksef/{ksef}/upo`, saves `{output_dir}/upo/{ksef}.xml`,
  sets `has_upo`/`upo_path`. Web UI download button + `GET /api/v1/invoices/{ksef}/upo`.

**Lightweight Polling**
- `monitoring.lazy_artifacts` — decouple XML/PDF download from detection (push
  fires from metadata; artifacts fetched in a separate phase, own rate budget).
- `monitoring.subject_poll_intervals` — configurable per-subject polling interval.

**Dependencies / spec**
- OpenAPI specs synced to KSeF 2.6.1 (test/demo/prod).
- cryptography 47→48.0.1 (GHSA-537c-gmf6-5ccf), bcrypt 5.0, pytz 2026.2,
  reportlab 4.5.0; added signxml + lxml (certificate signing).

**Fixes**
- Global API rate limit now enforced under Starlette 1.x — slowapi's default-limit
  middleware no-ops on FastAPI `include_router` routes; enforced explicitly.

### Invoice schema coverage + FA_RR rewrite (2026-06-03)

Full audit of FA(3) v1-0E field coverage against the published XSD, a ground-up
rewrite of the FA_RR parser/template against the real schema, and real XSD files
replacing the previous reference stubs. All schema sources verified against
`crd.gov.pl` (CRD) and `CIRFMF/ksef-docs`.

### Schemas (`spec/`)
- **FA(3) v1-0E** — confirmed current; local copy identical to CRD + CIRFMF
  (`sha256 b646b6b…`). No change.
- **FA(2) v1-0E** — reference stub replaced with the real published XSD
  (namespace `…/2023/06/29/12648/`).
- **FA_RR** — the old `schemat_FA_RR_v1-0E.xsd` stub described a schema that does
  not exist. Replaced with the real **FA_RR(1) v1-1E** XSD
  (`spec/schemat_FA_RR(1)_v1-1E.xsd`, namespace `…/2026/03/06/14189/`).

### FA_RR parser — full rewrite (was non-functional)
- The registered FA_RR namespaces (`…/12978/`, `…/13836/`) do not exist on CRD,
  so real RR invoices never reached `FA_RRInvoiceXMLParser` (they fell through to
  the FA2 path). All FA_RR-specific field names in the old parser were invented
  (`KwotaVatRR`, `StawkaVatRR`, `P_15RR`, `OswiadczenieDostawcy`, …) — none exist
  in the real schema.
- `_FA_RR_NAMESPACES` now includes the real `…/14189/` (old IDs kept only as
  historical aliases). Parser rebuilt around the real structure: `FakturaRR`
  body, `FakturaRRWiersz` line items, fields `P_4A/P_4B/P_4C`, `P_5`, `P_6A-C`,
  `P_7-P_11`, `P_11_1/2`, `P_12_1/2`, `DokumentZaplaty`, `NrKontrahenta`,
  correction (`Podmiot1K/2K`, `NrFaKorygowany`, `NrKSeF/N`). Roles: Podmiot1 =
  nabywca (skupujący/issuer), Podmiot2 = rolnik (dostawca).
- `invoice_pdf_fa_rr.html.j2` rewritten to match (items, totals, payment
  documents, correction, rozliczenie).

### FA(3) — expanded field coverage
Parser (`invoice_xml_parser.py`) now extracts the previously-dropped elements,
rendered in both the xhtml2pdf template and the ReportLab fallback:
- **Corrections:** `Podmiot1K`/`Podmiot2K` (party data before correction),
  `NrFaKorygowany`, `OkresFaKorygowanej`, `NrKSeF`/`NrKSeFN` markers.
- **Markers:** `GV` (VAT group), `JST`, `StatusInfoPodatnika`, `SystemInfo`,
  `BrakID`, `IDWew`, `IDNabywcy`, `AdresKoresp`.
- **Authorized entity:** `PodmiotUpowazniony` (+ `RolaPU`, `EmailPU`, `TelefonPU`).
- **Payment:** `IPKSeF`, `LinkDoPlatnosci`, `RachunekWlasnyBanku`; `WZ`,
  `ZwrotAkcyzy` in header.
- **Transport:** `WysylkaZ`/`WysylkaPrzez`/`WysylkaDo`, `AdresPrzewoznika`.
- **Negations:** `P_19N`, `P_PMarzyN`, `P_22N`.
- **New means of transport:** `P_22B2-B4`, `P_22BT`, `P_22C1`, `P_22D1`,
  `P_NrWierszaNST`.
- **Order lines (advance corrections):** `UU_IDZ`, `P_12Z_XII`, `P_12Z_Zal_15`,
  `GTINZ`, `PKWiUZ`, `CNZ`, `PKOBZ`, `GTUZ`, `ProceduraZ`, `KwotaAkcyzyZ`,
  `StanPrzedZ`.
- **Attachments:** `Zalacznik/Tabela` (column headers, rows, totals).
- Render gap closed: `FP` and `TP` flags now shown in the template.

### Spec drift detection
- `.github/workflows/check_ksef_fa_schema.yml` matrix extended from FA(3)-only to
  also cover **FA(2) v1-0E** and **FA_RR(1) v1-1E** (CRD + CIRFMF cross-check).
  New-version scan now walks both `faktury/schemy/FA` and `faktury/schemy/RR`.

### Tests
- `test_multi_schema_parser.py`: FA_RR tests rewritten against the real schema;
  new `TestFA3ExtendedFields` class covering the added fields. 61 passed.

## [0.5.3] — 2026-05-06 (post-0.5.2 hotfix bundle)

Seven defects surfaced during pre-merge user testing of the 0.5.2 build.
None were caught by the audit cycle — a few were latent bugs from earlier
versions that only became visible once the UI auth path went live.

### Showstoppers

- **Fresh-install lockout (UI):** when `api.enabled=true` and `auth_token`
  was empty, F-01 auto-generated a 48-char random token AND `main.py`
  used that token as the bootstrap admin's password. The operator only
  saw the first 8 chars in WARNING logs (R-01 truncation), so the UI
  was effectively locked: `/ui/login` rejected every guess and
  `/ui/setup` short-circuited because `count_users()==1`.
  `ConfigManager` now sets `api["_auth_token_auto_generated"]` and
  `main.py` skips bootstrap on that marker — the wizard is the only
  sane entry point for a fresh install. Bootstrap still runs when the
  operator supplies `auth_token` themselves (v0.5.0 → v0.5.x upgrade).
- **Initial load: every invoice rejected.** `_map_export_invoice` was
  written against pre-v2.x KSeF field names — `ksefReferenceNumber`,
  `grossValue`, `subjectBy.…`, `invoiceHash.hashSHA.value`. Real
  `_metadata.json` from `/invoices/exports` follows the v2.4
  `InvoiceMetadata` schema (`ksefNumber`, `grossAmount`, `seller.nip`,
  `invoiceHash` as a base64 string). Every lookup returned `None` and
  `db.save_invoice` rejected each row with "Cannot save invoice without
  ksef_number". Re-mapped against the spec example, kept legacy keys as
  fallbacks, also picks up `isSelfInvoicing` / `hasAttachment`.
- **Initial load: KSeF 21405 on every other window.** Both
  `InitialLoadManager` and `InvoiceMonitor._cap_date_from` produced
  91-day windows. KSeF treats `dateRange` as inclusive, max 90 days.
  Fixed via a 89-day `_WINDOW_SPAN` plus a +1-day cursor advance — now
  consecutive windows are non-overlapping and each one is exactly 90
  days inclusive.

### Logging

- **U-12 audit log silently dropped (ALL `logger.info`).**
  `alembic.ini` had `[logger_root] level = WARNING`. `fileConfig()` in
  `alembic/env.py` runs on every boot and clobbered the `INFO` root
  level set by `app.logging_config`. Five of the seven U-12 audit-trail
  events claimed by 0.5.2 — session create / revoke, password change,
  user create, absolute-cap eviction — were therefore invisible in
  production. Bumped alembic root to `INFO`; `[logger_alembic]` and
  `[logger_sqlalchemy]` unchanged.

### GUI

- **Initial load progress stuck at 50% under "Ukończony".**
  `windows_completed` only incremented on a successful export, but the
  job ended in `status=completed` regardless. With the dateRange bug
  above, half the windows failed and the bar never moved past 50%.
  Now bumps the counter on the non-fatal failure path too. Also
  introduces a new `completed_with_errors` job status, an amber
  "Ukończony z błędami" badge, and an inline "Niepowodzenia okien"
  callout populated from `error_message`.
- **Per-window history view (phase 8 migration).** New
  `initial_load_windows` table with FK CASCADE to `initial_load_jobs`
  records every processed window: type, range, status (success/failed),
  imported, skipped, error message, duration. Surfaced via
  `GET /api/v1/initial-load/windows?job_id=…` and a
  "Pokaż historię okien" toggle on the status card — lazy-loaded
  table, no inline event handlers (CSP nonce stays clean).
- **Logo / nav spacing.** The active nav-link's blue background
  visually merged with the "Monitor KSeF" brand text. Added
  `ml-2 sm:ml-4` on the `<nav>` element so only the logo→menu gap
  widens; right-side action spacing is unchanged.

### Documentation

- **iOS App Store status notice.** The published App Store build
  (v1.0.2) predates the push pairing flow. `/ui/push` now shows an
  amber callout under the App Store CTA pointing at
  `kontakt@krzewilabs.pl` for a TestFlight v1.1.x build until that
  release reaches the App Store. Same blockquote added to the iOS Push
  section in `README.md`.

### Migrations

- `h3c4d5e67890` — phase 8: `initial_load_windows`. Idempotent against
  `Base.metadata.create_all`, head-revision check in
  `tests/test_db_migration.py` updated.

### Tests

- `tests/test_security_controls.py`: 2 new in `TestAuthTokenAutoGeneration`
  (`test_auto_gen_sets_marker`, `test_user_token_no_marker`).
- `tests/test_initial_load_manager.py`: 2 new in
  `TestInitialLoadWindowLog` (success+failed roundtrip, error_message
  truncation).
- `tests/test_invoice_monitor.py`: `test_exceeds_range` expectation
  updated (90 days → 89 days) to match the inclusive dateRange semantic.
- Suite: **743 passed, 2 skipped** (was 739).

---

## [0.5.2] — 2026-05-04 (UI auth security audit remediation)

Closes 14 findings from `audit/20260504_security_audit_v0_5_1_ui_auth.md`
(focused review of V5-12/V5-13/V5-14 UI auth surface added in 0.5.1 that
hadn't gone through the v0.5.0 audit cycle). 0 CRITICAL, 0 HIGH originally;
6 MEDIUM, 6 LOW, 5 INFO. All addressed.

### Pre-release fixes (post-audit)

- **Logging:** `alembic.ini` `[logger_root] level` was `WARNING` — the
  `fileConfig()` call in `alembic/env.py` clobbered the `INFO` level set
  by `app.logging_config` at startup, silently dropping every
  `logger.info` after migrations ran. Five of the seven U-12 audit-trail
  events (session create/revoke, password change, user create,
  absolute-cap eviction) were therefore invisible in production. Bumped
  alembic root to `INFO`; `[logger_alembic]` and `[logger_sqlalchemy]`
  unchanged.
- **Fresh-install UX:** when `api.auth_token` is auto-generated (F-01
  fallback), `main.py` no longer bootstraps an `admin` user with that
  random token as the password. The wizard at `/ui/setup` is the only
  sensible entry point for a fresh install — bootstrapping with an
  unknowable password just locked the operator out of the UI. Bootstrap
  still runs when the operator supplies `auth_token` themselves
  (config / env), preserving the v0.5.0 → v0.5.2 upgrade flow. Marker:
  `api["_auth_token_auto_generated"]`.

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
