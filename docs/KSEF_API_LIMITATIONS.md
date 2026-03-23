# Ograniczenia KSeF API — kompletna dokumentacja

Dokument opisuje wszystkie znane ograniczenia i limity KSeF API v2.2.0, ich wpływ na działanie aplikacji oraz zastosowane obejścia.

---

## Rate limiting (limity zapytań)

Wszystkie endpointy KSeF API podlegają tym samym limitom:

| Limit | Wartość | Okno | Konsekwencja przekroczenia |
|---|---|---|---|
| **Per second** | 10 requestów | 1s sliding window | HTTP 429 |
| **Per minute** | 30 requestów | 60s sliding window | HTTP 429 |
| **Per hour** | 120 requestów | 3600s sliding window | HTTP 429 |

Źródło: pole `x-rate-limits` w OpenAPI spec (`spec/openapi.json`).

### Odpowiedź 429 Too Many Requests

```
HTTP/1.1 429 Too Many Requests
Retry-After: 30
```

- Header `Retry-After` może zawierać liczbę sekund lub datę HTTP
- Aplikacja parsuje oba formaty (`ksef_client.py` → `_request_with_retry()`)
- Max 3 retries po 429, cap na 120s, default 30s jeśli brak headera
- Limity liczone globalnie per token/sesję — obejmują WSZYSTKIE endpointy łącznie

### Wpływ na przetwarzanie dużej liczby faktur

| Scenariusz | API calls | Czas minimalny |
|---|---|---|
| 100 faktur (metadata + XML) | ~204 | ~1h |
| 500 faktur (metadata + XML) | ~1004 | ~8.5h |
| 1000 faktur (metadata + XML) | ~2004 | ~17h |

Szczegółowa analiza i plan naprawy: [RATE_LIMITING_DESIGN.md](RATE_LIMITING_DESIGN.md)

---

## Ograniczenia zapytań o metadane

### Zakres dat — max 90 dni

Endpoint `POST /v2/invoices/query/metadata` akceptuje `dateRange` o maksymalnym rozpiętości **90 dni** (3 miesiące).

```json
{
  "dateRange": {
    "dateType": "Invoicing",
    "from": "2026-01-01T00:00:00.000Z",
    "to":   "2026-03-31T23:59:59.999Z"
  }
}
```

**Obsługa w aplikacji:** `invoice_monitor.py` automatycznie obcina `date_from` do max 90 dni wstecz (`MAX_DATE_RANGE_DAYS = 90`).

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
| Rate limit per second | 10 req/s | `ksef_client.py` → retry 429 |
| Rate limit per minute | 30 req/min | `ksef_client.py` → retry 429 |
| Rate limit per hour | 120 req/h | `ksef_client.py` → retry 429 |
| Max zakres dat | 90 dni | `invoice_monitor.py` → cap |
| Max rekordów per query | 10 000 | `ksef_client.py` → truncation narrowing |
| Max pageSize | 250 | `ksef_client.py` → `PAGINATION_PAGE_SIZE` |
| Min pageSize | 10 | API spec |
| Retry po 429 | max 3, cap 120s | `ksef_client.py` → `_request_with_retry()` |
| Batch download | brak | pojedyncze requesty |

---

## Powiązane dokumenty

- [RATE_LIMITING_DESIGN.md](RATE_LIMITING_DESIGN.md) — plan implementacji globalnego rate limitera
- [DATABASE_DESIGN.md](DATABASE_DESIGN.md) — baza danych z resumable artifact download
- [SPEC_CHECK_DESIGN.md](SPEC_CHECK_DESIGN.md) — monitoring zmian API i schematu FA

---

**Ostatnia aktualizacja:** 2026-03-08
**Wersja API:** v2.2.0 (produkcja od 2026-02-26)
