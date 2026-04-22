# Security Guide - Protecting Sensitive Credentials

This guide explains multiple methods to secure your API tokens and credentials for the KSeF Monitor v0.4.

**Protected Credentials:**
- KSeF API token
- API auth token (REST API Bearer auth)
- Pushover User Key & API Token
- Discord Webhook URL
- Slack Webhook URL
- Email SMTP password
- Webhook authentication token

## 🔐 Security Methods Overview

| Method | Security Level | Complexity | Best For |
|--------|---------------|------------|----------|
| Environment Variables | Medium | Low | Development |
| Docker Secrets | High | Medium | Production |
| Config File Only | Low | Very Low | **NOT RECOMMENDED** |
| External Vault | Very High | High | Enterprise |

## Method 1: Environment Variables (Recommended for Development)

### How It Works

Sensitive credentials are stored in a `.env` file and loaded as environment variables. The application reads them instead of storing in `config.json`.

### Setup

1. **Create .env file:**
   ```bash
   cp .env.example .env
   ```

2. **Edit .env with your credentials:**
   ```bash
   # Required
   KSEF_TOKEN=your-actual-ksef-token-here

   # Notification channels (add only channels you're using)

   # Pushover
   PUSHOVER_USER_KEY=your-pushover-user-key
   PUSHOVER_API_TOKEN=your-pushover-api-token

   # Discord
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

   # Slack
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

   # Email
   EMAIL_PASSWORD=your-smtp-password-or-app-password

   # Webhook
   WEBHOOK_TOKEN=your-auth-token
   ```

   **Note:** Only include secrets for notification channels you've enabled in `config.json`

3. **Use secure config file:**
   ```bash
   cp config.secure.json config.json
   ```

4. **Use environment-enabled docker-compose:**
   ```bash
   cp docker-compose.env.yml docker-compose.yml
   ```

5. **Run:**
   ```bash
   docker-compose up -d
   ```

