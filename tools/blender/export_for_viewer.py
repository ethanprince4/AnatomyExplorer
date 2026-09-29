"""Export a frozen microanatomy .blend to a viewer GLB plus a JSON sidecar (headless Blender).

    blender --background --factory-startup --python-exit-code 1 \
        --python tools/blender/export_for_viewer.py -- --blend <model.blend> [--name heart] [--out-dir models/heart]

The original .blend is never opened or saved: it is copied to a temp folder and the model collection is
appended from the copy (its sha256 is checked before and after). The GLB keeps everything at full resolution:

* every mesh, its one ``Contraction`` shape key as a glTF morph target, and one merged clip
  (``export_apply=False``, ``ACTIVE_ACTIONS``; applying modifiers would drop the shape keys);
* ``COLOR_0`` (the baked stripe) and the custom mesh attributes the materials read through Attribute nodes,
  renamed with a leading ``_`` so the exporter writes them (``fiber_u`` -> ``_fiber_u``);
* node extras (structure ids, labels, reveal tags) and the materials with the KHR extensions Blender writes.

The sidecar ``<name>.viewer.json`` carries what glTF cannot: the clip frame range, the state offsets (the
teased reveal is a frame driver, not an action), each material's procedural recipe (stripe period, band
threshold, band colours, contraction shortening; nucleus mottle; facing-weighted alpha), the harness camera
set (V0-V6 and the anchors) and the harness light rig and backdrop. All positions are in glTF space (Y up).

``--no-clip`` is for refined models that carry no animation (no shape keys, no actions): the GLB checks then
require no animations and no morph targets on any mesh (the custom-attribute check is unchanged), so a clip left in
the model fails the export, and the sidecar's ``clip`` is ``null``. Without the flag the clip checks are as above.
"""
import hashlib
import json
import math
import os
import shutil
import struct
import sys
import tempfile
import time
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                 # the repository: models land in models/<name>/


def say(msg):
    print(f"[export_for_viewer] {msg}", flush=True)


def parse_args():
    import argparse
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="export_for_viewer")
    p.add_argument("--blend", required=True, help="frozen model .blend (read-only; a temp copy is used)")
    p.add_argument("--name", default=None, help="output base name (default: the route folder name)")
    p.add_argument("--out-dir", default=None, help="default: models/<name> in the repository")
    p.add_argument("--collection", default="MODEL", help="root collection to export")
    p.add_argument("--manifest", default=None, help="route manifest.json (default: found next to the route)")
    p.add_argument("--views", default=None, help="harness views.json (default: found above the route)")
    p.add_argument("--stage-config", default=None, help="harness config.json (default: found above the route)")
    p.add_argument("--contract", default=None, help="brief contract.json (default: found above the route)")
    p.add_argument("--no-clip", action="store_true",
                   help="the model carries no clip: require no animations and no morph targets; sidecar clip null")
    return p.parse_args(argv)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def find_up(start, *rel):
    for p in [start, *start.parents]:
        cand = p.joinpath(*rel)
        if cand.is_file():
            return cand
    return None


def to_gltf(v):
    """Blender Z-up -> glTF Y-up (the exporter's export_yup conversion)."""
    x, y, z = (float(c) for c in v)
    return [x, z, -y]


def r6(v):
    return [round(float(c), 6) for c in v]


# --------------------------------------------------------------------------------------------------
# Materials: the procedural recipe the viewer's shader reproduces
# --------------------------------------------------------------------------------------------------

def _links_into(nt, node):
    return [l for l in nt.links if l.to_node == node]


def _links_from(nt, node):
    return [l for l in nt.links if l.from_node == node]


def _input_value(sock):
    v = sock.default_value
    try:
        return [float(x) for x in v]
    except TypeError:
        return float(v)


