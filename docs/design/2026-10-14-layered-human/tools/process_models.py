"""Copy model-viewer plates (already matted by render_models.py) into the design assets as WebP, with their anchors."""
import json
import shutil
import sys
from pathlib import Path
from PIL import Image

SRC, ASSETS = Path(sys.argv[1]), Path(sys.argv[2])
for png in sorted(SRC.glob("*.png")):
    out = ASSETS / f"{png.stem}.webp"
    if out.exists() and out.stat().st_mtime > png.stat().st_mtime:
        continue
    im = Image.open(png)
    if png.stem.startswith("thumb_") or png.stem in ("cardiac_muscle",):
        im.thumbnail((900, 900))
    im.save(out, quality=90, method=5)
    print(png.stem, im.size)
for a in SRC.glob("*.anchors.json"):
    shutil.copy(a, ASSETS / a.name)
