"""Vitruvian logo option for Layered Human: Leonardo's figure, layered (skin, muscle, bone) in depth.

Run from the repository root with the project venv (numpy, scipy, shapely, Pillow); the wordmark is outlined by
tools/build_identity.py in the identity venv (fontTools, uharfbuzz, brotli), which this script calls for you:

  .venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/vitruvian.py explore   contact sheet of variations
  .venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/vitruvian.py build     every deliverable
  .venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/vitruvian.py midline   Section down the midline,
      the Specimen mark chosen at checkpoint 1 (see vitruvian_midline.py; `midline json|option|explore|board`)

Set IDVENV to the identity venv's python if it is not at the scratch path below. Node with Playwright renders."""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                                 # the design folder
sys.path[:0] = [str(HERE), str(ROOT / "tools")]
import build_identity as bi                            # noqa: E402  helpers only; never edited
import vitruvian_geom as G                             # noqa: E402
import vitruvian_marks as M                            # noqa: E402

SLUG = "vitruvian"
OUT = ROOT / "identity/options" / SLUG
RENDERS = ROOT / "renders/checkpoint-1/logo"
SCRATCH = Path(os.environ.get("VITRUVIAN_SCRATCH", "/tmp/claude-0/-home-user-AnatomyExplorer/"
                              "effa1011-ff25-5650-b9af-b091db4dac0b/scratchpad/logo-vitruvian"))
IDVENV = os.environ.get("IDVENV", "/tmp/claude-0/-home-user-AnatomyExplorer/"
                        "effa1011-ff25-5650-b9af-b091db4dac0b/scratchpad/idvenv/bin/python")
NODE_PW = "/opt/node-tools/node_modules/playwright/index.mjs"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

SLATE = bi.SCHEMES["specimen"]["schemes"]["slate"]
DARK = {"ink": "#efece6", "brass": "#d4b47e", "top": SLATE["stage_top"], "bottom": SLATE["stage_bottom"],
        "spot": SLATE["spot"]}
PAPER = "#ece8e0"
LIGHT = {"ink": "#1d2024", "brass": "#8c6a32", "top": PAPER, "bottom": "#dbd7d0", "spot": "#f7f5f1"}
MONO = {"ink": "currentColor", "brass": "currentColor"}
MAC_EXT = .58                                          # the mark's 42-unit extent as a share of the 824 tile


def tile_svg(mark_body, px=1024, spot=True):
    """macOS tile (as build_identity.mac_icon): 824 superellipse on a 1024 canvas, shadow, slate, spotlight.
    mark_body is drawn in a 48 box that is scaled so its 42-unit extent is 58% of the tile."""
    p = {"top": DARK["top"], "bottom": DARK["bottom"], "spot": DARK["spot"]}
    tile = bi.superellipse(512, 512, 412)
    k = MAC_EXT * 824 / 42
    defs = bi.ground_defs(p, spot) + ('<filter id="sh" x="-.2" y="-.2" width="1.4" height="1.4">'
                                      '<feGaussianBlur stdDeviation="14"/></filter>')
    body = (f'<path d="{tile}" fill="#000" fill-opacity=".3" transform="translate(0 11)" filter="url(#sh)"/>'
            + bi.ground(tile, spot)
            + f'<g transform="translate({bi.n(512 - 24 * k)} {bi.n(512 - 24 * k)}) scale({bi.n(k)})">{mark_body}</g>'
            + bi.edge(512, 512, 412, max(2, 1024 / px)))
    return bi.svg(1024, 1024, body, defs=defs)


def symbol_svg(items, pal, size=48, ext=42):
    f, k = M.fit(items, size, ext)
    return bi.svg(size, size, M.body(items, pal, f, k)), M.body(items, pal, f, k)


def shoot(html, out, w, h, scale=2):
    """Capture an HTML file with Chromium; returns the PNG path."""
    js = SCRATCH / "shoot.mjs"
    js.write_text(f"""import {{ chromium }} from '{NODE_PW}';
const [,, src, out, w, h, s] = process.argv;
const b = await chromium.launch({{ executablePath: '{CHROME}' }});
const p = await b.newPage({{ viewport: {{ width: +w, height: +h }}, deviceScaleFactor: +s }});
await p.goto('file://' + src); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(300);
await p.screenshot({{ path: out, fullPage: false }}); await b.close();
""")
    subprocess.run(["node", str(js), str(html), str(out), str(w), str(h), str(scale)], check=True)
    return out


