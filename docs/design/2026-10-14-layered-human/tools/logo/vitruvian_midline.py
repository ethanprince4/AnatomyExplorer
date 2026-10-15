"""Section down the midline: the Specimen identity mark, chosen at checkpoint 1 (vitruvian-b with the cut run down the
whole midline). Called by vitruvian.py; run from the repository root with the project venv:

  .venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/vitruvian.py midline           everything below
  .venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/vitruvian.py midline json      the drawings only
  .venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/vitruvian.py midline explore   the variants sheet

`json` writes tools/logo/section_midline.json: the drawings in frame units, one per mark size in output pixels that
build_identity.py draws (build_identity.midline_sizes()). The option folder identity/options/section-midline/ is then
made with build_identity's own Specimen functions, so it matches identity/specimen/ exactly. After `json`, rebuild the
identity with: S0/idvenv/bin/python docs/design/2026-10-14-layered-human/tools/build_identity.py build"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "tools")]
import build_identity as bi                            # noqa: E402
import vitruvian_geom as G                             # noqa: E402
import vitruvian_marks as M                            # noqa: E402

OPT = "section-midline"
OUT = ROOT / "identity/options" / OPT
RENDERS = ROOT / "renders/checkpoint-2/logo"
BEFORE = ROOT / "identity/options/vitruvian-b"
SCRATCH = Path(os.environ.get("MIDLINE_SCRATCH", "/tmp/claude-0/-home-user-AnatomyExplorer/"
                              "effa1011-ff25-5650-b9af-b091db4dac0b/scratchpad/logo-midline"))
IDVENV = os.environ.get("IDVENV", "/tmp/claude-0/-home-user-AnatomyExplorer/"
                        "effa1011-ff25-5650-b9af-b091db4dac0b/scratchpad/idvenv/bin/python")
NODE_PW = "/opt/node-tools/node_modules/playwright/index.mjs"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
CHOSEN = {"head": "split", "detail": "full"}
NAME = "Section, down the midline"
LINE = ("Leonardo's figure in its circle, cut down the midline: one half skin, the other half the muscle beneath, "
        "one step deeper.")
MAC_SIZES = (16, 32, 64, 128, 256, 512, 1024)


# ---- drawings -------------------------------------------------------------------------------------------------------

def _fmt(v):
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def entry(items, u, grid):
    return {"u": round(u, 4), "grid": grid, "bounds": [round(v, 1) for v in M.bounds(items)],
            "items": [[role, round(a, 3), G.path_d(g, tol=max(.8, .12 * u), fmt=_fmt)] for g, role, a in items]}


def drawings(head="split", detail="full", sizes=None, **kw):
    """The vector drawing and one drawing per mark size (output pixels)."""
    data = {"vector": entry(M.midline(head=head, lines=detail), 0, False)}
    for m in sizes or bi.midline_sizes():
        data[str(m)] = entry(*M.midline_px(m, head, detail, **kw))
    return data


def write_json():
    data = drawings(**CHOSEN)
    bi.MIDLINE.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    bi._MID = None
    print("wrote", bi.MIDLINE, f"({bi.MIDLINE.stat().st_size // 1024} KB, sizes {', '.join(data)})")


def use(data):
    """Point build_identity's Specimen functions at a set of drawings (None: the JSON file)."""
    bi._MID = data


# ---- tools ----------------------------------------------------------------------------------------------------------

def raster(jobs):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    tmp = SCRATCH / "jobs.json"
    tmp.write_text(json.dumps([{k: str(v) if k != "size" else v for k, v in j.items()} for j in jobs]))
    subprocess.run(["node", str(ROOT / "tools/raster_svg.mjs"), str(tmp)], check=True, stdout=subprocess.DEVNULL)


def shoot(html, out, w, h, scale=2):
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
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.open(png).convert("RGB").save(out, "WEBP", quality=q, method=6)
    print("wrote", out)


_WORD = None


