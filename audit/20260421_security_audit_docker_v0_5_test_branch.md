# Audyt Bezpieczeństwa — KSeF Monitor Docker **v0.5.0** (branch `test`)

> **Data audytu:** 2026-04-21
> **Commit HEAD:** `f7aa694` (branch `test`, tracking `origin/test`)
> **Zakres:** pełny stack Dockera v0.5 — Dockerfile, docker-compose.{yml,env,secrets}, entrypoint, kod aplikacji (**Web UI, Push iOS, Initial Load, bulk export, multi-schema parser**), zależności, CI/CD
> **Typ:** nowy audyt delty `main..test` (ponad 8 000 linii dodane; 57 plików zmienionych)

---

## 1. Podsumowanie wykonawcze

**Stan bezpieczeństwa: ŚREDNI → WYSOKIE ryzyko** (regres vs v0.4 z powodu publicznego Web UI bez auth).

v0.5 wprowadza ogromną delte attack surface: 8 nowych plików router/manager (8000+ LoC), Web UI, iOS Push pairing, Initial Load bulk import, multi-schema XML parser, CIRFMF generator integration. **Model bezpieczeństwa z v0.4 (jeden Bearer token dla wszystkiego) NIE SKALUJE na v0.5** — rozwiązano to przez szeroki auth bypass whitelist, co wprowadza krytyczne problemy.

### Top 4 do pilnego działania (P1)

| ID | Problem | Severity |
|----|---------|----------|
| **V5-01** | Auth bypass whitelist `startswith("/ui")` — **całe Web UI bez auth**, a compose eksponuje `127.0.0.1:8080`. Komentarz w kodzie: *"the port is typically bound to 127.0.0.1 or behind a reverse proxy"* — zaufanie do reverse proxy ≠ security boundary | HIGH |
| **V5-02** | `/ui/push` ujawnia **plaintext pairing_code (32-bit) + QR** bez auth — atakujący sparuje własne iOS z notyfikacjami zawierającymi dane faktur | HIGH |
| **V5-03** | `/api/v1/invoices/{ksef_number}/pdf|xml` auth-bypassed via `endswith("/pdf"\|"/xml")` + brak walidacji formatu `ksef_number` → enumeration + potencjalny HTTP header injection w `Content-Disposition` | HIGH |
| **V5-04** | `urllib3` niepinowany (retained z v0.4), `cryptography` pin rozjazd (retained z v0.4), brak `requirements.lock` mimo że v0.5 dodała `fastapi`, `uvicorn`, `slowapi`, `python-multipart` (transitive) — brak lockfile niezdrowy przy tej skali deps | HIGH (supply chain) |

### Statystyki

| Kategoria | Liczba |
|-----------|-------|
| Poprawki z v0.4 nadal poprawne | **7 / 7** (M7, L1, N1-N5, + większość v0.4 findings) |
| v0.4 findings zaadresowane w v0.5 | 2 (F-10 token log, F-01 częściowo — `cryptography==46.0.5` nadal w pyproject) |
| v0.4 findings nadal OPEN | 9 (F-01 partial, F-02, F-03, F-04, F-05, F-06, F-07, F-08, F-09) |
| **Nowe znaleziska v0.5** | **12** |
| CRITICAL | 0 |
| HIGH | **4** (V5-01, V5-02, V5-03, V5-04) |
| MEDIUM | **5** (V5-05..V5-09) |
| LOW | **3** (V5-10, V5-11, V5-12) |

---

## 2. Stack wykryty — delta v0.4 → v0.5

| Warstwa | v0.4 | v0.5 |
|---------|------|------|
| version | 0.4.0 | **0.5.0** (pyproject; `health_check` hardcoded "0.4.0" ❌ — stale) |
| Porty eksponowane | 8000 (Prometheus, 127.0.0.1) | + **8080 (REST API + Web UI, 127.0.0.1)** we wszystkich 3 compose files |
| Nowe routery | invoices, stats, monitor, artifacts | + **push, initial_load, ui** |
| Nowe moduły | — | **push_manager.py** (621 L), **initial_load_manager.py** (529 L), **invoice_export_manager.py** (499 L), **ios_push_notifier.py** (237 L) |
| Nowe template'y | — | **app/ui/templates/** (base, dashboard, invoices, invoice_detail, initial_load, push) — Web UI + Tailwind z CDN |
| Multi-schema parser | FA(3) | + **FA(2), FA_RR, PEF** (UBL/PEPPOL), auto-detekcja po namespace |
| External service | — | **push.monitorksef.com** (Cloudflare Worker relay dla APNs) |
| External service | — | **CIRFMF ksef-pdf-generator** (opcjonalny mikroserwis PDF) |
| Nowe tabele DB | invoices, monitor_state, notification_log, api_request_log, invoice_artifacts | + **push_instances**, + **initial_load_jobs** (zakładane) |
| Auth middleware | 1 whitelist (`/docs`, `/redoc`, `/openapi.json`, `/api/v1/monitor/health`) | **rozszerzony whitelist: + `/api/v1/monitor/ksef-status`, `/api/v1/push/devices`, `path.startswith("/ui")`, `path.startswith("/api/v1/invoices/") and endswith("/pdf"\|"/xml")`** |

