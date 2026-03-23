# Audyt Bezpieczenstwa -- KSeF Monitor Docker (v0.4)

> **Data audytu:** 2026-03-19
> **Audytor:** Claude Opus 4.6 (1M context)
> **Zakres:** Pelny przeglad bezpieczenstwa kodu zrodlowego, konfiguracji Docker, zaleznosci, API REST, kanaly powiadomien
> **Wersja aplikacji:** v0.4 (package __version__ = "2.0.0")
> **Commit:** HEAD brancha main (na dzien 2026-03-19)
> **Metodologia:** Statyczna analiza kodu, przeglad architektury, analiza zaleznosci, analiza konfiguracji Docker

---

## 1. Podsumowanie wykonawcze

KSeF Monitor to aplikacja Python/Docker monitorujaca faktury w Krajowym Systemie e-Faktur. Projekt wykazuje **dojrzaly poziom bezpieczenstwa** -- widoczne sa liczne poprawki z poprzednich audytow (2026-02). Niemniej zidentyfikowano **1 finding CRITICAL**, **2 HIGH**, **4 MEDIUM** i **3 LOW**.

### Metryka znalezisk

| Waznosc | Ilosc | Opis |
|---------|-------|------|
| **CRITICAL** | 1 | Produkcyjne sekrety w pliku config.json na dysku |
| **HIGH** | 2 | Brak walidacji SSRF w notifierach Discord/Slack; Python 3.9 EOL |
| **MEDIUM** | 4 | Pinowanie zaleznosci z zakresami; brak CSP; brak timeoutu sesji DB; logowanie auto-generowanego tokenu |
| **LOW** | 3 | Brak sprawdzania uprawnien config.json; brak limitu rozmiaru odpowiedzi XML; minor info disclosure |
| **INFO** | 2 | Rekomendacje dotyczace hardening |

**Ocena ogolna:** Aplikacja jest dobrze zabezpieczona w porownaniu do typowych projektow open-source. Wiekszosc wczesniejszych finding-ow zostala zaadresowana. Kluczowy problem to fizyczna obecnosc produkcyjnych sekretow na dysku.

---

## 2. Stos technologiczny

### 2.1 Jezyk i framework

| Komponent | Wersja | Uwagi |
|-----------|--------|-------|
| Python | 3.11-slim (Docker), 3.9 (.venv lokalne) | Dockerfile pinuje 3.11 z digest SHA256 |
| FastAPI | >=0.115.0,<1.0.0 | REST API (opcjonalne) |
| uvicorn | >=0.34.0,<1.0.0 | ASGI server |
| SQLAlchemy | >=2.0.0,<3.0.0 | ORM + SQLite |
| Jinja2 | >=3.1.6,<4.0.0 | Szablony powiadomien |

### 2.2 Biblioteki bezpieczenstwa

| Komponent | Wersja | Cel |
|-----------|--------|-----|
| cryptography | ==46.0.5 | RSA-OAEP szyfrowanie tokenu KSeF |
| defusedxml | >=0.7.1,<1.0.0 | Bezpieczne parsowanie XML (anty-XXE) |
| slowapi | >=0.1.9,<1.0.0 | Rate limiting REST API |
| detect-secrets | v1.5.0 | Pre-commit hook + CI scanning |

### 2.3 Architektura

```
[KSeF API] <--HTTPS--> [KSeFClient] --> [InvoiceMonitor] --> [NotificationManager]
                                              |                    |-- PushoverNotifier
                                              |                    |-- DiscordNotifier
                                              |                    |-- SlackNotifier
                                              |                    |-- EmailNotifier
                                              |                    |-- WebhookNotifier
                                              |
                                        [Database SQLite]
                                              |
                                        [REST API FastAPI] <--HTTP--> [klient]
                                              |
                                        [Prometheus /metrics]
```

### 2.4 Powierzchnia ataku

| Wektor | Opis | Ekspozycja |
|--------|------|-----------|
| REST API (port 8080) | FastAPI, opcjonalnie wlaczane | Domyslnie `127.0.0.1` |
| Prometheus (port 8000) | Metryki `/metrics` | Domyslnie `127.0.0.1`, w Docker `0.0.0.0` |
| Plik konfiguracyjny | JSON z sekretami | Montowany read-only |
| Baza SQLite | Dane faktur, NIP-y | Wolumin Docker `/data` |
| Kanaly powiadomien | HTTP(S) do zewn. serwisow | Outbound only |
| KSeF API | HTTPS z tokenem Bearer | Outbound only |

