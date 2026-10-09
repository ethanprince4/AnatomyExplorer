"""Load user-owned local models directly into the native CPU viewer model.

No builders, payload hashes, lineage receipts, or complete-library checks. Shape
checks exist only where the renderer needs valid buffers. Optional stale sidecars
produce warnings and do not prevent other models or versions from opening.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import uuid

import numpy as np

from ..viewer.part_guide import load_part_guide


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _check(token):
    if token is not None:
        for name in ("check", "checkpoint", "raise_if_cancelled"):
            method = getattr(token, name, None)
            if callable(method):
                method()
                return


def _path(value, root):
    value = _get(value, "path", value)
    path = Path(value)
    return path if path.is_absolute() else Path(root) / path


def _json(value, root, warnings, label):
    if value is None:
        return {}
    if isinstance(value, dict) and "path" not in value:
        return deepcopy(value)
    try:
        return json.loads(_path(value, root).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        warnings.append(f"{label} unavailable: {exc}")
        return {}


def _normals(vertices, faces):
    normals = np.zeros_like(vertices, dtype=np.float64)
    tri = vertices[faces].astype(np.float64)
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    # One weighted bincount per axis over the three corner lists in order: the same additions, in the same order,
    # as three np.add.at passes, so the result is bit-identical and several times faster.
    corners = np.concatenate([faces[:, 0], faces[:, 1], faces[:, 2]])
    for axis in range(3):
        normals[:, axis] = np.bincount(corners, weights=np.tile(cross[:, axis], 3), minlength=len(normals))
    lengths = np.linalg.norm(normals, axis=1)
    good = lengths > 0
    normals[good] /= lengths[good, None]
    normals[~good] = [0, 0, 1]
    return normals.astype(np.float32)


def _colors(values, count, warnings, name):
    if values is None:
        return None
    source = np.asarray(values)
    color = source.astype(np.float32)
    if source.dtype.kind in "ui":
        color /= np.iinfo(source.dtype).max
    if color.ndim == 2 and color.shape == (count, 4):
        color = color[:, :3]
    if color.shape != (count, 3) or not np.isfinite(color).all() or np.any((color < 0) | (color > 1)):
        warnings.append(f"{name}: incompatible vertex colors omitted; material color retained")
        return None
    return np.ascontiguousarray(color)


def decode_local_npz(path, token=None, warnings=None):
    warnings = warnings if warnings is not None else []
    rows = []
    with np.load(path, allow_pickle=False) as archive:
        keys = set(archive.files)
        raw_meta = archive["meta"]
        metadata = json.loads(raw_meta.tobytes().decode("utf-8"))
        for i, original in enumerate(metadata["parts"]):
            _check(token)
            row = deepcopy(original)
            row.setdefault("name", f"Part {i + 1}")
            raw = archive[f"p{i}"]
            if raw.dtype.kind == "u" and f"b{i}" in keys:
                lo, span = archive[f"b{i}"]
                vertices = (raw.astype(np.float64) / 65535.0 * span + lo).astype(np.float32)
            else:
                vertices = raw.astype(np.float32, copy=False)
            if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
                raise ValueError(f"{row['name']}: unreadable vertex positions")
            indices = archive[f"i{i}"]
            if indices.ndim == 2 and indices.shape[1] == 3:
                faces = indices.astype(np.int64)
            else:
                faces = np.cumsum(indices.astype(np.int64)).reshape(-1, 3)
            if faces.size and (faces.min() < 0 or faces.max() >= len(vertices)):
                raise ValueError(f"{row['name']}: triangle refers to a missing vertex")
            raw_normals = archive[f"n{i}"] if f"n{i}" in keys else None
            normals = raw_normals.astype(np.float32, copy=False) if raw_normals is not None else None
            if raw_normals is not None and raw_normals.dtype.kind in "iu":
                normals /= 127.0
            if normals is None or normals.shape != vertices.shape or not np.isfinite(normals).all():
                warnings.append(f"{row['name']}: missing or incompatible normals regenerated")
                normals = _normals(vertices, faces)
            else:
                length = np.linalg.norm(normals, axis=1)
                good = length > 1e-20
                normals[good] /= length[good, None]
                if not good.all():
                    normals[~good] = _normals(vertices, faces)[~good]
                    warnings.append(f"{row['name']}: zero normals repaired")
            colors = _colors(archive[f"c{i}"] if f"c{i}" in keys else None, len(vertices), warnings, row["name"])
            rows.append((row, vertices, normals, faces, colors))
    return metadata, rows


def _prune_selectors(value, names, warnings, context="controls"):
    selector_lists = {"hidden", "visible_parts", "part_names", "label_keys", "show_parts", "hide_parts", "selected_parts"}
    if isinstance(value, list):
        return [_prune_selectors(v, names, warnings, context) for v in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in selector_lists and isinstance(item, list) and all(isinstance(x, str) for x in item):
            absent = sorted(set(item) - names)
            if absent:
                warnings.append(f"{context}: removed-part references ignored: {', '.join(absent)}")
            result[key] = [x for x in item if x in names]
        elif key == "hosts" and isinstance(item, dict):
            absent = set(item) - names
            if absent:
                warnings.append(f"{context}: removed host references ignored: {', '.join(sorted(absent))}")
            result[key] = {k: deepcopy(v) for k, v in item.items() if k in names}
        else:
            result[key] = _prune_selectors(item, names, warnings, context)
    return result


def _companions(descriptor):
    value = _get(descriptor, "companions", {}) or {}
    if isinstance(value, dict):
        return value
    return {_get(v, "role", str(i)): v for i, v in enumerate(value)}


def _controls(entry, descriptor, metadata, decoded, warnings):
    from .anatomy_runtime_adapters import controls as helpers
    here = Path(helpers.__file__).parent
    root = _get(descriptor, "root", Path(_get(descriptor.primary, "path")).parent)
    companions = _companions(descriptor)
    supplied = {role: _json(value, root, warnings, role) for role, value in companions.items()
                if str(_get(value, "path", value)).lower().endswith(".json") or (isinstance(value, dict) and "path" not in value)}
    controls = _json(_get(descriptor, "runtime_controls", companions.get("runtime_controls")), root, warnings, "Runtime controls")
    names = [r[0]["name"] for r in decoded]
    if _get(_get(descriptor, "record", {}), "static_recipe", False):
        # Final standalone models carry their own presentation. Older organ
        # hooks and recipes describe different parts and must not leak into it.
        native = helpers._native(metadata, entry.id)
        native.update(helpers._native(supplied.get("teaching_recipe", {}), entry.id))
        native.update(deepcopy(controls.get("native", {})))
        native.setdefault("summary", getattr(entry, "summary", ""))
        native.setdefault("scale_note", getattr(entry, "scale_note", ""))
        native.setdefault("metres_per_unit", 0.0)
        if not isinstance(native.get("home_view"), (list, tuple)):
            native["home_view"] = [-.62, .42]
        native.setdefault("cutaway", [[1, 0, 0], [0, 0, 1]])
        native.setdefault("cut_at", [0, 0])
        native.setdefault("cut_on", False)
        native.setdefault("viewer_cameras", {})
        native["labels_on_open"] = False
        viewer = deepcopy(controls.get("viewer", {}))
        viewer.setdefault("mixed_schematic_scale", entry.id in helpers.MIXED_MODELS)
        viewer.setdefault("scale_note", native["scale_note"])
        return _prune_selectors(dict(native=native, viewer=viewer, documents=[],
            teaching_views=[], functional_sequences=[], verified_documents=supplied,
            source_part_names=names, part_names=names,
            parts=[deepcopy(row) for row, *_ in decoded]), set(names), warnings)
    controls["source_part_names"] = [p["name"] for p in controls.get("parts", [])] or list(names)
    inherited = json.loads((here / "inherited_defaults.json").read_text(encoding="utf-8"))
    native = deepcopy(inherited.get(entry.id, {}))
    native.update(deepcopy(helpers.EXPLICIT_DEFAULTS.get(entry.id, {})))
    docs = deepcopy(controls.get("documents", []))
    if not docs:
        folder = here / "source_data" / entry.id
        for path in sorted(folder.glob("document_*.json"), key=lambda p: int(p.stem.split("_")[-1])):
            docs.append(json.loads(path.read_text(encoding="utf-8")))
    views, sequences = [], []
    for document in docs:
        native.update(helpers._native(document, entry.id))
        if not views:
            views = helpers._views(document)
        sequences.extend(helpers._sequences(document))
    native.update(helpers._native(metadata, entry.id))
    for role in ("comparison", "native_defaults", "teaching_recipe", "teaching_views", "native_controls", "viewer"):
        if role in supplied:
            native.update(helpers._native(supplied[role], entry.id))
            views = helpers._views(supplied[role]) or views
    native.update(deepcopy(controls.get("native", {})))
    views = controls.get("teaching_views", views)
    sequences = controls.get("functional_sequences", sequences)
    cameras = deepcopy(native.get("viewer_cameras", {}))
    for view in views:
        camera = deepcopy(view.get("native_camera", view.get("camera", {})))
        if not camera:
            continue
        name = helpers._view_name(view, entry.id)
        if not name:
            continue
        if "visible_parts" in view:
            camera["hidden"] = [n for n in names if n not in view["visible_parts"]]
        if "hosts" in view:
            camera["hidden"] = [n for n in names if not view["hosts"].get(n, {}).get("visible", False)]
        for field in ("cut_on", "labels_on", "sections", "tissue_opacity_percent"):
            if field in view:
                camera[field] = deepcopy(view[field])
        camera.setdefault("note", view.get("caption", view.get("purpose", "")))
        cameras[name] = camera
    native["viewer_cameras"] = cameras
    native.setdefault("summary", getattr(entry, "summary", ""))
    native.setdefault("scale_note", getattr(entry, "scale_note", "") or "Scale not supplied for this local model.")
    native.setdefault("metres_per_unit", 0.0)
    native.setdefault("home_view", [-.62, .42])
    native.setdefault("cutaway", [[1, 0, 0], [0, 0, 1]])
    native.setdefault("cut_at", [0, 0])
    native.setdefault("cut_on", False)
    if native.get("start_view") not in cameras:
        native["start_view"] = next(iter(cameras), None)
    controls.update(native=native, documents=docs, teaching_views=views, functional_sequences=sequences,
                    parts=[deepcopy(r[0]) for r in decoded], part_names=names,
                    verified_documents={**controls.get("verified_documents", {}), **supplied})
    controls.setdefault("viewer", {})
    controls["viewer"].setdefault("mixed_schematic_scale", entry.id in helpers.MIXED_MODELS)
    controls["viewer"].setdefault("scale_note", native["scale_note"])
    return _prune_selectors(controls, set(names), warnings) if names else controls


def _load_color_companion(descriptor, decoded, warnings):
    companions = _companions(descriptor)
    if "colors" not in companions:
        return
    root = _get(descriptor, "root", Path(descriptor.primary.path).parent)
    contract = _json(companions.get("color_contract"), root, warnings, "Color mapping")
    rows = {row.get("name"): row for row in contract.get("parts", [])}
    try:
        with np.load(_path(companions["colors"], root), allow_pickle=False) as archive:
            for i, (meta, vertices, normals, faces, inline) in enumerate(decoded):
                if inline is not None:
                    continue
                key = rows.get(meta["name"], {}).get("array_key", f"c{i}")
                if key not in archive:
                    continue
                colors = _colors(archive[key], len(vertices), warnings, meta["name"])
                decoded[i] = (meta, vertices, normals, faces, colors)
    except (OSError, ValueError, KeyError) as exc:
        warnings.append(f"Optional color companion unavailable: {exc}")


def _animation(descriptor, micro, parts, controls, warnings):
    companions = _companions(descriptor)
    if "animation" not in companions:
        return
    root = descriptor.root
    source_names = controls.get("source_part_names", [p.name for p in parts])
    attached = 0
    try:
        with np.load(_path(companions["animation"], root), allow_pickle=False) as archive:
            for part in parts:
                if part.name not in source_names:
                    warnings.append(f"{part.name}: no source animation mapping; displayed statically")
                    continue
                index = source_names.index(part.name)
                if f"m{index}" not in archive:
                    continue
                morph = archive[f"m{index}"].astype(np.float32)
                phase = archive[f"f{index}"].copy()
                count = len(part.mesh.arrays()[0])
                if morph.ndim != 3 or morph.shape[0] != count or morph.shape[2] != 3 or phase.shape != (count,) or not np.isfinite(morph).all() or not np.isfinite(phase).all():
                    warnings.append(f"{part.name}: stale vertex animation disabled; geometry remains available")
                    continue
                part.anim = {"morph": morph, "phase": phase}
                attached += 1
        if attached and descriptor.model_id == "pancreas":
            from .anatomy_runtime_adapters.pancreas_animation import make_animation
            micro.animation = make_animation()
        elif attached:
            warnings.append("Animation channels are present but no compatible native animation controller was supplied")
    except (OSError, ValueError, KeyError) as exc:
        warnings.append(f"Optional animation unavailable: {exc}")


def _component_descriptor(entry, descriptor, warnings):
    component = getattr(entry, 'component', 'main')
    if component == 'main':return descriptor, None
    components = _get(descriptor, 'components', {}) or {}
    record = components.get(component, _companions(descriptor).get(component))
    root = Path(_get(descriptor, 'root', Path(descriptor.primary.path).parent))
    try:
        if record is None:raise ValueError('No saved component was imported')
        record = dict(record) if isinstance(record, dict) else {'path':record}
        primary = record.get('primary', record)
        path = _path(primary, root)
        if path.suffix.lower() not in ('.npz', '.glb') or not path.is_file():
            raise ValueError('The saved component file is missing or unsupported')
        child = SimpleNamespace(model_id=entry.id, variant=entry.variant, root=root,
            primary=SimpleNamespace(path=path, format=path.suffix[1:]),
            companions=record.get('companions', {}), runtime_controls=record.get('runtime_controls'),
            token=(*_get(descriptor,'token',(entry.id,entry.variant)),component), record=record)
        return child, component
    except (OSError,ValueError,TypeError,KeyError) as exc:
        warnings.append(f'{component} unavailable: {exc}. Showing the main model instead.')
        entry.component='main'
        return descriptor, None


def _component_controls(entry, descriptor, metadata, decoded, warnings):
    """A separate scene must never inherit the organ's cameras or physical ruler."""
    from .anatomy_runtime_adapters.components import INSET_SCALE_NOTE
    controls = _json(_get(descriptor,'runtime_controls'),descriptor.root,warnings,'Component controls')
    names=[row['name'] for row,*_ in decoded]
    native=dict(summary='Separate enlarged cell inset.', scale_note=INSET_SCALE_NOTE,
                metres_per_unit=0.,cut_on=False,labels_on_open=False,home_view=[-.62,.42],
                cutaway=[[1,0,0],[0,0,1]],cut_at=[0,0])
    pose={'type':'ORTHO','position':[2.4,2.8,3.2],'target':[0,.1,0],'ortho_width':2.7,'cut_on':False}
    native['viewer_cameras']={
        'V1':dict(pose,title='Cell walls and open lumens',hidden=[n for n in names if n.endswith('/ nucleus') or n.endswith('/ basement membrane')]),
        'V2':dict(pose,title='Basal lamina and nuclei',hidden=[])}
    native['start_view']='V1'
    native.update(deepcopy(controls.get('native',{})))
    native['metres_per_unit']=0.  # Component coordinates are an enlarged schematic space.
    controls.update(native=native,parts=[deepcopy(row) for row,*_ in decoded],part_names=names,
        documents=[],verified_documents={},teaching_views=controls.get('teaching_views',[]),
        functional_sequences=controls.get('functional_sequences',[]),source_part_names=names,
        viewer={'mixed_schematic_scale':True,'scale_note':native['scale_note']})
    return _prune_selectors(controls,set(names),warnings)


