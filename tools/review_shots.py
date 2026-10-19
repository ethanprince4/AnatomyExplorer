"""Review shots (F9 PNGs) as a test bench: list them, replay their camera on a model with the app's own viewer, compare.

  init    <png files or folders...> --out shots.json
  render  --model model.npz --shots shots.json --out DIR [--only id1,id2] [--width 1024] [--hide NAME ...]
  compare --shots shots.json --tile "Label=DIR" [--tile ...] --out DIR [--width 2400] [--only id1,id2]
  infer-hidden --model model.npz --shots shots.json   (old shots: guess hidden parts from each shot's PNG)

render uses the app's own ModelView / ModelViewport / Renderer on a hidden OpenGL context (no window is ever shown),
with the user's saved view settings (the same ones launch_current.py gives the app). Only one render process runs at a
time on the machine (lock file in the temp folder). The special tile dir "source" means each shot's own PNG."""
import argparse
import json
import os
import re
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = "AnatomyExplorer-camera"
INVISIBLE = {ord(c): None for c in "​‌‍‎‏⁠﻿"}
PIECE_RE = re.compile(r"^(?P<base>.*?)\s+(?P<n>\d+)\s*\(\s*x\s*(?P<x>-?[\d.]+)\s*,\s*y\s*(?P<y>-?[\d.]+)\s*,"
                      r"\s*z\s*(?P<z>-?[\d.]+)\s*\)\s*$")
PIECE_TOL = 0.03          # of the model's bounding-box diagonal
LOCK_PATH = Path(tempfile.gettempdir()) / "AnatomyExplorer-review-render.lock"
STAMP_KEY = "AnatomyExplorer-review-render"   # every PNG this tool writes carries it (render and compare)


