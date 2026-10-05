"""Install model-owned tracheal presets on an already-created native ModelView.

Import-safe: no application imports, loading, geometry, or rendering occurs here.
Call install(model_view, views_path, variant) after creating the native ModelView.
The caller owns opening the exact hash-bound cache/candidate; this module only
binds teaching camera/visibility/section state to the existing native controls.
"""
import json
from pathlib import Path


def bind_controls(model_view, settings):
    native = model_view.vmodel
    actual = {item.key for item in native.items}
    expected = set(settings["parts"])
    if actual != expected:
        raise ValueError("Trachea view variant does not match exact saved item identities")
    cameras = settings["cameras"]
    for record in cameras.values():
        if not set(record.get("hidden", [])) <= actual:
            raise ValueError("Unknown hidden tracheal item")
        if record.get("cut_on") is not False:
            raise ValueError("Tracheal cameras must clear stale cuts")
    native.cameras = cameras
    native.camera_order = settings["camera_order"]
    native.sidecar["start_view"] = settings["start_view"]
    model_view._view_names = list(native.camera_order)
    viewport = model_view.gl_widget
    # This connection follows ModelView's existing _view_changed connection.
    # Native dropdown/next/home controls all emit the same viewChanged signal.
    previous = getattr(model_view, "_trachea_view_handler", None)
    if previous is not None:
        viewport.viewChanged.disconnect(previous)

    def apply_sections(name):
        model_view.clear_sections()
        viewport.cut_on = False
        for record in settings["section_presets"].get(name, []):
            k = record["axis_index"]
            fraction = float(record["fraction"])
            if k not in (0, 1, 2) or not 0 <= fraction <= 1:
                raise ValueError("Invalid model-relative section preset")
            _box, slider, flip = model_view.section_rows[k]
            was = slider.blockSignals(True)
            slider.setValue(round(fraction * 1000))
            slider.blockSignals(was)
            # set_section applies native UI defaults (including auto flip for
            # axes 1/2). Override flip after enabling, then preserve exact
            # fractional position despite the native UI's 0.1% slider steps.
            model_view.set_section(k, True)
            was = flip.blockSignals(True)
            flip.setChecked(bool(record["flip"]))
            flip.blockSignals(was)
            lo, hi = model_view._axis_range(k)
            viewport.sections[k] = [lo + (hi - lo) * fraction, bool(record["flip"])]
        viewport.invalidate_labels()
        viewport.update()

    model_view._trachea_view_handler = apply_sections
    viewport.viewChanged.connect(apply_sections)
    viewport.set_named_view(settings["start_view"], animate=False, visibility=True)
    return apply_sections
