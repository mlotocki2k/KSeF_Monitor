# Bugi wykryte przez AI Tester

Pełen run (smoke + public + auth + a11y + responsive + explorer): **84 passed, 7 failed**.

Po naprawach testów: **5 realnych bugów** w aplikacji do naprawienia.

---

## 🔴 Bug #1 — Mobile responsive: 554px horizontal scroll

**Severity:** High (UX broken na mobile)
**Strony dotknięte:** `/ui` (dashboard) + `/ui/invoices`
**Viewport:** 375×667 (iPhone SE)
**Pomiar:** `scrollWidth - clientWidth = 554px`

**Problem:** dashboard i lista faktur mają stały szeroki layout. Na mobile pojawia się ogromny horizontal scroll — strona nieużyteczna na telefonie.

**Prawdopodobna przyczyna:** tabela `<table>` z fakturami nie jest responsive (brak `overflow-x: auto` na kontenerze, brak responsywnego układu kolumn).

**Naprawa:**
```html
<!-- przed -->
<table class="invoices">...</table>

<!-- po -->
<div class="overflow-x-auto"><table class="invoices min-w-full">...</table></div>
```

Lub Tailwind: `<table class="hidden md:table">` + alternatywny `<div class="md:hidden">` z kart-list.

**Pliki:**
- [app/ui/templates/dashboard.html](monitor-ksef/ksef_monitor_v0_1/app/ui/templates/dashboard.html)
- [app/ui/templates/invoices.html](monitor-ksef/ksef_monitor_v0_1/app/ui/templates/invoices.html)
- prawdopodobnie też [base.html](monitor-ksef/ksef_monitor_v0_1/app/ui/templates/base.html) (top nav)

**Test:** `tests-e2e/tests/test_10_responsive.py::TestResponsiveAuthed::test_responsive_screenshots`
**Screenshoty:** `tests-e2e/screenshots/dashboard_mobile.png`, `invoices_mobile.png`

---

## 🔴 Bug #2 — A11y CRITICAL: filtry faktur bez accessible name

**Severity:** Critical (axe-core)
**Strona:** `/ui/invoices`
**WCAG:** 4.1.2 Name, Role, Value (Level A)

**Problem:** 6 form elementów na stronie filtrów nie ma żadnej etykiety dostępnej dla czytników ekranu:

| Element | Brakuje |
|---|---|
| `<input type="date" name="issue_date_from">` | label / aria-label |
| `<input type="date" name="issue_date_to">` | label / aria-label |
| `<input type="checkbox" id="chk-all">` | label / aria-label |
| `<select name="subject_type">` | label / aria-label |
| `<select name="sort_by">` | label / aria-label |
| `<select name="sort_order">` | label / aria-label |

**Naprawa — minimum:**
```html
<select name="subject_type" class="input" aria-label="Typ faktury">...</select>
<input type="date" name="issue_date_from" aria-label="Data wystawienia od" ...>
<input type="checkbox" id="chk-all" aria-label="Zaznacz wszystkie faktury">
```

**Plik:** [app/ui/templates/invoices.html](monitor-ksef/ksef_monitor_v0_1/app/ui/templates/invoices.html)

**Test:** `test_09_accessibility.py::TestAccessibilityAuthed::test_authed_page_a11y[/ui/invoices]`

---

## 🟠 Bug #3 — Color contrast WCAG AA fail (wszystkie strony)

**Severity:** Serious (axe-core)
**Strony dotknięte:** wszystkie 4 testowane (login, dashboard, invoices, account)
**WCAG:** 1.4.3 Contrast (Minimum) — Level AA

**Problemy:**

| Element | Foreground | Background | Ratio | Wymagane | Strony |
|---|---|---|---|---|---|
| Button "Zaloguj" / "Filtruj" / nav active | `#FFFFFF` | `#007AFF` | **4.01** | 4.5 | wszystkie |
| Linki z numerem faktury (np. "523043280426") | `#007AFF` | `#1A2B50` | **3.47** | 4.5 | invoices |

**Naprawa:**
```css
:root {
  --accent: #0066CC;       /* zamiast #007AFF -> 4.6:1 z bialym */
  --accent-link: #4DA3FF;  /* nowy - jasniejszy, tylko do linkow na ciemnym tle */
}

a.invoice-link { color: var(--accent-link); }
.btn-primary { background: var(--accent); }
```

Alternatywa: dać buttonom `font-weight: 600` (WCAG dopuszcza dla 14px+).

**Plik:** [app/ui/templates/base.html](monitor-ksef/ksef_monitor_v0_1/app/ui/templates/base.html) (CSS root variables) i specyficzne strony.

---

## 🟡 Bug #4 — Brak `<h1>` na stronach (page-has-heading-one)

**Severity:** Moderate (axe-core)
**Strony dotknięte:** dashboard, invoices

**Problem:** dokument nie ma żadnego `<h1>` — utrudnia nawigację screen-readerom.

**Naprawa:** dodać główny nagłówek strony:
```html
<!-- dashboard.html -->
<h1 class="sr-only">Dashboard Monitor KSeF</h1>
<!-- lub widoczny -->
<h1 class="text-2xl font-bold mb-4">Dashboard</h1>

<!-- invoices.html -->
<h1 class="text-2xl font-bold mb-4">Lista faktur</h1>
```

---

## 🟡 Bug #5 — Brak `<main>` landmark (login)

**Severity:** Moderate (axe-core)
**Strona:** `/ui/login`

**Problem:** content nie jest opakowany w `<main>` — screen readers nie mogą skoczyć do głównej zawartości.

**Naprawa:**
```html
<!-- login.html -->
<body class="h-full flex items-center justify-center">
  <main class="card p-8 w-full max-w-sm mx-4">
    ...
  </main>
</body>
```

---

## 🟡 Bug #6 (minor) — Pusta `<th>` w tabeli faktur

**Severity:** Minor (axe-core)
**Strona:** `/ui/invoices`

**Problem:** kolumna z checkboxem ma pusty `<th>`, co dezorientuje screen-reader.

**Naprawa:**
```html
<th class="th w-8">
  <span class="sr-only">Zaznaczanie</span>
  <input type="checkbox" id="chk-all" onchange="toggleAll(this)" aria-label="Zaznacz wszystkie">
</th>
```

---

## ✅ Co działa świetnie

- **Security headers** kompletne i poprawne (HSTS, CSP z `frame-ancestors 'none'`, XCTO, X-Frame, referrer-policy, permissions-policy)
- **Path traversal blokowane** — `/ui/invoices/..%2F...` wszystkie zwracają 404
- **Bad login** zwraca 303 z `?error=invalid` w query (sanitarnie)
- **Sesja HttpOnly** w `mksef_session` cookie
- **Healthcheck** czysty: `{"status":"ok","version":"0.5.1","db_connected":true}`
- **OpenAPI/docs** wyłączone (security best practice na test stand)
- **24 strony scrawlowane** (dashboard + 22 invoice details + push + initial-load + account) — 0 console errors, 0 broken images, 0 failed requests, 0 5xx

---

## Priorytet napraw

1. **Bug #1 (mobile responsive)** — krytyczne UX, połowa userów na mobile
2. **Bug #2 (a11y filtry)** — critical violation, blocker dla legal compliance jeśli aplikacja idzie do produkcji w UE (EAA 2025)
3. **Bug #3 (color contrast)** — łatwy fix, duży impact
4. **Bug #4-6 (landmarks, h1, th)** — minor/moderate, można razem z #2 w jednej iteracji a11y
