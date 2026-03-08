# Wybór bazy danych — analiza i rekomendacja

Dokument opisuje wybór bazy danych dla KSeF Monitor v0.3 (roadmap punkt 5: "Przeniesienie informacji o fakturach do bazy").

---

## Kontekst

### Stan obecny
- Faktury śledzone w pliku JSON (`last_check.json`) z listą hashy SHA-256
- Brak trwałego przechowywania metadanych faktur
- Deduplication w pamięci (lista `seen_invoices`)

### Wymagania v0.3
- Trwałe przechowywanie metadanych faktur z API KSeF
- Model danych rozdzielony "per subject, per NIP"
- Indeksy pod najczęstsze zapytania (subject + nip + timestamp)
- Zapis przy pobraniu/detekcji faktury

### Wymagania przyszłe (v0.4–v0.5)
- REST API: lista/filtrowanie/sortowanie/paginacja faktur
- Statystyki: ile faktur per subject, per NIP, per okres
- Initial load danych historycznych (potencjalnie tysiące faktur)
- Idempotentne zapisy, retry-safe
- Multi-NIP w v2.0 (separacja per tenant)

### Ograniczenia
- Docker Compose (bez zewnętrznych managed services)
- Single-node deployment
- Python 3.11+ (dobre wsparcie ORM/driver)
- Lekki footprint — obok głównej aplikacji
- Licencja kompatybilna z MIT

---

## Porównanie opcji

| Kryterium | SQLite + WAL | PostgreSQL (Docker) | DuckDB |
|---|---|---|---|
| **Setup Docker** | zero — plik w volume `data/` | dodatkowy kontener, credentials, healthcheck | zero — plik |
| **RAM** | ~0 MB | 50–100 MB minimum | ~0 MB |
| **Concurrent R/W** | dobre (WAL: readers nie blokują writera) | doskonałe | słabe (single writer, OLAP) |
| **Filtrowanie/sort/paginacja** | pełne SQL, CTE, window functions | pełne SQL + zaawansowane indexy | pełne SQL, ale OLAP-optimized |
| **Full-text search** | FTS5 (dobry) | natywne tsvector + polski stemmer | ograniczone |
| **Migracje schematu** | Alembic (batch mode) | Alembic (natywnie) | brak wsparcia |
| **Backup** | kopia pliku | pg_dump | kopia pliku |
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

---

## Rekomendacja: SQLite + SQLAlchemy 2.0 ORM

### Dlaczego

1. **Odpowiedni rozmiar do obciążenia.** Setki do niskich tysięcy faktur per NIP rocznie to trywialny wolumen. Jeden writer (monitor) + jeden reader (przyszłe API) — WAL mode obsługuje to bez problemu.

2. **Zero infrastruktury.** Brak dodatkowego kontenera, credentials, connection pooling, healthchecks. Plik DB żyje w tym samym volume `data/` co obecny `last_check.json`.

3. **SQLAlchemy 2.0** daje kluczowe funkcje:
   - Deklaratywne modele z type annotations (Python 3.11+ style)
   - Composable queries dla REST API (filter, sort, paginate)
   - **Alembic** do migracji schematu między wersjami
   - Idempotentne zapisy via `INSERT OR IGNORE` / `ON CONFLICT`

4. **Czysta ścieżka migracji do PostgreSQL** — jeśli kiedykolwiek potrzeba (mało prawdopodobne przy tej skali), zmiana connection string + kilka dialect-specific poprawek.

5. **Multi-NIP (v2.0)** — dwa podejścia:
   - Jedna baza z `nip` jako kolumna + composite indexy (prostsze, rekomendowane)
   - Osobny plik SQLite per NIP (pełna izolacja tenantów, trivial z osobnymi engine instances)

### Kiedy przemyśleć PostgreSQL

- Wiele procesów piszących jednocześnie
- Full-text search z polskim stemmerem jako kluczowa funkcja
- LISTEN/NOTIFY dla real-time UI
- Skala > 100k faktur (mało prawdopodobne w single-NIP)

---

## Model danych

### Tabela `invoices`

