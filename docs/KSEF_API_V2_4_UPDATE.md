# KSeF API v2.4.0 — Plan implementacji (Docker Monitor)

**Data:** 2026-04-13
**Deadline produkcji KSeF:** 2026-04-16 (środa)
**Aktualny stan lokalnych speców:** v2.3.0 (build 2.3.0-*-20260331.1)
**Nowy stan:** v2.4.0 (build 2.4.0-*-20260410.1)
**GitHub issues:** #40 (demo), #41 (test)

## Podsumowanie zmian v2.4.0

| Zmiana | Wpływ na monitor |
|--------|-----------------|
| Token operations bez dodatkowych uprawnień | BRAK — nie używamy `/tokens/*` |
| Zakazane znaki Unicode + processing instructions w XML | BRAK — monitor jest read-only |
| Retention 7 dni na `/auth/{ref}` → 410 Gone | NISKI — polling natychmiastowy, ale brak obsługi 410 |
| Problem Details opt-in (header `X-Error-Format`) dla 400/429 | BRAK — nie wysyłamy headera |
| `timestamp` w ForbiddenProblemDetails/UnauthorizedProblemDetails | BRAK — ignorowane przy parsowaniu |
| AllowedIps min/max w POST `/auth/ksef-token` | BRAK — nie ustawiamy AllowedIps |
| Export limits zwiększone | BRAK — nie używamy exportu |

## Taski

### 1. Obsługa HTTP 410 Gone w `_wait_for_auth_status()` — NISKI priorytet

**Plik:** `app/ksef_client.py`, metoda `_wait_for_auth_status()` (~linia 466)

Aktualnie polling loop obsługuje:
- `status.code == 200` → sukces
- `status.code == 100` → retry
- inne → błąd

Po v2.4.0 endpoint `/auth/{referenceNumber}` zwraca **410 Gone** po 7 dniach. W normalnym flow (polling natychmiast po inicjacji auth) to się nie zdarzy, ale warto dodać explicit handling:

```python
# W _wait_for_auth_status(), po response = self._request_with_retry(...)
if response.status_code == 410:
    raise KSeFAuthError("Authentication reference expired (410 Gone)")
```

**Effort:** ~5 linii kodu + test

### 2. Aktualizacja lokalnych specyfikacji OpenAPI

Pobrać aktualne speci i zastąpić lokalne pliki:

- [ ] `spec/openapi-test.json` ← `https://api-test.ksef.mf.gov.pl/docs/v2/openapi.json`
- [ ] `spec/openapi-demo.json` ← `https://api-demo.ksef.mf.gov.pl/docs/v2/openapi.json`
- [ ] `spec/openapi.json` (produkcja) ← po 16 kwietnia: `https://api.ksef.mf.gov.pl/docs/v2/openapi.json`

**Effort:** 3x curl + commit

### 3. Zamknięcie GitHub issues

- [ ] Zamknij #40 (demo) po aktualizacji `spec/openapi-demo.json`
- [ ] Zamknij #41 (test) po aktualizacji `spec/openapi-test.json`

### 4. Aktualizacja wersji w kodzie — OPCJONALNE

**Plik:** `app/main.py` (linia 3-4) — zmienić komentarz z "v2.2.0/v2.3.0" na "v2.4.0"

## Kolejność

1. Pobranie speców test + demo (już dostępne)
2. Dodanie obsługi 410 Gone
3. Commit + push
4. 16 kwietnia: pobranie spec produkcyjnego, commit + push
5. Zamknięcie issues #40 i #41
