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