def webp(png, out, q=90):
    from PIL import Image
    Image.open(png).convert("RGB").save(out, "WEBP", quality=q, method=6)


ROUNDS = (("Round 1: seven ways to layer the figure", "VARIANTS"),
          ("Round 2: the section and the sheets, built in 3D", "VARIANTS2"),
          ("Round 3: the two finalists and their small drawings", "FINAL"))


def explore(rnd="all"):
    """Contact sheet: every variation on the slate tile at 256, 64, 32 and 16 px, labelled."""
    ex = SCRATCH / "explore"
    ex.mkdir(parents=True, exist_ok=True)
    blocks, rows = [], 0
    for i, (title, name) in enumerate(ROUNDS):
        if rnd != "all" and str(i + 1) != rnd:
            continue
        cells = []
        for key, (label, fn) in getattr(M, name).items():
            items = fn()
            f, k = M.fit(items, 48, 42)
            body = M.body(items, DARK, f, k)
            bi.write(ex / f"r{i + 1}-{key}-tile.svg", tile_svg(body))
            imgs = "".join(f'<img src="r{i + 1}-{key}-tile.svg" width="{s}" height="{s}">' for s in (256, 64, 32, 16))
            cells.append(f'<div><div class="row">{imgs}</div><p>{label}</p></div>')
        rows += (len(cells) + 2) // 3
        blocks.append(f'<h2>{title}</h2><div class="g">{"".join(cells)}</div>')
    html = ex / "sheet.html"
    html.write_text(f"""<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="{ROOT}/assets/fonts/fonts.css">
<style>body{{margin:0;background:#1a1e22;color:#c7c6c1;font:15px 'Fira Sans';padding:28px 32px}}
.g{{display:grid;grid-template-columns:repeat(3,500px);gap:22px 20px}}.row{{display:flex;align-items:end;gap:10px}}
p{{margin:8px 0 0}}h1{{font:400 26px Literata;color:#efece6;margin:0 0 4px}}
h2{{font:400 18px Literata;color:#efece6;margin:30px 0 14px}}</style>
<h1>Vitruvian, layered: explorations</h1><p>Each mark on the slate app tile at 256, 64, 32 and 16 px.</p>{''.join(blocks)}""")
    h = 110 + 60 * len(blocks) + 300 * rows
    png = shoot(html, SCRATCH / f"explore-{rnd}.png", 1600, h, 1)
    if rnd == "all":
        RENDERS.mkdir(parents=True, exist_ok=True)
        webp(png, RENDERS / f"{SLUG}-explore.webp")
    print("wrote", png)


# ---- the finished options -------------------------------------------------------------------------------------------

OPTIONS = {
    SLUG: {"name": "Peel", "main": "peel", "s32": "peel-32", "s16": "peel-16", "lock": "peel-lockup", "ext": .66, "small_ext": (.8, .76), "lockup": (2.25, .5),
           "line": "Leonardo's figure on three sheets of glass, receding in depth: skin in front, then the muscle, "
                   "then the skeleton."},
    SLUG + "-b": {"name": "Section", "main": "section", "s32": "section-32", "s16": "section-16", "lock": "section-32",
                  "ext": .58, "small_ext": (.74, .66), "lockup": (2.2, .45),
                  "line": "Leonardo's figure in its circle with a quarter of the skin cut away, so the muscle shows "
                          "one layer deeper."},
}
MAC_SIZES = (16, 32, 64, 128, 256, 512, 1024)


def mark(key, u=0):
    fn = {"peel": M.peel, "section": M.section}.get(key)
    if fn and u:
        return fn(u=u)
    return M.FINAL[key][1]()


def tight(items, pal, size=48, tol=.045):
    """A symbol in a tight box: the larger side is `size` units."""
    x0, y0, x1, y1 = M.bounds(items)
    k = size / max(x1 - x0, y1 - y0)
    w, h = (x1 - x0) * k, (y1 - y0) * k
    f = (lambda p: ((p[0] - x0) * k, (p[1] - y0) * k))
    return bi.svg(w, h, M.body(items, pal, f, k, tol)), w, h


def mono_pal():
    return {"ink": "currentColor", "brass": "currentColor"}


def recolour(items, mode):
    """Mono: brass becomes the ink at 62% so the layers stay apart."""
    if mode != "mono":
        return items
    return [(g, r, a * (.62 if r == "brass" else 1)) for g, r, a in items]


