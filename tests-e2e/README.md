# AI Tester — Monitor KSeF

Automatyczny tester GUI symulujący prawdziwego użytkownika. Headless Chromium przez Playwright.

## Pokrycie

| Plik | Co testuje | Marker |
|---|---|---|
| `test_01_smoke.py` | Health, redirects, static assets, login renders | `smoke`, `public` |
| `test_02_login.py` | Walidacja, błędne credentials, XSS, SQLi, rate limit | `public`, `security`, `destructive` |
| `test_03_auth_flow.py` | Login → dashboard → nawigacja → logout | `auth` |
| `test_04_invoices.py` | Lista faktur — filtry, sort, paginacja, search, API | `auth` |
| `test_05_invoice_detail.py` | Detail page, PDF, XML, path traversal | `auth`, `security` |
| `test_06_account.py` | Account page + zmiana hasła (destructive) | `auth`, `destructive` |
| `test_07_security.py` | Headers, error pages, sensitive files exposure | `security`, `public` |
| `test_08_ai_explorer.py` | **AI crawl** — odwiedza wszystkie linki, wykrywa 4xx/5xx, console errors | `explorer` |
| `test_09_accessibility.py` | axe-core scan (WCAG 2 A/AA) | `a11y` |
| `test_10_responsive.py` | Mobile/tablet/desktop viewports + screenshoty | `responsive` |

## Setup

```bash
cd tests-e2e
./setup.sh
```

Co robi:
1. Tworzy `.venv` (Python 3.10+)
2. Instaluje deps (Playwright, pytest, axe-core)
3. Pobiera Chromium (~150 MB)
4. Tworzy `.env` z `.env.example`

Następnie **uzupełnij `.env`**:

```bash
KSEF_BASE_URL=http://test.krzewiny.net:8888
KSEF_TEST_USER=twoj_test_user        # WYMAGANE dla testów auth
KSEF_TEST_PASS=twoje_test_haslo      # WYMAGANE dla testów auth
KSEF_HEADED=false                     # true = widzialna przegladarka
```

> **Bez credentials** — uruchomi się tylko `public` + `smoke` + `security` (wszystkie auth-required są auto-skipped).

## Uruchomienie

```bash
./run.sh                  # full (bez destructive)
./run.sh smoke            # tylko smoke (szybkie, ~10s)
./run.sh public           # bez auth
./run.sh auth             # tylko zalogowane
./run.sh security         # security audit
./run.sh a11y             # accessibility
./run.sh explorer         # AI crawl
./run.sh all              # WSZYSTKO + destructive (zmieni hasło!)
```

Lub bezpośrednio pytestem:

```bash
source .venv/bin/activate
pytest -m smoke -v                    # smoke
pytest -m "auth and not destructive"  # auth bez password change
pytest tests/test_01_smoke.py -v      # konkretny plik
pytest -k "test_login_page_renders"   # konkretny test
KSEF_HEADED=true pytest -m smoke      # widzialna przeglądarka
KSEF_SLOWMO=500 pytest                # spowolnij akcje
```

## Wyniki

Po uruchomieniu:

```
reports/
├── report.html                  # pytest HTML report (per-test)
├── ai_tester_report.html        # KONSOLIDOWANY dashboard
├── explorer_authed.json         # crawl zalogowany
├── explorer_public.json         # crawl publiczny
├── a11y_login.json              # axe violations dla loginu
├── a11y_dashboard.json
└── ...
screenshots/
├── login_mobile_iphone_se.png
├── login_desktop_full_hd.png
├── dashboard_mobile.png
└── FAIL_*.png                   # screenshoty z failed testów
```

**Otwórz dashboard:**
```bash
open reports/ai_tester_report.html
```

## Markery pytest

```bash
pytest -m smoke              # 1. szybkie sanity check
pytest -m public             # 2. bez logowania
pytest -m auth               # 3. wymagają sesji
pytest -m security           # 4. XSS, headers, headers fingerprinting
pytest -m a11y               # 5. accessibility (WCAG)
pytest -m responsive         # 6. mobile/tablet/desktop
pytest -m explorer           # 7. AI crawl całej app
pytest -m destructive        # 8. zmieniają stan (rate limit, password)
pytest -m slow               # 9. >5s każdy
```

Kombinacje: `pytest -m "auth and not destructive"`, `pytest -m "smoke or public"`.

## Tryb interaktywny (debug)

```bash
KSEF_HEADED=true KSEF_SLOWMO=1000 pytest -m smoke -v -s
```

- `KSEF_HEADED=true` — widzisz Chrome
- `KSEF_SLOWMO=1000` — każda akcja spowolniona o 1s
- `-s` — pokazuje print() w czasie rzeczywistym

## CI / Gitea Actions

Przykładowy workflow (do dodania w `.github/workflows/e2e.yml`):

```yaml
name: e2e
on: [pull_request]
jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: cd tests-e2e && ./setup.sh
      - run: cd tests-e2e && ./run.sh smoke
        env:
          KSEF_BASE_URL: ${{ secrets.KSEF_TEST_URL }}
          KSEF_TEST_USER: ${{ secrets.KSEF_TEST_USER }}
          KSEF_TEST_PASS: ${{ secrets.KSEF_TEST_PASS }}
      - uses: actions/upload-artifact@v4
        with:
          name: e2e-reports
          path: tests-e2e/reports/
```

## Co tester wykrywa

✓ HTTP 4xx/5xx na dowolnej stronie
✓ JavaScript console errors / unhandled rejections
✓ Failed network requests (broken assets, dead APIs)
✓ Broken images
✓ XSS w formularzach (search, login)
✓ SQL injection w filterach
✓ Path traversal w URL params
✓ Brak security headers (XCTO, X-Frame, CSP)
✓ Wycieki konfiguracji (.env, config.json, .git)
✓ Stack tracebacks na 404/500
✓ Rate limit nie działa
✓ Sesja nie inwalidowana po logout
✓ Sesja nie inwalidowana po zmianie hasła
✓ Accessibility violations (axe WCAG 2 A/AA)
✓ Horizontal scroll na mobile
✓ Niewidoczne elementy w małych viewportach

## Rozszerzanie

Nowy test = nowy plik `tests/test_NN_*.py` lub klasa w istniejącym. Dostępne fixtures:

- `page` — czysta `Page` (bez auth)
- `authed_page` — `Page` z aktywną sesją (skip jeśli brak credentials)
- `authed_context` — `BrowserContext` z sesją (do API z cookies)
- `base_url` — np. `http://test.krzewiny.net:8888`
- `console_capture` — lista `{type, text, url}` z console
- `network_capture` — lista `{url, status, method}` failed
