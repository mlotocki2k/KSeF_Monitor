# Project Structure

This document explains the organization of the KSeF Invoice Monitor v0.2 application.

## Directory Layout

```
KSeF_Monitor/
│
├── main.py                      # Application entry point
│   └── Orchestrates all modules, handles signals
│
├── test_invoice_pdf.py          # CLI test script for PDF generation
│
├── app/                         # Application package
│   ├── __init__.py             # Makes app a Python package
│   ├── config_manager.py       # Configuration management
│   ├── secrets_manager.py      # Secrets from env / Docker secrets / config
│   ├── ksef_client.py          # KSeF API v2.1/v2.2 client
│   ├── invoice_monitor.py      # Main monitoring logic
│   ├── invoice_pdf_generator.py # XML parser + ReportLab PDF generator
│   ├── logging_config.py       # Logging setup with timezone
│   ├── prometheus_metrics.py   # Prometheus metrics endpoint
│   ├── scheduler.py            # Flexible scheduling (5 modes)
│   └── notifiers/              # Multi-channel notification system
│       ├── __init__.py
│       ├── base_notifier.py    # Abstract base class
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
│   ├── SECURITY.md             # Security best practices
│   ├── TESTING.md              # Testing guide
│   ├── PDF_GENERATION.md       # PDF generation guide
│   ├── ROADMAP.md              # Project roadmap
│   ├── PROJECT_STRUCTURE.md    # This file
│   └── IDE_TROUBLESHOOTING.md  # IDE setup help
│
├── examples/                    # Example configuration files
│   ├── config.example.json     # Configuration template (with secrets)
│   ├── config.secure.json      # Config for Docker secrets (no secrets)
│   └── .env.example            # Environment variables template
│
├── spec/                        # API specifications
│   └── openapi.json            # KSeF API v2.2.0 OpenAPI spec
│
├── .github/                     # GitHub community & CI
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md        # Bug report template
│   │   └── feature_request.md   # Feature request template
│   ├── PULL_REQUEST_TEMPLATE.md # PR template
│   └── workflows/               # GitHub Actions
│       ├── docker-publish.yml          # Build & push Docker image to GHCR
│       ├── check_ksef_openapi.yml      # Monitor KSeF OpenAPI spec (3 envs)
│       ├── check_ksef_fa_schema.yml    # Monitor FA(3)/FA(2) XSD schemas
│       ├── check-requirements-updates.yml  # Check outdated packages
│       └── update-requirements.yml     # Auto-update requirements.txt
│
├── CONTRIBUTING.md              # How to contribute
├── CODE_OF_CONDUCT.md           # Community guidelines (Contributor Covenant)
├── pyproject.toml               # Python project metadata & keywords
├── config.json                  # Your configuration (git-ignored)
├── .env                         # Your secrets (git-ignored)
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Docker image definition (OCI labels)
├── docker-compose.yml           # Standard Docker Compose
├── docker-compose.env.yml       # Docker Compose with .env
├── docker-compose.secrets.yml   # Docker Compose with Docker secrets
│
└── data/                        # Persistent data (auto-created)
    ├── last_check.json          # Application state
    └── invoices/                # Saved invoices (XML, PDF)
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
- Validates required fields (ksef, notifications, schedule, storage)
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

### `app/invoice_monitor.py`
**Core monitoring logic**

- Polls KSeF API at configured intervals
- Tracks seen invoices to prevent duplicates (MD5 hash deduplication)
- Caps `dateRange` to 90 days (KSeF API 3-month limit) with warning
- Normalizes naive datetimes in state file with warning
- Manages persistent state (`last_check.json`)
- Saves invoice artifacts (XML, PDF)

**Key methods:**
- `run()` - Main monitoring loop
- `check_for_new_invoices()` - Check and notify
- `_save_invoice_artifacts()` - Save PDF, XML to target dir
- `shutdown()` - Graceful shutdown

### `app/invoice_pdf_generator.py`
**Invoice XML parser + ReportLab PDF generator**

- `InvoiceXMLParser` — parses FA_VAT XML from KSeF API into `invoice_data` dict
- `InvoicePDFGenerator` — generates PDF with ReportLab (A4 format, QR code, Polish characters)
- `generate_invoice_pdf()` — public API for PDF generation

### `app/scheduler.py`
**Flexible scheduling system**

5 scheduling modes: `simple`, `minutes`, `hourly`, `daily`, `weekly`

### `app/prometheus_metrics.py`
**Prometheus metrics endpoint**

Exports: `ksef_last_check_timestamp`, `ksef_new_invoices_total`, `ksef_monitor_up`

### `app/notifiers/`
**Multi-channel notification system**

#### `base_notifier.py`
Abstract base class for all notifiers:
- `send_notification()` - Abstract method for sending notifications

#### `notification_manager.py`
Facade managing multiple notification channels:
- `send_notification()` - Send to all channels (error/test/start/stop messages)

#### Channel notifiers

| Notifier | Channel | Description |
|----------|---------|-------------|
| `pushover_notifier.py` | Pushover | Mobile push notifications |
| `discord_notifier.py` | Discord | Webhook with rich embeds |
| `slack_notifier.py` | Slack | Webhook with Block Kit |
| `email_notifier.py` | Email | SMTP with HTML formatting |
| `webhook_notifier.py` | Webhook | Generic HTTP endpoint |

## Data Flow

### Invoice Notification

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
                              check_for_new_invoices()
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │notification_manager  │
                              │send_notification()   │
                              └──────────┬───────────┘
                                         │
                              ┌──────────┴──────────┐
                              ▼         ▼          ▼
                        ┌─────────┐ ┌────────┐ ┌────────┐
                        │Pushover │ │Discord │ │Email   │ ...
                        │  API    │ │Webhook │ │ SMTP   │
                        └─────────┘ └────────┘ └────────┘
```

## Volume Mounts (Docker)

| Mount | Path in Container | Mode | Purpose |
|-------|-------------------|------|---------|
| `./config.json` | `/data/config.json` | ro | Configuration |
| `./data` | `/data` | rw | Persistent state + invoices |

## Development Workflow

### Making Changes

1. **Edit code** in `main.py` or `app/*.py`
2. **Restart container**: `docker-compose restart`
3. **Check logs**: `docker-compose logs -f`

No rebuild needed thanks to volume mounts!

## Dependencies

Managed in `requirements.txt`:

| Package | Purpose |
|---------|---------|
| `requests` | HTTP client for APIs |
| `python-dateutil` | Date parsing utilities |
| `cryptography` | RSA-OAEP encryption |
| `pytz` | Timezone support |
| `prometheus-client` | Prometheus metrics |
| `reportlab` | PDF generation |
| `qrcode` | QR Code on invoices |

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

- **config_manager.py**: Validation errors exit with message
- **ksef_client.py**: Retries authentication, logs API errors
- **notifiers/*.py**: Log failures, continue operation (one channel failure doesn't stop others)
- **invoice_monitor.py**: Catches exceptions, sends error notifications
- **main.py**: Top-level exception handler, graceful shutdown
