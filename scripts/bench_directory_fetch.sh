#!/usr/bin/env bash
# Benchmark serial vs concurrent directory population (#20).
#
# Runs the full boards-directory refresh twice — once with the worker pool
# disabled (MONDO_DIR_FETCH_CONCURRENCY=1, the pre-#20 serial walk) and once
# with the default pool — and prints wall times. Read-only; requires
# MONDAY_API_TOKEN in the environment.
#
# Reference numbers (5,966-board account, 60 pages, 2026-06):
#   serial 65.0s | concurrent(4) 20.9s | warm cache hit 0.4s

set -euo pipefail

if [[ -z "${MONDAY_API_TOKEN:-}" ]]; then
    echo "error: set MONDAY_API_TOKEN first" >&2
    exit 1
fi

run() {
    local label=$1
    shift
    local start end
    start=$(python3 -c 'import time; print(time.time())')
    "$@" >/dev/null 2>&1
    end=$(python3 -c 'import time; print(time.time())')
    python3 -c "print(f'${label}: {${end}-${start}:.1f}s')"
}

cd "$(dirname "$0")/.."

run "serial refresh        " env MONDO_DIR_FETCH_CONCURRENCY=1 \
    uv run mondo board list --refresh-cache --fields id -o none
run "concurrent refresh (4)" \
    uv run mondo board list --refresh-cache --fields id -o none
run "warm cache hit        " \
    uv run mondo board list --fields id -o none