# ---------------------------------------------------------------------------------------------------- PNG payloads
def read_png_payload(path):
    """The decoded AnatomyExplorer-camera JSON of a PNG, or None."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    i = 8
    while i + 8 <= len(data):
        n, = struct.unpack(">I", data[i:i + 4])
        kind = data[i + 4:i + 8].decode("latin1")
        body = data[i + 8:i + 8 + n]
        i += 12 + n
        if kind not in ("tEXt", "zTXt", "iTXt"):
            continue
        key, _, rest = body.partition(b"\0")
        if key.decode("latin1") != KEY:
            continue
        if kind == "zTXt":
            rest = zlib.decompress(rest[1:])
        elif kind == "iTXt":
            flag, method = rest[0], rest[1]
            rest = rest[2:]
            _lang, _, rest = rest.partition(b"\0")
            _trans, _, rest = rest.partition(b"\0")
            if flag:
                rest = zlib.decompress(rest)
        try:
            return json.loads(rest.decode("utf8", "replace").lstrip("\0"))
        except ValueError:
            return None
    return None


def collect_pngs(paths):
    out = []
    for p in paths:
        p = Path(p)
        out.extend(sorted(p.glob("*.png")) if p.is_dir() else [p])
    return out


def cmd_init(args):
    entries, seen = [], set()
    for png in collect_pngs(args.inputs):
        png = png.resolve()
        payload = read_png_payload(png)
        if payload is None:
            print(f"warning: no camera payload in {png}", file=sys.stderr)
        stem = png.stem
        if stem in seen:
            stem = f"{png.parent.name}__{png.stem}"
        seen.add(stem)
        t = (payload or {}).get("time")
        entries.append((float(t) if isinstance(t, (int, float)) else png.stat().st_mtime, png.name, {
            "id": stem, "source_png": str(png), "payload": payload or {},
            "hidden": list((payload or {}).get("hidden") or []), "note": ""}))
    entries.sort(key=lambda e: (e[0], e[1]))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([e[2] for e in entries], indent=1, ensure_ascii=False), encoding="utf8")
    print(f"wrote {len(entries)} shots to {out}")
    return 0


def load_shots(path):
    shots = json.loads(Path(path).read_text(encoding="utf8"))
    if isinstance(shots, dict):
        shots = shots.get("shots", [])
    return shots


# ---------------------------------------------------------------------------------------------------- lock
class RenderLock:
    """One render process at a time on this machine; others wait."""

    def __enter__(self):
        self.f = open(LOCK_PATH, "a+b")
        waited = False
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.f.seek(0)
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if not waited:
                    print(f"waiting for another render process ({LOCK_PATH})", flush=True)
                    waited = True
                time.sleep(1.0)
        return self

    def __exit__(self, *exc):
        try:
            if os.name == "nt":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            self.f.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------------------------------- part matching
def clean(name):
    return str(name).translate(INVISIBLE).strip()


class PartHider:
    """Resolves hidden names to whole items or to one connected piece of an item, and applies them to the model.

    A piece is hidden by dropping its triangles from the index buffer the renderer is built from (the item list stays
    as it is), so the model must be handed to Renderer.set_model again whenever the set of hidden pieces changes."""

    def __init__(self, model):
        import numpy as np
        self.np = np
        self.model = model
        self.by_name = {}
        for it in model.items:
            for n in (it.name, getattr(it, "key", None)):
                if n:
                    self.by_name.setdefault(clean(n), it.index)
                    self.by_name.setdefault(clean(n).casefold(), it.index)
        self.diag = float(np.linalg.norm(model.bounds_max - model.bounds_min))
        self._orig_indices = model.indices
        self._orig_ranges = {p.id: (p.first, p.count) for p in model.parts}
        self._orig_lod = {pid: list(l.indices) for pid, l in (model.lod or {}).items()}
        self._pieces = {}            # item index -> list of (part, tri mask labels, label, centre)
        self.applied = frozenset()

    def _item_pieces(self, item_index):
        if item_index in self._pieces:
            return self._pieces[item_index]
        np = self.np
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        m = self.model
        out = []
        for part in m.items[item_index].parts:
            first, count = self._orig_ranges[part.id]
            ix = np.asarray(self._orig_indices[first:first + count], dtype=np.int64).reshape(-1, 3)
            if not len(ix):
                continue
            used, inv = np.unique(ix.ravel(), return_inverse=True)
            pos = np.asarray(m.vertices[used, :3], dtype=np.float64)
            q = np.round(pos / max(self.diag * 1e-6, 1e-12)).astype(np.int64)
            _u, weld = np.unique(q, axis=0, return_inverse=True)
            weld = weld.reshape(-1)
            tri = weld[inv].reshape(-1, 3)
            nw = int(weld.max()) + 1
            rows = np.concatenate([tri[:, 0], tri[:, 1], tri[:, 2]])
            cols = np.concatenate([tri[:, 1], tri[:, 2], tri[:, 0]])
            _n, lab = connected_components(coo_matrix((np.ones(len(rows), np.int8), (rows, cols)), shape=(nw, nw)),
                                           directed=False)
            tri_lab = lab[tri[:, 0]]
            posw = np.zeros((nw, 3))
            posw[weld] = pos
            for label in np.unique(tri_lab):
                tm = tri_lab == label
                pts = posw[np.unique(tri[tm].ravel())]
                centre = (pts.min(axis=0) + pts.max(axis=0)) / 2
                out.append((part, tm, ix[tm], centre))
        self._pieces[item_index] = out
        return out

    def resolve(self, names):
        """names -> (item indices to hide, [(item index, part, tri mask)] pieces, [unmatched names], [notes])."""
        np = self.np
        items, pieces, unmatched, notes = set(), [], [], []
        for raw in names:
            name = clean(raw)
            hit = self.by_name.get(name, self.by_name.get(name.casefold()))
            if hit is not None:
                items.add(hit)
                continue
            m = PIECE_RE.match(name)
            base = clean(m.group("base")) if m else None
            hit = None if base is None else self.by_name.get(base, self.by_name.get(base.casefold()))
            if hit is None:
                unmatched.append(raw)
                continue
            target = np.array([float(m.group("x")), float(m.group("y")), float(m.group("z"))])
            cand = self._item_pieces(hit)
            best, dist = None, None
            for c in cand:
                d = float(np.linalg.norm(c[3] - target))
                if dist is None or d < dist:
                    best, dist = c, d
            if best is not None and dist <= PIECE_TOL * self.diag:
                pieces.append((hit, best[0], best[1], best[2]))
                notes.append(f"piece of '{self.model.items[hit].name}' ({len(cand)} pieces), centre off by {dist:.4f}")
            else:
                items.add(hit)
                near = "none" if dist is None else f"{dist:.4f} (limit {PIECE_TOL * self.diag:.4f})"
                notes.append(f"WARNING no piece of '{self.model.items[hit].name}' ({len(cand)} pieces) near "
                             f"({target[0]}, {target[1]}, {target[2]}); nearest {near}; hiding the whole part")
        return items, pieces, unmatched, notes

    def apply_pieces(self, pieces):
        """Make the model's index buffer match these pieces. Returns True when the model changed."""
        np = self.np
        key = frozenset((id(p[1]), int(p[2].sum()), int(p[2].argmax())) for p in pieces)
        if key == self.applied:
            return False
        m = self.model
        for p in m.parts:
            p.first, p.count = self._orig_ranges[p.id]
        for pid, levels in self._orig_lod.items():
            m.lod[pid].indices = list(levels)
        m.indices = self._orig_indices
        self.applied = key
        if not pieces:
            return True
        drop = np.zeros(len(m.vertices), dtype=bool)
        by_part = {}
        for _item, part, tmask, tris in pieces:
            by_part.setdefault(part.id, []).append(tmask)
            drop[tris.ravel()] = True
        chunks, offset = [], len(self._orig_indices)
        for part in m.parts:
            masks = by_part.get(part.id)
            if not masks:
                continue
            first, count = self._orig_ranges[part.id]
            ix = np.asarray(self._orig_indices[first:first + count]).reshape(-1, 3)
            gone = np.zeros(len(ix), dtype=bool)
            for tm in masks:
                gone |= tm
            kept = np.ascontiguousarray(ix[~gone]).ravel().astype(np.uint32)
            chunks.append(kept)
            part.first, part.count = offset, len(kept)
            offset += len(kept)
        for pid, levels in self._orig_lod.items():
            if pid in by_part:
                m.lod[pid].indices = [np.ascontiguousarray(
                    np.asarray(l).reshape(-1, 3)[~drop[np.asarray(l).reshape(-1, 3)[:, 0]]]).ravel().astype(np.uint32)
                    for l in levels]
        m.indices = np.concatenate([np.asarray(self._orig_indices, dtype=np.uint32)] + chunks)
        return True