def prepare_local_model(entry, token=None):
    """Open a library model. The prepared-model cache is used when it holds this exact file; any trouble with it
    (stale, damaged, mismatched) falls back to the ordinary decode-and-build path without a message."""
    from ..load_control import LoadCancelled
    try:
        return _prepare_local_model(entry, token, True)
    except LoadCancelled:
        raise
    except Exception:
        if not getattr(entry, "_prepared_used", False):
            raise
    entry._prepared_used = False
    return _prepare_local_model(entry, token, False)


def _prepare_local_model(entry, token, use_cache):
    from .anatomy_runtime_adapters.runtime import NativeBackend, _prepare_hooks, _hook, _resolve_fit_cameras, _retire_native_backing
    _check(token)
    descriptor = getattr(entry, "descriptor", None) or entry.store.resolve(entry.id, entry.variant)
    entry.descriptor = descriptor
    warnings = []
    descriptor, component = _component_descriptor(entry, descriptor, warnings)
    standalone = bool(_get(_get(descriptor, "record", {}), "static_recipe", False))
    root = Path(_get(descriptor, "root", Path(descriptor.primary.path).parent))
    path = _path(descriptor.primary, root)
    # Some older native teaching hooks call this field 'sha256' but only use a
    # 64-hex string as a view/session binding. This random opaque session token
    # is NOT a checksum, is never persisted as evidence, and binds no file bytes.
    local_binding = uuid.uuid4().hex + uuid.uuid4().hex
    companions = _companions(descriptor)
    assets = {role: SimpleNamespace(path=_path(value, root)) for role, value in companions.items()
              if not isinstance(value, dict) or "path" in value}
    bound = SimpleNamespace(model_id=entry.id, variant=entry.variant, label=getattr(entry, "label", entry.variant),
                            root=root, token=_get(descriptor, "token", (entry.id, entry.variant, str(path))),
                            companions=companions, assets=assets,
                            primary=SimpleNamespace(path=path, format=path.suffix.lower().lstrip("."), sha256=local_binding),
                            generation_id="local", descriptor_sha256=None)
    backend = NativeBackend()
    if path.suffix.lower() == ".npz":
        from ..viewer import prepared_cache
        guide = load_part_guide(entry.id)
        retired = guide.excluded_groups
        key = prepared_cache.make_key(path, [(role, a.path) for role, a in sorted(assets.items())], retired)             if use_cache and not component else None
        cached = prepared_cache.lookup(key) if key else None
        entry._prepared_used = cached is not None
        if cached is not None:
            # stand-in arrays of the recorded sizes: the real ones come memory-mapped from the cache
            with np.load(path, allow_pickle=False) as archive:
                metadata = json.loads(archive["meta"].tobytes().decode("utf-8"))
            decoded = prepared_cache.stub_rows(metadata, cached.manifest)
            warnings.extend(cached.decode_warnings)
        else:
            metadata, decoded = decode_local_npz(path, token, warnings)
        sizes = [(len(v), len(f), c is not None) for _, v, _, f, c in decoded]
        kept = list(range(len(decoded)))
        if retired:
            # Parts a model's guide retires (the adrenal gland that came with the kidney); references to them in
            # views and recipes are pruned like any removed part.
            kept = [i for i, row in enumerate(decoded) if row[0].get("group", "Model") not in retired]
            decoded = [decoded[i] for i in kept]
            metadata = {**metadata, "parts": [p for p in metadata.get("parts", []) if p.get("group", "Model") not in retired]}
        if cached is None:
            _load_color_companion(descriptor, decoded, warnings)
        if key and cached is None:
            for slot, row in zip(kept, decoded):
                sizes[slot] = (sizes[slot][0], sizes[slot][1], row[4] is not None)
            plan = dict(key=key, source=dict(path=str(path)), decode=sizes, warnings=list(warnings))
        else:
            plan = None
        controls = (_component_controls(entry, descriptor, metadata, decoded, warnings) if component else
                    _controls(entry, descriptor, metadata, decoded, warnings))
        from app.micro.base import Part
        from app.micro.geometry import Mesh
        parts = []
        for row, vertices, normals, faces, colors in decoded:
            _check(token)
            part = Part(row["name"], row.get("group", "Model"), row.get("color", "#c98f88"),
                        Mesh().add(vertices, faces, normals), row.get("description", ""),
                        **{key: row[key] for key in ("alpha", "category", "label", "rank", "clip", "bulk", "detail") if key in row})
            for key, value in row.items():
                if key not in ("mesh", "anim"):
                    setattr(part, key, deepcopy(value))
            parts.append(part)
        micro = backend.micro(entry.id, entry.name, controls["native"].get("summary", ""), parts)
        for key, value in controls["native"].items():
            setattr(micro, key, deepcopy(value))
        colors = {row["name"]: color for row, v, n, f, color in decoded if color is not None}
        linear = {row["name"]: row["color_linear"] for row, *_ in decoded if "color_linear" in row}
        def vertex_colors(name, positions):
            if name in colors:
                return colors[name]
            if name in linear:
                return np.broadcast_to(np.asarray(linear[name], dtype=np.float32), (len(positions), 3))
            return None
        micro.viewer_vertex_colors = vertex_colors
        micro.runtime_descriptor = bound
        _animation(bound, micro, parts, controls, warnings)
        hooks_available = not standalone
        try:
            if not component and not standalone:_prepare_hooks(bound, micro, controls, parts)
        except Exception as exc:
            hooks_available = False
            warnings.append(f"Some model-specific controls are unavailable for these parts: {exc}")
        if cached is not None:
            # parts carry stand-in meshes: the builder only takes sizes from them, the arrays come from the cache
            for part, (row, vertices, _n, faces, _c) in zip(parts, decoded):
                part.mesh = prepared_cache.StubMesh(len(vertices), len(faces))
            from app.viewer.procedural import ProceduralModel
            with prepared_cache.using(cached):
                model = ProceduralModel(micro, parts=parts)
            model.lod = cached.lod
        else:
            model = backend.procedural(micro, parts)
            model._prepared_plan = plan
        try:
            if not standalone and entry.id == "tooth" and controls["documents"]:
                _hook(entry.id, "teaching").apply_to_viewer_model(model, controls["documents"][0], model_id=entry.id)
            elif not standalone and entry.id == "tongue_papillae" and controls["documents"]:
                _hook(entry.id, "teaching").install_native_metadata(model, contract=controls["documents"][0], model_id=entry.id)
        except Exception as exc:
            warnings.append(f"Some teaching metadata could not follow the current parts: {exc}")
        model.metres_per_unit = float(controls["native"].get("metres_per_unit", 0))
        catalog = controls.get("verified_documents", {}).get("catalog", {})
        for item in model.items:
            display = catalog.get("parts", {}).get(item.key, {})
            if display.get("name"):
                item.name = display["name"]
            if not item.description and display.get("description"):
                item.description = display["description"]
            if display.get("atlas"):
                item.atlas = list(display["atlas"])
            if guide.names.get(item.key):
                # A readable name in place of a build label; the key and the old name still find the part.
                item.former_names = [item.name]
                item.name = guide.names[item.key]
        _retire_native_backing(model, [row for row, *_ in decoded])
    elif path.suffix.lower() == ".glb":
        from app.viewer.model import Model
        controls = (_component_controls(entry, descriptor, {}, [], warnings) if component else
                    _controls(entry, descriptor, {}, [], warnings))
        side = controls.get("verified_documents", {}).get("viewer")
        if isinstance(side, dict) and side:
            class LocalGLB(Model):
                def _load_sidecar(self):
                    return deepcopy(side)
            model = LocalGLB(path)
        else:
            model = Model(path)
        catalog = controls.get("verified_documents", {}).get("catalog")
        if catalog:
            from app.viewer.catalog import apply_meta
            apply_meta(model, catalog)
        names = {item.key for item in model.items}
        controls = _prune_selectors(controls, names, warnings)
        model.cameras = _prune_selectors(model.cameras, names, warnings, "GLB cameras")
        hooks_available = True
    else:
        raise ValueError("Local model must be NPZ or GLB")
    try:
        _resolve_fit_cameras(model, controls)
    except Exception as exc:
        warnings.append(f"An optional named-camera anchor is unavailable: {exc}")
    if not model.cameras:
        lo, hi = np.asarray(model.bounds_min), np.asarray(model.bounds_max)
        center = (lo + hi) * .5
        radius = max(float(np.linalg.norm(hi - lo)), .001)
        model.cameras = {"Home": {"position": (center + radius * np.array([1., .6, 1.5])).tolist(), "target": center.tolist(), "type": "PERSP", "fov_deg": 40, "hidden": []}}
    model.camera_order = list(model.cameras)
    controls["native"]["viewer_cameras"] = deepcopy(model.cameras)
    opening = controls["native"].get("start_view")
    if opening not in model.cameras:
        opening = model.sidecar.get("start_view")
    if opening not in model.cameras:
        opening = next(iter(model.cameras))
    controls["native"]["start_view"] = opening
    model.sidecar.update(deepcopy(controls.get("viewer", {})))
    model.sidecar.update(start_view=opening, variant=entry.variant, variant_label=bound.label, model_id=entry.id, local_library=True)
    if component:
        model.runtime_component_id = component
        model.runtime_component_descriptor = descriptor
        model.metres_per_unit = 0.
        model.sidecar["component_id"] = component
    model.runtime_controls = controls
    model.runtime_descriptor = bound
    model.runtime_identity = bound.token
    model.runtime_entry = entry
    model.runtime_hooks_available = hooks_available
    model.runtime_warnings = list(dict.fromkeys(warnings))
    entry.micro = SimpleNamespace(labels_on_open=controls["native"].get("labels_on_open", False))
    entry.scale_note = controls["native"].get("scale_note", getattr(entry, "scale_note", ""))
    _check(token)
    return model
