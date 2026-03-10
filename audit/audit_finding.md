# Audyt Bezpieczeństwa — KSeF Invoice Monitor v0.3

> Data audytu: 2026-02-20
> Zakres: cały kod źródłowy, konfiguracja, Docker, CI/CD, zależności

---

## Podsumowanie

| Severity | Ilość | Opis |
|----------|-------|------|
| CRITICAL | 2 | Wyciek danych wrażliwych w logach, brak ochrony XXE |
| HIGH | 5 | Docker root, path traversal, SSRF webhook, notifier bez Session, brak secret scanning |
| MEDIUM | 8 | Prometheus bez auth, e.response.text w logach, brak rate limit, log injection, brak pinowania akcji GH, starttls bez weryfikacji cert, brak log rotation w env compose, brak walidacji SSTI |
| LOW | 3 | Brak walidacji email, niepotrzebny import requests w notifiers, brak webhook signing |
| INFO | 4 | Dobre praktyki: secrets priority, HTTPS only, Jinja2 autoescape, .gitignore |

**Łączna liczba znalezisk: 22**

---

## CRITICAL

### C1. Logowanie wrażliwych danych z API response w exception handlers

**Pliki i linie:**
- `app/ksef_client.py:221` — `logger.error(f"Response: {e.response.text}")`
- `app/ksef_client.py:315` — j.w.
- `app/ksef_client.py:430` — j.w.
- `app/ksef_client.py:563` — j.w.
- `app/ksef_client.py:627` — j.w.
- `app/notifiers/pushover_notifier.py:91,125`
- `app/notifiers/discord_notifier.py:116,149`
- `app/notifiers/webhook_notifier.py:128,164`
- `app/notifiers/slack_notifier.py:147,176`

**Opis:** W blokach `except` logowany jest pełny tekst odpowiedzi HTTP (`e.response.text`). Odpowiedzi API mogą zawierać tokeny, dane osobowe (NIP, nazwy firm), błędy wewnętrzne serwera z informacjami o infrastrukturze.

**Wpływ:** Ujawnienie wrażliwych danych w logach. Logi mogą trafiać do systemów monitoringu (ELK, CloudWatch), where access control is broader.

**Zalecenie:**
```python
# Zamiast:
logger.error(f"Response: {e.response.text}")
# Użyć:
logger.error(f"Response status: {e.response.status_code}")
```

---

### C2. Brak ochrony XXE w parsowaniu XML

**Plik:** `app/invoice_pdf_generator.py:151`

**Opis:** Użycie `ET.fromstring(self.xml_content)` bez jawnego wyłączenia DTD/entity expansion. Chociaż Python 3.9+ `ElementTree` domyślnie nie przetwarza external entities, to:
1. Nie ma jawnej konfiguracji — zależy od wersji Pythona
2. Plik XML pochodzi z zewnętrznego API (KSeF) — nie jest zaufany
3. Atak XXE mógłby odczytać pliki z systemu (`/etc/passwd`, Docker secrets)

**Wpływ:** Odczyt dowolnych plików z kontenera (path: `/run/secrets/*`, `/data/config.json`), DoS przez entity expansion ("Billion Laughs").

**Zalecenie:**
```python
# Opcja A: defusedxml (zalecane)
pip install defusedxml
from defusedxml import ElementTree as ET

# Opcja B: jawne wyłączenie entity expansion
parser = ET.XMLParser()
parser.entity = {}
self.root = ET.fromstring(self.xml_content, parser=parser)
```

---

## HIGH

### H1. Docker: kontener działa jako root

**Plik:** `Dockerfile`

**Opis:** Brak dyrektywy `USER` — aplikacja działa jako root w kontenerze. W przypadku RCE (Remote Code Execution) atakujący ma pełne uprawnienia w kontenerze, w tym dostęp do Docker socket (jeśli zamontowany) i możliwość eskalacji.

**Wpływ:** Eskalacja uprawnień, odczyt wszystkich plików w kontenerze, potencjalnie ucieczka z kontenera.

