"""Presentation board for the "free" (Quarter) logo option: an HTML page in the scratch folder, captured with
Playwright at 2x (1600 x 1000 css px) and saved as renders/checkpoint-1/logo/free.webp. Run through free.py."""
import base64
import re
import subprocess

from PIL import Image

import free as F

NAME = "Quarter"
SENTENCE = ("The skin is cut away from one quarter of the body, from the crown to the hip, "
            "so you see the muscle beneath it and how thick the skin is.")
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
PW = "/opt/node-tools/node_modules/playwright/index.mjs"


def uri(path):
    return "file://" + str(path)


def favicon_variant(mode):
    """The favicon as a browser draws it in a light or a dark tab bar (its prefers-color-scheme rule resolved)."""
    text = (F.OUT / "favicon.svg").read_text()
    pal = F.LIGHT if mode == "light" else F.DARK
    rules = f".i{{fill:{pal['ink']}}}.a{{fill:{pal['accent']}}}"
    text = re.sub(r"<style>.*</style>", f"<style>{rules}</style>", text, flags=re.S)
    return "data:image/svg+xml;base64," + base64.b64encode(text.encode()).decode()


def lockup_height(cap_px):
    """Display height of the outlined lockup for a given cap height (the SVGs are set at a 24 px cap)."""
    h = float(re.search(r'height="([\d.]+)"', (F.OUT / "lockup-dark.svg").read_text())[1])
    return h * cap_px / 24


def tabs(mode):
    bar, active, ghost, text = (("#dee1e6", "#ffffff", "#c4c7cc", "#1f1f1f") if mode == "light"
                                else ("#1f2023", "#35363a", "#4a4c50", "#e8eaed"))
    ghost_tab = (f'<div class="tab ghost"><i style="background:{ghost}"></i><b style="background:{ghost}"></b></div>')
    return (f'<div class="tabs" style="background:{bar}">'
            f'<div class="tab" style="background:{active};color:{text}"><img src="{favicon_variant(mode)}" width="16" height="16">'
            f'<span>Layered Human</span></div>{ghost_tab}{ghost_tab}</div>')