def _fit(items, box, ext):
    x0, y0, size = box
    bx0, by0, bx1, by1 = M.bounds(items)
    k = ext * size / max(bx1 - bx0, by1 - by0)
    cx, cy = x0 + size / 2, y0 + size / 2
    return (lambda p: (cx + k * (p[0] - (bx0 + bx1) / 2), cy + k * (p[1] - (by0 + by1) / 2))), k


def mac_icon(opt, px):
    """macOS icon: 1024 canvas, 824 superellipse tile, shadow, slate ground and the spotlight (as
    build_identity.mac_icon). 64 px and below use the small drawings; strokes never fall under a pixel."""
    o = OPTIONS[opt]
    key = o["s16"] if px <= 16 else o["s32"] if px <= 32 else o["lock"] if px <= 64 else o["main"]
    probe = mark(key)
    bx0, by0, bx1, by1 = M.bounds(probe)
    u = max(bx1 - bx0, by1 - by0) / (o["ext"] * 824 * px / 1024)       # frame units per output pixel
    items = probe if px <= 64 else mark(key, u if px < 512 else 0)
    # 32 px and below: the small drawing fills more of the tile (16: first value, 32: second)
    ext = o["small_ext"][0] if px <= 16 else o["small_ext"][1] if px <= 32 else o["ext"]
    f, k = _fit(items, (100, 100, 824), ext)
    p = {"top": DARK["top"], "bottom": DARK["bottom"], "spot": DARK["spot"]}
    tile = bi.superellipse(512, 512, 412)
    defs = bi.ground_defs(p, True) + ('<filter id="sh" x="-.2" y="-.2" width="1.4" height="1.4">'
                                      '<feGaussianBlur stdDeviation="14"/></filter>')
    body = (f'<path d="{tile}" fill="#000" fill-opacity=".3" transform="translate(0 11)" filter="url(#sh)"/>'
            + bi.ground(tile, True) + M.body(items, DARK, f, k, tol=.6) + bi.edge(512, 512, 412, max(2, 1024 / px)))
    return bi.svg(1024, 1024, body, defs=defs)


_WORD = None


def word():
    """The outlined Literata wordmark from build_identity (run in the identity venv, which has the font tools)."""
    global _WORD
    if _WORD is None:
        code = ("import sys, json; sys.path.insert(0, %r); import build_identity as b; "
                "print(json.dumps(b.wordmark('specimen')))" % str(ROOT / "tools"))
        _WORD = json.loads(subprocess.run([IDVENV, "-c", code], check=True, capture_output=True, text=True).stdout)
    return _WORD


def lockup(opt, pal, items, mode="dark"):
    """Symbol then wordmark, in font units (baseline y 0, y down); the symbol centred on the middle of the caps."""
    w = word()
    X0, Y0, X1, Y1 = w["bounds"]
    cap = w["cap"]
    ratio, gap = OPTIONS[opt]["lockup"]
    bx0, by0, bx1, by1 = M.bounds(items)
    k = ratio * cap / (by1 - by0)
    right = X0 - gap * cap
    ox, oy = right - k * bx1, -cap / 2 - k * (by0 + by1) / 2
    f = (lambda p: (ox + k * p[0], oy + k * p[1]))
    body = M.body(recolour(items, mode), pal, f, k, tol=1.2)
    box = (ox + k * bx0, min(Y0, oy + k * by0), X1, max(Y1, oy + k * by1))
    x0, y0 = math.floor(box[0]), math.floor(box[1])
    W, Hh = math.ceil(box[2]) - x0, math.ceil(box[3]) - y0
    sc = 24 / cap
    return bi.svg(W * sc, Hh * sc, body + f'<path fill="{pal["ink"]}" d="{w["d"]}"/>', view=f"{x0} {y0} {W} {Hh}"), {
        "symbol_h_em": ratio * cap / w["upm"], "symbol_w_em": k * (bx1 - bx0) / w["upm"],
        "gap_em": (X0 - right) / w["upm"] + 0, "x0": X0}


def favicon(opt):
    """Transparent favicon from the 16 px drawing; colours follow the browser's light or dark scheme."""
    items = mark(OPTIONS[opt]["s16"])
    x0, y0, x1, y1 = M.bounds(items)
    side = max(x1 - x0, y1 - y0)
    k = 46 / side
    f = (lambda p: (24 + k * (p[0] - (x0 + x1) / 2), 24 + k * (p[1] - (y0 + y1) / 2)))
    marker = {"ink": "INK", "brass": "BRASS"}
    raw = M.body(items, marker, f, k)
    raw = raw.replace('fill="INK"', 'class="i"').replace('fill="BRASS"', 'class="b"')
    style = (f"<style>.i{{fill:{LIGHT['ink']}}}.b{{fill:{LIGHT['brass']}}}@media (prefers-color-scheme: dark)"
             f"{{.i{{fill:{DARK['ink']}}}.b{{fill:{DARK['brass']}}}}}</style>")
    return bi.svg(48, 48, raw, style=style), {m: bi.svg(48, 48, M.body(items, pal, f, k)) for m, pal in
                                             (("light", LIGHT), ("dark", DARK))}


