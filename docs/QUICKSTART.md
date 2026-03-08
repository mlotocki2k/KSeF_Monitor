# Quick Start Guide

Get your KSeF Invoice Monitor v0.3 running in 5 minutes!

## Prerequisites

- Docker installed ([Get Docker](https://docs.docker.com/get-docker/))
- Docker Compose installed
- KSeF authorization token
- At least one notification channel (choose from):
  - **Pushover** - Mobile notifications ([Sign up](https://pushover.net/))
  - **Discord** - Create a webhook in Server Settings → Integrations
  - **Slack** - Create incoming webhook at [api.slack.com](https://api.slack.com/messaging/webhooks)
  - **Email** - SMTP credentials (Gmail, Outlook, etc.)
  - **Webhook** - Your own HTTP endpoint

## Installation Methods

Choose the method that fits your needs:

### 🚀 Method 1: Automated Setup (Easiest)

```bash
# Run the setup wizard
chmod +x setup.sh
./setup.sh

# Follow the prompts to choose your security method
```

### 🔧 Method 2: Manual Setup (Development)

**Step 1: Choose Your Notification Channel(s)**

Choose one or more from:

<details>
<summary><b>Pushover</b> (Mobile notifications)</summary>

- Go to [pushover.net](https://pushover.net/)
- Copy your User Key
- Create an application and copy the API Token
</details>

<details>
<summary><b>Discord</b> (Webhook)</summary>

- Open Discord server settings
- Navigate to Integrations → Webhooks
- Click "New Webhook"
- Copy the Webhook URL
</details>

<details>
<summary><b>Slack</b> (Webhook)</summary>

- Go to [api.slack.com/messaging/webhooks](https://api.slack.com/messaging/webhooks)
- Create a new app or use existing
- Enable Incoming Webhooks
- Copy the Webhook URL
</details>

<details>
<summary><b>Email</b> (SMTP)</summary>

- Gmail: Create App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
- Outlook: Use account password with `smtp-mail.outlook.com:587`
- Other: Get SMTP server, port, and credentials from provider
</details>

<details>
<summary><b>Webhook</b> (Custom endpoint)</summary>

- Set up your own HTTP endpoint
- Optionally prepare authentication token
- Endpoint will receive POST with JSON: `{title, message, priority, timestamp}`
</details>

**Step 2: Get KSeF Token**
- Log in to [ksef-test.mf.gov.pl](https://ksef-test.mf.gov.pl/web/login) (or production: [ksef.mf.gov.pl](https://ksef.mf.gov.pl/web/login))
- Navigate to "Tokens" section
- Generate a new token — **ustaw uprawnienia tylko do przeglądania/pobierania faktur** (read-only)
- Copy it immediately (may be shown only once)
- Szczegółowy przewodnik: [KSEF_TOKEN.md](./KSEF_TOKEN.md)

**Step 3: Configure**
```bash
# Copy templates
cp examples/.env.example .env
cp examples/config.secure.json config.json
cp docker-compose.env.yml docker-compose.yml

# Edit .env with your credentials
nano .env
```

**Add your credentials** (only for channels you're using):
```bash
# Required
KSEF_TOKEN=your-ksef-token-here

# Pushover (optional)
PUSHOVER_USER_KEY=your-pushover-user-key
PUSHOVER_API_TOKEN=your-pushover-api-token

# Discord (optional)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Slack (optional)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Email (optional)
EMAIL_PASSWORD=your-smtp-password-or-app-password

# Webhook (optional)
WEBHOOK_TOKEN=your-auth-token
```

**Edit config.json** to enable your channels:
```bash
nano config.json
```

Enable channels in `notifications` section:
```json
{
  "notifications": {
    "channels": ["discord", "email"],  // ← Enable channels here
    "message_priority": 0,
    "discord": {
      "webhook_url": "loaded-from-env"
    },
    "email": {
      "smtp_server": "smtp.gmail.com",
      "smtp_port": 587,
      "use_tls": true,
      "username": "your-email@gmail.com",
      "password": "loaded-from-env",
      "from_address": "KSeF Monitor <your-email@gmail.com>",
      "to_addresses": ["recipient@example.com"]
    }
  }
}
```

**Step 4: Secure and Run**
```bash
# Set secure permissions
chmod 600 .env

# Start (image is pulled automatically from GHCR)
docker-compose up -d

# View logs
docker-compose logs -f
```

### 🏢 Method 3: Production with Docker Secrets

```bash
# Initialize Swarm (if not already)
docker swarm init

# Create secrets (only for channels you're using)
echo "your-ksef-token" | docker secret create ksef_token -

# Pushover
echo "your-pushover-user-key" | docker secret create pushover_user_key -
echo "your-pushover-api-token" | docker secret create pushover_api_token -

# Discord
echo "https://discord.com/api/webhooks/..." | docker secret create discord_webhook_url -

# Slack
echo "https://hooks.slack.com/services/..." | docker secret create slack_webhook_url -

# Email
echo "your-smtp-password" | docker secret create email_password -

# Webhook
echo "your-auth-token" | docker secret create webhook_token -

# Verify secrets
docker secret ls

# Copy config and enable channels
cp examples/config.secure.json config.json
nano config.json  # Set notifications.channels to ["pushover", "discord", ...]

# Deploy
docker stack deploy -c docker-compose.secrets.yml ksef

# View logs
docker service logs -f ksef_ksef-monitor
```

## Verification

### Check if it's running:
```bash
docker-compose ps
# or for swarm:
docker service ls
```

### View logs:
```bash
docker-compose logs -f
# or for swarm:
docker service logs -f ksef_ksef-monitor
```

### Expected output:
```
ksef-monitor | ======================================================================
ksef-monitor | KSeF Invoice Monitor v0.3
ksef-monitor | Based on KSeF API v2.2.0 (github.com/CIRFMF/ksef-docs)
ksef-monitor | Multi-channel notifications with Jinja2 templates
ksef-monitor | ======================================================================
ksef-monitor | Loading configuration...
ksef-monitor | ✓ Configuration loaded
ksef-monitor | ✓ KSeF client initialized
ksef-monitor | Initializing notification channels...
ksef-monitor | ✓ Notification system initialized
ksef-monitor |   Enabled channels: discord, email
ksef-monitor | ✓ Invoice monitor initialized
ksef-monitor | Checking for new invoices...
```

## Testing

### Automatic test notification:
Enable test notification in `config.json`:
```json
{
  "notifications": {
    "test_notification": true
  }
}
```

Restart and you'll receive a test notification on all enabled channels:
```bash
docker-compose restart
docker-compose logs -f
```

### Manual test:
```bash
docker-compose exec ksef-monitor python3 -c "
from app.config_manager import ConfigManager
from app.notifiers import NotificationManager
config = ConfigManager('/config/config.json')
notifier = NotificationManager(config)
print('Testing all channels...')
notifier.test_connection()
"
```

### Check which channels are enabled:
```bash
docker-compose logs | grep "Enabled channels"
# Output: Enabled channels: discord, email, pushover
```

### Force invoice check:
```bash
docker-compose restart
docker-compose logs -f
```

## Configuration

Edit `config.json` to customize:

```json
{
  "ksef": {
    "environment": "test",      // "test" or "prod"
    "nip": "1234567890"         // Your NIP
  },
  "notifications": {
    "channels": ["pushover", "discord"],  // Enabled notification channels
    "message_priority": 0,                // Priority for new invoices
    "test_notification": false,           // Send test on startup
    "pushover": {
      "user_key": "loaded-from-env",
      "api_token": "loaded-from-env"
    },
    "discord": {
      "webhook_url": "loaded-from-env",
      "username": "KSeF Monitor"
    }
  },
  "monitoring": {
    "subject_types": ["Subject1", "Subject2"],  // Invoice types to monitor
    "timezone": "Europe/Warsaw"                // IANA timezone (default)
  },
  "storage": {
    "save_xml": false,            // Save invoice XML files
    "save_pdf": false,            // Generate and save PDF files
    "output_dir": "/data/invoices", // Output directory (auto-created)
    "folder_structure": "",       // Subfolder pattern: {year}/{month}/{day}/{type}
    "file_exists_strategy": "skip" // skip / rename / overwrite
  },
  "schedule": {
    "mode": "minutes",          // Scheduling mode
    "interval": 5               // Check every 5 minutes
  }
}
```

**Multi-Channel Examples:**

```json
// Pushover + Email
{
  "notifications": {
    "channels": ["pushover", "email"],
    "pushover": { "user_key": "...", "api_token": "..." },
    "email": {
      "smtp_server": "smtp.gmail.com",
      "smtp_port": 587,
      "use_tls": true,
      "username": "monitor@example.com",
      "password": "loaded-from-env",
      "from_address": "KSeF Monitor <monitor@example.com>",
      "to_addresses": ["admin@example.com"]
    }
  }
}

// Discord + Slack (team notifications)
{
  "notifications": {
    "channels": ["discord", "slack"],
    "discord": { "webhook_url": "loaded-from-env" },
    "slack": { "webhook_url": "loaded-from-env" }
  }
}

// All 5 channels
{
  "notifications": {
    "channels": ["pushover", "discord", "slack", "email", "webhook"],
    "pushover": { ... },
    "discord": { ... },
    "slack": { ... },
    "email": { ... },
    "webhook": { "url": "https://example.com/webhook" }
  }
}
```

For detailed channel configuration, see [NOTIFICATIONS.md](./NOTIFICATIONS.md)

**Scheduling Options:**

```json
// Every 5 minutes
{"mode": "minutes", "interval": 5}

// Every 2 hours
{"mode": "hourly", "interval": 2}

// Daily at 9:00 AM
{"mode": "daily", "time": "09:00"}

// 3 times daily: morning, afternoon, evening
{"mode": "daily", "time": ["09:00", "14:00", "18:00"]}

// Weekdays only at 9:00 AM
{"mode": "weekly", "days": ["monday", "tuesday", "wednesday", "thursday", "friday"], "time": "09:00"}

// Mon, Wed, Fri - twice daily
{"mode": "weekly", "days": ["monday", "wednesday", "friday"], "time": ["08:00", "16:00"]}
```

**Validation:**
- interval-based modes (`simple`, `minutes`, `hourly`): require positive `interval`
- time-based modes (`daily`, `weekly`): require `time` in HH:MM format
- `weekly` mode: requires `days` array with valid weekday names

Secrets are in `.env` (or Docker secrets). Only include secrets for channels you're using:
```bash
# Required
KSEF_TOKEN=your-ksef-token

# Pushover (optional)
PUSHOVER_USER_KEY=your-user-key
PUSHOVER_API_TOKEN=your-api-token

# Discord (optional)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Slack (optional)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Email (optional)
EMAIL_PASSWORD=your-smtp-password

# Webhook (optional)
WEBHOOK_TOKEN=your-auth-token
```

## Common Commands

```bash
# Start
docker-compose up -d

# Stop
docker-compose down

# Restart
docker-compose restart

# View logs
docker-compose logs -f

# View last 100 lines
docker-compose logs --tail=100

# Rebuild after code changes
docker-compose build --no-cache
docker-compose up -d

# Check status
docker-compose ps

# Access shell
docker-compose exec ksef-monitor /bin/bash
```

## Troubleshooting

### No notifications received
1. Check which channels are enabled in logs:
   ```bash
   docker-compose logs | grep "Enabled channels"
   ```
2. Verify credentials in `.env` for enabled channels
3. Check channel-specific requirements:
   - **Pushover**: App installed on device
   - **Discord**: Webhook URL valid and not expired
   - **Slack**: Webhook URL valid and app installed in workspace
   - **Email**: SMTP credentials correct, port open (587/465)
   - **Webhook**: Endpoint accessible and responding
4. Enable test notification and restart:
   ```json
   "notifications": { "test_notification": true }
   ```
5. Check logs for errors:
   ```bash
   docker-compose logs -f | grep -i "notification\|error"
   ```

### Authentication failed
1. Verify KSeF token is correct
2. Check NIP format (10 digits, no spaces)
3. Ensure environment matches token (test/prod)
4. Check logs: `docker-compose logs | grep -i auth`

### Container won't start
```bash
# Check logs
docker-compose logs --tail=100

# Verify config syntax
cat config.json | python3 -m json.tool

# Check .env exists
ls -la .env

# Verify permissions
chmod 600 .env
```

### IDE import errors
See [IDE_TROUBLESHOOTING.md](./IDE_TROUBLESHOOTING.md)

This is just an IDE issue - the code runs fine!

## File Structure

```
KSeF_Monitor/
├── main.py                        # Entry point
├── app/                           # Application modules
│   ├── config_manager.py          # Configuration loading & validation
│   ├── secrets_manager.py         # Secrets from env / Docker secrets / config
│   ├── ksef_client.py             # KSeF API v2.1/v2.2 client
│   ├── invoice_monitor.py         # Main monitoring loop
│   ├── invoice_pdf_generator.py   # XML parser + ReportLab PDF (fallback)
│   ├── invoice_pdf_template.py    # HTML/CSS → PDF via xhtml2pdf (primary)
│   ├── template_renderer.py       # Jinja2 notification templates
│   ├── scheduler.py               # 5 scheduling modes
│   ├── prometheus_metrics.py      # /metrics endpoint
│   ├── logging_config.py          # Logging with timezone
│   ├── templates/                 # Built-in Jinja2 templates
│   └── notifiers/                 # Multi-channel notifications (5 channels)
├── config.json                    # Configuration (git-ignored)
├── .env                           # Secrets (git-ignored)
├── docker-compose.yml             # Docker Compose config
├── Dockerfile                     # Docker image definition
└── data/                          # Persistent data (auto-created)
    └── last_check.json            # State file
```

## Next Steps

1. **Read the docs:**
   - [README.md](../README.md) - Full documentation
   - [NOTIFICATIONS.md](./NOTIFICATIONS.md) - Complete notification channel guide
   - [TEMPLATES.md](./TEMPLATES.md) - Custom notification templates (Jinja2)
   - [SECURITY.md](./SECURITY.md) - Security best practices
   - [PROJECT_STRUCTURE.md](./PROJECT_STRUCTURE.md) - Architecture details

2. **Customize:**
   - Change check interval
   - Customize notification templates ([TEMPLATES.md](./TEMPLATES.md))
   - Add custom logic

3. **Monitor:**
   - Set up log rotation
   - Configure alerts
   - Regular token rotation

4. **Production:**
   - Use Docker Secrets
   - Enable log rotation
   - Set up monitoring
   - Regular backups

## Getting Help

- Check logs: `docker-compose logs -f`
- Read documentation files
- Verify configuration
- Test components individually

## Security Reminders

✅ Never commit `.env` or `config.json` with secrets
✅ Use `chmod 600 .env` to secure credentials
✅ Rotate tokens regularly
✅ Use Docker Secrets in production
✅ Monitor access logs

---

**Ready to go! Your KSeF invoices will be monitored automatically.**

For detailed documentation, see [README.md](../README.md)
