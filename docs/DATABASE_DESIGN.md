# Struktura bazy danych — kompletny projekt

Dokument opisuje pełną strukturę bazy danych KSeF Monitor, podzieloną na fazy zgodne z roadmapem wersji.

**Technologia:** SQLite + WAL mode + SQLAlchemy 2.0 ORM + Alembic migracje

---

## Spis treści

1. [Uzasadnienie wyboru technologii](#uzasadnienie-wyboru-technologii)
2. [Faza 1 — v0.3: Fundament](#faza-1--v03-fundament)
3. [Faza 2 — v0.4: Stabilizacja + API](#faza-2--v04-stabilizacja--api)
4. [Faza 3 — v0.5: Initial load + Web UI](#faza-3--v05-initial-load--web-ui)
5. [Faza 4 — v1.0: Panel admin](#faza-4--v10-panel-admin)
6. [Faza 5 — v2.0: Multi-NIP](#faza-5--v20-multi-nip)
7. [Podsumowanie tabel per faza](#podsumowanie-tabel-per-faza)
8. [Decyzje techniczne](#decyzje-techniczne)
9. [Plan implementacji fazy 1](#plan-implementacji-fazy-1)

---

## Uzasadnienie wyboru technologii

### Porównanie opcji

| Kryterium | SQLite + WAL | PostgreSQL (Docker) | DuckDB |
|---|---|---|---|
| **Setup Docker** | zero — plik w volume `data/` | dodatkowy kontener, credentials, healthcheck | zero — plik |
| **RAM** | ~0 MB | 50–100 MB minimum | ~0 MB |
| **Concurrent R/W** | dobre (WAL: readers nie blokują writera) | doskonałe | słabe (single writer, OLAP) |
| **Filtrowanie/sort/paginacja** | pełne SQL, CTE, window functions | pełne SQL + zaawansowane indexy | pełne SQL, ale OLAP-optimized |
| **Full-text search** | FTS5 (dobry) | natywne tsvector + polski stemmer | ograniczone |
| **Migracje schematu** | Alembic (batch mode) | Alembic (natywnie) | brak wsparcia |
| **Footprint** | 0 dodatkowego obrazu Docker | obraz ~80 MB + dane | 0 dodatkowego obrazu |
| **Skalowalność** | do ~100k wierszy bez problemu | praktycznie nieograniczona | nie jako OLTP |
| **ORM (SQLAlchemy)** | pełne wsparcie | pełne wsparcie | ograniczone |

### Odrzucone opcje

| Opcja | Powód odrzucenia |
|---|---|
| **DuckDB** | OLAP, nie OLTP — słaba obsługa częstych małych insertów, brak Alembic |
| **MongoDB** | Overkill, dane są relacyjne, cięższy niż PostgreSQL |
| **TinyDB / shelve / JSON** | Brak query, indeksów, migracji — regresja względem obecnego stanu |
| **PostgreSQL** | Overkill na obecną skalę (setki–tysiące faktur/rok), dodatkowy kontener, credentials, RAM |

### Rekomendacja: SQLite + SQLAlchemy 2.0

1. **Odpowiedni rozmiar** — setki do niskich tysięcy faktur per NIP rocznie. Jeden writer (monitor) + jeden reader (API) — WAL mode obsługuje bez problemu
2. **Zero infrastruktury** — plik DB w tym samym volume `data/` co obecny `last_check.json`
3. **SQLAlchemy 2.0** — deklaratywne modele, composable queries, Alembic migracje, `INSERT OR IGNORE`
4. **Ścieżka migracji do PostgreSQL** — zmiana connection string + kilka dialect-specific poprawek

### Kiedy przemyśleć PostgreSQL

- Wiele procesów piszących jednocześnie
- Full-text search z polskim stemmerem jako kluczowa funkcja
- LISTEN/NOTIFY dla real-time UI
- Skala > 100k faktur

---

## Faza 1 — v0.3: Fundament

**Cel:** zastąpić `last_check.json` bazą danych, trwale przechowywać metadane faktur.

### Tabela `invoices`

Przechowuje metadane faktur z API KSeF. Jedno źródło prawdy o fakturach.

```sql
CREATE TABLE invoices (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identyfikatory
    ksef_number         TEXT    UNIQUE NOT NULL,  -- klucz deduplikacji (np. "1234567890-20260301-ABCDEF-AB")
    invoice_number      TEXT,                     -- numer faktury nadany przez sprzedawcę
    invoice_hash        TEXT,                     -- SHA-256 z API (Base64), używany do QR code

    -- Klasyfikacja
    invoice_type        TEXT,                     -- Vat, Kor, Zal, Roz, Upr, etc.
    subject_type        TEXT    NOT NULL,         -- Subject1 (sprzedaż) / Subject2 (zakup)
    form_code           TEXT,                     -- FA v1-0E, FA(3) v1-0E, etc.

    -- Daty
    issue_date          DATE,                     -- data wystawienia (z XML/metadata)
    invoicing_date      DATETIME,                -- data przyjęcia w KSeF
    acquisition_date    DATETIME,                -- data nadania numeru KSeF

    -- Kwoty
    gross_amount        DECIMAL(15,2),           -- brutto
    net_amount          DECIMAL(15,2),           -- netto
    vat_amount          DECIMAL(15,2),           -- VAT
    currency            TEXT    DEFAULT 'PLN',   -- kod waluty ISO 4217

    -- Sprzedawca
    seller_nip          TEXT    NOT NULL,
    seller_name         TEXT,

    -- Nabywca
    buyer_nip           TEXT,                     -- może być NULL (osoba fizyczna)
    buyer_name          TEXT,

    -- Flagi z metadata API
    is_self_invoicing   BOOLEAN DEFAULT FALSE,   -- samofakturowanie
    has_attachment      BOOLEAN DEFAULT FALSE,   -- czy faktura ma załączniki

    -- Artefakty na dysku
    has_xml             BOOLEAN DEFAULT FALSE,
    has_pdf             BOOLEAN DEFAULT FALSE,
    has_upo             BOOLEAN DEFAULT FALSE,   -- kolumna zachowana, ale nieużywana (UPO nie jest pobierane)
    xml_path            TEXT,                     -- ścieżka względna do XML
    pdf_path            TEXT,                     -- ścieżka względna do PDF
    upo_path            TEXT,                     -- kolumna zachowana, ale nieużywana

    -- Metadane
    created_at          DATETIME DEFAULT (datetime('now')),
    updated_at          DATETIME DEFAULT (datetime('now')),
    raw_metadata        TEXT                      -- pełny JSON z API (na przyszłość)
);
```

**Źródło danych:** `ksef_client.get_invoices_metadata()` → pole `invoices[]` w odpowiedzi API.

**Mapowanie API → kolumny:**

| Pole API | Kolumna DB |
|---|---|
| `ksefNumber` | `ksef_number` |
| `invoiceNumber` | `invoice_number` |
| `issueDate` | `issue_date` |
| `invoicingDate` | `invoicing_date` |
| `acquisitionDate` | `acquisition_date` |
| `grossAmount` | `gross_amount` |
| `netAmount` | `net_amount` |
| `vatAmount` | `vat_amount` |
| `currency` | `currency` |
| `seller.nip` | `seller_nip` |
| `seller.name` | `seller_name` |
| `buyer.nip` | `buyer_nip` |
| `buyer.name` | `buyer_name` |
| parametr zapytania | `subject_type` |
| header `x-ms-meta-hash` (z GET XML) | `invoice_hash` |

### Tabela `monitor_state`

Zastępuje `last_check.json`. Stan monitoringu per NIP + subject_type.

```sql
CREATE TABLE monitor_state (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Klucz: NIP + subject_type (unique pair)
    nip                 TEXT    NOT NULL,          -- NIP podmiotu (future-proof: multi-NIP v2.0)
    subject_type        TEXT    NOT NULL,           -- Subject1 / Subject2

    -- Timestamps
    last_check          DATETIME NOT NULL,         -- timestamp ostatniego sprawdzenia (UTC)
    last_invoice_at     DATETIME,                  -- timestamp najnowszej wykrytej faktury

    -- Resume support
    last_ksef_number    TEXT,                       -- ostatni przetworzony numer KSeF

    -- Statystyki (cache)
    invoices_count      INTEGER DEFAULT 0,         -- licznik faktur (aktualizowany przy insercie)

    -- Error tracking
    consecutive_errors  INTEGER DEFAULT 0,         -- licznik kolejnych błędów (reset po sukcesie)
    last_error          TEXT,                       -- ostatni komunikat błędu
    last_error_at       DATETIME,                  -- timestamp ostatniego błędu

    -- Status
    status              TEXT    DEFAULT 'active',   -- active / paused / error
    updated_at          DATETIME DEFAULT (datetime('now')),

    UNIQUE(nip, subject_type)
);
```

**Kolumny — uzasadnienie:**

| Kolumna | Po co |
|---|---|
| `nip` | Multi-NIP (v2.0) — osobny stan per NIP. W v0.3 jeden wiersz per subject_type z NIP z config |
| `last_ksef_number` | Resume po restarcie — wiadomo do którego numeru KSeF pobrano artefakty |
| `consecutive_errors` | Backoff — jeśli odpytywanie danego NIP+subject ciągle failuje, można zwiększyć interwał |
| `last_error` / `last_error_at` | Diagnostyka bez grzebania w logach |
| `status` | `active` (normalny), `paused` (wstrzymany), `error` (auto-zatrzymany po N błędach) |

### Tabela `notification_log`

Historia wysłanych powiadomień — deduplication, diagnostyka, audyt.

```sql
CREATE TABLE notification_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id          INTEGER REFERENCES invoices(id),  -- NULL dla systemowych (start/stop/error)

    -- Co wysłano
    event_type          TEXT    NOT NULL,           -- invoice / startup / shutdown / error / test
    channel             TEXT    NOT NULL,           -- pushover / discord / slack / email / webhook
    title               TEXT,
    priority            INTEGER DEFAULT 0,          -- -2 do 2

    -- Status dostarczenia
    status              TEXT    DEFAULT 'sent',     -- sent / failed / skipped
    error_message       TEXT,                       -- komunikat błędu jeśli failed

    -- Timestamps
    sent_at             DATETIME DEFAULT (datetime('now')),

    -- Deduplikacja (opcjonalna)
    dedup_key           TEXT                        -- np. "{ksef_number}:{channel}" — zapobiega duplikatom
);
```

**Dlaczego w fazie 1:**
- `invoice_monitor.py` wysyła powiadomienia na 5 kanałów — bez logowania nie wiadomo czy dotarły
- Przy restarcie aplikacja może wysłać duplikat powiadomienia — `dedup_key` to blokuje
- Przyszłe UI (v0.5) będzie chciało wyświetlić historię powiadomień per faktura

### Indeksy — faza 1

```sql
-- Faktury: najczęstsze zapytanie (lista per subject + NIP + data)
CREATE INDEX ix_invoices_lookup
    ON invoices(subject_type, seller_nip, issue_date);

-- Faktury: wyszukiwanie po nabywcy
CREATE INDEX ix_invoices_buyer
    ON invoices(buyer_nip, issue_date);

-- Faktury: filtrowanie po typie
CREATE INDEX ix_invoices_type
    ON invoices(invoice_type);

-- Faktury: chronologiczne listowanie
CREATE INDEX ix_invoices_date
    ON invoices(issue_date DESC);

-- Notification log: per invoice
CREATE INDEX ix_notif_invoice
    ON notification_log(invoice_id);

-- Notification log: chronologiczne
CREATE INDEX ix_notif_sent
    ON notification_log(sent_at DESC);

-- Notification log: deduplikacja
CREATE UNIQUE INDEX ix_notif_dedup
    ON notification_log(dedup_key)
    WHERE dedup_key IS NOT NULL;
```

### Migracja z `last_check.json`

Przy starcie aplikacji:
1. Jeśli istnieje `last_check.json` a tabela `monitor_state` jest pusta:
   - Import `last_check` timestamp do DB z aktualnym NIP z config
   - Hashe z `seen_invoices` — opcjonalnie insert jako "known" rekordy (bez metadanych)
   - Rename pliku na `.json.migrated`
2. Jeśli obie istnieją — DB ma priorytet

---

## Faza 2 — v0.4: Stabilizacja + API

**Cel:** REST API pod UI, statystyki, retry-safe operacje, audyt.

### Tabela `api_request_log` (nowa)

Śledzenie wszystkich zapytań do KSeF API — diagnostyka, rate limiting, metryki.

```sql
CREATE TABLE api_request_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Zapytanie
    endpoint            TEXT    NOT NULL,           -- np. "/v2/invoices/query/metadata"
    method              TEXT    NOT NULL,           -- GET / POST
    nip                 TEXT,                       -- NIP dla którego wykonano request

    -- Odpowiedź
    status_code         INTEGER,                   -- HTTP status (200, 401, 429, 500...)
    response_time_ms    INTEGER,                   -- czas odpowiedzi w ms
    retry_count         INTEGER DEFAULT 0,         -- ile razy retry (429/5xx)
    retry_after_sec     INTEGER,                   -- wartość Retry-After (jeśli 429)

    -- Kontekst
    invoices_returned   INTEGER,                   -- ile faktur zwrócono (dla metadata query)
    page_offset         INTEGER,                   -- numer strony paginacji
    is_truncated        BOOLEAN DEFAULT FALSE,     -- czy API zwróciło truncation

    -- Timestamp
    requested_at        DATETIME DEFAULT (datetime('now'))
);
```

**Zastosowania:**
- Metryki operacyjne: czasy odpowiedzi, error rate, 429 frequency
- Rate limiter: zliczanie requests per window z tabeli zamiast in-memory
- Prometheus: `ksef_api_requests_total`, `ksef_api_response_time_seconds`
- UI diagnostyczne: "ile razy API odpowiedziało 429 w ostatniej godzinie?"

### Tabela `invoice_artifacts` (nowa)

Śledzi status pobierania artefaktów — resumable download po przerwaniu.

```sql
CREATE TABLE invoice_artifacts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id          INTEGER NOT NULL REFERENCES invoices(id),

    -- Typ artefaktu
    artifact_type       TEXT    NOT NULL,           -- xml / pdf

    -- Status
    status              TEXT    DEFAULT 'pending',  -- pending / downloaded / failed / skipped
    download_attempts   INTEGER DEFAULT 0,
    last_attempt_at     DATETIME,
    error_message       TEXT,

    -- Plik na dysku
    file_path           TEXT,                       -- ścieżka względna do pliku
    file_size           INTEGER,                   -- rozmiar w bajtach
    file_hash           TEXT,                       -- SHA-256 dla weryfikacji integralności

    -- Timestamps
    created_at          DATETIME DEFAULT (datetime('now')),
    downloaded_at       DATETIME,                  -- kiedy pomyślnie pobrano

    UNIQUE(invoice_id, artifact_type)
);
```

**Dlaczego:**
- Obecny kod w `_save_invoice_artifacts()` nie wie co pobrano wcześniej — przy 500 fakturach i restarcie zaczyna od nowa
- `status=pending` → trzeba pobrać, `downloaded` → pominąć, `failed` → retry
- Rate limiting: wiadomo ile artefaktów do pobrania = ile API calls potrzeba
- Zastępuje kolumny `has_xml/has_pdf/xml_path/pdf_path` z tabeli `invoices` (normalizacja)

### Rozszerzenie `invoices` — nowe kolumny

```sql
-- Dodane w migracji Alembic (faza 2)
ALTER TABLE invoices ADD COLUMN bookkeeping_version TEXT;  -- wersja FA z API metadata
ALTER TABLE invoices ADD COLUMN source TEXT DEFAULT 'polling';  -- polling / initial_load / manual
```

### Indeksy — faza 2

```sql
-- API request log: statystyki per endpoint
CREATE INDEX ix_api_log_endpoint
    ON api_request_log(endpoint, requested_at DESC);

-- API request log: rate limiting window
CREATE INDEX ix_api_log_rate
    ON api_request_log(requested_at DESC);

-- Artifacts: pending downloads (resumable)
CREATE INDEX ix_artifacts_pending
    ON invoice_artifacts(status)
    WHERE status IN ('pending', 'failed');
```

### Typowe zapytania — faza 2

```sql
-- Statystyki API: error rate w ostatniej godzinie
SELECT
    status_code,
    COUNT(*) as cnt,
    AVG(response_time_ms) as avg_ms
FROM api_request_log
WHERE requested_at >= datetime('now', '-1 hour')
GROUP BY status_code;

-- Ile artefaktów czeka na pobranie?
SELECT artifact_type, COUNT(*) as pending
FROM invoice_artifacts
WHERE status IN ('pending', 'failed')
GROUP BY artifact_type;

-- Resume: następne do pobrania (oldest first, max 10)
SELECT ia.*, i.ksef_number
FROM invoice_artifacts ia
JOIN invoices i ON i.id = ia.invoice_id
WHERE ia.status IN ('pending', 'failed')
  AND ia.download_attempts < 3
ORDER BY ia.created_at ASC
LIMIT 10;

-- Paginacja z total count (REST API)
SELECT COUNT(*) OVER() as total_count, *
FROM invoices
WHERE subject_type = ?
  AND issue_date BETWEEN ? AND ?
ORDER BY issue_date DESC
LIMIT ? OFFSET ?;
```

---

## Faza 3 — v0.5: Initial load + Web UI

**Cel:** import historyczny, dashboard, lista faktur, podgląd.

### Tabela `import_jobs` (nowa)

Zarządza procesem initial load — moving window, progress tracking, resume.

```sql
CREATE TABLE import_jobs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Konfiguracja
    nip                 TEXT    NOT NULL,
    subject_type        TEXT    NOT NULL,
    date_from           DATETIME NOT NULL,         -- start zakresu importu
    date_to             DATETIME NOT NULL,         -- koniec zakresu importu

    -- Moving window state
    current_window_from DATETIME,                  -- aktualnie przetwarzane okno (start)
    current_window_to   DATETIME,                  -- aktualnie przetwarzane okno (koniec)
    window_size_days    INTEGER DEFAULT 90,         -- rozmiar okna (max 90 — limit API)
    windows_completed   INTEGER DEFAULT 0,         -- ile okien zakończono
    windows_total       INTEGER,                   -- ile okien łącznie (obliczone)

    -- Postęp
    status              TEXT    DEFAULT 'pending',  -- pending / running / paused / completed / failed
    invoices_found      INTEGER DEFAULT 0,         -- ile faktur znaleziono łącznie
    invoices_imported   INTEGER DEFAULT 0,         -- ile nowych (nie duplikatów) zapisano
    invoices_skipped    INTEGER DEFAULT 0,         -- ile pominięto (duplikaty)
    artifacts_pending   INTEGER DEFAULT 0,         -- ile artefaktów do pobrania

    -- Raport
    error_message       TEXT,
    started_at          DATETIME,
    completed_at        DATETIME,
    created_at          DATETIME DEFAULT (datetime('now')),
    updated_at          DATETIME DEFAULT (datetime('now')),

    UNIQUE(nip, subject_type, date_from, date_to)
);
```

**Moving window — jak działa:**
1. Zakres `date_from..date_to` dzielony na okna ≤90 dni (limit KSeF API)
2. Każde okno przetwarzane sekwencyjnie z paginacją
3. Po zakończeniu okna: `windows_completed++`, `current_window_from` przesuwa się
4. Przerwanie → restart: sprawdza `current_window_from`, wznawia od tego okna
5. Rate limiting między oknami (patrz: [RATE_LIMITING_DESIGN.md](RATE_LIMITING_DESIGN.md))

### Tabela `invoice_views` (nowa)

Cache podglądu faktur — XML pobrane z API, żeby nie odpytywać wielokrotnie.

```sql
CREATE TABLE invoice_views (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id          INTEGER UNIQUE NOT NULL REFERENCES invoices(id),

    -- Cache XML
    xml_content         TEXT,                       -- pełna treść XML faktury
    xml_fetched_at      DATETIME,                  -- kiedy pobrano z API

    -- Sparsowane dane (z XML, do wyświetlenia w UI)
    parsed_data         TEXT,                       -- JSON ze sparsowanymi polami (seller address, items, VAT summary, payment)

    -- PDF on-demand
    pdf_generated_at    DATETIME,                  -- kiedy ostatnio wygenerowano PDF
    pdf_generator       TEXT,                       -- xhtml2pdf / reportlab / cirfmf

    created_at          DATETIME DEFAULT (datetime('now'))
);
```

**Dlaczego:**
- UI wyświetla podgląd faktury — dane z XML (pozycje, kwoty VAT, adres, metoda płatności)
- Parsowanie XML jest kosztowne → cache w `parsed_data` (JSON)
- Pozycje faktury (items[]), VAT summary, dane płatności — nie są w API metadata, tylko w XML
- PDF on-demand: użytkownik zaznacza fakturę → generuje PDF → zapamiętuje generator

### Tabela `dashboard_stats` (nowa)

Zmaterializowane statystyki dla dashboardu — żeby nie liczyć przy każdym request.

```sql
CREATE TABLE dashboard_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Klucz
    nip                 TEXT    NOT NULL,
    subject_type        TEXT    NOT NULL,
    period              TEXT    NOT NULL,           -- "2026-03" (miesiąc) / "2026" (rok) / "total"

    -- Statystyki
    invoices_count      INTEGER DEFAULT 0,
    gross_total         DECIMAL(15,2) DEFAULT 0,
    net_total           DECIMAL(15,2) DEFAULT 0,
    vat_total           DECIMAL(15,2) DEFAULT 0,

    -- Top kontrahenci (JSON array)
    top_counterparties  TEXT,                       -- [{"nip": "...", "name": "...", "count": N, "total": X}, ...]

    -- Timestamps
    calculated_at       DATETIME DEFAULT (datetime('now')),

    UNIQUE(nip, subject_type, period)
);
```

**Aktualizacja:** trigger lub cron po insercie nowej faktury — `INSERT OR REPLACE` z przeliczonymi wartościami.

### Rozszerzenie `invoices` — FTS5

```sql
-- Full-text search na nazwach kontrahentów i numerach faktur
CREATE VIRTUAL TABLE invoices_fts USING fts5(
    ksef_number,
    invoice_number,
    seller_name,
    buyer_name,
    content='invoices',
    content_rowid='id'
);

-- Triggers do synchronizacji FTS z tabelą główną
CREATE TRIGGER invoices_fts_insert AFTER INSERT ON invoices BEGIN
    INSERT INTO invoices_fts(rowid, ksef_number, invoice_number, seller_name, buyer_name)
    VALUES (new.id, new.ksef_number, new.invoice_number, new.seller_name, new.buyer_name);
END;

CREATE TRIGGER invoices_fts_delete BEFORE DELETE ON invoices BEGIN
    INSERT INTO invoices_fts(invoices_fts, rowid, ksef_number, invoice_number, seller_name, buyer_name)
    VALUES ('delete', old.id, old.ksef_number, old.invoice_number, old.seller_name, old.buyer_name);
END;

CREATE TRIGGER invoices_fts_update AFTER UPDATE ON invoices BEGIN
    INSERT INTO invoices_fts(invoices_fts, rowid, ksef_number, invoice_number, seller_name, buyer_name)
    VALUES ('delete', old.id, old.ksef_number, old.invoice_number, old.seller_name, old.buyer_name);
    INSERT INTO invoices_fts(rowid, ksef_number, invoice_number, seller_name, buyer_name)
    VALUES (new.id, new.ksef_number, new.invoice_number, new.seller_name, new.buyer_name);
END;
```

### Indeksy — faza 3

```sql
-- Import jobs: aktywne joby
CREATE INDEX ix_import_status
    ON import_jobs(status)
    WHERE status IN ('pending', 'running', 'paused');

-- Dashboard stats: lookup
CREATE INDEX ix_dashboard_lookup
    ON dashboard_stats(nip, subject_type, period);
```

### Typowe zapytania — faza 3

```sql
-- Dashboard: podsumowanie per NIP (bieżący miesiąc)
SELECT * FROM dashboard_stats
WHERE nip = ? AND period = strftime('%Y-%m', 'now');

-- Search: wyszukiwanie kontrahenta
SELECT i.* FROM invoices i
JOIN invoices_fts fts ON fts.rowid = i.id
WHERE invoices_fts MATCH ?
ORDER BY rank
LIMIT 20;

-- Import progress
SELECT
    status,
    windows_completed || '/' || windows_total as progress,
    invoices_found, invoices_imported, invoices_skipped
FROM import_jobs
WHERE nip = ? AND status != 'completed'
ORDER BY created_at DESC
LIMIT 1;

-- Podgląd faktury (cache hit)
SELECT iv.parsed_data, iv.xml_fetched_at
FROM invoice_views iv
WHERE iv.invoice_id = ?;
```

---

## Faza 4 — v1.0: Panel admin

**Cel:** konfiguracja z UI, audit trail zmian, zarządzanie schedulera.

### Tabela `app_config` (nowa)

Konfiguracja aplikacji przechowywana w DB — edytowalna z UI.

```sql
CREATE TABLE app_config (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    section             TEXT    NOT NULL,           -- ksef / notifications / monitoring / schedule / storage / prometheus
    key                 TEXT    NOT NULL,           -- np. "interval", "channels", "save_xml"
    value               TEXT    NOT NULL,           -- wartość (JSON-encoded dla złożonych typów)
    value_type          TEXT    DEFAULT 'string',   -- string / integer / boolean / json / secret
    description         TEXT,                       -- opis dla UI
    updated_at          DATETIME DEFAULT (datetime('now')),
    updated_by          TEXT    DEFAULT 'system',   -- system / admin / migration

    UNIQUE(section, key)
);
```

**Relacja z `config.json`:**
- Przy starcie: config.json → DB (jeśli DB pusta)
- Runtime: UI edytuje DB → restart serwisu ładuje z DB
- Export: DB → config.json (backup)

### Tabela `audit_log` (nowa)

Audit trail wszystkich zmian konfiguracji i akcji administracyjnych.

```sql
CREATE TABLE audit_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    action              TEXT    NOT NULL,           -- config_change / import_start / import_stop / monitor_pause / monitor_resume
    entity_type         TEXT,                       -- config / import_job / monitor_state
    entity_id           INTEGER,                   -- ID zmienionego rekordu
    old_value           TEXT,                       -- poprzednia wartość (JSON)
    new_value           TEXT,                       -- nowa wartość (JSON)
    performed_by        TEXT    DEFAULT 'admin',    -- admin / system / api
    performed_at        DATETIME DEFAULT (datetime('now'))
);
```

### Tabela `sessions` (nowa)

Sesje użytkowników web UI (podstawowe auth z roadmap v0.4).

```sql
CREATE TABLE sessions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    token               TEXT    UNIQUE NOT NULL,    -- session token (SHA-256 random)
    user_agent          TEXT,
    ip_address          TEXT,
    created_at          DATETIME DEFAULT (datetime('now')),
    expires_at          DATETIME NOT NULL,
    last_activity_at    DATETIME DEFAULT (datetime('now'))
);
```

### Indeksy — faza 4

```sql
-- Audit log: chronologiczny przegląd
CREATE INDEX ix_audit_log_time
    ON audit_log(performed_at DESC);

-- Audit log: per entity
CREATE INDEX ix_audit_log_entity
    ON audit_log(entity_type, entity_id);

-- Sessions: lookup by token
CREATE INDEX ix_sessions_token
    ON sessions(token);

-- Sessions: cleanup expired
CREATE INDEX ix_sessions_expires
    ON sessions(expires_at);
```

---

## Faza 5 — v2.0: Multi-NIP

**Cel:** pełna izolacja danych per NIP (tenant).

### Tabela `tenants` (nowa)

Rejestr NIP-ów z ich konfiguracją.

```sql
CREATE TABLE tenants (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nip                 TEXT    UNIQUE NOT NULL,    -- NIP podmiotu
    name                TEXT,                       -- nazwa firmy
    environment         TEXT    DEFAULT 'prod',     -- test / demo / prod

    -- KSeF auth per tenant
    ksef_token_ref      TEXT,                       -- referencja do secret (nie plaintext!)

    -- Konfiguracja per tenant
    subject_types       TEXT    DEFAULT '["Subject1"]',  -- JSON array
    date_type           TEXT    DEFAULT 'Invoicing',
    schedule_config     TEXT,                       -- JSON: override schedulera per NIP
    notification_config TEXT,                       -- JSON: override powiadomień per NIP (routing)

    -- Status
    status              TEXT    DEFAULT 'active',   -- active / paused / disabled
    created_at          DATETIME DEFAULT (datetime('now')),
    updated_at          DATETIME DEFAULT (datetime('now'))
);
```

### Rozszerzenie istniejących tabel

Tabele `invoices`, `monitor_state`, `notification_log`, `api_request_log`, `import_jobs`, `dashboard_stats` — już mają kolumnę `nip`. Dodajemy FK constraint:

```sql
-- Migracja: dodanie FK do tenants (Alembic batch mode)
-- invoices.seller_nip → tenants.nip (dla Subject1)
-- Lub lepiej: dodać kolumnę tenant_nip (bo seller_nip != NIP monitorujący przy Subject2)

ALTER TABLE invoices ADD COLUMN tenant_nip TEXT REFERENCES tenants(nip);
ALTER TABLE api_request_log ADD COLUMN tenant_nip TEXT REFERENCES tenants(nip);
ALTER TABLE notification_log ADD COLUMN tenant_nip TEXT REFERENCES tenants(nip);

-- Backfill: UPDATE invoices SET tenant_nip = (SELECT nip FROM tenants LIMIT 1) WHERE tenant_nip IS NULL;
```

**Dlaczego `tenant_nip` zamiast re-use `seller_nip`:**
- Przy Subject1 (sprzedaż): `seller_nip` = nasz NIP ✅
- Przy Subject2 (zakup): `seller_nip` = NIP kontrahenta, nasz NIP to `buyer_nip` ✅
- `tenant_nip` jednoznacznie identyfikuje czyja to faktura, niezależnie od subject_type

### Indeksy — faza 5

```sql
-- Invoices per tenant
CREATE INDEX ix_invoices_tenant
    ON invoices(tenant_nip, issue_date DESC);

-- Cross-tenant stats
CREATE INDEX ix_dashboard_tenant
    ON dashboard_stats(nip);
```

### Typowe zapytania — faza 5

```sql
-- Lista wszystkich tenantów ze statystykami
SELECT
    t.nip, t.name, t.status,
    ms.last_check, ms.invoices_count, ms.consecutive_errors
FROM tenants t
LEFT JOIN monitor_state ms ON ms.nip = t.nip
ORDER BY t.name;

-- Przełączanie tenanta w UI: faktury dla wybranego NIP
SELECT * FROM invoices
WHERE tenant_nip = ?
ORDER BY issue_date DESC
LIMIT 20;
```

---

## Podsumowanie tabel per faza

| Faza | Wersja | Nowe tabele | Rozszerzenia |
|---|---|---|---|
| **1** | v0.3 | `invoices`, `monitor_state`, `notification_log` | — |
| **2** | v0.4 | `api_request_log`, `invoice_artifacts` | `invoices` +2 kolumny |
| **3** | v0.5 | `import_jobs`, `invoice_views`, `dashboard_stats`, `invoices_fts` (FTS5) | — |
| **4** | v1.0 | `app_config`, `audit_log`, `sessions` | — |
| **5** | v2.0 | `tenants` | `invoices`, `api_request_log`, `notification_log` +`tenant_nip` |

### Diagram relacji (faza 5 — pełna)

```
tenants (nip)
    │
    ├──< monitor_state (nip, subject_type)
    ├──< import_jobs (nip, subject_type)
    ├──< dashboard_stats (nip, subject_type)
    │
    └──< invoices (tenant_nip)
              │
              ├──< invoice_artifacts (invoice_id)
              ├──< invoice_views (invoice_id)
              └──< notification_log (invoice_id)

app_config (section, key)
audit_log (entity_type, entity_id)
sessions (token)
api_request_log (tenant_nip)
```

---

## Decyzje techniczne

| Aspekt | Decyzja |
|---|---|
| **ORM** | SQLAlchemy 2.0 (`mapped_column`, type annotations) |
| **Migracje** | Alembic z `render_as_batch=True` (SQLite ALTER TABLE workaround) |
| **WAL mode** | Włączany przy connect: `PRAGMA journal_mode=WAL` |
| **Foreign keys** | Włączane: `PRAGMA foreign_keys=ON` |
| **Deduplication** | UNIQUE constraint na `ksef_number`, `INSERT OR IGNORE` |
| **raw_metadata** | Pełny JSON z API — umożliwia późniejsze wzbogacanie bez migracji |
| **Backup** | Kopia pliku `invoices.db` (lub SQLite backup API) |
| **FTS (v0.5)** | FTS5 virtual table z triggerami synchronizacji |
| **Secrets** | Nigdy w DB plaintext — `ksef_token_ref` to referencja, nie wartość |

### Inicjalizacja engine

```python
from sqlalchemy import create_engine, event

engine = create_engine(
    "sqlite:///data/invoices.db",
    connect_args={"check_same_thread": False},
    echo=False,
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")  # 5s wait on lock
    cursor.close()
```

### Konfiguracja

```json
{
  "database": {
    "path": "/data/invoices.db"
  }
}
```

### Zależności

```
SQLAlchemy>=2.0.0,<3.0.0
alembic>=1.13.0,<2.0.0
```

---

## Plan implementacji fazy 1

1. **Dodać zależności** — SQLAlchemy, Alembic w `requirements.txt` i `pyproject.toml`
2. **Utworzyć `app/database.py`** — engine, session factory, Base, modele: `Invoice`, `MonitorState`, `NotificationLog`
3. **Zainicjować Alembic** — `alembic init`, `env.py` z `render_as_batch=True`
4. **Pierwsza migracja** — `invoices` + `monitor_state` + `notification_log` + indeksy
5. **Integracja `invoice_monitor.py`** — zapis metadanych przy detekcji + aktualizacja `monitor_state`
6. **Integracja notifiers** — zapis do `notification_log` po wysłaniu/błędzie
7. **Migracja `last_check.json`** — import do DB, rename na `.json.migrated`
8. **Config** — sekcja `database` w `config_manager.py` z defaults
9. **Testy** — unit testy: CRUD, deduplikacja, migracja stanu, notification dedup

---

## Powiązane dokumenty

- [RATE_LIMITING_DESIGN.md](RATE_LIMITING_DESIGN.md) — rate limiter (wpływa na `api_request_log`)
- [KSEF_API_LIMITATIONS.md](KSEF_API_LIMITATIONS.md) — limity API (90 dni, 10k truncation, rate limits)
- [ROADMAP.md](ROADMAP.md) — planowane funkcjonalności per wersja

---

**Ostatnia aktualizacja:** 2026-03-09
**Wersja dokumentu:** v2.0 (kompletna struktura multi-fazowa)
