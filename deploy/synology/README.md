# Deploy na Synology (CI via ci-templates)

CI = reusable workflow `mlotocki/ci-templates/.gitea/workflows/docker-synology.yml@v0.18.0`,
wołany z `.gitea/workflows/ci.yml`. Build → push do rejestru Gitea → deploy przez SSH.
Skrypty deploy (`resolve-deploy-config.sh`, `remote-deploy.sh`) należą do ci-templates
(`templates_ref: v0.18.0`) — **nie** kopiujemy ich do tego repo.

## Flow

| Trigger | Tag | Deploy |
|---------|-----|--------|
| push `test` | `:test` + `:sha` | test.krzewiny.net (`DEPLOY_TEST_*`) |
| push `main` | `:latest` + `:sha` | docker.krzewiny.net (`DEPLOY_PROD_*`) |
| pull request | build only | brak |
| workflow_dispatch | wybór test/prod | wybór |

Template obsługuje branch `test` (obok `develop`) → env `test`.

## Layout hosta (istniejący, zweryfikowany)

| | test | prod |
|--|------|------|
| dir | `/volume1/docker/monitor_ksef` | `/volume1/docker/ksef_monitor` |
| tag | `test` | `latest` |
| user SSH | `cdeploy` (klucz `cdeploy_test`) | `cdeploy` (klucz `cdeploy_docker`) |

Oba: `compose.yaml` + `config.json` (sekrety KSeF) + `data/` (bind). Deploy NIE
rusza `config.json` ani `data/`.

## Gitea — konfiguracja (repo `KSeF_Monitor` → Settings → Actions)

Repo-level (user-level zajęty przez inny projekt). Do template przez `secrets: inherit`.

**Secrets:** `DEPLOY_TEST_SSH_KEY` (klucz `cdeploy_test`), `DEPLOY_PROD_SSH_KEY` (klucz
`cdeploy_docker`), `REGISTRY_TOKEN` — **jako Secret** (maskowany w logach; Variable NIE jest).

**Variables:** `DEPLOY_USER=cdeploy`, `DEPLOY_TEST_HOST=test.krzewiny.net`,
`DEPLOY_PROD_HOST=docker.krzewiny.net`, `DEPLOY_TEST_SSH_PORT=223`, `DEPLOY_PROD_SSH_PORT=223`,
`DEPLOY_TEST_PATH=/volume1/docker/monitor_ksef`, `DEPLOY_PROD_PATH=/volume1/docker/ksef_monitor`.

Brak wymaganej wartości → deploy job **czerwony** z `Brak <NAZWA>: ustaw w…` (świadomie —
głośny sygnał zamiast cichego skipu).

## compose_src + jednorazowa zmiana host compose (opcja A)

Template czyta `deploy/synology/compose.yaml` (`compose_src`) i **bootstrapuje** na host tylko
gdy tam brak (nie nadpisuje). Tag obrazu przez env `MKSEF_TAG` (`tag_env`).

Hosty mają już `compose.yaml` wskazujący GHCR — bootstrap go NIE nadpisze. Na **obu** hostach
podmień linię `image:` na obraz z rejestru Gitea i dodaj `pull_policy: always`:

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

## Uwaga bezpieczeństwa (znane, fix upstream)

`docker-synology.yml@v0.18.0` przekazuje `REGISTRY_TOKEN` w argv `ssh` — narusza regułę
„sekret NIGDY w argv". Ryzyko niskie (single-tenant runner + admin NAS). Fix należy do repo
`ci-templates` (→ v0.19.0), potem bump `@v0.19.0` tutaj.
