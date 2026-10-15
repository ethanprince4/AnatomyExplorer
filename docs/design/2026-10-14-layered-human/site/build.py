"""Build the Layered Human website into one folder a static host can serve.

    python site/build.py                  build into site/dist
    python site/build.py --serve          build, then serve it at http://localhost:8000 the way a host would
    python site/build.py --out DIR        build somewhere else (DIR must be empty or an earlier build)
    python site/build.py --base /path/    for a site that will not sit at the root of its domain

Here the site lives at site/specimen/ and reaches the plates, fonts, renders and marks it shares with the rest of the
design folder through ../../, so it opens straight from the folder. A host wants the home page at the root of one
folder, so the build lays it out like this, with nothing else in it:

    index.html  404.html  robots.txt  sitemap.xml   from site/specimen/
    img/                                            from site/specimen/img/
    assets/  identity/  renders/  system/           the files the pages use, at the same paths as here
    favicon.ico                                     identity/specimen/favicon.ico again, for whatever asks the root

The home page's ../../ links lose the ../../. A host serves 404.html at whatever address was asked for, so every link
in it is made absolute. GitHub Pages, Netlify, Cloudflare Pages and Vercel all serve a root 404.html that way; the
empty .nojekyll file tells GitHub Pages to serve the folder as it is.

A file goes in when a page names it: in a src, href, srcset or imagesrcset attribute, as a quoted path in a script,
as a layeredhuman.com address in the head, or in a url() of a stylesheet the page loads. Two sets of names are only
made as the home page runs, so the build makes them too: each wall's lesson pictures, and the hero's depth plates,
full size and in the lighter copies in img/. A file the pages name that is not here stops the build, and so does a
link in a built page that does not land on a built file."""
import argparse
import functools
import http.server
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent                  # site/
DESIGN = HERE.parent                                    # the design folder: every path below is relative to it
SITE = "site/specimen"
DOMAIN = "https://layeredhuman.com/"
PAGES = ("index.html", "404.html")
ALSO = (SITE + "/robots.txt", SITE + "/sitemap.xml")
AT_ROOT = {"favicon.ico": "identity/specimen/favicon.ico"}
DEFAULT_OUT = HERE / "dist"

# The two paths the home page's script builds as it runs. If either line changes there, change runtime() to match.
LESSON_JS = "'../../renders/specimen/specimen_' + k + '_' + img.getAttribute('data-render')"
PLATE_JS = "'img/' + name + '-m.webp' : '../../assets/plates/' + name + '.webp'"

ATTR = re.compile(r'\s(?:src|href|poster)="([^"]*)"')
SRCSET = re.compile(r'\s(?:srcset|imagesrcset)="([^"]*)"')
QUOTED = re.compile(r"""["'`]((?:\.\./|\./)?\w[\w./@-]*\.(?:webp|png|jpe?g|gif|svg|ico|avif|woff2?|css|js|json|mp4|webm))["'`]""")
ADDRESS = re.compile(re.escape(DOMAIN) + r"[\w./@-]*")     # the social card and the like, in content= and JSON-LD
CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+?)["']?\s*\)""")
LEAVE = ("#", "data:", "mailto:", "tel:", "javascript:", "http:", "https:", "//")


def fail(message, items=()):
    print("site/build.py: " + message, file=sys.stderr)
    for item in sorted(items):
        print("  " + item, file=sys.stderr)
    sys.exit(1)


def read(rel):
    return (DESIGN / rel).read_text(encoding="utf-8")


def out_path(rel):
    """Where a file of the design folder goes in the build."""
    return rel[len(SITE) + 1:] if rel.startswith(SITE + "/") else rel


def source_of(path):
    """The design-folder file a site address (the part after the domain) stands for: out_path the other way round."""
    path = path or "index.html"
    return SITE + "/" + path if (DESIGN / SITE / path).is_file() else path


