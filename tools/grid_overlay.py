"""Overlay a labelled 0.05 grid on a radiology image, so label coordinates can be read off by eye."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "radiology" / "images"
OUT = ROOT / "logs" / "grid"
OUT.mkdir(parents=True, exist_ok=True)

for name in sys.argv[1:] or [p.stem for p in sorted(SRC.glob("*"))]:
    path = next(SRC.glob(name + ".*"))
    im = Image.open(path).convert("RGB")
    target = 900
    scale = target / max(im.size)
    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
    d = ImageDraw.Draw(im, "RGBA")
    w, h = im.size
    for i in range(1, 20):
        f = i / 20
        major = i % 2 == 0
        col = (255, 90, 90, 200) if major else (90, 200, 255, 90)
        d.line([(f * w, 0), (f * w, h)], fill=col, width=2 if major else 1)
        d.line([(0, f * h), (w, f * h)], fill=col, width=2 if major else 1)
        if major:
            d.text((f * w + 3, 3), f"{f:.1f}", fill=(255, 220, 120, 255))
            d.text((3, f * h + 2), f"{f:.1f}", fill=(255, 220, 120, 255))
    im.save(OUT / f"{name}.png")
    print(name, path.name, im.size)