**Zalecenie:**
```dockerfile
# Po COPY app/ ./app/
RUN useradd -r -u 1000 -m ksef && \
    chown -R ksef:ksef /app /data
USER ksef
```

---

### H2. Path traversal w zapisie artefaktów faktur

**Plik:** `app/invoice_monitor.py:353-356`

**Opis:** Numer KSeF z API jest sanityzowany tylko przez zamianę `/` i `\` na `_`, ale nie jest walidowany pod kątem path traversal:
```python
safe_ksef = ksef_number.replace('/', '_').replace('\\', '_')
base_name = f"{prefix}_{safe_ksef}_{date_str}"
```
Złośliwy numer KSeF zawierający `..` mógłby spowodować zapis pliku poza `output_dir` (np. `../../etc/cron.d/malicious`).

**Wpływ:** Zapis dowolnych plików poza katalogiem output (XML, PDF) — możliwe nadpisanie konfiguracji lub wstrzyknięcie plików.

**Zalecenie:**
```python
safe_ksef = ksef_number.replace('/', '_').replace('\\', '_').replace('..', '_')
full_path = (self.output_dir / f"{prefix}_{safe_ksef}_{date_str}.xml").resolve()
if not str(full_path).startswith(str(self.output_dir.resolve())):
    logger.error(f"Path traversal detected in KSeF number: {ksef_number}")
    return
```

---

### H3. SSRF przez konfigurację webhook URL

**Plik:** `app/notifiers/webhook_notifier.py:95-115`

**Opis:** URL webhooka jest pobierany bezpośrednio z konfiguracji bez walidacji. Ktoś z dostępem do config.json może skierować webhook na wewnętrzne serwisy:
- `http://localhost:8000/metrics` — odczyt metryk
- `http://169.254.169.254/latest/meta-data/` — AWS metadata (tokeny IAM)
- `http://internal-service:8080/admin` — wewnętrzne API

**Wpływ:** Server-Side Request Forgery — dostęp do wewnętrznych serwisów, wyciek credentiali cloud.

**Zalecenie:**
```python
from urllib.parse import urlparse
import ipaddress

def _validate_webhook_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ('https', 'http'):
        return False
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False
    except ValueError:
        pass  # hostname, not IP — OK
    return True
```

---

### H4. Notifiers używają raw `requests` zamiast Session

**Pliki:**
- `app/notifiers/webhook_notifier.py:95,102,110,144,146,148`
- `app/notifiers/pushover_notifier.py:82,116`
- `app/notifiers/discord_notifier.py:103,137`
- `app/notifiers/slack_notifier.py:134,164`

**Opis:** Poprawka #3 z poprzedniego audytu dodała `requests.Session()` do `KSeFClient`, ale notifiers nadal używają raw `requests.get/post`. Brak connection pooling i brak spójności z klientem KSeF.

**Wpływ:** Każde powiadomienie otwiera nowe połączenie TCP. Przy wielu kanałach i wielu fakturach — nadmiarowe połączenia.

**Zalecenie:** Dodać `self.session = requests.Session()` w `BaseNotifier.__init__()` i zamienić wszystkie `requests.*` na `self.session.*`.

---

### H5. Brak secret scanning w CI/CD

**Pliki:** `.github/workflows/docker-publish.yml`

**Opis:** Pipeline CI/CD nie skanuje kodu pod kątem wycieków sekretów (tokenów, haseł, kluczy API). Przypadkowy commit z `config.json` lub tokenem w kodzie nie zostanie wykryty.

**Wpływ:** Wycieki credentiali mogą zostać pushowane do repozytorium i być widoczne w historii git.

**Zalecenie:**
- Włączyć GitHub Secret Scanning (Settings → Security)
- Dodać pre-commit hook z `detect-secrets` lub `truffleHog`
- Dodać step w workflow: `pip install detect-secrets && detect-secrets scan`

---

## MEDIUM

### M1. Prometheus metrics endpoint bez autentykacji

**Plik:** `app/prometheus_metrics.py:72`