# ---------------------------------------------------------------------------------------------------- render
def app_settings():
    """The settings MainWindow gives the model views, read (never written) from the user's saved preferences."""
    from PySide6.QtCore import QSettings
    from app import config
    from app.config import DEFAULT_SETTINGS
    from app.main_window import _validated_settings
    q = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
    settings = dict(DEFAULT_SETTINGS)
    try:
        settings.update(_validated_settings(json.loads(q.value("view_settings", "{}"))))
    except (TypeError, ValueError):
        pass
    if q.value("gizmo_default_off_revision", 0, type=int) < 1:
        settings["show_gizmo"] = False
    if q.value("studio_startup_revision", 0, type=int) < 1:
        settings["restore_session"] = False
    if q.value("fast_renderer_on_revision", 0, type=int) < 1:
        settings["fast_renderer"] = True
    settings["show_structure_labels"] = False
    settings.update(custom_background=True, bg_top="#141b22", bg_bottom="#141b22")
    return settings, q


def setup_app_environment():
    hub = Path(os.environ.get("AE_HUB") or ROOT.parents[1])
    os.environ["AE_LOCAL_MODEL_LIBRARY"] = str(ROOT / "data" / "local_model_library")
    for key in ("AE_REQUIRED_MODEL_GENERATION", "AE_REQUIRED_MODEL_CATALOG_SHA256", "AE_DATASET_READY_FILE"):
        os.environ.pop(key, None)
    sys.path.insert(0, str(ROOT))
    import app.config as config
    config.ORG_NAME = "AnatomyExplorerViewerPreview"
    if (hub / "Workspace" / "user").is_dir():
        config.USER_DIR = hub / "Workspace" / "user"
    config.LOG_DIR = Path(tempfile.gettempdir()) / "AnatomyExplorer-review-logs"
    return config


