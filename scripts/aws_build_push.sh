#!/usr/bin/env bash
set -euo pipefail
# Publishing is permitted only for the exact images that passed the paired gate.
# Build locally first; this entrypoint deliberately never rebuilds after testing.
uv run --frozen python scripts/release_cloud.py publish "$@"
