# Project Structure

This document explains the organization of the KSeF Invoice Monitor application.

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
│   ├── ksef_client.py          # KSeF API v2.0 client
│   ├── pushover_notifier.py    # Pushover notification service
│   └── invoice_monitor.py      # Main monitoring logic
│
├── config.json                  # Your configuration (git-ignored)
├── config.example.json          # Configuration template
│
├── Dockerfile                   # Docker image definition
├── docker-compose.yml           # Docker Compose orchestration
├── requirements.txt             # Python dependencies
│
├── .gitignore                  # Git ignore patterns
├── README.md                   # Main documentation
├── PROJECT_STRUCTURE.md        # This file
│
└── data/                       # Persistent data (auto-created)
    └── last_check.json         # Application state
```

## Module Responsibilities

### `main.py`
**Entry point for the application**

- Initializes all components
- Sets up logging
- Registers signal handlers for graceful shutdown
- Orchestrates the monitoring process

**Key functions:**
- `main()` - Application initialization and startup
- `signal_handler()` - Handles SIGINT and SIGTERM

### `app/config_manager.py`
**Configuration loading and validation**

- Loads configuration from JSON file
- Validates required fields
- Provides typed access to configuration values

**Key class:**
- `ConfigManager` - Manages application configuration

### `app/ksef_client.py`
**KSeF API v2.0 integration**

Implements the full KSeF authentication flow:
1. Challenge request
2. Token authentication
3. Status polling
4. Token redemption
5. Automatic token refresh

**Key class:**
- `KSeFClient` - Handles all KSeF API interactions

**Key methods:**
- `authenticate()` - Complete auth flow
- `get_invoices_metadata()` - Query invoice metadata
- `refresh_access_token()` - Refresh expired tokens
- `revoke_current_session()` - Clean session termination

### `app/pushover_notifier.py`
**Push notification service**

- Sends notifications via Pushover API
- Handles errors gracefully
- Provides specialized notification types

**Key class:**
- `PushoverNotifier` - Manages Pushover notifications

**Key methods:**
- `send_notification()` - Send standard notification
- `send_error_notification()` - Send error with high priority
- `test_connection()` - Test Pushover setup

### `app/invoice_monitor.py`
**Core monitoring logic**

- Polls KSeF API at configured intervals
- Tracks seen invoices to prevent duplicates
- Formats and sends notifications
- Manages persistent state

**Key class:**
- `InvoiceMonitor` - Main monitoring service

**Key methods:**
- `run()` - Main monitoring loop
- `check_for_new_invoices()` - Check and notify
- `format_invoice_message()` - Format notification text
- `shutdown()` - Graceful shutdown

## Data Flow

```
┌─────────────┐
│   main.py   │ ← Entry point
└──────┬──────┘
       │ initializes
       ├──────────────────────────────┐
       │                              │
       ▼                              ▼
┌──────────────┐              ┌──────────────┐
│config_manager│◄─────────────┤invoice_monitor│
└──────────────┘              └───────┬──────┘
                                      │
                              ┌───────┴───────┐
                              │               │
                              ▼               ▼
                      ┌──────────────┐ ┌──────────────┐
                      │ ksef_client  │ │pushover_     │
                      │              │ │notifier      │
                      └──────┬───────┘ └──────┬───────┘
                             │                │
                             ▼                ▼
                      ┌──────────────┐ ┌──────────────┐
                      │  KSeF API    │ │ Pushover API │
                      └──────────────┘ └──────────────┘
```

## Volume Mounts (Docker)

The docker-compose.yml configuration mounts:

1. **`./main.py:/app/main.py:ro`**
   - Main entry point (read-only)
   - Allows updates without rebuild

2. **`./app:/app/app:ro`**
   - All application modules (read-only)
   - Hot reload capability

3. **`./config.json:/data/config.json:ro`**
   - Configuration file (read-only)
   - Separate from code for security

4. **`./data:/data`**
   - Persistent state (read-write)
   - Survives container restarts

## Development Workflow

### Making Changes

1. **Edit code** in `main.py` or `app/*.py`
2. **Restart container**: `docker-compose restart`
3. **Check logs**: `docker-compose logs -f`

No rebuild needed thanks to volume mounts!

### Adding New Module

1. Create new file in `app/` directory
2. Add import in `app/__init__.py`
3. Import and use in `main.py`
4. Restart container

### Testing Changes

```bash
# Test configuration
docker-compose exec ksef-monitor python3 -c "
from app.config_manager import ConfigManager
config = ConfigManager('/data/config.json')
print('Config OK')
"

# Test KSeF authentication
docker-compose exec ksef-monitor python3 -c "
from app import ConfigManager, KSeFClient
config = ConfigManager('/data/config.json')
client = KSeFClient(config)
print('Auth:', client.authenticate())
"

# Test Pushover
docker-compose exec ksef-monitor python3 -c "
from app import ConfigManager, PushoverNotifier
config = ConfigManager('/data/config.json')
notifier = PushoverNotifier(config)
notifier.test_connection()
"
```

## Configuration Management

### File Location

- **Host**: `./config.json`
- **Container**: `/data/config.json`
- **Mounted**: Read-only
- **Not in git**: Listed in `.gitignore`

### Structure

```json
{
  "ksef": { ... },       // KSeF API settings
  "pushover": { ... },   // Notification settings
  "monitoring": { ... }  // Monitoring behavior
}
```

### Loading

Configuration is loaded once at startup by `ConfigManager`:
1. Validates file exists
2. Parses JSON
3. Validates required fields
4. Provides typed access

## State Management

### State File

- **Location**: `./data/last_check.json`
- **Format**: JSON
- **Purpose**: Track seen invoices and last check time

### Structure

```json
{
  "last_check": "2024-02-04T15:30:00",
  "seen_invoices": ["hash1", "hash2", ...]
}
```

### Lifecycle

1. **Load** on startup (or create empty)
2. **Update** after each check
3. **Persist** to disk
4. **Retain** across restarts

## Error Handling

Each module implements comprehensive error handling:

- **config_manager.py**: Validation errors exit with message
- **ksef_client.py**: Retries authentication, logs API errors
- **pushover_notifier.py**: Logs failures, continues operation
- **invoice_monitor.py**: Catches exceptions, sends error notifications
- **main.py**: Top-level exception handler, graceful shutdown

## Logging

All modules use Python's `logging` module:

```python
logger = logging.getLogger(__name__)
```

**Log levels:**
- `INFO`: Normal operations
- `WARNING`: Recoverable issues
- `ERROR`: Operation failures
- `DEBUG`: Detailed information (not enabled by default)

**Log format:**
```
%(asctime)s - %(name)s - %(levelname)s - %(message)s
```

## Security Considerations

1. **Config file**: Read-only mount, not in git
2. **Tokens**: Never logged or exposed
3. **Credentials**: Only in config.json
4. **File permissions**: Config should be 600 or 644
5. **Volume mounts**: Code is read-only

## Dependencies

Managed in `requirements.txt`:
- `requests` - HTTP client for APIs
- `python-dateutil` - Date parsing utilities

Installed during Docker build.

## Future Extensions

To add new features:

1. **New API client**: Create `app/new_api_client.py`
2. **Database storage**: Add persistence module
3. **Web interface**: Add Flask/FastAPI app
4. **Multiple monitors**: Run multiple instances with different configs
5. **Metrics**: Add Prometheus exporter

Each new module follows the same pattern:
- Create class in `app/`
- Import in `app/__init__.py`
- Initialize in `main.py`
- Use dependency injection
