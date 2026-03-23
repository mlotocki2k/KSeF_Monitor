# Re-Audit Remediation Report

**Project:** KSeF Monitor v0.4
**Date:** 2026-03-13
**Scope:** Re-audit findings R-01, R-02, R-03
**Branch:** `test` (commit `977f4ae`), cherry-picked to `v05_push` (`5f77159`)

---

## Executive Summary

All three re-audit findings have been remediated and verified with automated tests. The full test suite (423 tests) passes with zero regressions.

| Finding | Severity | Status | Commit |
|---------|----------|--------|--------|
| R-01: Auth token logged in plaintext | P3 | **FIXED** | `977f4ae` |
| R-02: `docs_enabled` not auto-disabled in prod | P4 | **FIXED** | `977f4ae` |
| R-03: REST API not wired in `main.py` | P3 | **FIXED** | `977f4ae` |

---

## R-01: Auth Token Logged in Plaintext (P3)

### Finding

When `api.enabled = true` and `auth_token` is empty, `ConfigManager._apply_api_defaults()` auto-generates a 48-character token (F-01 control) but logs the **full token** in plaintext:

```python
# BEFORE (config_manager.py:470)
logger.warning("  %s", generated_token)
```

**Risk:** Log aggregation systems, shared log files, or `docker logs` output expose the full Bearer token to anyone with log access.

### Remediation

Truncated the logged token to the first 8 characters followed by `...`:

```python
# AFTER (config_manager.py:470)
logger.warning("  %s...", generated_token[:8])
```

**Log output example:**
```
WARNING  API enabled without auth_token — auto-generated:
WARNING    a3Bf9xKq...
WARNING  Set api.auth_token in config.json or API_AUTH_TOKEN env var for a persistent token.
```

The administrator sees enough to identify the token but cannot reconstruct the full credential from logs.

### Test Coverage

| Test | Assertion |
|------|-----------|
| `TestTokenLogTruncation::test_token_logged_truncated` | Full token NOT in warning logs; truncated prefix IS present |
| `TestTokenLogTruncation::test_token_not_in_info_logs` | Full token NOT in info logs |

**File:** `tests/test_security_controls.py`

---

## R-02: `docs_enabled` Not Auto-Disabled in Production (P4)

### Finding

The F-02 control added `docs_enabled` parameter to `create_app()`, but `ConfigManager` always defaulted to `True`:

```python
# BEFORE (config_manager.py:453-454)
api.setdefault("docs_enabled", True)
```

In production (`ksef.environment == "prod"`), Swagger UI (`/docs`), ReDoc (`/redoc`), and OpenAPI spec (`/openapi.json`) remained enabled unless explicitly disabled — violating defense-in-depth.

### Remediation

`docs_enabled` now auto-defaults based on the KSeF environment:

```python
# AFTER (config_manager.py:453-458)
ksef_env = config.get("ksef", {}).get("environment", "")
if ksef_env == "prod":
    api.setdefault("docs_enabled", False)
else:
    api.setdefault("docs_enabled", True)
```

**Behavior:**
- `environment: "test"` / `"demo"` → `docs_enabled: true` (default)
- `environment: "prod"` → `docs_enabled: false` (default)
- Explicit `docs_enabled: true` in config.json **overrides** the prod default (operator opt-in)

### Test Coverage

| Test | Assertion |
|------|-----------|
| `TestDocsAutoDisableProd::test_docs_disabled_in_prod` | `environment=prod` → `docs_enabled=False` |
| `TestDocsAutoDisableProd::test_docs_enabled_in_test` | `environment=test` → `docs_enabled=True` |
| `TestDocsAutoDisableProd::test_explicit_docs_enabled_overrides_prod` | Explicit `docs_enabled=True` overrides prod default |

**File:** `tests/test_security_controls.py`

---

## R-03: REST API Not Wired in `main.py` (P3)

### Finding

The REST API module (`app/api/`) with `create_app()` factory and `APIServer` daemon thread existed and was fully tested, but `main.py` never imported or started it. The API was dead code in production — `api.enabled: true` in config had no effect.

### Remediation

Added API startup block in `main.py` after monitor initialization, before signal handler registration:

```python
# main.py (lines 165-186)
api_config = config.get("api") or {}
if api_config.get("enabled"):
    try:
        from app.api import create_app
        from app.api.server import APIServer

        api_app = create_app(
            db=database,
            monitor_instance=monitor,
            auth_token=api_config.get("auth_token", ""),
            cors_origins=api_config.get("cors_origins"),
            rate_limit_config=api_config.get("rate_limit"),
            docs_enabled=api_config.get("docs_enabled", True),
        )
        api_server = APIServer(
            api_app,
            host=api_config.get("bind_address", "127.0.0.1"),
            port=api_config.get("port", 8080),
        )
        api_server.start()
        logger.info("✓ REST API server started")
    except Exception as e:
        logger.warning(f"Failed to start REST API: {e}")
        logger.info("Continuing without REST API")
```

