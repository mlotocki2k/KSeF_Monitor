# Gitea CI Build + Deploy (KSeF Monitor Docker) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodać do repo dockerowego pipeline Gitea Actions build → push (rejestr Gitea) → deploy przez SSH na `test.krzewiny.net` (branch `test`) i `docker.krzewiny.net` (branch `main`), wzorowany 1:1 na budget app.

> **PIVOT 2026-06-30 — Tasks 1/2/4/5 ZASTĄPIONE.** Zamiast kopiować inline pipeline,
> KSeF używa reusable `mlotocki/ci-templates/.gitea/workflows/docker-synology.yml@v0.18.0`
> przez cienki caller `.gitea/workflows/ci.yml` (commit `5bf89e7`). Usunięto
> `resolve-deploy-config.sh`, `remote-deploy.sh`, `docker-build.yml` (template ma własne w `_cit/`).
> **Nadal aktualne:** Task 3 (`compose.yaml` = `compose_src`), Task 6 (Gitea Variables/Secrets
> + edycja host compose), Task 7 (pierwszy deploy test), Task 8 (promocja main). Zamiast
> commitować `docker-build.yml` (Task 7 Step 2) — commituje się `ci.yml` (już zrobione).
> Poniższe Tasks 1/2/4/5 zachowane jako historia.
>
> **KOREKTA Task 6 (2026-06-30):** Gitea config jest GLOBALNY (user-level, współdzielony z
> budget/bug-intake) — NIE repo-level. KSeF nie ustawia nic w Gitea (globalne `DEPLOY_USER=cdeploy`,
> hosty, porty, klucze `cdeploy_test`/`cdeploy_docker`, `REGISTRY_TOKEN` już istnieją). Niestandardowe
> ścieżki hosta idą przez inputy `deploy_test_path`/`deploy_prod_path` w `ci.yml` (już dodane).

**Architecture:** Jeden workflow `.gitea/workflows/docker-build.yml` z jobem `build` (build+push obrazu do rejestru Gitea) i dwoma jobami deploy (`deploy-test`, `deploy-prod`) uruchamianymi warunkowo po branchu/dispatchu. Deploy = SSH na Synology, `resolve-deploy-config.sh` czyta konfigurację z Gitea Variables/Secrets, `remote-deploy.sh` robi `docker compose pull` + `up -d` serwisu `ksef_monitor`. Dodanie `.gitea/workflows` **wyłącza** równoległe wykonywanie `.github/workflows` przez Gitę (precedence WorkflowDirs).

**Tech Stack:** Gitea Actions (Gitea 1.26.2), Bash, Docker Compose, Synology DSM Container Manager.

## Global Constraints

- Rejestr obrazu (lowercase, wymuszone): `gitea.krzewiny.net:3033/mlotocki/ksef_monitor`
- Branch → env → host: `test` → `:test` → `test.krzewiny.net`; `main` → `:latest` → `docker.krzewiny.net`
- Deploy user: `cdeploy`, SSH port `223`, oba hosty
- Deploy paths: test `/volume1/docker/monitor_ksef`, prod `/volume1/docker/ksef_monitor`
- Klucze SSH per-env: test `cdeploy_test`, prod `cdeploy_docker` (różne pary)
- Serwis compose `ksef_monitor`, kontener `ksef-monitor`, plik na hoście `compose.yaml`
- Zmienna tagu: `MKSEF_TAG`; obrazu: `MKSEF_IMAGE`
- Wolumeny (bind, nie named): `./config.json:/data/config.json:ro` + `./data:/data`
- `restart` **zakomentowany**; healthcheck NIE w compose (jest w Dockerfile)
- `.github/workflows/*` **bez zmian** (zostają dla GitHub mirror)
- Gitea Variables/Secrets na poziomie **repo** `KSeF_Monitor` (user-level zajęty przez budget)
- Wszystkie pliki tworzone w repo `ksef_monitor_v0_1`, branch `test` najpierw

## File Structure

- Create: `deploy/gitea-ci/resolve-deploy-config.sh` — resolver konfiguracji deploy z Variables/Secrets (env-agnostic)
- Create: `deploy/synology/remote-deploy.sh` — skrypt uruchamiany na hoście przez SSH (login rejestr + compose pull/up)
- Create: `deploy/synology/compose.yaml` — template compose = realny layout hostów + obraz z Gitea
- Create: `.gitea/workflows/docker-build.yml` — workflow build/push/deploy (ORAZ fix floodu `.github`)
- Create: `deploy/gitea-ci/README.md` — dokumentacja Variables/Secrets
- Create: `deploy/synology/README.md` — setup hostów jednorazowy
- Unchanged: `.github/workflows/*`, `Dockerfile`, istniejące `docker-compose*.yml`

Walidatory lokalne (brak `shellcheck` → `bash -n`): shell = `bash -n <plik>`; YAML = `python3 -c "import yaml; yaml.safe_load(open('<plik>'))"`; compose = `MKSEF_TAG=test docker compose -f <plik> config`.

---

### Task 1: resolve-deploy-config.sh

Kopia 1:1 z budget app (env-agnostic, działa bez zmian). Czyta `VAR_*`/`SEC_*` wstrzyknięte przez workflow, precedencja Variables → Secrets, per-env fallback; `exit 2` = brak konfiguracji → workflow pomija deploy.

**Files:**
- Create: `deploy/gitea-ci/resolve-deploy-config.sh`

