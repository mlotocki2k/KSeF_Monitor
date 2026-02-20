# Re-Audyt Bezpieczeństwa — KSeF Invoice Monitor v0.3

> Data re-audytu: 2026-02-20
> Commit bazowy: 32f5227 (Security audit: fix all 22 findings)
> Zakres: weryfikacja 22 poprawek + poszukiwanie nowych podatności

---

## Podsumowanie

| Kategoria | Ilość |
|-----------|-------|
| Poprawki potwierdzone (z 22) | **20** |
| Poprawki brakujące | **2** (M7, L1 — nie trafiły do commita) |
| Nowe znaleziska | **5** |
| CRITICAL nowe | 0 |
| HIGH nowe | 1 |
| MEDIUM nowe | 3 |
| LOW nowe | 1 |

---

## Weryfikacja 22 poprawek z audytu

### CRITICAL — 2/2 potwierdzone

| ID | Opis | Status |
|----|------|--------|
| **C1** | Usunięcie `e.response.text` z logów | ✅ Potwierdzone — 0 wystąpień w codebase |
| **C2** | defusedxml zamiast xml.etree.ElementTree | ✅ Potwierdzone — `from defusedxml import ElementTree as ET` |

### HIGH — 5/5 potwierdzone

| ID | Opis | Status |
|----|------|--------|
| **H1** | Non-root USER ksef w Dockerfile | ✅ `useradd -r -u 1000 -m ksef` + `USER ksef` |
| **H2** | Path traversal guard | ✅ `resolve()` + `startswith()` w `invoice_monitor.py:370-375` |
| **H3** | SSRF walidacja webhook URL | ✅ `_validate_webhook_url()` z `ipaddress`/`socket` w `webhook_notifier.py:59-85` |
| **H4** | Session pooling w notifiers | ✅ `self.session = requests.Session()` w `BaseNotifier.__init__()`, `super().__init__()` we wszystkich 5 notifiers |
| **H5** | Secret scanning w CI/CD | ✅ `detect-secrets scan` step w `docker-publish.yml` |

### MEDIUM — 7/8 potwierdzone

| ID | Opis | Status |
|----|------|--------|
| **M1** | Prometheus bind na localhost | ✅ `addr='127.0.0.1'` w `prometheus_metrics.py:72` |
| **M2** | Sanityzacja log injection | ✅ `replace('\n', ' ').replace('\r', ' ')` w `invoice_monitor.py:247` |
| **M3** | MIN_INTERVAL_SECONDS=300 | ✅ Walidacja i korekta w `scheduler.py:17,70-78` |
| **M4** | GitHub Actions pinowane do SHA | ✅ Wszystkie 5 akcji z commit hash |
| **M5** | SSL context w email STARTTLS | ✅ `ssl.create_default_context()` w obu wywołaniach |
| **M6** | Log rotation w docker-compose.env.yml | ✅ `max-size: 10m`, `max-file: 3` |
| **M7** | Pinowanie digest obrazu Docker | ❌ **BRAK** — `FROM python:3.11-slim` bez `@sha256:` |
| **M8** | Sanityzacja danych API | ✅ `_sanitize_field()` w `invoice_monitor.py:275-277` |

### LOW — 2/3 potwierdzone

| ID | Opis | Status |
|----|------|--------|
| **L1** | Walidacja adresów email | ❌ **BRAK** — regex walidacja i `_validate_addresses()` nie trafiły do commita |
| **L2** | Webhook HMAC signing | ✅ `_sign_payload()` z `hmac.new(sha256)` w `webhook_notifier.py:92-101` |
| **L3** | Upper bounds na zależnościach | ✅ `Jinja2<4.0.0`, `defusedxml<1.0.0`, `xhtml2pdf<1.0.0` |

---

## Brakujące poprawki (nie trafiły do commita)

### M7. Docker base image bez pinowania digest

**Plik:** `Dockerfile:1`
**Aktualnie:** `FROM python:3.11-slim`
**Wymagane:** `FROM python:3.11-slim@sha256:<digest>`

---

### L1. Brak walidacji adresów email

**Plik:** `app/notifiers/email_notifier.py`
**Opis:** Brak regex `_EMAIL_RE`, brak metody `_validate_addresses()`, brak `import re`.

---

## Nowe znaleziska

### N1. Brak pliku .dockerignore [HIGH]

