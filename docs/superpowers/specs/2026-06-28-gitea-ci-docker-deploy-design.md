# Spec — Gitea CI build + deploy (KSeF Monitor Docker)

Data: 2026-06-28
Repo: `gitea.krzewiny.net:3033/mlotocki/KSeF_Monitor` (`ksef_monitor_v0_1`)

> **PIVOT 2026-06-30 — PODEJŚCIE ZMIENIONE.** Ten spec opisuje pierwotny wariant
> „kopiuj inline pipeline z budget app". W trakcie realizacji ustalono, że istnieje
> **reusable workflow** `mlotocki/ci-templates/.gitea/workflows/docker-synology.yml`
> (uogólniony z budgetu; budget już go używa). KSeF migruje na niego zamiast kopiować.
> **Autorytatywne artefakty:** `.gitea/workflows/ci.yml` (cienki caller `@v0.18.0`) +
> `deploy/synology/compose.yaml` (`compose_src`) + `deploy/synology/README.md`.
> Skrypty deploy należą do ci-templates (`templates_ref: v0.18.0`) — nie do tego repo.
> Poniższe sekcje o `resolve-deploy-config.sh` / `remote-deploy.sh` / `docker-build.yml`
> są historyczne. Aktualne: branch/env mapping, hosty, ścieżki, Gitea Variables/Secrets,
> precedence `.gitea`>`.github`, edycja host compose (opcja A) — bez zmian.
> Znane residuum: v0.18.0 przekazuje `REGISTRY_TOKEN` w argv ssh (reguła #1) → fix upstream w ci-templates (→ v0.19.0).
>
> **KOREKTA konfiguracji (2026-06-30):** Gitea Variables/Secrets są **GLOBALNE (user-level),
> współdzielone** przez wszystkie projekty (budget/bug-intake/monitor_ksef deployują na te same
> 2 hosty Synology) — NIE repo-level jak pierwotnie zakładano. KSeF nie dodaje nic w Gitea.
> Niestandardowe katalogi hosta (`monitor_ksef`/`ksef_monitor` ≠ nazwa repo) rozwiązane przez
> **inputy `deploy_test_path`/`deploy_prod_path` w `ci.yml`**, nie przez repo-level Variables.

## Cel

Dodać do repozytorium dockerowego automatyczny pipeline build → push → deploy w
Gitea Actions, wzorowany 1:1 na działającym pipeline budget app. Push na branch
`test` wdraża na `test.krzewiny.net`, push na `main` wdraża na `docker.krzewiny.net`.
Dziś obrazy budują się tylko do GHCR (przez mirror GitHub) i **nie ma auto-deployu** —
hosty zostały zaktualizowane ostatnio ręcznie.

## Zweryfikowany stan realny (2026-06-28)

Inspekcja przez SSH (`cdeploy@…:223`) + Gitea API. **Realny layout różni się od
przykładowego `docker-compose.yml` w repo** — design bazuje na realnych hostach.

Oba hosty: serwis compose `ksef_monitor`, kontener `ksef-monitor`, plik `compose.yaml`,
**już zalogowane do `gitea.krzewiny.net:3033`** w `~/.docker/config.json`, deploy user
`cdeploy`.

| | test.krzewiny.net (VDSM_Test) | docker.krzewiny.net (SynNas_Docker) |
|---|---|---|
| stan kontenera | `Exited (0) 7 weeks ago` | `Up 2 weeks (healthy)` |
| image | `ghcr.io/mlotocki2k/ksef_monitor:test` | `ghcr.io/mlotocki2k/ksef_monitor:latest` |
| deploy dir | `/volume1/docker/monitor_ksef` | `/volume1/docker/ksef_monitor` |
| porty | `8999:8000` (metryki), `8888:8080` (UI/API) | identyczne |
| mounts | `./config.json:/data/config.json:ro`, `./data:/data` (bind) | identyczne |
| klucz SSH | `cdeploy_test` | `cdeploy_docker` |

Healthcheck pochodzi z `HEALTHCHECK` w `Dockerfile` (linia 65) — **nie** z compose;
stąd `(healthy)` na prod. W compose nie dodajemy healthchecku.

Gitea (repo `KSeF_Monitor`): brak repo-level Variables/Secrets, brak repo-runnera
(runner działa na poziomie instancji — budget CI działa). Branche `main`, `test`,
`v05_push`. Config deploy budget app trzymany na poziomie **usera** (inne hosty/user
niż KSeF — stąd dla KSeF używamy Variables **repo-level**, by uniknąć kolizji).

## Architektura — flow

| Trigger | Build tag | Deploy |
|---|---|---|
| push `test` | `:test` + `:sha` | `test.krzewiny.net` (`DEPLOY_TEST_*`) |
| push `main` | `:latest` + `:sha` | `docker.krzewiny.net` (`DEPLOY_PROD_*`) |
| pull request | tylko lokalny build (bez push/deploy) | brak |
| Run workflow (ręcznie) | wg wyboru `test`/`prod` | wg wyboru |

Rejestr: build+push do `gitea.krzewiny.net:3033/mlotocki/ksef_monitor` (lowercase
wymuszony przez rejestr). Deploy: SSH na host → `docker compose pull` +
`up -d --force-recreate` serwisu `ksef_monitor`.

⚠️ Konsekwencja: merge `test` → `main` = auto-deploy prod. Zgodne z release gating —
gating decyduje *kiedy* mergujesz; merge odpala prod.

## Pliki do utworzenia w repo

```
.gitea/workflows/docker-build.yml          # build → push → deploy-test / deploy-prod
deploy/gitea-ci/resolve-deploy-config.sh   # 1:1 z budget app (env-agnostic resolver)
deploy/gitea-ci/README.md                  # opis Variables/Secrets
deploy/synology/remote-deploy.sh           # uruchamiany na hoście przez SSH
deploy/synology/compose.yaml               # TEMPLATE referencyjny (= realny layout, Gitea image)
deploy/synology/README.md                  # setup hostów (jednorazowo)
```

GitHub `.github/workflows/*` (GHCR build + skany detect-secrets/pip-audit/trivy) —
**bez zmian**. Skany zostają na mirrorze; Gitea workflow robi tylko build + deploy
(parytet z budget — bez duplikacji skanów).

### KRYTYCZNE — precedence `.gitea` vs `.github` (Gitea WorkflowDirs)

Gitea czyta workflow z **pierwszego istniejącego** katalogu z listy
`setting.Actions.WorkflowDirs` (default `[.gitea/workflows, .github/workflows]`).
Źródło (`modules/actions/workflows.go`, release/v1.26):

```go
for _, workflowDir = range setting.Actions.WorkflowDirs {
    tree, err = commit.SubTree(workflowDir)
    if err == nil { break }   // pierwszy istniejący katalog = wyłączny
}
```

Konsekwencja: gdy istnieje `.gitea/workflows`, Gitea **całkowicie ignoruje**
`.github/workflows`. GitHub (mirror) dalej je wykonuje (nie zna `.gitea`).

**Dodanie `.gitea/workflows/docker-build.yml` jest więc nie tylko nowym pipeline,
ale i fixem.** Dopóki `.gitea/workflows` nie istnieje, Gitea spada na
`.github/workflows` i odpala **wszystkie 7** GitHubowych workflow — w tym matrycę
`tests.yml` (3.10/3.11/3.12, ~12 min/job), **dwa** nakładające się joby `build`
(`docker-publish.yml` + `build_push_test.yml` oba łapią push `test`) i `security`.

### Kontekst incydentu (2026-06-28)

Zweryfikowano na żywo (Gitea API): repo bez `.gitea/workflows` → ~6 ciężkich jobów
na każdy push `test`/`main`, runner nie wyrabia, backlog rósł do 20+ running + 20+
waiting, blokując CI. Dodatkowo joby `build` failowały co raz (login `ghcr.io` przez
`secrets.GITHUB_TOKEN`/`github.actor` nie działa z Gitei). Wgranie `.gitea/workflows`
zatrzymuje to dublowanie u źródła. Backlog z incydentu czyszczony ręcznie w UI Gitea
(poza zakresem tego specu).

## `.gitea/workflows/docker-build.yml`

Adaptacja `budget_app/.gitea/workflows/docker-build.yml`:
- Triggery: `push` na `[main, test]`, `pull_request` na `[main, test]`, `workflow_dispatch` (choice test/prod).
- Resolve env: `main` → `prod`/`latest`, `test` → `test`/`test`, dispatch → wybór.
- Build: `IMAGE=gitea.krzewiny.net:3033/mlotocki/ksef_monitor` (lowercase hardcode), cache-from po tagu, tagi `:<sha>` + `:<test|latest>`, `BUILD_SHA` build-arg.
- Push: tylko gdy nie-PR i tag ≠ pusty.
- Joby `deploy-test` / `deploy-prod`: `needs: build`, warunek po `deploy_env`, źródłem konfiguracji `deploy/gitea-ci/resolve-deploy-config.sh`, deploy przez `ssh … bash -s < deploy/synology/remote-deploy.sh` z przekazaniem `REGISTRY_*`, `DEPLOY_PATH`, `MKSEF_TAG`.

Zmienne nazewnicze vs budget: `BUDGET_APP_TAG` → `MKSEF_TAG`; serwis `app` → `ksef_monitor`; kontener `budget_app` → `ksef-monitor`.

## `deploy/synology/remote-deploy.sh`

Adaptacja budgetowego. Kontrakt (env z CI): `DEPLOY_PATH`, `REGISTRY_HOST`,
`REGISTRY_USER`, `REGISTRY_TOKEN`, `MKSEF_TAG`.

```sh
cd "${DEPLOY_PATH}"
echo "${REGISTRY_TOKEN}" | docker login "${REGISTRY_HOST}" -u "${REGISTRY_USER}" --password-stdin
export MKSEF_TAG
docker compose pull ksef_monitor
docker compose up -d --force-recreate --pull missing ksef_monitor || {
  # fallback: konflikt nazwy kontenera 'ksef-monitor'
  docker rm -f ksef-monitor 2>/dev/null || true
  docker compose up -d ksef_monitor
}
docker compose ps ksef_monitor
```
Zachowuje budgetowy PATH-fix dla Synology (`/usr/local/bin/docker`).
Plik compose na hoście to `compose.yaml` (domyślnie wykrywany przez `docker compose`).

## `deploy/synology/compose.yaml` (template referencyjny)

= realny layout hostów, jedyna zmiana: GHCR → rejestr Gitea + parametr tagu.
`restart` **pozostaje zakomentowany** (decyzja: zachować obecne zachowanie hostów).

```yaml
version: '3.8'
services:
  ksef_monitor:
    image: ${MKSEF_IMAGE:-gitea.krzewiny.net:3033/mlotocki/ksef_monitor}:${MKSEF_TAG:-test}
    container_name: ksef-monitor
    pull_policy: always
    #restart: unless-stopped
    ports:
      - "8999:8000"   # Prometheus metrics
      - "8888:8080"   # UI / API
    volumes:
      - ./config.json:/data/config.json:ro
      - ./data:/data
```

## `deploy/gitea-ci/resolve-deploy-config.sh`

Kopia 1:1 z budget app — env-agnostic (czyta `VAR_*`/`SEC_*`, precedencja
Variables → Secrets, per-env fallback). Bez zmian. Domyślny `DEPLOY_PATH`
(`/volume1/docker/<repo>`) jest nadpisywany przez Variables (patrz niżej), bo realne
ścieżki to `monitor_ksef` (test) i `ksef_monitor` (prod).

## Konfiguracja Gitea (repo-level: `KSeF_Monitor` → Settings → Actions)

Repo-level, bo user-level zajęte przez budget (inny user/hosty → kolizja).

**Secrets:**
| Nazwa | Wartość |
|---|---|
| `DEPLOY_TEST_SSH_KEY` | klucz prywatny `~/.ssh/cdeploy_test` |
| `DEPLOY_PROD_SSH_KEY` | klucz prywatny `~/.ssh/cdeploy_docker` |
| `REGISTRY_TOKEN` | token Gitea z prawem push/pull do rejestru (może być Variable) |

**Variables:**
| Nazwa | Wartość |
|---|---|
| `DEPLOY_USER` | `cdeploy` |
| `DEPLOY_TEST_HOST` | `test.krzewiny.net` |
| `DEPLOY_PROD_HOST` | `docker.krzewiny.net` |
| `DEPLOY_TEST_SSH_PORT` | `223` |
| `DEPLOY_PROD_SSH_PORT` | `223` |
| `DEPLOY_TEST_PATH` | `/volume1/docker/monitor_ksef` |
| `DEPLOY_PROD_PATH` | `/volume1/docker/ksef_monitor` |

## Host — jednorazowa zmiana (opcja A, wybrana)

Na **obu** Synology edytować istniejący `compose.yaml` (`/volume1/docker/monitor_ksef`
i `/volume1/docker/ksef_monitor`):
- `image:` → `${MKSEF_IMAGE:-gitea.krzewiny.net:3033/mlotocki/ksef_monitor}:${MKSEF_TAG:-test}`
  (na prod sensowny domyślny tag `latest`; CI i tak przekazuje `MKSEF_TAG`)
- dodać `pull_policy: always`

Rejestr Gitea już zalogowany na obu hostach (zweryfikowane), `config.json` + `data/`
zostają nietknięte przez deploy. Po edycji CI robi tylko `pull` + `up -d`.

## Strategia branchy / aktywacja

Workflow Gitea Actions wykonuje plik z brancha, na który następuje push. Pliki dodać
najpierw na `test` → aktywuje deploy test. Po mergu `test` → `main` plik trafia na
`main` → aktywuje deploy prod. Do czasu mergu prod-deploy nieaktywny (brak ryzyka
przypadkowego wdrożenia prod).

## Poza zakresem (YAGNI)

- Skany bezpieczeństwa w Gitea (zostają na GitHub).
- Healthcheck w compose (jest w Dockerfile).
- `restart: unless-stopped` (decyzja: nie włączać).
- CI dosyłające compose.yaml (wybrano opcję A — ręczna edycja hostów).
- Postgres/avahi (specyfika budget, nieobecne w KSeF).

## Weryfikacja po wdrożeniu

0. Po wgraniu `.gitea/workflows/` — Gitea **przestaje** uruchamiać joby `test (3.x)` /
   podwójny `build` / `security` z `.github/workflows` (precedence). Sprawdź w Actions, że
   nowe runy to tylko `build` + `deploy-*` z `.gitea`.
1. Push testowy na `test` → job `build` zielony, obraz `:test` + `:<sha>` w rejestrze Gitea.
2. Job `deploy-test` zielony; na `test.krzewiny.net`: `docker ps` pokazuje `ksef-monitor`
   `Up`, image `gitea.krzewiny.net:3033/mlotocki/ksef_monitor:test`.
3. UI dostępne na `http://test.krzewiny.net:8888` (lub przez reverse proxy).
4. Analogicznie merge na `main` → `deploy-prod` → `docker.krzewiny.net`.
5. `docker compose ps ksef_monitor` na hoście = `running`.

## Ryzyka / uwagi

- **Test kontener leży 7 tyg** — pierwszy deploy test go wskrzesi (recreate). Bez
  `restart` nie wstanie po reboocie hosta (świadoma decyzja).
- **Rejestr Gitea image case** — musi być lowercase `ksef_monitor`; build i host compose
  spójne.
- **REGISTRY_TOKEN scope** — wymaga write (push z CI) + pull (host). Hosty już mają
  zapisany login, ale CI loguje się ponownie tokenem.
- **Klucze deploy** — test i prod to **różne** pary (`cdeploy_test` / `cdeploy_docker`);
  nie mylić, stąd per-env `DEPLOY_*_SSH_KEY`.
- **Pierwszy push z `.gitea`** odpala od razu `build` + `deploy-test`. Jeśli Gitea
  Variables/Secrets nie są jeszcze ustawione, `resolve-deploy-config.sh` kończy
  `exit 2` → workflow **pomija deploy** (nie failuje). Bezpieczne: można wgrać workflow
  przed konfiguracją, deploy ruszy dopiero gdy zmienne będą gotowe.
- **Kolejność wdrożenia** — najpierw ustaw Gitea Variables/Secrets + edytuj host compose
  (opcja A), dopiero potem push `.gitea` na `test`, by pierwszy deploy zadziałał od razu.
