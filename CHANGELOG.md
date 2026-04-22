# Changelog

All notable changes to KSeF Monitor are documented here.

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