**Interfaces:**
- Consumes (env przed `source`): `DEPLOY_ENV` (`test`|`prod`), `GITEA_REPOSITORY`, `VAR_*`/`SEC_*`
- Produces (eksportuje po `source`): `DEPLOY_SSH_KEY`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PATH`, `DEPLOY_SSH_PORT`, `REGISTRY_TOKEN`; kody wyjścia: `0` OK, `1` błąd env, `2` brak wymaganych → skip

- [ ] **Step 1: Utwórz plik z pełną treścią**

```bash
#!/usr/bin/env bash
# Resolve deploy config from Gitea Actions variables + secrets.
#
# Variables (user/org/repo → Actions → Variables): host, user, path, registry token
# Secrets (Actions → Secrets): SSH private keys only
#
# Env before sourcing:
#   DEPLOY_ENV=test|prod
#   GITEA_REPOSITORY=owner/repo
#   VAR_* / SEC_* injected by workflow (empty if unset)

set -euo pipefail

pick() {
  local primary=$1
  shift
  if [ -n "${!primary:-}" ]; then
    printf '%s' "${!primary}"
    return
  fi
  for fallback in "$@"; do
    if [ -n "${!fallback:-}" ]; then
      printf '%s' "${!fallback}"
      return
    fi
  done
}

REPO_NAME="${GITEA_REPOSITORY##*/}"
DEFAULT_PATH="/volume1/docker/${REPO_NAME}"
DEPLOY_ENV_UPPER="$(printf '%s' "${DEPLOY_ENV}" | tr '[:lower:]' '[:upper:]')"

if [ "${DEPLOY_ENV}" = "test" ]; then
  export DEPLOY_SSH_KEY="$(pick SEC_DEPLOY_TEST_SSH_KEY SEC_DEPLOY_SSH_KEY)"
  export DEPLOY_HOST="$(pick VAR_DEPLOY_TEST_HOST VAR_DEPLOY_HOST SEC_DEPLOY_TEST_HOST SEC_DEPLOY_HOST)"
  export DEPLOY_USER="$(pick VAR_DEPLOY_TEST_USER VAR_DEPLOY_USER SEC_DEPLOY_TEST_USER SEC_DEPLOY_USER)"
  PATH_VARS=(VAR_DEPLOY_TEST_PATH VAR_DEPLOY_PATH SEC_DEPLOY_TEST_PATH SEC_DEPLOY_PATH)
  HOST_HINT="Variables: DEPLOY_TEST_HOST lub DEPLOY_HOST"
elif [ "${DEPLOY_ENV}" = "prod" ]; then
  export DEPLOY_SSH_KEY="$(pick SEC_DEPLOY_PROD_SSH_KEY SEC_DEPLOY_SSH_KEY)"
  export DEPLOY_HOST="$(pick VAR_DEPLOY_PROD_HOST SEC_DEPLOY_PROD_HOST)"
  export DEPLOY_USER="$(pick VAR_DEPLOY_PROD_USER VAR_DEPLOY_USER SEC_DEPLOY_PROD_USER SEC_DEPLOY_USER)"
  PATH_VARS=(VAR_DEPLOY_PROD_PATH VAR_DEPLOY_PATH SEC_DEPLOY_PROD_PATH SEC_DEPLOY_PATH)
  HOST_HINT="Variable: DEPLOY_PROD_HOST"
else
  echo "Nieznane DEPLOY_ENV=${DEPLOY_ENV}"
  exit 1
fi

  export DEPLOY_PATH="$(pick "${PATH_VARS[@]}")"
  if [ -z "${DEPLOY_PATH}" ]; then
    export DEPLOY_PATH="${DEFAULT_PATH}"
  fi

  if [ "${DEPLOY_ENV}" = "test" ]; then
    PORT_VARS=(VAR_DEPLOY_TEST_SSH_PORT VAR_DEPLOY_SSH_PORT SEC_DEPLOY_TEST_SSH_PORT SEC_DEPLOY_SSH_PORT)
  else
    PORT_VARS=(VAR_DEPLOY_PROD_SSH_PORT VAR_DEPLOY_SSH_PORT SEC_DEPLOY_PROD_SSH_PORT SEC_DEPLOY_SSH_PORT)
  fi
  export DEPLOY_SSH_PORT="$(pick "${PORT_VARS[@]}")"
  if [ -z "${DEPLOY_SSH_PORT}" ]; then
    export DEPLOY_SSH_PORT=22
  fi

  export REGISTRY_TOKEN="$(pick VAR_REGISTRY_TOKEN SEC_REGISTRY_TOKEN)"

check_required() {
  local kind=$1
  local name=$2
  local value=$3
  local hint=$4
  if [ -z "${value}" ]; then
    echo "Brak ${name}: ustaw w Gitea → Actions → ${kind}: ${hint}"
    return 1
  fi
  echo "OK: ${name}"
  return 0
}

echo "=== Konfiguracja deploy (${DEPLOY_ENV}) ==="
MISSING=0
check_required "Secrets" "DEPLOY_SSH_KEY" "${DEPLOY_SSH_KEY}" \
  "DEPLOY_${DEPLOY_ENV_UPPER}_SSH_KEY lub DEPLOY_SSH_KEY" || MISSING=1
check_required "Variables" "DEPLOY_HOST" "${DEPLOY_HOST}" "${HOST_HINT}" || MISSING=1
check_required "Variables" "DEPLOY_USER" "${DEPLOY_USER}" \
  "DEPLOY_${DEPLOY_ENV_UPPER}_USER lub DEPLOY_USER" || MISSING=1
check_required "Variables" "REGISTRY_TOKEN" "${REGISTRY_TOKEN}" \
  "REGISTRY_TOKEN (Variable; Secret też działa — legacy)" || MISSING=1
