# Roadmap

## v0.2 ✅ (zrobione)
**Cel:** podstawowa obserwowalność + dostęp do PDF

- [x] Endpoint pod Prometheusa
- [x] Pobieranie obrazu/PDF wybranej faktury

**DoD:** metryki widoczne w Prometheusie, PDF/obraz faktury do pobrania dla wskazanego dokumentu.

---

## v0.3 (Fundament: templating + DB) — w trakcie
**Cel:** ustandaryzować komunikację i zacząć trwale trzymać dane o fakturach

### 1) Powiadomienia oparte o template
- [ ] System szablonów Jinja2 z osobnym szablonem per kanał (5 szablonów)
- [ ] `TemplateRenderer` z custom filtrami (`money`, `money_raw`, `date`, `json_escape`)
- [ ] Możliwość podmiany szablonów przez użytkownika (`templates_dir` w config)
- [ ] Fallback na wbudowane domyślne szablony + plain text przy błędach
- [ ] Polskie formatowanie kwot (`,` separator dziesiętny, spacja tysięcy, kod waluty)
- [ ] Dokumentacja: [TEMPLATES.md](TEMPLATES.md) — zmienne, filtry, przykłady modyfikacji

### 2) Template generowania obrazu faktury
- [ ] HTML/CSS template (Jinja2) → render do PDF przez xhtml2pdf
- [ ] `InvoicePDFTemplateRenderer` z custom filtrami (`fmt_amt`, `vat_label`, `payment_method`)
- [ ] Możliwość podmiany szablonu przez użytkownika (`pdf_templates_dir` w config storage)
- [ ] Automatyczny fallback na ReportLab generator przy błędach lub braku xhtml2pdf
- [ ] Dynamiczne kolumny tabeli pozycji (warunkowe wyświetlanie)
- [ ] QR Code Type I jako base64 data URI w HTML
- [ ] Dokumentacja: [PDF_TEMPLATES.md](PDF_TEMPLATES.md) — zmienne, filtry, CSS customizacja

### 3) Formatowanie/zapisywanie (struktura folderów)
- [ ] Konfigurowalna struktura folderów (`folder_structure` w config storage)
- [ ] Placeholdery: `{year}`, `{month}`, `{day}`, `{type}` (sprzedaz/zakup)
- [ ] Walidacja wzorca w config_manager (tylko dozwolone placeholdery)
- [ ] Path traversal guard na wynikowej ścieżce
- [ ] Backward compatible: pusty string = flat directory (zachowanie domyślne)

### 4) Safecheck na overwrite plików
- [ ] Sprawdzanie czy plik (XML/PDF/UPO) już istnieje przed zapisem
- [ ] Strategia: skip / rename / overwrite (konfiguracja)

### 5) Przeniesienie informacji o fakturach do bazy
- model danych rozdzielony "per subject, per NIP"
- indeksy pod najczęstsze zapytania (np. subject + nip + timestamp)
- migracja: zapis przy pobraniu/detekcji faktury

**Zależności:** v0.2
**DoD:** powiadomienia i obraz faktury generują się wyłącznie z template; faktury lądują w DB i da się je filtrować per subject/NIP.

---

## Infrastruktura i jakość (częściowo zrobione)
Poprawki niezwiązane z konkretnymi feature'ami, ale krytyczne dla stabilności:

### Bezpieczeństwo
- [ ] Re-audit: Docker hardening (M7, L1, N1-N5)
- [ ] SHA-256 deduplication (zamiast MD5) w `seen_invoices`
- [ ] Atomic state write (`last_check.json` — tmp + rename + fsync)
- [ ] Path traversal guards w `_resolve_output_dir()` i `_save_invoice_artifacts()`
- [ ] Input sanitization (`_sanitize_field()`) w template context

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

### Docker i CI
- [ ] Entrypoint z dynamicznym ownership (`gosu`)
- [ ] Named volume + config mount separation (`/config` vs `/data`)
- [x] 429 retry z backoff + parsowanie `Retry-After` (HTTP-date i sekundy)
- [x] KSeF number validation regex
- [x] CI: build & push Docker image (test + main)
- [x] CI: automatyczne sprawdzanie outdated Python packages → issue + PR
- [x] CI: sprawdzanie zmian OpenAPI spec KSeF (3 środowiska: test, demo, production) z Pushover notification
- [ ] Deprecated `datetime.utcnow()` → `datetime.now(timezone.utc)`
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

