# KSeF Invoice Monitor v0.3

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

Monitor faktur w Krajowym Systemie e-Faktur (KSeF). Aplikacja cyklicznie pobiera metadata faktur z API KSeF v2 i wysyła powiadomienia o nowych fakturach sprzedażowych i/lub zakupowych przez **5 kanałów notyfikacji** z **konfigurowalnym systemem szablonów Jinja2**.

**Obsługiwane kanały:**
- 📱 **Pushover** - powiadomienia mobilne
- 💬 **Discord** - webhook z rich embeds
- 💼 **Slack** - webhook z Block Kit
- 📧 **Email** - SMTP z HTML formatowaniem
- 🔗 **Webhook** - generyczny HTTP endpoint

Bazuje na oficjalnej specyfikacji API: https://github.com/CIRFMF/ksef-docs

---

## Struktura projektu

```
ksef_monitor_v0_1/
├── main.py                      # Entry point — logging, signal handling, bootstrap
├── test_invoice_pdf.py          # Test script for PDF generation
├── app/                         # Application modules
│   ├── __init__.py
│   ├── config_manager.py        # Wczytanie i walidacja config.json
│   ├── secrets_manager.py       # Sekretne wartości z env / Docker secrets / config
│   ├── ksef_client.py           # Klient API KSeF v2 (autentykacja + zapytania)
│   ├── invoice_monitor.py       # Główna pętla monitorowania + kontekst szablonów
│   ├── invoice_pdf_generator.py # XML parser + PDF generator
│   ├── prometheus_metrics.py    # Prometheus metrics endpoint
│   ├── scheduler.py             # Elastyczny system schedulowania (5 trybów)
│   ├── template_renderer.py     # Silnik szablonów Jinja2 (v0.3)
│   ├── templates/               # Wbudowane szablony powiadomień (v0.3)
│   │   ├── pushover.txt.j2     # Plain text (Pushover)
│   │   ├── email.html.j2       # HTML (Email)
│   │   ├── slack.json.j2       # Block Kit JSON (Slack)
│   │   ├── discord.json.j2     # Embed JSON (Discord)
│   │   └── webhook.json.j2     # Payload JSON (Webhook)
│   └── notifiers/               # Multi-channel notification system
│       ├── __init__.py
│       ├── base_notifier.py     # Abstract base class + render_and_send()
│       ├── notification_manager.py  # Facade zarządzający wieloma kanałami
│       ├── pushover_notifier.py     # Powiadomienia mobilne Pushover
│       ├── discord_notifier.py      # Webhook Discord z rich embeds
│       ├── slack_notifier.py        # Webhook Slack z Block Kit
│       ├── email_notifier.py        # SMTP email z HTML
│       └── webhook_notifier.py      # Generyczny HTTP endpoint
├── docs/                        # Documentation
│   ├── QUICKSTART.md            # Quick start guide
│   ├── KSEF_TOKEN.md            # Tworzenie tokena KSeF (read-only)
│   ├── NOTIFICATIONS.md         # Konfiguracja powiadomień (5 kanałów)
│   ├── TEMPLATES.md             # Szablony Jinja2 — zmienne, filtry, przykłady (v0.3)
│   ├── SECURITY.md              # Security best practices
│   ├── TESTING.md               # Testing guide
│   ├── PDF_GENERATION.md        # Generowanie PDF faktur
│   ├── PROJECT_STRUCTURE.md     # Project architecture
│   ├── IDE_TROUBLESHOOTING.md   # IDE setup help
│   ├── ROADMAP.md               # Roadmap projektu
│   └── INDEX.md                 # Documentation index
├── examples/                    # Example configuration files
│   ├── config.example.json      # Configuration template
│   ├── config.secure.json       # Config for Docker secrets
│   └── .env.example             # Environment variables template
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Docker image definition
├── docker-compose.yml           # Basic Docker Compose setup
├── docker-compose.env.yml       # Docker Compose with .env
├── docker-compose.secrets.yml   # Docker Compose with secrets
├── LICENSE                      # MIT License
└── README.md                    # This file
```

Katalog `data/` powstaje w runtime i zawiera plik stanu `last_check.json`.

---

## Dokumentacja

- 📖 [QUICKSTART.md](docs/QUICKSTART.md) — Szybki start w 5 minut
- 🔑 [KSEF_TOKEN.md](docs/KSEF_TOKEN.md) — Tworzenie tokena KSeF (krok po kroku, uprawnienia read-only)
- 🔔 [NOTIFICATIONS.md](docs/NOTIFICATIONS.md) — Konfiguracja powiadomień (5 kanałów, tworzenie webhooków)
- 🎨 [TEMPLATES.md](docs/TEMPLATES.md) — Szablony Jinja2 powiadomień (zmienne, filtry, przykłady)
- 🔒 [SECURITY.md](docs/SECURITY.md) — Najlepsze praktyki bezpieczeństwa
- 🧪 [TESTING.md](docs/TESTING.md) — Przewodnik testowania
- 📄 [PDF_GENERATION.md](docs/PDF_GENERATION.md) — Generowanie PDF faktur
- 🏗️ [PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) — Architektura projektu
- 💻 [IDE_TROUBLESHOOTING.md](docs/IDE_TROUBLESHOOTING.md) — Pomoc z konfiguracją IDE
- 🗺️ [ROADMAP.md](docs/ROADMAP.md) — Roadmap projektu
- 📚 [INDEX.md](docs/INDEX.md) — Indeks dokumentacji

---

## Wymagania

