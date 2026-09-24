"""Render every microanatomy model into one contact sheet, using the app's own renderer."""
import subprocess, sys, math
from pathlib import Path
from PIL import Image
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.micro.registry import MODELS

ids = sys.argv[1:] or list(MODELS)
tiles = []
for mid in ids:
    out = ROOT / "logs" / "sheet" / f"{mid}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    tube = MODELS[mid].cutaway[1] == (0.0, 1.0, 0.0)
    yaw, pitch = (205, 35) if tube else (215, 32)
    subprocess.run([str(ROOT / ".venv/Scripts/python.exe"), str(ROOT / "tools/render_micro.py"), mid,
                    "--yaw", str(yaw), "--pitch", str(pitch), "--size", "440", "-o", str(out)], check=True)
    im = Image.open(out).convert("RGB")
    tiles.append((mid, im))
cols = 5
rows = math.ceil(len(tiles) / cols)
W = H = 440
sheet = Image.new("RGB", (cols * W, rows * H), (18, 19, 22))
for i, (mid, im) in enumerate(tiles):
    sheet.paste(im, ((i % cols) * W, (i // cols) * H))
p = ROOT / "logs" / "contact_sheet.png"
sheet.save(p)
print(p, [t[0] for t in tiles])
