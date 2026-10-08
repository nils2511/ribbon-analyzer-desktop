#!/usr/bin/env bash
# Install locally without storing API keys or changing shell configuration.
set -euo pipefail
APP_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$APP_DIR"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10+ required")'
if ! python3 -c 'import tkinter' 2>/dev/null; then
    echo 'Tkinter is required. Use a Python distribution with Tcl/Tk support.'
    echo 'On Debian/Ubuntu: sudo apt install python3-tk python3-venv'
    exit 1
fi
if [ ! -d venv ]; then
    python3 -m venv venv
fi
"$APP_DIR/venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
echo 'Setup complete. Run: bash start.sh'
echo 'Manual annotation works locally without an API key.'
