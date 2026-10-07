#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "Virtual environment python not found at ${VENV_PYTHON}."
    exit 1
fi

export PYTHONPATH="${PROJECT_ROOT}/src:${PYTHONPATH:-}"

echo "Executing Self-Healing Health Check..."
exec "${VENV_PYTHON}" -m self_healing.cli health "$@"