echo "Ścieżka deploy: ${DEPLOY_PATH} (domyślnie ${DEFAULT_PATH})"
echo "Port SSH: ${DEPLOY_SSH_PORT}"
if [ "${MISSING}" -ne 0 ]; then
  echo "Pomijam deploy ${DEPLOY_ENV}."
  exit 2
fi
```

- [ ] **Step 2: Walidacja składni**

Run: `bash -n deploy/gitea-ci/resolve-deploy-config.sh`
Expected: brak outputu, exit 0

- [ ] **Step 3: Smoke test resolvera (env test, brak zmiennych → exit 2)**

Run:
```bash
( set +e; DEPLOY_ENV=test GITEA_REPOSITORY=mlotocki/KSeF_Monitor bash -c 'source deploy/gitea-ci/resolve-deploy-config.sh'; echo "exit=$?" )
```
Expected: wypisze `Brak DEPLOY_SSH_KEY…`, `Pomijam deploy test.`, `exit=2`

- [ ] **Step 4: Commit**

```bash
git add deploy/gitea-ci/resolve-deploy-config.sh
git commit -m "feat(ci): add gitea deploy config resolver"
```

---

### Task 2: remote-deploy.sh

Skrypt uruchamiany na Synology przez `ssh … bash -s <`. Loguje do rejestru Gitea, robi `docker compose pull` + `up -d` serwisu `ksef_monitor`, z fallbackiem na konflikt nazwy kontenera `ksef-monitor`. Zachowuje budgetowy PATH-fix (`/usr/local/bin/docker`).

**Files:**
- Create: `deploy/synology/remote-deploy.sh`

**Interfaces:**
- Consumes (env z CI przez `ssh "VAR=... bash -s"`): `DEPLOY_PATH`, `REGISTRY_HOST`, `REGISTRY_USER`, `REGISTRY_TOKEN`, `MKSEF_TAG`
- Produces: recreate kontenera `ksef-monitor` z obrazu `${MKSEF_IMAGE:-…/ksef_monitor}:${MKSEF_TAG}`; wypisuje `docker compose ps ksef_monitor`

- [ ] **Step 1: Utwórz plik z pełną treścią**

```bash
#!/usr/bin/env bash
# Wywoływany z CI: ssh cdeploy@host "ENV=..." bash -s < deploy/synology/remote-deploy.sh
set -euo pipefail

export PATH="/usr/local/bin:/usr/sbin:/sbin:/bin:${PATH:-}"
if [ -x /usr/local/bin/docker ]; then
  DOCKER=/usr/local/bin/docker
elif command -v docker >/dev/null 2>&1; then
  DOCKER=$(command -v docker)
else
  echo "docker: command not found (PATH=${PATH})"
  echo "DSM: włącz Container Manager dla użytkownika deploy."
  exit 1
fi
docker() { "${DOCKER}" "$@"; }

: "${DEPLOY_PATH:?DEPLOY_PATH}"
: "${REGISTRY_HOST:?REGISTRY_HOST}"
: "${REGISTRY_USER:?REGISTRY_USER}"
: "${REGISTRY_TOKEN:?REGISTRY_TOKEN}"
: "${MKSEF_TAG:?MKSEF_TAG}"

cd "${DEPLOY_PATH}"

echo "${REGISTRY_TOKEN}" | docker login "${REGISTRY_HOST}" \
  -u "${REGISTRY_USER}" --password-stdin

export MKSEF_TAG

compose_redeploy() {
  local container_name="ksef-monitor"
  docker compose pull ksef_monitor
  if docker compose up -d --force-recreate --pull missing ksef_monitor 2>/dev/null; then
    docker compose ps ksef_monitor
    return 0
  fi
  if docker ps -a --format '{{.Names}}' | grep -qx "${container_name}"; then
    echo "Konflikt nazwy: zatrzymuję i usuwam ${container_name} (bind ./data zostaje)."
    docker stop "${container_name}" || true
    docker rm "${container_name}" || true
  fi
  docker compose up -d ksef_monitor
  docker compose ps ksef_monitor
}

