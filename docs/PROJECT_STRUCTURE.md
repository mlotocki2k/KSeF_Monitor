# Project Structure

This document explains the organization of the KSeF Invoice Monitor v0.3 application.

## Directory Layout

```
KSeF_Monitor/
│
├── main.py                      # Application entry point
│   └── Orchestrates all modules, handles signals
│
├── app/                         # Application package
│   ├── __init__.py             # Makes app a Python package
│   ├── config_manager.py       # Configuration management
│   ├── secrets_manager.py      # Secrets from env / Docker secrets / config
│   ├── ksef_client.py          # KSeF API v2.1/v2.2 client
│   ├── invoice_monitor.py      # Main monitoring logic + template context
│   ├── invoice_pdf_generator.py # XML parser + ReportLab PDF generator (fallback)
│   ├── invoice_pdf_template.py  # HTML/CSS template PDF renderer (xhtml2pdf)
│   ├── template_renderer.py    # Jinja2 template engine
│   ├── prometheus_metrics.py   # Prometheus metrics endpoint
│   ├── scheduler.py            # Flexible scheduling (5 modes)
│   ├── database.py             # SQLite + SQLAlchemy 2.0 ORM (v0.3)
│   ├── logging_config.py       # Logging setup with timezone
│   ├── templates/              # Built-in Jinja2 templates
│   │   ├── invoice_pdf.html.j2 # Invoice PDF template (HTML/CSS)
│   │   ├── pushover.txt.j2    # Plain text (Pushover)
│   │   ├── email.html.j2      # HTML (Email)
│   │   ├── slack.json.j2      # Block Kit JSON (Slack)
│   │   ├── discord.json.j2    # Embed JSON (Discord)
│   │   └── webhook.json.j2    # Payload JSON (Webhook)
│   └── notifiers/              # Multi-channel notification system
│       ├── __init__.py
│       ├── base_notifier.py    # Abstract base + render_and_send()
│       ├── notification_manager.py  # Facade managing multiple channels
│       ├── pushover_notifier.py     # Pushover mobile notifications
│       ├── discord_notifier.py      # Discord webhook with rich embeds
│       ├── slack_notifier.py        # Slack webhook with Block Kit
│       ├── email_notifier.py        # SMTP email with HTML
│       └── webhook_notifier.py      # Generic HTTP endpoint
│
├── docs/                        # Documentation
│   ├── INDEX.md                # Documentation index
│   ├── QUICKSTART.md           # Quick start guide
│   ├── KSEF_TOKEN.md           # KSeF token creation guide
│   ├── NOTIFICATIONS.md        # Notification channels guide
│   ├── TEMPLATES.md            # Jinja2 templates guide
│   ├── SECURITY.md             # Security best practices
│   ├── TESTING.md              # Testing guide
│   ├── PDF_GENERATION.md       # PDF generation guide
│   ├── PDF_TEMPLATES.md        # PDF template customization
│   ├── ROADMAP.md              # Project roadmap
│   ├── PROJECT_STRUCTURE.md    # This file
│   ├── KSEF_API_LIMITATIONS.md  # KSeF API limits & constraints
│   ├── SPEC_CHECK_DESIGN.md    # Spec monitoring design analysis
│   ├── DATABASE_DESIGN.md      # Database design (SQLite + SQLAlchemy)
│   ├── RATE_LIMITING_DESIGN.md # Rate limiter implementation plan
│   ├── OPTIMIZATION_FINDINGS.md # Performance optimization notes
│   └── IDE_TROUBLESHOOTING.md  # IDE setup help
│
├── examples/                    # Example configs & test scripts
│   ├── config.example.json     # Configuration template (with secrets)
│   ├── config.secure.json      # Config for Docker secrets (no secrets)
│   ├── .env.example            # Environment variables template
│   ├── test_invoice_pdf.py     # CLI test script for PDF generation
│   ├── test_template_pdf.py    # Test script for template PDF
│   └── test_dummy_pdf.py       # Test script with dummy data
│
├── spec/                        # API specifications
│   ├── openapi.json            # KSeF API v2.2.0 OpenAPI spec (production)
│   ├── openapi-test.json       # KSeF API OpenAPI spec (test environment)
│   ├── openapi-demo.json       # KSeF API OpenAPI spec (demo environment)
│   └── schemat_FA(3)_v1-0E.xsd # FA(3) invoice XSD schema
│
├── .github/                     # GitHub community & CI
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md        # Bug report template
│   │   └── feature_request.md   # Feature request template
│   ├── PULL_REQUEST_TEMPLATE.md # PR template
│   └── workflows/               # GitHub Actions
│       ├── docker-publish.yml          # Build & push Docker image to GHCR
│       ├── check_ksef_openapi.yml      # Monitor KSeF OpenAPI spec (3 envs)
│       ├── check_ksef_fa_schema.yml    # Monitor FA(3) XSD schema
│       ├── check-requirements-updates.yml  # Check outdated packages
│       └── update-requirements.yml     # Auto-update requirements.txt
│
├── alembic/                     # Database migrations (Alembic)
│   ├── env.py                  # Alembic environment config
│   ├── script.py.mako          # Migration template
│   └── versions/               # Migration scripts
│       └── a6a08e11ea74_phase1_*.py  # Phase 1: invoices + state + notifications
│
├── alembic.ini                  # Alembic configuration
│
├── tests/                       # Unit tests (pytest)
│   ├── conftest.py             # Shared test fixtures
│   ├── test_config_manager.py  # Configuration validation tests
│   └── test_invoice_monitor.py # Invoice monitor tests
│
├── db_admin.py                  # Database administration CLI tool
├── CONTRIBUTING.md              # How to contribute
├── CODE_OF_CONDUCT.md           # Community guidelines (Contributor Covenant)
├── pyproject.toml               # Python project metadata & keywords
├── entrypoint.sh                # Docker entrypoint (gosu, ownership fix)
├── config.json                  # Your configuration (git-ignored)
├── .env                         # Your secrets (git-ignored)
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Docker image definition (OCI labels, healthcheck)
├── docker-compose.yml           # Standard Docker Compose
├── docker-compose.env.yml       # Docker Compose with .env
├── docker-compose.secrets.yml   # Docker Compose with Docker secrets
│
└── data/                        # Persistent data (auto-created)
    ├── invoices.db              # SQLite database (invoices, state, notification log)
    ├── last_check.json          # Legacy state file (auto-migrated to DB on first run)
    └── invoices/                # Saved invoices (XML, PDF, UPO)
        └── {folder_structure}/  # Subfolders per config (e.g., 2026/02/)
```

