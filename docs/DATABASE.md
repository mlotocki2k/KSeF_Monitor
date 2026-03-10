# Database — SQLite + SQLAlchemy 2.0

KSeF Monitor v0.3 przechowuje metadane faktur, stan monitoringu i log powiadomień w SQLite.

## Konfiguracja

```json
{
  "database": {
    "enabled": true,
    "path": "/data/invoices.db"
  }
}
```

| Pole | Domyślnie | Opis |
|------|-----------|------|
| `enabled` | `true` | Wyłączenie (`false`) powoduje fallback na `last_check.json` |
| `path` | `/data/invoices.db` | Ścieżka do pliku SQLite (auto-tworzony) |

Baza jest **opcjonalna** — monitor działa bez niej, ale traci trwałe przechowywanie metadanych faktur, log powiadomień i error tracking.

## Tabele (faza 1)

### `invoices`

Metadane faktur z API KSeF. Klucz deduplikacji: `ksef_number` (UNIQUE).

| Kolumna | Typ | Opis |
|---------|-----|------|
| `ksef_number` | TEXT UNIQUE | Numer KSeF (np. `1234567890-20260301-ABCDEF-AB`) |
| `invoice_number` | TEXT | Numer faktury nadany przez sprzedawcę |
| `invoice_type` | TEXT | Vat, Kor, Zal, Roz, Upr, etc. |
| `subject_type` | TEXT | Subject1 (sprzedaż) / Subject2 (zakup) |
| `issue_date` | TEXT | Data wystawienia (ISO) |
| `gross_amount` | DECIMAL | Kwota brutto |
| `net_amount` | DECIMAL | Kwota netto |
| `vat_amount` | DECIMAL | Kwota VAT |
| `currency` | TEXT | Kod waluty (domyślnie PLN) |
| `seller_nip` / `seller_name` | TEXT | Dane sprzedawcy |
| `buyer_nip` / `buyer_name` | TEXT | Dane nabywcy |
| `has_xml` / `has_pdf` / `has_upo` | BOOLEAN | Czy artefakt został zapisany |
| `xml_path` / `pdf_path` / `upo_path` | TEXT | Ścieżki do artefaktów |
| `raw_metadata` | TEXT | Pełny JSON z API (na przyszłość) |

**Indeksy:** `(subject_type, seller_nip, issue_date)`, `(buyer_nip, issue_date)`, `(invoice_type)`, `(issue_date DESC)`

### `monitor_state`

Zastępuje `last_check.json`. Stan monitoringu per NIP + subject_type.

| Kolumna | Typ | Opis |
|---------|-----|------|
| `nip` | TEXT | NIP podmiotu |
| `subject_type` | TEXT | Subject1 / Subject2 |
| `last_check` | DATETIME | Timestamp ostatniego sprawdzenia (UTC) |
| `last_invoice_at` | DATETIME | Timestamp najnowszej faktury |
| `last_ksef_number` | TEXT | Ostatni przetworzony numer KSeF |
| `invoices_count` | INTEGER | Licznik faktur |
| `consecutive_errors` | INTEGER | Licznik kolejnych błędów (reset po sukcesie) |
| `last_error` | TEXT | Ostatni komunikat błędu |
| `status` | TEXT | `active` / `paused` / `error` |

**Klucz unikalny:** `(nip, subject_type)`

### `notification_log`

Historia wysłanych powiadomień — deduplikacja, diagnostyka, audyt.

| Kolumna | Typ | Opis |
|---------|-----|------|
| `event_type` | TEXT | `invoice` / `startup` / `shutdown` / `error` / `test` |
| `channel` | TEXT | `pushover` / `discord` / `slack` / `email` / `webhook` |
| `status` | TEXT | `sent` / `failed` / `skipped` |
| `invoice_id` | INTEGER | Powiązanie z fakturą (NULL dla systemowych) |
| `dedup_key` | TEXT | np. `{ksef_number}:{channel}` — zapobiega duplikatom |
| `error_message` | TEXT | Komunikat błędu (jeśli `failed`) |

**Indeksy:** `(invoice_id)`, `(sent_at DESC)`, `(dedup_key)` UNIQUE

## Migracja z last_check.json

Przy pierwszym uruchomieniu z włączoną bazą:

1. Jeśli istnieje `last_check.json` a tabela `monitor_state` jest pusta:
   - Import `last_check` timestamp do DB z aktualnym NIP z config
   - Tworzony wpis per `subject_type` z config
   - Plik rename'owany na `last_check.json.migrated`
2. Jeśli obie istnieją — DB ma priorytet
3. JSON state file jest nadal zapisywany (backward compat)

## Alembic — migracje schematu

```bash
# Uruchom migracje (tworzenie/aktualizacja tabel)
python -m alembic upgrade head

# Sprawdź aktualną wersję
python -m alembic current

# Wygeneruj nową migrację (po zmianie modeli)
python -m alembic revision --autogenerate -m "description"

# Rollback ostatniej migracji
python -m alembic downgrade -1
```

