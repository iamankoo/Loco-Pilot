#!/usr/bin/env bash
# Starts the FastAPI app with auto-reload, reading host/port from .env.
set -euo pipefail
cd "$(dirname "$0")/../.."

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"

uvicorn backend.app.main:app --reload --host "$API_HOST" --port "$API_PORT"
