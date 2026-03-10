# Rate Limiting KSeF API — analiza i plan naprawy

Dokument opisuje problemy z limitami API KSeF oraz plan implementacji globalnego rate limitera.

---

## Limity API KSeF (z OpenAPI spec)

| Limit | Wartość | Okno |
|---|---|---|
| **Per second** | 10 requestów | 1s sliding window |
| **Per minute** | 30 requestów | 60s sliding window |
| **Per hour** | 120 requestów | 3600s sliding window |

Wszystkie endpointy podlegają tym samym limitom. Przy przekroczeniu → HTTP 429 z opcjonalnym `Retry-After`.

---

## Stan obecny — co działa

### Reaktywne zabezpieczenie (429 retry)

Lokalizacja: `app/ksef_client.py` → `_request_with_retry()`

- Max 3 retries po 429
- Parsowanie `Retry-After` (sekundy i HTTP-date)
- Cap na 120s, default 30s jeśli brak headera
- Działa poprawnie — ale jest to **ostatnia linia obrony**, nie strategia

### Proaktywny throttle (per-invoice sleep)

Lokalizacja: `app/invoice_monitor.py` → `check_for_new_invoices()`, linia ~301

```python
if self.save_xml or self.save_pdf:
    time.sleep(2)  # Rate limit: max 30 req/min API limit
```

---

## Znalezione problemy

### Problem 1: Subject1 przekracza 30 req/min (KRYTYCZNY)

Dla Subject1 z `save_xml=true`:
- `get_invoice_xml()` → 1 API call
- `get_invoice_upo()` → 1 API call (tylko Subject1)
- `time.sleep(2)` → 2s delay

**Efekt:** 2 calls / 2s = **60 calls/min** — dwukrotne przekroczenie limitu 30/min.

### Problem 2: Limit 120 req/hour (KRYTYCZNY)

Najpoważniejszy bottleneck. Przy 500 nowych fakturach:
- ~1500 API calls (metadata + XML + UPO)
- Nawet przy idealnym 30/min → zajmuje 50 minut
- Ale **120/hour** oznacza blokadę po 120 callach w pierwszej godzinie
- Pełne przetworzenie: **~12.5 godziny**

### Problem 3: Brak throttle na paginacji metadanych

`get_invoices_metadata()` wykonuje wiele stron paginacji bez delay:
- 1000 faktur → 4 strony → 4 calle w <1s
- Przy truncation → reset i kolejne strony
- Może burst do 10+ calls/s

### Problem 4: Brak globalnego trackera

Każda metoda throttluje się niezależnie (lub wcale). Brak wspólnego licznika:
- Metadata calls nie są liczone
- Auth calls nie są liczone
- Brak widoczności ile quota zostało

---

## Worst case: 500 faktur Subject1 + Subject2

| Operacja | Calls | Delay |
|---|---|---|
| Metadata Subject1 (2 strony) | 2 | 0s (brak throttle) |
| Metadata Subject2 (2 strony) | 2 | 0s (brak throttle) |
| XML per invoice (1000) | 1000 | 2s per invoice* |
| UPO per Subject1 (500) | 500 | brak dodatkowego delay |
| **RAZEM** | **~1504** | |

*Sleep 2s jest po obu callach (XML+UPO), nie po każdym z osobna.

**Bez naprawy:** ~1504 calls przy limicie 120/h = **~12.5h**, z wielokrotnymi 429 po drodze.

---

## Rekomendacja: Globalny Rate Limiter + Batch Queue

### Architektura

```
┌──────────────────────────────────────────────┐
│  RateLimiter (app/rate_limiter.py)           │
│                                              │
│  Token bucket z 3 oknami:                    │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐      │
│  │ 10/sec  │ │ 30/min   │ │ 120/hour │      │
│  └─────────┘ └──────────┘ └──────────┘      │
│                                              │
│  acquire() → sleep do wolnego slotu          │
│  remaining() → ile zostało w każdym oknie    │
│  reset_at() → kiedy okno się odnowi          │
└──────────┬───────────────────────────────────┘
           │
           │ każdy API call przechodzi przez acquire()
           │
┌──────────▼───────────────────────────────────┐
│  KSeFClient._request_with_retry()            │
│                                              │
│  1. rate_limiter.acquire()  ← NOWE           │
│  2. requests.get/post(...)                   │
│  3. if 429 → retry z Retry-After (jak teraz) │
└──────────────────────────────────────────────┘
```

### Klasa `RateLimiter`

