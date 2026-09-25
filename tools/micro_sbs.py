"""Put a before and an after render side by side, labelled, for review.

Usage: python tools/micro_sbs.py before.png after.png [-o cmp.jpg] [--labels BEFORE,AFTER]
"""
import argparse

from PIL import Image, ImageDraw, ImageFont


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("-o", "--out", default="cmp.jpg")
    ap.add_argument("--labels", default="BEFORE,AFTER")
    a = ap.parse_args()
    imgs = [Image.open(p).convert("RGB") for p in (a.before, a.after)]
    h = max(i.height for i in imgs)
    imgs = [i.resize((round(i.width * h / i.height), h)) if i.height != h else i for i in imgs]
    gap, bar = 12, 44
    out = Image.new("RGB", (imgs[0].width + gap + imgs[1].width, h + bar), (24, 26, 31))
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 24)
    except OSError:
        font = ImageFont.load_default()
    x = 0
    for img, label in zip(imgs, a.labels.split(",")):
        out.paste(img, (x, bar))
        d.text((x + 10, 9), label, fill=(240, 240, 240), font=font)
        x += img.width + gap
    out.save(a.out, quality=88)
    print(a.out)


if __name__ == "__main__":
    main()
