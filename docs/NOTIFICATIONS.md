# Notification Channels Guide

KSeF Monitor v0.2 supports multiple notification channels. You can enable one or more channels simultaneously to receive invoice notifications through your preferred platform(s).

## Supported Channels

| Channel | Best For | Requirements | Setup Time |
|---------|----------|--------------|------------|
| **Pushover** | Mobile notifications | User Key + API Token | 2 min |
| **Discord** | Team collaboration | Webhook URL | 1 min |
| **Slack** | Enterprise teams | Webhook URL | 2 min |
| **Email** | Email-based workflows | SMTP credentials | 3 min |
| **Webhook** | Custom integrations | HTTP endpoint | 1 min |

---

## Configuration Structure

All notification channels are configured under the `notifications` section in `config.json`:

```json
{
  "notifications": {
    "channels": ["pushover", "discord"],
    "message_priority": 0,
    "test_notification": true,
    "pushover": { ... },
    "discord": { ... },
    "slack": { ... },
    "email": { ... },
    "webhook": { ... }
  }
}
```

**Key Fields:**
- `channels`: Array of enabled channels (choose 1-5)
- `message_priority`: Default priority for all channels (-2 to 2)
- `test_notification`: Send test notification on startup

---

## 1. Pushover (Mobile Notifications)

Perfect for personal mobile notifications on iOS/Android.

### Setup

