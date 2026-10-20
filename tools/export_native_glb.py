"""Copy a native NPZ model to GLB without changing its decoded geometry.

Run with the app's Python: ``python tools/export_native_glb.py --source model.npz
--output model.glb --model-id spleen --recipe recipe.json``. The adjacent viewer
and controls sidecars retain the native teaching state. Export is exclusive:
existing deliveries and input files are never overwritten. No builders run.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import gc
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import time
from types import SimpleNamespace

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

SCHEMA = "ae.native-glb.v1"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def array_sha256(array):
    return hashlib.sha256(np.ascontiguousarray(array).view(np.uint8)).hexdigest()


def _portable(value):
    """Keep semantic documents; machine-local provenance belongs in the report."""
    if isinstance(value, dict):
        return {key: _portable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_portable(item) for item in value]
    if isinstance(value, Path):
        return value.name
    if isinstance(value, str) and (Path(value).is_absolute() or (len(value) > 2 and value[1:3] in (":\\", ":/"))):
        return value.replace("\\", "/").rsplit("/", 1)[-1]
    return value


def _write_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def _source_context(source, model_id, recipe, controls, companions):
    from app.variants.local_runtime import _controls, _load_color_companion
    from app.variants.local_runtime import decode_local_npz
    warnings = []
    metadata, rows = decode_local_npz(source, warnings=warnings)
    bound = dict(companions or {})
    recipe = Path(recipe) if recipe else source.with_name("recipe.json")
    if recipe.is_file():
        bound["teaching_recipe"] = {"path": str(recipe.resolve())}
    descriptor = SimpleNamespace(primary=SimpleNamespace(path=source), root=source.parent,
                                 companions=bound, runtime_controls=controls,
                                 record={"static_recipe": True})
    entry = SimpleNamespace(id=model_id, name=model_id.replace("_", " ").title(), summary="", scale_note="")
    _load_color_companion(descriptor, rows, warnings)
    resolved = _controls(entry, descriptor, metadata, rows, warnings)
    return metadata, rows, resolved, warnings


def export_native_glb(source, output, model_id=None, recipe=None, controls=None, companions=None, *, verify=True):
    """Export and prove exact equality with canonical ``decode_local_npz`` arrays.

    Integer normals/positions and delta indices are decoded by the actual app.
    Native colors and Look values are derived by the actual app's providers.
    The source NPZ remains authoritative and is hashed before and after export.
    """
    from app.micro.base import DETAIL_DEFAULTS, rgb, tone
    from app.viewer.procedural import draft_look, look_for

    started = time.perf_counter()
    source, output = Path(source).resolve(), Path(output).resolve()
    if source.suffix.lower() != ".npz" or output.suffix.lower() != ".glb" or source == output:
        raise ValueError("Use a source NPZ and a distinct new GLB output")
    paths = {"viewer": output.with_suffix(".viewer.json"), "controls": output.with_suffix(".controls.json"),
             "report": output.with_suffix(".transport.json"), "source_hash": output.with_suffix(".source.sha256")}
    if any(path.exists() for path in [output, *paths.values()]):
        raise FileExistsError("Choose a new output name; existing deliveries are never overwritten")
    model_id = model_id or source.parent.name
    before_hash = sha256(source)
    companion_sources = {}
    for role, value in (companions or {}).items():
        value = value.get("path") if isinstance(value, dict) else value
        if isinstance(value, (str, Path)):
            path = Path(value)
            path = path if path.is_absolute() else source.parent / path
            if path.is_file():
                companion_sources[role] = {"path": str(path.resolve()), "name": path.name, "sha256": sha256(path)}
    recipe_path = Path(recipe) if recipe else source.with_name("recipe.json")
    if recipe_path.is_file():
        companion_sources["teaching_recipe"] = {"path": str(recipe_path.resolve()), "name": recipe_path.name,
                                                 "sha256": sha256(recipe_path)}
    metadata, rows, resolved, warnings = _source_context(source, model_id, recipe, controls, companions)
    names = [row["name"] for row, *_ in rows]
    if len(names) != len(set(names)):
        raise ValueError("Native part names must be unique selection keys")
    if not rows or any(not len(vertices) or not faces.size for _, vertices, _, faces, _ in rows):
        raise ValueError("Empty parts cannot roundtrip through the current triangle viewer")
    native = resolved["native"]
    viewing = native.get("viewer_look")
    if viewing and model_id in {"heart", "whole_heart", "cardiac_muscle"}:
        raise ValueError("Protected model cannot receive a teaching Look")
    transport = dict(schema=SCHEMA, source={"name": source.name, "sha256": before_hash,
                     "companions": {role: {k: v for k, v in record.items() if k != "path"}
                                    for role, record in companion_sources.items()}},
                     metadata=_portable(metadata), controls=_portable(resolved), parts={},
                     model={"home": native.get("home_view", [-.62, .42]),
                            "cutaway": {"axes": native.get("cutaway", [[1, 0, 0], [0, 0, 1]]),
                                        "at": native.get("cut_at", [0, 0]), "on": native.get("cut_on", False)},
                            "metres_per_unit": native.get("metres_per_unit", 0),
                            "look_defaults": {"exposure": .35, "studio": .45}, "explode": "native_layers"})
    doc = {"asset": {"version": "2.0", "generator": "Layered Human canonical native GLB transport"},
           "scene": 0, "scenes": [{"name": model_id, "nodes": list(range(len(rows)))}],
           "nodes": [], "meshes": [], "materials": [], "accessors": [], "bufferViews": [],
           "extras": {"native_transport": transport,
                      "coordinates": "Original native Y-up coordinates; no transform or rescaling"}}
    output.parent.mkdir(parents=True, exist_ok=True)
    inventory = []
    with tempfile.TemporaryFile(dir=output.parent) as binary:
        def accessor(array, kind, component, target, bounds=False):
            array = np.ascontiguousarray(array)
            offset = binary.tell()
            padding = (-offset) % 4
            if padding:
                binary.write(b"\0" * padding)
                offset += padding
            binary.write(memoryview(array).cast("B"))
            view = len(doc["bufferViews"])
            doc["bufferViews"].append(dict(buffer=0, byteOffset=offset, byteLength=array.nbytes, target=target))
            record = dict(bufferView=view, componentType=component, count=len(array), type=kind)
            if bounds:
                record.update(min=array.min(axis=0).tolist(), max=array.max(axis=0).tolist())
            index = len(doc["accessors"])
            doc["accessors"].append(record)
            return index

        for index, (row, vertices, normals, faces, colors) in enumerate(rows):
            name, category = row["name"], row.get("category", "other")
            colour = tone(rgb(row.get("color", "#c98f88")))
            detail = row.get("detail")
            if detail is None:
                detail = DETAIL_DEFAULTS.get(category, DETAIL_DEFAULTS["other"])
            look = draft_look(look_for(category, colour, row.get("alpha", 1), detail), viewing)
            if colors is None and "color_linear" in row:
                colors = np.broadcast_to(np.asarray(row["color_linear"], dtype=np.float32), vertices.shape)
            if colors is not None:
                look.base, look.use_vcol = (1., 1., 1.), True
            transport["parts"][name] = {"metadata": _portable(row), "look": asdict(look), "colour": colour}
            attributes = {"POSITION": accessor(vertices.astype("<f4", copy=False), "VEC3", 5126, 34962, True),
                          "NORMAL": accessor(normals.astype("<f4", copy=False), "VEC3", 5126, 34962)}
            if colors is not None:
                attributes["COLOR_0"] = accessor(colors.astype("<f4", copy=False), "VEC3", 5126, 34962)
            indices = accessor(faces.ravel().astype("<u4"), "SCALAR", 5125, 34963)
            doc["materials"].append({"name": name, "pbrMetallicRoughness": {
                "baseColorFactor": list(look.base) + [look.alpha], "metallicFactor": look.metal,
                "roughnessFactor": look.rough}, "doubleSided": look.double_sided,
                "alphaMode": "BLEND" if look.translucent else "OPAQUE", "extras": {"native_look": asdict(look)}})
            doc["meshes"].append({"name": name, "primitives": [dict(attributes=attributes, indices=indices, material=index, mode=4)]})
            doc["nodes"].append({"name": name, "mesh": index, "extras": {**_portable(row), "structure": row.get("group", "Model")}})
            inventory.append(dict(name=name, vertices=len(vertices), triangles=len(faces),
                                  position_sha256=array_sha256(vertices), normal_sha256=array_sha256(normals),
                                  indices_sha256=array_sha256(faces.astype("<u4")),
                                  color_sha256=array_sha256(colors) if colors is not None else None))
        size = binary.tell()
        doc["buffers"] = [{"byteLength": size}]
        encoded = json.dumps(doc, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        encoded += b" " * ((-len(encoded)) % 4)
        bin_pad = (-size) % 4
        length = 12 + 8 + len(encoded) + 8 + size + bin_pad
        if length > 0xffffffff:
            raise ValueError("GLB exceeds its 4 GiB container limit; split into independent model scenes")
        with output.open("xb") as stream:
            stream.write(struct.pack("<III", 0x46546c67, 2, length))
            stream.write(struct.pack("<II", len(encoded), 0x4e4f534a))
            stream.write(encoded)
            stream.write(struct.pack("<II", size + bin_pad, 0x004e4942))
            binary.seek(0)
            shutil.copyfileobj(binary, stream, length=8 * 1024 * 1024)
            stream.write(b"\0" * bin_pad)
    sidecar = {"native_transport": transport, "cameras": deepcopy(native.get("viewer_cameras", {})),
               "camera_order": list(native.get("viewer_cameras", {})), "start_view": native.get("start_view"),
               "um_per_bu": float(native.get("metres_per_unit", 0)) * 1e6,
               **deepcopy(resolved.get("viewer", {}))}
    _write_json(paths["viewer"], sidecar)
    _write_json(paths["controls"], _portable(resolved))
    paths["source_hash"].write_text(f"{before_hash}  {source.name}\n", encoding="utf-8")
    del rows, metadata, doc, encoded
    gc.collect()
    proof = validate_native_glb(source, output, companions=companions) if verify else {"status": "not_run"}
    after_hash = sha256(source)
    if before_hash != after_hash:
        raise RuntimeError("Source file changed during export")
    if any(sha256(record["path"]) != record["sha256"] for record in companion_sources.values()):
        raise RuntimeError("A source companion changed during export")
    report = {"schema": SCHEMA, "source": str(source), "source_sha256": before_hash,
              "source_unchanged": True, "output": str(output), "output_sha256": sha256(output),
              "bytes": output.stat().st_size, "parts": inventory, "decode_warnings": warnings,
              "companion_sources": companion_sources,
              "verification": proof, "seconds": time.perf_counter() - started,
              "limits": ["Geometry equality is against the real NPZ decoder, including its normal normalization.",
                         "Native tissue shader and teaching controls require Layered Human's metadata bridge; generic GLB viewers use PBR.",
                         "Numerical parity and app parsing do not establish anatomical or visual acceptance."]}
    _write_json(paths["report"], report)
    return report


def validate_native_glb(source, output, companions=None):
    """Reopen saved GLB with the actual app parser and CPU viewer model."""
    from app.variants.local_runtime import decode_local_npz, _load_color_companion
    from app.viewer.model import Model
    warnings = []
    metadata, rows = decode_local_npz(source, warnings=warnings)
    if companions:
        descriptor = SimpleNamespace(primary=SimpleNamespace(path=Path(source)), root=Path(source).parent,
                                     companions=companions)
        _load_color_companion(descriptor, rows, warnings)
    model = Model(output)
    expected_names = [row["name"] for row, *_ in rows]
    if expected_names != [item.key for item in model.items]:
        raise AssertionError("Saved part names/order changed")
    parts = []
    for row, vertices, normals, faces, colors in rows:
        part = model.parts[len(parts)]
        actual = model.vertices[part.vertex_base:part.vertex_base + part.vertex_count]
        local_faces = (model.indices[part.first:part.first + part.count] - part.vertex_base).reshape(-1, 3)
        for label, before, after in (("positions", vertices, actual[:, :3]), ("normals", normals, actual[:, 3:6]), ("faces", faces, local_faces)):
            if not np.array_equal(before, after):
                raise AssertionError(f"{row['name']}: saved {label} changed")
        if colors is None and "color_linear" in row:
            colors = np.broadcast_to(np.asarray(row["color_linear"], dtype=np.float32), vertices.shape)
        if colors is not None and not np.array_equal(colors, actual[:, 13:16]):
            raise AssertionError(f"{row['name']}: saved vertex colors changed")
        item = model.items[len(parts)]
        for field, default in (("category", "other"), ("label", True), ("clip", False), ("bulk", False), ("rank", 0)):
            if getattr(item, field) != row.get(field, default):
                raise AssertionError(f"{row['name']}: {field} changed")
        if item.group != row.get("group", "Model") or item.description != row.get("description", ""):
            raise AssertionError(f"{row['name']}: grouping/description changed")
        parts.append({"name": row["name"], "positions_exact": True, "normals_exact": True, "faces_exact": True,
                      "colors_exact": True, "semantics_exact": True})
    transport = model.native_transport
    if transport["metadata"] != _portable(metadata):
        raise AssertionError("Original native metadata changed")
    native = transport["controls"]["native"]
    if model.cameras != native.get("viewer_cameras", {}):
        raise AssertionError("Authored cameras/visibility changed")
    return {"status": "passed", "actual_app_parser": "app.viewer.model.Model", "parts": parts,
            "vertices": len(model.vertices), "triangles": model.triangle_count,
            "cameras_exact": True, "metadata_exact": True, "decode_warnings": warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-id")
    parser.add_argument("--recipe")
    parser.add_argument("--controls")
    parser.add_argument("--validate-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.validate_only:
        result = validate_native_glb(arguments.source, arguments.output)
    else:
        result = export_native_glb(arguments.source, arguments.output, arguments.model_id, arguments.recipe, arguments.controls)
    print(json.dumps({key: result[key] for key in result if key not in ("parts", "verification")}, ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    main()
