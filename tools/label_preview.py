"""Draw a case's labels onto its image, so the positions can be checked by eye before the app is opened.

  python tools/label_preview.py                 # every case
  python tools/label_preview.py cxr_pa hand_pa  # just these

Writes logs/labels/<id>.png: the cropped image with a numbered dot per label and the legend beside it.
Also accepts a bare image id plus x,y pairs, to try positions out before writing them into the JSON:

  python tools/label_preview.py shoulder_ap 0.46,0.30 0.52,0.29
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.radiology import IMAGE_DIR, load_cases          # noqa: E402

OUT = ROOT / "logs" / "labels"
OUT.mkdir(parents=True, exist_ok=True)
TARGET = 820                    # height of the image panel
LEGEND = 430


def font(size):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(image_path, crop, labels, out_path):
    im = Image.open(image_path).convert("RGB")
    if crop:
        x0, y0, x1, y1 = crop
        im = im.crop((int(x0 * im.width), int(y0 * im.height), int(x1 * im.width), int(y1 * im.height)))
    scale = TARGET / im.height
    im = im.resize((max(1, int(im.width * scale)), TARGET), Image.LANCZOS)
    canvas = Image.new("RGB", (im.width + LEGEND, TARGET), (18, 20, 24))
    canvas.paste(im, (0, 0))
    d = ImageDraw.Draw(canvas, "RGBA")
    f_num, f_txt = font(13), font(14)
    for i, (lx, ly, text) in enumerate(labels, 1):
        x, y = lx * im.width, ly * TARGET
        d.ellipse([x - 11, y - 11, x + 11, y + 11], fill=(20, 110, 210, 225), outline=(255, 255, 255, 235))
        d.text((x, y), str(i), fill=(255, 255, 255), font=f_num, anchor="mm")
        d.line([(x + 12, y), (im.width + 8, 16 + (i - 1) * 20 + 8)], fill=(90, 150, 220, 70), width=1)
        d.text((im.width + 14, 16 + (i - 1) * 20), f"{i}. {text}", fill=(220, 228, 240), font=f_txt)
    canvas.save(out_path)
    print(out_path.relative_to(ROOT), canvas.size)


def main():
    args = sys.argv[1:]
    if len(args) >= 2 and "," in args[1]:
        stem = args[0]
        path = next(IMAGE_DIR.glob(stem + ".*"))
        pts = [(float(a.split(",")[0]), float(a.split(",")[1]), f"({a})") for a in args[1:]]
        render(path, None, pts, OUT / f"{stem}.png")
        return 0
    wanted = set(args)
    for case in load_cases():
        if wanted and case.id not in wanted:
            continue
        render(case.image, case.crop, [(l.x, l.y, l.text) for l in case.labels], OUT / f"{case.id}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
