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