---

## 3. Analiza zaleznosci

### 3.1 Zaleznosci z pinowanymi wersjami

| Biblioteka | Wersja w requirements.txt | Uwagi |
|------------|--------------------------|-------|
| requests | ==2.32.5 | Pinowana scisle |
| python-dateutil | ==2.9.0.post0 | Pinowana scisle |
| cryptography | ==46.0.5 | Pinowana scisle |
| prometheus-client | ==0.24.1 | Pinowana scisle |
| pytz | ==2026.1.post1 | Pinowana scisle |
| reportlab | ==4.4.10 | Pinowana scisle |
| qrcode | ==8.2 | Pinowana scisle |

### 3.2 Zaleznosci z zakresami (MEDIUM -- patrz F-04)

| Biblioteka | Zakres | Ryzyko |
|------------|--------|--------|
| Jinja2 | >=3.1.6,<4.0.0 | Moze podbic do wersji z regresja |
| defusedxml | >=0.7.1,<1.0.0 | j.w. |
| xhtml2pdf | >=0.2.16,<1.0.0 | j.w. |
| SQLAlchemy | >=2.0.0,<3.0.0 | Szeroki zakres major |
| alembic | >=1.13.0,<2.0.0 | j.w. |
| fastapi | >=0.115.0,<1.0.0 | j.w. |
| uvicorn | >=0.34.0,<1.0.0 | j.w. |
| slowapi | >=0.1.9,<1.0.0 | j.w. |

### 3.3 Znane CVE

> **Uwaga:** Brak dostepu do WebSearch/WebFetch w trakcie audytu. Projekt posiada `pip-audit --strict` w CI workflow `tests.yml` -- pipeline automatycznie wykrywa znane CVE. Ponizsze oparte na wiedzy do maja 2025:

| Biblioteka | Status CVE (do maja 2025) |
|------------|--------------------------|
| requests 2.32.5 | Brak znanych CVE w tej wersji |
| cryptography 46.0.5 | Aktualna; poprzednie CVE naprawione w 42.x+ |
| Jinja2 3.1.6 | Aktualna; CVE-2024-56201 naprawione w 3.1.5 |
| SQLAlchemy 2.0.x | Brak znanych CVE w 2.0 |
| defusedxml 0.7.1 | Brak znanych CVE |

**Rekomendacja:** Uruchomic `pip-audit -r requirements.txt` lokalnie dla aktualnych wynikow.

---

## 4. Znaleziska bezpieczenstwa

---

### F-01 [CRITICAL] Produkcyjne sekrety w pliku config.json na dysku

**Lokalizacja:** `config.json` (root projektu)

**Opis:**
Plik `config.json` na dysku zawiera produkcyjne sekrety w jawnym tekscie:
- Token KSeF produkcyjny: `[REDACTED]` (linia 5)
- NIP produkcyjny: `[REDACTED]` (linia 4)
- Klucze Pushover: `[REDACTED]` / `[REDACTED]` (linie 16-17)

Plik jest w `.gitignore` (nie trafi do repo), ale:
1. Lezy na dysku developerskim bez ochrony
2. Moze trafic do backup-ow, synchronizacji chmurowej, IDE cache
3. Kazdy z dostepem do systemu plikow ma pelny dostep do sekretow
4. Narzedzie `detect-secrets` w `.pre-commit-config.yaml` nie chroni juz istniejacych plikow lokalnych

**Dowod:**
```json
"token": "[REDACTED — production KSeF token]"
"user_key": "[REDACTED — Pushover user key]"
"api_token": "[REDACTED — Pushover API token]"
```

**Wplyw:** Pelny dostep do KSeF API produkcyjnego (odczyt faktur, metadanych). Pelny dostep do konta Pushover (mozliwosc wysylania powiadomien w imieniu wlasciciela).

**CVSS v3.1:** 8.6 (High) -- AV:L/AC:L/PR:L/UI:N/S:C/C:H/I:N/A:N