def word():
    global _WORD
    if _WORD is None:
        code = ("import sys, json; sys.path.insert(0, %r); import build_identity as b; "
                "print(json.dumps(b.wordmark('specimen')))" % str(ROOT / "tools"))
        _WORD = json.loads(subprocess.run([IDVENV, "-c", code], check=True, capture_output=True, text=True).stdout)
    return _WORD


def svg_size(path):
    m = re.search(r'width="([\d.]+)" height="([\d.]+)"', Path(path).read_text())
    return float(m[1]), float(m[2])


# ---- the option folder ------------------------------------------------------------------------------------------------

def build_option():
    """identity/options/section-midline/: the same set of files as vitruvian-b, from build_identity's Specimen path."""
    use(None)
    out, src = OUT, OUT / "src"
    dark, light = bi.palette("specimen", "dark"), bi.palette("specimen", "light")
    for mode, p in (("dark", dark), ("light", light), ("mono", bi.MONO)):
        bi.write(out / f"symbol-{mode}.svg", bi.symbol("specimen", p, mode, None))
    bi.write(out / "symbol-small.svg", bi.svg(48, 48, bi.midline(dark, "dark", (0, 0, 48), 42 / 48,
                                                                 key=str(bi.MIDLINE_LOCKUP))))
    bi.write(src / "symbol-16.svg", bi.svg(48, 48, bi.midline(dark, "dark", (0, 0, 48), 46 / 48,
                                                             key=str(bi.MIDLINE_FAVICON))))
    w = word()
    for mode, p in (("dark", dark), ("light", light)):
        bi.write(out / f"lockup-{mode}.svg", bi.lockup("specimen", p, mode, w))
    bi.write(out / "favicon.svg", bi.favicon_svg("specimen", None))
    for mode, p in (("light", light), ("dark", dark)):    # the favicon's two schemes, for the board's tab bars
        body = bi.midline(p, mode, (0, 0, 48), 46 / 48, key=str(bi.MIDLINE_FAVICON))
        bi.write(SCRATCH / "board" / f"favicon-{mode}.svg", bi.svg(48, 48, body))
    jobs, pngs = [], {}
    for px in MAC_SIZES:
        path = bi.write(src / f"macos-{px}.svg", bi.mac_icon("specimen", "dark", px, None))
        dest = out / f"icon-{px}.png" if px in (16, 32, 64, 128, 1024) else SCRATCH / f"icon-{px}.png"
        jobs.append({"svg": path, "out": dest, "size": px})
        pngs[px] = dest
    raster(jobs)
    bi.write_icns(out / "icon.icns", pngs)
    print("wrote", out)


# ---- explorations -----------------------------------------------------------------------------------------------------

VARIANTS = [
    ("split-full", "Head split, full detail: neck, chest, abdomen, arm, thigh, shin (chosen)", dict(head="split", detail="full")),
    ("whole-full", "Head whole, cut turns under the chin", dict(head="whole", detail="full")),
    ("split-some", "Head split, four lines: chest, rectus, sartorius, shin", dict(head="split", detail="some")),
    ("split-few", "Head split, three lines: chest, rectus, sartorius", dict(head="split", detail="few")),
    ("split-none", "Head split, no lines: the silhouette alone", dict(head="split", detail=None)),
    ("whole-none", "Head whole, no lines", dict(head="whole", detail=None)),
]
SMALL = [
    ("s32-gap", "32 px: a pixel of gap between the halves", 32, dict(head="split", wall32=False), {}),
    ("s32-wall", "32 px: the pixel between them grey, as a wall (chosen)", 32, dict(head="split"), {}),
    ("s32-17", "32 px: mark 17 px across (19 chosen)", 32, dict(head="split"), {32: 17}),
    ("s16-step", "16 px: muscle half up and right one pixel", 16, dict(head="split", tiny_step=(1, 1)), {}),
    ("s16-up", "16 px: muscle half up one pixel, halves touching (chosen)", 16, dict(head="split"), {}),
    ("s16-whole", "16 px: head whole", 16, dict(head="whole"), {}),
    ("s128-none", "128 px: no lines (chosen)", 128, dict(head="split"), {}),
    ("s128-few", "128 px: three lines", 128, dict(head="split", mid="few"), {}),
    ("s64", "64 px: skin, gap, wall, gap, muscle", 64, dict(head="split"), {}),
]


