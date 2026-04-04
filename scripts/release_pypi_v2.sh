#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
PUBLISH="${PUBLISH:-0}"
TEST_PYPI="${TEST_PYPI:-0}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python executable not found: $PYTHON_BIN" >&2
  exit 1
fi

echo "Using Python: $PYTHON_BIN"
"$PYTHON_BIN" -V

echo "Cleaning old artifacts"
rm -rf dist build *.egg-info src/*.egg-info

echo "Building distributions"
"$PYTHON_BIN" -m build

echo "Running Twine checks"
"$PYTHON_BIN" -m twine check dist/*

if [[ "$PUBLISH" != "1" ]]; then
  echo "Build complete. Set PUBLISH=1 to upload."
  exit 0
fi

if [[ -z "${SIOF_PYPI_TOKEN:-}" ]]; then
  echo "Missing SIOF_PYPI_TOKEN environment variable" >&2
  exit 1
fi

if [[ "$TEST_PYPI" == "1" ]]; then
  echo "Uploading to TestPyPI"
  "$PYTHON_BIN" -m twine upload \
    --repository-url https://test.pypi.org/legacy/ \
    -u __token__ \
    -p "$SIOF_PYPI_TOKEN" \
    dist/*
else
  echo "Uploading to PyPI"
  "$PYTHON_BIN" -m twine upload \
    -u __token__ \
    -p "$SIOF_PYPI_TOKEN" \
    dist/*
fi

echo "Release upload completed"