**Opis:** `start_http_server(self.port)` nasłuchuje na 0.0.0.0 bez autentykacji. Endpoint `/metrics` ujawnia:
- Liczbę przetworzonych faktur
- Czasy ostatnich sprawdzeń
- Status monitora (up/down)
- Typy faktur (Subject1/Subject2)

**Wpływ:** Information disclosure — atakujący dowiaduje się o wzorcach aktywności firmy.

**Zalecenie:**
```python
# Bind tylko na localhost
start_http_server(self.port, addr='127.0.0.1')
```
Lub dodać reverse proxy z auth (np. nginx basic auth) przed endpointem.

---

### M2. Log injection przez dane z API KSeF

**Plik:** `app/invoice_monitor.py:231,233`

**Opis:** Dane z API KSeF (`invoice.get('ksefNumber')`) są logowane bez sanityzacji. Złośliwy numer KSeF z newline mógłby wstrzyknąć fałszywe wpisy do logów:
```
ksefNumber: "1234\n2026-02-20 INFO Authentication successful"
```

**Wpływ:** Manipulacja logami, ukrycie aktywności atakującego, fałszywe wpisy.

**Zalecenie:**
```python
safe_ksef = str(invoice.get('ksefNumber', 'N/A')).replace('\n', ' ').replace('\r', ' ')
logger.info(f"Notification sent [{subject_type}] invoice: {safe_ksef}")
```

---

### M3. Brak rate limiting dla wywołań API

**Pliki:** `app/ksef_client.py`, `app/scheduler.py`

**Opis:** Brak minimum interwału w schedulerze. Konfiguracja `interval: 0` spowoduje ciągłe odpytywanie API KSeF, co może prowadzić do:
- Blokady konta przez API KSeF (429 Too Many Requests)
- Obciążenia serwera
- Wysokich kosztów (jeśli API jest płatne)

**Zalecenie:** Dodać walidację minimalnego interwału w `Scheduler`:
```python
MIN_INTERVAL_SECONDS = 300
if interval < MIN_INTERVAL_SECONDS:
    logger.warning(f"Interval {interval}s too low, using minimum {MIN_INTERVAL_SECONDS}s")
    interval = MIN_INTERVAL_SECONDS
```

---

### M4. GitHub Actions — wersje akcji nie pinowane do SHA

**Plik:** `.github/workflows/docker-publish.yml:17,19,22,30,39`

**Opis:** Używane są tagi wersji (`@v4`, `@v3`, `@v5`, `@v6`) zamiast commit SHA. Tagi mogą zostać nadpisane (supply chain attack).

**Zalecenie:**
```yaml
# Zamiast:
- uses: actions/checkout@v4
# Użyć:
- uses: actions/checkout@692973e3d937129bcbf40652eb9f2f61becf3332  # v4
```

---

### M5. Email STARTTLS bez weryfikacji certyfikatu

**Plik:** `app/notifiers/email_notifier.py:168-169`

**Opis:** `server.starttls()` jest wywołane bez parametru `context` (SSLContext). Domyślnie Python's SMTP `starttls()` nie weryfikuje certyfikatu serwera — podatne na MITM.

**Wpływ:** Atakujący w sieci lokalnej może przechwycić credentiale SMTP i treść powiadomień.

**Zalecenie:**
```python
import ssl
context = ssl.create_default_context()
server.starttls(context=context)
```

---

### M6. Brak log rotation w docker-compose.env.yml

**Plik:** `docker-compose.env.yml`

**Opis:** Plik `docker-compose.secrets.yml` ma konfigurację log rotation (max-size: 10m, max-file: 3), ale `docker-compose.env.yml` — nie. Bez limitów logi mogą rosnąć w nieskończoność.

**Zalecenie:** Dodać do `docker-compose.env.yml`:
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

---

### M7. Docker base image bez pinowania digest

**Plik:** `Dockerfile:1`

**Opis:** `FROM python:3.11-slim` — tag `slim` jest mutable i może zostać nadpisany. Nowa wersja obrazu bazowego może zawierać podatności lub breaking changes.