def refs(text):
    """Every file a page or script names: attributes, srcset candidates, quoted paths, the site's own addresses."""
    found = set(ATTR.findall(text)) | set(QUOTED.findall(text)) | set(ADDRESS.findall(text))
    for srcset in SRCSET.findall(text):
        found |= {c.split()[0] for c in srcset.split(",") if c.strip()}
    return found


def clean(ref):
    return ref.split("#")[0].split("?")[0]


def resolve(ref, folder):
    """The design-folder path a reference made from `folder` points at, or None for one that leaves the site."""
    ref = ref.strip()
    if ref.startswith(DOMAIN):
        return source_of(clean(ref[len(DOMAIN):]))
    if not ref or ref.startswith(LEAVE) or not clean(ref):
        return None
    parts = []
    for part in (folder + "/" + clean(ref)).split("/"):
        if part == "..":
            if not parts:
                return ".." + "/" + clean(ref)     # outside the design folder: reported as missing
            parts.pop()
        elif part not in ("", "."):
            parts.append(part)
    return "/".join(parts)


def walls():
    """The Specimen walls as the page reads them, from system/schemes.js."""
    m = re.match(r"\s*window\.LH_SCHEMES\s*=\s*(\{.*\})\s*;?\s*$", read("system/schemes.js"), re.S)
    if not m:
        fail("system/schemes.js no longer reads window.LH_SCHEMES = {...};")
    return json.loads(m.group(1))["specimen"]["schemes"]


def runtime(page):
    """The files the home page's script names as it runs, which no attribute or quoted path carries in full."""
    if LESSON_JS not in page or PLATE_JS not in page:
        fail("the home page no longer builds its lesson and plate paths the way runtime() expects; update it")
    need, ws = set(), walls()
    # each wall's lesson pictures: specimen_<wall>_<data-render>.webp, and @2x.webp where the img has data-2x
    for tag in re.findall(r'<img\b[^>]*\sdata-render="[^"]+"[^>]*>', page):
        render = re.search(r'\sdata-render="([^"]+)"', tag).group(1)
        for k in ws:
            base = "renders/specimen/specimen_%s_%s" % (k, render)
            need.add(base + ".webp")
            if re.search(r"\sdata-2x\b", tag):
                need.add(base + "@2x.webp")
    # the hero's depth plates, named in STOPS; a name ending in _ takes each wall's selection colour
    names = set(re.findall(r"\b(?:plate|over):\s*'(\w+)'", page))
    med = re.search(r"var MED = /(.+?)/;", page)
    if not names or not med:
        fail("the home page no longer names its plates in STOPS and MED the way runtime() expects; update it")
    med = re.compile(med.group(1))
    for name in names:
        full = {name + (ws[k].get("select") or "#ffffff").lstrip("#").lower() for k in ws} if name.endswith("_") else {name}
        for plate in full:
            need.add("assets/plates/%s.webp" % plate)
            if med.match(plate):
                need.add("%s/img/%s-m.webp" % (SITE, plate))
    return need


def collect():
    """The pages' text and every other file the build needs, as design-folder paths."""
    pages = {name: read(SITE + "/" + name) for name in PAGES}
    need = set(ALSO) | set(AT_ROOT.values()) | runtime(pages["index.html"])
    for text in pages.values():
        need |= {r for r in (resolve(ref, SITE) for ref in refs(text)) if r}
    for css in [n for n in need if n.endswith(".css") and (DESIGN / n).is_file()]:
        folder = css.rpartition("/")[0]
        need |= {r for r in (resolve(u, folder) for u in CSS_URL.findall(read(css))) if r}
    need -= {SITE + "/" + name for name in PAGES}
    missing = [n for n in need if n.startswith("..") or not (DESIGN / n).is_file()]
    if missing:
        fail("the pages name files that are not in the design folder:", missing)
    places = {}
    for n in need:
        if places.setdefault(out_path(n), n) != n:
            fail("two files would land at %s: %s and %s" % (out_path(n), places[out_path(n)], n))
    return pages, need