def mac_m(px):
    return bi.MIDLINE_MAC[px] if px <= 32 else round(bi.MAC["specimen"] * 824 * px / 1024)


def explore():
    ex = SCRATCH / "explore"
    ex.mkdir(parents=True, exist_ok=True)
    jobs, cells, small = [], [], []
    for key, label, kw in VARIANTS:
        data = drawings(sizes=[mac_m(px) for px in (16, 32, 64, 128)], **kw)
        use(data)
        bi.write(ex / f"{key}-symbol.svg", bi.symbol("specimen", bi.palette("specimen", "dark"), "dark", None))
        for px in (16, 32, 64, 128):
            jobs.append({"svg": bi.write(ex / f"{key}-{px}.svg", bi.mac_icon("specimen", "dark", px, None)),
                         "out": ex / f"{key}-{px}.png", "size": px})
        cells.append(f"""<div class="c"><div class="row"><img src="{key}-symbol.svg" width="230" height="230">
<div class="ic"><img src="{key}-128.png" width="128"><div class="row"><img src="{key}-64.png" width="64">
<img src="{key}-32.png" width="32"><img src="{key}-16.png" width="16"></div>
<div class="row"><img class="px" src="{key}-32.png" width="96"><img class="px" src="{key}-16.png" width="64"></div>
</div></div><p>{label}</p></div>""")
    saved = dict(bi.MIDLINE_MAC)
    for key, label, px, kw, mac in SMALL:
        bi.MIDLINE_MAC.update(mac)
        use(drawings(sizes=[mac_m(px)], **kw))
        jobs.append({"svg": bi.write(ex / f"{key}.svg", bi.mac_icon("specimen", "dark", px, None)),
                     "out": ex / f"{key}.png", "size": px})
        bi.MIDLINE_MAC.clear()
        bi.MIDLINE_MAC.update(saved)
        z = 4 if px <= 32 else 2 if px <= 64 else 1
        small.append(f"""<div class="c"><div class="row"><img src="{key}.png" width="{px}">
<img class="px" src="{key}.png" width="{px * z}"></div><p>{label}</p></div>""")
    use(None)
    raster(jobs)
    html = ex / "sheet.html"
    html.write_text(f"""<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="{ROOT}/assets/fonts/fonts.css">
<style>body{{margin:0;background:#1a1e22;color:#c7c6c1;font:15px 'Fira Sans';padding:28px 32px}}
.g{{display:grid;grid-template-columns:repeat(3,500px);gap:26px 20px}}.row{{display:flex;align-items:end;gap:12px}}
.ic{{display:flex;flex-direction:column;gap:12px}}.px{{image-rendering:pixelated}}
.s{{display:grid;grid-template-columns:repeat(3,500px);gap:22px 20px}}
p{{margin:8px 0 0}}h1{{font:400 26px Literata;color:#efece6;margin:0 0 4px}}
h2{{font:400 18px Literata;color:#efece6;margin:34px 0 14px}}</style>
<h1>Section, down the midline: what was weighed</h1>
<p>Each on the wall at 230 px, then the app icon at 128, 64, 32 and 16 px, and 32 and 16 px enlarged (pixelated).</p>
<h2>The head, and how much muscle the brass half carries</h2><div class="g">{''.join(cells)}</div>
<h2>The small drawings, on the pixel grid (1x, then enlarged)</h2><div class="s">{''.join(small)}</div>""")
    png = shoot(html, SCRATCH / "explore.png", 1600, 1500, 1)
    webp(png, RENDERS / f"{OPT}-explore.webp")


# ---- boards -----------------------------------------------------------------------------------------------------------

FONTS = f'<link rel="stylesheet" href="{ROOT}/assets/fonts/fonts.css">'