**Opis:** Brak `.dockerignore` powoduje że kontekst buildu zawiera niepotrzebne pliki: `.git/`, `audit/`, `examples/`, `data/`, pliki konfiguracyjne. Zwiększa rozmiar image i ryzyko wycieku wrażliwych danych do obrazu Docker.

**Wpływ:** Potencjalny wyciek danych testowych, audytów, konfiguracji do obrazu produkcyjnego.

**Zalecenie:** Stworzyć `.dockerignore`:
```
.git
.github
__pycache__
*.pyc
.venv
venv
.env
.env.example
config.json
config_test.json
data/
audit/
examples/
*.md
```

---

### N2. docker-compose.yml — log rotation zakomentowane [MEDIUM]

**Plik:** `docker-compose.yml:28-33`

**Opis:** Poprawka M6 dodała log rotation do `docker-compose.env.yml`, ale główny plik `docker-compose.yml` nadal ma logging zakomentowane. Jest to domyślny plik wdrożeniowy.

**Zalecenie:** Odkomentować sekcję logging w `docker-compose.yml`.

---

### N3. docker-compose — port Prometheus na 0.0.0.0 [MEDIUM]

**Pliki:** `docker-compose.yml:11`, `docker-compose.env.yml:18`

**Opis:** Port mapping `"8000:8000"` eksponuje metryki na wszystkich interfejsach. Mimo że kod binduje na `127.0.0.1`, Docker port forwarding omija to ograniczenie — ruch z zewnątrz trafia do kontenera.

**Zalecenie:**
```yaml
ports:
  - "127.0.0.1:8000:8000"
```

---

### N4. Brak HEALTHCHECK w Dockerfile [MEDIUM]

**Plik:** `Dockerfile`

**Opis:** Brak dyrektywy `HEALTHCHECK`. Docker/Kubernetes nie może automatycznie wykryć zawieszenia procesu monitora. Brak automatycznego restartu przy awarii.

**Zalecenie:**
```dockerfile
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/metrics', timeout=5)" || exit 1
```

---

### N5. Brak spójności timezone w porównaniach dat [LOW]

**Plik:** `app/invoice_monitor.py:151-158`

**Opis:** Porównania dat w `load_state()` (TTL filtering) mogą mieszać naive i aware datetime gdy `PYTZ_AVAILABLE=True`. Mały wpływ — dotyczy jedynie edge-case'u przy filtrowaniu starych wpisów.

**Wpływ:** Potencjalny wyjątek `TypeError` przy porównaniu naive vs aware datetime. Nie wpływa na bezpieczeństwo, ale na stabilność.

---

## Potwierdzone dobre praktyki

| # | Praktyka | Status |
|---|----------|--------|
| I1 | Hierarchia sekretów (env → Docker secrets → config.json) | ✅ |
| I2 | HTTPS dla wszystkich endpointów API KSeF | ✅ |
| I3 | Jinja2 autoescape dla HTML templates | ✅ |
| I4 | config.json w .gitignore | ✅ |
| I5 | Brak shell injection (brak subprocess, os.system, eval) | ✅ |
| I6 | Brak SQL injection (brak SQL w codebase) | ✅ |
| I7 | Brak unsafe deserialization (brak pickle, yaml.load) | ✅ |
| I8 | Brak hardcoded secrets w kodzie | ✅ |
| I9 | Poprawna obsługa wyjątków (status code, nie response body) | ✅ |
| I10 | RSA-OAEP z SHA256 do szyfrowania tokenów | ✅ |

---

## Priorytet napraw

### Natychmiast
1. **M7** — Pinowanie Docker base image digest
2. **L1** — Walidacja email regex w email_notifier.py
3. **N1** — Stworzenie .dockerignore

### Krótkoterminowe
4. **N3** — Ograniczenie port binding do 127.0.0.1 w docker-compose
5. **N4** — HEALTHCHECK w Dockerfile
6. **N2** — Log rotation w docker-compose.yml

### Długoterminowe
7. **N5** — Spójność timezone w porównaniach dat

---

## Ocena ogólna

**Stan bezpieczeństwa: DOBRY**

20 z 22 poprawek wdrożonych poprawnie. Dwie brakujące (M7, L1) wynikają z utraty zmian przed commitem, nie z błędu w implementacji. Nowe znaleziska dotyczą głównie hardening'u infrastruktury Docker (nie aplikacji). Aplikacja jest gotowa do produkcji po uzupełnieniu brakujących poprawek i stworzeniu `.dockerignore`.
