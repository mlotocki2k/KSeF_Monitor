# v0.5 Security Audit Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all P1 BLOCKER and P2 findings from the v0.5 security audit ([20260421_security_audit_docker_v0_5_test_branch.md](20260421_security_audit_docker_v0_5_test_branch.md)) before merging `test → main`.

**Architecture:** Fixes are layered:
1. **Auth model rework** (V5-01, V5-02, V5-03): tighten auth middleware whitelist; add Pydantic/regex validation at every `ksef_number` entry point; use `urllib.parse.quote` for HTTP header values.
2. **Supply chain** (V5-04): pin `urllib3`, `starlette`, `python-multipart`, `cryptography` in both `requirements.txt` and `pyproject.toml`; add `requirements.lock` via `pip-compile`.
3. **UI hardening** (V5-05, V5-10): add CSP/HSTS/Referrer-Policy headers; self-host Tailwind CSS (build-time bundle).
4. **Rate limiting** (V5-06): per-endpoint `slowapi` decorators on all mutating endpoints.
5. **Defense-in-depth** (V5-07, V5-08, V5-09): SSRF guard for `pdf_ksef_generator_url`; `link_callback` for `xhtml2pdf.pisa.CreatePDF`; single-source version.

**Tech Stack:** Python 3.11, FastAPI ≥0.115, SlowAPI, SQLAlchemy 2.0, Jinja2 ≥3.1.6, pytest, Docker, GitHub Actions.

**Working branch:** `test` (commit `f7aa694` at plan start). All commits target `test`. Merge `test → main` ONLY after all P1 tasks pass.

---

## File Structure (what this plan touches)

| Path | Role | Change |
|------|------|--------|
| `app/api/__init__.py` | Auth middleware + app factory | Rewrite whitelist; version param |
| `app/api/routers/invoices.py` | PDF/XML download endpoints | Add `ksef_number` regex + `quote()` for headers |
| `app/api/routers/monitor.py` | Trigger/state/health | Remove hardcoded version; add `@limiter.limit` |
| `app/api/routers/push.py` | Push setup/devices | Remove from auth bypass list; add `@limiter.limit` |
| `app/api/routers/initial_load.py` | Bulk import | Add `@limiter.limit`; add max range validator |
| `app/api/routers/ui.py` | Web UI | Remove pairing_code from `/ui/push` default response; add "show/hide" click gesture |
| `app/api/schemas.py` | Response models | Remove hardcoded `version="0.4.0"` default |
| `app/config_manager.py` | Config + defaults | Add `pdf_ksef_generator_url` SSRF guard; API UI settings |
| `app/invoice_pdf_template.py` | xhtml2pdf renderer | Add `link_callback` blocking external URIs |
| `app/invoice_pdf_generator.py` | CIRFMF generator | Use shared SSRF validator |
| `app/push_manager.py` | Pairing credentials | Expand `pairing_code` to 64-bit (8 bytes hex) |
| `app/_ssrf_guard.py` | **NEW** | Shared SSRF validation (move from `webhook_notifier`) |
| `app/__init__.py` | Package version | Fix `__version__` to `"0.5.0"` (currently `"2.0.0"`) |
| `app/ui/templates/base.html` | HTML shell | Remove Tailwind CDN; include local CSS |
| `app/ui/static/tailwind.min.css` | **NEW** | Pre-built Tailwind output |
| `app/ui/templates/push.html` | Push pairing page | Hide code behind click; add CSRF-like token |
| `pyproject.toml` | Package metadata | Sync with `requirements.txt`; bump `cryptography` |
| `requirements.txt` | Pip pins | Add `urllib3`, `starlette`, `python-multipart`; bump existing |
| `requirements.lock` | **NEW** | `pip-compile` output for reproducibility |
| `Dockerfile` | Container build | Use `--require-hashes` with `requirements.lock` |
| `.github/workflows/docker-publish.yml` | CI | Add `trivy image` scan + `pip-audit` step |
| `tests/test_api_auth.py` | Auth tests | Add tests for tightened whitelist |
| `tests/test_api_invoices.py` | Invoice tests | Add tests for `ksef_number` validation + header quote |
| `tests/test_api_push.py` | **NEW** | Push pairing exposure tests |
| `tests/test_api_ui.py` | **NEW** | UI auth tests |
| `tests/test_api_rate_limit.py` | **NEW** | Per-endpoint rate limit tests |
| `tests/test_ssrf_guard.py` | **NEW** | SSRF validator tests |
| `tests/test_pdf_security.py` | PDF security tests | Add `link_callback` test |
| `tests/test_push_manager.py` | Existing | Update for 64-bit pairing_code |

---

## P1 Tasks — BLOCKER before `test → main` merge

### Task 1: Fix hardcoded version string + unify version source (V5-09, V5-12)

Pre-requisite for other tasks (tests assert version). Small + low-risk.

**Files:**
- Modify: `app/__init__.py:6`
- Modify: `app/api/__init__.py:48`
- Modify: `app/api/routers/monitor.py:35`
- Modify: `app/api/schemas.py:104`
- Modify: `main.py:57`
- Test: `tests/test_api_monitor.py`

- [ ] **Step 1.1: Write the failing test**

Add to `tests/test_api_monitor.py` (create if missing):
```python
from app import __version__

def test_health_returns_package_version(client_open):
    resp = client_open.get("/api/v1/monitor/health")
    assert resp.status_code == 200
    assert resp.json()["version"] == __version__
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `cd ksef_monitor_v0_1 && pytest tests/test_api_monitor.py::test_health_returns_package_version -v`
Expected: FAIL — current response says `"0.4.0"`, package says `"2.0.0"`.

- [ ] **Step 1.3: Fix single-source version in `app/__init__.py`**

Replace `app/__init__.py:6`:
```python
__version__ = "0.5.0"
```

- [ ] **Step 1.4: Use `__version__` in FastAPI app**

In `app/api/__init__.py`, replace line 48:
```python
from app import __version__

