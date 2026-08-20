#!/usr/bin/env bash
# Runs the test suite. Start docker-compose first for the full integration
# set (DB/Redis/LLM tests skip gracefully if their dependency is unavailable).
set -euo pipefail
cd "$(dirname "$0")/../.."

pytest "$@"