```python
import time
import threading
from collections import deque

class RateLimiter:
    """Sliding window rate limiter for KSeF API.

    Enforces 3 concurrent limits:
    - 10 requests per second
    - 30 requests per minute
    - 120 requests per hour
    """

    def __init__(self, per_second=10, per_minute=30, per_hour=120):
        self.limits = [
            {"window": 1.0,    "max": per_second, "timestamps": deque()},
            {"window": 60.0,   "max": per_minute, "timestamps": deque()},
            {"window": 3600.0, "max": per_hour,   "timestamps": deque()},
        ]
        self._lock = threading.Lock()
        self._total_calls = 0

    def acquire(self, timeout=None):
        """Block until a request slot is available.

        Returns wait time in seconds (0 if no wait needed).
        """
        total_wait = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                wait = self._calculate_wait(now)
                if wait <= 0:
                    # Slot available — record timestamp
                    for limit in self.limits:
                        limit["timestamps"].append(now)
                    self._total_calls += 1
                    return total_wait

            # Wait outside lock
            time.sleep(wait)
            total_wait += wait

    def _calculate_wait(self, now):
        """Calculate seconds to wait for the most restrictive limit."""
        max_wait = 0.0
        for limit in self.limits:
            # Evict expired timestamps
            while limit["timestamps"] and (now - limit["timestamps"][0]) > limit["window"]:
                limit["timestamps"].popleft()

            if len(limit["timestamps"]) >= limit["max"]:
                # Window full — wait until oldest expires
                oldest = limit["timestamps"][0]
                wait = limit["window"] - (now - oldest) + 0.01  # +10ms buffer
                max_wait = max(max_wait, wait)

        return max_wait

    def remaining(self):
        """Return remaining calls in each window."""
        with self._lock:
            now = time.monotonic()
            result = {}
            for limit in self.limits:
                while limit["timestamps"] and (now - limit["timestamps"][0]) > limit["window"]:
                    limit["timestamps"].popleft()
                window_name = f"{int(limit['window'])}s"
                result[window_name] = limit["max"] - len(limit["timestamps"])
            result["total_calls"] = self._total_calls
            return result

    def pause_until(self, seconds):
        """Force pause (e.g., after 429 with Retry-After)."""
        with self._lock:
            # Mark all windows as full for the duration
            now = time.monotonic()
            future = now + seconds
            for limit in self.limits:
                limit["timestamps"].append(future)
```

---

## Integracja z istniejącym kodem

### 1. `ksef_client.py` — dodać rate limiter

```python
class KSeFClient:
    def __init__(self, config):
        # ... existing init ...
        self.rate_limiter = RateLimiter(
            per_second=10,
            per_minute=30,
            per_hour=120,
        )

    def _request_with_retry(self, method, url, **kwargs):
        # NOWE: acquire slot before request
        wait = self.rate_limiter.acquire()
        if wait > 0:
            logger.debug(f"Rate limiter waited {wait:.1f}s before request")

        # ... existing retry logic (429 handling) ...

        # NOWE: on 429, inform rate limiter
        if response.status_code == 429:
            retry_after = self._parse_retry_after(response)
            self.rate_limiter.pause_until(retry_after)
```

### 2. `invoice_monitor.py` — usunąć stary `time.sleep(2)`

```python
# PRZED (stary kod):
if self.save_xml or self.save_pdf:
    time.sleep(2)  # Rate limit: max 30 req/min API limit

# PO (nowy kod):
# Usunięte — rate limiter w ksef_client obsługuje throttling globalnie
```

### 3. Logging per check cycle

```python
def check_for_new_invoices(self):
    # ... existing logic ...

    # Na koniec cyklu: log stats
    remaining = self.ksef.rate_limiter.remaining()
    logger.info(
        f"Check cycle complete: {len(new_invoices)} new invoices, "
        f"API calls: {remaining['total_calls']}, "
        f"remaining: {remaining['60s']}/min, {remaining['3600s']}/hour"
    )
```

---

## Batch processing z kontynuacją

### Problem

Przy 500+ fakturach i limicie 120/h — przetwarzanie trwa wiele godzin. Jeśli aplikacja się zrestartuje, zaczyna od zera.

### Rozwiązanie: Progress tracking w DB

Z tabelą `invoices` z DATABASE_DESIGN.md — każda faktura zapisana do DB natychmiast po wykryciu (metadata), a artefakty pobierane w osobnym kroku:

```
┌─────────────────────────────────────────────────────┐
│  Faza 1: Zbierz metadane (szybkie, 2-4 API calls)  │
│  → INSERT OR IGNORE do tabeli invoices              │
│  → Pole: artifacts_downloaded = FALSE               │
└───────────────────────┬─────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────┐
│  Faza 2: Pobierz artefakty (wolne, rate-limited)    │
│  → SELECT WHERE artifacts_downloaded = FALSE        │
│  → Pobierz XML → Pobierz UPO → Generuj PDF         │
│  → UPDATE artifacts_downloaded = TRUE               │
│  → Rate limiter kontroluje tempo                    │
└───────────────────────┬─────────────────────────────┘
                        │
│  Restart? → Faza 2 kontynuuje od nieprzetworzonych  │
```

