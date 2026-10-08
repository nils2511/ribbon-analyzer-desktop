#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
if [ ! -x "$APP_DIR/venv/bin/python" ]; then
    echo 'Run bash setup.sh first.' >&2
    exit 1
fi
cd "$APP_DIR"
exec "$APP_DIR/venv/bin/python" "$APP_DIR/ribbon_analyzer.py" "$@"