- Python 3.9+ lub Docker
- Token autoryzacyjny z portalu KSeF (https://ksef.gov.pl)
- Co najmniej jeden kanał powiadomień (opcjonalnie — możesz wyłączyć wszystkie):
  - **Pushover** — User Key + API Token (https://pushover.net)
  - **Discord** — Webhook URL (https://discord.com)
  - **Slack** — Webhook URL (https://slack.com)
  - **Email** — Konto SMTP (Gmail, Outlook, własny serwer)
  - **Webhook** — Własny HTTP endpoint

### Zależności Python

| Pakiet | Wersja | Przeznaczenie |
|---|---|---|
| `requests` | 2.32.5 | HTTP calls do KSeF API i webhook notifiers |
| `python-dateutil` | 2.9.0 | Parsing dat w odpowiedziach API |
| `cryptography` | 46.0.5 | RSA-OAEP encryption tokena w auth flow |
| `pytz` | 2025.2 | Obsługa stref czasowych (timezone support) |
| `prometheus-client` | 0.23.1 | Eksport metryk Prometheus |
| `Jinja2` | 3.1.0+ | Silnik szablonów powiadomień (v0.3) |
| `reportlab` | 4.4.10 | Generowanie PDF faktur (włączane w sekcji `storage`) |
| `qrcode` | 8.2 | Generowanie QR Code Type I na fakturach PDF |

---

## Konfiguracja

Skopiuj `examples/config.example.json` do `config.json` i uzupełnij wartości.

### Sekcja `ksef`

| Pole | Opis |
|---|---|
| `environment` | `test` \| `demo` \| `prod` — wyznacza base URL API (patrz tabelka poniżej). |
| `nip` | 10-cyfrowy NIP podmiotu. |
| `token` | Token autoryzacyjny z portalu KSeF — **wyłącznie z uprawnieniami do przeglądania faktur** (read-only). Może być podany tu lub przez env variable / Docker secret (patrz [Sekretne wartości](#sekretne-wartości)). Przewodnik tworzenia: [KSEF_TOKEN.md](docs/KSEF_TOKEN.md) |

Base URLs przypisane automatycznie:

| Środowisko | URL |
|---|---|
| `prod` | `https://api.ksef.mf.gov.pl` |
| `demo` | `https://api-demo.ksef.mf.gov.pl` |
| `test` | `https://api-test.ksef.mf.gov.pl` |

### Sekcja `notifications`

System powiadomień obsługuje **5 kanałów** jednocześnie. Możesz włączyć jeden lub wiele.

| Pole | Opis |
|---|---|
| `channels` | Lista włączonych kanałów: `["pushover", "discord", "slack", "email", "webhook"]` |
| `message_priority` | Priority dla nowych faktur. `-2` cisza \| `-1` cicho \| `0` normalne \| `1` wysoka \| `2` pilne (Pushover). |
| `test_notification` | `true` wysyła testowe powiadomienie przy starcie. |
| `templates_dir` | Opcjonalny katalog z własnymi szablonami Jinja2 (nadpisują wbudowane). Domyślnie: brak (wbudowane szablony). Szczegóły: [TEMPLATES.md](docs/TEMPLATES.md) |

**Konfiguracja kanałów:**

<details>
<summary><b>Pushover</b> — Powiadomienia mobilne</summary>

```json
"pushover": {
  "user_key": "twoj-user-key",
  "api_token": "twoj-api-token"
}
```

- `user_key` — User Key z konta Pushover
- `api_token` — API Token aplikacji w Pushover
- Pobierz z: https://pushover.net
</details>

<details>
<summary><b>Discord</b> — Webhook z rich embeds</summary>

```json
"discord": {
  "webhook_url": "https://discord.com/api/webhooks/...",
  "username": "KSeF Monitor",
  "avatar_url": "https://example.com/avatar.png"
}
```

- `webhook_url` — **Wymagane.** Webhook URL z serwera Discord
- `username` — Opcjonalne. Nazwa bota (default: "KSeF Monitor")
- `avatar_url` — Opcjonalne. Avatar bota
- Jak utworzyć: Server Settings → Integrations → Webhooks → New Webhook
</details>

<details>
<summary><b>Slack</b> — Webhook z Block Kit</summary>

```json
"slack": {
  "webhook_url": "https://hooks.slack.com/services/...",
  "username": "KSeF Monitor",
  "icon_emoji": ":receipt:"
}
```

- `webhook_url` — **Wymagane.** Incoming Webhook URL
- `username` — Opcjonalne. Nazwa bota (default: "KSeF Monitor")
- `icon_emoji` — Opcjonalne. Emoji ikony (np. `:receipt:`, `:bell:`)
- Jak utworzyć: https://api.slack.com/messaging/webhooks
</details>

<details>
<summary><b>Email</b> — SMTP z HTML formatowaniem</summary>

```json
"email": {
  "smtp_server": "smtp.gmail.com",
  "smtp_port": 587,
  "use_tls": true,
  "username": "twoj-email@gmail.com",
  "password": "twoje-haslo-aplikacji",
  "from_address": "KSeF Monitor <twoj-email@gmail.com>",
  "to_addresses": ["email1@example.com", "email2@example.com"]
}
```

- `smtp_server` — Adres serwera SMTP
- `smtp_port` — Port (587 dla TLS, 465 dla SSL, 25 dla plain)
- `use_tls` — `true` dla STARTTLS (Gmail, Outlook)
- `username` — Login SMTP
- `password` — Hasło SMTP (dla Gmail: App Password)
- `from_address` — Adres nadawcy
- `to_addresses` — Lista adresów odbiorców

**Gmail App Password:** https://myaccount.google.com/apppasswords
</details>

<details>
<summary><b>Webhook</b> — Generyczny HTTP endpoint</summary>

```json
"webhook": {
  "url": "https://example.com/webhook",
  "method": "POST",
  "headers": {
    "Authorization": "Bearer token123",
    "Content-Type": "application/json"
  },
  "timeout": 10
}
```

- `url` — **Wymagane.** URL endpointu
- `method` — HTTP metoda: `POST`, `PUT`, `GET` (default: `POST`)
- `headers` — Opcjonalne. Dodatkowe nagłówki
- `timeout` — Timeout w sekundach (default: 10)

**Payload JSON:**
```json
{
  "title": "Nowa faktura sprzedażowa w KSeF",
  "message": "Do: Firma ABC - NIP 1234567890\n...",
  "priority": 0,
  "timestamp": "2026-02-06T10:30:00Z",
  "url": null
}
```
</details>

**Przykładowa konfiguracja (3 kanały włączone):**

```json
{
  "notifications": {
    "channels": ["pushover", "discord", "email"],
    "message_priority": 0,
    "test_notification": false,
    "pushover": {
      "user_key": "abc123...",
      "api_token": "xyz789..."
    },
    "discord": {
      "webhook_url": "https://discord.com/api/webhooks/..."
    },
    "email": {
      "smtp_server": "smtp.gmail.com",
      "smtp_port": 587,
      "use_tls": true,
      "username": "monitor@example.com",
      "password": "app-password-here",
      "from_address": "KSeF Monitor <monitor@example.com>",
      "to_addresses": ["admin@example.com"]
    }
  }
}
```

Pełna dokumentacja: [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md)
Szablony powiadomień: [docs/TEMPLATES.md](docs/TEMPLATES.md)

### Sekcja `monitoring`

| Pole | Default | Opis |
|---|---|---|
| `subject_types` | `["Subject1", "Subject2"]` | Typy faktur do monitorowania. `Subject1` = sprzedażowe (Ty = sprzedawca), `Subject2` = zakupowe (Ty = nabywca). Jedno zapytanie API na każdy typ. |
| `date_type` | `"Invoicing"` | Typ daty w zakresie zapytania. Dozwolone wartości: `Issue` (data wystawienia), `Invoicing` (data przyjęcia w KSeF), `PermanentStorage` (data trwałego zapisu). Fallback na `Invoicing` przy niepoprawnej wartości. |
| `timezone` | `"Europe/Warsaw"` | Strefa czasowa używana do wszystkich operacji z datami. Nazwa według standardu IANA (np. `Europe/Warsaw`, `America/New_York`). Zobacz [listę stref czasowych](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones). Fallback na `Europe/Warsaw` przy niepoprawnej wartości. |
| `message_priority` | `0` | Priority powiadomień Pushover dla nowych faktur. `-2` cisza \| `-1` cicho \| `0` normalne \| `1` wysoka \| `2` pilne (wymaga potwierdzenia). Fallback na `0`. |
| `test_notification` | `false` | Jeśli `true` — wysyła testowe powiadomienie przy starcie aplikacji. |

### Sekcja `schedule`

Elastyczny system schedulowania z 5 trybami:

| Tryb | Opis | Parametry |
|---|---|---|
| `simple` | Co X sekund (tryb kompatybilności wstecznej) | `interval`: liczba sekund |
| `minutes` | Co X minut | `interval`: liczba minut |
| `hourly` | Co X godzin | `interval`: liczba godzin |
| `daily` | O konkretnej godzinie/godzinach każdego dnia | `time`: `"HH:MM"` lub `["HH:MM", "HH:MM", ...]` |
| `weekly` | W konkretne dni tygodnia o konkretnej godzinie/godzinach | `days`: `["monday", "tuesday", ...]`<br>`time`: `"HH:MM"` lub `["HH:MM", ...]` |

**Przykłady konfiguracji:**

```json
// Co 5 minut
{"mode": "minutes", "interval": 5}

// Co 2 godziny
{"mode": "hourly", "interval": 2}

// Codziennie o 9:00
{"mode": "daily", "time": "09:00"}

// 3 razy dziennie: rano, po południu, wieczorem
{"mode": "daily", "time": ["09:00", "14:00", "18:00"]}

// W dni robocze o 9:00
{"mode": "weekly", "days": ["monday", "tuesday", "wednesday", "thursday", "friday"], "time": "09:00"}

// Poniedziałek, środa, piątek - 2 razy dziennie
{"mode": "weekly", "days": ["monday", "wednesday", "friday"], "time": ["08:00", "16:00"]}
```

**Uwaga:** Stary parametr `check_interval` w sekcji `monitoring` nadal działa dla kompatybilności wstecznej, ale zaleca się migrację do nowej sekcji `schedule`.

### Walidacja konfiguracji

Aplikacja automatycznie waliduje konfigurację przy starcie:

**Wymagania dla trybów interval-based (`simple`, `minutes`, `hourly`):**
- Pole `interval` musi być liczbą dodatnią

**Wymagania dla trybów time-based (`daily`, `weekly`):**
- Pole `time` jest wymagane (może być string lub array)
- Format czasu: `HH:MM` (godziny 0-23, minuty 0-59)
- Dla `weekly`: pole `days` jest wymagane (niepusta lista nazw dni tygodnia)

**Dozwolone nazwy dni:** `monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday`, `sunday`

**Przykłady błędów walidacji:**
```
❌ Missing required field 'interval' for schedule mode 'minutes'
❌ Missing required field 'time' for schedule mode 'daily'
❌ Invalid hour in '25:00'. Hour must be 0-23
❌ Field 'schedule.time' cannot be an empty list
❌ Invalid weekday: mondayy
```

### Sekcja `storage`

Konfiguracja zapisywania plików faktur (XML, PDF). Domyślnie wyłączone.

| Pole | Default | Opis |
|---|---|---|
| `save_xml` | `false` | Zapisuj pliki XML faktur (źródłowe dane z KSeF) oraz UPO (dla faktur sprzedażowych). |
| `save_pdf` | `false` | Generuj i zapisuj pliki PDF faktur (wymaga `reportlab`). |
| `output_dir` | `"/data/invoices"` | Katalog docelowy dla zapisanych plików. Tworzony automatycznie jeśli nie istnieje. |

**Przykład konfiguracji:**

```json
{
  "storage": {
    "save_xml": true,
    "save_pdf": true,
    "output_dir": "/data/invoices"
  }
}
```

**Nazewnictwo plików:**
```
sprz_<numer_ksef>_<data>.xml    — XML faktury sprzedażowej
sprz_<numer_ksef>_<data>.pdf    — PDF faktury sprzedażowej
zak_<numer_ksef>_<data>.xml     — XML faktury zakupowej
zak_<numer_ksef>_<data>.pdf     — PDF faktury zakupowej
UPO_sprz_<numer_ksef>_<data>.xml — UPO (tylko faktury sprzedażowe)
```

**Uwagi:**
- Jeśli oba flagi `save_xml` i `save_pdf` są `false`, żadne pliki nie są pobierane/generowane
- Generowanie PDF wymaga biblioteki `reportlab` (w `requirements.txt`)
- Katalog `output_dir` jest tworzony automatycznie przy pierwszym zapisie
- UPO (Urzędowe Poświadczenie Odbioru) zapisywane jest razem z XML (zależne od `save_xml`)

### Sekcja `prometheus`

Eksport metryk dla systemów monitorowania (Prometheus, Grafana, etc.)

| Pole | Default | Opis |
|---|---|---|
| `enabled` | `true` | Włącz/wyłącz endpoint metryk Prometheus |
| `port` | `8000` | Port HTTP dla endpointu `/metrics` |

**Dostępne metryki:**

| Metryka | Typ | Opis |
|---|---|---|
| `ksef_last_check_timestamp` | Gauge | Unix timestamp ostatniego sprawdzenia API KSeF (seconds since epoch) |
| `ksef_new_invoices_total{subject_type}` | Counter | Łączna liczba nowych faktur per `subject_type` (`Subject1`, `Subject2`) |
| `ksef_monitor_up` | Gauge | Status monitora: `1` = running, `0` = stopped |

**Przykład konfiguracji:**

```json
{
  "prometheus": {
    "enabled": true,
    "port": 8000
  }
}
```

**Dostęp do metryk:**
```bash
# Lokalnie
curl http://localhost:8000/metrics

# Z Docker (jeśli port jest zmapowany)
curl http://localhost:8000/metrics
```

**Przykładowy output:**
```
# HELP ksef_last_check_timestamp Unix timestamp of last KSeF API check
# TYPE ksef_last_check_timestamp gauge
ksef_last_check_timestamp 1675612345.0

# HELP ksef_new_invoices_total Total number of new invoices found
# TYPE ksef_new_invoices_total counter
ksef_new_invoices_total{subject_type="Subject1"} 5
ksef_new_invoices_total{subject_type="Subject2"} 3

# HELP ksef_monitor_up KSeF Monitor health status (1 = running, 0 = stopped)
# TYPE ksef_monitor_up gauge
ksef_monitor_up 1.0
```

**Integracja z Prometheus:**

Dodaj do `prometheus.yml`:
```yaml
scrape_configs:
  - job_name: 'ksef-monitor'
    static_configs:
      - targets: ['ksef-invoice-monitor:8000']
    scrape_interval: 30s
```

**Wyłączenie Prometheus:**

Jeśli nie używasz monitorowania, możesz wyłączyć endpoint:
```json
{
  "prometheus": {
    "enabled": false
  }
}
```

---

## Sekretne wartości

Wrażliwe dane mogą być dostarczone na trzy sposoby. Kolejność priorytetów od najwyższego:

1. **Zmienne środowiska** (`.env` file lub `docker-compose.env.yml`)
2. **Docker secrets** (pliki w `/run/secrets/` — dla Swarm)
3. **Config file** (wartość wpisana bezpośrednio w `config.json`)

| Wartość | Zmienne środowiska | Docker secret | Kanał |
|---|---|---|---|
| KSeF token | `KSEF_TOKEN` | `ksef_token` | — |
| Pushover User Key | `PUSHOVER_USER_KEY` | `pushover_user_key` | Pushover |
| Pushover API Token | `PUSHOVER_API_TOKEN` | `pushover_api_token` | Pushover |
| Discord Webhook URL | `DISCORD_WEBHOOK_URL` | `discord_webhook_url` | Discord |
| Slack Webhook URL | `SLACK_WEBHOOK_URL` | `slack_webhook_url` | Slack |
| Email Password | `EMAIL_PASSWORD` | `email_password` | Email |
| Webhook Token | `WEBHOOK_TOKEN` | `webhook_token` | Webhook |

**Uwaga:** Tylko sekrety dla włączonych kanałów są wymagane. Jeśli używasz tylko Discord, nie musisz podawać credentials dla Pushover, Email, etc.

**Przykład `.env` file:**
```bash
KSEF_TOKEN=your-ksef-token
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
EMAIL_PASSWORD=your-app-password
```

Więcej informacji: [docs/SECURITY.md](docs/SECURITY.md)

---

## Uruchomienie

### Lokalne (bez Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp examples/config.example.json config.json   # uzupełnij wartości
python main.py
```

### Docker — podstawowe

Sekretne wartości wpisane bezpośrednio w `config.json`. Najprostsze podejście do testowania.

```bash
cp examples/config.example.json config.json   # uzupełnij wszystkie wartości
docker compose -f docker-compose.yml up -d
```

### Docker — z plikiem .env

Sekretne wartości w osobnym pliku `.env`. Konfiguracja podzielona na `config.secure.json` (bez sekretów) i `.env` (sam sekrety).

```bash
cp examples/config.secure.json config.secure.json   # lub dostosuj ręcznie
cp examples/.env.example .env                       # uzupełnij KSEF_TOKEN, PUSHOVER_*
chmod 600 .env
docker compose -f docker-compose.env.yml up -d
```

### Docker Swarm — Docker secrets (produkcja)

Sekretne wartości przechowywane w Docker Swarm. Wymaga uruchomionego Swarm.

```bash
# Utworzenie sekretów (tylko dla kanałów których używasz)
echo "twoj-ksef-token"          | docker secret create ksef_token -
echo "twoj-pushover-user-key"   | docker secret create pushover_user_key -
echo "twoj-pushover-api-token"  | docker secret create pushover_api_token -
echo "https://discord.com/api/webhooks/..." | docker secret create discord_webhook_url -
echo "https://hooks.slack.com/services/..." | docker secret create slack_webhook_url -
echo "twoj-smtp-password"       | docker secret create email_password -
echo "twoj-webhook-token"       | docker secret create webhook_token -

# config.secure.json bez sekretów
cp examples/config.secure.json config.secure.json

# Deploy
docker swarm init   # jeśli jeszcze nie zrobione
docker compose -f docker-compose.secrets.yml up -d
```

**Uwaga:** Twórz tylko sekrety dla kanałów, które włączyłeś w `notifications.channels`.

### Zarządzanie kontenerem

```bash
docker logs ksef-invoice-monitor -f      # logs
docker restart ksef-invoice-monitor      # restart
docker stop ksef-invoice-monitor         # stop
```

---

## Przepływ autentykacji KSeF API v2

Autentykacja (metoda `KSeFClient.authenticate()`) składa się z 5 kroków:

```
1.  POST  /v2/auth/challenge
        → { challenge, timestampMs }

2.  GET   /v2/security/public-key-certificates
        → lista certyfikatów; filtr: usage zawiera "KsefTokenEncryption"
        → ekstrakcja klucza publicznego RSA z certyfikatu DER (base64)

3.  POST  /v2/auth/ksef-token
        payload: {
            challenge,
            contextIdentifier: { type: "nip", value: "<NIP>" },
            encryptedToken: base64( RSA-OAEP( "<token>|<timestampMs>" ) )
        }
        → { referenceNumber, authenticationToken: { token, validUntil } }

4.  GET   /v2/auth/{referenceNumber}
        header: Authorization: Bearer <authenticationToken.token>
        → polling co 2s, aż status.code == 200  (max 10 prób)

5.  POST  /v2/auth/token/redeem
        header: Authorization: Bearer <authenticationToken.token>
        body:   (puste)
        → { accessToken: { token, validUntil },
            refreshToken: { token, validUntil } }
```

Po uzyskaniu `accessToken` — używany do zapytań o faktury. Przy 401 na zapytanie — najpierw próba odświeżenia tokena (`POST /v2/auth/token/refresh` z `refreshToken` w Bearer), a jeśli to nie działa — pełna re-autentykacja od kroku 1.

### Parametry RSA-OAEP

| Parametr | Wartość |
|---|---|
| Algorithm | RSA-OAEP |
| Hash | SHA-256 |
| MGF | MGF1 (SHA-256) |
| Label | None |
| Plaintext | `<token>\|<timestampMs>` (UTF-8) |

---

## Zapytanie o faktury

Endpoint: `POST /v2/invoices/query/metadata`

- Jedno zapytanie na `subjectType` — iteracja po liście `subject_types` z konfiguracji.
- `dateType` pochodzi z pola `date_type` w konfiguracji.
- Daty w formacie ISO 8601 z sufixem `Z` (UTC).
- Wszystkie daty są konwertowane z skonfigurowanej strefy czasowej (`timezone`) do UTC przed wysłaniem do API.
- `pageSize: 100`, `pageOffset: 0`.

Przykładowy payload:

```json
{
  "subjectType": "Subject1",
  "dateRange": {
    "dateType": "Invoicing",
    "From": "2026-02-04T00:00:00.000Z",
    "To":   "2026-02-05T12:00:00.000Z"
  },
  "pageSize": 100,
  "pageOffset": 0
}
```

---

## Powiadomienia

### Tytuły — zależne od `subjectType`

Wszystkie kanały otrzymują te same tytuły:

| `subjectType` | Tytuł |
|---|---|
| `Subject1` | Nowa faktura sprzedażowa w KSeF |
| `Subject2` | Nowa faktura zakupowa w KSeF |
| inne | Nowa faktura w KSeF |

### Treść wiadomości — zależna od `subjectType`

**Subject1** (sprzedażowa — Ty = sprzedawca) — wyświetla się nabywca:

```
Do: <nazwa nabywcy> - NIP <NIP>
Nr Faktury: <numer faktury>
Data: <data wystawienia>
Brutto: 1 234,56 PLN
Numer KSeF: <numer KSeF>
```

**Subject2** (zakupowa — Ty = nabywca) — wyświetla się sprzedawca:

```
Od: <nazwa sprzedawcy> - NIP <NIP>
Nr Faktury: ...
Data: ...
Brutto: 1 234,56 PLN
Numer KSeF: ...
```

**Inne** — wyświetlają się oba:

```
Od: <sprzedawca> - NIP ...
Do: <nabywca>   - NIP ...
Nr Faktury: ...
Data: ...
Brutto: 1 234,56 PLN
Numer KSeF: ...
```

> **Uwaga:** Format powiadomień jest konfigurowalny przez szablony Jinja2. Szczegóły: [TEMPLATES.md](docs/TEMPLATES.md)

### Pozostałe powiadomienia

| Wydarzenie | Tytuł | Priority |
|---|---|---|
| Start aplikacji | KSeF Monitor Started | `-1` |
| Zatrzymanie | KSeF Monitor Stopped | `-1` |
| Błąd w pętli | KSeF Monitor Error | `1` |
| Test na starcie | KSeF Monitor Test | `0` |

### Priority mapping

Każdy kanał mapuje priority (`-2` do `2`) na własny format:

| Priority | Pushover | Discord | Slack | Email | Webhook |
|---|---|---|---|---|---|
| `-2` | Cisza | Kolor szary | Kolor szary | X-Priority: 5 | `priority: -2` |
| `-1` | Cicho | Kolor szary | Emoji `:bell:` | X-Priority: 5 | `priority: -1` |
| `0` | Normalne | Kolor niebieski | Emoji `:envelope:` | X-Priority: 3 | `priority: 0` |
| `1` | Wysoka | Kolor pomarańczowy | Emoji `:warning:` + `@channel` | X-Priority: 2 | `priority: 1` |
| `2` | Pilne (wymaga potwierdzenia) | Kolor czerwony | Emoji `:rotating_light:` + `<!here>` | X-Priority: 1 | `priority: 2` |

Więcej szczegółów: [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md)

---

## Stan aplikacji

Plik `data/last_check.json` przechowuje stan między restartami:

```json
{
  "last_check": "2026-02-05T12:00:00.123456",
  "seen_invoices": ["a1b2c3d4...", "..."]
}
```

- `last_check` — ISO 8601 timestamp ostatniego sprawdzenia. Kolejne zapytanie zacznie zakres od tej daty.
- `seen_invoices` — hashes MD5 (`ksefNumber_invoiceNumber`) faktur dla których powiadomienie wysłano. Max 1000 najnowszych pozycji.
- Przy pierwszym uruchomieniu (brak pliku lub brak `last_check`) zakres zapytania to ostatnie 24 godziny.

---

## Endpoints KSeF API

| Endpoint | Metoda | Przeznaczenie |
|---|---|---|
| `/v2/auth/challenge` | POST | Pobranie challenge |
| `/v2/security/public-key-certificates` | GET | Klucz publiczny RSA |
| `/v2/auth/ksef-token` | POST | Autentykacja z encrypted token |
| `/v2/auth/{referenceNumber}` | GET | Polling statusu auth |
| `/v2/auth/token/redeem` | POST | Uzyskanie access/refresh token |
| `/v2/auth/token/refresh` | POST | Odświżenie access tokena |
| `/v2/auth/sessions` | GET | Lista aktywnych sesji |
| `/v2/auth/sessions/current` | DELETE | Revoke sesji |
| `/v2/invoices/query/metadata` | POST | Zapytanie o metadata faktur |
| `/v2/invoices/ksef/{ksefNumber}` | GET | Pobranie XML faktury |

Dokumentacja API: https://api.ksef.mf.gov.pl/docs/v2/

---

## Generowanie PDF faktur

Moduł do pobierania XML faktur z KSeF i konwersji do PDF według oficjalnego wzoru KSeF.

**Włączenie** — ustaw w `config.json`:
```json
{"storage": {"save_pdf": true, "save_xml": true}}
```

### Funkcjonalność

- ✅ Pobieranie XML faktury po numerze KSeF (endpoint `GET /v2/invoices/ksef/{ksefNumber}`)
- ✅ Parser XML faktury FA_VAT (wszystkie główne sekcje)
- ✅ Generator PDF według oficjalnego wzoru KSeF (XSD/XSL)
- ✅ QR Code Type I (weryfikacja faktury)
- ✅ Polskie znaki diakrytyczne (DejaVu Sans / Arial)
- ✅ Stopka z datą generowania i strefą czasową
- ✅ Automatyczny zapis PDF/XML dla nowych faktur (sekcja `storage`)
- ✅ Skrypt testowy do manualnego generowania PDF

### Użycie - Skrypt testowy

```bash
# Podstawowe użycie - pobierz XML i wygeneruj PDF
python test_invoice_pdf.py <numer-ksef>

# Przykład
python test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB

# Z własną nazwą pliku
python test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB -o moja_faktura.pdf

# Tylko XML (bez PDF)
python test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB --xml-only

# Debug mode
python test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB --debug
```

### Użycie programatyczne

```python
from app.config_manager import ConfigManager
from app.ksef_client import KSeFClient
from app.invoice_pdf_generator import generate_invoice_pdf

# Załaduj config i zaloguj się
config = ConfigManager('config.json')
client = KSeFClient(config)
client.authenticate()

# Pobierz XML faktury
result = client.get_invoice_xml("1234567890-20240101-ABCDEF123456-AB")

if result:
    # Wygeneruj PDF
    pdf_buffer = generate_invoice_pdf(
        xml_content=result['xml_content'],
        ksef_number=result['ksef_number'],
        output_path="faktura.pdf"
    )
    print(f"PDF wygenerowany: faktura.pdf")
```

### Format PDF

Generator tworzy PDF według wzoru KSeF zawierający:
- ✅ Nagłówek z numerem faktury i datami
- ✅ Dane sprzedawcy i nabywcy (NIP, nazwa, adres)
- ✅ Tabelę pozycji faktury (ilość, cena, VAT)
- ✅ Podsumowanie kwot (netto, VAT, brutto)
- ✅ Informacje o płatności (termin, konto bankowe)
- ✅ Uwagi dodatkowe

### Pliki modułu

| Plik | Opis |
|------|------|
| `app/ksef_client.py` | Metoda `get_invoice_xml()` - pobieranie XML |
| `app/invoice_pdf_generator.py` | Parser XML + generator PDF |
| `test_invoice_pdf.py` | Skrypt testowy CLI |

### Walidacja numeru KSeF

Format numeru KSeF: `NIP-YYYYMMDD-RANDOM-XX`

Przykład: `1234567890-20240101-ABCDEF123456-AB`

- `NIP` - 10 cyfr
- `YYYYMMDD` - data (8 cyfr)
- `RANDOM` - identyfikator alfanumeryczny
- `XX` - sufiks (2 wielkie litery)

### Troubleshooting

**ImportError: No module named 'reportlab'**
```bash
pip install reportlab
```

**Authentication failed**
- Sprawdź poprawność tokenu KSeF w config.json
- Upewnij się, że token nie wygasł
- Zweryfikuj NIP w konfiguracji

**Failed to fetch invoice XML**
- Faktura nie istnieje lub nie masz do niej dostępu
- Sprawdź format numeru KSeF (użyj `--debug`)
- Zweryfikuj uprawnienia tokena

**Invalid KSeF number format**
```bash
# Poprawny format
python test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB

# Niepoprawne
python test_invoice_pdf.py 123456789020240101ABCDEF123456AB  # brak myślników
python test_invoice_pdf.py 12345-20240101-ABCDEF123456-AB     # NIP za krótki
```

### Przyszłe funkcje (planowane)

Funkcje które będą dodane w przyszłości:
- 🔜 Automatyczne pobieranie PDF dla nowych faktur
- 🔜 Katalog archiwum PDF (np. `invoices/2024/01/`)
- 🔜 Załączanie PDF do powiadomień email
- 🔜 Batch download - pobieranie wielu faktur naraz
- 🔜 CLI interaktywny do przeglądania i pobierania faktur
- 🔜 Konfiguracja w config.json (auto-download, katalog docelowy)
- 🔜 Metadane w PDF (QR kod KSeF, numer referencyjny)

---

## Troubleshooting

### Brak powiadomień

**1. Sprawdź które kanały są włączone:**
```bash
docker logs ksef-invoice-monitor | grep "Enabled channels"
# Powinno pokazać: Enabled channels: discord, email, pushover
```

**2. Jeśli żaden kanał nie jest włączony:**
- Sprawdź sekcję `notifications.channels` w `config.json`
- Upewnij się, że lista nie jest pusta: `"channels": ["pushover", "discord"]`
- Sprawdź czy nazwy kanałów są poprawne (lowercase)

**3. Problemy z konkretnymi kanałami:**

<details>
<summary><b>Pushover</b> - Brak powiadomień mobilnych</summary>

- Sprawdź poprawność `user_key` i `api_token` w `.env` lub `config.json`
- Upewnij się, że aplikacja Pushover jest zainstalowana na urządzeniu
- Zweryfikuj API Token w panelu [pushover.net](https://pushover.net/)
- Sprawdź logi: `docker logs ksef-invoice-monitor | grep -i pushover`
- Test manualny:
  ```bash
  curl -s \
    --form-string "token=YOUR_API_TOKEN" \
    --form-string "user=YOUR_USER_KEY" \
    --form-string "message=Test" \
    https://api.pushover.net/1/messages.json
  ```
</details>

<details>
<summary><b>Discord</b> - Brak wiadomości na serwerze</summary>

- Zweryfikuj `webhook_url` - musi zaczynać się od `https://discord.com/api/webhooks/`
- Sprawdź czy webhook nie został usunięty w Server Settings → Integrations
- Test webhook bezpośrednio:
  ```bash
  curl -H "Content-Type: application/json" \
    -d '{"content":"Test"}' \
    "YOUR_WEBHOOK_URL"
  ```
- Upewnij się, że bot ma uprawnienia do pisania na kanale
- Sprawdź logi: `docker logs ksef-invoice-monitor | grep -i discord`
</details>

<details>
<summary><b>Slack</b> - Brak wiadomości w workspace</summary>

- Zweryfikuj `webhook_url` - musi zaczynać się od `https://hooks.slack.com/services/`
- Sprawdź czy Incoming Webhook jest nadal aktywny w [api.slack.com](https://api.slack.com/apps)
- Test webhook bezpośrednio:
  ```bash
  curl -X POST \
    -H "Content-Type: application/json" \
    -d '{"text":"Test"}' \
    "YOUR_WEBHOOK_URL"
  ```
- Upewnij się, że aplikacja jest zainstalowana w workspace
- Sprawdź logi: `docker logs ksef-invoice-monitor | grep -i slack`
</details>

<details>
<summary><b>Email</b> - Brak emaili</summary>

- **Gmail:**
  - Użyj App Password, nie zwykłego hasła: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
  - Włącz 2FA przed utworzeniem App Password
  - SMTP: `smtp.gmail.com:587`, `use_tls: true`
- **Outlook:**
  - SMTP: `smtp-mail.outlook.com:587`, `use_tls: true`
  - Może wymagać App Password jeśli 2FA włączone
- **Inne:**
  - Sprawdź czy port SMTP jest otwarty (587 dla TLS, 465 dla SSL)
  - Zweryfikuj credentials SMTP u swojego providera
- Test SMTP:
  ```bash
  docker logs ksef-invoice-monitor | grep -i "smtp\|email"
  ```
- Sprawdź spam folder w skrzynce odbiorczej
</details>

<details>
<summary><b>Webhook</b> - Endpoint nie otrzymuje danych</summary>

- Sprawdź czy URL endpointu jest dostępny z kontenera Docker
- Zweryfikuj metodę HTTP (`POST`, `PUT`, `GET`)
- Sprawdź logi endpoint (jeśli masz do nich dostęp)
- Test endpoint bezpośrednio:
  ```bash
  curl -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer YOUR_TOKEN" \
    -d '{"title":"Test","message":"Test message"}' \
    "YOUR_WEBHOOK_URL"
  ```
- Dla localhost z Docker: użyj `host.docker.internal` zamiast `localhost`
- Sprawdź logi: `docker logs ksef-invoice-monitor | grep -i webhook`
</details>

**4. Włącz testowe powiadomienie:**
```json
{
  "notifications": {
    "test_notification": true
  }
}
```
Restart kontenera wyśle powiadomienie testowe na wszystkie włączone kanały.

**5. Sprawdź szczegółowe logi błędów:**
```bash
docker logs ksef-invoice-monitor -f | grep -i "error\|failed\|✗"
```

### Błędy autentykacji KSeF

**Token wygasł lub nieprawidłowy:**
- Zweryfikuj token w portalu KSeF — tokeny mają ograniczoną żywotność
- Wygeneruj nowy token i zaktualizuj w `.env` lub Docker secret
- Sprawdź logi: `docker logs ksef-invoice-monitor | grep -i "auth\|401\|403"`

**Nieprawidłowy NIP:**
- Format: dokładnie 10 cyfr, bez spacji, myślników, prefiksów
- Przykład poprawny: `"nip": "1234567890"`
- Przykład błędny: `"nip": "123-456-78-90"` lub `"nip": "PL1234567890"`

**Niezgodne środowisko:**
- Upewnij się, że `environment` w config odpowiada portalowi, z którego pochodzi token
- Token z `ksef-test.mf.gov.pl` → `"environment": "test"`
- Token z `ksef.mf.gov.pl` → `"environment": "prod"`

### Błędy konfiguracji

**Walidacja JSON:**
```bash
# Sprawdź poprawność składni
python3 -m json.tool config.json

# Jeśli błąd składni, pokaże linię problemu
cat config.json | jq .
```

**Brakujące wymagane pola:**
```bash
# Sprawdź logi przy starcie
docker logs ksef-invoice-monitor | grep -i "validation\|missing\|required"
```

**Nieprawidłowe wartości schedulera:**
```bash
# Sprawdź logi walidacji
docker logs ksef-invoice-monitor | grep -i "schedule\|invalid"
```

### Problemy z Docker

**Kontener nie startuje:**
```bash
# Sprawdź szczegółowe logi
docker logs ksef-invoice-monitor --tail=100

# Sprawdź czy kontener żyje
docker ps -a | grep ksef

# Sprawdź czy config.json istnieje i jest montowany
docker inspect ksef-invoice-monitor | grep -A 10 Mounts
```

**Brak dostępu do plików:**
```bash
# Sprawdź uprawnienia
ls -la config.json .env data/

# Powinny być:
# -rw------- .env (600)
# -rw-r--r-- config.json (644 jeśli bez sekretów)
# drwxr-xr-x data/ (755)
```

**Problem z secretami Docker:**
```bash
# Lista sekretów
docker secret ls

# Sprawdź czy sekrety są dostępne w kontenerze
docker exec ksef-invoice-monitor ls -la /run/secrets/

# Powinny być widoczne:
# -r-------- ksef_token
# -r-------- discord_webhook_url
# etc.
```

### Problemy z siecią

**Brak połączenia z KSeF API:**
```bash
# Test połączenia z kontenera
docker exec ksef-invoice-monitor curl -v https://api-test.ksef.mf.gov.pl/v2/health

# Sprawdź DNS
docker exec ksef-invoice-monitor nslookup api-test.ksef.mf.gov.pl
```

**Webhook/SMTP timeout:**
- Sprawdź ustawienie `timeout` w konfiguracji webhook
- Zweryfikuj czy firewall nie blokuje połączeń wychodzących
- Dla SMTP sprawdź czy porty 587/465 są otwarte

### Pomocne komendy diagnostyczne

```bash
# Pełne logi z timestampami
docker logs ksef-invoice-monitor --timestamps

# Tylko błędy
docker logs ksef-invoice-monitor 2>&1 | grep -i error

# Tail ostatnich 50 linii
docker logs ksef-invoice-monitor --tail=50

# Restart z czystymi logami
docker restart ksef-invoice-monitor && docker logs -f ksef-invoice-monitor

# Sprawdź wykorzystanie zasobów
docker stats ksef-invoice-monitor --no-stream

# Wejdź do kontenera (debugging)
docker exec -it ksef-invoice-monitor /bin/bash
```

### Dalsze wsparcie

Jeśli problem nie został rozwiązany:

1. **Zbierz informacje:**
   ```bash
   # Wersja
   docker logs ksef-invoice-monitor | grep "KSeF Invoice Monitor"

   # Pełne logi (wyczyść sekrety przed udostępnieniem!)
   docker logs ksef-invoice-monitor > ksef-logs.txt
   ```

2. **Sprawdź dokumentację:**
   - [NOTIFICATIONS.md](docs/NOTIFICATIONS.md) - Szczegółowa konfiguracja kanałów
   - [SECURITY.md](docs/SECURITY.md) - Zarządzanie sekretami
   - [QUICKSTART.md](docs/QUICKSTART.md) - Przewodnik szybkiego startu

3. **GitHub Issues:**
   - Otwórz issue na GitHub (NIE dołączaj tokenów/sekretów!)
   - Opisz problem, środowisko (test/prod), logi (bez sekretów)

4. **Problemy IDE:**
   - Zobacz [IDE_TROUBLESHOOTING.md](docs/IDE_TROUBLESHOOTING.md)
   - Są to tylko problemy edytora - kod działa poprawnie

---

## Licencja

Projekt udostępniony na licencji MIT License. Zobacz plik [LICENSE](LICENSE) po szczegóły.

**Co to oznacza:**
- ✅ Wolno używać komercyjnie
- ✅ Wolno modyfikować i dostosowywać
- ✅ Wolno dystrybuować
- ✅ Wolno używać prywatnie
- ⚠️ Bez gwarancji

---

## Zastrzeżenia

Niezależne narzędzie, nie afiliowane z Ministerstwa Finansów ani KSeF. Korzystaj na własne ryzyko i zgodnie z regulaminami KSeF.

**Oprogramowanie dostarczane "TAK JAK JEST", bez jakichkolwiek gwarancji.** Autorzy nie ponoszą odpowiedzialności za jakiekolwiek szkody wynikające z użytkowania tego oprogramowania.
