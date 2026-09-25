# Ograniczenia KSeF API — kompletna dokumentacja

Dokument opisuje wszystkie znane ograniczenia i limity KSeF API v2.4.0, ich wpływ na działanie aplikacji oraz zastosowane obejścia.

---

## Rate limiting (limity zapytań)

Limity są **per endpoint** (nie globalnie). Każdy endpoint ma własne `x-rate-limits` w OpenAPI spec (`spec/openapi.json`).

### Limity kluczowych endpointów

| Endpoint | /sec | /min | /hour | Uwagi |
|---|---|---|---|---|
| `POST /invoices/query/metadata` | 8 | 16 | **20** | ⚠️ najniższy limit — bottleneck monitoringu |
| `GET /invoices/ksef/{ksefNumber}` | 8 | 16 | 64 | pobieranie XML faktury |
| `POST /invoices/exports` | 4 | 8 | 20 | eksport zbiorczy |
| `POST /auth/...` (autentykacja) | 10 | 30 | 120 | challenge, status, redeem |
| `GET /rate-limits` | 10 | 30 | 120 | sprawdzenie aktualnych limitów |

### Token vs certyfikat — brak różnicy w v2

KSeF API v2.4 obsługuje wyłącznie **Bearer token**. Certyfikatowa autentykacja istniała w v1 (wycofane). W v2 **nie ma rozróżnienia** limitów między metodami autentykacji — identyczne `x-rate-limits` niezależnie od ścieżki auth.

### Odpowiedź 429 Too Many Requests

```
HTTP/1.1 429 Too Many Requests
Retry-After: 30
```

- Header `Retry-After` może zawierać liczbę sekund lub datę HTTP
- Aplikacja parsuje oba formaty (`ksef_client.py` → `_request_with_retry()`)
- Max 3 retries po 429, cap na 120s, default 30s jeśli brak headera

### Wpływ na przetwarzanie dużej liczby faktur

| Scenariusz | API calls | Czas minimalny |
|---|---|---|
| 100 faktur (metadata + XML) | ~204 | ~1h |
| 500 faktur (metadata + XML) | ~1004 | ~8.5h |
| 1000 faktur (metadata + XML) | ~2004 | ~17h |

Szczegółowa analiza i plan naprawy: [RATE_LIMITING_DESIGN.md](RATE_LIMITING_DESIGN.md)

---

## Ograniczenia zapytań o metadane

### Zakres dat — max 100 dni (UTC)

Endpointy `POST /v2/invoices/query/metadata` i `POST /v2/invoices/exports` akceptują `dateRange` o rozpiętości
maksymalnie **100 dni liczonych w UTC** (KSeF API 2.7.1+; wcześniej „3 miesiące”, empirycznie 89 dni).

```json
{
  "dateRange": {
    "dateType": "Invoicing",
    "from": "2026-01-01T00:00:00.000Z",
    "to":   "2026-03-31T23:59:59.999Z"
  }
}
```

**Obsługa w aplikacji (od 0.6.5):** `invoice_monitor.py` obcina `date_from` do max 100 dni wstecz
(`MAX_DATE_RANGE_DAYS = 100`), a import historyczny dzieli zakres na okna `MAX_WINDOW_DAYS = 100`.
Faktycznie odpytywany span to **99 dni** (`MAX - 1`) — ten sam margines, który działał przy starym limicie
(90 → 89), bezpieczny niezależnie od tego, czy KSeF liczy koniec zakresu włącznie. Import roku = 4 okna
na podmiot zamiast 5.

> **KSeF API 2.7.1 — limit podniesiony do 100 dni (liczonych w UTC).** Zmiana kompatybilna wstecznie.
> Wdrożenia: TEST 26.08.2026, DEMO 15.09.2026, **PRD 23.09.2026** (live spec PRD z „100 dni w strefie UTC”
> potwierdzony 25.09.2026, build `2.8.1-pr-20260923.3`). Wersje < 0.6.5 zostają przy 90 dniach — działają dalej.
> Czy KSeF przyjmuje pełne 100 dni, można zmierzyć sondą `examples/probe_date_range.py` (TEST).