**Zalecenie:**
```dockerfile
FROM python:3.11.11-slim@sha256:<specific_digest>
```

---

### M8. Brak walidacji danych z API przed renderowaniem szablonów

**Pliki:** `app/template_renderer.py`, `app/invoice_pdf_template.py`

**Opis:** Dane z API KSeF (nazwy firm, adresy, numery) są bezpośrednio przekazywane do szablonów Jinja2. Chociaż HTML autoescape jest włączony, to:
- Szablony JSON/plain text nie mają autoescape
- Webhook i Slack szablony renderują dane bez HTML escape
- Złośliwe dane w fakturze mogłyby wstrzyknąć treść w powiadomieniach

**Zalecenie:** Dodać sanityzację pól string z API przed przekazaniem do szablonu:
```python
def sanitize_invoice_field(value: str, max_length: int = 500) -> str:
    return str(value)[:max_length].replace('\x00', '')
```

---

## LOW

### L1. Brak walidacji adresów email w konfiguracji

**Plik:** `app/notifiers/email_notifier.py:45`

**Opis:** Adresy email z konfiguracji nie są walidowane. Niepoprawny format spowoduje runtime error przy wysyłce.

**Zalecenie:** Walidacja regex przy starcie (nie przy wysyłce).

---

### L2. Brak HMAC signing dla webhook payloads

**Plik:** `app/notifiers/webhook_notifier.py`

**Opis:** Payloady webhooków nie są podpisane kryptograficznie. Odbiorca nie może zweryfikować, czy wiadomość pochodzi z aplikacji.

**Zalecenie:** Dodać opcjonalny header `X-Signature: sha256=<hmac>` z sekretnym kluczem z konfiguracji.

---

### L3. Zależności xhtml2pdf i Jinja2 bez upper bound

**Plik:** `requirements.txt:8,13`

**Opis:** `Jinja2>=3.1.0` i `xhtml2pdf>=0.2.16` nie mają górnego limitu. Nowa major version mogłaby złamać kompatybilność.

**Zalecenie:**
```
Jinja2>=3.1.0,<4.0.0
xhtml2pdf>=0.2.16,<1.0.0
```

---

## INFO (Dobre praktyki)

### I1. Hierarchia sekretów poprawna
`SecretsManager` implementuje priorytet: env vars → Docker secrets → config.json. Prawidłowe podejście.

### I2. Wszystkie endpointy API używają HTTPS
KSeF API: `https://api.ksef.mf.gov.pl`, `https://api-demo.ksef.mf.gov.pl`, `https://api-test.ksef.mf.gov.pl`.

### I3. Jinja2 autoescape włączony
`select_autoescape(["html"])` w `template_renderer.py` i `invoice_pdf_template.py`. Poprawne.

### I4. Config files w .gitignore
`config.json` i `config_test.json` wykluczone z repozytorium.

---

## Priorytet napraw

### Natychmiast (przed produkcją)
1. **C1** — Usunąć logowanie `e.response.text` z wszystkich plików
2. **C2** — Dodać `defusedxml` lub jawnie wyłączyć entity expansion
3. **H1** — Dodać USER ksef do Dockerfile
4. **H2** — Walidacja ścieżki pliku (path traversal guard)

### Krótkoterminowe (1-2 tygodnie)
5. **H3** — Walidacja webhook URL (SSRF prevention)
6. **H4** — Session pooling w notifiers
7. **M1** — Bind Prometheus na localhost
8. **M5** — SSL context w email STARTTLS

### Średnioterminowe (następna wersja)
9. **H5** — Secret scanning w CI/CD
10. **M2** — Sanityzacja danych w logach
11. **M3** — Minimum interwał w schedulerze
12. **M4** — Pinowanie SHA akcji GitHub
13. **M6** — Log rotation w docker-compose.env.yml
14. **M7** — Pinowanie digest obrazu Docker

### Długoterminowe (planowane)
15. **L2** — Webhook HMAC signing
16. **L3** — Upper bounds na zależnościach
17. **M8** — Walidacja danych z API przed renderowaniem