**Remediacja:**
1. **Natychmiastowa:** Przeniesc sekrety do zmiennych srodowiskowych lub Docker secrets. Uzyc `config.secure.json` (juz istnieje w `examples/`) ktory nie zawiera zadnych sekretow.
2. Zrotowac token KSeF (wygenerowac nowy w portalu KSeF)
3. Zrotowac klucze Pushover
4. Ustawic `chmod 600` na pliku config.json jesli musi istniec
5. Rozwazyc uzycie `docker-compose.secrets.yml` lub `docker-compose.env.yml` (oba sa juz gotowe)

---

### F-02 [HIGH] Brak walidacji SSRF dla webhook URL-i Discord i Slack

**Lokalizacja:**
- `app/notifiers/discord_notifier.py` -- linia 40: `self.webhook_url = discord_config.get("webhook_url")`
- `app/notifiers/slack_notifier.py` -- linia 39: `self.webhook_url = slack_config.get("webhook_url")`

**Opis:**
Notifier `WebhookNotifier` posiada solidna walidacje SSRF (`_validate_webhook_url()` z DNS resolution check + re-walidacja przy kazdym uzyciu). Jednak `DiscordNotifier` i `SlackNotifier` nie implementuja **zadnej** walidacji URL-a webhook. Uzytkownik podaje URL w konfiguracji, ktory jest uzywany bez sprawdzenia.

Chociaz w praktyce Discord/Slack URL-e sa publiczne, atakujacy ktory ma dostep do pliku konfiguracyjnego moze ustawic webhook_url na adres wewnetrzny (np. `http://169.254.169.254/latest/meta-data/` na AWS, `http://localhost:8080/api/v1/monitor/trigger`), co pozwoli na:
- Skanowanie sieci wewnetrznej
- Dostep do metadata service chmury
- Triggerowanie wewnetrznych endpoint-ow

Oba notifiery maja `allow_redirects=False` (dobra praktyka), ale brak walidacji samego URL-a jest niespojny z podejsciem w `WebhookNotifier`.

**Dowod:**
```python
# discord_notifier.py:40 -- brak walidacji
self.webhook_url = discord_config.get("webhook_url")

# webhook_notifier.py:46 -- pelna walidacja
self.url = raw_url if self._validate_webhook_url(raw_url) else None
```

**CVSS v3.1:** 5.4 (Medium) -- AV:N/AC:L/PR:L/UI:N/S:U/C:L/I:L/A:N (wymaga dostepu do konfiguracji)

**Remediacja:**
1. Wyodrebnic `_validate_webhook_url()` do `BaseNotifier` lub modulu utils
2. Zastosowac walidacje w `DiscordNotifier.__init__()` i `SlackNotifier.__init__()`
3. Dodac `_revalidate_url()` przed kazdym wysylaniem (tak jak w WebhookNotifier)

---

### F-03 [HIGH] Python 3.9 w srodowisku lokalnym -- End of Life

**Lokalizacja:** `.venv/pyvenv.cfg` -- Python 3.9

**Opis:**
Lokalne srodowisko deweloperskie uzywa Python 3.9, ktory osiagnal End of Life w pazdzierniku 2025. Nie otrzymuje juz poprawek bezpieczenstwa. Docker image prawidlowo uzywa Python 3.11-slim z pinowanym digest SHA256, wiec produkcja jest chroniona. Jednak:
- Testy lokalne moga nie wykryc bledow specyficznych dla 3.11
- Lokalne uruchomienie (`python main.py` bez Docker) jest podatne na niezalatane CVE w interpreterze

**CVSS v3.1:** 5.3 (Medium) -- AV:L/AC:L/PR:N/UI:N/S:U/C:L/I:L/A:L

**Remediacja:**
1. Uaktualnic lokalne .venv do Python 3.11+
2. Usunac Python 3.9 z macierzy testow CI (tests.yml testuje 3.9, 3.11, 3.12)

---

### F-04 [MEDIUM] Niepinowane zakresy wersji krytycznych zaleznosci

**Lokalizacja:** `requirements.txt`, linie 8, 11, 14, 19-20, 23-25

**Opis:**
8 z 13 zaleznosci w `requirements.txt` uzywa zakresow (`>=X,<Y`) zamiast pinowanych wersji (`==X`). Przy `pip install -r requirements.txt` na swiezym srodowisku (np. budowa Docker image) moze zostac pobrana nowsza wersja z regresja, backdoor-em, lub niekompatybilnoscia. Krytyczne zaleznosci:

- `SQLAlchemy>=2.0.0,<3.0.0` -- zakres obejmuje >24 minor releases
- `fastapi>=0.115.0,<1.0.0` -- aktywnie rozwijany, czeste breaking changes
- `Jinja2>=3.1.6,<4.0.0` -- moze podbic do wersji z innymi domyslnymi ustawieniami autoescape

**CVSS v3.1:** 4.8 (Medium) -- AV:N/AC:H/PR:N/UI:N/S:U/C:L/I:L/A:N

**Remediacja:**
1. Pinowac wszystkie zaleznosci do dokladnych wersji (`==`)
2. Uzywac `pip-compile` (pip-tools) lub `uv lock` do generowania lockfile
3. Workflow `check-requirements-updates.yml` juz istnieje -- zapewnic regularne aktualizacje

---

### F-05 [MEDIUM] Logowanie auto-generowanego tokenu API do stdout

**Lokalizacja:** `app/config_manager.py`, linie 470-474

**Opis:**
Gdy API jest wlaczone bez `auth_token`, system auto-generuje bezpieczny token (`secrets.token_urlsafe(48)`) -- co jest dobra praktyka. Jednak loguje pierwsze 8 znakow tokenu do stdout:

```python
logger.warning("  %s...", generated_token[:8])
```

W srodowisku Docker logi sa przechowywane przez sterownik logowania (`json-file`). Jesli logi sa forwarded do centralnego systemu logowania (ELK, Loki, CloudWatch), prefiks tokenu moze byc uzyty do zawezenia ataku brute-force. Ponadto pelny token jest przechowywany jedynie w pamieci -- po restarcie kontenera generowany jest nowy, co w praktyce oznacza ze "auto-generated" token jest efemeryczny.

**CVSS v3.1:** 3.3 (Low) -- AV:L/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N

**Remediacja:**
1. Nie logowac nawet prefiksu tokenu. Zamiast tego logowac jedynie informacje ze token zostal auto-wygenerowany
2. Lub: zapisac token do pliku z uprawnieniami 600 zamiast logowania

---

### F-06 [MEDIUM] Brak naglokowka Content-Security-Policy w REST API

**Lokalizacja:** `app/api/__init__.py`, linie 92-98

**Opis:**
Middleware `add_security_headers` dodaje `X-Content-Type-Options`, `X-Frame-Options` i `Cache-Control`, ale nie ustawia naglowka `Content-Security-Policy`. Chociaz API zwraca jedynie JSON (nie HTML), brak CSP moze byc problemem jesli:
- `/docs` (Swagger UI) jest wlaczone -- renderuje HTML z inline JS
- Odpowiedz bledna zostanie wyswietlona w przegladarce

**CVSS v3.1:** 3.1 (Low) -- AV:N/AC:H/PR:N/UI:R/S:U/C:L/I:N/A:N

**Remediacja:**
Dodac do middleware:
```python
response.headers["Content-Security-Policy"] = "default-src 'none'"
```
Lub dla `/docs`: `"default-src 'self'; script-src 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; style-src 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com"`

---

### F-07 [MEDIUM] Brak timeoutu i limitu rozmiaru na sesje SQLAlchemy

**Lokalizacja:** `app/database.py`, linia 312; `app/api/routers/invoices.py`, linia 53

**Opis:**
Sesje SQLAlchemy sa tworzone przez `db.get_session()` i zamykane w bloku `try/finally`, co jest poprawne. Jednak:
1. Brak `expire_on_commit=False` w sessionmaker -- sesja po commit() invaliduje wszystkie obiekty
2. Brak konfiguracji `pool_timeout` i `pool_recycle` w engine -- w dlugodzialajacym procesie moze dojsc do wyciekow polaczen
3. W endpointach API brak mechanizmu przerywania dlugo trwajacych zapytan (np. `PRAGMA busy_timeout=5000` jest ustawiony, ale na poziomie ORM nie ma timeoutu)

**CVSS v3.1:** 4.3 (Medium) -- AV:N/AC:L/PR:L/UI:N/S:U/C:N/I:N/A:L

**Remediacja:**
1. Dodac do `create_engine()`:
   ```python
   pool_timeout=30,
   pool_recycle=3600,
   pool_pre_ping=True,
   ```
2. Rozwazyc `expire_on_commit=False` w sessionmaker dla API endpoints
3. Dodac context manager pattern zamiast manualnego `try/finally`