def cmd_render(args):
    shots = load_shots(args.shots)
    if args.only:
        want = [s.strip() for s in args.only.split(",") if s.strip()]
        missing = [w for w in want if w not in {s["id"] for s in shots}]
        if missing:
            print(f"warning: unknown shot ids {missing}", file=sys.stderr)
        shots = [s for s in shots if s["id"] in want]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    config = setup_app_environment()
    with RenderLock():
        r = ShotRenderer(args.model, config)
        if r.error:
            print(r.error, file=sys.stderr)
            return 2
        unmatched_all = {}
        for shot in shots:
            t1 = time.perf_counter()
            img, W, H, unmatched = r.render(shot, int(args.width), extra_hidden=args.hide or [])
            for n in unmatched:
                unmatched_all.setdefault(clean(n), []).append(shot["id"])
            if img is None:
                continue
            save_stamped(img, out / f"{shot['id']}.png", {"shot": shot["id"], "model": str(Path(args.model).resolve())})
            print(f"{shot['id']}: {time.perf_counter() - t1:.2f}s  {W}x{H}", flush=True)
        if unmatched_all:
            print("UNMATCHED hidden names (hid nothing):")
            for n, ids in unmatched_all.items():
                print(f"  {n!r}  in {len(ids)} shot(s): {', '.join(ids[:6])}")
        r.close()
    return 0


def save_stamped(img, path, info):
    """Save an RGB(A) array as PNG with the review-render stamp (the only PNGs the A/B worker hook lets agents open)."""
    import numpy as np
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    meta = PngInfo()
    meta.add_text(STAMP_KEY, json.dumps(dict(info, tool="review_shots.py", time=time.time())))
    Image.fromarray(np.ascontiguousarray(img)).save(path, pnginfo=meta)


class ShotRenderer:
    """The app's own ModelView / ModelViewport / Renderer on a hidden OpenGL context, ready to replay shots."""

    def __init__(self, model_path, config):
        self.error = None
        from app.__main__ import configure_qt
        configure_qt()
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
        from PySide6.QtWidgets import QApplication
        t0 = time.perf_counter()
        qapp = QApplication.instance() or QApplication(sys.argv[:1])
        qapp.setApplicationName(config.APP_NAME)
        qapp.setOrganizationName(config.ORG_NAME)
        fmt = QSurfaceFormat.defaultFormat()
        self.surface = surface = QOffscreenSurface()
        surface.setFormat(fmt)
        surface.create()
        self.ctx = ctx = QOpenGLContext()
        ctx.setFormat(fmt)
        if not ctx.create() or not ctx.makeCurrent(surface):
            self.error = "cannot create a hidden OpenGL context"
            return
        settings, _q = app_settings()

        from app.data import Dataset
        from app.content import ContentIndex
        from app.load_control import LoadToken, checkpoint, load_scope
        from app.ui.model_view import ModelView
        from app.variants.catalog import DeferredVariantEntry
        from app.variants.local_library import SingleFileLibrary
        from app.viewer.model_loading import _prepare_model
        from app.viewer.lod import build as build_lod

        content = ContentIndex(Dataset(config.DATA_DIR))
        path = str(Path(model_path).resolve())
        if path.lower().endswith(".npz"):
            store = SingleFileLibrary(path)
            entry = DeferredVariantEntry(store.metadata(store.model_id), store)
        else:
            from app.viewer.catalog import FileEntry
            entry = FileEntry(path)
        token = LoadToken()
        with load_scope(token):
            model = _prepare_model(entry, token)
            if getattr(model, "lod", None) is None:
                from app.viewer.model import ViewerModel
                if isinstance(model, ViewerModel):
                    model.lod = build_lod(model, checkpoint)
        entry = getattr(model, "runtime_entry", entry)
        from types import SimpleNamespace
        self.view = view = ModelView(entry, content, settings, parent=None,
                                     prepared=SimpleNamespace(model=model, seconds=0.0))
        self.vp = vp = view.gl_widget
        if type(vp).__name__ != "ModelViewport":
            self.error = (f"the view is {type(vp).__name__}, not the OpenGL ModelViewport; cannot render it offscreen "
                          f"here")
            return
        vp._make_current = lambda: ctx.makeCurrent(surface)
        vp._done_current = lambda: None
        vp._init_backend()
        if vp.graphics_error or vp.renderer is None:
            self.error = "graphics failed: " + str(vp.graphics_error)
            return
        self.vmodel = view.vmodel
        self.hider = PartHider(self.vmodel)
        print(f"setup {time.perf_counter() - t0:.1f}s  model {Path(path).name}: {len(self.vmodel.items)} items, "
              f"{vp.gl_info}", flush=True)

    def item_names(self):
        return [it.name for it in self.vmodel.items]

    def render(self, shot, width, extra_hidden=(), hidden_items=None, quiet=False):
        """(image array or None, W, H, unmatched names). hidden_items (item indices) replaces the shot's hidden list."""
        from app.viewer.viewport_core import _smooth
        vp, vmodel, hider, state = self.vp, self.vmodel, self.hider, self.view.state
        payload = shot.get("payload") or {}
        cam = payload.get("camera")
        saved = payload.get("saved_view_camera")
        port = payload.get("viewport") or {}
        if not cam or not saved:
            print(f"{shot['id']}: no camera in payload, skipped", flush=True)
            return None, 0, 0, []
        vw, vh = float(port.get("width") or 1600), float(port.get("height") or 900)
        dpr = float(port.get("device_pixel_ratio") or 1.0)
        W = int(width)
        H = max(int(round(W * vh / vw)), 2)
        if hidden_items is None:
            items, pieces, unmatched, notes = hider.resolve(list(shot.get("hidden") or []) + list(extra_hidden))
        else:
            items, pieces, unmatched, notes = set(hidden_items), [], [], []
        if not quiet:
            for n in notes:
                print(f"  {shot['id']}: {n}", flush=True)
        if hider.apply_pieces(pieces):
            vp._make_current()
            vp.renderer.set_model(vmodel)
        state.hidden[:] = False
        state.forced[:] = False
        state.isolated = None
        for i in items:
            state.hidden[i] = True
        sel = [hider.by_name[clean(n)] for n in payload.get("selected") or [] if clean(n) in hider.by_name]
        state.selected = sel
        state._vis_dirty()
        # camera through the app's own API
        c = vp.camera
        fov = cam.get("fov_deg")
        if fov:
            c.fov = float(fov)
        c.ortho = bool(cam.get("ortho", False))
        ow = cam.get("ortho_width") if c.ortho else None
        c.animate_to(saved[0], saved[1], saved[2], saved[3], 0.0, ortho_width=ow)
        # cut-away / sections / explode, only when the shot says so and the model can
        cut = (payload.get("cut") or {}).get("cut_away")
        if cut is not None and getattr(vp, "cut_planes", None) is not None:
            vp.cut_on = bool(cut)
        secs = payload.get("sections")
        if secs:
            vp.sections = [None if s is None else [s[0], bool(s[1])] for s in secs]
        if payload.get("explode"):
            vp.set_explode(float(payload["explode"]))
        elif getattr(vp, "explode", 0.0):
            vp.set_explode(0.0)
        # what the app does at the start of every frame
        vp._physical_size = lambda W=W, H=H: (W, H)
        vp.devicePixelRatioF = lambda dpr=dpr: dpr
        c.aspect = W / H
        vp._sync_settings()
        if vmodel.clip is not None and vp.anim_kind() == "clip":
            vmodel.evaluate(vp.anim_t, vp.reveal_state, _smooth(vp.reveal_amount))
        else:
            vmodel.evaluate(vmodel.clip_range[0], vp.reveal_state, _smooth(vp.reveal_amount))
        img = vp.grab_image(1.0)
        if img is None:
            print(f"{shot['id']}: renderer returned nothing", file=sys.stderr)
        return img, W, H, unmatched

    def close(self):
        self.vp.release_gl()


