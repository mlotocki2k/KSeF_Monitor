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
- Aplikacja iOS: Monitor KSeF (w trakcie review w App Store)
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
- [x] Parser FA_RR(1) — `FA_RRInvoiceXMLParser` (rolnik PESEL, KwotaVatRR, oświadczenie)
- [x] Template PDF per schemat — `invoice_pdf_fa_rr.html.j2` dla FA_RR, PEF → ReportLab minimal
- [x] Fallback: nieznany schemat → zapis XML bez PDF + warning w logu i powiadomieniu
- [x] Specyfikacje XSD stubs: `spec/schemat_FA(2)_v1-0E.xsd`, `spec/schemat_FA_RR_v1-0E.xsd`
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

## v0.6 (Lightweight Polling)
**Cel:** rozdzielenie detekcji nowych faktur od pobierania artefaktów — oszczędność API calls, szybsze push notifications

### Analiza limitów API
- `POST /invoices/query/metadata`: **hour=20** (nie 120 jak dotąd zakładano — per endpoint, nie globalnie)
- Minimum bezpieczny polling interval: **4 min** (1 subject) / **7 min** (oba subjects)
- Poll co 60s = niemożliwe (3× przekroczony limit hour=20)

### 1) Dwufazowy cykl monitoringu
- [ ] Faza 1: detekcja — `pageSize=10`, tylko metadane, bez XML (1-2 API calls per cykl)
- [ ] Faza 2: artefakty — lazy/background, osobny rate budget (`GET /invoices/ksef/{ksefNumber}` hour=64)
- [ ] Konfiguracja interwału pollingu per subject type w `config.json`
- [ ] Update `invoice_monitor.py` — oddzielenie detekcji od artifact download

### 2) Push notification z metadata (bez XML)
- [ ] Treść push budowana z pól `InvoiceMetadata` (seller, buyer, kwoty, typ, daty)
- [ ] XML pobierany lazy dopiero gdy user otwiera fakturę w app
- [ ] Update `ios_push.json.j2` — template oparty wyłącznie o metadata

### 3) Dokumentacja
- [x] Analiza limitów per endpoint (z OpenAPI spec `x-rate-limits`) — [KSEF_API_LIMITATIONS.md](KSEF_API_LIMITATIONS.md)
- [x] Design lekkiego pollingu — [LIGHTWEIGHT_POLLING_DESIGN.md](LIGHTWEIGHT_POLLING_DESIGN.md)

**Zależności:** v0.5
**DoD:** monitor wykrywa nowe faktury i wysyła push w jednym tanim API call; artefakty pobierane niezależnie; konfigurowalny interwał pollingu; testy aktualne.

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
