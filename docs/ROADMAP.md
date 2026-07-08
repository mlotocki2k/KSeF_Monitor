# Roadmap

## v0.2 ✅ (zrobione)
**Cel:** podstawowa obserwowalność + dostęp do PDF

- [x] Endpoint pod Prometheusa
- [x] Pobieranie obrazu/PDF wybranej faktury

**DoD:** metryki widoczne w Prometheusie, PDF/obraz faktury do pobrania dla wskazanego dokumentu.

---

## v0.3 ✅ (zrobione)
**Cel:** ustandaryzować komunikację i zacząć trwale trzymać dane o fakturach (fundament: templating + DB)

### 1) Powiadomienia oparte o template ✅
- [x] System szablonów Jinja2 z osobnym szablonem per kanał (5 szablonów)
- [x] `TemplateRenderer` z custom filtrami (`money`, `money_raw`, `date`, `json_escape`)
- [x] Możliwość podmiany szablonów przez użytkownika (`templates_dir` w config)
- [x] Fallback na wbudowane domyślne szablony + plain text przy błędach
- [x] Polskie formatowanie kwot (`,` separator dziesiętny, spacja tysięcy, kod waluty)
- [x] Dokumentacja: [TEMPLATES.md](TEMPLATES.md) — zmienne, filtry, przykłady modyfikacji

### 2) Template generowania obrazu faktury ✅
- [x] HTML/CSS template (Jinja2) → render do PDF przez xhtml2pdf
- [x] `InvoicePDFTemplateRenderer` z custom filtrami (`fmt_amt`, `vat_label`, `payment_method`)
- [x] Możliwość podmiany szablonu przez użytkownika (`pdf_templates_dir` w config storage)
- [x] Automatyczny fallback na ReportLab generator przy błędach lub braku xhtml2pdf
- [x] Dynamiczne kolumny tabeli pozycji (warunkowe wyświetlanie)
- [x] QR Code Type I jako base64 data URI w HTML
- [x] Dokumentacja: [PDF_TEMPLATES.md](PDF_TEMPLATES.md) — zmienne, filtry, CSS customizacja

### 3) Formatowanie/zapisywanie (struktura folderów + nazwy plików) ✅
- [x] Konfigurowalna struktura folderów (`folder_structure` w config storage)
- [x] Placeholdery folderów: `{year}`, `{month}`, `{day}`, `{type}` (sprzedaz/zakup)
- [x] Konfigurowalne nazwy plików (`file_name_pattern` w config storage)
- [x] Placeholdery nazw: `{type}` (sprz/zak), `{date}`, `{invoice_number}`, `{ksef}`, `{ksef_short}`, `{seller_nip}`, `{buyer_nip}`
- [x] Walidacja wzorców w config_manager (tylko dozwolone placeholdery)
- [x] Path traversal guard na wynikowej ścieżce
- [x] Backward compatible: domyślny pattern `{type}_{date}_{invoice_number}`

### 4) Safecheck na overwrite plików ✅
- [x] Sprawdzanie czy plik (XML/PDF) już istnieje przed zapisem
- [x] Strategia: skip / rename / overwrite (`file_exists_strategy` w config storage)

### 5) Przeniesienie informacji o fakturach do bazy ✅
- [x] SQLite + WAL mode + SQLAlchemy 2.0 ORM + Alembic migracje
- [x] Tabele: `invoices`, `monitor_state`, `notification_log` + indeksy
- [x] Model danych rozdzielony "per subject, per NIP" (UNIQUE na `ksef_number`)
- [x] Zapis metadanych przy detekcji faktury + ścieżki artefaktów
- [x] Odczyt `last_check` z DB (monitor_state) z fallbackiem na JSON
- [x] Automatyczna migracja `last_check.json` → DB (rename na `.json.migrated`)
- [x] Notification log — dedup, diagnostyka, audyt powiadomień per kanał
- [x] Error tracking w `monitor_state` (consecutive_errors, last_error)
- [x] Konfiguracja: sekcja `database` w config (enabled, path)
- [x] Design: [DATABASE_DESIGN.md](DATABASE_DESIGN.md)

### 6) Dokumentacja ograniczeń API ✅
- [x] Kompletna dokumentacja limitów KSeF API: [KSEF_API_LIMITATIONS.md](KSEF_API_LIMITATIONS.md)
- [x] Plan globalnego rate limitera: [RATE_LIMITING_DESIGN.md](RATE_LIMITING_DESIGN.md)

**Zależności:** v0.2
**DoD:** powiadomienia i obraz faktury generują się wyłącznie z template; faktury lądują w DB i da się je filtrować per subject/NIP.

---

## Infrastruktura i jakość ✅ (zrobione w ramach v0.3)
Poprawki niezwiązane z konkretnymi feature'ami, ale krytyczne dla stabilności:

### Bezpieczeństwo
- [x] Security audit: 22 findings (C1-C2, H1-H5, M1-M8, L1-L3) — naprawione
- [x] Re-audit: Docker hardening (M7, L1, N1-N5)
- [x] SHA-256 deduplication (zamiast MD5) w `seen_invoices`
- [x] Atomic state write (`last_check.json` — tmp + rename + fsync)
- [x] Path traversal guards w `_resolve_output_dir()` i `_save_invoice_artifacts()`
- [x] Input sanitization (`_sanitize_field()`) w template context

### KSeF API client (#13-#17)
- [x] **#13** Pełna paginacja `get_invoices_metadata()` — `hasMore`/`isTruncated`, max 250/page, safety limit 10 000
- [x] **#14** Cap `dateRange` do 90 dni (KSeF API 3-month limit) z WARNING
- [x] **#15** `_extract_api_error_details()` — parsowanie `problem+json` i `ExceptionResponse`
- [x] **#15** `_handle_401_refresh()` — deduplikacja obsługi wygasłego tokena
- [x] **#16** Aktualizacja `spec/openapi.json` → KSeF API v2.2.0
- [x] **#17** Logowanie `authenticationMethodInfo` na DEBUG (zastępuje deprecated `authenticationMethod`)
- [x] Fix: `pageSize`/`pageOffset` jako query params (nie body) — zgodność ze specyfikacją
- [x] Fix: `dateRange` lowercase `from`/`to` (nie `From`/`To`)
- [x] Warning przy naive datetime w state file

### Operacje
- [x] On-demand trigger: `docker kill -s SIGUSR1 <container>` — natychmiastowe sprawdzenie faktur poza harmonogramem

### Docker i CI
- [x] Entrypoint z dynamicznym ownership (`gosu`)
- [x] Named volume + config mount separation (`/config` vs `/data`)
- [x] 429 retry z backoff + parsowanie `Retry-After` (HTTP-date i sekundy)
- [x] KSeF number validation regex
- [x] CI: build & push Docker image (test + main)
- [x] CI: automatyczne sprawdzanie outdated Python packages → issue + PR
- [x] CI: sprawdzanie zmian OpenAPI spec KSeF (3 środowiska: test, demo, production) z Pushover notification
- [x] Deprecated `datetime.utcnow()` → `datetime.now(timezone.utc)`
- [x] `prometheus-client` 0.23.1 → 0.24.1

