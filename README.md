# KSeF Invoice Monitor v0.1

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

Monitor faktur w Krajowym Systemie e-Faktur (KSeF). Aplikacja cyklicznie pobiera metadata faktur z API KSeF v2 i wysyła powiadomienia przez Pushover o nowych fakturach sprzedażowych i/lub zakupowych.

Bazuje na oficjalnej specyfikacji API: https://github.com/CIRFMF/ksef-docs

---

## Struktura projektu

```
ksef_monitor_v0_1/
├── main.py                      # Entry point — logging, signal handling, bootstrap
├── app/
│   ├── __init__.py
│   ├── config_manager.py        # Wczytanie i walidacja config.json
│   ├── secrets_manager.py       # Sekretne wartości z env / Docker secrets / config
│   ├── ksef_client.py           # Klient API KSeF v2 (autentykacja + zapytania)
│   ├── invoice_monitor.py       # Główna pętla monitorowania + formatowanie
│   ├── pushover_notifier.py     # Klient API Pushover
│   └── scheduler.py             # Elastyczny system schedulowania (5 trybów)
├── config.example.json          # Szablon konfiguracji
├── .env.example                 # Szablon zmiennych środowiska
├── requirements.txt             # Zależności Python
├── Dockerfile                   # Obraz kontenerowy (Python 3.11-slim)
├── docker-compose.yml           # Uruchomienie podstawowe
├── docker-compose.env.yml       # Uruchomienie z plikiem .env
├── docker-compose.secrets.yml   # Produkcja — Docker Swarm secrets
└── .gitignore
```

Katalog `data/` powstaje w runtime i zawiera plik stanu `last_check.json`.

---

## Wymagania