compose_redeploy
```

- [ ] **Step 2: Walidacja składni**

Run: `bash -n deploy/synology/remote-deploy.sh`
Expected: brak outputu, exit 0

- [ ] **Step 3: Test guardów env (brak MKSEF_TAG → błąd)**

Run:
```bash
( set +e; DEPLOY_PATH=/tmp REGISTRY_HOST=x REGISTRY_USER=x REGISTRY_TOKEN=x bash deploy/synology/remote-deploy.sh 2>&1 | grep -c 'MKSEF_TAG'; )
```
Expected: `1` (brak MKSEF_TAG wywala `: "${MKSEF_TAG:?MKSEF_TAG}"` zanim dojdzie do docker login)

- [ ] **Step 4: Commit**

```bash
git add deploy/synology/remote-deploy.sh
git commit -m "feat(ci): add synology remote-deploy script"
```

---

### Task 3: compose.yaml (template hosta)

Template = realny layout obu hostów (zweryfikowany), jedyna zmiana vs produkcyjny: GHCR → rejestr Gitea + parametr `MKSEF_TAG` + `pull_policy: always`. `restart` zostaje zakomentowany, brak healthcheck (jest w Dockerfile).

**Files:**
- Create: `deploy/synology/compose.yaml`

**Interfaces:**
- Consumes: env `MKSEF_TAG` (domyślnie `test`), opcjonalnie `MKSEF_IMAGE`
- Produces: definicję serwisu `ksef_monitor` / kontenera `ksef-monitor`, porty `8999:8000` + `8888:8080`, bind `./config.json` + `./data`

- [ ] **Step 1: Utwórz plik z pełną treścią**

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

- [ ] **Step 2: Walidacja compose (rozwiązanie zmiennych + składnia)**

Run: `MKSEF_TAG=test docker compose -f deploy/synology/compose.yaml config`
Expected: wypisuje rozwiązany compose z `image: gitea.krzewiny.net:3033/mlotocki/ksef_monitor:test`, `container_name: ksef-monitor`, bez błędów

- [ ] **Step 3: Commit**

```bash
git add deploy/synology/compose.yaml
git commit -m "feat(ci): add synology compose template (gitea registry image)"
```

---

### Task 4: .gitea/workflows/docker-build.yml

Główny workflow. Job `build` (resolve env → login rejestr Gitea → build → push), joby `deploy-test`/`deploy-prod` (checkout → resolve config → SSH deploy). **Uwaga:** samo utworzenie tego katalogu sprawia, że Gitea przestaje wykonywać `.github/workflows` (precedence — patrz spec).

**Files:**
- Create: `.gitea/workflows/docker-build.yml`

**Interfaces:**
- Consumes: Gitea Variables/Secrets (Task 6), `deploy/gitea-ci/resolve-deploy-config.sh` (Task 1), `deploy/synology/remote-deploy.sh` (Task 2)
- Produces: obraz `gitea.krzewiny.net:3033/mlotocki/ksef_monitor:{sha,test|latest}`; deploy na hosty

- [ ] **Step 1: Utwórz plik z pełną treścią**

```yaml
name: Build, Push & Deploy

# Branch → środowisko:
#   main → prod (tag latest, deploy na docker.krzewiny.net)
#   test → test (tag test,   deploy na test.krzewiny.net)
# PR: tylko build (bez push/deploy). Ręcznie (workflow_dispatch): wybór test|prod.

on:
  push:
    branches: [main, test]
  pull_request:
    branches: [main, test]
  workflow_dispatch:
    inputs:
      environment:
        description: Środowisko (test lub prod)
        required: true
        default: test
        type: choice
        options:
          - test
          - prod

jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    outputs:
      deploy_env: ${{ steps.resolve-env.outputs.deploy_env }}
      image_tag: ${{ steps.resolve-env.outputs.image_tag }}
    env:
      REGISTRY_HOST: gitea.krzewiny.net:3033
    steps:
      - name: Resolve environment
        id: resolve-env
        run: |
          set -euo pipefail
          if [ "${{ gitea.event_name }}" = "workflow_dispatch" ]; then
            ENV="${{ gitea.event.inputs.environment }}"
          elif [ "${{ gitea.ref }}" = "refs/heads/main" ]; then
            ENV=prod
          elif [ "${{ gitea.ref }}" = "refs/heads/test" ]; then
            ENV=test
          else
            ENV=none
          fi
          case "${ENV}" in
            prod)  TAG=latest ;;
            test)  TAG=test ;;
            *)     TAG= ;;
          esac
          echo "deploy_env=${ENV}" >> "${GITHUB_ENV}"
          echo "image_tag=${TAG}" >> "${GITHUB_ENV}"
          echo "deploy_env=${ENV}" >> "${GITHUB_OUTPUT}"
          echo "image_tag=${TAG}" >> "${GITHUB_OUTPUT}"
          echo "Środowisko: ${ENV} (tag obrazu: ${TAG:-brak — tylko build})"

      - name: Checkout
        env:
          SERVER_URL: ${{ gitea.server_url }}
          GIT_TOKEN: ${{ gitea.token }}
          REPO: ${{ gitea.repository }}
          SHA: ${{ gitea.sha }}
        run: |
          set -euo pipefail
          AUTH="Authorization: token ${GIT_TOKEN}"
          git -c "http.extraHeader=${AUTH}" clone --depth=1 "${SERVER_URL}/${REPO}.git" .
          git -c "http.extraHeader=${AUTH}" fetch --depth=1 origin "${SHA}"
          git checkout FETCH_HEAD

      - name: Login to Gitea registry
        if: gitea.event_name != 'pull_request' && env.image_tag != ''
        env:
          VAR_REGISTRY_TOKEN: ${{ vars.REGISTRY_TOKEN }}
          SEC_REGISTRY_TOKEN: ${{ secrets.REGISTRY_TOKEN }}
        run: |
          set -euo pipefail
          REGISTRY_TOKEN="${VAR_REGISTRY_TOKEN:-${SEC_REGISTRY_TOKEN:-}}"
          if [ -z "${REGISTRY_TOKEN}" ]; then
            echo "Brak REGISTRY_TOKEN (Variable lub Secret) w Gitea."
            exit 1
          fi
          echo "${REGISTRY_TOKEN}" | docker login "${REGISTRY_HOST}" \
            -u "${{ gitea.repository_owner }}" --password-stdin

      - name: Build image
        env:
          BUILD_SHA: ${{ gitea.sha }}
        run: |
          set -euo pipefail
          IMAGE="${REGISTRY_HOST}/mlotocki/ksef_monitor"
          export DOCKER_BUILDKIT=1
          CACHE_FROM=()
          if [ -n "${image_tag:-}" ]; then
            if docker pull "${IMAGE}:${image_tag}"; then
              CACHE_FROM=(--cache-from "${IMAGE}:${image_tag}")
            fi
          fi
          docker build \
            "${CACHE_FROM[@]}" \
            --build-arg BUILDKIT_INLINE_CACHE=1 \
            --build-arg BUILD_SHA="${BUILD_SHA}" \
            -t "ksef_monitor:${BUILD_SHA}" \
            -t "${IMAGE}:${BUILD_SHA}" \
            .
          if [ -n "${image_tag:-}" ]; then
            docker tag "${IMAGE}:${BUILD_SHA}" "${IMAGE}:${image_tag}"
          fi

      - name: Push image
        if: gitea.event_name != 'pull_request' && env.image_tag != ''
        env:
          BUILD_SHA: ${{ gitea.sha }}
        run: |
          set -euo pipefail
          IMAGE="${REGISTRY_HOST}/mlotocki/ksef_monitor"
          docker push "${IMAGE}:${BUILD_SHA}"
          docker push "${IMAGE}:${image_tag}"

  deploy-test:
    runs-on: ubuntu-latest
    needs: build
    if: needs.build.outputs.deploy_env == 'test' && gitea.event_name != 'pull_request'
    timeout-minutes: 15
    env:
      REGISTRY_HOST: gitea.krzewiny.net:3033
      MKSEF_TAG: test
    steps:
      - name: Checkout
        env:
          SERVER_URL: ${{ gitea.server_url }}
          GIT_TOKEN: ${{ gitea.token }}
          REPO: ${{ gitea.repository }}
          SHA: ${{ gitea.sha }}
        run: |
          set -euo pipefail
          AUTH="Authorization: token ${GIT_TOKEN}"
          git -c "http.extraHeader=${AUTH}" clone --depth=1 "${SERVER_URL}/${REPO}.git" .
          git -c "http.extraHeader=${AUTH}" fetch --depth=1 origin "${SHA}"
          git checkout FETCH_HEAD

      - name: Deploy to test host
        env:
          DEPLOY_ENV: test
          GITEA_REPOSITORY: ${{ gitea.repository }}
          SEC_DEPLOY_TEST_SSH_KEY: ${{ secrets.DEPLOY_TEST_SSH_KEY }}
          SEC_DEPLOY_SSH_KEY: ${{ secrets.DEPLOY_SSH_KEY }}
          VAR_DEPLOY_TEST_HOST: ${{ vars.DEPLOY_TEST_HOST }}
          VAR_DEPLOY_HOST: ${{ vars.DEPLOY_HOST }}
          VAR_DEPLOY_TEST_USER: ${{ vars.DEPLOY_TEST_USER }}
          VAR_DEPLOY_USER: ${{ vars.DEPLOY_USER }}
          VAR_DEPLOY_TEST_PATH: ${{ vars.DEPLOY_TEST_PATH }}
          VAR_DEPLOY_PATH: ${{ vars.DEPLOY_PATH }}
          VAR_DEPLOY_TEST_SSH_PORT: ${{ vars.DEPLOY_TEST_SSH_PORT }}
          VAR_DEPLOY_SSH_PORT: ${{ vars.DEPLOY_SSH_PORT }}
          VAR_REGISTRY_TOKEN: ${{ vars.REGISTRY_TOKEN }}
          SEC_REGISTRY_TOKEN: ${{ secrets.REGISTRY_TOKEN }}
        run: |
          set -euo pipefail
          source deploy/gitea-ci/resolve-deploy-config.sh || { [ "$?" -eq 2 ] && exit 0; exit "$?"; }
          echo "SSH: ${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_SSH_PORT}"
          install -m 700 -d ~/.ssh
          printf '%s\n' "${DEPLOY_SSH_KEY}" > ~/.ssh/deploy_key
          chmod 600 ~/.ssh/deploy_key
          ssh-keyscan -p "${DEPLOY_SSH_PORT}" -H "${DEPLOY_HOST}" >> ~/.ssh/known_hosts 2>/dev/null || true
          REGISTRY_USER="${{ gitea.repository_owner }}"
          ssh -p "${DEPLOY_SSH_PORT}" -i ~/.ssh/deploy_key -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
            "${DEPLOY_USER}@${DEPLOY_HOST}" \
            "REGISTRY_HOST='${REGISTRY_HOST}' REGISTRY_USER='${REGISTRY_USER}' REGISTRY_TOKEN='${REGISTRY_TOKEN}' DEPLOY_PATH='${DEPLOY_PATH}' MKSEF_TAG='${MKSEF_TAG}' bash -s" \
            < deploy/synology/remote-deploy.sh

  deploy-prod:
    runs-on: ubuntu-latest
    needs: build
    if: needs.build.outputs.deploy_env == 'prod' && gitea.event_name != 'pull_request'
    timeout-minutes: 15
    env:
      REGISTRY_HOST: gitea.krzewiny.net:3033
      MKSEF_TAG: latest
    steps:
      - name: Checkout
        env:
          SERVER_URL: ${{ gitea.server_url }}
          GIT_TOKEN: ${{ gitea.token }}
          REPO: ${{ gitea.repository }}
          SHA: ${{ gitea.sha }}
        run: |
          set -euo pipefail
          AUTH="Authorization: token ${GIT_TOKEN}"
          git -c "http.extraHeader=${AUTH}" clone --depth=1 "${SERVER_URL}/${REPO}.git" .
          git -c "http.extraHeader=${AUTH}" fetch --depth=1 origin "${SHA}"
          git checkout FETCH_HEAD

      - name: Deploy to prod host
        env:
          DEPLOY_ENV: prod
          GITEA_REPOSITORY: ${{ gitea.repository }}
          SEC_DEPLOY_PROD_SSH_KEY: ${{ secrets.DEPLOY_PROD_SSH_KEY }}
          SEC_DEPLOY_SSH_KEY: ${{ secrets.DEPLOY_SSH_KEY }}
          VAR_DEPLOY_PROD_HOST: ${{ vars.DEPLOY_PROD_HOST }}
          VAR_DEPLOY_PROD_USER: ${{ vars.DEPLOY_PROD_USER }}
          VAR_DEPLOY_USER: ${{ vars.DEPLOY_USER }}
          VAR_DEPLOY_PROD_PATH: ${{ vars.DEPLOY_PROD_PATH }}
          VAR_DEPLOY_PATH: ${{ vars.DEPLOY_PATH }}
          VAR_DEPLOY_PROD_SSH_PORT: ${{ vars.DEPLOY_PROD_SSH_PORT }}
          VAR_DEPLOY_SSH_PORT: ${{ vars.DEPLOY_SSH_PORT }}
          VAR_REGISTRY_TOKEN: ${{ vars.REGISTRY_TOKEN }}
          SEC_REGISTRY_TOKEN: ${{ secrets.REGISTRY_TOKEN }}
        run: |
          set -euo pipefail
          source deploy/gitea-ci/resolve-deploy-config.sh || { [ "$?" -eq 2 ] && exit 0; exit "$?"; }
          echo "SSH: ${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_SSH_PORT}"
          install -m 700 -d ~/.ssh
          printf '%s\n' "${DEPLOY_SSH_KEY}" > ~/.ssh/deploy_key
          chmod 600 ~/.ssh/deploy_key
          ssh-keyscan -p "${DEPLOY_SSH_PORT}" -H "${DEPLOY_HOST}" >> ~/.ssh/known_hosts 2>/dev/null || true
          REGISTRY_USER="${{ gitea.repository_owner }}"
          ssh -p "${DEPLOY_SSH_PORT}" -i ~/.ssh/deploy_key -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
            "${DEPLOY_USER}@${DEPLOY_HOST}" \
            "REGISTRY_HOST='${REGISTRY_HOST}' REGISTRY_USER='${REGISTRY_USER}' REGISTRY_TOKEN='${REGISTRY_TOKEN}' DEPLOY_PATH='${DEPLOY_PATH}' MKSEF_TAG='${MKSEF_TAG}' bash -s" \
            < deploy/synology/remote-deploy.sh
