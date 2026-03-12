# Notification Channels Guide

KSeF Monitor v0.5 supports multiple notification channels with **customizable Jinja2 templates**. You can enable one or more channels simultaneously to receive invoice notifications through your preferred platform(s).

> **New in v0.5:** iOS Push notifications — natywne powiadomienia na iPhone/iPad przez aplikację Monitor KSeF. See [iOS Push section](#6-ios-push--monitor-ksef-v05).

> **New in v0.3:** Notification format is now fully customizable through Jinja2 templates. See [TEMPLATES.md](TEMPLATES.md) for details.

## Supported Channels

| Channel | Best For | Requirements | Setup Time |
|---------|----------|--------------|------------|
| **Pushover** | Mobile notifications | User Key + API Token | 2 min |
| **Discord** | Team collaboration | Webhook URL | 1 min |
| **Slack** | Enterprise teams | Webhook URL | 2 min |
| **Email** | Email-based workflows | SMTP credentials | 3 min |
| **Webhook** | Custom integrations | HTTP endpoint | 1 min |
| **iOS Push** | Natywne powiadomienia iOS | Aplikacja Monitor KSeF | 1 min |

---

## Configuration Structure

All notification channels are configured under the `notifications` section in `config.json`:

```json
{
  "notifications": {
    "channels": ["pushover", "discord"],
    "message_priority": 0,
    "test_notification": true,
    "templates_dir": "/data/templates",
    "pushover": { ... },
    "discord": { ... },
    "slack": { ... },
    "email": { ... },
    "webhook": { ... },
    "ios_push": { ... }
  }
}
```

**Key Fields:**
- `channels`: Array of enabled channels (choose 1-6)
- `message_priority`: Default priority for all channels (-2 to 2)
- `test_notification`: Send test notification on startup
- `templates_dir`: Optional path to custom Jinja2 templates (overrides built-in defaults). See [TEMPLATES.md](TEMPLATES.md)

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

### Setup — krok po kroku

**Wymagania:** Musisz mieć uprawnienia **Manage Webhooks** na serwerze Discord (administrator lub odpowiednia rola).

1. **Otwórz ustawienia serwera**
   - Kliknij nazwę serwera w lewym górnym rogu
   - Wybierz **Server Settings** (Ustawienia serwera)

2. **Przejdź do Integrations**
   - W menu po lewej kliknij **Integrations** (Integracje)
   - Kliknij **Webhooks** (lub **View Webhooks** jeśli już istnieją)

3. **Utwórz nowy webhook**
   - Kliknij **New Webhook** (Nowy Webhook)
   - Discord automatycznie utworzy webhook o losowej nazwie

4. **Skonfiguruj webhook**
   - **Nazwa:** Zmień na `KSeF Monitor` (lub inna dowolna)
   - **Avatar:** Możesz dodać własną ikonę (opcjonalnie)
   - **Channel:** Wybierz kanał docelowy dla powiadomień
     - Zalecenie: utwórz dedykowany kanał np. `#ksef-faktury`

5. **Skopiuj Webhook URL**
   - Kliknij przycisk **Copy Webhook URL**
   - URL ma format: `https://discord.com/api/webhooks/XXXXXXXXX/YYYYYYYYYYYY`
   - **Traktuj ten URL jak hasło** — każdy kto go posiada może pisać na kanale

6. **Zapisz zmiany** — kliknij **Save Changes**

**Weryfikacja — wyślij testową wiadomość:**
```bash
curl -H "Content-Type: application/json" \
  -d '{"content": "Test KSeF Monitor"}' \
  "https://discord.com/api/webhooks/TWOJ_WEBHOOK_URL"
```
Jeśli na kanale pojawi się wiadomość — webhook działa poprawnie.

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

### Setup — krok po kroku

**Wymagania:** Musisz mieć uprawnienia do instalowania aplikacji w workspace Slack (administrator lub odpowiednia rola).

#### Metoda 1: Slack App z Incoming Webhooks (zalecana)

1. **Utwórz aplikację Slack**
   - Przejdź do [api.slack.com/apps](https://api.slack.com/apps)
   - Kliknij **Create New App**
   - Wybierz **From scratch**
   - Podaj nazwę: `KSeF Monitor`
   - Wybierz workspace, w którym chcesz otrzymywać powiadomienia
   - Kliknij **Create App**

2. **Włącz Incoming Webhooks**
   - W menu po lewej kliknij **Incoming Webhooks**
   - Przełącz **Activate Incoming Webhooks** na **On**

3. **Dodaj webhook do kanału**
   - Na dole strony kliknij **Add New Webhook to Workspace**
   - Wybierz kanał docelowy (np. `#ksef-faktury`)
   - Kliknij **Allow** (Zezwól)
   - Zalecenie: utwórz dedykowany kanał dla powiadomień KSeF

4. **Skopiuj Webhook URL**
   - Po autoryzacji pojawi się nowy webhook na liście
   - Kliknij **Copy** obok Webhook URL
   - URL ma format: `https://hooks.slack.com/services/TXXXXX/BXXXXX/XXXXXXXX`
   - **Traktuj ten URL jak hasło** — każdy kto go posiada może pisać na kanale

#### Metoda 2: Legacy Incoming Webhooks (prostsza, ale deprecated)

1. Przejdź do [slack.com/apps](https://slack.com/apps) i wyszukaj **Incoming WebHooks**
2. Kliknij **Add to Slack**
3. Wybierz kanał i kliknij **Add Incoming WebHooks Integration**
4. Skopiuj **Webhook URL**

> **Uwaga:** Metoda 2 jest deprecated przez Slack. Zalecana jest Metoda 1.

**Weryfikacja — wyślij testową wiadomość:**
```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"text": "Test KSeF Monitor"}' \
  "https://hooks.slack.com/services/TWOJ_WEBHOOK_URL"
```
Odpowiedź `ok` i wiadomość na kanale oznacza, że webhook działa poprawnie.

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
  "message": "Do: ACME Corp - NIP 1234567890\nNr Faktury: FV/2026/01/001\nData: 2026-02-20\nBrutto: 1 234,56 PLN\nNumer KSeF: 1234567890-20260220-ABCDEF-AB",
  "priority": 0,
  "priority_name": "normal",
  "timestamp": "2026-02-20T10:30:00",
  "source": "ksef-monitor",
  "invoice": {
    "ksef_number": "1234567890-20260220-ABCDEF-AB",
    "invoice_number": "FV/2026/01/001",
    "issue_date": "2026-02-20T10:30:00",
    "gross_amount": 1234.56,
    "net_amount": 1003.71,
    "vat_amount": 230.85,
    "currency": "PLN",
    "seller_name": "Firma ABC Sp. z o.o.",
    "seller_nip": "1234567890",
    "buyer_name": "ACME Corp S.A.",
    "buyer_nip": "0987654321",
    "subject_type": "Subject1"
  },
  "url": "https://ksef.mf.gov.pl/..."
}
```

> **Uwaga:** Format payloadu jest konfigurowalny przez szablon `webhook.json.j2`. Szczegóły: [TEMPLATES.md](TEMPLATES.md)

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

## 6. iOS Push — Monitor KSeF (v0.5)

Natywne push notifications na iPhone/iPad przez aplikację **Monitor KSeF**.

### Jak to działa

```
Docker (KSeF Monitor)  →  Cloudflare Worker  →  Apple Push (APNs)  →  iPhone
      POST /push/send       push.monitorksef.com       aps envelope         Monitor KSeF app
    X-Instance-Id/Key
```

- KSeF Monitor **nie komunikuje się bezpośrednio z Apple** — tylko z Worker
- Worker przechowuje klucz APNs (.p8) — nigdy nie opuszcza Worker
- Autentykacja: `X-Instance-Id` + `X-Instance-Key` (nie Bearer token)
- Payload: `{title, body, data}` — Worker buduje envelope `aps` sam

### Parowanie Docker ↔ iOS — krok po kroku

#### Wymagania
- KSeF Monitor v0.5+ z włączonym REST API (`api.enabled: true`)
- Aplikacja **Monitor KSeF** zainstalowana na iPhone/iPad
- Docker i iPhone w tej samej sieci (lub dostęp do API z zewnątrz)

#### Krok 1: Włącz kanał `ios_push` w konfiguracji

```json
{
  "notifications": {
    "channels": ["ios_push"],
    "ios_push": {
      "worker_url": "https://push.monitorksef.com",
      "timeout": 15
    }
  },
  "api": {
    "enabled": true,
    "port": 8080
  }
}
```

> **Uwaga:** `instance_id` i `instance_key` zostaną **wygenerowane automatycznie** przy pierwszym uruchomieniu przez PushManager. Nie musisz ich podawać ręcznie.

#### Krok 2: Uruchom KSeF Monitor

```bash
docker-compose up -d
```

Przy pierwszym uruchomieniu PushManager:
1. Generuje `instance_id` (UUID), `instance_key` (32 bajty random), `pairing_code` (8 znaków hex)
2. Rejestruje instancję w Worker (`POST /instances/register`) — wysyła tylko **hashe SHA-256**, nigdy plaintext
3. Zapisuje credentials w bazie SQLite (`push_instances` table)

W logach Docker zobaczysz **kod parowania i QR code** — wyświetlane **tylko raz**, przy pierwszym uruchomieniu:

```
╔══════════════════════════════════════════════════════╗
║           iOS Push — pairing code                   ║
║                                                      ║
║   Code:  A1B2C3D4                                   ║
║                                                      ║
║   Scan QR with Monitor KSeF app:                    ║
║    ▄▄▄▄▄▄▄  ▄▄▄  ▄▄▄▄▄▄▄                             ║
║    █ ▄▄▄ █ ▀▄▀ ▀ █ ▄▄▄ █                             ║
║    █ ███ █ ▄█ ██ █ ███ █                             ║
║    ...                                               ║
║                                                      ║
║   Or enter code manually in app:                    ║
║   Settings → Add instance → Enter code              ║
╚══════════════════════════════════════════════════════╝
```

> **Ważne:** QR code i kod parowania wyświetlają się w logach **tylko przy pierwszej generacji credentials**. Przy kolejnych restartach kontenera kod nie jest powtarzany (credentials są ładowane z bazy danych).

**Jeśli przegapiłeś kod lub potrzebujesz go ponownie:**

1. **Użyj REST API** — pobierz aktualny kod i QR:
   ```
   GET http://<docker-host>:8080/api/v1/push/setup
   ```
   Zwróci `pairing_code` i `qr_data_uri` (base64 PNG) — dostępne zawsze, nie tylko przy pierwszym uruchomieniu.

2. **Zresetuj credentials przez API** — generuje nowy `instance_id`, klucz i kod parowania:
   ```bash
   curl -X POST http://<docker-host>:8080/api/v1/push/reset \
     -H "Authorization: Bearer <your-token>"
   ```
   Nowy QR code pojawi się w logach Docker. Zwróci też `pairing_code` i `qr_data_uri` w odpowiedzi.

3. **Usuń rekord z bazy** — wymusi ponowną generację przy restarcie:
   ```bash
   docker-compose exec ksef-monitor python -c "
   from app.database import Database, PushInstance
   db = Database('/data/invoices.db')
   s = db.get_session()
   s.query(PushInstance).delete()
   s.commit()
   "
   docker-compose restart ksef-monitor
   ```

> **Uwaga:** Reset generuje **nowe credentials** — stary `pairing_code` przestaje działać. Istniejące sparowane urządzenia zostaną rozłączone i trzeba je sparować ponownie.

#### Krok 3: Zeskanuj QR code w aplikacji Monitor KSeF

1. Otwórz aplikację **Monitor KSeF** na iPhonie
2. Przejdź do **Ustawienia** → **Dodaj instancję**
3. Zeskanuj QR code z logów Docker lub z odpowiedzi API
4. Aplikacja odczyta kod `MKSEF:A1B2C3D4` i sparuje się z Twoim Docker

QR code zawiera: `MKSEF:{pairing_code}` — prefix `MKSEF:` identyfikuje kod jako parowanie Monitor KSeF.

#### Krok 4 (alternatywa): Ręczne parowanie

Jeśli skanowanie QR nie jest możliwe:

1. Skopiuj `pairing_code` z logów Docker lub z odpowiedzi API (np. `A1B2C3D4`)
2. W aplikacji Monitor KSeF → **Ustawienia** → **Dodaj instancję** → **Wpisz kod ręcznie**
3. Wprowadź 8-znakowy kod

#### Krok 5: Gotowe!

Po sparowaniu każda nowa faktura wykryta w KSeF wyśle natywny push na Twój iPhone:
- **Tytuł**: "Nowa faktura sprzedażowa w KSeF" (lub zakupowa)
- **Treść**: kontrahent, NIP, kwota brutto
- **Dane**: numer KSeF, numer faktury, kwoty, waluta

### Regeneracja kodu parowania

Jeśli chcesz sparować nowe urządzenie lub unieważnić stary kod:

```
POST http://<docker-host>:8080/api/v1/push/regenerate
```

Stary `pairing_code` przestaje działać, generowany jest nowy. Istniejące sparowane urządzenia **nie są rozłączane** — regeneracja dotyczy tylko nowych parowań.

### Configuration

```json
"ios_push": {
  "worker_url": "https://push.monitorksef.com",
  "timeout": 15
}
```

| Pole | Opis | Domyślnie |
|------|------|-----------|
| `worker_url` | URL Central Push Service | `https://push.monitorksef.com` |
| `timeout` | Timeout HTTP w sekundach | `15` |
| `instance_id` | UUID instancji (auto-generowany) | — |
| `instance_key` | Klucz instancji (auto-generowany) | — |

**Secret (opcjonalnie):**
```bash
# Jeśli chcesz podać klucz instancji ręcznie zamiast auto-generacji:
IOS_PUSH_INSTANCE_KEY=your-instance-key

# Docker secret
echo "your-instance-key" | docker secret create ios_push_instance_key -
```

### Bezpieczeństwo

- `instance_key` **nigdy nie jest logowany** — tylko `instance_id` pojawia się w logach
- Credentials w bazie SQLite (`push_instances` table) — nie w pliku tekstowym
- Worker przechowuje tylko **hashe SHA-256** klucza i kodu parowania
- Komunikacja Docker → Worker po HTTPS z walidacją certyfikatu
- `allow_redirects=False` — ochrona przed SSRF
- Klucz APNs (.p8) **nigdy nie opuszcza Worker**

### Features
- Natywne push notifications na iOS (APNs)
- Automatyczna generacja credentials przy pierwszym uruchomieniu
- Parowanie przez QR code lub ręczne wpisanie kodu
- Rich notifications z danymi faktury (numer, kwota, kontrahent)
- Regeneracja kodu parowania bez rozłączania istniejących urządzeń
- Obsługa wielu urządzeń iOS sparowanych z jedną instancją Docker

### Troubleshooting

**Brak powiadomień po sparowaniu:**
- Sprawdź czy `ios_push` jest w tablicy `channels`
- Sprawdź logi: `Push sent: X delivered, Y failed`
- Upewnij się że iPhone ma włączone powiadomienia dla Monitor KSeF

**Endpoint `/push/setup` zwraca 503:**
- API nie jest włączone lub PushManager nie zainicjalizowany
- Sprawdź `"api": {"enabled": true}` w konfiguracji

**Rejestracja w Worker nie powiodła się:**
- Sprawdź połączenie z `push.monitorksef.com`
- Logi: `Failed to register with Central Push Service`
- Przy kolejnym uruchomieniu Docker spróbuje ponownie

**QR code nie skanuje się:**
- Upewnij się że wyświetlasz pełny obraz (nie przycięty)
- Spróbuj ręcznego parowania kodem `pairing_code`

---

## Custom Templates (v0.3)

Notification format is customizable through Jinja2 templates. Each channel has its own template file:

| Channel | Template | Format |
|---------|----------|--------|
| Pushover | `pushover.txt.j2` | Plain text |
| Email | `email.html.j2` | HTML |
| Slack | `slack.json.j2` | Block Kit JSON |
| Discord | `discord.json.j2` | Embed JSON |
| Webhook | `webhook.json.j2` | Payload JSON |
| iOS Push | `ios_push.json.j2` | Push JSON |

### Quick Start

1. Skopiuj wbudowane szablony do katalogu templates:
   ```bash
   mkdir -p templates
   cp app/templates/*.j2 templates/
   ```

2. Dodaj `templates_dir` do konfiguracji:
   ```json
   {
     "notifications": {
       "templates_dir": "/data/templates"
     }
   }
   ```

3. Odmontuj katalog w Docker:
   ```yaml
   volumes:
     - ./templates:/data/templates:ro
   ```

4. Edytuj szablony według potrzeb.

Pełna dokumentacja szablonów: **[TEMPLATES.md](TEMPLATES.md)** — zmienne, filtry, przykłady modyfikacji, mini-przewodnik Jinja2.

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
IOS_PUSH_INSTANCE_KEY=your-instance-key

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
echo "your-instance-key" | docker secret create ios_push_instance_key -

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
config = ConfigManager('/config/config.json')
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

Your old config automatically migrates to multi-channel format:

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
- 🎨 [TEMPLATES](TEMPLATES.md) - Custom notification templates
- 🔒 [SECURITY](SECURITY.md) - Security best practices
- 🏗️ [PROJECT_STRUCTURE](PROJECT_STRUCTURE.md) - Architecture

For issues: Check logs with `docker-compose logs -f`
