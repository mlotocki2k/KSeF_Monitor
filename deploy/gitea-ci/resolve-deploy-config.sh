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