---

### F-08 [LOW] Brak sprawdzania uprawnien pliku konfiguracyjnego

**Lokalizacja:** `app/secrets_manager.py`, linia 90; `app/config_manager.py`, linia 40

**Opis:**
Plik konfiguracyjny jest otwierany i odczytywany bez sprawdzenia uprawnien systemowych. W srodowisku nie-Docker (bare metal) plik config.json moze miec zbyt otwarte uprawnienia (np. 644 lub 777), co pozwala innym uzytkownikom systemu odczytac sekrety.

Docker Compose montuje config jako `:ro` -- w kontenerze plik jest zabezpieczony. Problem dotyczy wylacznie uruchomienia poza Docker.

**CVSS v3.1:** 2.9 (Low) -- AV:L/AC:H/PR:L/UI:N/S:U/C:L/I:N/A:N

**Remediacja:**
Dodac sprawdzenie uprawnien na starcie:
```python
import stat
mode = self.config_path.stat().st_mode
if mode & (stat.S_IRGRP | stat.S_IROTH):
    logger.warning("Config file has overly permissive permissions: %o. Recommended: 600", stat.S_IMODE(mode))
```

---

### F-09 [LOW] Brak limitu rozmiaru odpowiedzi XML z KSeF API

**Lokalizacja:** `app/ksef_client.py`, linia 796: `xml_content = response.text`

**Opis:**
Odpowiedz XML z endpointu `/v2/invoices/ksef/{ksefNumber}` jest wczytywana w calosci do pamieci (`response.text`) bez limitu rozmiaru. Zlosliwy lub uszkodzony XML moglby miec bardzo duzy rozmiar, powodujac OOM kill kontenera.

W praktyce KSeF API nie zwraca bardzo duzych faktur, ale brak limitu jest zlym wzorcem defensywnym.

**CVSS v3.1:** 3.1 (Low) -- AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:N/A:L

**Remediacja:**
```python
MAX_XML_SIZE = 10 * 1024 * 1024  # 10 MB
content_length = int(response.headers.get('Content-Length', 0))
if content_length > MAX_XML_SIZE:
    logger.error("XML response too large: %d bytes", content_length)
    return None
xml_content = response.text
if len(xml_content) > MAX_XML_SIZE:
    logger.error("XML content exceeds size limit")
    return None
```

---

### F-10 [LOW] Wyciek wersji w health endpoint

**Lokalizacja:** `app/api/routers/monitor.py`, linia 35; `app/api/schemas.py`, linia 104

**Opis:**
Endpoint `/api/v1/monitor/health` (dostepny bez uwierzytelnienia) zwraca dokladna wersje aplikacji (`"version": "0.4.0"`). Informacja ta moze ulatwic atakujacemu identyfikacje znanych podatnosci specyficznych dla danej wersji.

Poprzedni audyt juz usunal `auth_enabled` z health response (F-09 w re_audit), ale wersja pozostaje.

**CVSS v3.1:** 2.1 (Low) -- AV:N/AC:H/PR:N/UI:N/S:U/C:L/I:N/A:N

**Remediacja:**
Zwracac wersje wylacznie gdy uzytkownik jest uwierzytelniony, lub zastapic szczegolowa wersje generickim stringiem (np. `"version": "0.x"`).

---

## 5. Dobre praktyki (Positive Findings)

Projekt implementuje wiele dojrzalych praktyk bezpieczenstwa. Ponizsze zasluguja na wyroznienie:

### P-01 Bezpieczne parsowanie XML (defusedxml)
`app/invoice_xml_parser.py` uzywa `defusedxml.ElementTree` zamiast `xml.etree.ElementTree`, co chroni przed XXE (XML External Entity), billion laughs i innymi atakami XML.

### P-02 Timing-safe porownywanie tokenow
`app/api/__init__.py:80` uzywa `hmac.compare_digest()` do porownywania tokenow Bearer, co zapobiega atakom timing side-channel.

### P-03 SandboxedEnvironment Jinja2
`app/template_renderer.py:116` uzywa `SandboxedEnvironment` z `select_autoescape(["html"])`, co chroni przed SSTI (Server-Side Template Injection) i XSS w szablonach email.