app = FastAPI(
    title="KSeF Monitor API",
    version=__version__,
    ...
```

- [ ] **Step 1.5: Use `__version__` in health response**

In `app/api/routers/monitor.py`, replace line 35:
```python
from app import __version__

return HealthResponse(
    status="ok",
    version=__version__,
    db_connected=db_connected,
)
```

- [ ] **Step 1.6: Remove default in schema**

In `app/api/schemas.py`, replace line 104:
```python
class HealthResponse(BaseModel):
    status: str = "ok"
    version: str                    # required; set from app.__version__
    db_connected: bool = False
```

- [ ] **Step 1.7: Update main.py banner**

In `main.py:57`:
```python
from app import __version__
logger.info(f"KSeF Monitor v{__version__}")
```

- [ ] **Step 1.8: Add CI check against pyproject**

Add `tests/test_version_consistency.py`:
```python
import tomllib
from pathlib import Path
from app import __version__

def test_version_matches_pyproject():
    pyproject = tomllib.loads(
        (Path(__file__).parent.parent / "pyproject.toml").read_text()
    )
    assert pyproject["project"]["version"] == __version__
```

- [ ] **Step 1.9: Run all tests to verify they pass**

Run: `pytest tests/test_api_monitor.py tests/test_version_consistency.py -v`
Expected: PASS (both tests green).

- [ ] **Step 1.10: Commit**

```bash
git add app/__init__.py app/api/__init__.py app/api/routers/monitor.py app/api/schemas.py main.py tests/test_api_monitor.py tests/test_version_consistency.py
git commit -m "fix(V5-09,V5-12): unify version string to 0.5.0 (single-source via app.__version__)"
```

---

### Task 2: Pin security-critical deps + add lockfile (V5-04)

Keep shippable while we fix code. Run this early — no code depends on the new pins.

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Create: `requirements.lock`
- Modify: `Dockerfile`
- Modify: `.github/workflows/docker-publish.yml`

- [ ] **Step 2.1: Align `pyproject.toml` with runtime deps**

Replace `pyproject.toml` dependencies section (lines 20-33) with:
```toml
dependencies = [
    "requests>=2.32.5,<3.0.0",
    "urllib3>=2.6.0,<3.0.0",            # CVE-2025-66418, CVE-2025-66471
    "python-dateutil==2.9.0.post0",
    "cryptography==46.0.7",             # CVE-2026-39892 — was 46.0.5
    "prometheus-client==0.24.1",
    "pytz==2026.1.post1",
    "Jinja2>=3.1.6,<4.0.0",
    "defusedxml>=0.7.1,<1.0.0",
    "reportlab==4.4.10",
    "qrcode==8.2",
    "xhtml2pdf>=0.2.16,<1.0.0",
    "SQLAlchemy>=2.0.0,<3.0.0",
    "alembic>=1.13.0,<2.0.0",
    "fastapi>=0.115.0,<1.0.0",
    "starlette>=0.49.1",                # CVE-2025-62727
    "uvicorn[standard]>=0.34.0,<1.0.0",
    "slowapi>=0.1.9,<1.0.0",
    "python-multipart>=0.0.22,<1.0.0",  # CVE-2024-53981, CVE-2026-40347, CVE-2026-24486
]
```

- [ ] **Step 2.2: Mirror in `requirements.txt`**

Replace `requirements.txt` contents:
```
requests>=2.32.5,<3.0.0
urllib3>=2.6.0,<3.0.0
python-dateutil==2.9.0.post0
cryptography==46.0.7
prometheus-client==0.24.1
pytz==2026.1.post1

# Notification templates
Jinja2>=3.1.6,<4.0.0

# Security
defusedxml>=0.7.1,<1.0.0

# PDF generation
reportlab==4.4.10
qrcode==8.2
xhtml2pdf>=0.2.16,<1.0.0

# Database
SQLAlchemy>=2.0.0,<3.0.0
alembic>=1.13.0,<2.0.0

# REST API
fastapi>=0.115.0,<1.0.0
starlette>=0.49.1
uvicorn[standard]>=0.34.0,<1.0.0
slowapi>=0.1.9,<1.0.0
python-multipart>=0.0.22,<1.0.0
```

- [ ] **Step 2.3: Generate lockfile**

Install `pip-tools` locally if absent, then:
```bash
cd ksef_monitor_v0_1
python -m pip install --upgrade pip pip-tools
pip-compile --generate-hashes --output-file=requirements.lock requirements.txt
```

Commit the generated `requirements.lock` verbatim.

- [ ] **Step 2.4: Dockerfile uses lockfile**

Replace lines 23-25 in `Dockerfile`:
```dockerfile
# Install Python dependencies from hashed lockfile
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
```

- [ ] **Step 2.5: Update `.dockerignore`**

Verify `requirements.lock` is NOT in `.dockerignore` (should be copied into build context). Add `requirements.lock` to the include list if needed.

- [ ] **Step 2.6: Add CI scan step**

In `.github/workflows/docker-publish.yml` after the `Secret scanning` step (line 29), add:
```yaml
      - name: Dependency vulnerability scan
        run: |
          pip install -q pip-audit
          pip-audit --requirement requirements.lock --strict --format columns

      - name: Trivy image scan
        uses: aquasecurity/trivy-action@6c175e9c4083a92bbca2f9724c8a5e33bc2d97a5  # v0.33.1 — pin to SHA
        with:
          image-ref: ghcr.io/${{ github.repository }}:${{ github.sha }}
          severity: CRITICAL,HIGH
          exit-code: 1
          ignore-unfixed: true
```

(Move `image-ref` scan to after Build & push OR do local scan before publish — whichever fits the existing workflow order.)

- [ ] **Step 2.7: Local smoke build**

Run: `docker build -t ksef_monitor:plan-task2 .`
Expected: build succeeds; verify inside: `docker run --rm ksef_monitor:plan-task2 pip freeze | grep -E "^(urllib3|starlette|cryptography|python-multipart)="`
Expected pins present at ≥ target versions.

- [ ] **Step 2.8: Commit**

```bash
git add pyproject.toml requirements.txt requirements.lock Dockerfile .github/workflows/docker-publish.yml
git commit -m "fix(V5-04): pin urllib3/starlette/python-multipart; add requirements.lock + trivy/pip-audit CI"
```

---

### Task 3: Shared SSRF validator module (V5-07, prep for V5-01)

Extract the well-tested SSRF guard from `webhook_notifier.py` into a reusable module so every outbound URL we trust goes through the same check.

**Files:**
- Create: `app/_ssrf_guard.py`
- Create: `tests/test_ssrf_guard.py`
- Modify: `app/notifiers/webhook_notifier.py:61-91` (delegate to new module)

- [ ] **Step 3.1: Write the failing test**

Create `tests/test_ssrf_guard.py`:
```python
import pytest
from unittest.mock import patch
from app._ssrf_guard import is_safe_public_url


class TestIsSafePublicUrl:
    def test_public_https_url_allowed(self):
        assert is_safe_public_url("https://example.com/webhook") is True

    def test_http_allowed(self):
        assert is_safe_public_url("http://example.com/webhook") is True

    def test_other_scheme_rejected(self):
        assert is_safe_public_url("file:///etc/passwd") is False
        assert is_safe_public_url("ftp://example.com") is False
        assert is_safe_public_url("gopher://example.com") is False

    def test_missing_hostname_rejected(self):
        assert is_safe_public_url("https:///path") is False

    def test_empty_url_rejected(self):
        assert is_safe_public_url("") is False
        assert is_safe_public_url(None) is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_private_ip_rejected(self, mock_gai):
        mock_gai.return_value = [(2, 1, 6, "", ("10.0.0.1", 0))]
        assert is_safe_public_url("https://internal.local/") is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_loopback_rejected(self, mock_gai):
        mock_gai.return_value = [(2, 1, 6, "", ("127.0.0.1", 0))]
        assert is_safe_public_url("https://localhost/") is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_link_local_rejected(self, mock_gai):
        mock_gai.return_value = [(2, 1, 6, "", ("169.254.169.254", 0))]
        assert is_safe_public_url("https://metadata.internal/") is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_dns_failure_rejected(self, mock_gai):
        import socket
        mock_gai.side_effect = socket.gaierror()
        assert is_safe_public_url("https://does-not-exist.invalid/") is False
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `pytest tests/test_ssrf_guard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app._ssrf_guard'`.

- [ ] **Step 3.3: Create the module**

Create `app/_ssrf_guard.py`:
```python
"""SSRF guard — validates outbound URLs for public network only.

Shared by webhook_notifier, ios_push_notifier, CIRFMF PDF generator, any
module that hands an admin-configured URL to ``requests``.
"""

import ipaddress
import logging
import socket
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}


def is_safe_public_url(url: Optional[str]) -> bool:
    """Return True only if URL resolves to a public, routable IP via http(s).

    Rejects: private, loopback, link-local, multicast, reserved ranges
    and URLs with missing/unparseable components.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in _ALLOWED_SCHEMES:
        logger.warning("URL rejected: unsupported scheme %r", parsed.scheme)
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        logger.warning("URL rejected: cannot resolve hostname")
        return False

    for family, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            logger.warning("URL rejected: resolves to non-public IP")
            return False
    return True
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `pytest tests/test_ssrf_guard.py -v`
Expected: PASS (9 tests).

- [ ] **Step 3.5: Delegate `webhook_notifier.py` to new module**

Replace `app/notifiers/webhook_notifier.py:61-91`:
```python
    @staticmethod
    def _validate_webhook_url(url: str) -> bool:
        """Delegate SSRF validation to the shared guard."""
        from app._ssrf_guard import is_safe_public_url
        return is_safe_public_url(url)
```

Remove now-unused imports in `webhook_notifier.py`:
```python
# DELETE: import ipaddress, import socket
# DELETE: from urllib.parse import urlparse  (still used elsewhere? keep if so)
```

Verify with: `python -c "from app.notifiers.webhook_notifier import WebhookNotifier; print('OK')"`

- [ ] **Step 3.6: Re-run existing webhook tests**

Run: `pytest tests/ -k webhook -v`
Expected: all green (the delegate should behave identically).

- [ ] **Step 3.7: Add SSRF check to CIRFMF generator**

In `app/invoice_pdf_generator.py:1189-1192`, replace:
```python
    # Validate: public http/https only
    from app._ssrf_guard import is_safe_public_url
    if not is_safe_public_url(base_url):
        logger.warning("CIRFMF generator URL rejected (non-public or bad scheme): %s", base_url)
        return None
```

- [ ] **Step 3.8: Add test for CIRFMF SSRF**

Append to `tests/test_pdf_security.py` (create if absent):
```python
from unittest.mock import patch
from app.invoice_pdf_generator import _try_ksef_generator  # (use actual import name)

def test_cirfmf_rejects_private_url(monkeypatch):
    from app import _ssrf_guard
    monkeypatch.setattr(_ssrf_guard, "is_safe_public_url", lambda u: False)
    result = _try_ksef_generator("<Faktura/>", "KSEF1", "http://169.254.169.254/")
    assert result is None
```

Run: `pytest tests/test_pdf_security.py -v`
Expected: PASS.

- [ ] **Step 3.9: Commit**

```bash
git add app/_ssrf_guard.py app/notifiers/webhook_notifier.py app/invoice_pdf_generator.py tests/test_ssrf_guard.py tests/test_pdf_security.py
git commit -m "refactor(V5-07): extract shared SSRF guard; apply to CIRFMF PDF generator URL"
```

---

### Task 4: Enforce auth on `/ui/**` and `/api/v1/invoices/{}/pdf|xml` (V5-01, V5-03)

Tighten the auth-middleware whitelist. Valid deployments that previously relied on the bypass will get 401; the `api.ui_public` escape hatch lets them opt back in deliberately.

**Files:**
- Modify: `app/api/__init__.py:65-106`
- Modify: `app/config_manager.py:499` (add `ui_public=false` default)
- Modify: `app/api/routers/invoices.py:127,180` (validate `ksef_number`; `quote` filename)
- Test: `tests/test_api_auth.py` (add cases); `tests/test_api_invoices.py`

- [ ] **Step 4.1: Write the failing auth tests**

Add to `tests/test_api_auth.py`:
```python
class TestUiAuth:
    def test_ui_requires_auth_by_default(self, client_auth):
        """UI routes should not bypass auth unless api.ui_public=true."""
        resp = client_auth.get("/ui")
        assert resp.status_code == 401

    def test_ui_accessible_with_token(self, client_auth):
        resp = client_auth.get(
            "/ui", headers={"Authorization": f"Bearer {'a' * 32}"}
        )
        # 200 (template renders) or 503 (db None) — NOT 401
        assert resp.status_code != 401

    def test_invoice_pdf_requires_auth(self, client_auth):
        resp = client_auth.get("/api/v1/invoices/1234567890-20260101-ABCDEF-01/pdf")
        assert resp.status_code == 401

    def test_invoice_xml_requires_auth(self, client_auth):
        resp = client_auth.get("/api/v1/invoices/1234567890-20260101-ABCDEF-01/xml")
        assert resp.status_code == 401

    def test_push_devices_requires_auth(self, client_auth):
        resp = client_auth.get("/api/v1/push/devices")
        assert resp.status_code == 401

    def test_ui_public_opt_in(self):
        """When api.ui_public=true, UI routes skip auth (legacy support)."""
        from app.api import create_app
        from fastapi.testclient import TestClient
        app = create_app(auth_token="a" * 32, ui_public=True)
        client = TestClient(app)
        resp = client.get("/ui")
        assert resp.status_code != 401
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `pytest tests/test_api_auth.py::TestUiAuth -v`
Expected: FAIL — bypass still active.

- [ ] **Step 4.3: Rewrite whitelist in `app/api/__init__.py`**

Replace `app/api/__init__.py:23-35` signature:
```python
def create_app(
    db=None,
    monitor_instance=None,
    auth_token: Optional[str] = None,
    cors_origins: Optional[list] = None,
    rate_limit_config: Optional[Dict[str, Any]] = None,
    docs_enabled: bool = True,
    prometheus_metrics=None,
    push_manager=None,
    initial_load_manager=None,
    ui_enabled: bool = True,
    ui_public: bool = False,        # NEW — opt-in bypass for legacy deployments
) -> FastAPI:
```

Replace `app/api/__init__.py:72-106` auth middleware body:
```python
    if auth_token:
        if len(auth_token) < 32:
            logger.warning(
                "API auth_token is shorter than 32 characters - use a stronger token"
            )

        # Narrow whitelist: health + docs only. UI and invoice downloads
        # require auth unless ui_public=True (deprecated escape hatch).
        _EXEMPT_EXACT = {
            "/docs", "/redoc", "/openapi.json",
            "/api/v1/monitor/health",
        }

        @app.middleware("http")
        async def verify_auth(request: Request, call_next):
            path = request.url.path
            if path in _EXEMPT_EXACT:
                return await call_next(request)
            if ui_public and path.startswith("/ui"):
                return await call_next(request)

            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Missing or invalid Authorization header"},
                )
            provided = auth_header[7:]
            if not hmac.compare_digest(provided, auth_token):
                logger.warning(
                    "Failed auth attempt from %s",
                    request.client.host if request.client else "unknown",
                )
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid authentication token"},
                )
            return await call_next(request)
    else:
        logger.warning("API running without authentication - set api.auth_token for production")
```

- [ ] **Step 4.4: Add `api.ui_public` config default**

In `app/config_manager.py` after line 499 (`api.setdefault("ui_enabled", True)`) add:
```python
        api.setdefault("ui_public", False)
        if api["ui_public"] and api["auth_token"]:
            logger.warning(
                "api.ui_public=true bypasses auth for /ui/* — only safe when "
                "port is bound to 127.0.0.1 or a trusted reverse proxy enforces "
                "authentication. Set to false for production."
            )
```

- [ ] **Step 4.5: Wire `ui_public` in `main.py`**

In `main.py` where `create_app(...)` is called (around line 223), pass:
```python
                api_app = create_app(
                    db=database,
                    monitor_instance=monitor,
                    auth_token=api_config.get("auth_token", ""),
                    cors_origins=api_config.get("cors_origins"),
                    rate_limit_config=api_config.get("rate_limit"),
                    docs_enabled=api_config.get("docs_enabled", True),
                    prometheus_metrics=prometheus_metrics,
                    push_manager=push_manager,
                    initial_load_manager=initial_load_manager,
                    ui_enabled=api_config.get("ui_enabled", True),
                    ui_public=api_config.get("ui_public", False),
                )
```

- [ ] **Step 4.6: Run auth tests to verify they pass**

Run: `pytest tests/test_api_auth.py -v`
Expected: all green. Existing tests should still pass (`TestOpenAccess`, `TestTokenAuth`).

- [ ] **Step 4.7: Add `ksef_number` validation + `quote()` in invoices router**

In `app/api/routers/invoices.py`, import at top:
```python
from urllib.parse import quote
```

After existing patterns (around line 23) ensure:
```python
_KSEF_PATTERN = re.compile(r"^\d{10}-\d{8}-[A-Z0-9]{6,}-[A-Z0-9]{2}$")
```

Replace `get_invoice` (line 106), `get_invoice_xml` (line 127), `get_invoice_pdf` (line 180) to start with:
```python
    if not _KSEF_PATTERN.match(ksef_number):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid KSeF number format"},
        )
```

Replace every `Content-Disposition` f-string with:
```python
safe_filename = quote(f"{ksef_number}.xml")   # or ".pdf"
return Response(
    content=...,
    media_type="application/xml",
    headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
)
```

- [ ] **Step 4.8: Write tests for validation + header**

Add to `tests/test_api_invoices.py`:
```python
def test_get_invoice_xml_rejects_bad_format(client_auth_with_db):
    resp = client_auth_with_db.get(
        "/api/v1/invoices/../etc/passwd/xml",
        headers={"Authorization": "Bearer " + "a" * 32},
    )
    assert resp.status_code == 400

def test_get_invoice_pdf_rejects_crlf(client_auth_with_db):
    resp = client_auth_with_db.get(
        "/api/v1/invoices/FAKE%0d%0aX-Bad%3Ahi/pdf",
        headers={"Authorization": "Bearer " + "a" * 32},
    )
    assert resp.status_code == 400
```

- [ ] **Step 4.9: Run the full invoices + auth test suite**

Run: `pytest tests/test_api_auth.py tests/test_api_invoices.py -v`
Expected: all green.

- [ ] **Step 4.10: Commit**

```bash
git add app/api/__init__.py app/api/routers/invoices.py app/config_manager.py main.py tests/test_api_auth.py tests/test_api_invoices.py
git commit -m "fix(V5-01,V5-03): narrow auth whitelist, validate ksef_number, quote Content-Disposition"
```

---

### Task 5: Hide pairing code from unauthenticated UI + widen code space (V5-02)

Default: UI shows nothing sensitive until user explicitly requests reveal (authenticated). Keep the API endpoint but require auth (Task 4 already removed `/api/v1/push/devices` from the whitelist).

**Files:**
- Modify: `app/push_manager.py:242,393` (8 bytes hex = 64-bit code)
- Modify: `app/push_manager.py:548-561` (`pairing_info` masking helper)
- Modify: `app/api/routers/push.py:15` (new `/push/pairing` reveal endpoint)
- Modify: `app/api/routers/ui.py:344-357` (don't embed code in template by default)
- Modify: `app/ui/templates/push.html` (click-to-reveal)
- Test: `tests/test_push_manager.py`, `tests/test_api_push.py` (new)

- [ ] **Step 5.1: Write the failing test — pairing code length**

Add to `tests/test_push_manager.py`:
```python
def test_generated_pairing_code_is_16_hex_chars(tmp_path, monkeypatch):
    from app.push_manager import PushManager
    monkeypatch.setenv("PUSH_CENTRAL_URL", "https://unused.test")
    mgr = PushManager({"worker_url": "https://unused.test"}, data_dir=str(tmp_path), db=None)
    assert len(mgr.pairing_code) == 16
    assert all(c in "0123456789ABCDEF" for c in mgr.pairing_code)
```

- [ ] **Step 5.2: Run test to verify it fails**

Run: `pytest tests/test_push_manager.py::test_generated_pairing_code_is_16_hex_chars -v`
Expected: FAIL — current length is 8.

- [ ] **Step 5.3: Widen pairing code to 64 bits**

In `app/push_manager.py:244`:
```python
        self.pairing_code = secrets.token_hex(8).upper()  # 64-bit
```

In `app/push_manager.py:393`:
```python
        new_code = secrets.token_hex(8).upper()
```

- [ ] **Step 5.4: Re-run pairing code test**

Run: `pytest tests/test_push_manager.py::test_generated_pairing_code_is_16_hex_chars -v`
Expected: PASS.

- [ ] **Step 5.5: Add masked-info property**

Replace `app/push_manager.py:548-561` with:
```python
    @property
    def pairing_info(self) -> Dict[str, Any]:
        """Masked pairing info safe to embed in unauthenticated UI."""
        return {
            "instance_id": self.instance_id,
            "pairing_code_masked": (
                (self.pairing_code[:2] + "…" + self.pairing_code[-2:])
                if self.pairing_code else None
            ),
            "registered_at": self.registered_at,
            "is_registered": self.is_registered,
            # QR intentionally omitted — would leak the code.
        }

    @property
    def pairing_info_full(self) -> Dict[str, Any]:
        """FULL pairing info — include pairing_code plaintext + QR. Auth-gated."""
        return {
            "instance_id": self.instance_id,
            "pairing_code": self.pairing_code,
            "registered_at": self.registered_at,
            "is_registered": self.is_registered,
            "qr_data_uri": self.generate_qr_data_uri(),
        }
```

- [ ] **Step 5.6: Add auth-gated reveal endpoint**

In `app/api/routers/push.py`, replace the existing `get_push_setup` (line 15-25):
```python
@router.get("/push/setup")
def get_push_setup(request: Request):
    """Masked pairing info — safe for UI landing page."""
    push_manager = getattr(request.app.state, "push_manager", None)
    if not push_manager:
        return JSONResponse(
            status_code=503,
            content={"detail": "Push notifications not configured"},
        )
    return push_manager.pairing_info


@router.get("/push/pairing")
def reveal_pairing(request: Request):
    """Full pairing info (code + QR). REQUIRES auth — not on any whitelist."""
    push_manager = getattr(request.app.state, "push_manager", None)
    if not push_manager:
        return JSONResponse(
            status_code=503,
            content={"detail": "Push notifications not configured"},
        )
    return push_manager.pairing_info_full
```

- [ ] **Step 5.7: Update UI template to show masked code + reveal button**

In `app/ui/templates/push.html`, replace the pairing_info render block. Example structure (adjust to match existing template's styling):
```html
{% if push %}
  <p>Instance: <code>{{ push.instance_id }}</code></p>
  <p>Pairing code: <code id="pairing-mask">{{ push.pairing_code_masked }}</code></p>
  <button id="reveal-btn" class="btn-secondary"
          onclick="reveal()">Show pairing code</button>
  <div id="pairing-full" style="display:none">
    <img id="pairing-qr" alt="QR" />
    <code id="pairing-code"></code>
  </div>
  <script>
    async function reveal() {
      const token = prompt("Enter API token to reveal:");
      if (!token) return;
      const resp = await fetch('/api/v1/push/pairing',
        { headers: { 'Authorization': 'Bearer ' + token }});
      if (!resp.ok) { alert('Auth failed'); return; }
      const data = await resp.json();
      document.getElementById('pairing-qr').src = data.qr_data_uri;
      document.getElementById('pairing-code').textContent = data.pairing_code;
      document.getElementById('pairing-full').style.display = 'block';
      document.getElementById('reveal-btn').style.display = 'none';
    }
  </script>
{% else %}
  <p>Push notifications not configured.</p>
{% endif %}
```

(The JS fetches the auth-gated endpoint with the user-supplied Bearer token — no XHR from unauthenticated contexts. Once we add session auth, this becomes a cookie-backed fetch with CSRF.)

- [ ] **Step 5.8: Remove pairing_info_full from `/ui/push` server-side context**

In `app/api/routers/ui.py:356`:
```python
    ctx["push"] = push_manager.pairing_info   # masked — no plaintext code
```

(Already correct if the property rename is picked up; verify after patching push_manager.)

- [ ] **Step 5.9: Write tests for leak prevention**

Create `tests/test_api_push.py`:
```python
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from app.api import create_app


@pytest.fixture
def mock_push_manager():
    pm = MagicMock()
    pm.pairing_info = {
        "instance_id": "abc",
        "pairing_code_masked": "AB…EF",
        "registered_at": "2026-04-21T00:00:00Z",
        "is_registered": True,
    }
    pm.pairing_info_full = {
        "instance_id": "abc",
        "pairing_code": "ABCD1234ABCD1234",
        "registered_at": "2026-04-21T00:00:00Z",
        "is_registered": True,
        "qr_data_uri": "data:image/png;base64,XXX",
    }
    return pm


@pytest.fixture
def client_with_push(mock_push_manager):
    app = create_app(auth_token="a" * 32, push_manager=mock_push_manager)
    return TestClient(app)


def test_setup_masked_only(client_with_push, mock_push_manager):
    """/push/setup needs auth and returns masked code only."""
    resp = client_with_push.get(
        "/api/v1/push/setup",
        headers={"Authorization": "Bearer " + "a" * 32},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "pairing_code_masked" in body
    assert "pairing_code" not in body
    assert "qr_data_uri" not in body


def test_pairing_requires_auth(client_with_push):
    resp = client_with_push.get("/api/v1/push/pairing")
    assert resp.status_code == 401


def test_pairing_returns_full_with_auth(client_with_push):
    resp = client_with_push.get(
        "/api/v1/push/pairing",
        headers={"Authorization": "Bearer " + "a" * 32},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pairing_code"] == "ABCD1234ABCD1234"
    assert body["qr_data_uri"].startswith("data:image/png;base64,")
```

- [ ] **Step 5.10: Run all push-related tests**

Run: `pytest tests/test_api_push.py tests/test_push_manager.py -v`
Expected: all green.

- [ ] **Step 5.11: Commit**

```bash
git add app/push_manager.py app/api/routers/push.py app/api/routers/ui.py app/ui/templates/push.html tests/test_push_manager.py tests/test_api_push.py
git commit -m "fix(V5-02): mask pairing_code in UI; add auth-gated /push/pairing; widen code to 64-bit"
```

---

## P2 Tasks — next sprint

### Task 6: Per-endpoint rate limits on mutating routes (V5-06)

**Files:**
- Modify: `app/api/__init__.py` (export `limiter` in app.state; already there — confirm)
- Modify: `app/api/routers/monitor.py` (+ import + decorator)
- Modify: `app/api/routers/initial_load.py` (same)
- Modify: `app/api/routers/push.py` (same)
- Modify: `app/config_manager.py` (expand `rate_limit` defaults)
- Test: `tests/test_api_rate_limit.py` (new)

- [ ] **Step 6.1: Expand rate_limit config defaults**

In `app/config_manager.py` replace lines 472-475:
```python
        rate_limit = api.setdefault("rate_limit", {})
        rate_limit.setdefault("enabled", True)
        rate_limit.setdefault("default", "60/minute")
        rate_limit.setdefault("trigger", "2/minute")
        rate_limit.setdefault("initial_load_start", "1/hour")
        rate_limit.setdefault("push_regenerate", "5/hour")
        rate_limit.setdefault("push_reset", "1/hour")
        rate_limit.setdefault("invoice_download", "30/minute")
```

- [ ] **Step 6.2: Write failing rate-limit test**

Create `tests/test_api_rate_limit.py`:
```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from app.api import create_app


@pytest.fixture
def client_rl():
    monitor = MagicMock()
    monitor.scheduler.force_next_run = MagicMock(return_value=None)
    app = create_app(
        auth_token="a" * 32,
        monitor_instance=monitor,
        rate_limit_config={
            "enabled": True,
            "default": "60/minute",
            "trigger": "2/minute",
        },
    )
    return TestClient(app)


def test_trigger_enforces_per_endpoint_limit(client_rl):
    """Third call within 1 min should 429."""
    headers = {"Authorization": "Bearer " + "a" * 32}
    r1 = client_rl.post("/api/v1/monitor/trigger", headers=headers)
    r2 = client_rl.post("/api/v1/monitor/trigger", headers=headers)
    r3 = client_rl.post("/api/v1/monitor/trigger", headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
```

Run: `pytest tests/test_api_rate_limit.py -v`
Expected: FAIL — third call returns 200.

- [ ] **Step 6.3: Pass the limiter config through app.state**

Verify that `app.state.rate_limit_config` is set in `create_app`. Add in `app/api/__init__.py` after `app.state.limiter = limiter`:
```python
    app.state.rate_limit_config = rl_config
```

- [ ] **Step 6.4: Apply per-endpoint limits in `monitor.py`**

In `app/api/routers/monitor.py` top:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address
```

Replace the `/monitor/trigger` decorator block (line 81):
```python
@router.post("/monitor/trigger", response_model=TriggerResponse)
def trigger_check(request: Request):
    limiter: Limiter = request.app.state.limiter
    rl = request.app.state.rate_limit_config or {}
    trigger_limit = rl.get("trigger", "2/minute")
    # Dynamic per-request limit — call hit() directly
    if limiter.enabled:
        try:
            limiter._check_request_limit(
                request, endpoint_name="/monitor/trigger",
                lookup_limits=[trigger_limit],
            )
        except Exception:
            from slowapi.errors import RateLimitExceeded
            raise RateLimitExceeded(trigger_limit)
    ...  # existing body
```

**Note for the engineer:** `slowapi` exposes a cleaner API via `@limiter.limit("2/minute")` decorator but it requires the limiter to be accessible at import time. The pattern above works with the request.app.state limiter. Alternative: instantiate the limiter at module scope in `api/__init__.py` and import it in routers.

Preferred simpler pattern — refactor `create_app` to provide a module-level `limiter`:

```python
# app/api/__init__.py — at module scope
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, enabled=False)  # enabled flipped in create_app

def create_app(..., rate_limit_config=None, ...):
    ...
    rl_config = rate_limit_config or {}
    limiter.enabled = rl_config.get("enabled", False)
    default = rl_config.get("default", "60/minute")
    limiter._default_limits = [default]        # slowapi internal — or use Limiter kwargs
    app.state.limiter = limiter
    ...
```

Then in `monitor.py`:
```python
from app.api import limiter

@router.post("/monitor/trigger", response_model=TriggerResponse)
@limiter.limit(lambda request: request.app.state.rate_limit_config.get("trigger", "2/minute"))
def trigger_check(request: Request):
    ...
```

Adopt whichever pattern the engineer validates works with `slowapi==0.1.9`. Prefer the decorator form. Document the choice in the commit message.

- [ ] **Step 6.5: Apply limits in `initial_load.py` and `push.py`**

Apply the decorator pattern:
```python
# initial_load.py
@router.post("/initial-load/start")
@limiter.limit(lambda r: r.app.state.rate_limit_config.get("initial_load_start", "1/hour"))
def start_initial_load(...):
    ...

# push.py
@router.post("/push/regenerate")
@limiter.limit(lambda r: r.app.state.rate_limit_config.get("push_regenerate", "5/hour"))
def regenerate_pairing(...): ...

@router.post("/push/reset")
@limiter.limit(lambda r: r.app.state.rate_limit_config.get("push_reset", "1/hour"))
def reset_push(...): ...

# invoices.py
@router.get("/invoices/{ksef_number}/pdf")
@limiter.limit(lambda r: r.app.state.rate_limit_config.get("invoice_download", "30/minute"))
def get_invoice_pdf(...): ...
```

- [ ] **Step 6.6: Run rate-limit test suite**

Run: `pytest tests/test_api_rate_limit.py -v`
Expected: PASS.

Then full suite: `pytest tests/ -v`
Expected: green (no regressions).

- [ ] **Step 6.7: Commit**

```bash
git add app/api/__init__.py app/api/routers/monitor.py app/api/routers/initial_load.py app/api/routers/push.py app/api/routers/invoices.py app/config_manager.py tests/test_api_rate_limit.py
git commit -m "fix(V5-06): per-endpoint slowapi limits for mutating routes + invoice downloads"
```

---

### Task 7: CSP + security headers + self-host Tailwind (V5-05, V5-10)

**Files:**
- Modify: `app/api/__init__.py:110-117` (expand security headers)
- Create: `app/ui/static/tailwind.min.css`
- Modify: `app/ui/templates/base.html:7-18` (remove CDN)
- Modify: `app/api/routers/ui.py` (mount StaticFiles)
- Modify: `Dockerfile` (copy ui/static)
- Test: `tests/test_api_auth.py` (new headers assertion)

- [ ] **Step 7.1: Decide on Tailwind bundling strategy**

Two options:
- **A (preferred):** build Tailwind at image build time via `npx tailwindcss` in a multi-stage Dockerfile stage. Pros: minimal CSS. Cons: needs Node in builder stage.
- **B (simple):** download a pinned Tailwind Play CDN snapshot into `app/ui/static/tailwind.min.css` and check it in. Pros: no Node. Cons: larger file checked in, manual updates.

This plan uses Option B for fastest landing. Switch to A in a later task if CSS size becomes a concern.

- [ ] **Step 7.2: Vendor Tailwind v3 minified CSS**

Download once locally:
```bash
cd ksef_monitor_v0_1
curl -sL -o app/ui/static/tailwind.min.css \
  https://cdn.tailwindcss.com/3.4.10?plugins=forms,typography
# Validate file is CSS not HTML
head -c 30 app/ui/static/tailwind.min.css   # should start with @charset or /*
```

Document the pinned URL in a comment at the top of the CSS or in `docs/PROJECT_STRUCTURE.md`.

- [ ] **Step 7.3: Update `base.html` to use local CSS**

Replace lines 7-18 in `app/ui/templates/base.html`:
```html
  <link rel="stylesheet" href="/ui/static/tailwind.min.css">
```

Remove the `<script>` that configures `tailwind.config` (no longer runtime-configurable with pre-built CSS; use custom CSS file for brand colors if needed).

- [ ] **Step 7.4: Mount StaticFiles in FastAPI**

At top of `app/api/routers/ui.py` add:
```python
from fastapi.staticfiles import StaticFiles
```

After the existing `router` definition, add a mount helper or register separately. Since APIRouter doesn't natively mount StaticFiles, do this in `create_app`:

In `app/api/__init__.py` after `if ui_enabled: app.include_router(ui.router)`:
```python
        from pathlib import Path
        from fastapi.staticfiles import StaticFiles
        static_dir = Path(__file__).parent.parent / "ui" / "static"
        app.mount("/ui/static", StaticFiles(directory=str(static_dir)), name="ui-static")
```

- [ ] **Step 7.5: Ensure Dockerfile includes `app/ui/static`**

Verify `Dockerfile:33` (`COPY app/ ./app/`) — should be fine; no change needed.

- [ ] **Step 7.6: Write failing headers test**

Add to `tests/test_api_auth.py`:
```python
class TestSecurityHeaders:
    def test_csp_header_present(self, client_open):
        resp = client_open.get("/api/v1/monitor/health")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_hsts_header_present(self, client_open):
        resp = client_open.get("/api/v1/monitor/health")
        hsts = resp.headers.get("Strict-Transport-Security", "")
        assert "max-age=" in hsts

    def test_referrer_policy_header(self, client_open):
        resp = client_open.get("/api/v1/monitor/health")
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
```

Run: `pytest tests/test_api_auth.py::TestSecurityHeaders -v`
Expected: FAIL.

- [ ] **Step 7.7: Expand security-headers middleware**

Replace `app/api/__init__.py:110-117`:
```python
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=()"
        )
        # CSP — Tailwind is local; data: allowed for QR code images.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response
```

**Note:** `'unsafe-inline'` for script-src is required because `push.html` ships an inline `<script>`. When the engineer moves inline JS to an external file, tighten CSP to nonces or hashes.

- [ ] **Step 7.8: Re-run header test**

Run: `pytest tests/test_api_auth.py::TestSecurityHeaders -v`
Expected: PASS.

- [ ] **Step 7.9: Smoke test UI rendering**

Run: `docker compose up -d && curl -s http://127.0.0.1:8080/ui/static/tailwind.min.css | head -c 50`
Expected: CSS content.

Also: `curl -s http://127.0.0.1:8080/ui -H "Authorization: Bearer <token>" | grep tailwind.min.css`
Expected: local CSS reference (not cdn.tailwindcss.com).

- [ ] **Step 7.10: Commit**

```bash
git add app/api/__init__.py app/api/routers/ui.py app/ui/templates/base.html app/ui/static/tailwind.min.css tests/test_api_auth.py
git commit -m "fix(V5-05,V5-10): self-host Tailwind; add CSP/HSTS/Referrer-Policy/Permissions-Policy"
```

---

### Task 8: `xhtml2pdf.pisa.CreatePDF` link_callback (V5-08 / v0.4 F-04)

**Files:**
- Modify: `app/invoice_pdf_template.py:161,174`
- Test: `tests/test_pdf_security.py`

- [ ] **Step 8.1: Write failing test**

Add to `tests/test_pdf_security.py`:
```python
def test_xhtml2pdf_blocks_external_uri():
    from app.invoice_pdf_template import _pdf_link_callback  # to be added
    # External URIs blocked
    assert _pdf_link_callback("http://evil.com/x.css", None) == ""
    assert _pdf_link_callback("file:///etc/passwd", None) == ""
    # data: URIs allowed (QR code)
    assert _pdf_link_callback("data:image/png;base64,XXX", None).startswith("data:")
    # Bundled app templates allowed
    assert _pdf_link_callback("/app/app/templates/fonts/DejaVu.ttf", None).startswith("/app/")
```

Run: `pytest tests/test_pdf_security.py::test_xhtml2pdf_blocks_external_uri -v`
Expected: FAIL — callback doesn't exist.

- [ ] **Step 8.2: Implement callback**

Add near the top of `app/invoice_pdf_template.py`, after imports:
```python
_PDF_SAFE_PREFIXES = ("data:", "/app/app/templates/")


def _pdf_link_callback(uri: str, rel) -> str:
    """xhtml2pdf link_callback — allow only bundled resources + data: URIs."""
    if not uri:
        return ""
    if uri.startswith(_PDF_SAFE_PREFIXES):
        return uri
    logger.warning("xhtml2pdf: blocked external resource %s", uri[:120])
    return ""
```

In the `pisa.CreatePDF` call (around line 161):
```python
        pisa_status = pisa.CreatePDF(
            html_content, dest=buffer, encoding='utf-8',
            link_callback=_pdf_link_callback,
        )
```

- [ ] **Step 8.3: Run test**

Run: `pytest tests/test_pdf_security.py::test_xhtml2pdf_blocks_external_uri -v`
Expected: PASS.

- [ ] **Step 8.4: Regression — real PDF still renders**

Run: `pytest tests/test_pdf_security.py -v`
Expected: all existing PDF tests still green (the callback doesn't change anything for the default templates which only reference bundled resources).

- [ ] **Step 8.5: Commit**

```bash
git add app/invoice_pdf_template.py tests/test_pdf_security.py
git commit -m "fix(V5-08): restrict xhtml2pdf external resource loading via link_callback"
```

---

## P3 Tasks — backlog

Keep on `test`, merge behind a feature flag if risky. Smaller than P1/P2.

### Task 9: Alembic replaces `_migrate_schema` (v0.4 F-07)

- [ ] Audit existing `alembic/versions/*.py` — confirm initial revision matches current Base.metadata.
- [ ] Add a new migration for Phase 2 v0.5 tables (push_instances, initial_load_jobs).
- [ ] Replace `app/database.py:_migrate_schema` body with a single call to `command.upgrade(alembic_cfg, "head")` wrapped in try/except for offline fallback.
- [ ] Add `tests/test_db_migration.py` asserting a fresh DB and an old-schema DB both converge.
- [ ] Commit: `refactor(F-07): use alembic command.upgrade in place of ad-hoc ALTER TABLE`.

### Task 10: Rootless entrypoint mode (v0.4 F-09)

- [ ] Edit `entrypoint.sh` — at top:
```sh
CURRENT_UID=$(id -u)
if [ "$CURRENT_UID" != "0" ]; then
    echo "Running as non-root (UID=$CURRENT_UID) — rootless mode"
    umask 077
    exec python -u main.py
fi
# ... existing rootful logic ...
```
- [ ] Document in `README.md` how to run with Podman rootless / `userns-remap`.
- [ ] Commit.

### Task 11: Pydantic auto-validated `ksef_number` in all path parameters (v0.4 F-08 / V5-03 follow-up)

- [ ] Create `app/api/path_params.py` with a `KsefNumber = Annotated[str, constr(pattern=...)]` alias.
- [ ] Replace raw `ksef_number: str` in all routers with `ksef_number: KsefNumber`.
- [ ] Delete explicit regex checks added in Task 4 (now redundant — Pydantic handles 422).
- [ ] Re-run `tests/test_api_invoices.py`.
- [ ] Commit.

### Task 12: Initial load max date range (V5-11)

- [ ] In `initial_load.py:StartJobRequest`, add:
```python
from datetime import datetime, timedelta

    @model_validator(mode="after")
    def check_range(self):
        start = datetime.fromisoformat(self.start_date)
        end = datetime.fromisoformat(self.end_date)
        if (end - start) > timedelta(days=1825):
            raise ValueError("range exceeds 5 years")
        return self
```
- [ ] Add test `test_initial_load_rejects_range_over_5y`.
- [ ] Commit.

### Task 13: Autoescape for JSON templates (v0.4 F-06)

- [ ] Change `select_autoescape(["html"])` to `select_autoescape(["html", "json", "j2"])` in `template_renderer.py` and `invoice_pdf_template.py`.
- [ ] **Or better:** introduce per-channel autoescape callable:
```python
def _autoescape_for(template_name):
    if template_name is None:
        return False
    return template_name.endswith((".html", ".html.j2", ".json.j2"))
env = SandboxedEnvironment(..., autoescape=_autoescape_for)
```
- [ ] Run existing template tests; adjust any that rely on no-escape behaviour.
- [ ] Commit.

---

## Merge gate checklist

Before cutting `v0.5.0` tag / merging `test → main`:

- [ ] P1 Tasks 1-5 all merged with green CI
- [ ] `pytest tests/ -v` — full suite green (>=165 tests passing)
- [ ] `docker build` succeeds locally; `trivy image --severity HIGH,CRITICAL` exit 0
- [ ] `pip-audit --requirement requirements.lock --strict` exit 0
- [ ] Manual smoke: `/ui` returns 401 without token (confirmed V5-01 fix)
- [ ] Manual smoke: `curl /api/v1/push/pairing` returns 401; same with valid token returns QR (confirmed V5-02 fix)
- [ ] Manual smoke: `curl /api/v1/invoices/../etc/passwd/xml` returns 400 (V5-03 fix)
- [ ] `app/__init__.py:__version__ == "0.5.0"` (V5-09/V5-12 fix)
- [ ] Update `docs/ROADMAP.md` — mark v0.5 Security Hardening as complete
- [ ] Update `CHANGELOG.md` / release notes with CVE references
- [ ] Update audit doc `audit/20260421_security_audit_docker_v0_5_test_branch.md` — add status column showing "FIXED in commit XXXXX" per finding
- [ ] Create re-audit doc `audit/YYYYMMDD_security_reaudit_docker_v0_5.md` confirming each fix

---

## Appendix — command cheatsheet

```bash
# Start dev iteration
cd /Users/mlotocki/Downloads/Developer/monitor-ksef/ksef_monitor_v0_1
git checkout test
python -m venv .venv3 && source .venv3/bin/activate
pip install -r requirements.txt pytest pytest-mock httpx

# Run test subset
pytest tests/test_api_auth.py tests/test_api_invoices.py tests/test_api_push.py tests/test_api_rate_limit.py -v

# Full suite
pytest tests/ -v

# Build image
docker build -t ksef_monitor:test .

# Security scan
docker run --rm aquasec/trivy:latest image ksef_monitor:test --severity HIGH,CRITICAL
pip-audit -r requirements.lock --strict

# Per-commit conventions
git commit -m "fix(V5-XX): <short description>"
# Body should reference the finding ID from the audit doc.
```