def stripe_recipe(nt):
    """The fibre-coordinate stripe (build.py myocyte_material + drive_band_width), or None."""
    attr = next((n for n in nt.nodes if n.type == "ATTRIBUTE" and n.attribute_type == "GEOMETRY"), None)
    if attr is None:
        return None
    rec = {"attribute": attr.attribute_name}
    div = next((l.to_node for l in _links_from(nt, attr)
                if l.to_node.type == "MATH" and l.to_node.operation == "DIVIDE"), None)
    if div is None:
        return None
    rec["period"] = float(div.inputs[1].default_value)
    gt = next((n for n in nt.nodes if n.type == "MATH" and n.operation == "GREATER_THAN"), None)
    mr = next((n for n in nt.nodes if n.type == "MAP_RANGE"), None)
    if gt is None or mr is None:
        return None
    thr = float(gt.inputs[1].default_value)
    lo, hi = float(mr.inputs["From Min"].default_value), float(mr.inputs["From Max"].default_value)
    # drive_band_width links the threshold to a DIVIDE whose numerator holds the rest threshold
    thr_div = next((l.from_node for l in _links_into(nt, gt) if l.to_socket == gt.inputs[1]), None)
    if thr_div is not None and thr_div.type == "MATH" and thr_div.operation == "DIVIDE":
        thr = float(thr_div.inputs[0].default_value)
    rec["threshold"] = thr                    # |fract(u/P) - 0.5| above this is I band
    rec["i_fraction"] = round(1.0 - 2.0 * thr, 6)
    rec["edge"] = round((hi - lo) / 2.0, 6) if hi > lo else 0.025
    band = next((l.to_node for l in _links_from(nt, mr)
                 if l.to_node.type == "MATH" and l.to_node.operation == "MULTIPLY"), None)
    rec["i_mix"] = float(band.inputs[1].default_value) if band is not None else 1.0
    mix = None
    if band is not None:
        mix = next((l.to_node for l in _links_from(nt, band) if l.to_node.type == "MIX"), None)
    if mix is None:
        return None
    rec["a_band_colour"] = _input_value(mix.inputs["A"])[:3]
    rec["i_band_colour"] = _input_value(mix.inputs["B"])[:3]
    val = next((n for n in nt.nodes if n.type == "VALUE"), None)
    shorten = 0.0
    if val is not None:
        mul = next((l.to_node for l in _links_from(nt, val)
                    if l.to_node.type == "MATH" and l.to_node.operation == "MULTIPLY"), None)
        if mul is not None:
            shorten = -float(mul.inputs[1].default_value)
    rec["shorten"] = shorten                  # threshold(w) = threshold / (1 - shorten * w): A bands keep width
    rec["weight"] = "clip"                    # the band change follows the Contraction weight
    return rec


def mottle_recipe(nt):
    noise = next((n for n in nt.nodes if n.type == "TEX_NOISE"), None)
    if noise is None:
        return None
    mr = next((l.to_node for l in _links_from(nt, noise) if l.to_node.type == "MAP_RANGE"), None)
    mix = next((l.to_node for l in _links_from(nt, mr) if l.to_node.type == "MIX"), None) if mr else None
    if mr is None or mix is None:
        return None
    coords = "object"
    for l in _links_into(nt, noise):
        if l.from_node.type == "TEX_COORD":
            coords = l.from_socket.name.lower()
    return {"scale": float(noise.inputs["Scale"].default_value),
            "detail": float(noise.inputs["Detail"].default_value),
            "roughness": float(noise.inputs["Roughness"].default_value),
            "from_min": float(mr.inputs["From Min"].default_value),
            "from_max": float(mr.inputs["From Max"].default_value),
            "colour_a": _input_value(mix.inputs["A"])[:3],
            "colour_b": _input_value(mix.inputs["B"])[:3],
            "coords": coords}


def facing_alpha_recipe(nt, bsdf):
    sock = bsdf.inputs["Alpha"]
    link = next((l for l in nt.links if l.to_socket == sock), None)
    if link is None:
        return None
    mr = link.from_node
    if mr.type != "MAP_RANGE":
        return None
    lw = next((l.from_node for l in _links_into(nt, mr) if l.from_node.type == "LAYER_WEIGHT"), None)
    if lw is None:
        return None
    return {"min": float(mr.inputs["To Min"].default_value), "max": float(mr.inputs["To Max"].default_value),
            "blend": float(lw.inputs["Blend"].default_value), "output": "facing"}


