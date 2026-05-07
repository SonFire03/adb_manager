#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

RUFF_BIN="${ROOT_DIR}/.venv/bin/ruff"
BLACK_BIN="${ROOT_DIR}/.venv/bin/black"
PYTEST_BIN="${ROOT_DIR}/.venv/bin/pytest"

if [[ ! -x "$RUFF_BIN" ]]; then
  RUFF_BIN="ruff"
fi
if [[ ! -x "$BLACK_BIN" ]]; then
  BLACK_BIN="black"
fi
if [[ ! -x "$PYTEST_BIN" ]]; then
  PYTEST_BIN="pytest"
fi

echo "==> Ruff"
"$RUFF_BIN" check .

echo "==> Black"
"$BLACK_BIN" --check .

echo "==> Tests + Coverage"
"$PYTEST_BIN" -q --cov --cov-report=term-missing --cov-fail-under=80

echo "==> Changelog/README sanity"
grep -q "## \\[Unreleased\\]" CHANGELOG.md
grep -q "Current stable release:" README.md

echo "Release checks passed."