## v0.4 (Stabilizacja + API pod UI) — propozycja
**Cel:** przygotować solidne backend API i jakość pod web UI + initial load

- Warstwa API dla UI
  - endpointy: statystyki / lista / szczegóły / podgląd
  - paginacja, sortowanie, filtrowanie (subject, nip, role: sprzedawca/kupujący, daty)
- Idempotencja i deduplikacja
  - klucz unikalny faktury, retry-safe zapisy
- Obsługa błędów i retry
  - polityka retry dla KSeF, timeouts, backoff
- Metryki + logi "operacyjne"
  - liczba nowych faktur/okno czasowe, błędy API, czasy odpowiedzi
- Testy i CI
  - testy jednostkowe logiki DB + templating
  - testy integracyjne (mock KSeF / sandbox)
- Szkielet uprawnień
  - podstawowe auth (np. token) dla web UI/admin

**Zależności:** v0.3
**DoD:** UI może bazować na stabilnym API; system jest odporny na retry i ma podstawową telemetrię operacyjną.

---

## v0.5 (Initial load + Web UI: odczyt)
**Cel:** pierwszy sensowny produkt dla użytkownika: dane + podgląd

### 1) Initial load (dane historyczne)
- od `2026-02-01` albo data definiowana w config (`initial_load.start_date`)
- tryb: jednorazowy import + zapis do DB + raport (ile pobrano, ile pominięto)
- **Moving window** — obejście limitu 90 dni (3 miesiące) API KSeF:
  - automatyczne dzielenie zakresu dat na okna ≤90 dni
  - sekwencyjne pobieranie okno po oknie z paginacją w każdym
  - progress tracking: zapis postępu (ostatnie zakończone okno) → resume po przerwaniu
  - rate limiting / backoff między oknami (unikanie throttlingu API)

### 2) Interfejs webowy (odczyt)
- pokazywanie ile nowych faktur od ostatniego sprawdzenia: **per subject, per NIP**
- pokazywanie ile ogólnie faktur: **per subject, per NIP** (sprzedawcy i kupującego)
- lista wszystkich faktur (z bazy): filtry/sort/paginacja
- podgląd wybranej faktury: pobranie po API z KSeF konkretnej faktury (z cache, jeśli już jest)
- możliwość zaznaczenia jednej lub wielu faktur do wygenerowania PDF
- integracja z oficjalną biblioteką CIRFMF do wizualizacji PDF ([ksef-pdf-generator](https://github.com/CIRFMF/ksef-pdf-generator)) jako opcjonalny mikroserwis Docker (REST API: XML → PDF), obok wbudowanego generatora (xhtml2pdf/ReportLab)

**Zależności:** v0.4
**DoD:** użytkownik widzi dashboard + listę + podgląd; initial load działa powtarzalnie bez duplikatów.

---

## v0.7 (Auto-update)
**Cel:** wbudowany mechanizm aktualizacji bez potrzeby aktualizowania całego obrazu Docker

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

**Zależności:** v1.0
**DoD:** można dodać drugi NIP i wszystko (import, lista, powiadomienia, metryki) działa niezależnie.

---

## Do rozważenia
- GUI do pobierania faktur przed v0.5?
- Wystawienie endpointu dla Message Queue (MQ)
- ~~Moduł sprawdzania `schemat_FA` — czy istnieje nowa wersja XSD i czy wpływa na aplikację~~ → zrobione (CI workflow, CRD + GitHub, FA(2)/FA(3) + Pushover)
- ~~Moduł sprawdzania `openapi.json` czy jest nowy~~ → zrobione (CI workflow, 3 środowiska + Pushover)

---

## Kluczowe zależności (krótko)
- **DB (v0.3)** jest krytyczne przed sensownym UI (v0.5)
- **API + stabilizacja (v0.4)** minimalizuje "dług" zanim dojdzie UI
- **Initial load (v0.5)** najlepiej robić dopiero gdy masz deduplikację/idempotencję (v0.4)