### P-04 Ochrona SSRF w WebhookNotifier
`app/notifiers/webhook_notifier.py:62-85` implementuje:
- Walidacje schematu URL (tylko https/http)
- DNS resolution z sprawdzeniem prywatnych IP (`ipaddress.is_private`, `is_loopback`, `is_link_local`)
- Re-walidacje DNS przed kazdym request-em (anti DNS-rebinding)
- `allow_redirects=False` i `max_redirects=0`
- HMAC-SHA256 signing payload

### P-05 Rate limiting na wielu poziomach
- **KSeF API:** `app/rate_limiter.py` -- sliding window (per-second, per-minute, per-hour) z thread-safety i `time.monotonic()`
- **REST API:** `slowapi` z konfigurowalnym limitem (domyslnie 60/min)
- **Scheduler:** `MIN_INTERVAL_SECONDS = 300` (5 min minimum)

### P-06 Bezpieczenstwo Docker
- Non-root user `ksef` (UID 1000)
- `no-new-privileges:true` w docker-compose
- `ulimits: core: 0` (bez core dump-ow z sekretami)
- Digest-pinowany base image (`python:3.11-slim@sha256:...`)
- Health check
- Usuwanie build deps (gcc, pkg-config) po instalacji
- `entrypoint.sh` -- `gosu` zamiast `su`/`sudo`, `umask 077`
- Log rotation: `max-size: 10m`, `max-file: 3`

### P-07 Secret management
- `SecretsManager` -- priorytet: env var > Docker secrets > config file
- `config.secure.json` -- wzorcowy plik bez sekretow
- Docker secrets support (`docker-compose.secrets.yml`)
- Environment variables support (`docker-compose.env.yml`)
- Ostrzezenie w logach gdy sekrety ladowane z pliku config

### P-08 Bezpieczenstwo API
- Bearer token auth z HMAC compare
- Auto-generowanie silnego tokenu jesli nie ustawiony (`secrets.token_urlsafe(48)`)
- Walidacja minimalnej dlugosci tokenu (32 znakow)
- Odrzucanie CORS wildcard `*` gdy auth jest wlaczone
- Nagliwki bezpieczenstwa: `X-Content-Type-Options`, `X-Frame-Options`, `Cache-Control`
- Automatyczne wylaczanie `/docs` w produkcji (`ksef.environment == "prod"`)
- Brak stack trace-ow w odpowiedziach bledow produkcyjnych
- Pydantic response models -- tylko zadeklarowane pola sa serializowane

### P-09 SQL Injection protection
Wszystkie zapytania uzywaja SQLAlchemy ORM (parametryzowane). Brak raw SQL w endpointach API. Jedyny raw SQL to `PRAGMA` w setup (bezpieczne -- brak user input).

### P-10 Input validation
- Regex walidacja NIP (`^\d{10}$`) i KSeF number w API endpoints
- Walidacja `sort_by` i `sort_order` przez FastAPI Query patterns
- `search` term ograniczony do 100 znakow (`search[:100]`)
- Sanityzacja pol z API (`_sanitize_field` -- null bytes, max length)
- Email address regex validation
- Email subject CRLF injection protection

### P-11 Atomic writes
`InvoiceMonitor.save_state()` uzywa atomic write pattern (write to .tmp, fsync, rename) -- bezpieczne przy naglem zatrzymaniu kontenera.

### P-12 CI/CD Security
- Secret scanning w `docker-publish.yml` (`detect-secrets scan`)
- Bandit SAST w `tests.yml`
- `pip-audit --strict` w `tests.yml`
- GitHub Actions pinowane do SHA (nie tagow)
- Minimalne uprawnienia: `permissions: contents: read`

### P-13 Path traversal protection
`invoice_monitor.py:567-569` -- `resolve()` + `is_relative_to()` guard na folder_structure placeholders.

### P-14 TLS enforcement
- `session.verify = True` w `BaseNotifier` i `KSeFClient`
- `ssl.create_default_context()` w EmailNotifier STARTTLS
- KSeF base URLs sa wylacznie HTTPS

---

## 6. Klasyfikacja OWASP Top 10 (2021)

