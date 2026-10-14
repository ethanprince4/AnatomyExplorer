#!/bin/bash
# Capture atlas plates with the app's own renderer, headless.
#   tools/capture/capture.sh batch1        (batches are defined in make_script.py)
# Needs an X server (e.g. Xvfb :99 -screen 0 4096x2560x24 +extension GLX), Mesa, and a Python 3.12 venv with the app's
# requirements at .venv312. Raw captures go to $LH_RAW (default ~/lh-plates/raw). The app rewrites its depth and
# sample caches when it starts, so they are restored from git afterwards.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../../.." && pwd)"
cd "$REPO"
DISPLAY=${DISPLAY:-:99} LIBGL_ALWAYS_SOFTWARE=1 QT_QPA_PLATFORM=xcb \
  "${PYTHON:-.venv312/bin/python}" -u -X faulthandler "$HERE/run_app.py" --no-restore --script "$(python3 "$HERE/make_script.py" "$1")"
git checkout -- data/anatomy/depth.npz data/anatomy/samples.npz
