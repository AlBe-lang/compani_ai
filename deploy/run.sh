#!/usr/bin/env bash
set -euo pipefail

MODEL_NAME="${OLLAMA_MODEL:-llama3.1:70b}"
PYTHON_BIN="${PYTHON_BIN:-python}"

error() {
  echo "[ERROR] $1" >&2
  exit 1
}

echo "[INFO] checking Ollama CLI..."
if ! command -v ollama >/dev/null 2>&1; then
  error "Ollama is not installed. Install Ollama and retry."
fi

echo "[INFO] checking Ollama daemon..."
if ! ollama list >/dev/null 2>&1; then
  error "Ollama daemon is not reachable. Start Ollama before running this script."
fi

echo "[INFO] checking model: ${MODEL_NAME}"
if ! ollama show "${MODEL_NAME}" >/dev/null 2>&1; then
  echo "[INFO] model not found locally. pulling ${MODEL_NAME}..."
  ollama pull "${MODEL_NAME}"
fi

echo "[INFO] starting application..."
PYTHONPATH="${PYTHONPATH:-}:$(pwd)/src" "${PYTHON_BIN}" main.py