def describe_material(mat):
    out = {"name": mat.name}
    nt = mat.node_tree
    if nt is None:
        return out
    b = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if b is None:
        return out

    def val(name):
        s = b.inputs.get(name)
        return None if s is None else _input_value(s)

    base_linked = b.inputs["Base Color"].is_linked
    if not base_linked:
        out["base_colour"] = val("Base Color")[:3]
    for key, sock in (("roughness", "Roughness"), ("metallic", "Metallic"), ("ior", "IOR"),
                      ("specular_ior_level", "Specular IOR Level"), ("subsurface_weight", "Subsurface Weight"),
                      ("subsurface_scale", "Subsurface Scale"), ("coat_weight", "Coat Weight"),
                      ("sheen_weight", "Sheen Weight"), ("transmission_weight", "Transmission Weight"),
                      ("emission_strength", "Emission Strength")):
        v = val(sock)
        if v is not None:
            out[key] = round(v, 6)
    ss = b.inputs.get("Subsurface Radius")
    if ss is not None:
        out["subsurface_radius"] = r6(ss.default_value)
    if not b.inputs["Alpha"].is_linked:
        out["alpha"] = float(b.inputs["Alpha"].default_value)
    fa = facing_alpha_recipe(nt, b)
    if fa:
        out["facing_alpha"] = fa
    st = stripe_recipe(nt)
    if st:
        out["stripe"] = st
    mo = mottle_recipe(nt)
    if mo:
        out["mottle"] = mo
    out["render_method"] = getattr(mat, "surface_render_method", "")
    return out


# --------------------------------------------------------------------------------------------------
# Cameras (the harness's camera_for_view maths, output in glTF space)
# --------------------------------------------------------------------------------------------------

AXES = {"-X": (-1.0, 0.0, 0.0), "+X": (1.0, 0.0, 0.0), "-Y": (0.0, -1.0, 0.0),
        "+Y": (0.0, 1.0, 0.0), "-Z": (0.0, 0.0, -1.0), "+Z": (0.0, 0.0, 1.0)}


def _view_direction(az_deg, el_deg):
    az, el = math.radians(float(az_deg)), math.radians(float(el_deg))
    return Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))


def _half_tans(lens, sensor, aspect):
    aw, ah = aspect
    t = (float(sensor) / 2.0) / float(lens)
    return (t, t * ah / aw) if aw >= ah else (t * aw / ah, t)


def _project(loc, quat, lens, sensor, aspect, p):
    rot_t = quat.to_matrix().transposed()
    c = rot_t @ (Vector(p) - loc)
    depth = -c.z
    tx, ty = _half_tans(lens, sensor, aspect)
    if depth <= 1e-12:
        return math.inf, math.inf, depth
    return (c.x / depth) / tx, (c.y / depth) / ty, depth


def camera_record(kind, loc, quat, target, lens=50.0, sensor=36.0, ortho=0.0, clip=(0.01, 1000.0), note=""):
    up = quat @ Vector((0.0, 1.0, 0.0))
    rec = {"type": kind, "position": r6(to_gltf(loc)), "target": r6(to_gltf(target)), "up": r6(to_gltf(up)),
           "sensor_fit": "AUTO", "clip": list(clip)}
    if kind == "ORTHO":
        rec["ortho_width"] = round(float(ortho), 6)         # AUTO fit: the larger image dimension
    else:
        rec["fov_deg"] = round(math.degrees(2.0 * math.atan((sensor / 2.0) / lens)), 6)
        rec["lens_mm"], rec["sensor_mm"] = float(lens), float(sensor)
    if note:
        rec["note"] = note
    return rec