### Dodatkowe kolumny w tabeli `invoices`

```sql
-- Dodać do modelu z DATABASE_DESIGN.md:
artifacts_downloaded  BOOLEAN DEFAULT FALSE,  -- czy XML/PDF/UPO pobrane
artifacts_error       TEXT,                   -- ostatni błąd pobierania (nullable)
download_attempts     INTEGER DEFAULT 0       -- ile razy próbowano pobrać
```

### Implementacja w `invoice_monitor.py`

```python
def check_for_new_invoices(self):
    # Faza 1: Zbierz metadane (szybko)
    for subject_type in self.subject_types:
        invoices = self.ksef.get_invoices_metadata(date_from, date_to, subject_type)
        for inv in invoices:
            if not self._is_seen(inv):
                db.insert_or_ignore(inv)  # Natychmiastowy zapis do DB
                self._send_notification(inv)

    # Faza 2: Pobierz artefakty (rate-limited, resumable)
    if self.save_xml or self.save_pdf:
        pending = db.get_pending_artifacts(limit=50)  # batch po 50
        for inv in pending:
            try:
                self._save_invoice_artifacts(inv)
                db.mark_downloaded(inv.ksef_number)
            except RateLimitExhausted:
                logger.warning("Hourly rate limit reached, continuing next cycle")
                break  # Dokończymy w następnym cyklu schedulera
            except Exception as e:
                db.mark_error(inv.ksef_number, str(e))
                logger.error(f"Failed to download artifacts for {inv.ksef_number}: {e}")
```

---

## Konfiguracja

Opcjonalna sekcja w `config.json` (defaults wystarczają):

```json
{
  "ksef": {
    "rate_limit": {
      "per_second": 10,
      "per_minute": 30,
      "per_hour": 120,
      "artifacts_batch_size": 50
    }
  }
}
```

Wartości domyślne odpowiadają limitom z OpenAPI spec. Użytkownik może je obniżyć (np. shared token).

---

## Metryki Prometheus (opcjonalnie, v0.4)

```python
# Nowe metryki:
ksef_api_calls_total          # Counter: łączna liczba API calls
ksef_api_rate_limit_waits     # Counter: ile razy rate limiter musiał czekać
ksef_api_rate_limit_remaining # Gauge: ile calls zostało w oknie godzinowym
ksef_artifacts_pending        # Gauge: ile faktur czeka na pobranie artefaktów
```

---

## Plan implementacji

| Krok | Opis | Plik |
|---|---|---|
| 1 | Utworzyć `app/rate_limiter.py` z klasą `RateLimiter` | nowy plik |
| 2 | Zintegrować z `_request_with_retry()` w ksef_client | `app/ksef_client.py` |
| 3 | Usunąć `time.sleep(2)` z invoice_monitor | `app/invoice_monitor.py` |
| 4 | Dodać logging remaining quota po cyklu | `app/invoice_monitor.py` |
| 5 | Dodać kolumny `artifacts_downloaded` do modelu DB | `app/database.py` |
| 6 | Implementować 2-fazowe przetwarzanie (metadata → artifacts) | `app/invoice_monitor.py` |
| 7 | Dodać `RateLimitExhausted` exception i batch break | `app/rate_limiter.py` |
| 8 | Testy: RateLimiter unit tests (timing, concurrency) | `tests/test_rate_limiter.py` |
| 9 | Config: opcjonalna sekcja `rate_limit` z defaults | `app/config_manager.py` |

### Kolejność

- Kroki 1-4: **quick fix** — naprawia obecne problemy bez DB
- Kroki 5-7: **po implementacji DB** (DATABASE_DESIGN.md) — dodaje resumability
- Kroki 8-9: finalizacja i testy

---

## Podsumowanie zmian vs obecny stan

| Aspekt | Przed | Po |
|---|---|---|
| **Throttle metadata** | brak | RateLimiter.acquire() przed każdym callem |
| **Throttle per-invoice** | sleep(2) — zbyt krótki dla Subject1 | RateLimiter — adaptacyjny, respektuje 3 okna |
| **Limit 120/h** | ignorowany — 429 i retry | proaktywny — acquire() czeka na slot |
| **Globalny tracker** | brak | sliding window na sec/min/hour |
| **Resume po restart** | od zera | DB: pending artifacts queue |
| **Widoczność** | brak | logging remaining quota, Prometheus metrics |

---

**Ostatnia aktualizacja:** 2026-03-08
**Wersja:** v0.3 → v0.4 (planowane)
