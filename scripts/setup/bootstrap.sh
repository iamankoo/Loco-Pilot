#!/usr/bin/env bash
# Bootstraps a local dev environment: venv, dependencies, .env file.
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ ! -d ".venv" ]; then
  python -m venv .venv
fi

if [ -f ".venv/Scripts/activate" ]; then
  source .venv/Scripts/activate
else
  source .venv/bin/activate
fi

pip install --upgrade pip
pip install -e ".[dev]"

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example — fill in real values (LLM_API_KEY, etc)."
fi

echo "Bootstrap complete. Activate with: source .venv/bin/activate (or .venv/Scripts/activate on Windows)"