def raster(jobs):
    tmp = SCRATCH / "jobs.json"
    tmp.write_text(json.dumps(jobs))
    subprocess.run(["node", str(ROOT / "tools/raster_svg.mjs"), str(tmp)], check=True)


def build_option(opt):
    o = OPTIONS[opt]
    out, src = OUT.parent / opt, OUT.parent / opt / "src"
    main, s32, s16 = mark(o["main"]), mark(o["s32"]), mark(o["s16"])
    for mode, pal in (("dark", DARK), ("light", LIGHT), ("mono", mono_pal())):
        bi.write(out / f"symbol-{mode}.svg", tight(recolour(main, mode), pal)[0])
    bi.write(out / "symbol-small.svg", tight(s32, DARK)[0])
    bi.write(src / "symbol-16.svg", tight(s16, DARK)[0])
    info = {}
    for mode, pal in (("dark", DARK), ("light", LIGHT)):
        # the lockup is a small-size use (a header, a footer, a letterhead), so it takes the 32 px drawing
        text, info = lockup(opt, pal, mark(o["lock"]), mode)
        bi.write(out / f"lockup-{mode}.svg", text)
    fav, previews = favicon(opt)
    bi.write(out / "favicon.svg", fav)
    for m, t in previews.items():
        bi.write(SCRATCH / "board" / f"{opt}-favicon-{m}.svg", t)
    jobs, pngs = [], {}
    for px in MAC_SIZES:
        svgp = bi.write(src / f"macos-{px}.svg", mac_icon(opt, px))
        dest = out / f"icon-{px}.png" if px in (16, 32, 64, 128, 1024) else SCRATCH / f"{opt}-icon-{px}.png"
        jobs.append({"svg": str(svgp), "out": str(dest), "size": px})
        pngs[px] = dest
    raster(jobs)
    bi.write_icns(out / "icon.icns", pngs)
    print(f"{opt}: lockup symbol {info['symbol_w_em']:.3f}em x {info['symbol_h_em']:.3f}em, gap {info['gap_em']:.3f}em")
    return info


def build(*only):
    for opt in OPTIONS:
        if only and opt not in only:
            continue
        build_option(opt)
    explore("all")
    board()


def svg_size(path):
    import re
    t = Path(path).read_text()
    m = re.search(r'width="([\d.]+)" height="([\d.]+)"', t)
    return float(m[1]), float(m[2])