def board():
    o, fonts = F.OUT, F.ROOT / "assets/fonts/fonts.css"
    cap_header = 14.2                                  # Literata 20 px: the figure is about 30 px high
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="{uri(fonts)}">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:1600px;height:1000px;overflow:hidden;background:#1d2227;font-family:'Fira Sans',sans-serif}}
.wall{{position:absolute;left:0;top:0;width:560px;height:1000px;
  background:radial-gradient(ellipse 70% 55% at 50% 42%,#3d4750 0%,#323b44 45%,#2a3138 70%,#1d2227 100%)}}
.wall img{{position:absolute;left:50%;top:70px;height:720px;transform:translateX(-50%)}}
.wall h1{{position:absolute;left:44px;bottom:92px;font-family:Literata;font-weight:450;font-size:40px;color:#efece6;
  font-variation-settings:"opsz" 36}}
.wall p{{position:absolute;left:44px;right:44px;bottom:40px;font-size:15px;line-height:1.45;color:#c7c6c1}}
.icons{{position:absolute;left:560px;top:0;width:1040px;height:600px;background:#15181b}}
.icons .big{{position:absolute;left:40px;top:44px;width:512px;height:512px}}
.ladder{{position:absolute;left:600px;top:120px;display:flex;align-items:flex-end;gap:28px}}
.zoom{{position:absolute;left:600px;top:330px;display:flex;gap:36px;align-items:flex-start}}
.zoom img{{image-rendering:pixelated;display:block}}
.cap{{font-size:12px;color:#7d8590;margin-top:10px;letter-spacing:.02em}}
.slate{{position:absolute;left:560px;top:600px;width:520px;height:400px;background:#2a3138}}
.slate .lock{{position:absolute;left:48px;top:64px}}
.header{{position:absolute;left:0;right:0;bottom:56px;height:52px;background:#2c333a;border-top:1px solid #3e4851;
  border-bottom:1px solid #3e4851;display:flex;align-items:center;padding:0 20px;gap:26px}}
.header nav{{display:flex;gap:20px;font-size:14.5px;color:#c7c6c1;margin-left:10px}}
.header nav span:first-child{{color:#efece6}}
.paper{{position:absolute;left:1080px;top:600px;width:520px;height:400px;background:#ece8e0}}
.paper .lock{{position:absolute;left:48px;top:64px}}
.tabs{{position:absolute;left:48px;right:48px;height:40px;display:flex;align-items:flex-end;padding:0 8px;gap:4px;
  border-radius:8px 8px 0 0}}
.tab{{height:32px;width:200px;white-space:nowrap;border-radius:8px 8px 0 0;display:flex;align-items:center;gap:8px;padding:0 12px;font-size:12.5px}}
.tab.ghost{{background:transparent}}
.tab.ghost i{{width:16px;height:16px;border-radius:3px;display:block}}
.tab.ghost b{{width:90px;height:8px;border-radius:4px;display:block}}
</style></head><body>
<div class="wall"><img src="{uri(o / 'symbol-dark.svg')}"><h1>{NAME}</h1><p>{SENTENCE}</p></div>
<div class="icons">
  <img class="big" src="{uri(o / 'icon-1024.png')}">
  <div class="ladder">
    <div><img src="{uri(o / 'icon-128.png')}" width="128"><div class="cap">128</div></div>
    <div><img src="{uri(o / 'icon-64.png')}" width="64"><div class="cap">64</div></div>
    <div><img src="{uri(o / 'icon-32.png')}" width="32"><div class="cap">32</div></div>
    <div><img src="{uri(o / 'icon-16.png')}" width="16"><div class="cap">16</div></div>
  </div>
  <div class="zoom">
    <div><img src="{uri(o / 'icon-32.png')}" width="128" height="128"><div class="cap">32 px, 4x</div></div>
    <div><img src="{uri(o / 'icon-16.png')}" width="64" height="64"><div class="cap">16 px, 4x</div></div>
    <div><img src="{uri(o / 'symbol-small.svg')}" width="128" height="128"><div class="cap">small drawing, 32 px, 4x</div></div>
  </div>
</div>
<div class="slate">
  <img class="lock" src="{uri(o / 'lockup-dark.svg')}" height="{lockup_height(36):.1f}">
  <div class="header"><img src="{uri(o / 'lockup-dark.svg')}" height="{lockup_height(cap_header):.1f}">
    <nav><span>Atlas</span><span>Lessons</span><span>Models</span><span>Radiology</span></nav></div>
</div>
<div class="paper">
  <img class="lock" src="{uri(o / 'lockup-light.svg')}" height="{lockup_height(36):.1f}">
  <div style="position:absolute;left:0;right:0;top:206px">{tabs('light')}</div>
  <div style="position:absolute;left:0;right:0;top:282px">{tabs('dark')}</div>
</div>
</body></html>"""
    d = F.SCRATCH / "board"
    d.mkdir(parents=True, exist_ok=True)
    page = d / "board.html"
    page.write_text(html)
    png = d / "board.png"
    shot = d / "shot.mjs"
    shot.write_text(f"""import {{ chromium }} from '{PW}';
const b = await chromium.launch({{ executablePath: '{CHROME}', args: ['--allow-file-access-from-files'] }});
const p = await b.newPage({{ viewport: {{ width: 1600, height: 1000 }}, deviceScaleFactor: 2 }});
await p.goto('{uri(page)}'); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(300);
await p.screenshot({{ path: '{png}' }});
await b.close();
""")
    subprocess.run(["node", str(shot)], check=True)
    F.RENDERS.mkdir(parents=True, exist_ok=True)
    Image.open(png).convert("RGB").save(F.RENDERS / "free.webp", quality=90, method=6)
    print("board:", F.RENDERS / "free.webp")