```

- [ ] **Step 2: Walidacja YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.gitea/workflows/docker-build.yml')); print('YAML OK')"`
Expected: `YAML OK`

- [ ] **Step 3: NIE commituj jeszcze — patrz Task 7**

Commit tego pliku odpala pierwszy realny deploy. Zostaje wykonany dopiero w Task 7 (po ustawieniu Gitea config i edycji host compose w Task 6). Na razie plik istnieje lokalnie, niecommitowany.

---

### Task 5: README (gitea-ci + synology)

Dokumentacja operacyjna. Dwa pliki: mapowanie Variables/Secrets + setup hostów.

**Files:**
- Create: `deploy/gitea-ci/README.md`
- Create: `deploy/synology/README.md`

- [ ] **Step 1: Utwórz `deploy/gitea-ci/README.md`**

```markdown
# Gitea Actions — build Docker + deploy (test / prod)

## Flow

| Trigger | Build tag | Deploy |
|---------|-----------|--------|
| push `test` | `:test` + `:sha` | host `DEPLOY_TEST_*` (test.krzewiny.net) |
| push `main` | `:latest` + `:sha` | host `DEPLOY_PROD_*` (docker.krzewiny.net) |
| pull request | lokalny build | brak push/deploy |
| Run workflow (ręcznie) | wg wyboru test/prod | wg wyboru |

## Precedence `.gitea` vs `.github`

Gitea czyta workflow z pierwszego istniejącego katalogu `[.gitea/workflows, .github/workflows]`.
Obecność `.gitea/workflows` **wyłącza** wykonywanie `.github/workflows` na Gitei
(GitHub mirror dalej je wykonuje). To celowe: skany/testy zostają na GitHubie,
Gitea robi tylko build+deploy.

## Konfiguracja — repo-level (KSeF_Monitor → Settings → Actions)

Ustawiamy na poziomie **repo** (user-level zajęty przez inny projekt).

**Secrets** (Settings → Actions → Secrets):

| Nazwa | Wartość |
|-------|---------|
| `DEPLOY_TEST_SSH_KEY` | klucz prywatny `cdeploy_test` (cały plik OpenSSH) |
| `DEPLOY_PROD_SSH_KEY` | klucz prywatny `cdeploy_docker` |
| `REGISTRY_TOKEN` | token Gitea z prawem push/pull rejestru (może być też Variable) |

**Variables** (Settings → Actions → Variables):

| Nazwa | Wartość |
|-------|---------|
| `DEPLOY_USER` | `cdeploy` |
| `DEPLOY_TEST_HOST` | `test.krzewiny.net` |
| `DEPLOY_PROD_HOST` | `docker.krzewiny.net` |
| `DEPLOY_TEST_SSH_PORT` | `223` |
| `DEPLOY_PROD_SSH_PORT` | `223` |
| `DEPLOY_TEST_PATH` | `/volume1/docker/monitor_ksef` |
| `DEPLOY_PROD_PATH` | `/volume1/docker/ksef_monitor` |

Brak wymaganej wartości → `resolve-deploy-config.sh` kończy `exit 2` → workflow
**pomija deploy** (job zielony, deploy nie wykonany). W logu joba szukaj linii
`SSH: user@host:port` i `Ścieżka deploy:`.

## Port SSH — Variable, nie w hoście

Nie wpisuj portu w `DEPLOY_*_HOST`. Port to osobna Variable (`223`).
```

