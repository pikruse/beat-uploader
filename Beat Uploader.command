#!/bin/zsh
# Double-clickable fallback launcher — opens in Terminal (always has
# file access), starts the Beat Uploader web GUI.
cd "$(dirname "$0")" || exit 1
PY="$HOME/miniconda3/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
exec "$PY" gui.py
