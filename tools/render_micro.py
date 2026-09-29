"""Render a microanatomy model offscreen with the app's own model viewer renderer.

Kept for the command line it has always had; tools/render_model.py does the work and renders any model in the
catalogue (the in-house GLB models, the procedural microanatomy models and the downloaded models) or any .glb file.

Usage: python tools/render_micro.py <model_id> [-o out.png] [--yaw 40] [--pitch 25] [--zoom 1] [--size 900]
       [--no-cut | --cut] [--explode 0] [--hide substr,...] [--only substr,...] [--focus substr,...]
       [--time T] [--frames N [--slow S]]

<model_id> can also be a downloaded model: sketchfab:<uid>, or just the first characters of its uid.
See tools/render_model.py for the other options (--view, --state, --section).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from render_model import main  # noqa: E402

if __name__ == "__main__":
    main(default_prefix="app")