- [ ] **Step 2: Utwórz `deploy/synology/README.md`**

```markdown
# Deploy na Synology (test.krzewiny.net / docker.krzewiny.net)

CI (Gitea Actions) buduje obraz, pushuje do rejestru Gitea, potem przez SSH
na hoście robi `docker compose pull` + `up -d` serwisu `ksef_monitor`.

## Layout hosta (istniejący, zweryfikowany)

| | test | prod |
|--|------|------|
| dir | `/volume1/docker/monitor_ksef` | `/volume1/docker/ksef_monitor` |
| tag | `test` | `latest` |
| user SSH | `cdeploy` (klucz `cdeploy_test`) | `cdeploy` (klucz `cdeploy_docker`) |

Oba: `compose.yaml` + `config.json` (sekrety KSeF) + `data/` (bind). Deploy NIE
rusza `config.json` ani `data/`.

## Jednorazowa zmiana host compose (opcja A)

W `compose.yaml` na **obu** hostach podmień linię `image:` na obraz z rejestru Gitea
i dodaj `pull_policy: always`:

```yaml
services:
  ksef_monitor:
    image: ${MKSEF_IMAGE:-gitea.krzewiny.net:3033/mlotocki/ksef_monitor}:${MKSEF_TAG:-test}
    container_name: ksef-monitor
    pull_policy: always
    #restart: unless-stopped
    ports:
      - "8999:8000"
      - "8888:8080"
    volumes:
      - ./config.json:/data/config.json:ro
      - ./data:/data
```

(Na prod domyślny `MKSEF_TAG` bez znaczenia — CI przekazuje `latest`.)
Referencyjny szablon: `deploy/synology/compose.yaml`.

## Rejestr

Oba hosty są już zalogowane do `gitea.krzewiny.net:3033` (`~/.docker/config.json`).
CI i tak loguje się ponownie tokenem `REGISTRY_TOKEN` przed pullem.

## Test ręczny SSH (jak CI, bez login shell)

```bash
ssh -p 223 -i ~/.ssh/cdeploy_test  cdeploy@test.krzewiny.net   'export PATH=/usr/local/bin:$PATH; docker ps'
ssh -p 223 -i ~/.ssh/cdeploy_docker cdeploy@docker.krzewiny.net 'export PATH=/usr/local/bin:$PATH; docker ps'
```
```

- [ ] **Step 3: Commit**

```bash
git add deploy/gitea-ci/README.md deploy/synology/README.md
git commit -m "docs(ci): document gitea deploy vars/secrets + host setup"
```

---

### Task 6: Konfiguracja Gitea + edycja host compose (RĘCZNE, user)

Kroki po stronie Gitea i hostów. Nie tworzą commitów w repo. **Wykonuje user** (dostęp admin repo + SSH). Muszą być gotowe PRZED Task 7, inaczej pierwszy deploy się pominie (`exit 2`).

**Files:** brak (konfiguracja zewnętrzna)

- [ ] **Step 1: Ustaw Gitea Secrets** (repo `KSeF_Monitor` → Settings → Actions → Secrets)

Dodaj: `DEPLOY_TEST_SSH_KEY` (zawartość `~/.ssh/cdeploy_test`), `DEPLOY_PROD_SSH_KEY` (zawartość `~/.ssh/cdeploy_docker`), `REGISTRY_TOKEN`.

- [ ] **Step 2: Ustaw Gitea Variables** (Settings → Actions → Variables)

`DEPLOY_USER=cdeploy`, `DEPLOY_TEST_HOST=test.krzewiny.net`, `DEPLOY_PROD_HOST=docker.krzewiny.net`, `DEPLOY_TEST_SSH_PORT=223`, `DEPLOY_PROD_SSH_PORT=223`, `DEPLOY_TEST_PATH=/volume1/docker/monitor_ksef`, `DEPLOY_PROD_PATH=/volume1/docker/ksef_monitor`.

- [ ] **Step 3: Edytuj compose na hoście TEST**

Run (podmień `image:` + dodaj `pull_policy` wg `deploy/synology/README.md`):
```bash
ssh -p 223 -i ~/.ssh/cdeploy_test cdeploy@test.krzewiny.net 'cat /volume1/docker/monitor_ksef/compose.yaml'
# edytuj plik (vi/nano na hoście lub scp), zweryfikuj:
ssh -p 223 -i ~/.ssh/cdeploy_test cdeploy@test.krzewiny.net 'export PATH=/usr/local/bin:$PATH; cd /volume1/docker/monitor_ksef && MKSEF_TAG=test docker compose config | grep image'
```
Expected: `image: gitea.krzewiny.net:3033/mlotocki/ksef_monitor:test`

- [ ] **Step 4: Edytuj compose na hoście PROD** (analogicznie, dir `/volume1/docker/ksef_monitor`)

Run:
```bash
ssh -p 223 -i ~/.ssh/cdeploy_docker cdeploy@docker.krzewiny.net 'export PATH=/usr/local/bin:$PATH; cd /volume1/docker/ksef_monitor && MKSEF_TAG=latest docker compose config | grep image'
```
Expected: `image: gitea.krzewiny.net:3033/mlotocki/ksef_monitor:latest`

---

### Task 7: Pierwszy deploy na test + weryfikacja (guarded)

Commit workflow (Task 4) i push na `test` → pierwszy realny build+deploy. **To także moment wyłączenia floodu `.github`** (od teraz Gitea czyta tylko `.gitea`). Backlog z incydentu (jeśli jeszcze wisi) user czyści ręcznie w UI PRZED tym pushem.