def page_for_host(name, text, base):
    if name == "index.html":
        return text.replace("../../", "")
    # 404.html: absolute links, since the host serves it at any depth
    text = text.replace("../../", base)
    return re.sub(r'(\s(?:href|src)=")index\.html(#[^"]*)?"', lambda m: m.group(1) + base + (m.group(2) or "") + '"', text)


def check(out, base):
    """Every link in the built pages and stylesheets lands on a built file; 404.html has no relative links."""
    bad = []
    for name in PAGES:
        for ref in refs((out / name).read_text(encoding="utf-8")):
            if ref.startswith(DOMAIN):
                path = ref[len(DOMAIN):]
            elif ref.startswith(LEAVE):
                continue
            elif ref.startswith("/"):
                if not ref.startswith(base):
                    bad.append("%s: %s is outside %s" % (name, ref, base))
                    continue
                path = ref[len(base):]
            elif name == "404.html":
                bad.append("404.html: %s is relative" % ref)
                continue
            else:
                path = ref
            path = clean(path)
            if not (out / (path if path and not path.endswith("/") else path + "index.html")).is_file():
                bad.append("%s: %s" % (name, ref))
    for css in out.rglob("*.css"):
        for u in CSS_URL.findall(css.read_text(encoding="utf-8")):
            target = (css.parent / clean(u)).resolve()
            if not u.startswith(LEAVE) and not (target.is_file() and out in target.parents):
                bad.append("%s: url(%s)" % (css.relative_to(out), u))
    if bad:
        fail("links in the build that land nowhere:", bad)


def build(out, base, wipe):
    pages, need = collect()
    if out.exists() and any(out.iterdir()):
        if not wipe and not ((out / "404.html").is_file() and (out / ".nojekyll").is_file()):
            fail("%s is not empty and is not an earlier build; choose another folder" % out)
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, text in pages.items():
        (out / name).write_text(page_for_host(name, text, base), encoding="utf-8")
    for n in sorted(need):
        (out / out_path(n)).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DESIGN / n, out / out_path(n))
    for name, n in AT_ROOT.items():
        shutil.copyfile(DESIGN / n, out / name)
    (out / ".nojekyll").write_text("")
    check(out, base)
    files = [f for f in out.rglob("*") if f.is_file()]
    size = sum(f.stat().st_size for f in files)
    print("built %s: %d files, %.1f MB" % (out, len(files), size / 1e6))
    top = {}
    for f in files:
        part = f.relative_to(out).parts
        key = part[0] + "/" if len(part) > 1 else "(root)"
        top[key] = top.get(key, 0) + f.stat().st_size
    for key in sorted(top):
        print("  %-12s %6.1f MB" % (key, top[key] / 1e6))


class Host(http.server.SimpleHTTPRequestHandler):
    """Serves the build as a static host does: 404.html, with status 404, for any address with no file behind it."""

    def list_directory(self, path):
        self.send_error(404)

    def send_error(self, code, message=None, explain=None):
        page = Path(self.directory) / "404.html"
        if code != 404 or not page.is_file():
            return super().send_error(code, message, explain)
        body = page.read_bytes()
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser(description="Build the Layered Human website for a static host.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to build (default site/dist)")
    ap.add_argument("--base", default="/", help="the site's path on its domain, for 404.html's links (default /)")
    ap.add_argument("--serve", action="store_true", help="serve the build at http://localhost:PORT afterwards")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    base = "/" + a.base.strip("/") + "/" if a.base.strip("/") else "/"
    out = a.out.resolve()
    build(out, base, wipe=out == DEFAULT_OUT)
    if a.serve:
        if base != "/":
            fail("--serve serves the build at the root; build with --base / to try it")
        print("serving %s at http://localhost:%d (Ctrl+C stops)" % (out, a.port))
        handler = functools.partial(Host, directory=str(out))
        try:
            http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler).serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
