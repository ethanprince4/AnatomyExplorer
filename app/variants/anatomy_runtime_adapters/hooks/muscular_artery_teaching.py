"""Source-only teaching adapter for the existing Anatomy Explorer native viewer.

No app imports, geometry reads or work at import. A future isolated runtime may
call attach_metadata(micro_model, exact_part_names, spec) BEFORE constructing its
ProceduralModel, then install_controller(model_view, spec) AFTER ModelView exists.
No shared application files are edited. This adapter has not run in the app here.
"""
from copy import deepcopy
from html import escape
import json
from pathlib import Path

SCALE_NOTE = (
    "Macro calibration: 1 model unit = 2.6 mm. Cell, nuclear, fibre, wall-vessel "
    "and neural representatives are enlarged and sparsely sampled; they do not "
    "share a verified uniform enlargement or literal density. IEL/EEL apertures "
    "are sparse enlarged teaching examples. The legacy 20x rat experimental "
    "pore prior is not human pore morphometry; the calibrated ruler is not a "
    "microscopic scale bar."
)


def load_spec(path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    if spec.get("schema_version") != 1 or spec.get("model_id") != "muscular_artery":
        raise ValueError("Expected muscular_artery teaching schema 1")
    if len({view["id"] for view in spec["views"]}) != len(spec["views"]):
        raise ValueError("Teaching view identifiers must be unique")
    return spec


def validate_selectors(part_names, spec):
    """Fail on unavailable teaching geometry; never silently drop a selector."""
    names = tuple(part_names)
    if len(set(names)) != len(names):
        raise ValueError("Native part keys must be unique")
    known = set(names)
    missing = {}
    for view in spec["views"]:
        wanted = set(view["visible_parts"]) | set(view.get("selected_parts", []))
        absent = sorted(wanted - known)
        if absent:
            missing[view["id"]] = absent
        if not set(view.get("selected_parts", [])) <= set(view["visible_parts"]):
            raise ValueError("Selected parts must be visible: " + view["id"])
    if missing:
        raise ValueError("Unimplemented teaching selectors: " + json.dumps(missing))
    return names


def native_metadata(part_names, spec):
    names = validate_selectors(part_names, spec)
    cameras = {}
    for view in spec["views"]:
        rec = deepcopy(view["camera"])
        rec.update(hidden=[key for key in names if key not in view["visible_parts"]],
                   state="assembled", cut_on=bool(view["cut_on"]),
                   note=view["purpose"] + " " + view["scale_note"])
        cameras[view["id"]] = rec
    return {"metres_per_unit": 0.0026, "scale_note": spec["scale_note"],
            "summary": spec["summary"], "viewer_cameras": cameras,
            "start_view": spec["opening_view"], "cut_on": True,
            "cutaway": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            "cut_at": (0.0, 0.0)}


def attach_metadata(micro_model, part_names=None, spec=None):
    spec = spec or load_spec(Path(__file__).with_name("native_views.json"))
    mid = getattr(micro_model, "id", "")
    if mid not in {"muscular_artery", "muscular_artery_refined"}:
        raise ValueError("This adapter is model-specific")
    if part_names is None:
        parts = getattr(micro_model, "_parts", None)
        if parts is None:
            raise ValueError("Provide saved parts first; adapter never invokes a builder")
        part_names = [part.name for part in parts]
    for key, value in native_metadata(part_names, spec).items():
        setattr(micro_model, key, value)


def _set_slider(widget, value):
    if widget is None:
        return
    old = widget.blockSignals(True)
    try:
        widget.setValue(value)
    finally:
        widget.blockSignals(old)


def apply_controls(model_view, view, spec):
    """Reset complete exploration state using existing ModelView controls.

    Named camera visibility alone cannot save opacity, sections or separation.
    Call on native viewChanged after set_named_view has applied its camera.
    """
    native = model_view.vmodel
    validate_selectors((item.key for item in native.items), spec)
    for section in view["sections"]:
        axis = section["native_axis_index"]
        if axis not in (0, 1, 2):
            raise ValueError("Invalid native section axis")
        lo, hi = model_view._axis_range(axis)
        if not lo <= section["position"] <= hi or hi <= lo:
            raise ValueError("Section outside the saved specimen bounds")
    lookup = {item.key: item.index for item in native.items}
    state, viewport = model_view.state, model_view.gl_widget
    state.reset_visibility()
    state.set_depth(0.0, band=0.0)
    state.system_alpha[:] = 1.0
    state.custom_colors.clear()
    state.clear_ghost()
    state.isolate([lookup[key] for key in view["visible_parts"]])
    state.select([lookup[key] for key in view.get("selected_parts", [])])
    model_view.clear_sections()
    viewport.cut_on = bool(view["cut_on"])
    viewport.reveal_state = None
    viewport.reveal_amount = viewport.reveal_target = 0.0
    viewport.playing = False
    viewport.set_anim_fraction(0.0)
    _set_slider(model_view.explode, round(view["explode"] * 100))
    viewport.set_explode(view["explode"])
    _set_slider(model_view.opacity, view["tissue_opacity_percent"])
    if model_view.opacity is not None:
        model_view._opacity(view["tissue_opacity_percent"])
    for section in view["sections"]:
        axis = section["native_axis_index"]
        _box, slider, flip = model_view.section_rows[axis]
        lo, hi = model_view._axis_range(axis)
        if not lo <= section["position"] <= hi or hi <= lo:
            raise ValueError("Section outside the saved specimen bounds")
        _set_slider(slider, round(1000 * (section["position"] - lo) / (hi - lo)))
        old = flip.blockSignals(True)
        try:
            flip.setChecked(section["flip"])
        finally:
            flip.blockSignals(old)
        model_view.set_section(axis, True)
        # set_section supplies atlas defaults; this vessel-specific plane is exact.
        viewport.sections[axis] = [section["position"], section["flip"]]
    if model_view.cut is not None:
        old = model_view.cut.blockSignals(True)
        try:
            model_view.cut.setChecked(viewport.cut_on)
        finally:
            model_view.cut.blockSignals(old)
    viewport.invalidate_labels()
    viewport.update()
    body = "<p>" + escape(view["purpose"]) + "</p>"
    body += "<p>" + escape(view["scale_note"]) + "</p>"
    body += "<p>" + escape(view["inspection_task"]) + "</p>"
    # The info panel is attached after opening. Skipping it here lets the model load.
    if model_view.info is not None:
        model_view.info.show_html("<h1>" + escape(view["id"]) + "</h1>", body)


def install_controller(model_view, spec=None):
    """Explicit runtime hook; returns disconnect callable for this view only."""
    spec = spec or load_spec(Path(__file__).with_name("native_views.json"))
    native = model_view.vmodel
    validate_selectors((item.key for item in native.items), spec)
    if not set(view["id"] for view in spec["views"]) <= set(native.cameras):
        raise ValueError("Attach native metadata before constructing ModelView")
    if getattr(model_view, "_muscular_teaching_controller", None) is not None:
        raise ValueError("Controller already installed on this view")
    # Native Details otherwise reports macro-calibrated dimensions for symbols.
    native.sidecar["mixed_schematic_scale"] = True
    by_id = {view["id"]: view for view in spec["views"]}

    def on_view(name):
        if name in by_id:
            apply_controls(model_view, by_id[name], spec)

    viewport = model_view.gl_widget
    viewport.viewChanged.connect(on_view)
    model_view._muscular_teaching_controller = on_view
    model_view.set_named_view(spec["opening_view"])

    def disconnect():
        viewport.viewChanged.disconnect(on_view)
        model_view._muscular_teaching_controller = None

    return disconnect


def install_registry_view_hook(review_model_id="muscular_artery_refined", spec=None):
    """Deferred isolated runtime hook for ordinary panes of one review model.

    Call explicitly after QApplication creation, not during early registry
    discovery. Registers a Qt event filter, not a replacement application class.
    No native app or Qt import occurs until this function is explicitly called.
    A registry without an existing QApplication must defer this to its launcher.
    Returns an uninstall callable. Native GUI validation remains deferred.
    """
    if review_model_id != "muscular_artery_refined":
        raise ValueError("This hook targets only muscular_artery_refined")
    spec = spec or load_spec(Path(__file__).with_name("native_views.json"))
    from PySide6.QtCore import QObject, QEvent
    from PySide6.QtWidgets import QApplication
    from app.ui.model_view import ModelView

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("Install review hook after QApplication creation")

    class ReviewFilter(QObject):
        def __init__(self):
            super().__init__(app)
            self.disconnects = []

        def eventFilter(self, watched, event):
            if event.type() == QEvent.Show and isinstance(watched, ModelView):
                micro = getattr(getattr(watched, "entry", None), "micro", None)
                if (getattr(micro, "id", None) == review_model_id
                        and getattr(watched, "_muscular_teaching_controller", None) is None):
                    self.disconnects.append(install_controller(watched, spec))
            return False

    event_filter = ReviewFilter()
    app.installEventFilter(event_filter)

    def uninstall():
        app.removeEventFilter(event_filter)
        for disconnect in event_filter.disconnects:
            try:
                disconnect()
            except RuntimeError:
                pass  # A pane may already have been destroyed.
        event_filter.deleteLater()

    return uninstall