**Files:**
- Commit: `.gitea/workflows/docker-build.yml` (utworzony w Task 4)

- [ ] **Step 1: Upewnij się że jesteś na branchu `test`**

Run: `git branch --show-current`
Expected: `test`

- [ ] **Step 2: Commit workflow**

```bash
git add .gitea/workflows/docker-build.yml
git commit -m "feat(ci): add gitea build+deploy workflow (suppresses .github on gitea)"
```

- [ ] **Step 3: Push na test**

Run: `git push origin test`
Expected: push OK

- [ ] **Step 4: Obserwuj run w Gitea** (UI: repo → Actions, lub API)

Sprawdź że pojawił się TYLKO run `Build, Push & Deploy` (job `build` + `deploy-test`), a NIE `test (3.x)`/`security`/podwójny `build` z `.github`.
Run (API, status ostatnich):
```bash
TOKEN=$(printf 'protocol=https\nhost=gitea.krzewiny.net\n\n' | git credential fill | sed -n 's/^password=//p')
curl -s -u "mlotocki:$TOKEN" "https://gitea.krzewiny.net:3033/api/v1/repos/mlotocki/KSeF_Monitor/actions/tasks?limit=5" | python3 -c "import sys,json;[print(r['name'],r['status'],r.get('conclusion')) for r in json.load(sys.stdin)['workflow_runs']]"
```
Expected: nazwy `Build, Push & Deploy`, status `success` (build + deploy-test)

- [ ] **Step 5: Weryfikuj kontener na test hoście**

Run:
```bash
ssh -p 223 -i ~/.ssh/cdeploy_test cdeploy@test.krzewiny.net 'export PATH=/usr/local/bin:$PATH; docker ps --filter name=ksef-monitor --format "{{.Names}} {{.Image}} {{.Status}}"'
```
Expected: `ksef-monitor gitea.krzewiny.net:3033/mlotocki/ksef_monitor:test Up ...`

- [ ] **Step 6: Weryfikuj obraz w rejestrze Gitea** (opcjonalnie, przez UI Packages)

Sprawdź w Gitea → user `mlotocki` → Packages → `ksef_monitor` że jest tag `test` + `sha-…`.

---

### Task 8: Promocja na prod (main) — po zaakceptowaniu testu

Po weryfikacji test i decyzji release (gating), merge `test` → `main` odpala deploy prod.

**Files:** brak nowych (workflow już na `test`, trafi na `main` z mergem)

- [ ] **Step 1: Potwierdź że test działa** (Task 7 zielony, kontener test `Up`)

- [ ] **Step 2: Merge test → main**

```bash
git checkout main
git merge --no-ff test -m "chore: merge test — enable gitea CI/CD"
git push origin main
```

- [ ] **Step 3: Obserwuj deploy-prod**

Run:
```bash
TOKEN=$(printf 'protocol=https\nhost=gitea.krzewiny.net\n\n' | git credential fill | sed -n 's/^password=//p')
curl -s -u "mlotocki:$TOKEN" "https://gitea.krzewiny.net:3033/api/v1/repos/mlotocki/KSeF_Monitor/actions/tasks?limit=5" | python3 -c "import sys,json;[print(r['name'],r['head_branch'],r['status'],r.get('conclusion')) for r in json.load(sys.stdin)['workflow_runs']]"
```
Expected: run na `head=main`, job `build` + `deploy-prod` = `success`

- [ ] **Step 4: Weryfikuj kontener prod**

Run:
```bash
ssh -p 223 -i ~/.ssh/cdeploy_docker cdeploy@docker.krzewiny.net 'export PATH=/usr/local/bin:$PATH; docker ps --filter name=ksef-monitor --format "{{.Names}} {{.Image}} {{.Status}}"'
```
Expected: `ksef-monitor gitea.krzewiny.net:3033/mlotocki/ksef_monitor:latest Up (healthy)`

- [ ] **Step 5: Checkout z powrotem na test** (branch roboczy)

Run: `git checkout test`

---

## Self-Review

**Spec coverage:**
- Rejestr Gitea lowercase → Task 4 (`IMAGE=…/mlotocki/ksef_monitor`), Task 3 (image ref). ✓
- Branch test/main → env/tag → Task 4 `Resolve environment`. ✓
- Serwis `ksef_monitor` / kontener `ksef-monitor` → Task 2, 3. ✓
- Wolumeny bind config `/data/config.json` + `./data` → Task 3. ✓
- Porty 8999/8888, restart zakomentowany, brak healthcheck → Task 3. ✓
- Per-env klucze/host/path → Task 4 (env bloki) + Task 6 (Gitea config). ✓
- `.github` bez zmian + precedence fix → Task 4 opis, Task 7 Step 4 weryfikacja. ✓
- resolve-deploy-config.sh reuse → Task 1. ✓
- remote-deploy.sh → Task 2. ✓
- Kolejność (config przed push) → Task 6 przed Task 7. ✓
- `exit 2` skip przy braku config → Task 1 Step 3, Task 5 README. ✓

**Placeholder scan:** brak TBD/TODO; wszystkie pliki mają pełną treść; komendy z expected output. ✓

**Type/nazwy consistency:** serwis `ksef_monitor`, kontener `ksef-monitor`, zmienne `MKSEF_TAG`/`MKSEF_IMAGE`, `DEPLOY_*` spójne między Task 1/2/4/6. Image ref identyczny w Task 2/3/4. ✓
