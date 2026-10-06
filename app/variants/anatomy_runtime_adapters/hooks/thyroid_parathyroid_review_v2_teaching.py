"""Model-scoped native teaching hooks; no app imports, meshes, or import-time work.

Integration runs on the later application/build machine. This module only reads
the supplied small JSON sidecar and uses already-existing MicroModel/ModelView
methods. It never calls a builder or changes a frozen Part or geometry array.
"""
from copy import deepcopy
import json
import math
from pathlib import Path


MODEL_ID = "thyroid_parathyroid_review_v2"
ATTRIBUTES = frozenset({
    "summary", "scale_note", "metres_per_unit", "home_view", "cut_on",
    "cutaway", "cut_at", "labels_on_open", "viewer_cameras", "start_view",
})
CAMERA_FIELDS = frozenset({
    "position", "target", "type", "ortho_width", "hidden", "cut_on", "note",
})


def _vector(value, length, label):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(label + " must have the declared vector length")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or
           not math.isfinite(x) for x in value):
        raise ValueError(label + " must contain finite numbers")


def validate_proposal(proposal):
    """Bounded schema/name checks, independent of application or mesh libraries."""
    if proposal.get("schema_version") != 1 or proposal.get("model_id") != MODEL_ID:
        raise ValueError("Wrong thyroid teaching sidecar identity/schema")
    names = proposal.get("exact_parts", [])
    if len(names) not in (21, 30) or len(set(names)) != len(names):
        raise ValueError("Expected the exact unique 30-part review-v2 contract")
    signals = proposal.get("signal_parts", [])
    if len(signals) not in (0, 9) or len(names) != 21 + len(signals) or set(signals) != {n for n in names if n.startswith("Signal ")}:
        raise ValueError("Expected exactly nine unchanged Signal-prefixed parts")
    attrs = proposal.get("native_attributes", {})
    if set(attrs) != ATTRIBUTES:
        raise ValueError("Unexpected/missing native model-scoped attribute")
    if attrs["labels_on_open"] is not True or attrs["cut_on"] is not True:
        raise ValueError("Opening labels and native teaching section must remain enabled")
    if attrs["metres_per_unit"] != 0.0005 or attrs["cut_at"] != [2.0, 0.12]:
        raise ValueError("Do not silently change frozen model scale or section")
    if attrs["cutaway"] != [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]:
        raise ValueError("Do not silently replace native section axes")
    _vector(attrs["home_view"], 2, "home_view")
    views = attrs["viewer_cameras"]
    if not isinstance(views, dict) or attrs["start_view"] not in views:
        raise ValueError("Opening view is absent from native camera records")
    if views[attrs["start_view"]].get("hidden") != []:
        raise ValueError("The default view must not conceal any normal tissue or signals")
    for name, camera in views.items():
        if not set(camera).issubset(CAMERA_FIELDS):
            raise ValueError("Unsupported native camera field in " + name)
        _vector(camera["position"], 3, name + " position")
        _vector(camera["target"], 3, name + " target")
        if camera["position"] == camera["target"]:
            raise ValueError("Camera eye cannot equal target")
        if camera["type"] not in {"PERSPECTIVE", "ORTHO"}:
            raise ValueError("Unsupported native projection")
        if camera["type"] == "ORTHO":
            width = camera.get("ortho_width")
            if isinstance(width, bool) or not isinstance(width, (int, float)) or not math.isfinite(width) or width <= 0:
                raise ValueError("Orthographic width must be positive and finite")
        hidden = camera["hidden"]
        if len(set(hidden)) != len(hidden) or not set(hidden).issubset(names):
            raise ValueError("Hidden lists must resolve exact unique native item keys")
        if not isinstance(camera["cut_on"], bool):
            raise ValueError("cut_on must be boolean")
    for action in proposal.get("focus_actions", []):
        if action["micro"] != MODEL_ID or action["view"] not in views:
            raise ValueError("Focus action has wrong model/view")
        if not set(action["micro_focus"]).issubset(names):
            raise ValueError("Focus action names are absent from the exact model contract")
    return proposal


def read_proposal(path):
    path = Path(path)
    if path.stat().st_size > 1_000_000:
        raise ValueError("Teaching sidecar unexpectedly large")
    return validate_proposal(json.loads(path.read_text(encoding="utf-8")))


def apply_model_teaching(micro_model, proposal_path):
    """Call only on the intended MicroModel instance, before entry.load().

    Native ProceduralModel copies viewer_cameras/start_view and cut metadata.
    Native ModelView reads labels_on_open and creates model-local label settings.
    Existing teaching_defaults.py does not accept labels_on_open, so that field
    must use this model-scoped instance hook or the existing registry attribute.
    """
    if getattr(micro_model, "id", None) != MODEL_ID:
        raise ValueError("Teaching hook cannot modify another model")
    proposal = read_proposal(proposal_path)
    for key, value in proposal["native_attributes"].items():
        setattr(micro_model, key, deepcopy(value))
    return tuple(proposal["native_attributes"]["viewer_cameras"])


def _check_native_view(model_view, proposal):
    if getattr(getattr(model_view, "entry", None), "id", None) != MODEL_ID:
        raise ValueError("Teaching action cannot target another ModelView")
    actual = {item.key for item in model_view.vmodel.items}
    if actual != set(proposal["exact_parts"]):
        raise ValueError("Loaded native item keys do not match teaching-sidecar contract")


def apply_native_view(model_view, proposal_path, view_name):
    """Optional integration hook, using existing native view/label/state methods.

    Native camera records have no focus field. Clearing a prior lesson's ghost
    focus matters: set_named_view() alone does not clear ghost_focus/selection.
    Native signals/tree/cut synchronization remains the viewer's responsibility.
    """
    proposal = read_proposal(proposal_path)
    _check_native_view(model_view, proposal)
    if view_name not in proposal["native_attributes"]["viewer_cameras"]:
        raise ValueError("Unknown authored thyroid teaching view")
    if view_name not in model_view.vmodel.cameras:
        raise ValueError("Teaching cameras were not attached before native model load")
    model_view.state.clear_ghost()
    model_view.state.select([])
    model_view.labels.setChecked(True)
    model_view.set_named_view(view_name)
    model_view.gl_widget.invalidate_labels()


def focus_native_action(model_view, proposal_path, action_id):
    """Optional lesson/action hook. No per-camera focus metadata is invented."""
    proposal = read_proposal(proposal_path)
    _check_native_view(model_view, proposal)
    actions = {a["id"]: a for a in proposal["focus_actions"]}
    if action_id not in actions:
        raise ValueError("Unknown authored focus action")
    action = actions[action_id]
    _, missing = model_view.part_ids(action["micro_focus"])
    if missing:
        raise ValueError("Native focus names failed to resolve: " + ", ".join(missing))
    apply_native_view(model_view, proposal_path, action["view"])
    return model_view.focus_parts(action["micro_focus"])
