#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

VENV_PYTEST="${PROJECT_ROOT}/.venv/bin/pytest"

if [[ ! -x "${VENV_PYTEST}" ]]; then
    echo "pytest binary not found at ${VENV_PYTEST}."
    exit 1
fi

export PYTHONPATH="${PROJECT_ROOT}/src:${PYTHONPATH:-}"

echo "Running pytest test suite..."
exec "${VENV_PYTEST}" -v "$@"
