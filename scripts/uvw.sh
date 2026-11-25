#!/usr/bin/env bash
# uv with the project environment on the Linux file system, outside the slow /mnt/c mount.
# Usage from Windows: wsl -d Ubuntu-24.04 -- bash -c "cd /mnt/c/.../foretaksrisiko && scripts/uvw.sh run pytest"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/.venvs/foretaksrisiko}"
exec uv "$@"
