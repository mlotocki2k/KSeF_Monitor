# TODO — KSeF Monitor (Docker)

Stan na: 2026-09-25 — `main` = 0.5.6, `test` = 0.6.3, `feat/ksef-api-2.8-adaptation` = 0.6.4 (niescalona).
Sekcje 0.5.x poniżej zostają jako historia; scenariusze user-testu nadal obowiązują dla merge `test` → `main`.

Aplikacja Docker — uruchamiana jako kontener (`docker-compose` / `docker stack`).
Wszystkie instrukcje CLI poniżej zakładają kontekst kontenera (`docker exec -it ksef-monitor ...`).

---

## Pre-prod (branch `test`, 0.5.3)

Release `test` → `main` gating: **manualny user-test + iOS app v1.1.1 w App Store** (patrz `memory/project_release_gating.md`).

> **2026-09-25:** warunek iOS spełniony — App Store serwuje Monitor KSeF **1.2.2** (wydanie 2026-08-20;
> sprawdzone `itunes.apple.com/lookup?id=6759834557`). Blokerem pozostaje **manualny user-test** (lista niżej).

### 0.5.2 baseline (UI auth audit remediation)
- [x] V5-12 cookie session
- [x] V5-13 user accounts + DB sessions + bootstrap admin
- [x] V5-14 middleware split (session resolver niezależny od auth gate)
- [x] V5-15 dark theme spójny z iOS
- [x] V5-16 fix `POST /monitor/trigger`
- [x] V5-17 fix PDF footer version (hardcoded v0.3 → `app.__version__`)

### 0.5.3 hotfixy (post user-test 0.5.2)
- [x] **Fresh install lockout** — bootstrap admin skipped przy auto-gen `auth_token`. Wizard `/ui/setup` jedyny entry point dla fresh install.
- [x] **Initial load: każda faktura odrzucona** — `_map_export_invoice` zaktualizowany do v2.4 `InvoiceMetadata` schema.
- [x] **Initial load: KSeF 21405** — 90-day window off-by-one (91-day inclusive). Fix: 89-day span + cursor +1.
- [x] **U-12 audit log silently dropped** — `alembic.ini` root WARNING → INFO.
- [x] **GUI: progress 50% pod "Ukończony"** — bump `windows_completed` na failure path. Nowy status `completed_with_errors`.
- [x] **GUI: per-window history** — phase 8 migration `initial_load_windows`, endpoint, toggle table.
- [x] **GUI: logo↔menu spacing** — `ml-2 sm:ml-4` na `<nav>`.
- [x] **iOS App Store status** — amber notice w `/ui/push` + README (historyczne — dot. TestFlight). **Nieaktualne od v1.1.2 (2026-07-08): parowanie push w App Store; README zaktualizowany.** Amber notice usunięty — `app/ui/templates/push.html` zawiera już tylko link „Pobierz Monitor KSeF z App Store” (sprawdzone 2026-09-25).

### User testing scenariuszy
- [ ] Fresh install (czysty volume): `/ui/login` → 303 → `/ui/setup` wizard → username/pass → login → dashboard
- [ ] Upgrade z v0.5.0 z istniejącym `auth_token`: bootstrap `admin` = `auth_token`, login, zmiana hasła w `/ui/account`
- [ ] Przycisk "Sprawdź" w navbar → status 200, flash "Check scheduled"
- [ ] Bearer `Authorization: Bearer <token>` curl na `/api/v1/invoices` → działa
- [ ] iOS pairing flow (push pairing code z `/ui/push` → App Store v1.1.2+)
- [ ] Rate limity: `/ui/login` 5/min, `/ui/setup` 3/min
- [ ] Password change → revoke wszystkich sesji → wymuszone ponowne logowanie
- [ ] Visual QA dark theme: navbar, dashboard, lista faktur, push, setup, login
- [ ] **Initial load fresh**: dłuższy zakres (>90 dni) → wszystkie okna succeed, faktury w DB, "Ukończony" 100%
- [ ] **Initial load history view**: toggle "Pokaż historię okien" → tabelka per-window, statusy OK/FAIL, durations
- [ ] **Audit log INFO**: `docker logs ksef-monitor 2>&1 | grep "UI login session created"` po loginie → widoczne
- [ ] Merge `test` → `main` (po zielonym user-test; warunek iOS spełniony — patrz wyżej)
- [ ] Docker image tag `v0.6.x` po merge (dziś `main` = 0.5.6)

---

## Follow-ups po 0.5.3 (non-blocking)

### UI auth enhancements
- [ ] Multi-user admin panel w UI (add/delete other users) — obecnie CLI-only (`python -m app.user_admin`)
- [ ] Opcjonalny 2FA / TOTP dla `/ui/login`
- [ ] Lista aktywnych sesji w `/ui/account` — revoke per-device
- [ ] Rotacja cookie value przy każdym requeście (defense-in-depth, session fixation)

### Theme
- [ ] Light-mode toggle (obecnie dark-only — aligned z iOS default appearance)
- [ ] Respektuj `prefers-color-scheme` media query (opcjonalnie)

---

## v0.6 (Lightweight Polling) — zaimplementowane, otwarte weryfikacje

Implementacja z `ROADMAP.md` §v0.6 (pkt 1–7) zamknięta na `test` (0.6.0–0.6.3);
adaptacja KSeF API 2.7.x/2.8.x (pkt 8, faza A) = 0.6.4 na `feat/ksef-api-2.8-adaptation`.
Kod bez zmian wymaga już tylko danych z żywego KSeF albo rolloutu PRD:

