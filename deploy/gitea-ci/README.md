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