---

## 3. HIGH FINDINGS — v0.5

### V5-01 (HIGH) — Auth bypass `path.startswith("/ui")` eksponuje całe Web UI bez autentykacji

| Pole | Wartość |
|------|---------|
| **Kategoria** | Broken authentication / authorization |
| **Confidence** | CONFIRMED |
| **CWE** | CWE-306 Missing Authentication for Critical Function, CWE-285 Improper Authorization |
| **OWASP** | A01:2021 Broken Access Control, API2:2023 Broken Authentication |
| **Status** | OPEN |
| **Location** | [app/api/__init__.py:85-89](../app/api/__init__.py) |

**Evidence:**
```python
# api/__init__.py:85-89
if path in _EXEMPT_EXACT or \
   path.startswith("/ui") or \
   (path.startswith("/api/v1/invoices/") and
    (path.endswith("/pdf") or path.endswith("/xml"))):
    return await call_next(request)
```

**Opis:** Cały prefiks `/ui` obchodzi bramę auth. Z komentarza w `ui.py:7`: *"the port is typically bound to 127.0.0.1 or behind a reverse proxy"* — to nie jest security control, tylko założenie o deploymencie. `docker-compose.yml:18` komentuje: *"Change 127.0.0.1 to 0.0.0.0 to expose beyond localhost (e.g. behind reverse proxy)"* — doc zachęca do eksponowania.

**Attack scenario:**
1. Admin zmienia mapping na `"0.0.0.0:8080:8080"` lub stawia nginx przed kontenerem bez dodawania basic auth.
2. Atakujący skanuje port 8080. Hituje `GET /ui/invoices` — widzi pełną listę faktur bez uwierzytelnienia:
   - `seller_nip`, `seller_name`, `buyer_nip`, `buyer_name`, `gross_amount`, `issue_date`, `ksef_number`, `invoice_number`
3. Hituje `GET /ui/invoices/{ksef}` → pełny `raw_metadata` (pełny payload z KSeF API).
4. Hituje `GET /ui/push` → pairing QR + plaintext code (patrz V5-02).

**Impact:**
- **Leak wszystkich metadanych faktur** (NIP kontrahentów, kwoty, numery) z całego monitorowanego NIP-a.
- **Naruszenie RODO** — NIP kontrahenta to dana osobowa w B2C.
- **Wyciek wywiadu biznesowego** — kto z kim handluje, za ile.

**Remediation (P1):**
```python
# Opcja A (preferred): wymagać auth dla UI jak dla reszty
if path in _EXEMPT_EXACT:
    return await call_next(request)
# Web UI używa tej samej bramy auth + cookie session dla przeglądarki

# Opcja B (doraźna): sprawdzać nagłówek zaufanego proxy
trusted_proxy_header = request.headers.get("X-Forwarded-By-Trusted-Proxy")
if path.startswith("/ui") and not trusted_proxy_header:
    return JSONResponse(status_code=401, content={"detail": "UI requires auth"})
```

Jeśli zostaje bypass — dodać `TrustedHostMiddleware` + CSP + konfig opcja `api.ui_public=false` domyślnie, która **wymaga** auth.

---

### V5-02 (HIGH) — `/ui/push` + `/api/v1/push/devices` leak pairing code / device list bez auth

| Pole | Wartość |
|------|---------|
| **Kategoria** | Information disclosure, authentication bypass |
| **Confidence** | CONFIRMED |
| **CWE** | CWE-200 Exposure of Sensitive Information, CWE-287 Improper Authentication |
| **OWASP** | A01:2021 Broken Access Control |
| **CVSS** | ~7.5 (Network / No Priv / Confidentiality HIGH) |
| **Status** | OPEN |
| **Location** | [app/api/__init__.py:83](../app/api/__init__.py) + [app/api/routers/ui.py:344-357](../app/api/routers/ui.py) + [app/push_manager.py:548-561](../app/push_manager.py) |

