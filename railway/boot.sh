#!/usr/bin/env bash
# Runs before engine.py — logs show in Railway even when Python is missing from PATH.
set -euo pipefail

log() {
  printf '%s\n' "[engine-boot] $*" >&2
}

log "time=$(date -Iseconds 2>/dev/null || date) pwd=$(pwd)"
log "PATH=$PATH"

for name in python3.12 python3.11 python3.10 python3 python; do
  if command -v "$name" >/dev/null 2>&1; then
    log "found: $name -> $(command -v "$name")"
    "$name" --version >&2 || true
  else
    log "missing: $name"
  fi
done

PYTHON_BIN="${PYTHON_BIN:-}"
for name in python3.12 python3.11 python3.10 python3 python; do
  if command -v "$name" >/dev/null 2>&1; then
    PYTHON_BIN=$(command -v "$name")
    break
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  log "FATAL: no python on PATH — Nixpacks likely did not install Python (add root requirements.txt / nixpacks python provider)."
  exit 127
fi

log "exec: PYTHONUNBUFFERED=1 $PYTHON_BIN railway/engine.py"
exec env PYTHONUNBUFFERED=1 "$PYTHON_BIN" railway/engine.py
