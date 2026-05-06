# Audyt Bezpieczeństwa — KSeF Monitor Docker (v0.4, pre-v0.5)

> **Data audytu:** 2026-04-21
> **Zakres:** Dockerfile, docker-compose.{yml,env.yml,secrets.yml}, entrypoint.sh, kod aplikacji (Python 3.11 + FastAPI + SQLAlchemy), CI/CD, zależności (pyproject.toml / requirements.txt)
> **Typ:** Pełny re-audyt + nowe znaleziska v0.4 (API REST)
> **Uwaga wersyjna:** Użytkownik poprosił o "audyt v0.5". **W repo nie ma wersji 0.5** — `pyproject.toml` = `0.4.0`, `main.py` loguje "KSeF Monitor v0.4", `api/__init__.py` version="0.4.0". v0.5 to roadmap (Initial load + Web UI) per `docs/ROADMAP.md:169` i `docs/DATABASE.md:301`. Audyt przeprowadzono na **bieżącym stanie v0.4**, z uwagami dot. nadchodzącego v0.5.

---

## 1. Podsumowanie wykonawcze

**Stan bezpieczeństwa: DOBRY → ŚREDNI ryzyko** (stabilne v0.4, rosnące dla v0.5 bez threat modelu UI).

| Kategoria | Liczba |
|-----------|-------|
| Poprawki potwierdzone z re-audytu v0.3 | **7 / 7** (M7, L1, N1, N2, N3, N4, N5 wszystkie zaadresowane) |
| Nowe znaleziska (v0.4 = FastAPI REST + DB Phase 2) | **11** |
| CRITICAL | 0 |
| HIGH | 1 (zależność urllib3 DoS, niepinowana) |
| MEDIUM | 6 |
| LOW | 3 |
| INFO | 1 |

### Top 3 do pilnego działania

1. **F-01** (HIGH) — urllib3 transitywne <2.6.0, CVE-2025-66418 / CVE-2025-66471, decompression bomb DoS. Brak pinów `urllib3`/lockfile.
2. **F-02** (MEDIUM) — Rozjazd pinów: `pyproject.toml` `cryptography==46.0.5` vs `requirements.txt` `cryptography==46.0.7`. 46.0.5 podatne na CVE-2026-39892 (GHSA-p423-j2cm-9vmq, OOB read). Dockerfile instaluje z `requirements.txt` → FAKTYCZNIE 46.0.7 w obrazie, ale rozjazd łamie reprodukowalność i user instalujący z pyproject dostaje vuln.
3. **F-05** (MEDIUM) — Endpoint `POST /api/v1/monitor/trigger` nie używa `rate_limit.trigger="2/minute"` z configu — ustawienie zdefiniowane w `_apply_api_defaults` ale nigdzie nie zaaplikowane. Pada tylko pod default 60/min, co daje amplifikację KSeF API calls.

---

## 2. Stack wykryty

| Warstwa | Technologia | Wersja |
|---------|-------------|--------|
| Base image | `python:3.11-slim` (Debian bookworm-slim) | pinowany `@sha256:543d6cace00ffc96bc95d332493bb28a4332c6dd614aab5fcbd649ae8a7953d9` |
| Runtime | Python | 3.11 |
| Web framework | FastAPI | `>=0.115.0,<1.0.0` |
| ASGI server | uvicorn[standard] | `>=0.34.0,<1.0.0` |
| Rate limiting | slowapi | `>=0.1.9,<1.0.0` |
| ORM / migracje | SQLAlchemy 2.0 / alembic | `>=2.0.0,<3.0.0` / `>=1.13.0,<2.0.0` |
| Baza | SQLite + WAL | `/data/invoices.db` |
| HTTP client | requests | `>=2.32.5,<3.0.0` (transitive urllib3 — NIEPINOWANY) |
| Crypto | cryptography | **ROZJAZD**: pyproject=46.0.5, requirements=46.0.7 |
| Templates | Jinja2 (Sandboxed, autoescape HTML) | `>=3.1.6,<4.0.0` ✅ |
| XML | defusedxml | `>=0.7.1,<1.0.0` ✅ |
| PDF | reportlab / xhtml2pdf | `4.4.10` / `>=0.2.16,<1.0.0` |
| Deployment | Docker + docker-compose v3.8 | Dockerfile multi-step, USER ksef (UID 1000), HEALTHCHECK obecny |
| CI/CD | GitHub Actions | Akcje pinowane do SHA ✅, detect-secrets ✅ |
| Registry | GHCR `ghcr.io/mlotocki2k/ksef_monitor` | `:latest`, `:test`, tag vX.Y.Z, `:sha-*` |