def board(*only):
    """Presentation board per option: 1600 x 1000 css px, captured at 2x."""
    bd = SCRATCH / "board"
    bd.mkdir(parents=True, exist_ok=True)
    for opt, o in OPTIONS.items():
        if only and opt not in only:
            continue
        d = OUT.parent / opt
        w = word()
        cap_px = 23 * w["cap"] / w["upm"]                      # the app's lockup: Literata 23 px
        lw, lh = svg_size(d / "lockup-dark.svg")
        hdr_scale = cap_px / 24
        big_lw, big_lh = svg_size(d / "lockup-dark.svg")
        sw, sh = svg_size(d / "symbol-dark.svg")
        sym_h = 470 if sh >= sw else 470 * sh / sw
        sym_w = sym_h * sw / sh
        tab = lambda mode: f"""<div class="tabs {mode}"><div class="tab on"><img src="{opt}-favicon-{mode}.svg" width="16" height="16">
<span>Layered Human</span><i>&#x2715;</i></div><div class="tab"><b></b><em></em></div><div class="tab"><b></b><em></em></div></div>
<div class="bar {mode}"><span></span></div>"""
        html = bd / f"{opt}.html"
        html.write_text(f"""<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="{ROOT}/assets/fonts/fonts.css">
<style>
*{{box-sizing:border-box}}body{{margin:0;width:1600px;height:1000px;background:#1d2227;color:#efece6;font-family:'Fira Sans';
display:grid;grid-template-columns:580px 560px 460px;overflow:hidden}}
.wall{{background:radial-gradient(ellipse 70% 58% at 50% 40%,#3d4750 0%,#323b44 40%,#2a3138 70%,#1d2227 100%);
position:relative;display:flex;flex-direction:column;align-items:center;padding:70px 48px 44px}}
.wall .sym{{flex:1;display:flex;align-items:center}}
.wall h1{{font:400 46px/1 Literata;font-variation-settings:"opsz" 72;margin:0;align-self:flex-start;letter-spacing:-.01em}}
.wall p{{font:300 17px/1.45 'Fira Sans';color:#c7c6c1;margin:12px 0 0;align-self:flex-start;max-width:470px}}
.icons{{padding:36px 24px;display:flex;flex-direction:column;gap:30px;background:#20262b}}
.ladder{{display:flex;align-items:flex-end;gap:18px}}.ladder img{{image-rendering:pixelated}}
.right{{display:flex;flex-direction:column}}
.lock{{flex:1;display:flex;align-items:center;justify-content:center}}
.slate{{background:#2a3138}}.paper{{background:#ece8e0}}
.hdr{{height:52px;background:#2a3138;border-top:1px solid #3e4851;border-bottom:1px solid #3e4851;display:flex;align-items:center;padding:0 20px;gap:22px}}
.hdr nav{{display:flex;gap:18px;font:500 14px 'Fira Sans';color:#c7c6c1;margin-left:14px}}.hdr nav a:first-child{{color:#efece6}}
.browser{{padding:22px 20px 26px;display:flex;flex-direction:column;gap:16px;background:#1d2227}}
.tabs{{height:38px;display:flex;align-items:flex-end;gap:2px;padding:0 8px;border-radius:8px 8px 0 0}}
.tabs.light{{background:#dfe1e5}}.tabs.dark{{background:#1f2023}}
.tab{{height:32px;width:190px;white-space:nowrap;border-radius:8px 8px 0 0;display:flex;align-items:center;gap:8px;padding:0 10px;font:13px 'Fira Sans'}}
.tab span{{flex:1}}.tab i{{font-style:normal;font-size:11px;opacity:.6}}
.tab b{{width:16px;height:16px;border-radius:4px}}.tab em{{height:8px;width:80px;border-radius:4px}}
.light .tab.on{{background:#fff;color:#1f1f1f}}.dark .tab.on{{background:#35363a;color:#e8eaed}}
.light .tab b,.light .tab em{{background:#bfc2c7}}.dark .tab b,.dark .tab em{{background:#55575c}}
.bar{{height:36px;display:flex;align-items:center;padding:0 12px;border-radius:0 0 8px 8px;margin-top:-16px}}
.bar.light{{background:#fff}}.bar.dark{{background:#35363a}}
.bar span{{height:24px;flex:1;border-radius:12px}}.bar.light span{{background:#f1f3f4}}.bar.dark span{{background:#202124}}
</style>
<section class="wall"><div class="sym"><img src="{d}/symbol-dark.svg" width="{sym_w:.0f}" height="{sym_h:.0f}"></div>
<h1>{o['name']}</h1><p>{o['line']}</p></section>
<section class="icons"><img src="{d}/icon-1024.png" width="512" height="512">
<div class="ladder"><img src="{d}/icon-128.png" width="128"><img src="{d}/icon-64.png" width="64"><img src="{d}/icon-32.png" width="32"><img src="{d}/icon-16.png" width="16">
<img src="{d}/icon-32.png" width="128" style="margin-left:14px"><img src="{d}/icon-16.png" width="64"></div></section>
<section class="right">
<div class="lock slate"><img src="{d}/lockup-dark.svg" width="{min(400, big_lw * 1.15):.0f}"></div>
<div class="lock paper"><img src="{d}/lockup-light.svg" width="{min(400, big_lw * 1.15):.0f}"></div>
<div class="hdr"><img src="{d}/lockup-dark.svg" width="{lw * hdr_scale:.1f}" height="{lh * hdr_scale:.1f}">
<nav><a>Atlas</a><a>Lessons</a><a>Models</a></nav></div>
<div class="browser">{tab('light')}{tab('dark')}</div></section>""")
        png = shoot(html, SCRATCH / f"board-{opt}.png", 1600, 1000, 2)
        webp(png, RENDERS / f"{opt}.webp")
        print("board", RENDERS / f"{opt}.webp")


if __name__ == "__main__":
    def midline(*args):
        import vitruvian_midline
        vitruvian_midline.run(*args)
    cmds = {"explore": explore, "build": build, "board": board, "midline": midline}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]](*sys.argv[2:])
