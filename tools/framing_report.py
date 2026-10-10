"""Bounding box of the non-background pixels of each <id>_3d.png, as fractions of the image.

    python tools/framing_report.py DIR [id ...]

Background is the colour of the image's four corners (the scene's clear colour). Prints x0 x1 y0 y1 (fractions),
the box's width and height fractions, and whether the model touches the left or right edge.
"""
import sys
from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage

TOLERANCE = 12            # per-channel difference from the background that counts as model


def measure(path):
    image = QImage(str(path)).convertToFormat(QImage.Format_RGB32)
    w, h = image.width(), image.height()
    a = np.frombuffer(image.constBits(), np.uint8).reshape(h, image.bytesPerLine() // 4, 4)[:, :w, :3].astype(int)
    corners = np.array([a[0, 0], a[0, -1], a[-1, 0], a[-1, -1]])
    bg = np.median(corners, 0)
    mask = (np.abs(a - bg).max(axis=2) > TOLERANCE)
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    return dict(x0=x0 / w, x1=x1 / w, y0=y0 / h, y1=y1 / h, w=(x1 - x0) / w, h=(y1 - y0) / h,
                edge=("L" if x0 == 0 else "") + ("R" if x1 == w else ""), size=f"{w}x{h}")


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    ids = sys.argv[2:] or sorted(p.name[:-7] for p in folder.glob("*_3d.png"))
    for case_id in ids:
        m = measure(folder / f"{case_id}_3d.png")
        if m is None:
            print(f"{case_id:36s} empty")
        else:
            print(f"{case_id:36s} x {m['x0']:.2f}-{m['x1']:.2f}  y {m['y0']:.2f}-{m['y1']:.2f}  "
                  f"w {m['w']:.2f} h {m['h']:.2f}  edge {m['edge'] or '-'}  {m['size']}")