### GitHub visibility & community
- [x] README: badge'e (Docker, KSeF API, Prometheus, CI status) + sekcja Quick Start
- [x] Dockerfile: OCI image labels (title, description, source, license, vendor)
- [x] Community health files: CONTRIBUTING.md, CODE_OF_CONDUCT.md
- [x] Issue templates (bug report, feature request) + PR template
- [x] `pyproject.toml` — metadane projektu Python
- [x] Repo metadata: description + topics (ksef, e-faktura, invoice, python, docker, etc.)
- [x] CI: sprawdzanie zmian FA(3)/FA(2) XSD schema z Pushover notification
- [x] Fix `.gitignore`: `.github/` nie jest już ignorowane

---

## v0.4 ✅ (zrobione)
**Cel:** przygotować solidne backend API i jakość pod web UI + initial load

### 1) Refaktoring (bez zmian zachowania) ✅
- [x] Rozbicie `invoice_pdf_generator.py` (1792 linii) na 3 moduły: `pdf_constants.py`, `invoice_xml_parser.py`, `invoice_pdf_generator.py`
- [x] Unifikacja 401-retry w `ksef_client.py` → `_make_authenticated_request()`
- [x] Rozbicie `check_for_new_invoices()` w `invoice_monitor.py` na mniejsze metody
- [x] Data-driven walidacja w `config_manager.py` — `_CHANNEL_VALIDATORS`
- [x] Deduplikacja logiki QR code i fontów między PDF generator a template

### 2) Rate Limiter ✅
- [x] `app/rate_limiter.py` — sliding window, 3 okna (10/s, 30/min, 120/h), thread-safe, fail-closed
- [x] Integracja z `ksef_client.py` — `acquire()` przed każdym HTTP call
- [x] `pause_until()` na 429 Retry-After, usunięcie `time.sleep(2)` z monitora
- [x] Konfiguracja: sekcja `ksef.rate_limit` z defaults

### 3) Baza danych — Phase 2 ✅
- [x] `ApiRequestLog` — śledzenie wywołań KSeF Monitor API (endpoint, status, timing)
- [x] `InvoiceArtifact` — status pobierania artefaktów (pending/downloaded/failed, retry counter, SHA-256 hash)
- [x] Rozszerzenie `Invoice` o pole `source`; CRUD metody; migracja Alembic

### 4) REST API (FastAPI) ✅
- [x] `app/api/` — auth middleware (Bearer + `hmac.compare_digest`), security headers, CORS
- [x] Endpointy: `/invoices` (paginacja, filtry, sort), `/invoices/{ksef_number}`, `/stats/summary`, `/stats/api`, `/monitor/health`, `/monitor/state`, `/monitor/trigger`, `/artifacts/pending`
- [x] Swagger docs na `/docs`, `APIServer` w daemon thread, config sekcja `api`

### 5) Auth + Metryki Prometheus ✅
- [x] Token auth z Docker secrets / env / config, open access mode z WARNING
- [x] 6 nowych metryk Prometheus (API requests, response time, rate limit, artifacts)
- [x] Podpięcie metryk do kodu: `ksef_client._request_with_retry()`, REST API middleware, `invoice_monitor` (artifacts gauge)

### 6) Security Audit ✅
- [x] F-01: Auto-generowanie `auth_token` gdy API włączone bez tokena (`secrets.token_urlsafe(48)`)
- [x] F-02: `docs_enabled` parametr — wyłączanie `/docs`, `/redoc`, `/openapi.json` w produkcji
- [x] F-03: Prometheus default bind zmieniony z `0.0.0.0` na `127.0.0.1`
- [x] F-04: Escapowanie HTML w emailach (`html.escape()`)
- [x] F-06: CRLF stripping w nagłówku Subject emaila (header injection)
- [x] F-07: Rate limiting API (slowapi middleware, `60/minute` default)
- [x] F-09: Usunięcie `auth_enabled` z `/health` response (info disclosure)
- [x] F-10: CORS wildcard `*` odrzucany gdy `auth_token` ustawiony
- [x] F-11: Jinja2 `SandboxedEnvironment` (SSTI prevention)
- [x] N-03: `allow_redirects=False` na webhookach (SSRF redirect blocking)
- [x] `API_AUTH_TOKEN` w `secrets_manager.py` (Docker secrets flow)

### 7) Testy ✅
- [x] 105 nowych testów (rate limiter, DB phase 2, API auth, invoices, stats, monitor)
- [x] 34 testów security audit (HTML escaping, SSRF, auth, sandbox, rate limit, docs, CORS, CRLF)
- [x] Łącznie: **423 testy**, 0 failures

**Zależności:** v0.3
**DoD:** UI może bazować na stabilnym API; system jest odporny na retry i ma podstawową telemetrię operacyjną.

---

## v0.5 (Initial load + Web UI: odczyt) ✅ (zrobione)
**Cel:** pierwszy sensowny produkt dla użytkownika: dane + podgląd

### 1) Initial load (dane historyczne) ✅
- [x] od `2026-02-01` albo data definiowana w config (`initial_load.start_date`)
- [x] tryb: jednorazowy import + zapis do DB + raport (ile pobrano, ile pominięto)
- [x] **Moving window** — obejście limitu 90 dni (3 miesiące) API KSeF:
  - automatyczne dzielenie zakresu dat na okna ≤90 dni
  - sekwencyjne pobieranie okno po oknie z paginacją w każdym
  - progress tracking: zapis postępu (ostatnie zakończone okno) → resume po przerwaniu
  - rate limiting / backoff między oknami (unikanie throttlingu API)