# ---------------------------------------------------------------------------------------------------- infer hidden
def _gray_small(img, w):
    import numpy as np
    from PIL import Image
    im = img if isinstance(img, Image.Image) else Image.fromarray(np.ascontiguousarray(img))
    im = im.convert("L")
    h = max(2, int(round(w * im.height / im.width)))
    return np.asarray(im.resize((w, h), Image.BILINEAR), dtype=np.float32)


def cmd_infer_hidden(args):
    """Old shots do not record hidden parts. Greedy guess per shot: hide the whole part that makes the render most like
    the shot's own PNG, repeat until no hide helps enough. Writes 'hidden' (part names) into shots.json for every shot
    whose 'hidden' is empty (or all of them with --redo), with 'hidden_inferred': true."""
    import numpy as np
    from PIL import Image
    shots = load_shots(args.shots)
    config = setup_app_environment()
    W = int(args.width)
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    changed = 0
    with RenderLock():
        r = ShotRenderer(args.model, config)
        if r.error:
            print(r.error, file=sys.stderr)
            return 2
        names = r.item_names()
        # candidates: every part alone, plus families of numbered parts ("Umbrella cell 01 cover" .. "19 cover", and
        # everything named "Umbrella cell ..."), since a peeled layer is often many numbered parts hidden together
        groups = {}
        for i, n in enumerate(names):
            groups.setdefault(re.sub(r"\d+", "#", n), []).append(i)
            m = re.match(r"^(.*?)\s*\d", n)
            if m and m.group(1):
                groups.setdefault(m.group(1).strip() + " *", []).append(i)
            for g, members in list(groups.items()):
                if g.endswith(" *") and n.startswith(g[:-2]) and i not in members:
                    members.append(i)
        candidates = [(i,) for i in range(len(names))]
        candidates += [tuple(sorted(set(v))) for v in groups.values() if len(set(v)) > 1]
        candidates = list(dict.fromkeys(candidates))
        for shot in shots:
            if (shot.get("hidden") and not args.redo) or (only and shot["id"] not in only):
                continue
            src = Path(shot["source_png"])
            if not src.is_file():
                continue
            t1 = time.perf_counter()
            target = _gray_small(Image.open(src), W)

            def score(hidden):
                img, *_ = r.render(shot, W, hidden_items=hidden, quiet=True)
                if img is None:
                    return None, None
                g = _gray_small(img, W)
                if g.shape != target.shape:
                    g = np.asarray(Image.fromarray(g).resize(target.shape[::-1]), dtype=np.float32)
                return float(np.abs(g - target).mean()), g

            hidden = []
            best, cur = score(hidden)
            if best is None:
                continue
            start = best
            alive = list(candidates)
            for _round in range(int(args.max_parts)):
                trial = []
                for cand in alive:
                    add = [i for i in cand if i not in hidden]
                    if not add:
                        continue
                    d, g = score(hidden + add)
                    if d is None or float(np.abs(g - cur).mean()) < 1e-3:   # hiding it changes nothing in this view
                        continue
                    trial.append((d, len(cand), cand))
                alive = [t[2] for t in trial]
                if not trial:
                    break
                need = max(float(args.gain), best * float(args.rel_gain))
                d, _n, cand = min(trial)
                if best - d < need:
                    # one hide alone may not help when two layers cover the same spot (plaques over umbrella cells):
                    # try every pair of hides that change this view
                    pair = None
                    for a in range(len(alive)):
                        for b in range(a + 1, len(alive)):
                            both = list(dict.fromkeys(alive[a] + alive[b]))
                            dd, _g = score(hidden + [i for i in both if i not in hidden])
                            if dd is not None and (pair is None or dd < pair[0]):
                                pair = (dd, tuple(both))
                    if pair is None or best - pair[0] < need:
                        break
                    d, cand = pair
                hidden.extend(i for i in cand if i not in hidden)
                alive = [c for c in alive if any(i not in hidden for i in c)]
                best, cur = score(hidden)
            # families over-hide (the nuclei came off with the umbrella cells): show again every part whose return
            # does not make the match worse
            again = True
            while again and hidden:
                again = False
                for i in list(hidden):
                    rest = [j for j in hidden if j != i]
                    d, _g = score(rest)
                    if d is not None and d <= best + 0.02:
                        hidden, best, again = rest, d, True
            shot["hidden"] = [names[i] for i in hidden]
            shot["hidden_inferred"] = True
            shot["infer_diff"] = [round(start, 2), round(best, 2)]
            changed += 1
            print(f"{shot['id']}: diff {start:.1f} -> {best:.1f} in {time.perf_counter() - t1:.1f}s  "
                  f"hidden {shot['hidden']}", flush=True)
        r.close()
    Path(args.shots).write_text(json.dumps(shots, indent=1, ensure_ascii=False), encoding="utf8")
    print(f"updated {changed} shots in {args.shots}")
    return 0