- Python 3.9+ lub Docker
- Token autoryzacyjny z portalu KSeF (https://ksef.gov.pl)
- Konto w Pushover (https://pushover.net) — User Key + API Token aplikacji

### Zależności Python

| Pakiet | Wersja | Przeznaczenie |
|---|---|---|
| `requests` | 2.31.0 | HTTP calls do KSeF API i Pushover API |
| `python-dateutil` | 2.8.2 | Parsing dat |
| `cryptography` | >=41.0.0 | RSA-OAEP encryption tokena w auth flow |

---

## Konfiguracja

Skopiuj `config.example.json` do `config.json` i uzupełnij wartości.

### Sekcja `ksef`

| Pole | Opis |
|---|---|
| `environment` | `test` \| `demo` \| `prod` — wyznacza base URL API (patrz tabelka poniżej). |
| `nip` | 10-cyfrowy NIP podmiotu. |
| `token` | Token autoryzacyjny z portalu KSeF. Może być podany tu lub przez env variable / Docker secret (patrz [Sekretne wartości](#sekretne-wartości)). |

Base URLs przypisane automatycznie:

| Środowisko | URL |
|---|---|
| `prod` | `https://api.ksef.mf.gov.pl` |
| `demo` | `https://api-demo.ksef.mf.gov.pl` |
| `test` | `https://api-test.ksef.mf.gov.pl` |

### Sekcja `pushover`

| Pole | Opis |
|---|---|
| `user_key` | User Key z konta Pushover. |
| `api_token` | API Token aplikacji w Pushover. |

### Sekcja `monitoring`

| Pole | Default | Opis |
|---|---|---|
| `subject_types` | `["Subject1", "Subject2"]` | Typy faktur do monitorowania. `Subject1` = sprzedażowe (Ty = sprzedawca), `Subject2` = zakupowe (Ty = nabywca). Jedno zapytanie API na każdy typ. |
| `date_type` | `"Invoicing"` | Typ daty w zakresie zapytania. Dozwolone wartości: `Issue` (data wystawienia), `Invoicing` (data przyjęcia w KSeF), `PermanentStorage` (data trwałego zapisu). Fallback na `Invoicing` przy niepoprawnej wartości. |
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

---

## Sekretne wartości

Trzy wartości (`token`, `user_key`, `api_token`) mogą być dostarczone na trzy sposoby. Kolejność priorytetów od najwyższego:

1. Zmienne środowiska
2. Docker secrets (pliki w `/run/secrets/`)
3. Wartość wpisana bezpośrednio w `config.json`

| Wartość | Zmienne środowiska | Docker secret |
|---|---|---|
| KSeF token | `KSEF_TOKEN` | `ksef_token` |
| Pushover User Key | `PUSHOVER_USER_KEY` | `pushover_user_key` |
| Pushover API Token | `PUSHOVER_API_TOKEN` | `pushover_api_token` |

---

## Uruchomienie

### Lokalne (bez Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json   # uzupełnij wartości
python main.py
```

### Docker — podstawowe

Sekretne wartości wpisane bezpośrednio w `config.json`. Najprostsze podejście do testowania.

```bash
cp config.example.json config.json   # uzupełnij wszystkie wartości
docker compose -f docker-compose.yml up -d
```

### Docker — z plikiem .env

Sekretne wartości w osobnym pliku `.env`. Konfiguracja podzielona na `config.secure.json` (bez sekretów) i `.env` (sam sekrety).

```bash
cp config.example.json config.secure.json   # uzupełnij tylko pola niesekretne
cp .env.example .env                        # uzupełnij KSEF_TOKEN, PUSHOVER_*
chmod 600 .env
docker compose -f docker-compose.env.yml up -d
```

### Docker Swarm — Docker secrets (produkcja)

Sekretne wartości przechowywane w Docker Swarm. Wymaga uruchomionego Swarm.

```bash
# Utworzenie sekretów
echo "twoj-ksef-token"          | docker secret create ksef_token -
echo "twoj-pushover-user-key"   | docker secret create pushover_user_key -
echo "twoj-pushover-api-token"  | docker secret create pushover_api_token -

# config.secure.json bez sekretów
cp config.example.json config.secure.json

# Deploy
docker swarm init   # jeśli jeszcze nie zrobione
docker compose -f docker-compose.secrets.yml up -d
```

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

## Powiadomienia Pushover

### Tytuły — zależne od `subjectType`

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
Numer KSeF: <numer KSeF>
```

**Subject2** (zakupowa — Ty = nabywca) — wyświetla się sprzedawca:

```
Od: <nazwa sprzedawcy> - NIP <NIP>
Nr Faktury: ...
Data: ...
Numer KSeF: ...
```

**Inne** — wyświetlają się oba:

```
Od: <sprzedawca> - NIP ...
Do: <nabywca>   - NIP ...
Nr Faktury: ...
Data: ...
Numer KSeF: ...
```

### Pozostałe powiadomienia

| Wydarzenie | Tytuł | Priority |
|---|---|---|
| Start aplikacji | KSeF Monitor Started | `-1` |
| Zatrzymanie | KSeF Monitor Stopped | `-1` |
| Błąd w pętli | KSeF Monitor Error | `1` |
| Test na starcie | KSeF Monitor Test | `0` |

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

Dokumentacja API: https://api.ksef.mf.gov.pl/docs/v2/

---

## Troubleshooting

**Brak powiadomień:**
- Sprawdź poprawność User Key i API Token w Pushover.
- Upewnij się, że aplikacja Pushover jest zainstalowana na urządzeniu.
- Przejrzyć logi: `docker logs ksef-invoice-monitor -f`

**Błędy autentykacji:**
- Zweryfikuj token KSeF — tokeny mają ograniczoną żywotność, regeneruj jeśli wygasł.
- Sprawdź format NIP (dokładnie 10 cyfr, bez spacji).
- Upewnij się, że `environment` w konfiguracji odpowiada portalowi, z którego pochodzi token.

**Walidacja JSON:**
```bash
python3 -m json.tool config.json
```

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
