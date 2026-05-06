# TODO — KSeF Monitor (Docker)

Stan na: 2026-05-06 (branch `test`, commit `3b35cd7` + bump `0.5.3`).

Aplikacja Docker — uruchamiana jako kontener (`docker-compose` / `docker stack`).
Wszystkie instrukcje CLI poniżej zakładają kontekst kontenera (`docker exec -it ksef-monitor ...`).

---

## Pre-prod (branch `test`, 0.5.3)

Release `test` → `main` gating: **manualny user-test + iOS app v1.1.1 w App Store** (patrz `memory/project_release_gating.md`).

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
- [x] **iOS App Store status** — amber notice w `/ui/push` + README pointujące na `kontakt@krzewilabs.pl` po TestFlight.

### User testing scenariuszy
- [ ] Fresh install (czysty volume): `/ui/login` → 303 → `/ui/setup` wizard → username/pass → login → dashboard
- [ ] Upgrade z v0.5.0 z istniejącym `auth_token`: bootstrap `admin` = `auth_token`, login, zmiana hasła w `/ui/account`
- [ ] Przycisk "Sprawdź" w navbar → status 200, flash "Check scheduled"
- [ ] Bearer `Authorization: Bearer <token>` curl na `/api/v1/invoices` → działa
- [ ] iOS pairing flow (push pairing code z `/ui/push` → TestFlight v1.1.x)
- [ ] Rate limity: `/ui/login` 5/min, `/ui/setup` 3/min
- [ ] Password change → revoke wszystkich sesji → wymuszone ponowne logowanie
- [ ] Visual QA dark theme: navbar, dashboard, lista faktur, push, setup, login
- [ ] **Initial load fresh**: dłuższy zakres (>90 dni) → wszystkie okna succeed, faktury w DB, "Ukończony" 100%
- [ ] **Initial load history view**: toggle "Pokaż historię okien" → tabelka per-window, statusy OK/FAIL, durations
- [ ] **Audit log INFO**: `docker logs ksef-monitor 2>&1 | grep "UI login session created"` po loginie → widoczne
- [ ] Merge `test` → `main` (po zielonym user-test + iOS v1.1.1 prod)
- [ ] Bump Docker image tag `v0.5.3` po merge

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

## v0.6 (Lightweight Polling) — planowany

Zgodnie z `ROADMAP.md` §v0.6. Skupia się na rozdzieleniu detekcji nowych
faktur od pobierania artefaktów (oszczędność API calls KSeF).

---

## Znane problemy (v0.5.3 test)

- `POST /api/v1/monitor/trigger` pre-V5-16 zwracał `Trigger failed` (phantom API call). Naprawione w `508d930`.
- PDF footer pre-V5-17 pokazywał `KSeF Monitor v0.3` (hardcoded). Naprawione w `85debc0`.
- Docker pre-commit hook secret-scan może tłumaczyć długie bcrypt hashe w testach. Obchodzone przez `_secret-scan.conf` allowlist.

## Stan branchy (versions audit)

| Branch | `app/__init__.py` | `pyproject.toml` | PDF footer |
|---|---|---|---|
| `main` | `"2.0.0"` ⚠ | `"0.4.0"` ⚠ | `v0.3` ⚠ (hardcoded, przed V5-17) |
| `test` | `"0.5.3"` ✓ | `"0.5.3"` ✓ | `v{{ app_version }}` ✓ (V5-17) |

**Main jest niespójny** (trzy różne wersje w trzech miejscach). Decyzja:
czekamy z naprawą do merge `test` → `main` — wtedy jednym ruchem
wyrównane do 0.5.3. Patrz `memory/project_release_gating.md`.

---

## Docker deployment scenarios pending test

Sprawdzić każdy wariant konfiguracji w docker-compose:

- [ ] **Dev**: `auth_token=""` → middleware bez auth gate, cookie session niezależny, `/ui/login` + `/ui/account` muszą działać
- [ ] **Prod direct, fresh install (auto-gen token)**: `auth_token=""` w config + `api.enabled=true` → token auto-gen, **bootstrap SKIPPED**, `/ui/login` → 303 → `/ui/setup` wizard
- [ ] **Prod direct, operator-supplied token**: `auth_token` ustawiony przez operatora → bootstrap admin = ten token, login OK
- [ ] **Prod + reverse-proxy (`ui_public=true`)**: UI bypass, ale cookie resolver wciąż populuje `ui_username` → navbar kompletny, `/ui/account` działa
- [ ] **Docker Swarm + secrets**: `API_AUTH_TOKEN` z secret file → operator-supplied path, bootstrap admin przy pustej DB
- [ ] **Upgrade 0.5.0 → 0.5.3**: `alembic upgrade head` doda phase5/6/7/8 (ui_users + ui_sessions + ui_login_attempts + initial_load_windows); main.py bootstrap → `admin` z istniejącym `auth_token`

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