**Evidence:**
```python
# api/__init__.py:83 — no-auth whitelist
"/api/v1/push/devices",  # read-only device list in Web UI

# ui.py:356 — exposes pairing_info w UI bez auth
ctx["push"] = push_manager.pairing_info

# push_manager.py:549-561
@property
def pairing_info(self) -> Dict[str, Any]:
    return {
        "instance_id": self.instance_id,
        "pairing_code": self.pairing_code,  # plaintext!
        "registered_at": self.registered_at,
        "is_registered": self.is_registered,
        "qr_data_uri": self.generate_qr_data_uri(),  # base64 PNG QR z plaintext code
    }
```

**Opis:** `pairing_code` = `secrets.token_hex(4).upper()` = **32 bitowy** kod. Używany jako wspólny sekret do parowania iOS app z Docker instance. Ujawniony bez auth na:
- `GET /ui/push` (HTML z QR + tekst)
- `GET /api/v1/push/devices` (lista sparowanych device_id, bez raw tokenów, ale z czasami użycia)

**Attack scenario:**
1. Atakujący uzyskuje pairing code via `curl http://victim:8080/ui/push | grep pairing_code`.
2. Instaluje iOS app Monitor KSeF, wpisuje code ręcznie lub skanuje QR.
3. Od tego momentu **otrzymuje wszystkie notyfikacje push** — każda nowa faktura z KSeF trafia na jego telefon z `seller_name`, `buyer_name`, `gross_amount`, `ksef_number`.
4. Właściciel nic nie zauważa (iOS app oficjalnie wspiera wiele paired devices — `/api/v1/push/devices` lista obejmie "legacy" paired + atakującego).
5. Atak trwa do momentu gdy admin zauważy w `/ui/push` lub wywoła `POST /push/regenerate` (wymaga auth).

**Evidence siły kodu:**
```
pairing_code = secrets.token_hex(4).upper()  # 4 bytes = 32 bits
```
32 bitów = 4.3 mld kombinacji. Z rate limitingiem worker'a po stronie Cloudflare → brute force nierealny; ale **NIE TRZEBA brute-force'ować**, kod jest leakowany w plaintext.

**Impact:** wyciek **każdej faktury** na nieautoryzowane urządzenie w czasie rzeczywistym.

**Remediation (P1):**
```python
# 1. Usuń /api/v1/push/devices z _EXEMPT_EXACT.
# 2. /ui/push wymaga auth — jeśli cookie/session nie wdrożone, wyłącz route.
# 3. pairing_info w UI POWINNO pokazywać tylko hashed pairing_code lub wymagać explicit "Show pairing code" button z CSRF token.
# 4. Rate limit /instances/regenerate-pairing po stronie Dockera (nie tylko workera) + alert do wszystkich paired devices przy każdym nowym pairingu.
# 5. Zwiększyć pairing_code do min. 8 bajtów (16 hex chars).
```

---

### V5-03 (HIGH) — `/api/v1/invoices/{ksef_number}/pdf|xml` auth bypass + brak walidacji formatu → enumeration + header injection

| Pole | Wartość |
|------|---------|
| **Kategoria** | Authentication bypass, Input validation, Header injection |
| **Confidence** | CONFIRMED |
| **CWE** | CWE-287, CWE-20, CWE-113 HTTP Response Splitting |
| **OWASP** | A01:2021, A03:2021 Injection |
| **Status** | OPEN |
| **Location** | [app/api/__init__.py:86-88](../app/api/__init__.py), [app/api/routers/invoices.py:127,180](../app/api/routers/invoices.py) |

**Opis:** Komentarz w `api/__init__.py:74-77` *"invoice file downloads without auth. ... Mutating endpoints (trigger, initial-load, push) still require auth."* — ale **odczyt faktur to też sensytywna operacja** (metadata + pełny XML faktury zawiera numery kont, stawki VAT, pozycje produktowe).

**Sub-findings:**

**(a) Enumeration attack:**
- Brak walidacji formatu `ksef_number` w `get_invoice_pdf` / `get_invoice_xml`. Endpoint zwraca 404 vs 503 różnicowo → można enumerować ważne numery KSeF (10 cyfr NIP + data + 6 alnum + 2 alnum).
- Z samej znajomości NIP-a firmy i zakresu dat można scorer'ować przestrzeń stanów.

