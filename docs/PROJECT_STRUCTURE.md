# Project Structure

This document explains the organization of the KSeF Invoice Monitor v0.3 application.

## Directory Layout

```
ksef-invoice-monitor/
│
├── main.py                      # Application entry point
│   └── Orchestrates all modules, handles signals
│
├── app/                         # Application package
│   ├── __init__.py             # Makes app a Python package
│   ├── config_manager.py       # Configuration management
│   ├── secrets_manager.py      # Secrets from env / Docker secrets / config
│   ├── ksef_client.py          # KSeF API v2.0 client
│   ├── invoice_monitor.py      # Main monitoring logic + template context
│   ├── invoice_pdf_generator.py # XML parser + PDF generator
│   ├── prometheus_metrics.py   # Prometheus metrics endpoint
│   ├── scheduler.py            # Flexible scheduling (5 modes)
│   ├── template_renderer.py    # Jinja2 template engine (v0.3)
│   ├── templates/              # Built-in notification templates (v0.3)
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
│   ├── TEMPLATES.md            # Jinja2 templates guide (v0.3)
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
│   └── openapi.json            # KSeF API v2.0 OpenAPI spec
│
├── config.json                  # Your configuration (git-ignored)
├── .env                         # Your secrets (git-ignored)
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Docker image definition
├── docker-compose.yml           # Standard Docker Compose
├── docker-compose.env.yml       # Docker Compose with .env
├── docker-compose.secrets.yml   # Docker Compose with Docker secrets
│
└── data/                        # Persistent data (auto-created)
    └── last_check.json          # Application state
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
- Provides typed access to configuration values

### `app/secrets_manager.py`
**Secrets management with priority chain**

- Loads secrets from: environment variables → Docker secrets → config file
- Supports all 7 secret types (KSeF token + 6 notification channels)

### `app/ksef_client.py`
**KSeF API v2.0 integration**

Implements the full KSeF authentication flow:
1. Challenge request
2. Token authentication (RSA-OAEP encryption)
3. Status polling
4. Token redemption
5. Automatic token refresh

**Key methods:**
- `authenticate()` - Complete auth flow
- `get_invoices_metadata()` - Query invoice metadata
- `get_invoice_xml()` - Fetch invoice XML by KSeF number
- `refresh_access_token()` - Refresh expired tokens
- `revoke_current_session()` - Clean session termination

### `app/invoice_monitor.py`
**Core monitoring logic**

- Polls KSeF API at configured intervals
- Tracks seen invoices to prevent duplicates (MD5 hash deduplication)
- Builds template context for notifications (v0.3)
- Manages persistent state (`last_check.json`)

**Key methods:**
- `run()` - Main monitoring loop
- `check_for_new_invoices()` - Check and notify
- `build_template_context()` - Build context dict for Jinja2 templates (v0.3)
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
**Invoice XML parser + PDF generator**

- Parses FA_VAT XML from KSeF API
- Generates PDF with ReportLab (A4 format, QR code, Polish characters)
- Polish monetary formatting (v0.3)

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
| `./config.json` | `/data/config.json` | ro | Configuration |
| `./data` | `/data` | rw | Persistent state |
| `./templates` | `/data/templates` | ro | Custom templates (optional) |

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
| `Jinja2` | Notification templates (v0.3) |
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

- **config_manager.py**: Validation errors exit with message; `templates_dir` warns only
- **ksef_client.py**: Retries authentication, logs API errors
- **template_renderer.py**: Returns `None` on render failure (triggers fallback)
- **base_notifier.py**: `render_and_send()` falls back to plain text on template errors
- **notifiers/*.py**: Log failures, continue operation (one channel failure doesn't stop others)
- **invoice_monitor.py**: Catches exceptions, sends error notifications
- **main.py**: Top-level exception handler, graceful shutdown
