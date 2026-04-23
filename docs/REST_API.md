# REST API — KSeF Monitor v0.5

REST API oparte na FastAPI, umożliwiające odczyt danych o fakturach, statystykach i stanie monitora.

## Uruchomienie

API uruchamia się automatycznie razem z monitorem (daemon thread). Konfiguracja w `config.json`:

```json
{
  "api": {
    "enabled": true,
    "host": "0.0.0.0",
    "port": 8080,
    "auth_token": "your-secret-token-min-32-chars",
    "cors_origins": [],
    "docs_enabled": true,
    "ui_public": false,
    "rate_limit": {
      "enabled": true,
      "default": "60/minute",
      "trigger": "2/minute",
      "initial_load_start": "1/hour",
      "push_regenerate": "5/hour",
      "push_reset": "1/hour",
      "invoice_download": "30/minute"
    }
  }
}
```

| Pole | Default | Opis |
|------|---------|------|
| `enabled` | `true` | Włącz/wyłącz REST API |
| `host` | `"0.0.0.0"` | Adres nasłuchu |
| `port` | `8080` | Port HTTP |
| `auth_token` | `null` | Token Bearer auth (min 32 znaki). `null` = open access (WARNING w logach) |
| `cors_origins` | `[]` | Lista dozwolonych originów CORS. Wildcard `*` zablokowany gdy auth_token ustawiony |
| `docs_enabled` | `true` | Swagger UI (`/docs`) i ReDoc (`/redoc`). Wyłącz w produkcji (F-02) |
| `ui_public` | `false` | (v0.5) Opt-in bypass auth dla `/ui` — dla reverse-proxy z zewnętrznym auth |
| `rate_limit.enabled` | `true` | Rate limiting (slowapi) |
| `rate_limit.default` | `"60/minute"` | Domyślny limit per IP dla niewymienionych endpointów |
| `rate_limit.trigger` | `"2/minute"` | Limit dla `POST /monitor/trigger` |
| `rate_limit.initial_load_start` | `"1/hour"` | Limit dla `POST /initial-load/start` |
| `rate_limit.push_regenerate` | `"5/hour"` | Limit dla `POST /push/regenerate` |
| `rate_limit.push_reset` | `"1/hour"` | Limit dla `POST /push/reset` |
| `rate_limit.invoice_download` | `"30/minute"` | Limit dla `GET /invoices/{ksef}/pdf` i `/xml` |

## Autentykacja

Dwie równoległe ścieżki auth (v0.5.1):