Konfiguracja: `alembic.ini` + `alembic/env.py` (render_as_batch=True dla SQLite).

W Dockerze migracja uruchamia się automatycznie — `Database.create_tables()` przy starcie.

## Narzędzie administracyjne: db_admin.py

CLI do zarządzania bazą danych. Uruchomienie:

```bash
python db_admin.py [--db ŚCIEŻKA] <komenda> [opcje]
```

Domyślna ścieżka DB: `data/invoices.db`. Override: `--db /data/invoices.db`.

### Komendy

#### Przegląd

```bash
# Status bazy: tabele, rozmiar, indeksy, wersja migracji
python db_admin.py status

# Stan monitoringu per NIP + subject_type
python db_admin.py state

# Błędy: monitor_state z consecutive_errors + failed notifications
python db_admin.py errors
```

#### Faktury

```bash
# Lista faktur (najnowsze, domyślnie 20)
python db_admin.py invoices
python db_admin.py invoices --limit 50
python db_admin.py invoices --subject Subject1
python db_admin.py invoices --nip 1234567890

# Szczegóły faktury (po numerze KSeF lub ID)
python db_admin.py invoice 1234567890-20260301-ABCDEF-AB
python db_admin.py invoice 42

# Wyszukiwanie (numer KSeF, NIP, nazwa kontrahenta)
python db_admin.py search "Firma ABC"
python db_admin.py search "1234567890"
```

#### Statystyki

```bash
# Pełne statystyki: per subject, per miesiąc, top sprzedawcy, artefakty, powiadomienia
python db_admin.py stats
```

Przykładowy output:
```
=== Invoice Statistics ===
Total invoices: 127
  Subject1: 45 invoices, gross total: 523,410.00 PLN
  Subject2: 82 invoices, gross total: 1,245,890.50 PLN

  Monthly breakdown (last 6 months):
    2026-03: 23 invoices, 245,100.00 PLN
    2026-02: 31 invoices, 312,500.00 PLN

  Top 5 sellers:
    9876543210    Dostawca Główny Sp. z o.o.      28 invoices

  Artifacts: XML=127/127  PDF=45/127  UPO=45/127

=== Notification Statistics ===
Total notifications: 254
  sent: 250
  failed: 4

  Per channel:
    pushover   sent   : 127
    discord    sent   : 123
    pushover   failed : 4
```

#### Powiadomienia

```bash
# Log powiadomień (najnowsze, domyślnie 30)
python db_admin.py notifications
python db_admin.py notifications --limit 100
python db_admin.py notifications --channel pushover
python db_admin.py notifications --status failed
```

#### Eksport

```bash
# CSV (domyślnie na stdout)
python db_admin.py export-invoices
python db_admin.py export-invoices --output faktury.csv

# JSON
python db_admin.py export-invoices --format json --output faktury.json
```

#### Utrzymanie

```bash
# Usunięcie starych logów powiadomień (domyślnie > 90 dni)
python db_admin.py cleanup-notifications
python db_admin.py cleanup-notifications --days 30 -y

# Reset liczników błędów w monitor_state
python db_admin.py reset-errors
python db_admin.py reset-errors -y

# Kompaktowanie pliku DB (SQLite VACUUM)
python db_admin.py vacuum
```

## Pragmy SQLite

Ustawiane automatycznie przy każdym połączeniu:

| Pragma | Wartość | Cel |
|--------|---------|-----|
| `journal_mode` | WAL | Readers nie blokują writera |
| `foreign_keys` | ON | Wymuszanie FK constraints |
| `busy_timeout` | 5000 ms | Czekanie na lock zamiast błędu |

## Backup

Plik `invoices.db` to standardowy SQLite — wystarczy kopia pliku:

```bash
# Kopia z poziomu hosta (volume mount)
cp data/invoices.db data/invoices.db.backup

# Kopia z poziomu kontenera Docker
docker cp ksef-monitor:/data/invoices.db ./invoices.db.backup

# SQLite backup API (bezpieczne przy aktywnym WAL)
sqlite3 data/invoices.db ".backup data/invoices.db.backup"
```

## Dalszy rozwój

Pełny wielofazowy projekt bazy: [DATABASE_DESIGN.md](DATABASE_DESIGN.md)

| Faza | Wersja | Tabele |
|------|--------|--------|
| **1** (obecna) | v0.3 | `invoices`, `monitor_state`, `notification_log` |
| 2 | v0.4 | `api_request_log`, `invoice_artifacts` |
| 3 | v0.5 | `import_jobs`, `invoice_views`, `dashboard_stats`, FTS5 |
| 4 | v1.0 | `app_config`, `audit_log`, `sessions` |
| 5 | v2.0 | `tenants` + multi-NIP FK |