def header(lockup, cap_px):
    lw, lh = svg_size(lockup)
    s = cap_px / 24
    return (f'<div class="hdr"><img src="{lockup}" width="{lw * s:.1f}" height="{lh * s:.1f}">'
            f'<nav><a>Atlas</a><a>Lessons</a><a>Models</a></nav></div>')


def board():
    """The presentation board (as at checkpoint 1) with a dock row at 64 and 128 px."""
    bd = SCRATCH / "board"
    bd.mkdir(parents=True, exist_ok=True)
    d, w = OUT, word()
    cap_px = 23 * w["cap"] / w["upm"]                      # the app's lockup: Literata 23 px
    lw, lh = svg_size(d / "lockup-dark.svg")
    tab = lambda mode: f"""<div class="tabs {mode}"><div class="tab on"><img src="favicon-{mode}.svg" width="16" height="16">
<span>Layered Human</span><i>&#x2715;</i></div><div class="tab"><b></b><em></em></div><div class="tab"><b></b><em></em></div></div>
<div class="bar {mode}"><span></span></div>"""
    dock = lambda size, n_left, n_right: (f'<div class="dock" style="--s:{size}px">'
                                          + '<i></i>' * n_left + f'<img src="{d}/icon-{size}.png" width="{size}">'
                                          + '<i></i>' * n_right + '</div>')
    html = bd / "board.html"
    html.write_text(f"""<!doctype html><meta charset="utf-8">{FONTS}
<style>
*{{box-sizing:border-box}}body{{margin:0;width:1600px;height:1000px;background:#1d2227;color:#efece6;font-family:'Fira Sans';
display:grid;grid-template-columns:540px 600px 460px;overflow:hidden}}
.wall{{background:radial-gradient(ellipse 70% 58% at 50% 40%,#3d4750 0%,#323b44 40%,#2a3138 70%,#1d2227 100%);
display:flex;flex-direction:column;align-items:center;padding:64px 44px 44px}}
.wall .sym{{flex:1;display:flex;align-items:center}}
.wall h1{{font:400 40px/1.1 Literata;font-variation-settings:"opsz" 72;margin:0;align-self:flex-start;letter-spacing:-.01em}}
.wall p{{font:300 17px/1.45 'Fira Sans';color:#c7c6c1;margin:12px 0 0;align-self:flex-start;max-width:450px}}
.icons{{padding:26px 24px;display:flex;flex-direction:column;align-items:center;gap:20px;background:#20262b}}
.ladder{{display:flex;align-items:flex-end;gap:18px}}.ladder img{{image-rendering:pixelated}}
.dock{{display:flex;align-items:center;gap:calc(var(--s) * .14);padding:calc(var(--s) * .1) calc(var(--s) * .16);
background:#3b4249;border:1px solid #4a525a;border-radius:calc(var(--s) * .3)}}
.dock i{{width:var(--s);height:var(--s);border-radius:22.5%;background:#6b7178;transform:scale(.805)}}
.dock img{{image-rendering:auto}}
.right{{display:flex;flex-direction:column}}
.lock{{flex:1;display:flex;align-items:center;justify-content:center}}
.slate{{background:#2a3138}}.paper{{background:#ece8e0}}
.hdr{{height:52px;background:#2a3138;border-top:1px solid #3e4851;border-bottom:1px solid #3e4851;display:flex;align-items:center;padding:0 20px;gap:22px}}
.hdr nav{{display:flex;gap:18px;font:500 14px 'Fira Sans';color:#c7c6c1;margin-left:14px}}
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
<section class="wall"><div class="sym"><img src="{d}/symbol-dark.svg" width="470" height="470"></div>
<h1>{NAME}</h1><p>{LINE}</p></section>
<section class="icons"><img src="{d}/icon-1024.png" width="512" height="512">
<div class="ladder"><img src="{d}/icon-128.png" width="128"><img src="{d}/icon-64.png" width="64"><img src="{d}/icon-32.png" width="32"><img src="{d}/icon-16.png" width="16">
<img src="{d}/icon-32.png" width="128" style="margin-left:14px"><img src="{d}/icon-16.png" width="64"></div>
{dock(64, 3, 3)}{dock(128, 1, 1)}</section>
<section class="right">
<div class="lock slate"><img src="{d}/lockup-dark.svg" width="{lw * 1.15:.0f}"></div>
<div class="lock paper"><img src="{d}/lockup-light.svg" width="{lw * 1.15:.0f}"></div>
{header(d / "lockup-dark.svg", cap_px)}
<div class="browser">{tab('light')}{tab('dark')}</div></section>""")
    webp(shoot(html, SCRATCH / "board.png", 1600, 1000, 2), RENDERS / f"{OPT}.webp")