### 1. Bearer token (curl, integracje, iOS push pairing)

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8080/api/v1/invoices
```

- Token z `api.auth_token` w configu
- Porównywany przez `hmac.compare_digest` (timing-safe)
- Automatycznie generowany jeśli puste, zapisywany w Docker secrets / env / config

### 2. Cookie session (przeglądarka, V5-13)

- Login form: `GET /ui/login` → POST z `username` + `password`
- Cookie: `mksef_session`, opaque 64-char hex, HttpOnly, SameSite=Strict, Secure (https), 7-dni rolling TTL
- Sesje persisted w tabeli `ui_sessions` (Alembic head: `e0f1g2h34567`)
- Pierwszy uruchomienie:
  - **Fresh install:** `/ui` → redirect `/ui/setup` → wizard tworzy konto admin
  - **Upgrade z v0.5.0:** jeśli `api.auth_token` był ustawiony, `main.py` automatycznie tworzy usera `admin` z hasłem = `auth_token`. Login: `admin` / `<your existing token>`. Zmień hasło w `/ui/account`.
- `POST /ui/logout` revoke sesję w DB + clear cookie
- `POST /ui/account/password` zmiana własnego hasła (revoke wszystkich sesji w tym bieżącej)

### Uprawnienia / endpointy publiczne

- Whitelist (bez auth): `/docs`, `/redoc`, `/openapi.json`, `/api/v1/monitor/health`, `/ui/login`, `/ui/logout`, `/ui/setup`
- Brak auth na `/ui/*` → 303 redirect do `/ui/login` (lub `/ui/setup` jeśli 0 userów w DB)
- Brak auth na `/api/*` → 401 JSON `{"detail":"Missing or invalid Authorization header"}`
- Opcja `api.ui_public: true` re-włącza bypass dla `/ui` (legacy reverse-proxy)

### CLI — zarządzanie kontami

```bash
python -m app.user_admin list                       # lista kont
python -m app.user_admin add <username>             # dodaj
python -m app.user_admin reset-password <username>  # zresetuj (revoke sesje)
python -m app.user_admin delete <username>          # usuń (refuse last user)
python -m app.user_admin cleanup-sessions           # purge expired
```

### Rate limits na auth

- `POST /ui/login` → 5/min
- `POST /ui/setup` → 3/min
- `POST /ui/account/password` → 5/min

## Swagger UI

Gdy `docs_enabled: true`:
- **Swagger UI:** `http://localhost:8080/docs`
- **ReDoc:** `http://localhost:8080/redoc`
- **OpenAPI JSON:** `http://localhost:8080/openapi.json`

## Endpointy

### Faktury

#### `GET /api/v1/invoices`

Lista faktur z paginacją, filtrowaniem i sortowaniem.

**Query parameters:**

| Parametr | Typ | Default | Opis |
|----------|-----|---------|------|
| `page` | int | 1 | Numer strony (1–10000) |
| `per_page` | int | 20 | Elementów na stronę (1–100) |
| `subject_type` | string | — | Filtr: `subject1` (sprzedaż) lub `subject2` (zakup) |
| `seller_nip` | string | — | Filtr po NIP sprzedawcy (10 cyfr) |
| `buyer_nip` | string | — | Filtr po NIP nabywcy (10 cyfr) |
| `issue_date_from` | string | — | Filtr: data od (ISO, np. `2026-01-01`) |
| `issue_date_to` | string | — | Filtr: data do |
| `search` | string | — | Wyszukiwanie w: ksef_number, invoice_number, seller_name, buyer_name |
| `sort_by` | string | `created_at` | Sortowanie: `created_at`, `issue_date`, `gross_amount`, `ksef_number` |
| `sort_order` | string | `desc` | Kolejność: `asc` / `desc` |

**Response (200):**

```json
{
  "items": [
    {
      "ksef_number": "1234567890-20260301-ABCDEF-AB",
      "invoice_number": "FV/2026/03/001",
      "invoice_type": "VAT",
      "subject_type": "subject1",
      "issue_date": "2026-03-01",
      "gross_amount": 1230.00,
      "currency": "PLN",
      "seller_nip": "1234567890",
      "seller_name": "Firma ABC Sp. z o.o.",
      "buyer_nip": "9876543210",
      "buyer_name": "Klient XYZ",
      "has_xml": true,
      "has_pdf": true,
      "created_at": "2026-03-01T12:00:00"
    }
  ],
  "total": 127,
  "page": 1,
  "per_page": 20,
  "pages": 7
}
```

#### `GET /api/v1/invoices/{ksef_number}`

Szczegóły faktury.

**Response (200):** Rozszerzony `InvoiceSummary` o: `net_amount`, `vat_amount`, `invoicing_date`, `acquisition_date`, `form_code`, `is_self_invoicing`, `has_attachment`, `source`, `updated_at`.

**Response (404):** `{"detail": "Invoice not found"}`

### Statystyki

#### `GET /api/v1/stats/summary`

Zagregowane statystyki faktur.

**Response (200):**

```json
{
  "total_invoices": 127,
  "by_subject_type": {"subject1": 45, "subject2": 82},
  "by_month": {"2026-03": 23, "2026-02": 31}
}
```

#### `GET /api/v1/stats/api`

Statystyki wywołań KSeF API.

| Parametr | Typ | Default | Opis |
|----------|-----|---------|------|
| `hours` | int | 1 | Okres: 1–24 godzin |

**Response (200):**

```json
{
  "total_requests": 42,
  "error_count": 2,
  "avg_response_time_ms": 345.7,
  "period_hours": 1
}
```

### Monitor

#### `GET /api/v1/monitor/health`

Health check — **nie wymaga autentykacji**.

**Response (200):**

```json
{
  "status": "ok",
  "version": "0.5.0",
  "db_connected": true
}
```

#### `GET /api/v1/monitor/state`

Stan monitoringu dla wszystkich par NIP + subject_type.

**Response (200):**

```json
[
  {
    "nip": "1234567890",
    "subject_type": "subject1",
    "last_check": "2026-03-23T10:00:00",
    "last_invoice_at": "2026-03-22T15:30:00",
    "last_ksef_number": "1234567890-20260322-ABCDEF-AB",
    "invoices_count": 45,
    "consecutive_errors": 0,
    "status": "active"
  }
]
```

#### `POST /api/v1/monitor/trigger`

Wymuszenie natychmiastowego sprawdzenia faktur.

**Response (200):**

```json
{
  "message": "Check scheduled for next cycle",
  "triggered": true
}
```

### Artefakty

#### `GET /api/v1/artifacts/pending`

Lista artefaktów oczekujących na pobranie.

| Parametr | Typ | Default | Opis |
|----------|-----|---------|------|
| `limit` | int | 50 | Maksymalna liczba wyników (1–100) |

**Response (200):**

```json
{
  "items": [
    {
      "artifact_type": "pdf",
      "status": "pending",
      "download_attempts": 2,
      "file_size": null,
      "created_at": "2026-03-22T15:30:00",
      "updated_at": "2026-03-23T10:00:00"
    }
  ],
  "total": 3
}
```

### Push notyfikacje

#### `GET /api/v1/push/setup`

Zwraca informacje o konfiguracji push — dla UI. Od v0.5 zwraca wyłącznie **zamaskowane** dane parowania
(`X…Y` preview pairing code). Nie ujawnia pełnego kodu ani QR.

**Wymaga autentykacji** od v0.5 (poprzednio pomijane w whiteliście).

#### `GET /api/v1/push/pairing` _(nowe w v0.5)_

Auth-gated endpoint zwracający **pełny plaintext pairing code** oraz wyrenderowany QR code do sparowania
z aplikacją Monitor KSeF (iOS). Kod jest 64-bitowy (`secrets.token_hex(8)` — 16 hex znaków).

Distinct od `/push/setup` — ten endpoint jest wyłącznie dla operatora/admina sparowującego urządzenie.

**Wymaga autentykacji.**

**Response (200):**

```json
{
  "pairing_code": "a1b2c3d4e5f6a7b8",
  "qr_text": "MKSEF:a1b2c3d4e5f6a7b8",
  "qr_ascii": "... ASCII QR ..."
}
```

#### `POST /api/v1/push/regenerate`

Regeneruje `instance_key`. Rate limit: 5/hr.

#### `POST /api/v1/push/reset`

Resetuje konfigurację push (usuwa parowania). Rate limit: 1/hr.

## Limity rate limiting (v0.5)

Per-endpoint limity `slowapi` (konfigurowalne w `api.rate_limit`):

| Endpoint | Metoda | Limit domyślny |
|----------|--------|:--------------:|
| `/api/v1/monitor/trigger` | POST | 2/min |
| `/api/v1/initial-load/start` | POST | 1/hr |
| `/api/v1/push/regenerate` | POST | 5/hr |
| `/api/v1/push/reset` | POST | 1/hr |
| `/api/v1/invoices/{ksef}/pdf` | GET | 30/min |
| `/api/v1/invoices/{ksef}/xml` | GET | 30/min |
| (wszystkie pozostałe) | * | 60/min |

Przekroczenie limitu zwraca `429 Too Many Requests`.

## Kody błędów

| Status | Opis |
|--------|------|
| 200 | Sukces |
| 400 | Nieprawidłowe parametry (np. zły format NIP) |
| 401 | Brak lub nieprawidłowy token autentykacji |
| 404 | Nie znaleziono (faktura) |
| 422 | Walidacja path-param — np. `ksef_number` nie pasuje do formatu KSeF (v0.5) |
| 429 | Rate limit exceeded |
| 500 | Błąd wewnętrzny (bez stack trace w odpowiedzi) |
| 503 | Baza danych niedostępna |

## Bezpieczeństwo

- **Bearer auth** z `hmac.compare_digest` (timing-safe)
- **Auth whitelist (v0.5):** tylko `{/docs, /redoc, /openapi.json, /api/v1/monitor/health}` publiczne — reszta wymaga tokenu
- **Security headers (v0.5):** CSP, HSTS (`max-age=31536000`), `Referrer-Policy`, `Permissions-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Cache-Control: no-store`
- **Per-endpoint rate limiting (v0.5)** — patrz tabela wyżej; domyślnie włączone
- **CORS** — domyślnie wyłączony; wildcard `*` zablokowany gdy auth_token ustawiony
- **SSRF guard (v0.5)** — `app._ssrf_guard.is_safe_public_url` dla webhook i CIRFMF URL
- **`KsefNumberPath` (v0.5)** — Pydantic type waliduje `ksef_number` na poziomie path-param (422 przy niezgodności)
- **No PII leak** — response models nie eksponują: file paths, internal IDs, request/response bodies
- **Docs disable** — w produkcji wyłącz Swagger/ReDoc (`docs_enabled: false`)
- **Generic error handler** — stack traces nie trafiają do odpowiedzi API