### Advantages
✅ Credentials separate from code
✅ `.env` file in `.gitignore` (won't be committed)
✅ Easy to update credentials
✅ No rebuild required

### File Permissions
```bash
chmod 600 .env          # Only owner can read/write
chmod 644 config.json   # Everyone can read, owner can write
```

## Method 2: Docker Secrets (Recommended for Production)

### How It Works

Docker Secrets is a secure way to manage sensitive data in Docker Swarm. Secrets are encrypted and only available to authorized services.

### Setup for Docker Swarm

1. **Initialize Swarm (if not already):**
   ```bash
   docker swarm init
   ```

2. **Create secrets** (only for channels you're using):
   ```bash
   # KSeF token (required)
   echo "your-ksef-token" | docker secret create ksef_token -

   # Pushover credentials (optional)
   echo "your-pushover-user-key" | docker secret create pushover_user_key -
   echo "your-pushover-api-token" | docker secret create pushover_api_token -

   # Discord webhook (optional)
   echo "https://discord.com/api/webhooks/..." | docker secret create discord_webhook_url -

   # Slack webhook (optional)
   echo "https://hooks.slack.com/services/..." | docker secret create slack_webhook_url -

   # Email SMTP password (optional)
   echo "your-smtp-password" | docker secret create email_password -

   # Webhook auth token (optional)
   echo "your-auth-token" | docker secret create webhook_token -
   ```

3. **Verify secrets created:**
   ```bash
   docker secret ls
   ```

4. **Use secure config:**
   ```bash
   cp config.secure.json config.json
   ```

5. **Deploy with secrets:**
   ```bash
   docker stack deploy -c docker-compose.secrets.yml ksef
   ```

### Setup for Docker Compose (Development Secrets)

For local development without Swarm:

1. **Create secrets directory:**
   ```bash
   mkdir -p secrets
   chmod 700 secrets
   ```

2. **Create secret files** (only for channels you're using):
   ```bash
   # Required
   echo "your-ksef-token" > secrets/ksef_token

   # Optional notification channels
   echo "your-pushover-user-key" > secrets/pushover_user_key
   echo "your-pushover-api-token" > secrets/pushover_api_token
   echo "https://discord.com/api/webhooks/..." > secrets/discord_webhook_url
   echo "https://hooks.slack.com/services/..." > secrets/slack_webhook_url
   echo "your-smtp-password" > secrets/email_password
   echo "your-auth-token" > secrets/webhook_token

   chmod 600 secrets/*
   ```

3. **Update docker-compose.yml:**
   ```yaml
   secrets:
     ksef_token:
       file: ./secrets/ksef_token
     # Add only secrets for channels you're using
     pushover_user_key:
       file: ./secrets/pushover_user_key
     pushover_api_token:
       file: ./secrets/pushover_api_token
     discord_webhook_url:
       file: ./secrets/discord_webhook_url
     slack_webhook_url:
       file: ./secrets/slack_webhook_url
     email_password:
       file: ./secrets/email_password
     webhook_token:
       file: ./secrets/webhook_token
   ```

### Advantages
✅ Encrypted at rest and in transit
✅ Centralized secret management
✅ Automatic rotation support
✅ Access control
✅ Production-grade security

### Managing Secrets

**Update a secret:**
```bash
# Example: Rotating KSeF token
docker secret rm ksef_token
echo "new-token" | docker secret create ksef_token -
docker service update --secret-rm ksef_token --secret-add ksef_token ksef_ksef-monitor

# Example: Updating Discord webhook
docker secret rm discord_webhook_url
echo "https://discord.com/api/webhooks/new-url" | docker secret create discord_webhook_url -
docker service update --secret-rm discord_webhook_url --secret-add discord_webhook_url ksef_ksef-monitor
```

**List secrets:**
```bash
docker secret ls
```

**Inspect secret (won't show value):**
```bash
docker secret inspect ksef_token
```

## Method 3: Config File Only (NOT RECOMMENDED)

### Security Risks
❌ Tokens visible in plain text
❌ Easy to accidentally commit to git
❌ Difficult to rotate credentials
❌ No encryption

### When to Use
Only for:
- Quick testing
- Throwaway environments
- Demo purposes

### If You Must Use This Method

1. **Use restrictive file permissions:**
   ```bash
   chmod 600 config.json
   chown root:root config.json
   ```

2. **Verify .gitignore:**
   ```bash
   cat .gitignore | grep config.json
   ```

3. **Encrypt the file system:**
   Use encrypted storage for the directory containing config.json

## Method 4: External Secrets Vault (Enterprise)

For enterprise deployments, integrate with external secret managers:

### HashiCorp Vault

```python
# Example integration (add to secrets_manager.py)
import hvac

client = hvac.Client(url='https://vault.example.com')
secret = client.secrets.kv.v2.read_secret_version(path='ksef/tokens')
token = secret['data']['data']['ksef_token']
```

### AWS Secrets Manager

```python
import boto3

client = boto3.client('secretsmanager')
response = client.get_secret_value(SecretId='ksef/prod/token')
token = response['SecretString']
```

### Azure Key Vault

```python
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential

client = SecretClient(vault_url="https://myvault.vault.azure.net", 
                      credential=DefaultAzureCredential())
token = client.get_secret("ksef-token").value
```

## Method 5: GitHub Actions Secrets (CI/CD)

GitHub Actions workflows use **repository secrets** for automated notifications (e.g., Pushover alerts on API spec changes).

### Setup

1. Go to **Settings → Secrets and variables → Actions** in your GitHub repository
2. Click **New repository secret**
3. Add required secrets:

| Secret | Used By | Purpose |
|--------|---------|---------|
| `PUSHOVER_APP_TOKEN` | `check_ksef_openapi.yml`, `check_ksef_fa_schema.yml` | Pushover app token for CI notifications |
| `PUSHOVER_USER_KEY` | `check_ksef_openapi.yml`, `check_ksef_fa_schema.yml` | Pushover user key for CI notifications |

### Security Notes
- Repository secrets are encrypted and only exposed to workflows
- Secrets are not passed to workflows triggered from forks
- Use separate Pushover app tokens for CI vs application (principle of least privilege)

---

## All Available Secrets

| Secret | Environment Variable | Docker Secret | Required For | Notes |
|--------|---------------------|---------------|--------------|-------|
| KSeF Token | `KSEF_TOKEN` | `ksef_token` | Always | API authorization |
| API Auth Token | `API_AUTH_TOKEN` | `api_auth_token` | API (v0.4) | REST API Bearer auth |
| Pushover User Key | `PUSHOVER_USER_KEY` | `pushover_user_key` | Pushover | Mobile notifications |
| Pushover API Token | `PUSHOVER_API_TOKEN` | `pushover_api_token` | Pushover | Mobile notifications |
| Discord Webhook | `DISCORD_WEBHOOK_URL` | `discord_webhook_url` | Discord | Webhook URL |
| Slack Webhook | `SLACK_WEBHOOK_URL` | `slack_webhook_url` | Slack | Webhook URL |
| Email Password | `EMAIL_PASSWORD` | `email_password` | Email | SMTP password |
| Webhook Token | `WEBHOOK_TOKEN` | `webhook_token` | Webhook | Optional auth token |

**Important:** Only configure secrets for notification channels you've enabled in `config.json` → `notifications.channels`.

## Priority Order

The application loads secrets in this order (first found wins):

1. **Environment Variables** (highest priority)
2. **Docker Secrets**
3. **Config File** (lowest priority)

This allows you to:
- Use config file for development
- Override with environment variables for testing
- Use Docker secrets for production

## Security Best Practices

### General
✅ Never commit secrets to version control
✅ Use `.gitignore` for sensitive files
✅ Rotate credentials regularly (quarterly minimum)
✅ Use different credentials for test/production
✅ Monitor access logs
✅ Use principle of least privilege

### Notification Channel Security

**Webhook URLs (Discord, Slack, Custom):**
⚠️ Treat webhook URLs as secrets - anyone with the URL can post messages
✅ Store in environment variables or Docker secrets, not in config files
✅ Use different webhooks for test/production environments
✅ Regenerate webhooks if exposed (e.g., in logs, screenshots, commits)
✅ For custom webhooks, implement rate limiting and authentication

**Email:**
✅ Use App Passwords instead of account passwords (Gmail, Outlook)
✅ Enable 2FA on email accounts
✅ Use dedicated email accounts for automated notifications
✅ Restrict SMTP access to required IP ranges if possible

**Pushover:**
✅ Use application-specific API tokens
✅ Separate applications for different environments (dev/prod)
✅ Monitor usage in Pushover dashboard for suspicious activity

### File Permissions
```bash
# Secrets should be readable only by owner
chmod 600 .env
chmod 600 secrets/*
chmod 600 config.json  # if it contains secrets

# Directories should be protected
chmod 700 secrets/
chmod 700 data/
```

### Docker Security
```bash
# Don't run as root (already handled in Dockerfile)
# Scan for vulnerabilities
docker scan ksef-invoice-monitor

# Use read-only mounts where possible (already configured)
# Enable content trust
export DOCKER_CONTENT_TRUST=1
```

### Network Security
- Use HTTPS for all API calls (enforced)
- Enable firewall rules
- Use private networks for production
- Consider VPN for sensitive operations

## Verification

### Check What Secrets Are Loaded

```bash
# View logs (secrets are masked)
docker-compose logs | grep "loaded from"

# Should see (depending on enabled channels):
# KSeF token loaded from environment variable
# Pushover user key loaded from Docker secret
# Discord webhook URL loaded from environment variable
# Email password loaded from Docker secret
# etc.
```

### Check Which Channels Are Active

```bash
# View enabled notification channels
docker-compose logs | grep "Enabled channels"

# Example output:
# Enabled channels: discord, email, pushover
```

### Test Secret Loading

```bash
docker-compose exec ksef-monitor python3 -c "
from app.config_manager import ConfigManager
config = ConfigManager('/config/config.json')
print('✓ Config loaded successfully')
print('Environment:', config.get('ksef', 'environment'))
print('Secrets loaded:', 'token' in str(config.get('ksef', 'token')))
"
```

## Incident Response

### If Credentials Are Compromised

1. **Immediately revoke the compromised credentials:**
   - **KSeF**: Revoke token in KSeF portal
   - **Pushover**: Regenerate API token in Pushover app settings
   - **Discord**: Delete and recreate webhook in Server Settings
   - **Slack**: Regenerate webhook URL in Slack app settings
   - **Email**: Change SMTP password (for Gmail: revoke App Password)
   - **Webhook**: Rotate authentication token on your endpoint

2. **Generate new credentials:**
   - Create new tokens/URLs for compromised channels
   - Update secrets using the appropriate method

3. **Rotate secrets:**
   ```bash
   # Docker secrets
   docker secret rm ksef_token
   echo "new-token" | docker secret create ksef_token -
   docker service update --secret-rm ksef_token --secret-add ksef_token ksef_ksef-monitor
   ```

4. **Review access logs:**
   - Check for unauthorized access
   - Document the incident

5. **Update security measures:**
   - Implement additional controls
   - Review and update this guide

## Compliance Considerations

### GDPR
- Credentials may be considered personal data
- Implement appropriate security measures
- Document data processing

### PCI DSS (if applicable)
- Encrypt credentials at rest and in transit
- Implement access controls
- Maintain audit logs

### SOC 2
- Document security policies
- Implement change management
- Regular security reviews

## Recommended Setup by Environment

### Development
```bash
Method: Environment Variables (.env file)
Config: config.secure.json
Compose: docker-compose.env.yml
Permissions: 600 on .env
```

### Staging
```bash
Method: Docker Secrets (file-based)
Config: config.secure.json
Compose: docker-compose.secrets.yml
Permissions: 700 on secrets/
```

### Production
```bash
Method: Docker Secrets (Swarm) or External Vault
Config: config.secure.json
Deploy: docker stack deploy
Monitoring: Enabled
Audit Logging: Enabled
```

## Quick Start Examples

### Development Setup
```bash
# 1. Setup
cp .env.example .env
cp config.secure.json config.json
cp docker-compose.env.yml docker-compose.yml

# 2. Edit secrets
nano .env

# 3. Set permissions
chmod 600 .env

# 4. Run
docker-compose up -d
```

### Production Setup
```bash
# 1. Setup
cp config.secure.json config.json
cp docker-compose.secrets.yml docker-compose.yml

# 2. Create secrets (only for channels you're using)
echo "prod-ksef-token" | docker secret create ksef_token -

# Example: Discord + Email channels
echo "https://discord.com/api/webhooks/..." | docker secret create discord_webhook_url -
echo "smtp-app-password" | docker secret create email_password -

# Or all channels:
# echo "..." | docker secret create pushover_user_key -
# echo "..." | docker secret create pushover_api_token -
# echo "..." | docker secret create slack_webhook_url -
# echo "..." | docker secret create webhook_token -

# 3. Update config.json with enabled channels
nano config.json  # Set notifications.channels

# 4. Deploy
docker stack deploy -c docker-compose.yml ksef
```

## v0.5 Security Hardening (2026-04)

This section covers security controls introduced in v0.5 as part of audit remediation
(`audit/20260421_security_audit_docker_v0_5_test_branch.md` + post-remediation re-audit
`audit/20260422_security_reaudit_v0_5_post_remediation.md`).

### Authentication model

v0.5 uses a **two-layer auth model**:

1. **Bearer token (default)** — all endpoints except the public whitelist require
   `Authorization: Bearer <token>` verified with `hmac.compare_digest`.
2. **`api.ui_public` opt-in (default `false`)** — setting `api.ui_public: true` re-enables
   unauthenticated access to the `/ui` routes for legacy reverse-proxy setups where the
   proxy enforces auth externally.

### Endpoint auth matrix

| Endpoint | Auth required | Notes |
|----------|:-------------:|-------|
| `/docs` | No | Swagger UI; disable with `docs_enabled: false` in prod |
| `/redoc` | No | ReDoc UI; same as above |
| `/openapi.json` | No | OpenAPI spec |
| `/api/v1/monitor/health` | No | Health probe — safe to expose to load balancers |
| `/ui/**` | **Yes** (unless `api.ui_public: true`) | Web UI routes |
| `/api/v1/invoices/{ksef}/pdf` | **Yes** | PDF download |
| `/api/v1/invoices/{ksef}/xml` | **Yes** | XML download |
| `/api/v1/push/**` | **Yes** | Push setup, pairing, regenerate, reset |
| All other `/api/v1/**` | **Yes** | Invoices, stats, monitor, artifacts |

Previous versions had a pattern-based whitelist that inadvertently exempted `/ui/**`,
`/invoices/**/pdf|xml`, and `/push/devices` — this was closed in V5-01.

### `GET /api/v1/push/pairing` — auth-gated plaintext reveal

v0.5 adds a new **authenticated** endpoint that returns the full plaintext pairing code
and a rendered QR code for pairing the Monitor KSeF iOS app. The pairing code was widened
from 32-bit to 64-bit (`secrets.token_hex(8)`) in the same release.

`/api/v1/push/setup` (unauthenticated when `ui_public` was set) now returns only a
**masked** preview (`X…Y`). The actual code is exclusively available at
`/api/v1/push/pairing` behind auth.

### Per-endpoint rate limits

v0.5 introduces granular `slowapi` rate limits on mutating and sensitive routes (V5-06).
All limits are overridable via `api.rate_limit.<key>` in `config.json`.

| Endpoint | Method | Default limit | Config key |
|----------|--------|:-------------:|------------|
| `/api/v1/monitor/trigger` | POST | 2/min | `api.rate_limit.trigger` |
| `/api/v1/initial-load/start` | POST | 1/hr | `api.rate_limit.initial_load_start` |
| `/api/v1/push/regenerate` | POST | 5/hr | `api.rate_limit.push_regenerate` |
| `/api/v1/push/reset` | POST | 1/hr | `api.rate_limit.push_reset` |
| `/api/v1/invoices/{ksef}/pdf` | GET | 30/min | `api.rate_limit.invoice_download` |
| `/api/v1/invoices/{ksef}/xml` | GET | 30/min | `api.rate_limit.invoice_download` |
| All other endpoints | * | 60/min | `api.rate_limit.default` |

### SSRF guard

`app._ssrf_guard.is_safe_public_url` is a shared validator applied to:
- **Webhook notifier URLs** (existing, carried forward from v0.4 N-03)
- **CIRFMF PDF generator URL** (`storage.pdf_ksef_generator_url`) — new in v0.5

The guard rejects private, loopback, link-local, multicast, and IANA-reserved IP
destinations. Known limitation: TOCTOU DNS rebinding is possible (a server that resolves
to a public IP at validation time could switch to a private IP before the actual request).
This is a defense-in-depth gap tracked at INFO level; mitigate with network-level egress
controls in production.

### Security headers (v0.5)

v0.5 expands the HTTP response header set (V5-05):

| Header | Value |
|--------|-------|
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=()` |
| `X-Content-Type-Options` | `nosniff` (carried forward) |
| `X-Frame-Options` | `DENY` (carried forward) |
| `Cache-Control` | `no-store` (carried forward) |

Known follow-up: `script-src 'unsafe-inline'` is required while `push.html` contains
inline JS. Tracked item — move to `app/ui/static/push.js` and switch to hashed/nonce CSP.

### `xhtml2pdf` link_callback restrictions (V5-08)

The PDF generator (`invoice_pdf_template.py`) passes a `link_callback` to
`xhtml2pdf.pisa.CreatePDF`. The callback allows only:
- `data:` URIs (inline base64 images — used for QR codes and embedded fonts)
- Paths under the bundled template directory

Any other URI (external HTTP, absolute filesystem paths outside the template root) is
**blocked**. This prevents SSRF and LFI through user-customized HTML/CSS PDF templates.

### Tailwind CSS — self-hosted (V5-10)

The Web UI no longer loads Tailwind CSS from `cdn.tailwindcss.com`. v0.5 bundles a
14 KB scanned/purged build at `app/ui/static/tailwind.min.css`. This eliminates the CDN
supply-chain dependency and the Content-Security-Policy violation that CDN loading caused.
Cache-busting is done via `?v={version}` query string on the static file reference.

### CVE-driven dependency pins (V5-04)

| Package | Pinned version | CVE(s) closed |
|---------|:-------------:|---------------|
| `urllib3` | `>=2.6.3` | CVE-2025-66418 (CVSS 8.9), CVE-2025-66471 |
| `starlette` | `>=0.49.1,<1.0.0` | CVE-2025-62727 |
| `python-multipart` | `>=0.0.26` | CVE-2024-53981, CVE-2026-40347, CVE-2026-24486 |
| `cryptography` | `==46.0.7` | CVE-2026-39892 |

`requirements.lock` is generated with `pip-compile --generate-hashes`; the Dockerfile
installs via `pip install --require-hashes` to enforce the lockfile. CI runs `pip-audit
--strict` against the lockfile and `trivy image` scan of the built container (exit-code 1
on CRITICAL/HIGH findings).

### Rootless entrypoint (v0.4 F-09 carried into v0.5)

`entrypoint.sh` detects `id -u != 0` at runtime. When non-root (Podman rootless,
userns-remap, rootless Docker), the `usermod`/`groupmod`/`chown` operations are skipped
and the application is exec'd directly, avoiding permission errors in restricted container
runtimes.

### Alembic migrations replace ad-hoc ALTER TABLE (v0.4 F-07 carried into v0.5)

The `_migrate_schema` method's runtime `ALTER TABLE` f-string loop was replaced by
`alembic.command.upgrade(head)` / `stamp(head)` detection based on the `alembic_version`
table. For databases upgrading from v0.4, operators should run:

```bash
alembic stamp <current_rev>
alembic upgrade head
```

if the `alembic_version` table is absent (a warning is logged on startup in that case).

### Known deferred items

1. **Regenerate `requirements.lock` under Python 3.11** — current lockfile was compiled
   with Python 3.12. Blocked on Docker Desktop availability in the build environment.
2. **Tighten CSP `script-src 'unsafe-inline'`** — requires moving `push.html` inline JS
   to `app/ui/static/push.js` and switching to a hashed/nonce-based script allowlist.
3. **TOCTOU DNS rebinding in SSRF guard** — defense-in-depth gap; mitigate with
   network-level egress controls. Tracked at INFO log level.

---

## Security Hardening (v0.4 Audit)

The following security controls were implemented based on a v0.4 security audit:

| ID | Control | Description |
|----|---------|-------------|
| F-01 | Auth token auto-generation | API auto-generates a random 48-char token if `auth_token` is empty when API is enabled. Token is logged at startup. |
| F-02 | Docs disable | `/docs`, `/redoc`, `/openapi.json` can be disabled with `docs_enabled: false` for production. |
| F-03 | Prometheus bind | Default bind changed from `0.0.0.0` to `127.0.0.1` to prevent unintended exposure. |
| F-04 | Email HTML escaping | All user-controlled fields in HTML emails are escaped via `html.escape()`. |
| F-06 | Email CRLF | CRLF characters stripped from email Subject header to prevent header injection. |
| F-07 | API rate limiting | slowapi middleware with configurable limits (`60/minute` default). |
| F-09 | Health info leak | `auth_enabled` field removed from `/health` response (info disclosure). |
| F-10 | CORS wildcard | CORS wildcard `*` rejected when `auth_token` is set. |
| F-11 | Template sandbox | Jinja2 `SandboxedEnvironment` replaces `Environment` (SSTI prevention). |
| N-03 | SSRF redirects | `allow_redirects=False` on all webhook/notifier HTTP calls. |

## Vulnerability Disclosure Policy

If you discover a security vulnerability in KSeF Monitor, please report it responsibly:

1. **Do NOT open a public GitHub issue** for security vulnerabilities
2. **Email the maintainer directly** or use [GitHub Security Advisories](https://github.com/mlotocki2k/KSeF_Monitor/security/advisories/new) to report privately
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

**Response timeline:**
- Acknowledgment within **48 hours**
- Assessment and fix plan within **7 days**
- Patch release within **30 days** (critical issues faster)

We will credit reporters in the release notes (unless anonymity is requested).

**Scope:** This policy covers the KSeF Monitor application code, Docker configuration, and CI/CD pipelines. It does not cover the KSeF API itself (report those to the Ministry of Finance).

## Support

For general security questions:
- Open a GitHub issue (do NOT include actual credentials or vulnerability details)
- Contact maintainers directly for sensitive matters

---

**Remember: Security is not a one-time setup, it's an ongoing process.**
