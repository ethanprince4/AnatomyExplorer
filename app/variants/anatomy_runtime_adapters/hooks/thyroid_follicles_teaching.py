"""Import-safe thyroid teaching metadata adapter; never evaluates a builder.

Call after baseline teaching defaults and before ProceduralModel construction.
Provide exact name/group/color records from the independently saved variant's
metadata. This helper never calls parts(), build(), a viewer, or mesh arrays.
Version persistence and selection belong to future whole-application integration.
"""
from copy import deepcopy
import json
from pathlib import Path


def read_teaching(sidecar_path=None):
    path = Path(sidecar_path) if sidecar_path is not None else Path(__file__).with_name("teaching_views.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("model_id") != "thyroid_follicles":
        raise ValueError("Invalid thyroid teaching sidecar identity")
    names = data["expected_parts"]
    if len(names) != 16 or len(names) != len(set(names)):
        raise ValueError("Thyroid sidecar must retain 16 unique original parts")
    expected = {record["name"]: record["group"] for record in data["parts"]}
    if set(expected) != set(names) or len(data["parts"]) != 16:
        raise ValueError("Thyroid sidecar selectors are incomplete")
    if data["opening_view"] not in data["views"]:
        raise ValueError("Unknown thyroid opening view")
    if data["opening_view"] != data["start_view"] or data["views"] != data["native_cameras"]:
        raise ValueError("Thyroid native aliases disagree")
    for view in data["teaching_views"]:
        visible, hidden = view["visible_parts"], view["hidden_parts"]
        if len(visible) != len(set(visible)) or len(hidden) != len(set(hidden)):
            raise ValueError("Duplicate part in thyroid visibility preset")
        if set(visible) & set(hidden) or set(visible) | set(hidden) != set(names):
            raise ValueError("Incomplete or conflicting thyroid visibility preset")
        camera = data["views"].get(view["title"])
        if camera != view["native_camera"] or camera["hidden"] != hidden:
            raise ValueError("Native thyroid camera and hidden selectors disagree")
        for key in ("visible_selectors", "hidden_selectors"):
            records = view[key]
            selected = visible if key == "visible_selectors" else hidden
            if [r["name"] for r in records] != selected:
                raise ValueError("Thyroid exact selector order differs from names")
            if any(expected[r["name"]] != r["group"] for r in records):
                raise ValueError("Thyroid exact selector group mismatch")
        if camera.get("type") != "ORTHO" or camera.get("ortho_width", 0) <= 0:
            raise ValueError("Invalid thyroid orthographic camera")
        if any(len(camera[key]) != 3 for key in ("position", "target")):
            raise ValueError("Invalid thyroid camera coordinates")
    if data["versions"]["display_mode"] != "one_at_a_time" or data["versions"]["side_by_side_allowed"]:
        raise ValueError("Thyroid variant display policy changed")
    return data


def validate_saved_selectors(data, part_metadata):
    """Validate tiny saved metadata only, never load geometry or guess selectors."""
    expected = {r["name"]: (r["group"], r["color"].lower()) for r in data["parts"]}
    actual = {}
    for record in part_metadata:
        name = record["name"]
        if name in actual:
            raise ValueError("Duplicate saved thyroid part: " + name)
        actual[name] = (record["group"], record["color"].lower())
        if "alpha" in record and record["alpha"] != 1.0:
            raise ValueError("Saved thyroid alpha changed: " + name)
    if actual != expected:
        raise ValueError("Saved thyroid names/groups/colors differ from the original 16-part source")


def apply_native_teaching(model, *, variant, available_part_metadata, sidecar_path=None):
    """Attach exact cameras/visibility and teaching text to one verified variant.

    Pre refine and Post refine are each passed independently. Geometry, colors,
    descriptions, normals, original planes, animation and materials are untouched.
    This does not certify the variant, create it, or make an unavailable Post ready.
    """
    data = read_teaching(sidecar_path)
    if variant not in data["versions"]["labels"]:
        raise ValueError("Thyroid variant must be Pre refine or Post refine")
    if getattr(model, "id", None) != data["model_id"]:
        raise ValueError("Cannot attach thyroid_follicles teaching to another model")
    validate_saved_selectors(data, available_part_metadata)
    cut = data["cutaway"]
    if tuple(getattr(model, "cut_at", ())) != tuple(cut["at"]):
        raise ValueError("Baseline thyroid cut changed; native review required")
    actual_axes = tuple(tuple(axis) for axis in getattr(model, "cutaway", ()))
    if actual_axes != tuple(tuple(axis) for axis in cut["axes"]):
        raise ValueError("Baseline thyroid cut axes changed")
    if float(getattr(model, "metres_per_unit", 0)) != data["scale"]["metres_per_unit"]:
        raise ValueError("Baseline thyroid authored scale is absent or changed")
    cameras = deepcopy(data["views"])
    for name, existing in getattr(model, "viewer_cameras", {}).items():
        if name in cameras and cameras[name] != existing:
            raise ValueError("Existing thyroid camera name collides: " + name)
        cameras.setdefault(name, deepcopy(existing))
    model.viewer_cameras = cameras
    model.start_view = data["opening_view"]
    model.scale_note = data["scale_note"]
    model.summary = data["summary"]
    return data


def configure_model(model, *, variant, available_part_metadata, sidecar_path=None):
    """Alias suitable for a lead's model-local configure hook."""
    return apply_native_teaching(model, variant=variant,
                                 available_part_metadata=available_part_metadata,
                                 sidecar_path=sidecar_path)
