"""Tooth-only native presentation adapter. Importing performs no I/O or app import.

Attach before ProceduralModel/ModelView construction to expose native view buttons.
The optional ModelView binding adds visible caveats and selective labels. Nothing
here accesses meshes, arrays, caches, builders, exports or geometry variants.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path


def load_manifest(path):
    """Read only the explicitly supplied small presentation JSON."""
    path = Path(path)
    if path.stat().st_size > 100_000:
        raise ValueError("Tooth presentation manifest exceeds its source-only bound")
    result = json.loads(path.read_text(encoding="utf-8"))
    validate_manifest(result)
    return result


def validate_manifest(manifest):
    if manifest.get("schema_version") != 1 or manifest.get("model_id") != "tooth":
        raise ValueError("Expected tooth presentation schema version 1")
    if manifest.get("metres_per_unit") != 0.01:
        raise ValueError("The preserved tooth unit is 0.01 metres per unit")
    if "summary" in manifest and (not isinstance(manifest["summary"], str) or not manifest["summary"].strip()):
        raise ValueError("An optional improved tooth summary must be nonempty text")
    keys = manifest.get("expected_part_keys", [])
    if len(keys) != 26 or len(set(keys)) != 26:
        raise ValueError("Expected the 26 distinct accepted tooth part keys")
    keyset = set(keys)
    views = manifest.get("views", [])
    cameras = manifest.get("viewer_cameras", {})
    if len(views) != 5 or len({v["id"] for v in views}) != 5:
        raise ValueError("Expected five distinct progressive tooth views")
    if [v["name"] for v in views] != list(cameras):
        raise ValueError("Teaching view order must match native camera order")
    if manifest.get("start_view") != views[0]["name"]:
        raise ValueError("The opening view must be the first teaching stage")
    for view in views:
        rec = cameras[view["name"]]
        visible, hidden, labelled = map(set, (view["visible_parts"], view["hidden_parts"], view["label_keys"]))
        if visible & hidden or visible | hidden != keyset or not labelled <= visible:
            raise ValueError("Visibility must partition exact keys and labels must be visible")
        for field in ("visible_parts", "hidden_parts", "label_keys"):
            if len(view[field]) != len(set(view[field])):
                raise ValueError("Duplicate presentation selectors are not permitted")
        if rec["hidden"] != view["hidden_parts"] or rec.get("cut_on") is not False:
            raise ValueError("Native hiding must match the stage; the source section stays uncut")
        if rec.get("type") != "ORTHO" or not math.isfinite(rec["ortho_width"]) or rec["ortho_width"] <= 0:
            raise ValueError("Expected a finite positive native orthographic extent")
        for field in ("position", "target"):
            if len(rec[field]) != 3 or not all(math.isfinite(c) for c in rec[field]):
                raise ValueError("Camera coordinates must be finite xyz vectors")
        if rec["position"] == rec["target"]:
            raise ValueError("Camera position and target must differ")
        if not view.get("caption") or not view.get("teacher_labels"):
            raise ValueError("Each stage requires visible caveats and teaching guidance")
    defaults = manifest.get("presentation_defaults", {})
    if defaults != {"labels_on": True, "tissue_opacity_percent": 100, "explode_percent": 0}:
        raise ValueError("Tooth presentation uses labelled, assembled, opaque tissue defaults")
    return True


def _check_units(model):
    current = getattr(model, "metres_per_unit", 0.0)
    if current not in (None, 0, 0.01):
        raise ValueError("Refuse to overwrite a conflicting source unit")


def apply_to_micro_model(micro_model, manifest):
    """Apply after tooth registration, before ProceduralModel construction.

    Does not call parts() or build(). The accepted 26 selector contract is proved
    again when the loaded viewer model is available, before the UI is constructed.
    """
    validate_manifest(manifest)
    if getattr(micro_model, "id", None) != "tooth":
        raise ValueError("This adapter is restricted to the tooth MicroModel")
    _check_units(micro_model)
    micro_model.viewer_cameras = deepcopy(manifest["viewer_cameras"])
    micro_model.start_view = manifest["start_view"]
    micro_model.labels_on_open = True
    micro_model.cut_on = False
    micro_model.metres_per_unit = 0.01
    micro_model.scale_note = manifest["scale_note"]
    if "summary" in manifest:
        micro_model.summary = manifest["summary"]
    micro_model.teaching_presentation = deepcopy(manifest)
    return {"model_id": "tooth", "start_view": micro_model.start_view, "camera_count": len(micro_model.viewer_cameras)}


def apply_to_viewer_model(viewer_model, manifest, *, model_id=None):
    """Install before ModelView makes its dataset and native view toolbar.

    Native procedural identity comes from source.id. For a separately loaded
    artifact, the root variant/provenance resolver must supply model_id='tooth'.
    Exact accepted keys and units are checked without reading vertex buffers.
    """
    validate_manifest(manifest)
    source_id = getattr(getattr(viewer_model, "source", None), "id", None)
    if source_id not in (None, "tooth") or model_id not in (None, "tooth") or (source_id or model_id) != "tooth":
        raise ValueError("A verified tooth model identity is required")
    keys = [item.key for item in viewer_model.items]
    if len(keys) != 26 or len(set(keys)) != 26 or set(keys) != set(manifest["expected_part_keys"]):
        raise ValueError("Loaded tooth selectors differ from the accepted 26-part contract")
    _check_units(viewer_model)
    viewer_model.cameras = deepcopy(manifest["viewer_cameras"])
    viewer_model.camera_order = list(viewer_model.cameras)
    viewer_model.sidecar = dict(viewer_model.sidecar)
    viewer_model.sidecar["start_view"] = manifest["start_view"]
    viewer_model.sidecar["view_transition"] = manifest["view_transition"]
    if getattr(viewer_model, "cutaway", None) is not None:
        viewer_model.cutaway = deepcopy(viewer_model.cutaway)
        viewer_model.cutaway["on"] = False
    viewer_model.metres_per_unit = 0.01
    viewer_model.teaching_presentation = deepcopy(manifest)
    return {"model_id": "tooth", "start_view": manifest["start_view"], "selector_count": len(keys)}


def bind_to_model_view(model_view, manifest, *, caption_factory=None):
    """Bind the already-constructed native ModelView to per-stage teaching state.

    Use apply_to_viewer_model BEFORE ModelView construction. This second step
    adds a wrapped caption to the existing sidebar using its actual Qt layout,
    then connects ModelViewport.viewChanged. A returned controller is retained
    on ModelView so callbacks and the native caption survive for that view.
    caption_factory supports tiny non-Qt tests, not an alternate runtime.
    """
    validate_manifest(manifest)
    if list(model_view.vmodel.camera_order) != list(manifest["viewer_cameras"]):
        raise ValueError("Install tooth camera metadata before constructing ModelView")
    keys = [item.key for item in model_view.vmodel.items]
    if len(keys) != 26 or set(keys) != set(manifest["expected_part_keys"]):
        raise ValueError("The native view must contain the accepted tooth selectors")
    existing = getattr(model_view, "_tooth_teaching_controller", None)
    if existing is not None:
        if existing.manifest != manifest:
            raise ValueError("A different tooth presentation is already bound")
        return existing
    if caption_factory is None:
        from PySide6.QtWidgets import QLabel  # Only during explicit native integration.
        caption_factory = QLabel
    caption = caption_factory(model_view.side)
    caption.setObjectName("toothTeachingCaption")
    caption.setWordWrap(True)
    model_view.side.layout().insertWidget(2, caption)
    controller = ToothTeachingController(model_view, deepcopy(manifest), caption)
    model_view.gl_widget.viewChanged.connect(controller.on_view_changed)
    model_view._tooth_teaching_controller = controller
    for view in manifest["views"]:
        button = model_view.view_buttons.get(view["name"])
        if button is not None:
            button.setToolTip(view["caption"])
    # This is a view-local settings copy, never a persistent/global settings edit.
    settings = getattr(model_view.gl_widget, "settings", None)
    if settings is not None:
        model_view.gl_widget.settings = dict(settings, show_landmarks=True,
                                            max_landmarks=max(60, int(settings.get("max_landmarks", 60))))
    controller.show(manifest["start_view"], animate=False)
    return controller


class ToothTeachingController:
    """Per-native-view presentation state; no persistent variant selection logic."""

    def __init__(self, model_view, manifest, caption):
        self.model_view, self.manifest, self.caption = model_view, manifest, caption
        self.by_name = {v["name"]: v for v in manifest["views"]}
        self.original_label_flags = {it.key: it.label for it in model_view.vmodel.items}

    def show(self, name, *, animate=True):
        if name not in self.by_name:
            raise ValueError("Unknown tooth teaching view")
        self.model_view.gl_widget.set_named_view(name, animate=animate, visibility=True)

    def on_view_changed(self, name):
        if name not in self.by_name:
            return
        view = self.by_name[name]
        widget = self.model_view
        labels = set(view["label_keys"])
        for item in widget.vmodel.items:
            item.label = item.key in labels
        # Native named views reset hiding/isolation but retain these user modes.
        # Clearing them makes every teaching stage repeatable after manual use.
        widget.state.clear_selection()
        widget.state.clear_ghost()
        # Native camera hiding alone cannot override a previous system toggle,
        # region/subsystem restriction or depth dissection filter. These are
        # tiny per-item/category presentation arrays, never geometry buffers.
        for field in ("system_on", "subsystem_on", "region_on"):
            getattr(widget.state, field)[:] = True
        widget.state.system_alpha[:] = 1.0
        widget.state.depth_cut = 0.0
        widget.state.depth_band = 0.0
        widget.state._vis_dirty()
        widget.filter.clear()
        widget.labels.setChecked(True)
        if widget.opacity is not None:
            widget.opacity.setValue(100)
        widget.explode.setValue(0)
        self.caption.setText(view["caption"] + "\n" + "\n".join(view["teacher_labels"]))
        widget.gl_widget.invalidate_labels()

    def detach(self):
        """Remove this optional teaching label/caption controller, retaining presets."""
        widget = self.model_view
        widget.gl_widget.viewChanged.disconnect(self.on_view_changed)
        for item in widget.vmodel.items:
            item.label = self.original_label_flags[item.key]
        self.caption.deleteLater()
        widget._tooth_teaching_controller = None
        widget.gl_widget.invalidate_labels()
