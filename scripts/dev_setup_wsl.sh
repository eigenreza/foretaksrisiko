#!/usr/bin/env bash
# Developer setup inside WSL Ubuntu: Python 3.12 through uv, project environment with the Spark
# and Databricks extras, then the test suite. Java 17 and uv must already be installed.
#
# The virtual environment is kept on the Linux file system, not under /mnt/c, because Spark and
# the JVM are slow on the Windows mount. The location is exported through UV_PROJECT_ENVIRONMENT.
set -euo pipefail

cd "$(dirname "$0")/.."

export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/.venvs/foretaksrisiko}"
if ! grep -q "UV_PROJECT_ENVIRONMENT" "$HOME/.bashrc" 2>/dev/null; then
  echo "export UV_PROJECT_ENVIRONMENT=\"$UV_PROJECT_ENVIRONMENT\"" >> "$HOME/.bashrc"
fi

java -version
uv --version
uv python install 3.12
uv sync --extra spark --extra databricks --extra ml --group dev
uv run ruff check .
uv run pytest
