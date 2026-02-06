# Quick Start Guide

Get your KSeF Invoice Monitor running in 5 minutes!

## Prerequisites

- Docker installed ([Get Docker](https://docs.docker.com/get-docker/))
- Docker Compose installed
- Pushover account ([Sign up free](https://pushover.net/))
- KSeF authorization token

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

**Step 1: Get Pushover Credentials**
- Go to [pushover.net](https://pushover.net/)
- Copy your User Key
- Create an application and copy the API Token

**Step 2: Get KSeF Token**
- Log in to [ksef-test.mf.gov.pl](https://ksef-test.mf.gov.pl/web/login) (or production)
- Navigate to "Tokens" section
- Generate a new token and copy it immediately

**Step 3: Configure**
```bash
# Copy templates
cp .env.example .env
cp config.secure.json config.json
cp docker-compose.env.yml docker-compose.yml

# Edit .env with your credentials
nano .env
```

Add your credentials:
```bash
KSEF_TOKEN=your-ksef-token-here
PUSHOVER_USER_KEY=your-pushover-user-key
PUSHOVER_API_TOKEN=your-pushover-api-token
```

**Step 4: Secure and Run**
```bash
# Set secure permissions
chmod 600 .env

# Build and start
docker-compose build
docker-compose up -d

# View logs
docker-compose logs -f
```

### 🏢 Method 3: Production with Docker Secrets

```bash
# Initialize Swarm (if not already)
docker swarm init

# Create secrets
echo "your-ksef-token" | docker secret create ksef_token -
echo "your-pushover-user-key" | docker secret create pushover_user_key -
echo "your-pushover-api-token" | docker secret create pushover_api_token -

# Verify secrets
docker secret ls

# Copy config
cp config.secure.json config.json

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
ksef-monitor | KSeF Invoice Monitor v2.0
ksef-monitor | Based on KSeF API v2.0 (github.com/CIRFMF/ksef-docs)
ksef-monitor | ======================================================================
ksef-monitor | Loading configuration...
ksef-monitor | ✓ Configuration loaded
ksef-monitor | ✓ KSeF client initialized
ksef-monitor | ✓ Pushover notifier initialized
ksef-monitor | ✓ Invoice monitor initialized
ksef-monitor | Checking for new invoices...
```

## Testing

### Test Pushover:
You should receive a startup notification on your device.

### Manual test:
```bash
docker-compose exec ksef-monitor python3 -c "
from app import ConfigManager, PushoverNotifier
config = ConfigManager('/data/config.json')
notifier = PushoverNotifier(config)
notifier.test_connection()
"
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
  "monitoring": {
    "subject_types": ["Subject1", "Subject2"],  // Invoice types to monitor
    "test_notification": false  // Send test on startup
  },
  "schedule": {
    "mode": "minutes",          // Scheduling mode
    "interval": 5               // Check every 5 minutes
  }
}
```

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

Secrets are in `.env` (or Docker secrets):
```bash
KSEF_TOKEN=...
PUSHOVER_USER_KEY=...
PUSHOVER_API_TOKEN=...
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
1. Check Pushover credentials in `.env`
2. Verify Pushover app installed on device
3. Check logs: `docker-compose logs -f`
4. Test connection (see Testing section above)

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
See [IDE_TROUBLESHOOTING.md](IDE_TROUBLESHOOTING.md)

This is just an IDE issue - the code runs fine!

## File Structure

```
ksef-invoice-monitor/
├── main.py                    # Entry point
├── app/                       # Application modules
│   ├── __init__.py
│   ├── secrets_manager.py
│   ├── config_manager.py
│   ├── ksef_client.py
│   ├── pushover_notifier.py
│   ├── invoice_monitor.py
│   └── scheduler.py           # Flexible scheduling system
├── config.json                # Configuration (git-ignored)
├── .env                       # Secrets (git-ignored)
├── docker-compose.yml         # Docker Compose config
├── Dockerfile                 # Docker image
└── data/                      # Persistent data (auto-created)
    └── last_check.json        # State file
```

## Next Steps

1. **Read the docs:**
   - [README.md](README.md) - Full documentation
   - [SECURITY.md](SECURITY.md) - Security best practices
   - [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) - Architecture details

2. **Customize:**
   - Change check interval
   - Modify notification format
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

For detailed documentation, see [README.md](README.md)
