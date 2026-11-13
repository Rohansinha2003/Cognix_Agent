#!/usr/bin/env bash
# Start Cognix. The first run creates a virtual environment and installs dependencies.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  PY="$(command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3)"
  if ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "Cognix needs Python 3.10 or newer (found: $("$PY" --version)). Try: brew install python@3.12" >&2
    exit 1
  fi
  echo "Setting up Cognix (first run only)…"
  "$PY" -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

exec .venv/bin/python -m cognix "$@"