### Eksport faktur — kompresja paczki

`POST /invoices/exports` przyjmuje `compressionType` (`Zip` | `TarGz`, domyślnie `Zip`) — pole jest już
w spec PRD 2.6.1. Od KSeF API 2.7.1 status eksportu zwraca też `package.compressionType`.
Aplikacja (od 0.6.4) wysyła jawnie `"Zip"`; paczka zgłoszona z inną kompresją kończy eksport błędem
`Unsupported export compression: <typ>`. Brak pola (PRD 2.6.1) = ZIP.

`InvoiceExportStatusResponse.package` jest w spec `nullable`. Eksport zakończony sukcesem (200), ale bez
paczki, aplikacja traktuje jako nieudane okno (`Export completed without package`) — okno trafia do
błędów joba importu historycznego, nie jest liczone jako pusty import.

### Nagłówek `X-System-Warning`

KSeF (od API 2.6.0) może dołączać do odpowiedzi nagłówek `X-System-Warning` z komunikatem systemowym.
Aplikacja (od 0.6.4) loguje go na poziomie WARNING — każdą różną treść raz na proces, bez znaków
sterujących, obciętą do 500 znaków. „Różna treść” liczona jest po skrócie SHA-256 pełnej wartości,
więc komunikaty różniące się dopiero po 500. znaku są logowane osobno.

### Rozmiar strony — 10 do 250 rekordów

| Parametr | Min | Max | Default w aplikacji |
|---|---|---|---|
| `pageSize` | 10 | 250 | 250 |

Parametr przekazywany jako query param (nie w body):
```
POST /v2/invoices/query/metadata?pageSize=250&pageOffset=0&sortOrder=Asc
```

### Limit rekordów — 10 000 (truncation)

API zwraca maksymalnie **10 000 rekordów** na jedno zapytanie. Po przekroczeniu:

- Odpowiedź zawiera `isTruncated: true`
- Aplikacja musi zawęzić `dateRange.from` do daty ostatniej zwróconej faktury
- Reset `pageOffset` do 0
- Kontynuacja pobierania z nowym zakresem

**Obsługa w aplikacji:** `ksef_client.py` → `get_invoices_metadata()` automatycznie obsługuje truncation i zawężanie zakresu dat.

### Paginacja

| Pole odpowiedzi | Znaczenie |
|---|---|
| `hasMore: false` | Koniec danych |
| `hasMore: true`, `isTruncated: false` | Kolejna strona dostępna (`pageOffset++`) |
| `hasMore: true`, `isTruncated: true` | Limit 10k — wymagane zawężenie `dateRange.from` |

---

## Ograniczenia autentykacji

### Token sesyjny

| Aspekt | Wartość |
|---|---|
| Typ tokena | Bearer (access + refresh) |
| Wygaśnięcie access token | Wymaga refresh (`/v2/auth/token/refresh`) |
| Wygaśnięcie refresh token | Wymaga ponownej autentykacji |
| Max aktywnych sesji | Ograniczone (API nie podaje limitu) |

**Obsługa w aplikacji:** `ksef_client.py` automatycznie odświeża token przy HTTP 401 (`_handle_401_refresh()`).

### Szyfrowanie challenge

Autentykacja wymaga szyfrowania RSA-OAEP z kluczem publicznym pobranym z API:

| Parametr | Wartość |
|---|---|
| Algorytm | RSA-OAEP |
| Hash | SHA-256 |
| MGF | MGF1 (SHA-256) |
| Plaintext | `<token>\|<timestampMs>` (UTF-8) |

---

## Ograniczenia pobierania faktur

### XML faktury