**(b) HTTP header injection (niska praktycznie, ale wzorzec niebezpieczny):**
```python
# invoices.py:157,211,247
headers={"Content-Disposition": f'attachment; filename="{ksef_number}.xml"'}
```
Starlette/FastAPI sanityzuje nagłówki, ale wzorzec f-string → header bez walidacji = anti-pattern. Przyszła zmiana mogłaby odkryć prawdziwy CRLF injection.

**(c) Leak przez publikację URL:**
- Web UI generuje klikalne linki: `/api/v1/invoices/{ksef_number}/pdf`. Jeśli admin share'uje URL (screenshot, ticket), URL niesie pełną informację + jest dostępny bez auth.

**Attack scenario:**
1. Atakujący zna NIP firmy (publiczne).
2. Brute-force `GET /api/v1/invoices/{NIP}-{YYYYMMDD}-{XXXXXX}-{YY}/xml` z różnicowaniem błędów → odkrywa istniejące faktury bez auth.
3. Ściąga XML — dostaje wszystkie pozycje, konta bankowe, adresy.

**Remediation (P1):**
1. Usuń `/pdf` i `/xml` z auth bypass — wymagaj auth jak reszta `/api/v1/*`.
2. Walidacja formatu `ksef_number` regex przed query:
   ```python
   _KSEF_PATTERN = re.compile(r"^\d{10}-\d{8}-[A-F0-9]{6}-[A-F0-9]{2}$")
   if not _KSEF_PATTERN.match(ksef_number):
       return JSONResponse(status_code=400, content={"detail": "Invalid format"})
   ```
3. Użyj `urllib.parse.quote(ksef_number)` w `Content-Disposition` lub Starlette helper (`content_disposition_filename`).
4. Rate limit `/invoices/{}/pdf|xml` (np. `10/minute`) — PDF generacja jest CPU-intensive.

---

### V5-04 (HIGH) — Supply chain: brak lockfile, rosnąca liczba niepinowanych deps, v0.4 F-01/F-02 NADAL OPEN

| Pole | Wartość |
|------|---------|
| **Kategoria** | Supply chain, dependency management |
| **Confidence** | CONFIRMED |
| **CVE** | CVE-2025-66418, CVE-2025-66471 (urllib3), CVE-2026-39892 (cryptography), CVE-2025-62727 (starlette), **nowe**: CVE-2024-53981 (python-multipart), CVE-2026-40347 (python-multipart) |
| **Status** | OPEN |
| **Location** | [requirements.txt](../requirements.txt), [pyproject.toml](../pyproject.toml) |

**Opis:** v0.5 dodaje `fastapi` + `uvicorn[standard]` + `slowapi` do `requirements.txt` ale **pyproject.toml nadal ich nie ma** (lines 20-33 — tylko 12 deps jak w v0.4). `cryptography` rozjazd **nadal** (pyproject=46.0.5 vs requirements=46.0.7). `urllib3` i `python-multipart` wciąż niepinowane (transitive via `requests` i `fastapi`).

**Nowe CVE relevantne dla v0.5:**