def before_after():
    """Section as it was beside the midline version: 256, 64, 32 and 16 px (32 and 16 enlarged), the lockup on slate
    and the mark in the app's header strip."""
    bd = SCRATCH / "board"
    bd.mkdir(parents=True, exist_ok=True)
    raster([{"svg": BEFORE / "src/macos-256.svg", "out": bd / "before-256.png", "size": 256}])
    w = word()
    cap_px = 23 * w["cap"] / w["upm"]
    rows = []
    for title, d, i256 in (("Before: Section, checkpoint 1", BEFORE, bd / "before-256.png"),
                           ("After: Section, down the midline", OUT, SCRATCH / "icon-256.png")):
        lw, _ = svg_size(d / "lockup-dark.svg")
        rows.append(f"""<div class="r"><h2>{title}</h2><div class="line">
<img src="{i256}" width="256"><img src="{d}/icon-64.png" width="64"><img src="{d}/icon-32.png" width="32">
<img src="{d}/icon-16.png" width="16"><img class="px" src="{d}/icon-32.png" width="128" style="margin-left:24px"><img class="px" src="{d}/icon-16.png" width="64">
<div class="side"><div class="lock"><img src="{d}/lockup-dark.svg" width="{lw * 1.15:.0f}"></div>{header(d / "lockup-dark.svg", cap_px)}</div>
</div></div>""")
    html = bd / "before-after.html"
    html.write_text(f"""<!doctype html><meta charset="utf-8">{FONTS}
<style>*{{box-sizing:border-box}}body{{margin:0;width:1600px;height:860px;background:#20262b;color:#efece6;font-family:'Fira Sans';
padding:34px 40px}}h1{{font:400 30px Literata;margin:0 0 6px}}body>p{{margin:0 0 10px;color:#c7c6c1;font:300 16px 'Fira Sans'}}
h2{{font:400 19px Literata;margin:26px 0 12px;color:#efece6}}.line{{display:flex;align-items:flex-end;gap:22px}}
.px{{image-rendering:pixelated}}.line>img:nth-child(-n+4){{image-rendering:pixelated}}
.side{{margin-left:auto;width:470px;display:flex;flex-direction:column;gap:14px}}
.lock{{height:150px;background:#2a3138;display:flex;align-items:center;justify-content:center}}
.hdr{{height:52px;background:#2a3138;border-top:1px solid #3e4851;border-bottom:1px solid #3e4851;display:flex;align-items:center;padding:0 20px;gap:22px}}
.hdr nav{{display:flex;gap:18px;font:500 14px 'Fira Sans';color:#c7c6c1;margin-left:14px}}</style>
<h1>Section, before and after</h1><p>The app icon at 256, 64, 32 and 16 px, then 32 and 16 px enlarged four times; the lockup on slate; the app header.</p>
{''.join(rows)}""")
    webp(shoot(html, SCRATCH / "before-after.png", 1600, 860, 2), RENDERS / "before-after.webp")


def run(cmd="all"):
    if cmd in ("all", "json"):
        write_json()
    if cmd in ("all", "option"):
        build_option()
    if cmd in ("all", "explore"):
        explore()
    if cmd in ("all", "board"):
        board()
        before_after()