**Design decisions:**
- **Lazy import:** `from app.api import create_app` inside the `if` block — no import overhead when API is disabled
- **Graceful degradation:** API failure logs a warning but does NOT block the main monitor loop (consistent with Prometheus metrics pattern)
- **All security controls passed through:** `auth_token`, `cors_origins`, `rate_limit_config`, `docs_enabled` all forwarded to `create_app()`

### Additional Fixes in `main.py`

| Line | Change | Reason |
|------|--------|--------|
| 57 | `v0.3` → `v0.4` | Version string was outdated |
| 137 | `default="0.0.0.0"` → `default="127.0.0.1"` | Prometheus bind default consistent with F-03 fix |

### Test Coverage

| Test | Assertion |
|------|-----------|
| `TestApiWiredInMain::test_main_has_api_wiring` | Source code contains `create_app`, `APIServer`, conditional guard |
| `TestApiWiredInMain::test_api_import_works` | `create_app` and `APIServer` are importable and callable |

**File:** `tests/test_security_controls.py`

---

## Test Summary

### New Tests Added: 7

| # | Test Class | Test Method | Finding |
|---|-----------|-------------|---------|
| 1 | `TestTokenLogTruncation` | `test_token_logged_truncated` | R-01 |
| 2 | `TestTokenLogTruncation` | `test_token_not_in_info_logs` | R-01 |
| 3 | `TestDocsAutoDisableProd` | `test_docs_disabled_in_prod` | R-02 |
| 4 | `TestDocsAutoDisableProd` | `test_docs_enabled_in_test` | R-02 |
| 5 | `TestDocsAutoDisableProd` | `test_explicit_docs_enabled_overrides_prod` | R-02 |
| 6 | `TestApiWiredInMain` | `test_main_has_api_wiring` | R-03 |
| 7 | `TestApiWiredInMain` | `test_api_import_works` | R-03 |

### Full Suite Results

```
======================== 423 passed, 0 failed in 3.58s ========================
```

- **Total tests:** 423 (was 416 before re-audit)
- **Security audit tests:** 41 (in `test_security_controls.py`)
- **Regressions:** 0

---

## Cumulative Security Controls

All 13 controls from original audit + re-audit:

| ID | Control | Status | Verified By |
|----|---------|--------|-------------|
| F-01 | Auth token auto-generation | ✅ Fixed | `TestAuthTokenAutoGeneration` (3 tests) |
| R-01 | Token log truncation | ✅ Fixed | `TestTokenLogTruncation` (2 tests) |
| F-02 | Docs disable (`docs_enabled`) | ✅ Fixed | `TestDocsDisabled` (2 tests) |
| R-02 | Docs auto-disable in prod | ✅ Fixed | `TestDocsAutoDisableProd` (3 tests) |
| F-03 | Prometheus bind `127.0.0.1` | ✅ Fixed | `TestPrometheusBindAddress` (1 test) |
| F-04 | Email HTML escaping | ✅ Fixed | `TestEmailHTMLEscaping` (5 tests) |
| F-06 | Email CRLF injection | ✅ Fixed | `TestEmailCRLFInjection` (2 tests) |
| F-07 | API rate limiting | ✅ Fixed | `TestRateLimiting` (3 tests) |
| F-09 | Health info leak | ✅ Fixed | `TestHealthInfoLeak` (2 tests) |
| F-10 | CORS wildcard rejection | ✅ Fixed | `TestCORSWildcardRejection` (3 tests) |
| F-11 | Template sandbox (SSTI) | ✅ Fixed | `TestSandboxedEnvironment` (4 tests) |
| N-03 | SSRF redirect blocking | ✅ Fixed | `TestDiscord/SlackRedirectBlocking` (4 tests) |
| R-03 | API wired in main.py | ✅ Fixed | `TestApiWiredInMain` (2 tests) |

---

## Files Modified

| File | Changes |
|------|---------|
| `app/config_manager.py` | R-01: token truncation; R-02: docs auto-disable logic |
| `main.py` | R-03: API startup block; version `v0.3→v0.4`; Prometheus bind fix |
| `tests/test_security_controls.py` | 7 new tests (R-01, R-02, R-03) |

---

## Verification Steps for Auditor

```bash
# 1. Run security tests only
pytest tests/test_security_controls.py -v

# 2. Run full suite (no regressions)
pytest tests/ -v

# 3. Verify R-01: token truncation in source
grep -n "generated_token\[:8\]" app/config_manager.py

# 4. Verify R-02: prod auto-disable in source
grep -A3 'ksef_env == "prod"' app/config_manager.py

# 5. Verify R-03: API wiring in main.py
grep -n "create_app\|APIServer" main.py
```