| OWASP | Finding | Status |
|-------|---------|--------|
| A01 Broken Access Control | Health endpoint bez auth -- by design | INFO |
| A02 Cryptographic Failures | F-01 sekrety na dysku | CRITICAL |
| A03 Injection | SQL: OK (ORM), XSS: OK (autoescape), SSTI: OK (sandbox), XXE: OK (defusedxml), CRLF: OK | PASS |
| A04 Insecure Design | F-02 niespojne SSRF | HIGH |
| A05 Security Misconfiguration | F-04 zakresy wersji, F-06 brak CSP | MEDIUM |
| A06 Vulnerable Components | F-03 Python 3.9 EOL | HIGH |
| A07 Auth Failures | Token auth poprawny (HMAC compare) | PASS |
| A08 Software and Data Integrity | CI/CD OK, Docker digest pinning OK | PASS |
| A09 Logging and Monitoring | F-05 logowanie tokenu, ogolnie dobre | MEDIUM |
| A10 SSRF | WebhookNotifier OK; Discord/Slack brak walidacji | HIGH |

---

## 7. Rekomendacje priorytetyzowane

### Natychmiastowe (tydzien 1)
1. **[F-01]** Przeniesc sekrety z `config.json` do env vars / Docker secrets. Zrotowac tokeny.
2. **[F-02]** Dodac walidacje SSRF do Discord i Slack notifierow (wyodrebnic z WebhookNotifier).

### Krotkoterminowe (tydzien 2-4)
3. **[F-03]** Uaktualnic lokalne .venv do Python 3.11+.
4. **[F-04]** Pinowac wszystkie zaleznosci do dokladnych wersji.
5. **[F-05]** Nie logowac prefiksu auto-generowanego tokenu.
6. **[F-06]** Dodac CSP header.

### Srednoterminowe (miesiac 2-3)
7. **[F-07]** Skonfigurowac pool_timeout i pool_recycle w SQLAlchemy engine.
8. **[F-08]** Sprawdzac uprawnienia pliku konfiguracyjnego na starcie.
9. **[F-09]** Dodac limit rozmiaru odpowiedzi XML.
10. **[F-10]** Ukryc dokladna wersje w health endpoint.

### Dodatkowe hardening (opcjonalne)
11. Dodac `read_only: true` do docker-compose (filesystem read-only, zapisywalny tylko `/data`)
12. Rozwazyc `seccomp` profil dla kontenera
13. Dodac `pip-audit` do pre-commit hooks (nie tylko CI)

---

## 8. Porownanie z poprzednim audytem

| Aspekt | Audyt 2026-02-20 | Audyt 2026-03-19 |
|--------|-------------------|-------------------|
| Scope | v0.3, 22 findings + 5 nowych | v0.4, pelny fresh audit |
| CRITICAL | 0 nowych | 1 (sekrety na dysku) |
| HIGH | 1 nowy | 2 (SSRF Discord/Slack, Python 3.9) |
| Poprawki z audytu 02-20 | 20/22 potwierdzone | Wszystkie 20 nadal obecne |
| Nowe pozytywne | -- | P-05 rate limiting, P-08 API security, P-09 SQL |
| Docker digest pinning (M7) | Brak | Naprawione (`@sha256:...` w Dockerfile) |

---

## 9. Podsumowanie

KSeF Monitor v0.4 to dobrze zabezpieczona aplikacja z dojrzalym podejsciem do bezpieczenstwa. Poprzednie audyty doprowadzily do wdrozenia licznych mechanizmow ochronnych (defusedxml, SSRF validation, rate limiting, Docker hardening, CI security scanning).

Najwazniejszy finding (**F-01 CRITICAL**) dotyczy higieny sekretow -- produkcyjne tokeny leza w pliku na dysku deweloperskim. Jest to problem operacyjny, nie architektoniczny -- infrastruktura do bezpiecznego zarzadzania sekretami (SecretsManager, Docker secrets, env vars) juz istnieje i jest gotowa do uzycia.

Dwa finding-i **HIGH** (F-02 SSRF w Discord/Slack, F-03 Python 3.9 EOL) wymagaja stosunkowo prostych poprawek.

**Ogolna ocena bezpieczenstwa: 7.5/10** -- powyzej sredniej dla projektow open-source tej skali.

---

*Raport wygenerowany: 2026-03-19*
*Audytor: Claude Opus 4.6 (1M context)*
*Narzedzia: statyczna analiza kodu, przeglad konfiguracji, analiza architektury*
*Ograniczenia: brak dostepu do WebSearch/WebFetch (CVE lookup oparty na wiedzy do maja 2025; CI pipeline z pip-audit pokrywa biezace CVE)*
