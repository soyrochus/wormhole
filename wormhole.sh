#!/usr/bin/env bash

# Start the wormhole module using uv, ensuring project deps are installed.
# Usage:
#   ./wormhole.sh [args...]
#
# Notes:
# - Requires uv (https://docs.astral.sh/uv/). Install on macOS:
#     curl -LsSf https://astral.sh/uv/install.sh | sh
# - Respects env vars:
#     UV_SYNC=0   -> skip dependency sync (default is 1)
#     UV_ARGS     -> extra args passed to `uv run` (e.g., "--python 3.11")

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
	echo "Error: uv is not installed. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
	exit 1
fi

# Ensure dependencies are synced into a local virtual environment
if [[ "${UV_SYNC:-1}" == "1" ]]; then
	# Use existing lock if present; otherwise uv will resolve and create one
	uv sync --frozen || uv sync
fi

# Run the wormhole package as a module, forwarding all args
exec uv run ${UV_ARGS:-} -m wormhole "$@"