| CVE | Package | Affected | Fix | Eksploatowalne? |
|-----|---------|----------|-----|-----------------|
| [CVE-2024-53981](https://github.com/advisories/GHSA-59g5-xgcq-4qw3) / [CVE-2026-40347](https://advisories.gitlab.com/pypi/python-multipart/CVE-2026-40347/) | python-multipart | <0.0.18 / <0.0.22 | ≥0.0.22 | **TAK** — v0.5 eksponuje `POST /api/v1/initial-load/start` (JSON body, nie multipart, więc specyficzny CVE nie bezpośrednio; ale app/fastapi może przyjmować multipart w przyszłości dla upload funkcji — defense-in-depth) |
| [CVE-2025-66418](https://github.com/advisories/GHSA-gm62-xv2j-4w53) (CVSS 8.9) | urllib3 | <2.6.0 | ≥2.6.0 | TAK — decompression bomb z dowolnego endpoint HTTP (webhook response, KSeF API response) |
| [CVE-2025-66471](https://github.com/advisories/GHSA-2xpw-w6gg-jr37) | urllib3 | <2.6.0 | ≥2.6.0 | TAK |
| [CVE-2026-39892](https://github.com/advisories/GHSA-p423-j2cm-9vmq) | cryptography | 45.0.0–46.0.6 | ≥46.0.7 | LOW — pyproject.toml instalacja daje podatną wersję |
| [CVE-2025-62727](https://github.com/advisories/GHSA-7f5h-v6xp-fcq8) (CVSS 7.5) | starlette | ≥0.39.0,<0.49.1 | ≥0.49.1 | **TAK w v0.5** — Web UI może w przyszłości dodać `StaticFiles`/`FileResponse` (gdy doda się JS/CSS bundling zamiast Tailwind CDN) |

**Remediation (P1):**
```
# requirements.txt — dodać:
urllib3>=2.6.0,<3.0.0            # CVE-2025-66418/66471
starlette>=0.49.1                 # CVE-2025-62727
python-multipart>=0.0.22,<0.0.23  # CVE-2024-53981, CVE-2026-40347

# pyproject.toml — zsynchronizować z requirements.txt lub użyć dynamic dependencies
# Rozważyć przejście na `uv` / `pip-tools` z `requirements.lock`
```

Plus dodać `syft`/`grype` lub `trivy image` scan w CI workflow (`.github/workflows/docker-publish.yml`).

---

## 4. MEDIUM FINDINGS — v0.5

### V5-05 (MEDIUM) — Brak `Content-Security-Policy` + Tailwind CDN externalnie w Web UI

| Pole | Wartość |
|------|---------|
| **Kategoria** | XSS hardening, supply chain |
| **CWE** | CWE-1021 Improper Restriction of Rendered UI Layers, CWE-829 Inclusion of Functionality from Untrusted Control Sphere |
| **Status** | OPEN |
| **Location** | [app/ui/templates/base.html:7-18](../app/ui/templates/base.html), [app/api/__init__.py:110-117](../app/api/__init__.py) |

**Opis:**
1. Web UI ładuje `https://cdn.tailwindcss.com` — bez Subresource Integrity (`integrity="sha..."`), bez CSP. Kompromitacja CDN = RCE w browser przeglądających admin'a.
2. Security headers middleware ustawia tylko `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Cache-Control: no-store`. **Brak**:
   - `Content-Security-Policy` (XSS mitigation w UI)
   - `Strict-Transport-Security` (HSTS)
   - `Referrer-Policy`
   - `Permissions-Policy`
3. Autoescape w `Jinja2Templates` FastAPI = domyślnie włączone dla `.html` (OK), ale brak defense-in-depth via CSP.

**Remediation (P2):**
1. Self-host Tailwind lub użyj build-time CSS bundling (PostCSS).
2. Dodaj CSP middleware:
   ```python
   response.headers["Content-Security-Policy"] = (
       "default-src 'self'; "
       "script-src 'self' 'sha256-<hash-tailwind-inline-config>'; "
       "style-src 'self' 'unsafe-inline'; "  # Tailwind @layer generates inline styles
       "img-src 'self' data:; "               # data: dla QR kodu
       "connect-src 'self'; "
       "frame-ancestors 'none';"
   )
   response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
   response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
   response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
   ```

---

### V5-06 (MEDIUM) — `rate_limit.trigger` nadal nieaktywowany; dodatkowo brak limitu na `/initial-load/start`, `/push/regenerate`

| Pole | Wartość |
|------|---------|
| **Kategoria** | Resource exhaustion |
| **CWE** | CWE-770 |
| **OWASP** | API4:2023 Unrestricted Resource Consumption |
| **Status** | OPEN (retained + extended) |
| **Location** | [app/api/routers/monitor.py:81](../app/api/routers/monitor.py), [app/api/routers/initial_load.py:52](../app/api/routers/initial_load.py), [app/api/routers/push.py:28,47](../app/api/routers/push.py) |

**Opis:** Jak w v0.4 F-05 — `rate_limit.trigger="2/minute"` nigdzie nie zaaplikowany. W v0.5 doszło więcej endpointów wymagających per-endpoint limitów:
- `POST /initial-load/start` — odpala bulk import (mogłoby to flashować KSeF API i obciążać DB — brak limitu)
- `POST /push/regenerate` — wywołuje zewnętrzny Worker endpoint (push.monitorksef.com) — brak limitu, potencjalny amplification
- `POST /push/reset` — podobnie
- `POST /push/devices/remove` — modyfikuje stan

**Remediation (P2):** zastosować slowapi dekoratory per-endpoint:
```python
@router.post("/monitor/trigger")
@limiter.limit("2/minute")
def trigger_check(request: Request): ...

@router.post("/initial-load/start")
@limiter.limit("1/hour")
def start_initial_load(...): ...

@router.post("/push/regenerate")
@limiter.limit("5/hour")
def regenerate_pairing(...): ...
```

---

### V5-07 (MEDIUM) — `pdf_ksef_generator_url` (CIRFMF) — brak SSRF guard

| Pole | Wartość |
|------|---------|
| **Kategoria** | SSRF (admin-controlled input) |
| **CWE** | CWE-918 |
| **Status** | OPEN |
| **Location** | [app/invoice_pdf_generator.py:1189-1192](../app/invoice_pdf_generator.py) |

**Opis:** CIRFMF PDF generator URL pobierany z `config.storage.pdf_ksef_generator_url`. Walidacja: tylko scheme `http://`/`https://`. Brak:
- Sprawdzenia czy URL resolve'uje do private IP (169.254.x, 10.x, 127.x, ::1)
- Allowlist dozwolonych hostów (np. `ksef-pdf-generator:8080` w compose)

**Attack:** Admin configure'uje nieostrożnie `pdf_ksef_generator_url = "http://169.254.169.254/latest/meta-data/"` → monitor wysyła XML faktury do AWS IMDS (SSRF do cloud metadata). Niski risk bo admin-controlled, ale `webhook_notifier._validate_webhook_url()` już ma gotowy wzorzec do re-use.

**Remediation (P2):** kopiuj logikę walidacji z `webhook_notifier.py:61-91` (scheme + private IP check).

---

### V5-08 (MEDIUM) — `xhtml2pdf.pisa.CreatePDF` nadal bez `link_callback` (retained z v0.4 F-04)

Poziom ryzyka wzrósł: v0.5 dodał drugi template (`invoice_pdf_fa_rr.html.j2`) i mikroserwis CIRFMF. Jeśli admin custom template'uje coś z `<img src="">` lub dołączy `|safe` filter, SSRF/LFI aktywny.

Remediation: patrz v0.4 F-04.

---

### V5-09 (MEDIUM) — `health_check` zwraca hardcoded `version="0.4.0"` w v0.5

| Pole | Wartość |
|------|---------|
| **Kategoria** | Stale code / diagnostic accuracy |
| **Confidence** | CONFIRMED |
| **Status** | OPEN |
| **Location** | [app/api/routers/monitor.py:35](../app/api/routers/monitor.py), [app/api/schemas.py:101-105](../app/api/schemas.py), [app/api/__init__.py:48](../app/api/__init__.py) |

```
monitor.py:35:        version="0.4.0",
schemas.py:104:    version: str = "0.4.0"
api/__init__.py:48:        version="0.4.0",
```

**Opis:** `pyproject.toml` mówi 0.5.0, `/health` mówi 0.4.0, `main.py:57` (check) mówi "KSeF Monitor v0.4". Niespójna wersja w response utrudnia monitoring, SIEM dedup, patch verification, incident response. Nie krytyczne dla bezpieczeństwa, ale dla operational security — tak.

**Remediation (P2):** single-source version: `from app import __version__` (`app/__init__.py:6` ma `__version__ = "2.0.0"` — kolejny rozjazd!). Zunifikować: single-source via `importlib.metadata.version("ksef-monitor")` lub literal w `app/__init__.py` i import wszędzie.

---

## 5. LOW FINDINGS — v0.5

### V5-10 (LOW) — `cdn.tailwindcss.com` bez SRI + fallback offline

Patrz V5-05. Self-host + `integrity` atrybut.

### V5-11 (LOW) — Initial Load job dates bez górnego limitu zakresu

[initial_load.py:76-80](../app/api/routers/initial_load.py) waliduje tylko `start<end`, brak maksymalnego zakresu (np. 5 lat). Admin może przypadkiem odpalić 20-letni import → wiele godzin obciążenia KSeF API + DB. Dodaj `if (end-start).days > 1825: reject`.

### V5-12 (LOW) — `app/__init__.py:6` ma `__version__ = "2.0.0"` — literal oderwany od rzeczywistości

Trzeci rozjazd wersji w repo. Defensive operability.

---

## 6. Status v0.4 findings w v0.5

| v0.4 ID | Opis | Status w v0.5 |
|---------|------|---------------|
| **F-01** | `urllib3` niepinowany (CVE-2025-66418/66471) | ❌ OPEN — nadal brak pin |
| **F-02** | `cryptography` pin rozjazd (pyproject 46.0.5 ❌ vs requirements 46.0.7 ✅) | ❌ OPEN — rozjazd identyczny |
| **F-03** | `starlette` <0.49.1 transitive via fastapi (CVE-2025-62727) | ❌ OPEN (+ratcheted: v0.5 UI wkrótce doda StaticFiles → aktywuje vector) |
| **F-04** | `pisa.CreatePDF` bez `link_callback` | ❌ OPEN |
| **F-05** | `rate_limit.trigger` nieaktywowany | ❌ OPEN (+extended do V5-06) |
| **F-06** | Autoescape tylko dla HTML (JSON templates polegają na `json_escape`) | ❌ OPEN |
| **F-07** | `_migrate_schema` buduje ALTER TABLE przez f-string | ❌ OPEN |
| **F-08** | `get_invoice(ksef_number)` nie waliduje formatu | ❌ OPEN (+ratcheted w V5-03) |
| **F-09** | `entrypoint.sh` wymaga rootful | ❌ OPEN |
| **F-10** | Auto-generated token w logu | ✅ **FIXED częściowo** — teraz zapisywany do `/data/api_token.txt` z 0o600, w logu tylko pierwsze 8 chars (commit `e0e47fc`, `1c53709`) |
| **F-11** | v0.5 threat model needed | ⚠️ **DZIŚ ZWERYFIKOWANE** — threat model nie został wykonany przed mergem test → main; V5-01..V5-04 są bezpośrednią konsekwencją braku threat modelu |

---

## 7. Potwierdzone dobre praktyki w v0.5

| # | Praktyka | Dowód |
|---|----------|-------|
| I1 | CORS wildcard rejected gdy auth enabled | [api/__init__.py:146-150](../app/api/__init__.py) |
| I2 | `hmac.compare_digest` dla auth token | [api/__init__.py:99](../app/api/__init__.py) |
| I3 | Redirects disabled dla wszystkich outbound requests (webhook, push, CIRFMF) | `allow_redirects=False` everywhere |
| I4 | Push credentials storage: DB z 0o600 JSON fallback | [push_manager.py:205-209](../app/push_manager.py) |
| I5 | Worker auth via hashes (`instance_key_hash`, `pairing_code_hash`), nie plaintext | [push_manager.py:262-266](../app/push_manager.py) |
| I6 | `X-Instance-Key` header jako sekret (nie Bearer) = odporny na Bearer token leakage via Referer | [ios_push_notifier.py:113-117](../app/notifiers/ios_push_notifier.py) |
| I7 | defusedxml dla wszystkich schematów (FA2/FA3/FA_RR/PEF) | [invoice_xml_parser.py:32](../app/invoice_xml_parser.py) |
| I8 | Schema detection na podstawie namespace (+ allowlist `_FA3_NAMESPACES` etc.) — odporne na schema spoofing | [invoice_xml_parser.py:40-64](../app/invoice_xml_parser.py) |
| I9 | Pydantic `field_validator` w `StartJobRequest` (subject_types allowlist, date_type allowlist) | [initial_load.py:24-41](../app/api/routers/initial_load.py) |
| I10 | RSA-OAEP SHA-256 dla KSeF token + bulk export encryption | [ksef_client.py:420-428](../app/ksef_client.py), [invoice_export_manager.py:22-25](../app/invoice_export_manager.py) |
| I11 | AES-256-CBC + PKCS7 padding + client-side key dla bulk export (KSeF v2.4 async flow) | [invoice_export_manager.py:66-77](../app/invoice_export_manager.py) |
| I12 | `zipfile.read(meta_name)` po nazwie explicit — brak extractall → no ZipSlip | [invoice_export_manager.py:477](../app/invoice_export_manager.py) |
| I13 | Token saved `/data/api_token.txt` 0o600 zamiast full w logu | [config_manager.py:484-486](../app/config_manager.py) |
| I14 | CIRFMF generator response validation: `pdf_bytes[:4] == b'%PDF'` | [invoice_pdf_generator.py:1209](../app/invoice_pdf_generator.py) |

---

## 8. Priorytety napraw dla release v0.5 GA

### P1 — BLOCKER przed merge `test → main`

1. **V5-01** — Usuń `path.startswith("/ui")` z auth bypass lub wprowadź session auth (cookie + CSRF) dla UI
2. **V5-02** — Ukryj `pairing_code` w UI za gesturem auth + click; zwiększ pairing_code do 64 bitów
3. **V5-03** — Auth+walidacja formatu dla `/invoices/{}/pdf|xml`; użyj `quote()` w Content-Disposition
4. **V5-04** — Pin `urllib3>=2.6.0`, `starlette>=0.49.1`, `python-multipart>=0.0.22`, `cryptography==46.0.7` w obu plikach; dodaj lockfile

### P2 — 1-2 sprints

5. **V5-05** — CSP + HSTS + Referrer-Policy; self-host Tailwind
6. **V5-06** — slowapi dekoratory per-endpoint dla mutujących routes
7. **V5-07** — SSRF validation dla `pdf_ksef_generator_url`
8. **V5-08** (=v0.4 F-04) — `link_callback` dla `pisa.CreatePDF`
9. **V5-09** — single-source version

### P3 — backlog

10. v0.4 F-06/F-07/F-08/F-09 — wszystkie nadal otwarte
11. V5-10, V5-11, V5-12 — defensive polish
12. Dodaj `trivy image` scan w `.github/workflows/docker-publish.yml`

---

## 9. Rekomendacje strategiczne

1. **Threat model workshop przed v0.5 GA** — V5-01..V5-04 to **nie są bug'i, to design decisions** niewykonanego threat modelu. Roadmap v0.4→v0.5 powiedziała "Web UI odczyt" ale nie postawiła pytania "co jeśli port 8080 wycieknie?"
2. **Dwupoziomowa auth**: `api.auth_token` (maszynowy, Bearer) + `api.ui_auth` (przeglądarkowy, cookie session + CSRF). FastAPI ma gotowe `OAuth2PasswordBearer` + `fastapi-login`/`fastapi-users`.
3. **Lockfile + SBOM** — `uv pip compile requirements.in -o requirements.lock` + `syft .` w CI.
4. **Permission model**: rozważyć read-only vs read-write tokens (jak GitHub PAT scopes). Dashboard read-only, actions wymagają write-token.
5. **Network segmentation** w docker-compose: oddzielny network dla CIRFMF generator (nie `bridge`).
6. **Secrets rotation** dokumentacja: jak rotować `api_auth_token`, `instance_key`, `ksef_token` bez downtime.

---

## 10. Źródła (CVE/GHSA — zweryfikowane WebSearch 2026-04-21)

- [CVE-2025-66418 — urllib3 DoS (GHSA-gm62-xv2j-4w53)](https://github.com/advisories/GHSA-gm62-xv2j-4w53)
- [CVE-2025-66471 — urllib3 streaming DoS (GHSA-2xpw-w6gg-jr37)](https://github.com/advisories/GHSA-2xpw-w6gg-jr37)
- [CVE-2025-62727 — Starlette FileResponse Range DoS (GHSA-7f5h-v6xp-fcq8)](https://github.com/advisories/GHSA-7f5h-v6xp-fcq8)
- [CVE-2026-39892 — cryptography OOB read (GHSA-p423-j2cm-9vmq)](https://github.com/advisories/GHSA-p423-j2cm-9vmq)
- [CVE-2024-53981 — python-multipart log DoS](https://www.sentinelone.com/vulnerability-database/cve-2024-53981/)
- [CVE-2026-40347 — python-multipart preamble DoS](https://advisories.gitlab.com/pypi/python-multipart/CVE-2026-40347/)
- [CVE-2026-24486 — python-multipart path traversal](https://www.sentinelone.com/vulnerability-database/cve-2026-24486/)
- [FastAPI XSS / CSP best practices (Snyk, Escape.tech)](https://escape.tech/blog/how-to-secure-fastapi-api/)
- [CodeQL — Jinja2 autoescape=False](https://codeql.github.com/codeql-query-help/python/py-jinja2-autoescape-false/)
- Poprzedni audyt: [20260421_security_audit_docker_v0_4_pre_v0_5.md](./20260421_security_audit_docker_v0_4_pre_v0_5.md), [re_audit_finding.md](./re_audit_finding.md)

---

## 11. Metadane audytu

- **Branch audited:** `test` (commit `f7aa694`)
- **Baseline diff:** `main..test` = 57 files, 8315 additions
- **Nowe moduły w audycie:** `push_manager.py`, `initial_load_manager.py`, `invoice_export_manager.py`, `ios_push_notifier.py`, `app/api/routers/{push,initial_load,ui}.py`, `app/ui/templates/*`
- **Narzędzia:** WebSearch (NVD/GHSA), grep/Grep, Read, git diff
- **Nie wykonano:** live `pip-audit` / `osv-scanner` / `trivy image` (brak dostępu do zbudowanego obrazu; rekomendowane w CI)
- **Anti-hallucination checklist ✅** — wszystkie 6 cytowanych CVE zweryfikowane WebSearch z direct URL do GHSA/NVD

**Auditor:** Claude Code + security-audit skill
**Timestamp:** 2026-04-21