```sql
CREATE TABLE invoices (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identyfikatory
    ksef_number         TEXT    UNIQUE NOT NULL,  -- klucz deduplikacji
    invoice_number      TEXT,                     -- numer faktury sprzedawcy
    invoice_hash        TEXT,                     -- SHA-256 z API (Base64)

    -- Klasyfikacja
    invoice_type        TEXT,                     -- Vat, Kor, Zal, Roz, Upr, etc.
    subject_type        TEXT    NOT NULL,         -- Subject1 / Subject2
    form_code           TEXT,                     -- FA v1-0E, FA (3) v1-0E, etc.

    -- Daty
    issue_date          DATE,                     -- data wystawienia
    invoicing_date      DATETIME,                -- data przyjęcia w KSeF
    acquisition_date    DATETIME,                -- data nadania numeru KSeF

    -- Kwoty
    gross_amount        DECIMAL(15,2),
    net_amount          DECIMAL(15,2),
    vat_amount          DECIMAL(15,2),
    currency            TEXT    DEFAULT 'PLN',

    -- Sprzedawca
    seller_nip          TEXT    NOT NULL,
    seller_name         TEXT,

    -- Nabywca
    buyer_nip           TEXT,
    buyer_name          TEXT,

    -- Flagi
    is_self_invoicing   BOOLEAN DEFAULT FALSE,
    has_attachment       BOOLEAN DEFAULT FALSE,

    -- Artefakty na dysku
    has_xml             BOOLEAN DEFAULT FALSE,
    has_pdf             BOOLEAN DEFAULT FALSE,
    xml_path            TEXT,                     -- ścieżka do zapisanego XML
    pdf_path            TEXT,                     -- ścieżka do zapisanego PDF

    -- Metadane
    created_at          DATETIME DEFAULT (datetime('now')),
    updated_at          DATETIME DEFAULT (datetime('now')),
    raw_metadata        TEXT                      -- pełny JSON z API (na przyszłość)
);
```

### Indeksy

```sql
-- Najczęstsze zapytanie: faktury per subject + NIP + data
CREATE INDEX ix_invoice_lookup
    ON invoices(subject_type, seller_nip, issue_date);

-- Wyszukiwanie po nabywcy
CREATE INDEX ix_invoice_buyer
    ON invoices(buyer_nip, issue_date);

-- Klucz deduplikacji (UNIQUE constraint na ksef_number już tworzy index)

-- Filtrowanie po typie faktury
CREATE INDEX ix_invoice_type
    ON invoices(invoice_type);

-- Chronologiczne listowanie
CREATE INDEX ix_invoice_date
    ON invoices(issue_date DESC);
```

### Typowe zapytania

```sql
-- Lista faktur sprzedażowych dla NIP z ostatniego miesiąca
SELECT * FROM invoices
WHERE subject_type = 'Subject1'
  AND seller_nip = '1234567890'
  AND issue_date >= date('now', '-30 days')
ORDER BY issue_date DESC
LIMIT 20 OFFSET 0;

-- Statystyki per NIP
SELECT seller_nip, COUNT(*) as cnt, SUM(gross_amount) as total
FROM invoices
WHERE subject_type = 'Subject1'
GROUP BY seller_nip
ORDER BY total DESC;

-- Idempotentny insert (deduplikacja)
INSERT OR IGNORE INTO invoices (ksef_number, invoice_number, ...)
VALUES (?, ?, ...);
```

---

## Konfiguracja

Nowa sekcja w `config.json`:

```json
{
  "database": {
    "path": "/data/invoices.db"
  }
}
```

Default: `/data/invoices.db` (ten sam volume co `last_check.json`).

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
| **FTS (v0.5)** | FTS5 virtual table gdy potrzebny full-text search |

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
    cursor.close()
```

---

## Zależności

Nowe pakiety w `requirements.txt`:

```
SQLAlchemy>=2.0.0,<3.0.0
alembic>=1.13.0,<2.0.0
```

SQLite jest wbudowany w Python — brak dodatkowych zależności systemowych.

---

## Plan implementacji

1. **Dodać zależności** — SQLAlchemy, Alembic w `requirements.txt` i `pyproject.toml`
2. **Utworzyć moduł `app/database.py`** — engine, session factory, Base, model `Invoice`
3. **Zainicjować Alembic** — `alembic init`, konfiguracja `env.py` z batch mode
4. **Pierwsza migracja** — utworzenie tabeli `invoices` z indeksami
5. **Integracja z `invoice_monitor.py`** — zapis metadanych przy detekcji nowej faktury
6. **Migracja `seen_invoices`** — przy starcie: jeśli istnieje `last_check.json` z hashami, zaimportować do DB
7. **Config** — nowa sekcja `database` w `config_manager.py` z defaults
8. **Testy** — unit testy dla warstwy DB (CRUD, deduplikacja, indeksy)

---

**Ostatnia aktualizacja:** 2026-03-08
**Wersja:** v0.3