def camera_set(views, contract, manifest):
    envelope = (contract or views)["envelope_bu"]
    stage = (contract or views)["stage_bu"]
    aspect = tuple(float(v) for v in views.get("aspect", [16, 9]))
    clip = tuple(float(v) for v in views.get("clip", [0.01, 1000]))
    margin_default = float(views.get("margin", 0.05))
    cams = {}
    for name, view in views["views"].items():
        kind = view["type"]
        if kind == "ORTHO":
            look = Vector(AXES[view["look"]])
            target = Vector(view.get("target", [0, 0, 0]))
            ortho = (float(view["visible_height_bu"]) * aspect[0] / aspect[1]
                     if "visible_height_bu" in view else float(view["ortho_scale"]))
            axis = max(range(3), key=lambda i: abs(look[i]))
            back = float(stage[axis]) / 2.0 + float(views.get("ortho_distance_bu", 100.0))
            loc = target - look * back
            quat = look.to_track_quat("-Z", "Y")
            cams[name] = camera_record("ORTHO", loc, quat, target, ortho=ortho, clip=clip)
            continue
        lens, sensor = float(view["lens_mm"]), float(view["sensor_mm"])
        tx, _ = _half_tans(lens, sensor, aspect)
        if "frame_width_bu" in view:
            look = Vector(AXES[view["look"]])
            target = Vector(view["target"])
            dist = (float(view["frame_width_bu"]) / 2.0) / tx
            loc = target - look * dist
            cams[name] = camera_record("PERSP", loc, look.to_track_quat("-Z", "Y"), target, lens, sensor, clip=clip)
            continue
        box = {"envelope": envelope, "stage": stage}[view["fit"]]
        hx, hy, hz = (float(e) / 2.0 for e in box)
        corners = [Vector((sx * hx, sy * hy, sz * hz)) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
        d = _view_direction(view["azimuth_deg"], view["elevation_deg"])
        quat = (-d).to_track_quat("-Z", "Y")
        limit = 1.0 - float(view.get("margin", margin_default))

        def fits(dist):
            loc_ = d * dist
            for p in corners:
                x, y, depth = _project(loc_, quat, lens, sensor, aspect, p)
                if depth <= 1e-6 or abs(x) > limit or abs(y) > limit:
                    return False
            return True

        lo, hi = 0.0, 1.0
        while not fits(hi):
            hi *= 2.0
        for _ in range(30):
            mid = 0.5 * (lo + hi)
            if fits(mid):
                hi = mid
            else:
                lo = mid
        cams[name] = camera_record("PERSP", d * hi, quat, Vector((0, 0, 0)), lens, sensor, clip=clip)
    rule = views.get("anchor_rule")
    for anc in (manifest or {}).get("anchors", []) if rule else []:
        base = views["views"][rule.get("direction", "V1")]
        d = _view_direction(base["azimuth_deg"], base["elevation_deg"])
        _, ty = _half_tans(base["lens_mm"], base["sensor_mm"], aspect)
        dist = float(rule["radius_bu"]) / math.sin(float(rule["fill_fraction_of_height"]) * math.atan(ty))
        target = Vector(anc["location"])
        rec = camera_record("PERSP", target + d * dist, (-d).to_track_quat("-Z", "Y"), target,
                            base["lens_mm"], base["sensor_mm"], clip=clip, note=anc.get("role", ""))
        if anc.get("state"):
            rec["state"] = anc["state"]
        cams[anc["id"]] = rec
    return cams


# --------------------------------------------------------------------------------------------------
# GLB check
# --------------------------------------------------------------------------------------------------

def glb_json(path):
    with open(path, "rb") as fh:
        data = fh.read(1 << 24)
    magic, version, _length = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF" and version == 2, "not a GLB 2.0 file"
    n, kind = struct.unpack_from("<II", data, 12)
    assert kind == 0x4E4F534A, "first chunk is not JSON"
    return json.loads(data[20:20 + n].decode("utf-8"))


# --------------------------------------------------------------------------------------------------

def main():
    a = parse_args()
    t_start = time.monotonic()
    blend = Path(a.blend).resolve()
    if not blend.is_file():
        raise SystemExit(f"no such .blend: {blend}")
    route = blend.parent.parent if blend.parent.name == "out" else blend.parent
    name = a.name or route.name
    out_dir = Path(a.out_dir).resolve() if a.out_dir else ROOT / "models" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_p = Path(a.manifest) if a.manifest else find_up(blend.parent, "manifest.json")
    views_p = Path(a.views) if a.views else find_up(blend.parent, "harness", "views.json")
    stage_p = Path(a.stage_config) if a.stage_config else find_up(blend.parent, "harness", "config.json")
    contract_p = Path(a.contract) if a.contract else find_up(blend.parent, "brief", "contract.json")
    load = lambda p: json.load(open(p, "r", encoding="utf-8-sig")) if p and Path(p).is_file() else None
    manifest, views, stage_cfg, contract = load(manifest_p), load(views_p), load(stage_p), load(contract_p)
    say(f"model {blend}")
    say(f"manifest {manifest_p}; views {views_p}; stage {stage_p}; contract {contract_p}")

    digest_before = sha256(blend)
    tmp = Path(tempfile.mkdtemp(prefix="viewer_export_"))
    try:
        copy = tmp / "model_copy.blend"
        shutil.copyfile(blend, copy)

        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        with bpy.data.libraries.load(str(copy), link=False) as (src, dst):
            dst.collections = [n for n in src.collections if n == a.collection]
        root = next((c for c in dst.collections if c is not None), None)
        if root is None:
            raise SystemExit(f"no collection {a.collection!r} in {blend}")
        scene.collection.children.link(root)
        for k, v in ((manifest or {}).get("um_per_bu") and {"um_per_bu": manifest["um_per_bu"]} or {}).items():
            scene[k] = v

        anim = (manifest or {}).get("animation") or {}
        clip_name = anim.get("clip_name", "Contraction")
        fps = float(anim.get("fps", 24))
        scene.render.fps = int(round(fps))
        scene.render.fps_base = scene.render.fps / fps
        if isinstance(anim.get("frame_start"), int):
            scene.frame_start, scene.frame_end = anim["frame_start"], anim["frame_end"]

        objects = sorted((ob for ob in root.all_objects), key=lambda o: o.name)
        meshes = [ob for ob in objects if ob.type == "MESH"]

        # materials and the attributes their shaders read
        mats = {}
        for ob in meshes:
            for slot in ob.material_slots:
                if slot.material and slot.material.name not in mats:
                    mats[slot.material.name] = describe_material(slot.material)
        wanted_attrs = {m["stripe"]["attribute"] for m in mats.values() if "stripe" in m}
        renamed = {}
        for ob in meshes:
            me = ob.data
            for an in wanted_attrs:
                at = me.attributes.get(an)
                if at is not None and not an.startswith("_"):
                    at.name = "_" + an
                    renamed[an] = "_" + an
        for m in mats.values():
            if "stripe" in m and m["stripe"]["attribute"] in renamed:
                m["stripe"]["gltf_attribute"] = renamed[m["stripe"]["attribute"]]
        say(f"materials {len(mats)}; attributes carried {sorted(renamed.values())}")

        # states: the offsets drivers give each object at each declared state frame (glTF space)
        states = []
        for st in (manifest or {}).get("states", []) or [{"name": "assembled", "frame": 0}]:
            scene.frame_set(int(st["frame"]))
            offs = {}
            for ob in objects:
                dl = Vector(ob.delta_location)
                if dl.length > 1e-7:
                    offs[ob.name] = r6(to_gltf(dl))
            weights = {}
            for ob in meshes:
                keys = ob.data.shape_keys
                if keys is not None and len(keys.key_blocks) > 1 and keys.key_blocks[1].value > 1e-6:
                    weights[ob.name] = round(keys.key_blocks[1].value, 6)
            rec = {"name": st["name"], "frame": int(st["frame"]), "offsets": offs}
            if st.get("description"):
                rec["description"] = st["description"]
            if weights:
                rec["weights"] = weights
            states.append(rec)
        say("states " + ", ".join(f"{s['name']}@{s['frame']} ({len(s['offsets'])} moved)" for s in states))

        scene.frame_set(scene.frame_start)
        glb_tmp = tmp / "out.glb"
        kwargs = {
            "filepath": str(glb_tmp),
            "export_format": "GLB",
            "export_apply": False,
            "export_animations": True,
            "export_animation_mode": "ACTIVE_ACTIONS",
            "export_nla_strips_merged_animation_name": clip_name,
            "export_morph": True,
            "export_morph_normal": True,
            "export_extras": True,
            "export_attributes": True,
            "export_hierarchy_full_collections": True,
            "export_yup": True,
        }
        known = {p.identifier for p in bpy.ops.export_scene.gltf.get_rna_type().properties}
        dropped = sorted(k for k in kwargs if k not in known)
        t0 = time.monotonic()
        bpy.ops.export_scene.gltf(**{k: v for k, v in kwargs.items() if k in known})
        export_s = time.monotonic() - t0
        if not glb_tmp.is_file() or glb_tmp.stat().st_size == 0:
            raise SystemExit("the exporter wrote no file")

        g = glb_json(glb_tmp)
        prims = [p for m in g.get("meshes", []) for p in m.get("primitives", [])]
        custom = sorted({k for p in prims for k in p["attributes"] if k.startswith("_")})
        with_custom = sum(1 for p in prims if any(k.startswith("_") for k in p["attributes"]))
        morph = sum(1 for m in g.get("meshes", []) if any(p.get("targets") for p in m["primitives"]))
        anims = [x.get("name") for x in g.get("animations", [])]
        n_meshes = len(g.get("meshes", []))
        if a.no_clip:
            clip_checks = [
                (not anims, f"no animations (--no-clip): {anims}"),
                (morph == 0, f"no mesh has morph targets (--no-clip): {morph} of {n_meshes} meshes"),
            ]
        else:
            clip_checks = [
                (len(anims) == 1 and anims[0] == clip_name, f"one clip named {clip_name}: {anims}"),
                (morph == n_meshes, f"morph targets on {morph} of {n_meshes} meshes"),
            ]
        checks = clip_checks + [
            (not wanted_attrs or with_custom > 0, f"custom attributes {custom} on {with_custom} primitives"),
        ]
        for ok, line in checks:
            say(("PASS " if ok else "FAIL ") + line)
        if not all(ok for ok, _ in checks):
            raise SystemExit("GLB check failed")
        acc = g["accessors"][g["animations"][0]["samplers"][0]["input"]] if anims else None
        # the custom attribute's name as written (the exporter may change its case)
        for m in mats.values():
            if "stripe" in m and custom:
                want = m["stripe"].get("gltf_attribute", "").lower()
                m["stripe"]["gltf_attribute"] = next((c for c in custom if c.lower() == want), custom[0])

        stage = (stage_cfg or {}).get("stage", {})
        sidecar = {
            "schema": 1,
            "generator": "tools/blender/export_for_viewer.py",
            "source": {"blend": str(blend).replace("\\", "/"), "sha256": digest_before,
                       "manifest": str(manifest_p).replace("\\", "/") if manifest_p else None},
            "space": "glTF (Y up; Blender x, y, z -> x, z, -y)",
            "um_per_bu": (manifest or {}).get("um_per_bu", 10),
            "clip": None if a.no_clip else {
                "name": clip_name, "fps": fps,
                "frame_start": anim.get("frame_start"), "frame_end": anim.get("frame_end"),
                "t_start": acc["min"][0] if acc else None, "t_end": acc["max"][0] if acc else None,
                "claim": (anim.get("verdict_reason") or "")[:600]},
            "states": states,
            "materials": mats,
            "structures": {sid: {"slug": s.get("slug"), "count": s.get("count")}
                           for sid, s in ((manifest or {}).get("structures") or {}).items()},
            "roles": {"annotation": ["S16"], "covering": ["S14"]},
            "cameras": camera_set(views, contract, manifest) if views else {},
            "camera_order": list((views or {}).get("views", {}).keys()) +
                            [x["id"] for x in (manifest or {}).get("anchors", [])],
            "lights": {"rule": stage.get("lights_rule", ""), "rig": stage.get("lights", []),
                       "world": stage.get("world", {}), "view_transform": stage.get("view_transform"),
                       "exposure": stage.get("exposure", 0.0)},
            "export": {"kwargs": {k: v for k, v in kwargs.items() if k != "filepath"}, "dropped": dropped,
                       "seconds": round(export_s, 2), "blender": bpy.app.version_string},
        }
        glb_out = out_dir / f"{name}.glb"
        side_out = out_dir / f"{name}.viewer.json"
        shutil.move(str(glb_tmp), str(glb_out))
        with open(side_out, "w", encoding="utf-8") as fh:
            json.dump(sidecar, fh, indent=1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    digest_after = sha256(blend)
    if digest_after != digest_before:
        raise SystemExit("the source .blend changed during export")
    say(f"source unchanged (sha256 {digest_before[:12]}...)")
    say(f"wrote {glb_out} ({glb_out.stat().st_size / 1e6:.1f} MB) and {side_out.name} in "
        f"{time.monotonic() - t_start:.1f} s (export {export_s:.1f} s)")


if __name__ == "__main__":
    main()