- Endpoint: `GET /v2/invoices/ksef/{ksefNumber}`
- Wymaga aktywnej sesji (Bearer token)
- Podlega rate limiting (każde pobranie = 1 API call)
- Brak batch download — każda faktura wymaga osobnego requestu

### Brak batch API

KSeF API **nie oferuje** endpointu do zbiorczego pobierania:
- Brak batch download XML (trzeba pobierać pojedynczo)
- Brak WebSocket/streaming — tylko polling

---

## Różnice Subject1 vs Subject2

| Aspekt | Subject1 (sprzedaż) | Subject2 (zakup) |
|---|---|---|
| Kto wystawił fakturę | Twoja firma | Kontrahent |
| API calls per faktura (XML) | 1 | 1 |

---

## Ograniczenia środowiskowe

KSeF API działa w trzech środowiskach z oddzielnymi specyfikacjami:

| Środowisko | URL bazowy | Specyfikacja |
|---|---|---|
| **Produkcja** | `https://api.ksef.mf.gov.pl` | `spec/openapi.json` |
| **Test** | `https://api-test.ksef.mf.gov.pl` | `spec/openapi-test.json` |
| **Demo** | `https://api-demo.ksef.mf.gov.pl` | `spec/openapi-demo.json` |

- Tokeny z jednego środowiska **nie działają** w innym
- Wersje API mogą się różnić między środowiskami
- Dane testowe nie przenoszą się do produkcji

---

## Ograniczenia schematu faktur

### Aktualny schemat: FA(3) v1-0E

- Namespace: `http://crd.gov.pl/wzor/2025/06/25/14855/`
- XSD: `spec/schemat_FA(3)_v1-0E.xsd`
- FA(2) — wycofany, nie jest wspierany

### Znane ograniczenia parsowania

- Schemat FA może się zmienić bez ostrzeżenia
- Nowe pola mogą pojawić się w XML bez aktualizacji XSD w repo
- Monitoring zmian schematu: [SPEC_CHECK_DESIGN.md](SPEC_CHECK_DESIGN.md)

---

## Podsumowanie limitów

| Ograniczenie | Wartość | Gdzie obsłużone |
|---|---|---|
| Rate limit metadata /sec | 8 req/s | `ksef_client.py` → retry 429 |
| Rate limit metadata /min | 16 req/min | `ksef_client.py` → retry 429 |
| Rate limit metadata /hour | **20 req/h** | `ksef_client.py` → retry 429 |
| Rate limit XML /hour | 64 req/h | `ksef_client.py` → retry 429 |
| Minimalny bezpieczny polling interval | 4 min (1 subject) / 7 min (2 subjects) | `scheduler.py` config |
| Max zakres dat | 100 dni UTC (API 2.7.1+, PRD od 23.09.2026); aplikacja od 0.6.5 odpytuje 99 dni | `invoice_monitor.py` → cap |
| Max rekordów per query | 10 000 | `ksef_client.py` → truncation narrowing |
| Max pageSize | 250 | `ksef_client.py` → `PAGINATION_PAGE_SIZE` |
| Min pageSize | 10 | API spec |
| Retry po 429 | max 3, cap 120s | `ksef_client.py` → `_request_with_retry()` |
| Batch download | brak | pojedyncze requesty |

---

## Powiązane dokumenty

- [RATE_LIMITING_DESIGN.md](RATE_LIMITING_DESIGN.md) — plan implementacji globalnego rate limitera
- [LIGHTWEIGHT_POLLING_DESIGN.md](LIGHTWEIGHT_POLLING_DESIGN.md) — architektura lekkiego pollingu dla iOS / SaaS
- [DATABASE_DESIGN.md](DATABASE_DESIGN.md) — baza danych z resumable artifact download
- [SPEC_CHECK_DESIGN.md](SPEC_CHECK_DESIGN.md) — monitoring zmian API i schematu FA

---

**Ostatnia aktualizacja:** 2026-04-17
**Wersja API:** v2.4.0 (produkcja od 2026-04-16)