- [ ] **Sonda granicy `dateRange` na TEST** — `examples/probe_date_range.py` (7 wywołań metadata, sesja unieważniana na końcu):
  ```bash
  read -rs KSEF_TOKEN && export KSEF_TOKEN   # token TEST, bez echa
  export KSEF_NIP=<nip>
  python examples/probe_date_range.py
  ```
  Wynik (max przyjęty span) wpisać do `ROADMAP.md` §v0.6 pkt 8.
- [ ] **0.6.5: `dateRange` 90 → 100 dni** (`MAX_DATE_RANGE_DAYS`, `MAX_WINDOW_DAYS`) — dopiero gdy live spec PRD pokaże „100 dni w strefie UTC” (23.09.2026 nadal „3 miesiące”) i jest wynik sondy. Plan: `docs/superpowers/plans/2026-09-23-ksef-api-2.8-adaptation.md` Task 6–7.
- [ ] **0.6.5: baseline `spec/openapi.json` (PRD) → 2.8.x** po rolloucie PRD.
- [ ] **E2E UPO** na żywym KSeF — wymaga tokenu z uprawnieniem `Introspection` (§4).
- [ ] **E2E logowania certyfikatem XAdES** — wymaga prawdziwego `.p12` (§7).
- [ ] **Operacyjne potwierdzenie limitów TEST = PRD** (§5).
- [ ] (Opcjonalnie) wrapper `/testdata/rate-limits` — endpoint już dostępny na TEST (§5).
- [ ] Po pushu 0.6.4 na `test`: zamknąć ręcznie issues bota driftu **#4** (test) i **#5** (demo) — `Closes #X` nie działa na gałęzi niedomyślnej.

---

## Znane problemy (v0.5.3 test)

- `POST /api/v1/monitor/trigger` pre-V5-16 zwracał `Trigger failed` (phantom API call). Naprawione w `508d930`.
- PDF footer pre-V5-17 pokazywał `KSeF Monitor v0.3` (hardcoded). Naprawione w `85debc0`.
- Docker pre-commit hook secret-scan może tłumaczyć długie bcrypt hashe w testach. Obchodzone przez `_secret-scan.conf` allowlist.

## Stan branchy (versions audit)

Stan 2026-09-25 (`git show origin/<branch>:…`):

| Branch | `app/__init__.py` | `pyproject.toml` | PDF footer | Migracje alembic |
|---|---|---|---|---|
| `main` | `"0.5.6"` ✓ | `"0.5.6"` ✓ | `v{{ app_version }}` ✓ | phase1–8 |
| `test` | `"0.6.3"` ✓ | `"0.6.3"` ✓ | `v{{ app_version }}` ✓ | phase1–8 |
| `feat/ksef-api-2.8-adaptation` | `"0.6.4"` ✓ | `"0.6.4"` ✓ | `v{{ app_version }}` ✓ | phase1–8 |

Niespójność wersji na `main` (2.0.0 / 0.4.0 / v0.3) zniknęła, gdy na `main` weszły wydania 0.5.2 i 0.5.3
(`b21ea8a`, `44cd16c` — UI auth V5-12…V5-17). `test` wyprzedza `main` o 49 commitów; `main` ma 23 commity
spoza `test` — cherry-picki i backporty: sync spec OpenAPI, bump zależności (cryptography, fastapi/starlette),
poprawki CI etykiet issue, webhook `allow_private_network`, runtime bez pip, usunięcie ostrzeżenia App Store.

---

## Docker deployment scenarios pending test

Sprawdzić każdy wariant konfiguracji w docker-compose:

- [ ] **Dev**: `auth_token=""` → middleware bez auth gate, cookie session niezależny, `/ui/login` + `/ui/account` muszą działać
- [ ] **Prod direct, fresh install (auto-gen token)**: `auth_token=""` w config + `api.enabled=true` → token auto-gen, **bootstrap SKIPPED**, `/ui/login` → 303 → `/ui/setup` wizard
- [ ] **Prod direct, operator-supplied token**: `auth_token` ustawiony przez operatora → bootstrap admin = ten token, login OK
- [ ] **Prod + reverse-proxy (`ui_public=true`)**: UI bypass, ale cookie resolver wciąż populuje `ui_username` → navbar kompletny, `/ui/account` działa
- [ ] **Docker Swarm + secrets**: `API_AUTH_TOKEN` z secret file → operator-supplied path, bootstrap admin przy pustej DB
- [ ] **Upgrade 0.5.0 → 0.5.3**: `alembic upgrade head` doda phase5/6/7/8 (ui_users + ui_sessions + ui_login_attempts + initial_load_windows); main.py bootstrap → `admin` z istniejącym `auth_token`
- [ ] **Upgrade 0.5.6 (`main`) → 0.6.x**: te same migracje phase1–8 po obu stronach — start bez zmian schematu, dane i sesje UI zachowane

---

## Komendy do testu (kontekst docker)

```bash
# Lista kont UI
docker exec -it ksef-monitor python -m app.user_admin list

# Dodanie usera
docker exec -it ksef-monitor python -m app.user_admin add <username>

# Reset hasła (revoke wszystkich sesji użytkownika)
docker exec -it ksef-monitor python -m app.user_admin reset-password <username>

# Usunięcie usera (refuses last user)
docker exec -it ksef-monitor python -m app.user_admin delete <username>

# Czyszczenie wygasłych sesji
docker exec -it ksef-monitor python -m app.user_admin cleanup-sessions
```

Logi bootstrap admin:
```bash
docker logs ksef-monitor 2>&1 | grep -i "Bootstrap: created"
```
