"""Render every app mockup screen: the full matrix at 1x, the atlas screen of every scheme and every screen of each
direction's default scheme at 2x. PNG captures go to a temp folder and are converted to WebP in renders/<design>/.
Usage: render_all.py [design ...]"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "renders"
SCHEMES = json.loads((ROOT / "system/schemes.json").read_text())
DEFAULT = {"overlay": "graphite", "specimen": "slate", "plate": "bristol"}
SCREENS = "atlas,peel,lesson,lessons,models,radiology,practice,histology,settings"


def capture(tmp, design, schemes, screens, scale):
    cmd = ["node", str(HERE / "render_mockups.mjs"), str(tmp), design, schemes, screens, str(scale)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    errs = sorted({l for l in r.stderr.splitlines() if "PAGEERROR" in l})
    if errs:
        print("\n".join(errs))
    return r.returncode


def convert(tmp, design, suffix, quality):
    dest = OUT / design
    dest.mkdir(parents=True, exist_ok=True)
    for png in sorted(Path(tmp).glob(f"{design}_*.png")):
        out = dest / (png.stem + suffix + ".webp")
        Image.open(png).convert("RGB").save(out, quality=quality, method=5)
        png.unlink()


for design in (sys.argv[1:] or ["overlay", "specimen", "plate"]):
    with tempfile.TemporaryDirectory() as tmp:
        capture(tmp, design, "all", SCREENS, 1)
        convert(tmp, design, "", 86)
        capture(tmp, design, "all", "atlas", 2)
        convert(tmp, design, "@2x", 88)
        capture(tmp, design, DEFAULT[design], SCREENS, 2)
        convert(tmp, design, "@2x", 88)
    print(design, len(list((OUT / design).glob("*.webp"))), "renders")