## Module Responsibilities

### `main.py`
**Entry point for the application**

- Initializes all components
- Sets up logging
- Registers signal handlers for graceful shutdown
- Orchestrates the monitoring process

### `app/config_manager.py`
**Configuration loading and validation**

- Loads configuration from JSON file
- Validates required fields (ksef, notifications, schedule, storage, prometheus)
- Validates `templates_dir` if provided (warning only, non-blocking)
- Validates `folder_structure` and `file_name_pattern` placeholders (warning + fallback)
- Provides typed access to configuration values

### `app/secrets_manager.py`
**Secrets management with priority chain**

- Loads secrets from: environment variables → Docker secrets → config file
- Supports all 7 secret types (KSeF token + 6 notification channels)

### `app/ksef_client.py`
**KSeF API v2.1/v2.2 integration**

Implements the full KSeF authentication flow:
1. Challenge request
2. Token authentication (RSA-OAEP encryption)
3. Status polling
4. Token redemption
5. Automatic token refresh

**Key methods:**
- `authenticate()` - Complete auth flow
- `get_invoices_metadata()` - Query invoice metadata with full pagination (handles `hasMore`/`isTruncated`, max 250/page, safety limit 10,000 records)
- `get_invoice_xml()` - Fetch invoice XML by KSeF number
- `refresh_access_token()` - Refresh expired tokens
- `revoke_current_session()` - Clean session termination
- `_extract_api_error_details()` - Parse KSeF error responses (`problem+json` / `ExceptionResponse`)
- `_handle_401_refresh()` - Token expiry recovery with detailed logging

### `app/database.py` (v0.3)
**SQLite database layer — SQLAlchemy 2.0 ORM**

- `Database` class — engine, session factory, CRUD helpers, migration
- `Invoice` model — invoice metadata (ksef_number UNIQUE dedup)
- `MonitorState` model — per NIP + subject_type state (replaces `last_check.json`)
- `NotificationLog` model — notification delivery audit + dedup
- WAL mode + foreign keys + busy_timeout pragmas
- Automatic migration from `last_check.json` → DB on first run
- Alembic migrations with `render_as_batch=True` (SQLite)

Design: [DATABASE_DESIGN.md](DATABASE_DESIGN.md)

### `app/invoice_monitor.py`
**Core monitoring logic**