**Attack surface (v0.4):**
- Zewnętrzne: port 8000 (Prometheus metrics) — bind `127.0.0.1` w compose ✅
- Wewnętrzne: port 8080 (REST API FastAPI) — nie mapowany na host, tylko w sieci kontenera
- Volumes: `/config/config.json` (ro), `/data` (rw named volume), opcjonalne `/data/templates` (ro), `/data/pdf_templates` (ro)
- Wychodzące: HTTPS do `api(-demo|-test).ksef.mf.gov.pl`, webhooki Discord/Slack/Pushover/Email SMTP
- Signals: SIGINT/SIGTERM (shutdown), SIGUSR1 (trigger sprawdzenia)

---

## 3. Weryfikacja poprzednich znalezisk (re-audit v0.3 → v0.4)

### Wszystkie 7 pozostałych braków z `re_audit_finding.md` — ZAADRESOWANE ✅

| ID | Problem | Status w v0.4 | Dowód |
|----|---------|---------------|-------|
| **M7** | Base image bez pin digest | ✅ FIXED | [Dockerfile:1](../Dockerfile) — `FROM python:3.11-slim@sha256:543d6...` |
| **L1** | Brak walidacji email | ✅ FIXED | [email_notifier.py:23,60-68](../app/notifiers/email_notifier.py) — `_EMAIL_RE` + `_validate_addresses()` |
| **N1** | Brak .dockerignore | ✅ FIXED | [.dockerignore](../.dockerignore) obecny, wyklucza `.git`, `audit/`, `examples/`, `config*.json`, `docker-compose*.yml`, `.env*` |
| **N2** | Log rotation w głównym compose | ✅ FIXED | [docker-compose.yml:31-35](../docker-compose.yml) — `max-size: 10m, max-file: 3` |
| **N3** | Prometheus port 0.0.0.0 | ✅ FIXED | [docker-compose.yml:15](../docker-compose.yml) — `"127.0.0.1:8000:8000"` |
| **N4** | Brak HEALTHCHECK | ✅ FIXED | [Dockerfile:58-59](../Dockerfile) — healthcheck via `/metrics` |
| **N5** | Timezone naive/aware mismatch | ✅ FIXED | [invoice_monitor.py:131-140,419-427](../app/invoice_monitor.py) — jawne `localize()` i `astimezone()` |

**Wszystkie 22 pierwotne znaleziska z `audit_finding.md` wciąż poprawne (C1, C2, H1-H5, M1-M8, L1-L3 zaadresowane w v0.3; M7/L1 w v0.4).**

---

## 4. Nowe znaleziska v0.4

### F-01 (HIGH) — Transitywne `urllib3` bez pin, podatne CVE-2025-66418/66471

