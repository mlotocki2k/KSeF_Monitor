# TODO — KSeF Monitor (Docker)

Stan na: 2026-04-23 (branch `test`, commit `508d930`).

Aplikacja Docker — uruchamiana jako kontener (`docker-compose` / `docker stack`).
Wszystkie instrukcje CLI poniżej zakładają kontekst kontenera (`docker exec -it ksef-monitor ...`).

---

## Pre-prod (branch `test`, 0.5.1)

Release `test` → `main` gating: **manualny user-test + iOS app v1.1.1 w App Store** (patrz `memory/project_release_gating.md`).

- [x] V5-12 cookie session
- [x] V5-13 user accounts + DB sessions + bootstrap admin
- [x] V5-14 middleware split (session resolver niezależny od auth gate)
- [x] V5-15 dark theme spójny z iOS
- [x] V5-16 fix `POST /monitor/trigger`
- [x] V5-17 fix PDF footer version (hardcoded v0.3 → `app.__version__`)
- [ ] **User testing scenariuszy:**
  - [ ] Fresh install: wizard `/ui/setup` → utworzenie konta admin → zalogowanie
  - [ ] Upgrade z v0.5.0 z istniejącym `auth_token`: auto-bootstrap `admin` = `auth_token`, login, zmiana hasła w `/ui/account`
  - [ ] Przycisk "Sprawdź" w navbar → status 200, flash "Check scheduled"
  - [ ] Bearer `Authorization: Bearer <token>` curl na `/api/v1/invoices` → działa
  - [ ] iOS pairing flow (push pairing code z `/ui/push`)
  - [ ] Rate limity: `/ui/login` 5/min, `/ui/setup` 3/min
  - [ ] Password change → revoke wszystkich sesji → wymuszone ponowne logowanie
  - [ ] Visual QA dark theme: navbar, dashboard, lista faktur, push, setup, login
- [ ] Merge `test` → `main` (po zielonym user-test + iOS v1.1.1 prod)
- [ ] Bump Docker image tag `v0.5.1` po merge

---

## Follow-ups po 0.5.1 (non-blocking)

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

## Znane problemy (v0.5.1 test)

- `POST /api/v1/monitor/trigger` pre-V5-16 zwracał `Trigger failed` (phantom API call). Naprawione w `508d930`.
- PDF footer pre-V5-17 pokazywał `KSeF Monitor v0.3` (hardcoded). Naprawione w `85debc0`.
- Docker pre-commit hook secret-scan może tłumaczyć długie bcrypt hashe w testach. Obchodzone przez `_secret-scan.conf` allowlist.

## Stan branchy (versions audit)

| Branch | `app/__init__.py` | `pyproject.toml` | PDF footer |
|---|---|---|---|
| `main` | `"2.0.0"` ⚠ | `"0.4.0"` ⚠ | `v0.3` ⚠ (hardcoded, przed V5-17) |
| `test` | `"0.5.1"` ✓ | `"0.5.1"` ✓ | `v{{ app_version }}` ✓ (V5-17) |

**Main jest niespójny** (trzy różne wersje w trzech miejscach). Decyzja:
czekamy z naprawą do merge `test` → `main` — wtedy jednym ruchem
wyrównane do 0.5.1. Patrz `memory/project_release_gating.md`.

---

## Docker deployment scenarios pending test

Sprawdzić każdy wariant konfiguracji w docker-compose:

- [ ] **Dev**: `auth_token=""` → middleware bez auth gate, cookie session niezależny, `/ui/login` + `/ui/account` muszą działać
- [ ] **Prod direct**: `auth_token` set, bez reverse-proxy → wizard + login + account OK
- [ ] **Prod + reverse-proxy (`ui_public=true`)**: UI bypass, ale cookie resolver wciąż populuje `ui_username` → navbar kompletny, `/ui/account` działa
- [ ] **Docker Swarm + secrets**: `API_AUTH_TOKEN` z secret file → bootstrap admin przy pustej DB
- [ ] **Upgrade 0.5.0 → 0.5.1**: `alembic upgrade head` doda `ui_users` + `ui_sessions`; main.py bootstrap → `admin` z istniejącym `auth_token`

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