- Polls KSeF API at configured intervals
- Tracks seen invoices to prevent duplicates (SHA-256 hash deduplication)
- Saves invoice metadata to DB (when enabled) with ksef_number dedup
- Reads/writes monitor_state from DB (per NIP + subject_type) with JSON fallback
- Caps `dateRange` to 90 days (KSeF API 3-month limit) with warning
- Normalizes naive datetimes in state file with warning
- Builds template context for notifications (v0.3)
- Manages persistent state (`last_check.json` as fallback)
- Saves invoice artifacts (XML, PDF, UPO) with configurable folder structure (v0.3)
- Updates artifact paths in DB after saving files (v0.3)
- Safe file writing with configurable `file_exists_strategy` (skip/rename/overwrite) (v0.3)
- Error tracking in monitor_state (consecutive_errors, last_error) (v0.3)

**Key methods:**
- `run()` - Main monitoring loop
- `check_for_new_invoices()` - Check and notify
- `build_template_context()` - Build context dict for Jinja2 templates (v0.3)
- `_build_file_name()` - Build file name from configurable `file_name_pattern` (v0.3)
- `_resolve_output_dir()` - Resolve target dir from `folder_structure` pattern (v0.3)
- `_resolve_safe_path()` - Apply file_exists_strategy before writing (v0.3)
- `_save_invoice_artifacts()` - Save PDF, XML, UPO to target dir
- `shutdown()` - Graceful shutdown

### `app/template_renderer.py` (v0.3)
**Jinja2 notification template engine**

- Loads templates from user directory (priority) with fallback to built-in defaults
- `select_autoescape` only for `.html` — JSON/TXT without autoescaping
- Custom Jinja2 filters: `money`, `money_raw`, `date`, `json_escape`
- Polish monetary formatting (`,` decimal, space thousands separator)

**Key class:** `TemplateRenderer`
- `render(channel, context)` - Render template for given channel
- `has_template(channel)` - Check template availability

### `app/invoice_pdf_generator.py`
**Invoice XML parser + ReportLab PDF generator (fallback)**

- `InvoiceXMLParser` — parses FA_VAT XML from KSeF API into `invoice_data` dict
- `InvoicePDFGenerator` — generates PDF with ReportLab (A4 format, QR code, Polish characters)
- `generate_invoice_pdf()` — public API: template-first (xhtml2pdf) with ReportLab fallback
- Polish monetary formatting (v0.3)

### `app/invoice_pdf_template.py`
**HTML/CSS template PDF renderer (v0.3)**

- `InvoicePDFTemplateRenderer` — renders invoice PDF from Jinja2 HTML/CSS template via xhtml2pdf
- User template override mechanism (custom dir → built-in defaults)
- Custom Jinja2 filters: `fmt_amt`, `vat_label`, `payment_method`
- QR Code Type I as base64 data URI for HTML embedding

See [PDF_TEMPLATES.md](PDF_TEMPLATES.md) for template customization guide.

### `app/scheduler.py`
**Flexible scheduling system**

5 scheduling modes: `simple`, `minutes`, `hourly`, `daily`, `weekly`

### `app/prometheus_metrics.py`
**Prometheus metrics endpoint**

Exports: `ksef_last_check_timestamp`, `ksef_new_invoices_total`, `ksef_monitor_up`

Configurable `bind_address`: `0.0.0.0` (Docker, default) or `127.0.0.1` (bare metal).

### `app/notifiers/`
**Multi-channel notification system**

#### `base_notifier.py`
Abstract base class for all notifiers:
- `send_notification()` - Abstract method for sending notifications
- `render_and_send()` - Render Jinja2 template + send (v0.3)
- `_send_rendered()` - Channel-specific rendered content handler (v0.3)
- `_build_fallback_message()` - Plain text fallback on template errors (v0.3)

#### `notification_manager.py`
Facade managing multiple notification channels:
- `send_notification()` - Send to all channels (error/test/start/stop messages)
- `send_invoice_notification()` - Send invoice via templates to all channels (v0.3)
- Initializes `TemplateRenderer` from config (v0.3)

#### Channel notifiers
Each notifier overrides `_send_rendered()` for channel-specific formatting:

| Notifier | Channel | `_send_rendered()` behavior |
|----------|---------|---------------------------|
| `pushover_notifier.py` | Pushover | Plain text, truncated to 1024 chars |
| `discord_notifier.py` | Discord | JSON embed wrapped in `{"embeds": [...]}` |
| `slack_notifier.py` | Slack | Block Kit JSON with username/icon |
| `email_notifier.py` | Email | HTML body + plain text fallback |
| `webhook_notifier.py` | Webhook | JSON payload via configured HTTP method |