| Pole | Wartość |
|------|---------|
| **Kategoria** | Dependency / Supply chain |
| **Severity** | HIGH |
| **Confidence** | CONFIRMED (CVE), LIKELY (eksploatowalność w tym projekcie) |
| **CVE** | CVE-2025-66418, CVE-2025-66471 |
| **GHSA** | [GHSA-gm62-xv2j-4w53](https://github.com/advisories/GHSA-gm62-xv2j-4w53), [GHSA-2xpw-w6gg-jr37](https://github.com/advisories/GHSA-2xpw-w6gg-jr37) |
| **CVSS** | 8.9 / HIGH (66418), ~7.5 (66471) |
| **CWE** | CWE-400 Uncontrolled Resource Consumption, CWE-409 Decompression bomb |
| **Affected** | urllib3 `>=1.24, <2.6.0` |
| **Status** | OPEN |
| **Location** | [requirements.txt](../requirements.txt) — brak pin `urllib3`; transitive przez `requests>=2.32.5,<3.0.0` |

**Opis:** urllib3 do 2.6.0 akceptuje nieograniczoną liczbę łańcuchowych `Content-Encoding` i przy strumieniowym odczycie dekompresuje dane skompresowane w nadmiernym stopniu, co daje zdalny DoS (CPU + RAM).

**Attack scenario:** Atakujący kontrolujący endpoint webhooka (własny endpoint Discord/Slack/generyczny) lub MITM odpowiedzi HTTP zwraca payload z `Content-Encoding: gzip, deflate, br, zstd, gzip, ...` — proces monitora zużywa tyle RAM/CPU, że crashuje. Alternatywnie zip-bomb w odpowiedzi KSeF API (niski risk: mały TLS bez MITM).

**Evidence:**
```
$ grep urllib3 ksef_monitor_v0_1/requirements.txt
(brak — tylko implicit via requests)
```

**Remediation (P1):**
```
# requirements.txt
urllib3>=2.6.0,<3.0.0   # CVE-2025-66418, CVE-2025-66471
```
Oraz dodać `pip freeze > requirements.lock` i budować obraz z lockfile.

---

### F-02 (MEDIUM) — Rozjazd pinów `cryptography` między pyproject i requirements

| Pole | Wartość |
|------|---------|
| **Kategoria** | Supply chain / Reproducibility |
| **Severity** | MEDIUM |
| **Confidence** | CONFIRMED |
| **CVE** | CVE-2026-39892 (dotyczy `cryptography <46.0.7`) |
| **GHSA** | [GHSA-p423-j2cm-9vmq](https://github.com/advisories/GHSA-p423-j2cm-9vmq) |
| **CWE** | CWE-125 Out-of-bounds Read, CWE-1104 Use of Unmaintained Third Party Components (meta) |
| **Status** | OPEN |
| **Location** | [pyproject.toml:23](../pyproject.toml) (46.0.5 ❌) vs [requirements.txt:3](../requirements.txt) (46.0.7 ✅) |

**Opis:** Dockerfile (`RUN pip install -r requirements.txt`) instaluje wersję bezpieczną (46.0.7), **ale** użytkownicy instalujący `pip install .` z `pyproject.toml` dostają podatny build 46.0.5.

**Wpływ:** Naruszona reprodukowalność; każdy, kto używa `pyproject.toml` (dev, CI lokalne, niektóre narzędzia SBOM) dostaje vuln.

**Evidence:**
```
pyproject.toml:23:    "cryptography==46.0.5",
requirements.txt:3:cryptography==46.0.7
```

**Remediation (P1):** Ujednolicić na `cryptography==46.0.7`. Rozważyć single-source-of-truth: usunąć zduplikowaną listę deps z `pyproject.toml` (zostawić `dynamic = ["dependencies"]` + `tool.setuptools.dynamic`) lub auto-generować `requirements.txt` z `pyproject.toml`.

---

### F-03 (MEDIUM) — `starlette` (przez FastAPI) potencjalnie <0.49.1, CVE-2025-62727

| Pole | Wartość |
|------|---------|
| **Kategoria** | Dependency |
| **Severity** | MEDIUM (niższa niż HIGH bo nie-eksploatowalne w kodzie; retained jako supply chain) |
| **Confidence** | LIKELY (brak lockfile — realna wersja zależna od daty builda) |
| **CVE** | CVE-2025-62727 |
| **GHSA** | [GHSA-7f5h-v6xp-fcq8](https://github.com/advisories/GHSA-7f5h-v6xp-fcq8) |
| **CVSS** | 7.5 |
| **CWE** | CWE-407 Algorithmic Complexity (O(n²) DoS) |
| **Affected** | starlette `>=0.39.0, <0.49.1` (transitive via `fastapi>=0.115`) |
| **Status** | OPEN (uncomplicated by code — aplikacja **NIE używa** `StaticFiles`/`FileResponse`) |

**Opis:** DoS przez łączenie nagłówka `Range` w `starlette.responses.FileResponse`.

**Nie-eksploatowalne w tym projekcie:** grep `FileResponse|StaticFiles` = 0 wystąpień. Aplikacja zwraca wyłącznie `JSONResponse`.

**Remediation (P2):** Dodać do `requirements.txt`:
```
starlette>=0.49.1
```
Nawet jako defense-in-depth przed v0.5 (Web UI najprawdopodobniej doda `StaticFiles` dla assetów → aktywuje vector).

---

### F-04 (MEDIUM) — `xhtml2pdf.pisa.CreatePDF` bez `link_callback` → potencjalny SSRF / local file read

| Pole | Wartość |
|------|---------|
| **Kategoria** | SSRF / LFI via PDF renderer |
| **Severity** | MEDIUM |
| **Confidence** | LIKELY |
| **CWE** | CWE-918 SSRF, CWE-73 External Control of File Name or Path |
| **OWASP** | A10:2021 Server-Side Request Forgery |
| **Status** | OPEN |
| **Location** | [app/invoice_pdf_template.py:161](../app/invoice_pdf_template.py) |

**Opis:** `pisa.CreatePDF(html_content, dest=buffer, encoding='utf-8')` — brak parametru `link_callback`. `xhtml2pdf` domyślnie próbuje pobrać zewnętrzne zasoby (`<img src="http://...">`, `<link rel="stylesheet" href="file:///etc/passwd">`) podczas generowania PDF.

**Attack scenario:**
1. Admin mountuje własny `/data/pdf_templates/invoice_pdf.html.j2` z `{{ seller_name }}` bez autoescape lub z `|safe`.
2. Sprzedawca wystawia fakturę z nazwą `<img src="http://internal-admin.corp/reset-password?token=X">` lub `<link href="file:///proc/self/environ" rel="stylesheet">`.
3. Kontener generuje PDF → wysyła request / czyta plik lokalny → embed w PDF lub leak w SSRF.

**Prerequisites:** custom template z `|safe` lub bez autoescape (autoescape domyślnie `True` dla `.html`, **ale** domyślny `invoice_pdf.html.j2` ma rozszerzenie `.html.j2` co jest obejmowane regułą `select_autoescape(["html"])` — ✅ w shipped default).

**Evidence:**
```python
pisa_status = pisa.CreatePDF(html_content, dest=buffer, encoding='utf-8')
```

**Remediation (P2):**
```python
def safe_link_callback(uri, rel):
    # Blok all remote + file:// — allow tylko data: URIs i wbudowane czcionki
    if uri.startswith('data:') or uri.startswith('/app/app/templates/'):
        return uri
    logger.warning("xhtml2pdf: blocked external resource %s", uri[:120])
    return ''  # pusty string = nie pobieraj

pisa_status = pisa.CreatePDF(
    html_content, dest=buffer, encoding='utf-8',
    link_callback=safe_link_callback,
)
```

---

### F-05 (MEDIUM) — `rate_limit.trigger` nieaktywowany na `/api/v1/monitor/trigger`

| Pole | Wartość |
|------|---------|
| **Kategoria** | API Abuse / Resource Exhaustion |
| **Severity** | MEDIUM |
| **Confidence** | CONFIRMED |
| **CWE** | CWE-770 Allocation of Resources Without Limits |
| **OWASP** | API4:2023 Unrestricted Resource Consumption |
| **Status** | OPEN |
| **Location** | [app/api/routers/monitor.py:57-78](../app/api/routers/monitor.py); [app/config_manager.py:464](../app/config_manager.py) |

**Opis:** Config default `rate_limit.trigger = "2/minute"` zdefiniowany w `_apply_api_defaults`, ale w `api/__init__.py` limiter tylko przyjmuje `default_limits=[default_limit]` (60/min). Endpoint `POST /monitor/trigger` nie ma dekoratora `@limiter.limit(trigger_limit)`.

**Wpływ:** Authenticated user (lub atakujący po przechwyceniu tokena) może 60/min wywoływać `force_next_run()` → amplification KSeF API calls → możliwy throttle po stronie KSeF (blokada konta), skok kosztów sieciowych.

**Evidence:**
```python
# config_manager.py:464
rate_limit.setdefault("trigger", "2/minute")

# api/__init__.py:113-121
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[default_limit],  # tylko default
    enabled=rl_enabled,
)
# monitor.py — brak @limiter.limit(...)
```

**Remediation (P2):**
```python
# api/routers/monitor.py
from slowapi import Limiter

@router.post("/monitor/trigger", response_model=TriggerResponse)
@limiter.limit(lambda: request.app.state.rate_limit_trigger or "2/minute")
def trigger_check(request: Request):
    ...
```
Alternatywnie przekazać limiter do routera i udekorować.

---

### F-06 (MEDIUM) — Jinja2 autoescape nie pokrywa szablonów JSON (slack/discord/webhook) — delegacja na `|json_escape`

| Pole | Wartość |
|------|---------|
| **Kategoria** | Injection (JSON) |
| **Severity** | MEDIUM (downgrade: shipped templates używają filtra; ryzyko tylko dla custom templates) |
| **Confidence** | LIKELY |
| **CWE** | CWE-116 Improper Encoding, CWE-1287 |
| **Status** | OPEN |
| **Location** | [app/template_renderer.py:118](../app/template_renderer.py) — `autoescape=select_autoescape(["html"])` |

**Opis:** `select_autoescape(["html"])` włącza autoescape tylko dla `*.html*`. Szablony `slack.json.j2`, `discord.json.j2`, `webhook.json.j2`, `pushover.txt.j2` **nie mają autoescape**. Shipped templates używają filtra `{{ x | json_escape }}` poprawnie (widać w [slack.json.j2](../app/templates/slack.json.j2)), ale user's custom template w `/data/templates/` może go pominąć → JSON injection przez nazwy stron (seller_name = `","admin":true}`).

**Attack scenario:** Atakujący wystawia fakturę z `sellerName = "Foo","text":"Przelew 100k PLN zrealizowany"` → notyfikacja Slacka wyświetla fałszywe treści lub pozwala na wstrzyknięcie markdownu.

**Remediation (P2):**
1. Bezpośrednio: wymuś filter w shipped templates (już jest) oraz zmień signature na zmapowanie per-channel autoescape:
   ```python
   def channel_autoescape(name):
       return name and (name.endswith('.json.j2') or name.endswith('.html.j2'))
   SandboxedEnvironment(autoescape=channel_autoescape, ...)
   ```
2. Lepiej: programatycznie budować payload Slacka/Discorda w Pythonie (JSON `dict` → `json.dumps`) zamiast renderować JSON w Jinja2.

---

### F-07 (LOW) — `_migrate_schema` buduje ALTER TABLE przez f-string

| Pole | Wartość |
|------|---------|
| **Kategoria** | SQL construction (defense-in-depth) |
| **Severity** | LOW (źródło danych = własne modele SQLAlchemy, nie input) |
| **Confidence** | CONFIRMED (patt), ASSUMED (eksploatacja niemożliwa) |
| **CWE** | CWE-89 (w teorii), ale trusted source |
| **Status** | OPEN |
| **Location** | [app/database.py:322-341](../app/database.py) |

**Opis:**
```python
stmt = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}{default_clause}"
conn.execute(text(stmt))
```
Dane pochodzą z `Base.metadata.sorted_tables` — kontrolowane przez dev, nie przez atakującego. Ryzyko = zerowe dziś, ale wzorzec niebezpieczny (łatwo przez przypadek przekazać user input).

**Remediation (P3):** Użyć `alembic` (projekt już go ma!) dla migracji zamiast autogenerowanego ALTER w runtime. `_migrate_schema()` niepotrzebnie duplikuje alembic.

---

### F-08 (LOW) — `get_invoice(ksef_number)` nie waliduje formatu (zdefiniowany `_KSEF_PATTERN` nieużywany)

| Pole | Wartość |
|------|---------|
| **Kategoria** | Input validation / Enumeration |
| **Severity** | LOW |
| **Confidence** | CONFIRMED |
| **CWE** | CWE-20 Improper Input Validation |
| **Status** | OPEN |
| **Location** | [app/api/routers/invoices.py:22-23,105-122](../app/api/routers/invoices.py) |

**Opis:** `_KSEF_PATTERN = re.compile(...)` zdefiniowany w linii 23, ale `get_invoice` (linia 106) go nie używa. Brak pre-validation pozwala na enumeration attacks (różnicowanie 404 vs 400) i marnuje cykle SQL.

**Remediation (P3):**
```python
@router.get("/invoices/{ksef_number}", response_model=InvoiceDetail)
def get_invoice(request: Request, ksef_number: str):
    if not _KSEF_PATTERN.match(ksef_number):
        return JSONResponse(status_code=400, content={"detail": "Invalid KSeF number format"})
    ...
```

---

### F-09 (LOW) — `entrypoint.sh` wymaga CAP_CHOWN/CAP_SETUID (rootful), brak trybu rootless

| Pole | Wartość |
|------|---------|
| **Kategoria** | Container hardening |
| **Severity** | LOW |
| **Confidence** | CONFIRMED |
| **Status** | OPEN |
| **Location** | [entrypoint.sh:1-42](../entrypoint.sh) |

**Opis:** `usermod`/`groupmod` + `chown -R` wymagają root w kontenerze. `gosu ksef` drop-duje uprawnienia **po**. Działa, ale:
1. Rootless Docker (`userns-remap`, Podman rootless) zawodzi — `usermod` nie przejdzie.
2. `chmod -R u+rwX /data` jest szerokie (cały volume) — ustawia bity wykonywalne na kat.

**Remediation (P3):** Dodać tryb `--rootless` (skip usermod gdy `$DATA_UID == $(id -u)`) lub udokumentować wymagania uprawnień:
```sh
# Skip UID matching if already running as target user (rootless scenario)
CURRENT_UID=$(id -u)
if [ "$CURRENT_UID" != "0" ]; then
    echo "Running as non-root (UID=$CURRENT_UID), skipping usermod"
    umask 077
    exec python -u main.py
fi
# ... istniejąca logika dla rootful ...
```

---

### F-10 (LOW) — Auto-generated API token logowany w 8 pierwszych znakach

| Pole | Wartość |
|------|---------|
| **Kategoria** | Information disclosure via logs |
| **Severity** | LOW |
| **Confidence** | CONFIRMED |
| **CWE** | CWE-532 Insertion of Sensitive Information into Log File |
| **Status** | OPEN |
| **Location** | [app/config_manager.py:468-478](../app/config_manager.py) |

**Opis:** Gdy API włączone bez `auth_token`, generuje `secrets.token_urlsafe(48)` i loguje pierwsze 8 znaków jako "warning" — prawdopodobnie dla debugowania. 8 znaków z `token_urlsafe` to log₂(64⁸) ≈ 48 bitów, niepraktycznie do brute force, ale zasada: sekret w logu = anty-wzorzec. Logi idą do `docker logs` = widoczne przez każdego z dostępem do socketu Docker.

**Remediation (P3):** Usunąć echo tokenu z logu; wymagać eksplicytnego setu `api.auth_token` lub `API_AUTH_TOKEN` env var przy `api.enabled=true` zamiast auto-generacji.

---

### F-11 (INFO) — Roadmap v0.5 znacząco zwiększy attack surface — wymagany threat model PRZED mergowaniem

| Pole | Wartość |
|------|---------|
| **Kategoria** | Threat modeling / planning |
| **Severity** | INFO (advisory) |
| **Status** | OPEN |

**Opis:** `docs/ROADMAP.md:169` i `docs/DATABASE_DESIGN.md:406` planują na v0.5:
- Web UI (odczyt faktur) → eksponuje HTTP dashboard,
- Initial load (masowy import),
- FTS5 virtual tables + `invoices_fts` triggers,
- `import_jobs`, `invoice_views`, `dashboard_stats`.

**Nowe wektory, które pojawią się w v0.5:**
1. **XSS w UI** — renderowanie `seller_name`/`buyer_name` z KSeF API (obecnie sanityzacja jest tylko w Pythonie, nie przy render HTML).
2. **Authn/Authz UI** — obecny Bearer token OK dla API, ale UI potrzebuje session cookies → CSRF, secure/httponly/SameSite.
3. **StaticFiles (Starlette)** — aktywuje CVE-2025-62727 (F-03 staje się CRITICAL).
4. **Enumeration** — `get_invoice` (F-08) zmusi do sanitize all endpoints.
5. **DB bulk import** — walidacja input size, resource limits, transakcyjność.

**Remediation (P1 przed v0.5):**
- Zrobić threat model przed pierwszym commitem v0.5.
- Dodać `TrustedHostMiddleware` do FastAPI.
- Pin `starlette>=0.49.1` **teraz** (F-03).
- Ustalić politykę CSP nagłówków dla UI (obecne security headers pokrywają `X-Content-Type-Options`, `X-Frame-Options`, `Cache-Control` — brakuje `Content-Security-Policy`, `Referrer-Policy`, `Strict-Transport-Security`).
- Tokeny API w UI: HttpOnly cookie + rotation + CSRF token (slowapi nie chroni CSRF).

---

## 5. Potwierdzone dobre praktyki (utrzymane z v0.3)

| # | Praktyka | Status | Dowód |
|---|----------|--------|-------|
| I1 | Hierarchia sekretów (env → Docker secrets → config.json) | ✅ | [secrets_manager.py:34-58](../app/secrets_manager.py) |
| I2 | HTTPS dla KSeF API | ✅ | [ksef_client.py:62-67](../app/ksef_client.py) |
| I3 | Jinja2 SandboxedEnvironment + autoescape HTML | ✅ | [template_renderer.py:116-121](../app/template_renderer.py), [invoice_pdf_template.py:120-125](../app/invoice_pdf_template.py) |
| I4 | `.gitignore` + `.dockerignore` wykluczają `config*.json` | ✅ | [.gitignore](../.gitignore), [.dockerignore](../.dockerignore) |
| I5 | Brak `subprocess`/`os.system`/`eval`/`pickle` | ✅ | `grep` = 0 match |
| I6 | SQLAlchemy ORM, brak raw SQL z user input | ✅ | [database.py:363,368](../app/database.py) — `filter_by(ksef_number=...)` parametryzowane |
| I7 | defusedxml zamiast xml.etree | ✅ | [invoice_xml_parser.py:16](../app/invoice_xml_parser.py) |
| I8 | RSA-OAEP SHA-256 do szyfrowania tokena KSeF | ✅ | [ksef_client.py:420-428](../app/ksef_client.py) |
| I9 | `hmac.compare_digest` do auth token compare | ✅ | [app/api/__init__.py:82](../app/api/__init__.py) |
| I10 | `requests.Session()` + `verify=True` explicit | ✅ | [ksef_client.py:75-76](../app/ksef_client.py), [base_notifier.py:24-25](../app/notifiers/base_notifier.py) |
| I11 | Path traversal guard z `Path.resolve()` + `is_relative_to()` | ✅ | [invoice_monitor.py:586-588,710-712](../app/invoice_monitor.py) |
| I12 | SSRF walidacja webhook URL + DNS re-validation + redirects disabled | ✅ | [webhook_notifier.py:61-91,131-133](../app/notifiers/webhook_notifier.py) — najlepsze w całym projekcie |
| I13 | HMAC-SHA256 signing webhook payloads | ✅ | [webhook_notifier.py:98-107](../app/notifiers/webhook_notifier.py) |
| I14 | NIP masking w logach | ✅ | [invoice_monitor.py:790](../app/invoice_monitor.py) — `nip[:3] + "****" + nip[-3:]` |
| I15 | Atomic state write (tmp + rename) | ✅ | [invoice_monitor.py:220-228](../app/invoice_monitor.py) |
| I16 | Min interval w schedulerze (F-M3 z audytu v0.3) | ✅ | via `Scheduler` validation |
| I17 | Response model Pydantic — `only declared fields serialized` | ✅ | [api/schemas.py](../app/api/schemas.py) — brak `file_path`, `raw_metadata` w odpowiedziach |
| I18 | Auth bypass only dla `/api/v1/monitor/health` (stały set) | ✅ | [api/__init__.py:70-72](../app/api/__init__.py) |
| I19 | GitHub Actions pinowane do SHA + detect-secrets w CI | ✅ | [.github/workflows/docker-publish.yml](../.github/workflows/docker-publish.yml) |
| I20 | Dockerfile: `USER` non-root, multi-step purge `gcc`, pinowany digest, HEALTHCHECK | ✅ | [Dockerfile](../Dockerfile) |
| I21 | docker-compose: `security_opt: no-new-privileges:true`, `ulimits: core: 0`, log rotation | ✅ | [docker-compose.yml:8-11,31-35](../docker-compose.yml) |

---

## 6. Priorytety napraw

### P1 — Natychmiast (przed v0.5 release)

1. **F-01** — Dodać `urllib3>=2.6.0,<3.0.0` do `requirements.txt` i lockfile
2. **F-02** — Ujednolicić `cryptography==46.0.7` w `pyproject.toml`, rozważyć `dynamic dependencies`
3. **F-11** — Threat model v0.5 PRZED pierwszym commitem UI; pin `starlette>=0.49.1`

### P2 — 1-2 tygodnie (v0.4.x bugfix)

4. **F-03** — `starlette>=0.49.1` pin w `requirements.txt` (defense-in-depth)
5. **F-04** — `link_callback` dla `pisa.CreatePDF` blokujący zewnętrzne zasoby
6. **F-05** — Wire `rate_limit.trigger` na `@limiter.limit()` dekorator endpointu `/monitor/trigger`
7. **F-06** — Per-file autoescape lub refaktor JSON templates na `json.dumps` w Pythonie

### P3 — Backlog (v0.5+)

8. **F-07** — Zastąpić `_migrate_schema` alembic migrations (projekt ma alembic!)
9. **F-08** — Pre-validate `ksef_number` w `get_invoice` przez `_KSEF_PATTERN`
10. **F-09** — Rootless-mode support w `entrypoint.sh`
11. **F-10** — Usunąć echo auto-generated token z logu, wymagać explicit config

---

## 7. Rekomendacje architektoniczne dla v0.5

Bazując na roadmap + F-11:

1. **Lockfile**: dodać `requirements.lock` (pip-compile lub uv) **teraz**, przed v0.5. Bez tego CVE tracking jest ślepy.
2. **SBOM** w CI/CD: dodać `syft` / `grype` scan w GitHub Actions, wysyłać wyniki do GHCR OCI artifacts.
3. **Trivy image scan** w pipeline przed `docker push`:
   ```yaml
   - uses: aquasecurity/trivy-action@<sha>
     with:
       image-ref: ghcr.io/mlotocki2k/ksef_monitor:${{ github.sha }}
       severity: 'CRITICAL,HIGH'
       exit-code: 1
   ```
4. **CSP / CORS / Security headers**: przed v0.5 dodać `TrustedHostMiddleware`, `Content-Security-Policy: default-src 'self'`, `Strict-Transport-Security`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`.
5. **CSRF**: jeśli UI używa cookies, dodać `fastapi-csrf-protect` lub double-submit token.
6. **Pydantic input schemas** dla wszystkich mutujących endpointów (obecnie tylko response).

---

## 8. Źródła (CVE / GHSA — zweryfikowane WebSearch 2026-04-21)

- [CVE-2025-66418 — urllib3 decompression chain DoS (GHSA-gm62-xv2j-4w53)](https://github.com/advisories/GHSA-gm62-xv2j-4w53)
- [CVE-2025-66471 — urllib3 streaming API compressed data DoS (GHSA-2xpw-w6gg-jr37)](https://github.com/advisories/GHSA-2xpw-w6gg-jr37)
- [CVE-2025-62727 — Starlette FileResponse Range O(n²) DoS (GHSA-7f5h-v6xp-fcq8)](https://github.com/advisories/GHSA-7f5h-v6xp-fcq8)
- [CVE-2026-39892 — cryptography OOB read via non-contiguous buffer (GHSA-p423-j2cm-9vmq)](https://github.com/advisories/GHSA-p423-j2cm-9vmq)
- [CVE-2025-27516 — Jinja2 sandbox attr filter bypass (GHSA-cpwx-vrp4-4pq7)](https://github.com/advisories/GHSA-cpwx-vrp4-4pq7) — **NIE dotyczy** (projekt ≥3.1.6)
- [CVE-2024-25885 — xhtml2pdf getcolor ReDOS (GHSA-jj5c-hhrg-vv5h)](https://github.com/advisories/GHSA-jj5c-hhrg-vv5h) — dotyczy 0.2.13, projekt ≥0.2.16 (ASSUMED zaadresowane upstream, niewryfikowane release notes 0.2.16)
- [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/)
- [Starlette security advisory GHSA-7f5h-v6xp-fcq8](https://github.com/advisories/GHSA-7f5h-v6xp-fcq8)
- Poprzedni audyt: [audit_finding.md](./audit_finding.md), [re_audit_finding.md](./re_audit_finding.md)
- Docker image: `python:3.11-slim@sha256:543d6cace00ffc96bc95d332493bb28a4332c6dd614aab5fcbd649ae8a7953d9`

---

## 9. Metadane audytu

- Narzędzia: `WebSearch` (NVD/GHSA/vendor), manualna inspekcja plików, `grep`/`Grep` empiryczna weryfikacja wzorców
- Nie wykonano: live `pip-audit` / `osv-scanner` / `trivy image` (brak dostępu do Docker builda; rekomendowane jako follow-up w CI)
- Nie fabrykowano CVE (anti-hallucination checklist ✅): wszystkie 4 CVE potwierdzone przez GHSA URL

**Auditor:** Claude Code + security-audit skill
**Branch sprawdzony:** current working tree (no VCS context — `Is a git repository: false` na top-level; `.git` obecny tylko w `ksef_monitor_v0_1/`)