### 2) Interfejs webowy (odczyt) ✅
- [x] Dashboard: statystyki faktur, stan monitora, ostatnio dodane, widget KSeF API status
- [x] Widget KSeF API status: polling `/api/v1/monitor/ksef-status`, badge dostępności, latencja
- [x] Lista faktur: filtry (typ, NIP, daty, szukaj), sort, paginacja, zaznaczanie, bulk PDF
- [x] Podgląd faktury: metadane, kwoty, daty, pobieranie PDF i XML z cache lub live z KSeF
- [x] Podgląd initial load: progress bar, status okien, log operacji
- [x] Tailwind CSS CDN — zero build step, responsywny layout
- [x] Auth bypass dla `/ui` (token z localStorage, taki sam jak API)
- [x] `app/api/routers/ui.py` — trasy Jinja2 SSR dla wszystkich widoków
- [x] integracja z oficjalną biblioteką CIRFMF ([ksef-pdf-generator](https://github.com/CIRFMF/ksef-pdf-generator)) jako opcjonalny mikroserwis (`storage.pdf_ksef_generator_url`)

### 3) Push notyfikacje iOS — Monitor KSeF (Cloudflare Worker) ✅
- nowy kanał powiadomień: natywne push notifications na iOS via aplikację **Monitor KSeF**
- Aplikacja iOS: Monitor KSeF (dostępna w App Store, v1.1.2+ — parowanie push działa)
- **Architektura** (wg `architektura_push_notifications_v1_1_PL.md`):
  - Central Push Service: Cloudflare Worker (`push.monitorksef.com`) jako proxy do APNs
  - Worker przechowuje klucz .p8 — nigdy nie opuszcza Worker
  - Autentykacja Worker ↔ APNs: token-based auth (JWT ES256, .p8 key)
  - Autentykacja Monitor → Worker: `X-Instance-Id` + `X-Instance-Key` headers
  - Payload: `{title, body, data}` — Worker buduje envelope `aps`
- **Parowanie instancji Docker ↔ iOS**:
  - Docker generuje `instance_id` (UUID), `instance_key` (32B random), `pairing_code` (8 hex)
  - Docker rejestruje instancję w Worker (`POST /instances/register`, hashe SHA-256)
  - Docker wyświetla QR code z `MKSEF:{pairing_code}` w Web UI (`/api/v1/push/setup`)
  - iOS skanuje QR → wysyła `device_token` + `pairing_code` do Worker → mapowanie

- [x] `app/push_manager.py` — PushManager: credentials, rejestracja, QR, wysyłka
- [x] `app/notifiers/ios_push_notifier.py` — IosPushNotifier (integracja z NotificationManager)
- [x] `app/templates/ios_push.json.j2` — szablon payloadu push
- [x] `app/api/routers/push.py` — REST endpoint `/api/v1/push/setup`, `/push/regenerate`, `/push/reset`
- [x] Konfiguracja w `config.json`: sekcja `notifications.ios_push`
- [x] Secret: `IOS_PUSH_INSTANCE_KEY` (env var / Docker secret)
- [x] Credentials auto-generowane przez PushManager na pierwszym uruchomieniu
- [x] QR code ASCII w logach przy starcie
- [x] Parowanie iOS: pairing_code + Worker registration
- [x] Baza danych Phase 3: tabela `push_instances` (alembic migration)
- [x] 62 nowe testy (`test_ios_push_notifier.py`, `test_push_manager.py`)

### 4) Obsługa wszystkich schematów faktur KSeF
Cel: uniwersalny monitor i generator PDF dla każdego typu faktury w KSeF — nie tylko FA(3).

**Obsługiwane schematy (per KSeF API v2.2):**
| Schema | SchemaVersion | Typ | Opis |
|---|---|---|---|
| FA (2) | 1-0E | FA | Faktura VAT (starsza wersja) |
| FA (3) | 1-0E | FA | Faktura VAT (aktualna) |
| PEF (3) | 2-1 | PEF | Platforma Elektronicznego Fakturowania (zamówienia publiczne) |
| PEF_KOR (3) | 2-1 | PEF | Korekta PEF |
| FA_RR (1) | 1-0E | RR | Faktura VAT RR (rolnik ryczałtowy) |
| FA_RR (1) | 1-1E | RR | Faktura VAT RR (nowa wersja, obowiązkowa od 01.04.2026) |

**Zakres prac:**
- [x] Architektura multi-schema: `BaseInvoiceXMLParser` + `create_invoice_xml_parser()` factory
- [x] Auto-detekcja schematu z namespace XML (bez konfiguracji — `detect_schema_type()`)
- [x] Parser FA(2) — mapowanie pól na wspólny model danych (obsługa obu namespace URI)
- [x] Parser PEF(3) / PEF_KOR(3) — `PEFInvoiceXMLParser` (UBL CBC/CAC namespaces)
- [x] Parser FA_RR(1) — `FA_RRInvoiceXMLParser` (⚠️ w v0.5 niefunkcjonalny: zły namespace + zmyślone pola; przepisany w v0.6 — patrz niżej)
- [x] Template PDF per schemat — `invoice_pdf_fa_rr.html.j2` dla FA_RR, PEF → ReportLab minimal
- [x] Fallback: nieznany schemat → zapis XML bez PDF + warning w logu i powiadomieniu
- [x] Specyfikacje XSD stubs: `spec/schemat_FA(2)_v1-0E.xsd`, `spec/schemat_FA_RR_v1-0E.xsd` (zastąpione realnymi XSD w v0.6)
- [x] Aktualizacja szablonów powiadomień — pole `schema_type` w webhook.json.j2 i ios_push.json.j2
- [x] Dokumentacja: rozszerzenie `PDF_TEMPLATES.md` o nowe schematy i CIRFMF integrację
- [x] 50 nowych testów (`test_multi_schema_parser.py`)

### 5) Security hardening — audit remediation ✅
_Źródło: `audit/20260421_security_audit_docker_v0_5_test_branch.md` + `audit/20260422_security_reaudit_v0_5_post_remediation.md`. Pełna lista zmian: `CHANGELOG.md` [0.5.0]._

- [x] **V5-01** Zawężenie whitelist auth do `{/docs, /redoc, /openapi.json, /api/v1/monitor/health}`. Nowa opcja `api.ui_public` (domyślnie `false`) jako opt-in dla reverse-proxy.
- [x] **V5-02** Pairing code rozszerzony 32-bit → 64-bit, maskowany w UI (`X…Y`). Plaintext code + QR przeniesiony za auth do `GET /api/v1/push/pairing`.
- [x] **V5-03** Auth bypass `/invoices/{ksef}/pdf|xml` usunięty. `KsefNumberPath` Pydantic type waliduje `ksef_number` na poziomie path-param (422 przy niezgodności). `Content-Disposition` używa `urllib.parse.quote()`.
- [x] **V5-04** CVE-driven pinning: `urllib3>=2.6.3`, `starlette>=0.49.1,<1.0.0`, `python-multipart>=0.0.26`, `cryptography==46.0.7`. `requirements.lock` z hashami, CI: `pip-audit` + `trivy image`.
- [x] **V5-05** Security headers: CSP, HSTS (`max-age=31536000`), `Referrer-Policy`, `Permissions-Policy`.
- [x] **V5-06** Per-endpoint rate limity: `/monitor/trigger` 2/min, `/initial-load/start` 1/hr, `/push/regenerate` 5/hr, `/push/reset` 1/hr, `/invoices/{}/pdf|xml` 30/min. Konfigurowalne przez `api.rate_limit.*`.
- [x] **V5-07** SSRF guard `app._ssrf_guard.is_safe_public_url` — wspólny walidator dla webhook + CIRFMF PDF generator URL.
- [x] **V5-08** `xhtml2pdf` `link_callback` blokuje zewnętrzne URI — dozwolone tylko `data:` i ścieżki bundlowanych szablonów.
- [x] **V5-09/V5-12** Ujednolicenie stringa wersji do `0.5.0`, single-source przez `app.__version__`.
- [x] **V5-10** Tailwind CSS self-hosted (`app/ui/static/tailwind.min.css`, 14 KB). Usunięta zależność CDN.
- [x] **V5-11** `StartJobRequest` odrzuca zakresy dat > 5 lat przez Pydantic `model_validator`.
- [x] **v0.4 F-06** Jinja2 autoescape extension-driven — callable `_jinja_autoescape(name)`.
- [x] **v0.4 F-07** `_migrate_schema` zastąpiony przez `alembic.command.upgrade(head)` / `stamp(head)`.
- [x] **v0.4 F-09** `entrypoint.sh` — rootless mode: `id -u` check, pomija `usermod`/`chown` gdy non-root.

### Zmiany API / schema ✅
- [x] KSeF API v2.4.0: Problem Details, 429 retry, 410 Gone, isTruncated pagination, API status monitor
- [x] `GET /api/v1/monitor/ksef-status` — probe dostępności API bez logowania
- [x] `GET /api/v1/invoices/{ksef_number}/xml` — pobieranie XML (cache → live KSeF fallback)
- [x] `GET /api/v1/invoices/{ksef_number}/pdf` — pobieranie PDF (cache → generuj on-demand)
- [x] `storage.pdf_ksef_generator_url` — opcjonalny CIRFMF microservice jako pierwszy renderer

**Zależności:** v0.4
**DoD:** ✅ użytkownik widzi dashboard + listę + podgląd; initial load działa powtarzalnie bez duplikatów; push notification dociera na iOS; PDF generuje się poprawnie dla każdego typu faktury obsługiwanego przez KSeF. **581 testów, 0 failures.**

---

## v0.5.1 (UI auth UX) ✅
_Źródło: regresja UX po V5-01 — token modal blokował dashboard. Pełna lista: `CHANGELOG.md` [0.5.1]._

- [x] **V5-12** Cookie session zamiast localStorage Bearer (interim — value = api.auth_token).
- [x] **V5-13** User accounts w DB (bcrypt) + opaque DB-backed sessions (256-bit, 7-dni rolling TTL).
  - Tabele `ui_users`, `ui_sessions` (Alembic head: `e0f1g2h34567`).
  - First-launch wizard `/ui/setup` (form: username + password); locks idempotently po pierwszym userze.
  - `/ui/login`, `/ui/logout`, `/ui/account` (zmiana hasła revoke wszystkie sesje, w tym bieżącą).
  - Bearer nadal działa równolegle dla curl/iOS pairing/integracji.
  - Rate limit: `POST /ui/login` 5/min, `/ui/setup` 3/min, `/ui/account/password` 5/min.
  - Open-redirect guard na `next=`; cookie `HttpOnly`+`SameSite=Strict`+`Secure` (https).
  - **Upgrade-friendly:** main.py auto-tworzy usera `admin` z `password = api.auth_token` przy pierwszym starcie z istniejącym tokenem i pustą tabelą userów. Zero key regeneration.
  - CLI: `python -m app.user_admin {list, add, reset-password, delete, cleanup-sessions}`.
- [x] **deps:** `bcrypt>=4.2.0,<5.0.0`.
- [x] **V5-14** Regresja `/ui/account` pod `ui_public=true` / `auth_token=""` — split middleware: `resolve_ui_session` (ZAWSZE) + `verify_auth` (gate tylko gdy `auth_token`). Cookie state populowany niezależnie od ścieżki auth. 4 regresyjne testy.
- [x] **V5-15** Dark theme spójny z iOS app — paleta 1:1 z `monitor_ksef_ios/.../Assets.xcassets/*.colorset` (dark appearance). `--app-bg #0B1A3E`, `--accent #007AFF`, iOS status colors. Ikona `AppIcon.appiconset/icon_dark_1024.png` reuse (128/64/32 PNG). Dark-only (`color-scheme: dark`); plain CSS (prebuilt tailwind.min.css bez JIT). `base.html`, `login.html`, `setup.html` przepisane.
- [x] **V5-16** Fix `POST /api/v1/monitor/trigger` — router wołał nieistniejącą `monitor.scheduler.force_next_run()`. Podmiana na `monitor.trigger_check()` (istniejąca metoda w `InvoiceMonitor`, flipuje `_manual_trigger`). Testy `test_api_monitor.py`, `test_api_rate_limit.py` zaktualizowane.
- [x] **V5-17** Fix stopki PDF — oba generatory (`InvoicePDFGenerator` ReportLab + `invoice_pdf.html.j2` xhtml2pdf) miały hardcoded `v0.3`. Teraz czytają `app.__version__` (single source of truth). Footer na test: `v0.5.1`.
- [x] **testy:** `tests/test_ui_user_auth.py` (55 testów, w tym 4 z `TestSessionResolver`); `test_api_auth.py`, `test_api_monitor.py`, `test_api_rate_limit.py` zaktualizowane; head ref w `test_db_migration.py` bumped. **114+ testów passes.**

**Follow-ups (non-blocking):**
- Multi-user admin panel w UI (obecnie CLI-only)
- Opcjonalny 2FA / TOTP
- Lista aktywnych sesji w `/ui/account` (revoke per-device)
- Rotacja cookie value przy każdym requeście (defense-in-depth)
- Light-mode toggle (obecnie dark-only)

---

## v0.5.2 (UI auth security audit remediation) ✅
_Źródło: focused audyt V5-12/V5-13/V5-14 → `audit/20260504_security_audit_v0_5_1_ui_auth.md`. Pełna lista zmian: `CHANGELOG.md` [0.5.2]._

Audyt dał 0 CRITICAL, 0 HIGH, 6 MEDIUM, 6 LOW, 5 INFO. Wszystkie 14 punktów zaadresowane.

### Sesja
- [x] **U-01** `api.cookie_secure_mode` (`auto`/`always`/`never`) + honor `X-Forwarded-Proto`. Default `auto` — w prod za reverse-proxy cookie dostaje `Secure` mimo `request.url.scheme="http"`.
- [x] **U-04** Opt-in `api.session_strict_binding` — SHA-256(UA) w `ui_sessions.ua_hash` (alembic phase7), mismatch → revoke. Legacy rows bez `ua_hash` grandfathered.
- [x] **U-09** Absolute lifetime cap 30 dni (`SESSION_ABSOLUTE_LIFETIME`) — sliding renew nie omija.
- [x] **U-12** Audit log: session create/revoke/eviction, lockout. `username_len` zamiast raw username (U-08 partial).

### Auth strength
- [x] **U-02** SHA-256+b64 pre-hash dla haseł >72B → bcrypt 5.0-ready (5.0 rzuca `ValueError`, byłby DoS na obecnych userach z długimi hasłami).
- [x] **U-03** Per-username brute-force lockout: tabela `ui_login_attempts` (alembic phase6), 5 fails / 15 min sliding → 15 min lock. Check przed bcrypt.
- [x] **U-07** Constant-time login: bcrypt zawsze (dummy hash dla nieistniejącego usera) → bez timing oracle dla username enumeration.
- [x] **U-11** Password strength: blocklist top-100 (rockyou, in-process, NIST SP 800-63B) + reject jeśli zawiera username (≥3 chars, case-insensitive).

### Setup wizard
- [x] **U-06** `create_first_admin_atomic()` z `BEGIN IMMEDIATE` (SQLite RESERVED lock) — concurrent setup POSTs nie tworzą drugiego konta admin.

### Web hardening
- [x] **U-05** CSP `script-src` używa per-request nonce (16-byte `secrets.token_urlsafe`) zamiast `'unsafe-inline'`. Wszystkie inline `<script>` w templates niosą `nonce="{{ request.state.csp_nonce }}"`. `style-src 'unsafe-inline'` zostaje (carryover).
- [x] **U-10** `_safe_next()` strict prefix — odrzuca `/ui-attacker/…`.

### Code quality
- [x] **U-13** `count_users()` używa `COUNT(*)` zamiast materializacji wszystkich row IDs.
- [x] **U-15** `resolve_ui_session` catch tylko `(OperationalError, DBAPIError)` — programming errors propagują się normalnie do 500 handler.
- [x] **U-17** Username case-insensitive (`func.lower`): lookup, lockout key, login flow. `admin`/`Admin`/`ADMIN` → ten sam wpis, ten sam licznik.

### Migrations
- [x] `f1a2b3c45678` — phase6 `ui_login_attempts`
- [x] `g2b3c4d56789` — phase7 `ui_sessions.ua_hash`

### Testy
- [x] `tests/test_ui_user_auth.py` 91 testów (był 57). Nowe klasy: `TestUsernameCaseInsensitive` (3), `TestLoginLockout` (7), `TestCookieSecureFlag` (6), `TestSessionUaBinding` (6), `TestCspNonce` (3); rozszerzenia w `TestPasswordHashing`, `TestSetupWizard`, `TestSessionLifecycle`, `TestValidation`.
- [x] `tests/test_db_migration.py` head ref bumped do `g2b3c4d56789`.

### Bonus (równolegle z audit-remediation)
- [x] `chore: sync spec/openapi.json with KSeF production (2026-04-23 build)` — closes #51 (RR enum cleanup, 16-hex validation, build `20260422.4 → 20260423.2`).
- [x] `ci(deps): respect wontfix label` — workflow `check-requirements-updates.yml` nie reopenuje issues z labelem `wontfix` dopóki tylko stare paczki są outdated; nowe paczki tworzą fresh issue (closes recurring noise from #28).

---

## v0.5.3 (post-0.5.2 hotfix bundle) ✅
_Pełna lista zmian: `CHANGELOG.md` [0.5.3]. Siedem defektów wykrytych w pre-merge user-test 0.5.2 — żaden nie był złapany przez cykl audytu._

### Showstoppery
- [x] **Fresh-install lockout (UI)** — auto-gen `auth_token` + bootstrap admin = ten sam token blokował GUI. `ConfigManager` ustawia `api["_auth_token_auto_generated"]`, `main.py` skipuje bootstrap przy markerze. Wizard `/ui/setup` jedynym entry point dla fresh install. Bootstrap zostaje przy operator-supplied token (upgrade v0.5.0).
- [x] **Initial load: każda faktura odrzucona** — `_map_export_invoice` używał pre-v2.x nazw pól. Re-mapped do v2.4 `InvoiceMetadata` schema (`ksefNumber`, `grossAmount`, `seller.nip`, `invoiceHash` jako string), legacy keys jako fallback. Bonus: `isSelfInvoicing`, `hasAttachment`.
- [x] **Initial load: KSeF 21405 co drugie okno** — `cursor + timedelta(days=90)` daje 91-day inclusive window. Fix: `_WINDOW_SPAN = 89` + cursor advance `+1day`. To samo w `InvoiceMonitor._cap_date_from`.

### Logowanie
- [x] **U-12 audit log silently dropped (wszystkie `logger.info`)** — `alembic.ini` `[logger_root] level = WARNING` nadpisywało app config przez `fileConfig()`. Fix: WARNING → INFO. 5 z 7 zdarzeń U-12 (session create/revoke, password change, user create, absolute-cap eviction) niewidocznych w prod aż do tego fixa.

### GUI
- [x] **Progress bar 50% pod "Ukończony"** — `windows_completed_delta=1` tylko przy success. Bump też na non-fatal failure path. Nowy status `completed_with_errors` + amber badge "Ukończony z błędami" + callout "Niepowodzenia okien" z `error_message` (top 5).
- [x] **Per-window history (phase 8)** — nowa tabela `initial_load_windows` (FK CASCADE, idx `(job_id, created_at)`) zapisuje każde okno: typ, range, status, imported, skipped, error, duration_ms. Endpoint `GET /api/v1/initial-load/windows?job_id=…` + toggle "Pokaż historię okien" w karcie status (lazy-loaded tabelka, brak inline event handlers — CSP nonce intact).
- [x] **Logo↔menu spacing** — active nav-link niebieskie tło zlewało się z brand text. `ml-2 sm:ml-4` na `<nav>`, prawa strona spacing bez zmian.

### Dokumentacja
- [x] **iOS App Store status notice** — (historyczne: App Store v1.0.2 nie obsługiwał parowania push; amber callout w `/ui/push` + blockquote w `README.md` kierujące na TestFlight). **Nieaktualne od v1.1.2 (2026-07-08): parowanie push działa w App Store; blockquote README zaktualizowany, amber callout w `/ui/push` do usunięcia.**

### Migracje
- [x] `h3c4d5e67890` — phase 8 `initial_load_windows`. Idempotent, head-revision check w `tests/test_db_migration.py` zaktualizowany.

### Testy
- [x] `tests/test_security_controls.py` — `TestAuthTokenAutoGeneration`: `test_auto_gen_sets_marker`, `test_user_token_no_marker`.
- [x] `tests/test_initial_load_manager.py` — `TestInitialLoadWindowLog`: success+failed roundtrip, error_message truncation.
- [x] `tests/test_invoice_monitor.py::test_exceeds_range` zaktualizowany (90 → 89 dni inclusive).
- Suite: **743 passed, 2 skipped** (był 739).

---

## v0.6 (Lightweight Polling)
**Cel:** rozdzielenie detekcji nowych faktur od pobierania artefaktów — oszczędność API calls, szybsze push notifications

### Analiza limitów API
- `POST /invoices/query/metadata`: **hour=20** (nie 120 jak dotąd zakładano — per endpoint, nie globalnie)
- Minimum bezpieczny polling interval: **4 min** (1 subject) / **7 min** (oba subjects)
- Poll co 60s = niemożliwe (3× przekroczony limit hour=20)

### 1) Dwufazowy cykl monitoringu
- [x] Faza 1: detekcja na metadanych + push z metadanych (bazowo już tak działało) — w trybie lazy artefakty NIE są pobierane inline *(pageSize bez zmian — `get_invoices_metadata` paginuje pełne metadane)*
- [x] Faza 2: artefakty — osobna faza `process_pending_artifacts()` (rate limiter globalny); flaga **opt-in** `monitoring.lazy_artifacts` (default: inline, bez zmiany zachowania)
- [x] Konfiguracja interwału pollingu per subject type w `config.json` — `monitoring.subject_poll_intervals` (sekundy/subject); `_subject_due` pomija subject jeśli interwał nie minął; testy `TestInvoiceMonitorSubjectIntervals` (5)
- [x] Update `invoice_monitor.py` — oddzielenie detekcji od artifact download (`_enqueue_artifacts` / `process_pending_artifacts` / `_check_and_drain`); testy `tests/test_invoice_monitor.py::TestInvoiceMonitorLazyArtifacts` (9)

### 2) Push notification z metadata (bez XML)
- [x] Treść push budowana z pól `InvoiceMetadata` — realizowane przez `build_template_context` (push nigdy nie wymagał XML)
- [x] XML pobierany lazy (gdy `lazy_artifacts=true`) — pobieranie przeniesione do Fazy 2 (Docker); w iOS XML i tak fetch-owany na żądanie
- [x] `ios_push.json.j2` zweryfikowany — używa wyłącznie pól metadanych (nazwy/NIP, kwoty, daty, `ksef_number`, `invoice_number`); `schema_type` z `_detect_schema_type_from_metadata` (pole `type`/`schemaType` z metadanych, bez parsowania XML). Bez zmian w kodzie.

### 3) Dokumentacja
- [x] Analiza limitów per endpoint (z OpenAPI spec `x-rate-limits`) — [KSEF_API_LIMITATIONS.md](KSEF_API_LIMITATIONS.md)
- [x] Design lekkiego pollingu — [LIGHTWEIGHT_POLLING_DESIGN.md](LIGHTWEIGHT_POLLING_DESIGN.md)

### 4) Pobieranie UPO (Urzędowe Poświadczenie Odbioru)
**Cel:** wykorzystanie nowego tokenu z uprawnieniem `Introspection` do pobierania UPO faktur sprzedażowych — wartość prawna potwierdzenia wystawienia.

**Status:** ścieżka API zweryfikowana skryptem `examples/test_upo_download.py` (env=test, 2026-04-29) — auth + listing sesji + UPO faktury + UPO sesji, SHA256 OK, schema `http://upo.schematy.mf.gov.pl/KSeF/v4-3`.

- [x] Rozszerzenie `app/ksef_client.py`:
  - `list_sessions(session_type, page_size, date_from, date_to)` → `GET /v2/sessions`
  - `get_session_invoices(reference)` → `GET /v2/sessions/{ref}/invoices` (`upoDownloadUrl` SAS direct)
  - `get_invoice_upo(sessionRef, ksefNumber)` → `GET /v2/sessions/{ref}/invoices/ksef/{ksefNumber}/upo`
  - Weryfikacja `x-ms-meta-hash` (SHA256 base64) — `_verify_sha256`, odrzut przy mismatch
- [x] Integracja z `invoice_monitor.py` (`process_pending_upo`, osobna faza po detekcji):
  - Dla faktur Subject1 (sprzedażowe) — odnajdź sesję i pobierz UPO XML
  - Mapa ksefNumber → sessionRef: cache `list_sessions` + `get_session_invoices`, TTL 24h
  - Bounded retry przy 21178 / brak sesji — artefakt `upo` z licznikiem prób (<3)
- [x] Storage:
  - `has_upo`/`upo_path` w `invoices` aktywowane
  - Zapis pliku: `{output_dir}/upo/{ksefNumber}.xml` (guard path traversal)
  - `artifact_type='upo'` w `invoice_artifacts`
- [x] Web UI:
  - Przycisk "Pobierz UPO" na `invoice_detail.html` (gdy `has_upo=True`)
  - Endpoint `GET /api/v1/invoices/{ksefNumber}/upo` (serwuje z cache; 404 gdy brak)
- [x] Konfiguracja: flaga `monitoring.fetch_upo` (default: false — opt-in, dodatkowy rate budget)
- [x] Token wymaga uprawnienia `Introspection` — udokumentowane w `config.example.json` (opis `fetch_upo`) i tutaj *(KSEF_TOKEN.md nie aktualizowany osobno)*
- [x] Testy: mock `/sessions` + `/upo`, SHA256 mismatch, brak sesji, bounded retry (21178), endpoint UI — `test_ksef_client.py::TestKSeFClientUPO` (10) + `test_invoice_monitor.py::TestInvoiceMonitorUPO` (9) + `test_api_invoices.py::TestUpoEndpoint` (4)
- [ ] **Weryfikacja end-to-end** przeciw realnemu KSeF — wymaga tokenu z uprawnieniem Introspection (dotąd tylko testy mock)

### 5) Adaptacja KSeF API v2.5.0
**Cel:** forward-compat z rotacją kluczy publicznych KSeF; zaktualizowane spec'i dla wszystkich środowisk.

**Harmonogram wdrożenia (z [api-changelog.md](https://github.com/CIRFMF/ksef-docs/blob/main/api-changelog.md)):**
- TEST: 06.05.2026 ✅ (spec zaktualizowany — `spec/openapi-test.json` SHA `ea05626e…`)
- DEMO: 07.05.2026 — pending (issue auto-otworzy się przy zmianie hash)
- PRD: 11.05.2026 — pending (issue auto-otworzy się przy zmianie hash)

**Smoke test (2026-05-07, env=test):** auth flow 6/6 OK przeciw `api-test.ksef.mf.gov.pl` — backward compat potwierdzony, klient działa **bez** wysyłania `publicKeyId`.

- [x] `spec/openapi-test.json` → **2.6.1** (TEST, build `20260610.2`, sync `d6d05e1`) — KSeF wyszedł poza 2.5.0
- [x] `spec/openapi-demo.json` → **2.6.1** (DEMO, build `20260615.1`, sync `f1c1ca7`)
- [x] `spec/openapi.json` → **2.6.1** (PRD, build `20260616.3`, sync `f1c1ca7`)
- [x] **Forward-compat dla rotacji kluczy** (przed PRD):
  - `KSeFClient._fetch_public_key` — zachowuje `cert["publicKeyId"]` w `self._ksef_public_key_id`
  - `KSeFClient._authenticate_with_token` — wysyła `publicKeyId` w body `POST /auth/ksef-token` gdy znany (nullable, omijany dla środowisk pre-2.5 bez rotacji); testy w `tests/test_ksef_client.py::TestKSeFClientPublicKeyId`
- [ ] Limity TEST API zrównane z PRD (ten sam profil) — zweryfikować że `_request_with_retry` + 429 backoff radzi sobie pod nowym budżetem; rozważyć wyrównanie defaultowego `check_interval` jeśli polling poprzednio bazował na luźniejszych limitach test
- [ ] (Opcjonalnie) Endpointy `/testdata/rate-limits` — wrapper do testów integracyjnych pod customowy profil limitów
- [x] Wsparcie `X-Error-Format: problem-details` dla 400/429 — nagłówek wysyłany w `session.headers` (`_extract_api_error_details` parsuje `problem+json`); spójny `application/problem+json` wszędzie
- [x] Test `tests/test_ksef_client.py` — snapshot `PublicKeyCertificate` schema v2.5.0 (`certificateId` + `publicKeyId`, wybór cert `KsefTokenEncryption` spośród wielu usage) — `test_fetch_public_key_snapshot_v25_schema`

### 6) Pełne pokrycie schematów faktur + FA_RR rewrite ✅
**Cel:** audyt pokrycia pól FA(3) względem opublikowanego XSD, przepisanie FA_RR wg realnego schematu, realne pliki XSD zamiast stubów. _Pełna lista zmian: `CHANGELOG.md` [0.6.0]._

**Schematy (`spec/`):**
| Schema | Wersja | Namespace | Status |
|---|---|---|---|
| FA(3) | v1-0E | `…/2025/06/25/13775/` | aktualny (sha `b646b6b…`), bez zmian |
| FA(2) | v1-0E | `…/2023/06/29/12648/` | stub → realny XSD |
| FA_RR(1) | v1-1E | `…/2026/03/06/14189/` | stub → realny XSD; stary `FA_RR_v1-0E` usunięty |

- [x] **FA_RR rewrite** — stary parser niefunkcjonalny: zarejestrowane namespace'y (`…/12978/`, `…/13836/`) nie istnieją na CRD, a wszystkie pola RR (`KwotaVatRR`, `P_15RR`, `OswiadczenieDostawcy`…) były zmyślone. `FA_RRInvoiceXMLParser` przepisany wg realnej struktury: `FakturaRR` / `FakturaRRWiersz`, pola `P_4A-C`/`P_5`/`P_6A-C`/`P_7-11`/`P_11_1/2`/`P_12_1/2`, `DokumentZaplaty`, `NrKontrahenta`, korekty (`Podmiot1K/2K`, `NrFaKorygowany`, `NrKSeF/N`). Role: Podmiot1 = nabywca (skupujący), Podmiot2 = rolnik. Template `invoice_pdf_fa_rr.html.j2` przepisany.
- [x] **FA(3) — rozszerzone pokrycie** (55 dotąd pomijanych elementów; render w jinja + ReportLab fallback):
  - korekty: `Podmiot1K`/`Podmiot2K`, `NrFaKorygowany`, `OkresFaKorygowanej`, `NrKSeF`/`NrKSeFN`
  - znaczniki: `GV`, `JST`, `StatusInfoPodatnika`, `SystemInfo`, `BrakID`, `IDWew`, `IDNabywcy`, `AdresKoresp`
  - `PodmiotUpowazniony` (+`RolaPU`/`EmailPU`/`TelefonPU`)
  - płatność: `IPKSeF`, `LinkDoPlatnosci`, `RachunekWlasnyBanku`; `WZ`, `ZwrotAkcyzy`
  - transport: `WysylkaZ`/`Przez`/`Do`, `AdresPrzewoznika`
  - negacje: `P_19N`, `P_PMarzyN`, `P_22N`; pełne pola pojazdów `P_22B2-4`/`P_22BT`/`P_22C1`/`P_22D1`/`P_NrWierszaNST`
  - `ZamowienieWiersz` warianty Z (`UU_IDZ`, `P_12Z_XII`, `GTINZ`…), `Zalacznik/Tabela`
  - render gap: flagi `FP`/`TP` dodane do szablonu
- [x] **Drift detection** — `check_ksef_fa_schema.yml` matryca rozszerzona o FA(2) v1-0E i FA_RR(1) v1-1E (CRD + CIRFMF); skan nowych wersji obejmuje `faktury/schemy/FA` + `faktury/schemy/RR`
- [x] Testy — `test_multi_schema_parser.py`: FA_RR przepisane na realny schemat + `TestFA3ExtendedFields` (61 passed)

### 7) Logowanie przez certyfikat (XAdES)
**Cel:** alternatywna metoda uwierzytelniania KSeF — podpis dokumentu `AuthTokenRequest` certyfikatem (kwalifikowany podpis/pieczęć lub certyfikat KSeF) zamiast tokenu KSeF. Endpoint `POST /auth/xades-signature` (zwraca 202).

**Flow API (openapi v2 + [uwierzytelnianie.md](https://github.com/CIRFMF/ksef-api/blob/main/uwierzytelnianie.md)):**
1. `POST /auth/challenge` → `challenge` + `timestamp`
2. Budowa `AuthTokenRequest` XML (schemat `auth v2-0`/`v2-1`) z `challenge`, `contextIdentifier` (Nip), typem podmiotu
3. Podpis XAdES (enveloped) kluczem prywatnym certyfikatu
4. `POST /auth/xades-signature` (`application/xml`) → 202 → `referenceNumber` + `authenticationToken`
5. `GET /auth/{referenceNumber}` polling — jak w token flow; `authenticationMethodInfo.category = "XadesSignature"`
6. `POST /auth/token/redeem` → access/refresh token (reużycie istniejącego kodu)

- [x] `app/ksef_client.py`: `_authenticate_certificate_flow()` + `_authenticate_with_xades()` — dispatch w `authenticate()` wg `auth_method`; wspólny challenge/poll/redeem, nowy krok podpisu
- [x] Budowa + podpis `AuthTokenRequest` (XAdES-BES enveloped, RSA-SHA256) — `app/xades_signer.py`, biblioteka **signxml** (bez systemowych zależności; pull `lxml`)
- [x] Ładowanie certyfikatu: `.p12`/`.pfx` (PKCS#12) z hasłem — ścieżka w configu, hasło przez `KSEF_CERT_PASSWORD` (`SecretsManager`/Docker secret)
- [x] Konfiguracja: `ksef.auth_method = "token" | "certificate"` + `ksef.certificate.{path, password, subject_identifier_type}`; walidacja w `config_manager` (token vs certyfikat)
- [x] Walidacja certyfikatu przed próbą auth — `_validate_certificate` w `load_pkcs12`: blokuje wygasły / jeszcze nieważny certyfikat; dopasowanie NIP do subject best-effort (ostrzeżenie). Testy `TestCertificateValidity` (5)
- [x] Web UI: upload `.p12`/`.pfx` na stronie `/ui/certificate` (auth-required) — walidacja PKCS#12 hasłem (hasło niezapisywane) + atomowy zapis 0600 do `ksef.certificate.path`; status pliku. *(Przełączenie `auth_method` nadal w `config.json`.)*
- [x] Testy: mock `/auth/xades-signature`, weryfikacja struktury podpisanego XML (XAdES-BES, rsa-sha256, enveloped), błędne hasło, brak pliku, dispatch — `tests/test_certificate_auth.py` (25 testów)
- [x] Dokumentacja: [KSEF_CERTIFICATE_AUTH.md](KSEF_CERTIFICATE_AUTH.md)
- [ ] **Weryfikacja end-to-end** przeciw realnemu KSeF — wymaga prawdziwego certyfikatu (dziś tylko testy mock)

> *(Osobny temat, poza tym wpisem)* Zarządzanie certyfikatami KSeF: `/certificates/enrollments`, `/certificates/query`, `/certificates/retrieve`, `/certificates/{serial}/revoke` — wydawanie i rotacja certyfikatów KSeF.

**Zależności:** v0.5
**DoD:** monitor wykrywa nowe faktury i wysyła push w jednym tanim API call; artefakty pobierane niezależnie; konfigurowalny interwał pollingu; UPO faktur sprzedażowych pobierane i zapisywane gdy `fetch_upo=true`; klient wysyła `publicKeyId` w `/auth/ksef-token` przed PRD 11.05.2026; logowanie certyfikatem XAdES przez `POST /auth/xades-signature` jako alternatywa dla tokenu; specy demo i prod zaktualizowane; testy aktualne.

**Status (2026-06-28):** wszystkie elementy zaimplementowane i pokryte testami (suite 837). Pozostaje **weryfikacja end-to-end na żywym KSeF**: logowanie certyfikatem (§7) i UPO (§4) — wymaga realnego certyfikatu / tokenu z uprawnieniem `Introspection`; oraz operacyjne potwierdzenie limitów TEST=PRD (§5). Opcjonalny wrapper `/testdata/rate-limits` pominięty (wartość tylko przy testach integracyjnych na żywym env).

---

## v0.7 (Auto-update)
**Cel:** wbudowany mechanizm aktualizacji bez potrzeby aktualizowania całego obrazu Docker

- Automatyczny update aplikacji bez przebudowy obrazu Docker

### Zmiany API / schema
- Mechanizm auto-update musi uwzględniać zmiany w schemacie DB (Alembic migracje przy update)
- Walidacja kompatybilności nowej wersji z aktualnym schematem FA i API KSeF

**Zależności:** v0.5

---

## v1.0 (Web UI: konfiguracja / panel admin)
**Cel:** samodzielna konfiguracja bez grzebania w plikach

**Panel konfiguracji:**
- konfiguracja schedulera (częstotliwość, okna czasowe, tryb "catch-up")
- konfiguracja notifiera (kanały, template, routing per subject/NIP)
- konfiguracja Prometheusa (enable/disable, port, ścieżka, metryki)
- konfiguracja MQ (połączenie, retry policy, DLQ jeśli używacie)
- konfiguracja nazw plików (pattern, prefix)
- konfiguracja folderów (folder_structure, output_dir)

### Zmiany API / schema
- UI do podglądu aktualnie używanej wersji API KSeF i schematu FA
- Powiadomienie w panelu admin o wykrytych zmianach w specyfikacji (z CI workflow)

**Zależności:** v0.5
**DoD:** wszystko da się skonfigurować z UI, a zmiany wchodzą w życie bez ręcznych edycji configów (lub z kontrolowanym restartem usługi).

---

## v2.0 (Multi-NIP)
**Cel:** obsługa wielu NIP-ów w jednym wdrożeniu

- model tenantów: NIP jako tenant + separacja danych (DB, konfiguracja, uprawnienia)
- UI: przełącznik NIP / lista NIP-ów / role
- scheduler: osobne harmonogramy per NIP (lub wspólny z kolejką)
- notifier: routing per NIP
- monitoring: metryki per NIP

### Zmiany API / schema
- Rozszerzenie modelu DB o tenant_id (NIP) — migracja Alembic
- Ewentualne nowe endpointy KSeF API per NIP (jeśli API wprowadzi multi-subject w jednej sesji)

**Zależności:** v1.0
**DoD:** można dodać drugi NIP i wszystko (import, lista, powiadomienia, metryki) działa niezależnie.

---

## Do rozważenia
- GUI do pobierania faktur przed v0.5?
  - Prosty interfejs webowy (Flask/FastAPI) do ręcznego pobrania faktury po numerze KSeF
  - Pobranie XML + generacja PDF on-demand z podglądem w przeglądarce
  - Bez pełnego dashboardu — tylko formularz „podaj numer KSeF → pobierz PDF"
- Wystawienie endpointu dla Message Queue (MQ)
  - Publikacja eventów o nowych fakturach do kolejki (RabbitMQ / Redis Streams / NATS)
  - Event payload: metadane faktury (ksef_number, NIP, kwota, data, subject_type)
  - Umożliwienie integracji z zewnętrznymi systemami (ERP, księgowość, automatyzacja)
  - Konfiguracja w `config.json`: typ brokera, connection string, nazwa kolejki/topicu
  - Retry + DLQ (Dead Letter Queue) dla nieudanych publishów
- API na Cloudflare do generowania faktur PDF dla iOS, gdzie można używać własnego template
  - Cloudflare Worker jako REST API: POST XML faktury → odpowiedź PDF (binary)
  - Wbudowany domyślny template HTML/CSS (analogiczny do `invoice_pdf.html.j2`)
  - Możliwość przesłania własnego template w requeście (lub przechowywanie w KV/R2)
  - Parser FA(3) XML → kontekst Jinja2 → render HTML → PDF (via Puppeteer/wasm lub zewnętrzny renderer)
  - Autentykacja: API key lub shared secret w nagłówku `Authorization`
  - Użycie przez aplikację iOS Monitor KSeF: pobranie XML z KSeF → wysłanie do Worker → wyświetlenie PDF
  - Opcjonalnie: cache wygenerowanych PDF w R2 (klucz: hash XML + template)
- ~~Moduł sprawdzania `schemat_FA` — czy istnieje nowa wersja XSD i czy wpływa na aplikację~~ → zrobione (CI workflow, CRD + GitHub, FA(2)/FA(3) + Pushover)
- ~~Moduł sprawdzania `openapi.json` czy jest nowy~~ → zrobione (CI workflow, 3 środowiska + Pushover)

---

## Kluczowe zależności (krótko)
- **DB (v0.3)** jest krytyczne przed sensownym UI (v0.5)
- **API + stabilizacja (v0.4)** minimalizuje "dług" zanim dojdzie UI
- **Initial load (v0.5)** najlepiej robić dopiero gdy masz deduplikację/idempotencję (v0.4)
