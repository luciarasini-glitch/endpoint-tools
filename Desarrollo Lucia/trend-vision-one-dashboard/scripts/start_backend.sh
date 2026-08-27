#!/usr/bin/env bash
set -euo pipefail

read_env_var() {
  local key="$1"
  local default_value="$2"
  local value=""

  if [[ -f .env ]]; then
    value="$(awk -F= -v k="$key" '$0 ~ ("^" k "=") {sub(/^[^=]*=/, "", $0); print $0; exit}' .env)"
    value="${value%$'\r'}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
  fi

  if [[ -n "$value" ]]; then
    printf "%s" "$value"
  else
    printf "%s" "$default_value"
  fi
}

BACKEND_HOST="${APP_BACKEND_HOST:-$(read_env_var APP_BACKEND_HOST 127.0.0.1)}"
BACKEND_PORT="${APP_BACKEND_PORT:-$(read_env_var APP_BACKEND_PORT 8000)}"
UVICORN_BIN="uvicorn"

if [[ -x .venv/bin/uvicorn ]]; then
  UVICORN_BIN=".venv/bin/uvicorn"
fi

exec "$UVICORN_BIN" app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload
