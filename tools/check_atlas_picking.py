"""Real atlas GPU/input probe; runnable on macOS/Retina and Windows.

    python tools/check_atlas_picking.py [--report path.json]

Set QT_SCALE_FACTOR=2 to exercise Retina-equivalent backing coordinates.
Reads only bundled atlas data; no saved settings/study data/caches are used.
Frozen builds expose this probe with --pick-diagnostics.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.picking_diagnostics import main

if __name__ == "__main__":
    raise SystemExit(main())