# ---------------------------------------------------------------------------------------------------- compare
def cmd_compare(args):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
    qapp = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    from PySide6.QtGui import QFontDatabase
    family = "Segoe UI"
    for f in (Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf",
              Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"):
        if f.is_file():                       # the offscreen platform has no font database of its own
            fid = QFontDatabase.addApplicationFont(str(f))
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if fams:
                family = fams[0]
                break
    tiles = []
    for t in args.tile:
        label, _, d = t.partition("=")
        tiles.append((label.strip(), d.strip()))
    shots = load_shots(args.shots)
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        shots = [s for s in shots if s["id"] in want]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    W = int(args.width)
    per_row = 5
    pad = max(8, W // 150)
    font_px = max(14, W // 90)
    label_font = QFont(family)
    label_font.setPixelSize(font_px)
    label_font.setBold(True)
    note_font = QFont(family)
    note_font.setPixelSize(font_px)
    n_cols = min(per_row, len(tiles))
    tile_w = (W - pad * (n_cols + 1)) // n_cols
    for shot in shots:
        images = []
        for label, d in tiles:
            p = Path(shot["source_png"]) if d == "source" else Path(d) / f"{shot['id']}.png"
            img = QImage(str(p)) if p.is_file() else QImage()
            images.append(None if img.isNull() else img.scaledToWidth(tile_w, Qt.SmoothTransformation))
        have = [i for i in images if i is not None]
        default_h = have[0].height() if have else int(tile_w * 0.5625)
        note = (shot.get("note") or "").strip()
        probe = QImage(1, 1, QImage.Format_RGB32)
        pp = QPainter(probe)
        pp.setFont(note_font)
        note_h = 0
        if note:
            note_h = int(pp.boundingRect(QRectF(0, 0, W - 2 * pad, 10000), Qt.TextWordWrap, note).height()) + 2 * pad
        pp.end()
        label_h = font_px + pad
        rows = [list(range(i, min(i + per_row, len(tiles)))) for i in range(0, len(tiles), per_row)]
        row_h = [max((images[i].height() if images[i] is not None else default_h) for i in r) for r in rows]
        H = note_h + sum(label_h + h + pad for h in row_h) + pad
        canvas = QImage(W, H, QImage.Format_RGB32)
        canvas.fill(QColor("#20252b"))
        p = QPainter(canvas)
        p.setRenderHint(QPainter.TextAntialiasing)
        y = 0
        if note:
            p.fillRect(0, 0, W, note_h, QColor("#3a3320"))
            p.setFont(note_font)
            p.setPen(QColor("#ffe9a8"))
            p.drawText(QRectF(pad, pad, W - 2 * pad, note_h - pad), Qt.TextWordWrap, note)
            y = note_h
        for r, rh in zip(rows, row_h):
            for col, i in enumerate(r):
                x = pad + col * (tile_w + pad)
                p.setFont(label_font)
                p.setPen(QColor("#e8edf2"))
                p.drawText(QRectF(x, y, tile_w, label_h), Qt.AlignLeft | Qt.AlignVCenter, tiles[i][0])
                if images[i] is not None:
                    p.drawImage(x, y + label_h, images[i])
                else:
                    p.fillRect(x, y + label_h, tile_w, default_h, QColor("#6b7178"))
                    p.setPen(QColor("#ffffff"))
                    p.drawText(QRectF(x, y + label_h, tile_w, default_h), Qt.AlignCenter, "missing")
            y += label_h + rh + pad
        p.end()
        canvas.setText(STAMP_KEY, json.dumps({"shot": shot["id"], "tool": "review_shots.py compare", "time": time.time()}))
        canvas.save(str(out / f"{shot['id']}.png"), "PNG")
    print(f"wrote {len(shots)} composites to {out}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("init", help="list review-shot PNGs into shots.json")
    a.add_argument("inputs", nargs="+")
    a.add_argument("--out", required=True)
    b = sub.add_parser("render", help="replay each shot's camera on a model with the app's own viewer")
    b.add_argument("--model", required=True)
    b.add_argument("--shots", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--only", default="")
    b.add_argument("--width", type=int, default=1024)
    b.add_argument("--hide", nargs="+", action="extend", default=[])
    c = sub.add_parser("compare", help="side-by-side composites")
    c.add_argument("--shots", required=True)
    c.add_argument("--tile", action="append", required=True, metavar="LABEL=DIR")
    c.add_argument("--out", required=True)
    c.add_argument("--width", type=int, default=2400)
    c.add_argument("--only", default="")
    e = sub.add_parser("infer-hidden", help="guess each shot's hidden parts by matching its own PNG")
    e.add_argument("--model", required=True)
    e.add_argument("--shots", required=True)
    e.add_argument("--only", default="")
    e.add_argument("--width", type=int, default=320)
    e.add_argument("--max-parts", type=int, default=12)
    e.add_argument("--gain", type=float, default=0.4)
    e.add_argument("--rel-gain", type=float, default=0.02)
    e.add_argument("--redo", action="store_true")
    args = ap.parse_args(argv)
    return {"init": cmd_init, "render": cmd_render, "compare": cmd_compare,
            "infer-hidden": cmd_infer_hidden}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