1. Create account at [pushover.net](https://pushover.net/)
2. Copy your **User Key** from dashboard
3. Create an application and copy the **API Token**
4. Install Pushover app on your device

### Configuration

```json
"pushover": {
  "user_key": "your-user-key",
  "api_token": "your-api-token"
}
```

**Secrets (recommended):**
```bash
# Environment variables
PUSHOVER_USER_KEY=your-user-key
PUSHOVER_API_TOKEN=your-api-token

# Docker secrets
echo "your-user-key" | docker secret create pushover_user_key -
echo "your-api-token" | docker secret create pushover_api_token -
```

### Features
- ✅ Instant mobile push notifications
- ✅ Rich notification with invoice details
- ✅ Priority levels (quiet to emergency)
- ✅ Sound customization
- ✅ Direct link to KSeF portal

---

## 2. Discord (Team Collaboration)

Great for team channels and development servers.

### Setup

1. Open Discord server settings
2. Go to **Integrations** → **Webhooks**
3. Click **New Webhook**
4. Customize name/icon, select channel
5. Copy **Webhook URL**

### Configuration

```json
"discord": {
  "webhook_url": "https://discord.com/api/webhooks/...",
  "username": "KSeF Monitor",
  "avatar_url": ""
}
```

**Secret (recommended):**
```bash
# Environment variable
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Docker secret
echo "https://discord.com/api/webhooks/..." | docker secret create discord_webhook_url -
```

### Features
- ✅ Rich embeds with color coding
- ✅ Priority mapped to colors (red=high, blue=normal, gray=low)
- ✅ Timestamp for each notification
- ✅ Clickable links to KSeF
- ✅ No rate limits for webhooks

### Priority Colors
- `-2` / `-1` (Low): Gray embed
- `0` (Normal): Blue embed
- `1` (High): Orange embed
- `2` (Emergency): Red embed

---

## 3. Slack (Enterprise Teams)

Ideal for business teams using Slack.

### Setup

1. Go to [Slack App Directory](https://slack.com/apps)
2. Search for **Incoming Webhooks**
3. Click **Add to Slack**
4. Select channel and click **Add Incoming WebHooks integration**
5. Copy **Webhook URL**

### Configuration

```json
"slack": {
  "webhook_url": "https://hooks.slack.com/services/...",
  "username": "KSeF Monitor",
  "icon_emoji": ":receipt:"
}
```

**Secret (recommended):**
```bash
# Environment variable
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Docker secret
echo "https://hooks.slack.com/services/..." | docker secret create slack_webhook_url -
```

### Features
- ✅ Block Kit formatted messages
- ✅ Priority mapped to colors and emojis
- ✅ High priority messages mention @channel
- ✅ Emergency messages mention <!here>
- ✅ Clickable "View in KSeF" button

### Priority Formatting
- `-2` / `-1` (Low): 🔕 Gray message
- `0` (Normal): 📋 Green message
- `1` (High): ⚠️ Orange message
- `2` (Emergency): 🚨 Red message + @channel

---

## 4. Email (SMTP Notifications)

Universal option using any SMTP server.

### Setup - Gmail Example

1. Enable 2-factor authentication on your Google account
2. Go to [App Passwords](https://myaccount.google.com/apppasswords)
3. Generate app password for "Mail"
4. Copy the 16-character password

### Configuration

```json
"email": {
  "smtp_server": "smtp.gmail.com",
  "smtp_port": 587,
  "use_tls": true,
  "username": "your-email@gmail.com",
  "password": "your-app-password",
  "from_address": "ksef-monitor@yourdomain.com",
  "to_addresses": ["recipient1@example.com", "recipient2@example.com"]
}
```

**Secret (recommended):**
```bash
# Environment variable (password only)
EMAIL_PASSWORD=your-app-password

# Docker secret
echo "your-app-password" | docker secret create email_password -
```

### SMTP Server Settings

| Provider | SMTP Server | Port | TLS |
|----------|-------------|------|-----|
| Gmail | smtp.gmail.com | 587 | ✅ |
| Outlook | smtp-mail.outlook.com | 587 | ✅ |
| Yahoo | smtp.mail.yahoo.com | 587 | ✅ |
| Custom | your-smtp-server.com | 587/465 | ✅/❌ |

### Features
- ✅ HTML formatted emails with styling
- ✅ Plain text fallback
- ✅ Priority mapped to X-Priority header
- ✅ Color-coded priority badges
- ✅ Multiple recipients
- ✅ Clickable "View in KSeF" button

---

## 5. Webhook (Custom Integrations)

Generic HTTP endpoint for custom integrations (Zapier, n8n, custom APIs).

### Setup

1. Set up your HTTP endpoint to receive POST requests
2. Configure authentication if needed
3. Copy the endpoint URL

### Configuration

```json
"webhook": {
  "url": "https://your-server.com/webhook",
  "method": "POST",
  "headers": {
    "Authorization": "Bearer your-token",
    "Content-Type": "application/json"
  },
  "timeout": 10
}
```

**Secret (optional):**
```bash
# Environment variable (auto-injected into Authorization header)
WEBHOOK_TOKEN=your-token

# Docker secret
echo "your-token" | docker secret create webhook_token -
```

### Payload Format

```json
{
  "title": "Nowa faktura sprzedażowa w KSeF",
  "message": "Kontrahent: ACME Corp\nNumer: FV/2025/01/001\n...",
  "priority": 0,
  "priority_name": "normal",
  "timestamp": "2026-02-06T12:34:56.789Z",
  "source": "ksef-monitor",
  "url": "https://ksef.mf.gov.pl/..."
}
```

### Supported Methods
- `POST` - Most common (default)
- `PUT` - For update operations
- `GET` - Sends data as query parameters

### Features
- ✅ Fully customizable HTTP requests
- ✅ Custom headers support
- ✅ JSON payload
- ✅ Configurable timeout
- ✅ Works with Zapier, n8n, Make.com, etc.

---

## Multi-Channel Setup

You can enable multiple channels simultaneously. Notifications are sent to all enabled channels.

### Example: Pushover + Discord + Email

```json
{
  "notifications": {
    "channels": ["pushover", "discord", "email"],
    "message_priority": 0,
    "test_notification": true,
    "pushover": {
      "user_key": "...",
      "api_token": "..."
    },
    "discord": {
      "webhook_url": "...",
      "username": "KSeF Monitor"
    },
    "email": {
      "smtp_server": "smtp.gmail.com",
      "smtp_port": 587,
      "use_tls": true,
      "username": "...",
      "from_address": "...",
      "to_addresses": ["..."]
    }
  }
}
```

**How it works:**
1. New invoice detected
2. Notification sent to Pushover → Success ✅
3. Notification sent to Discord → Failed ❌ (logged, continues)
4. Notification sent to Email → Success ✅
5. Overall result: Success (2/3 channels succeeded)

---

## Priority Levels

All channels support 5 priority levels. Each channel displays them differently.

| Priority | Name | Pushover | Discord | Slack | Email | Webhook |
|----------|------|----------|---------|-------|-------|---------|
| `-2` | Lowest | No alert | Gray | 🔕 Gray | Priority 5 | "lowest" |
| `-1` | Low | Quiet | Gray | 💤 Gray | Priority 5 | "low" |
| `0` | Normal | Normal | Blue | 📋 Green | Priority 3 | "normal" |
| `1` | High | High | Orange | ⚠️ Orange + @channel | Priority 2 | "high" |
| `2` | Emergency | Emergency | Red | 🚨 Red + <!here> | Priority 1 | "urgent" |

**Set priority in config:**
```json
"notifications": {
  "message_priority": 1
}
```

---

## Secrets Management

Sensitive values (tokens, passwords, webhooks) can be provided in 3 ways:

### 1. Config File (Not Recommended)
```json
"pushover": {
  "user_key": "actual-key-here",
  "api_token": "actual-token-here"
}
```

### 2. Environment Variables (Recommended for Development)
```bash
# .env file
PUSHOVER_USER_KEY=your-user-key
PUSHOVER_API_TOKEN=your-api-token
DISCORD_WEBHOOK_URL=https://...
SLACK_WEBHOOK_URL=https://...
EMAIL_PASSWORD=your-password
WEBHOOK_TOKEN=your-token

# Set permissions
chmod 600 .env

# Use with Docker Compose
docker-compose -f docker-compose.env.yml up -d
```

### 3. Docker Secrets (Recommended for Production)
```bash
# Create secrets
echo "your-user-key" | docker secret create pushover_user_key -
echo "your-api-token" | docker secret create pushover_api_token -
echo "https://..." | docker secret create discord_webhook_url -
echo "https://..." | docker secret create slack_webhook_url -
echo "your-password" | docker secret create email_password -
echo "your-token" | docker secret create webhook_token -

# Deploy with secrets
docker stack deploy -c docker-compose.secrets.yml ksef
```

---

## Testing

### Test on Startup
```json
"notifications": {
  "test_notification": true
}
```

Sends test message to all enabled channels when monitor starts.

### Manual Test
```bash
# Docker
docker-compose exec ksef-monitor python3 -c "
from app.config_manager import ConfigManager
from app.notifiers import NotificationManager
config = ConfigManager('/data/config.json')
manager = NotificationManager(config)
manager.test_connection()
"

# Local
python3 -c "
from app.config_manager import ConfigManager
from app.notifiers import NotificationManager
config = ConfigManager('config.json')
manager = NotificationManager(config)
manager.test_connection()
"
```

---

## Troubleshooting

### No notifications received

**Check configuration:**
```bash
# View logs
docker-compose logs -f ksef-monitor

# Look for:
# ✓ Pushover notifier initialized
# ✓ Discord notifier initialized
# or
# ⚠ Discord enabled but not configured - skipping
```

**Common issues:**
- Channel listed in `channels` array but config section missing
- Secrets not loaded (check env vars or Docker secrets)
- Invalid webhook URLs
- Wrong SMTP credentials
- Network/firewall blocking outbound connections

### Channel fails silently

Each channel logs errors independently:
```
ERROR - Failed to send Discord notification: Connection timeout
ERROR - SMTP error sending email notification: Authentication failed
```

One channel failure doesn't stop others from working.

### Discord/Slack webhook not working

- Verify webhook URL is correct
- Check webhook hasn't been deleted
- Test webhook with curl:
```bash
curl -X POST "https://discord.com/api/webhooks/..." \
  -H "Content-Type: application/json" \
  -d '{"content": "Test message"}'
```

### Email not sending

- Verify SMTP credentials
- For Gmail: use App Password, not regular password
- Check port: 587 (TLS) or 465 (SSL)
- Verify `use_tls` setting matches port
- Check firewall allows outbound SMTP

---

## Migration from v0.1 (Pushover-only)

Your old config automatically migrates to v0.2 format:

**Old format (v0.1):**
```json
{
  "pushover": {
    "user_key": "...",
    "api_token": "..."
  },
  "monitoring": {
    "message_priority": 0,
    "test_notification": true
  }
}
```

**Migrated automatically to:**
```json
{
  "notifications": {
    "channels": ["pushover"],
    "message_priority": 0,
    "test_notification": true,
    "pushover": {
      "user_key": "...",
      "api_token": "..."
    }
  },
  "monitoring": {}
}
```

You'll see warnings in logs:
```
WARNING - Detected legacy Pushover-only configuration format
WARNING - Automatically migrating to new multi-channel notifications format
WARNING - Please update your config.json to use the 'notifications' section
```

Update your config manually to remove warnings.

---

## Best Practices

**Security:**
- ✅ Use environment variables or Docker secrets for production
- ✅ Never commit secrets to git
- ✅ Use `chmod 600 .env` to protect credentials
- ✅ Rotate tokens regularly
- ✅ Use separate webhooks for dev/staging/production

**Reliability:**
- ✅ Enable 2-3 channels for redundancy
- ✅ Use `test_notification: true` initially
- ✅ Monitor logs for failures
- ✅ Set appropriate priority levels

**Performance:**
- ✅ Webhooks (Discord/Slack) are fastest
- ✅ Email may have delays (SMTP)
- ✅ All channels send in parallel
- ✅ One slow channel doesn't block others

---

## Examples

### Personal Use (Mobile Only)
```json
{
  "notifications": {
    "channels": ["pushover"],
    "message_priority": 0,
    "pushover": { "user_key": "...", "api_token": "..." }
  }
}
```

### Team Collaboration
```json
{
  "notifications": {
    "channels": ["discord", "slack"],
    "message_priority": 1,
    "discord": { "webhook_url": "..." },
    "slack": { "webhook_url": "..." }
  }
}
```

### Enterprise Setup
```json
{
  "notifications": {
    "channels": ["email", "slack", "webhook"],
    "message_priority": 0,
    "email": {
      "smtp_server": "smtp.company.com",
      "username": "ksef@company.com",
      "to_addresses": ["finance@company.com", "accounting@company.com"]
    },
    "slack": { "webhook_url": "..." },
    "webhook": {
      "url": "https://company.com/api/ksef-webhook",
      "headers": { "Authorization": "Bearer ..." }
    }
  }
}
```

---

## FAQ

**Q: Can I use different priorities for different channels?**
A: Currently, all channels use the same priority. Custom per-channel priorities may be added in future versions.

**Q: How many email recipients can I add?**
A: No hard limit, but keep it reasonable (1-10 recipients). For more, consider a mailing list.

**Q: Can I use Gmail without App Password?**
A: No, Gmail requires 2FA + App Password for SMTP access.

**Q: Do webhooks retry on failure?**
A: No automatic retries. Failed notifications are logged. Next invoice check will send new notifications.

**Q: Can I add custom webhook headers?**
A: Yes! Use the `headers` object in webhook config.

**Q: Which channel is most reliable?**
A: Pushover (designed for reliability). Email depends on SMTP server. Webhooks depend on your endpoint uptime.

**Q: Can I disable notifications temporarily?**
A: Yes, set `"channels": []` or remove all channels from the array.

---

## Support

- 📖 [README](../README.md) - Main documentation
- 🚀 [QUICKSTART](QUICKSTART.md) - Setup guide
- 🔒 [SECURITY](SECURITY.md) - Security best practices
- 🏗️ [PROJECT_STRUCTURE](PROJECT_STRUCTURE.md) - Architecture

For issues: Check logs with `docker-compose logs -f`
