#!/usr/bin/env bash
set -euo pipefail
trap 'echo "[ERROR] setup failed at line ${LINENO}: ${BASH_COMMAND}" >&2' ERR

PYTHON_BIN="${PYTHON_BIN:-python}"

echo "[INFO] checking python version..."
"${PYTHON_BIN}" - <<'PY'
import sys

if sys.version_info < (3, 11):
    raise SystemExit("[ERROR] Python 3.11+ is required.")
print(f"[INFO] Python version OK: {sys.version.split()[0]}")
PY

if [ ! -d ".venv" ]; then
  echo "[INFO] creating virtual environment..."
  "${PYTHON_BIN}" -m venv .venv
fi

if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
elif [ -f ".venv/Scripts/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/Scripts/activate
else
  echo "[ERROR] virtualenv activation script not found."
  exit 1
fi

echo "[INFO] upgrading pip..."
python -m pip install --upgrade pip

echo "[INFO] installing requirements..."
python -m pip install -r requirements.txt -r requirements-dev.txt

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp .env.example .env
  echo "[INFO] .env created from .env.example"
fi

echo "[INFO] setup completed."