## Data Flow

### Invoice Notification (v0.3)

```
┌─────────────┐
│   main.py   │ ← Entry point
└──────┬──────┘
       │ initializes
       ├─────────────────────────────────────┐
       │                                     │
       ▼                                     ▼
┌──────────────┐              ┌──────────────────────┐
│config_manager│◄─────────────│   invoice_monitor    │
└──────────────┘              └──────────┬───────────┘
                                         │
                              build_template_context()
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │notification_manager  │
                              │send_invoice_notification()│
                              └──────────┬───────────┘
                                         │
                              ┌──────────┴───────────┐
                              │                      │
                              ▼                      ▼
                    ┌─────────────────┐   ┌──────────────────┐
                    │template_renderer│   │   notifiers[]    │
                    │  render()       │──▶│ render_and_send() │
                    └─────────────────┘   └──────────────────┘
                              │                      │
                    ┌─────────┘           ┌──────────┴──────────┐
                    ▼                     ▼         ▼          ▼
              ┌──────────┐         ┌─────────┐ ┌────────┐ ┌────────┐
              │templates/│         │Pushover │ │Discord │ │Email   │ ...
              │  *.j2    │         │  API    │ │Webhook │ │ SMTP   │
              └──────────┘         └─────────┘ └────────┘ └────────┘
```

### Fallback chain (template errors)

```
Custom template → Built-in template → Plain text fallback
   (user dir)       (app/templates/)    (_build_fallback_message)
```

## Volume Mounts (Docker)

| Mount | Path in Container | Mode | Purpose |
|-------|-------------------|------|---------|
| `./config.json` | `/config/config.json` | ro | Configuration |
| `ksef-data` (named volume) | `/data` | rw | Persistent state + invoices |
| `./templates` | `/data/templates` | ro | Custom notification templates (optional) |
| `./pdf_templates` | `/data/pdf_templates` | ro | Custom invoice PDF template (optional) |

## Development Workflow

### Making Changes

1. **Edit code** in `main.py` or `app/*.py`
2. **Restart container**: `docker-compose restart`
3. **Check logs**: `docker-compose logs -f`

No rebuild needed thanks to volume mounts!

### Customizing Templates

1. Copy built-in templates: `cp -r app/templates/ ./templates/`
2. Edit templates in `./templates/`
3. Mount volume in docker-compose: `- ./templates:/data/templates:ro`
4. Set `templates_dir` in config: `"templates_dir": "/data/templates"`
5. Restart container

See [TEMPLATES.md](TEMPLATES.md) for template syntax and available variables.

## Dependencies

Managed in `requirements.txt`:

| Package | Purpose |
|---------|---------|
| `requests` | HTTP client for APIs |
| `python-dateutil` | Date parsing utilities |
| `cryptography` | RSA-OAEP encryption |
| `pytz` | Timezone support |
| `prometheus-client` | Prometheus metrics |
| `Jinja2` | Notification + PDF templates |
| `defusedxml` | Safe XML parsing (XXE protection) |
| `reportlab` | PDF generation (fallback engine) |
| `qrcode` | QR Code on invoices |
| `xhtml2pdf` | HTML/CSS to PDF rendering |
| `SQLAlchemy` | ORM + database engine |
| `alembic` | Database schema migrations |

Installed during Docker build.

## Logging

All modules use Python's `logging` module:

```python
logger = logging.getLogger(__name__)
```

**Log levels:**
- `INFO`: Normal operations
- `WARNING`: Recoverable issues (e.g., template dir not found)
- `ERROR`: Operation failures (e.g., template rendering error, notification send failure)
- `DEBUG`: Detailed information (not enabled by default)

## Error Handling

Each module implements comprehensive error handling:

- **config_manager.py**: Validation errors exit with message; `templates_dir` warns only
- **ksef_client.py**: Retries authentication, logs API errors
- **template_renderer.py**: Returns `None` on render failure (triggers fallback)
- **base_notifier.py**: `render_and_send()` falls back to plain text on template errors
- **notifiers/*.py**: Log failures, continue operation (one channel failure doesn't stop others)
- **invoice_monitor.py**: Catches exceptions, sends error notifications
- **main.py**: Top-level exception handler, graceful shutdown
