"""Static tooth teaching, using an already-open native ModelView.

Only the Python standard library is imported. Importing this file performs no
I/O and does not import the application, construct geometry, or start a viewer.
The application integration owner must call this on the GUI thread, after the
selected tooth variant has loaded. See INTEGRATION.md for the exact hook.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path


class StepContractError(ValueError):
    """An identity, selector or native-API prerequisite is missing."""


def _pair(selector):
    if not isinstance(selector, dict) or set(selector) != {"group", "name"}:
        raise StepContractError("Selector must contain exactly group and name")
    values = selector["group"], selector["name"]
    if not all(isinstance(v, str) and v for v in values):
        raise StepContractError("Selector group and name must be nonempty strings")
    return values


def validate_bundle(bundle):
    """Validate the small teaching sidecar; never load native meshes."""
    if bundle.get("schema_version") != 1 or bundle.get("model_id") != "tooth":
        raise StepContractError("Expected tooth static-step schema version 1")
    if bundle.get("presentation") != "static_steps":
        raise StepContractError("Only static_steps presentation is supported")
    selectors = [_pair(p) for p in bundle["selectors"]]
    if len(set(selectors)) != len(selectors):
        raise StepContractError("Duplicate canonical selector")
    known = set(selectors)
    evidence = {p["id"] for p in bundle["evidence"]}
    sequence_ids, step_ids = set(), set()
    for sequence in bundle["functional_sequences"]:
        sid = sequence["id"]
        if sid in sequence_ids:
            raise StepContractError("Duplicate sequence id: " + sid)
        sequence_ids.add(sid)
        if not sequence["schematic_limitations"] or not sequence["steps"]:
            raise StepContractError("Every sequence needs steps and limitations")
        if set(sequence["evidence_ids"]) - evidence:
            raise StepContractError("Unknown evidence id")
        for step in sequence["steps"]:
            key = sid, step["id"]
            if key in step_ids:
                raise StepContractError("Duplicate step id in sequence")
            step_ids.add(key)
            if step.get("action") != "static_focus":
                raise StepContractError("Non-static teaching action rejected")
            focus = [_pair(p) for p in step["focus_parts"]]
            visible = [_pair(p) for p in step["visible_parts"]]
            if not focus or len(focus) != len(set(focus)):
                raise StepContractError("Focus must contain distinct exact selectors")
            if not visible or len(visible) != len(set(visible)):
                raise StepContractError("Visibility must contain distinct exact selectors")
            if set(focus) - set(visible) or set(visible) - known:
                raise StepContractError("Focus/visibility selector outside contract")
            if not isinstance(step["text"], str) or not step["text"]:
                raise StepContractError("Step needs teaching text")
    return bundle


def load_bundle(path=None):
    path = Path(path) if path is not None else Path(__file__).with_name("function_sequences.json")
    return validate_bundle(json.loads(path.read_text(encoding="utf-8")))


def _step(bundle, sequence_id, step_id):
    validate_bundle(bundle)
    for sequence in bundle["functional_sequences"]:
        if sequence["id"] == sequence_id:
            for step in sequence["steps"]:
                if step["id"] == step_id:
                    return sequence, step
    raise StepContractError("Unknown tooth sequence/step")


def _preflight(view, bundle, step):
    # Do not use the app resolver's case-folded aliases/group expansion: this
    # contract intentionally requires the unchanged, exact group/name pairs.
    if getattr(getattr(view, "entry", None), "id", None) != bundle["model_id"]:
        raise StepContractError("Open ModelView entry must have id 'tooth'")
    model = getattr(view, "vmodel", None)
    items = getattr(model, "items", None)
    if items is None:
        raise StepContractError("Native view must expose vmodel.items")
    by_pair = {}
    for position, item in enumerate(items):
        pair = getattr(item, "group", None), getattr(item, "name", None)
        if pair in by_pair:
            raise StepContractError("Ambiguous native exact selector: " + repr(pair))
        if getattr(item, "index", None) != position:
            raise StepContractError("Native item.index no longer matches list position")
        by_pair[pair] = position
    missing = [p for p in bundle["selectors"] if _pair(p) not in by_pair]
    if missing:
        raise StepContractError("Missing native tooth selectors: " + repr(missing))
    state, gl = getattr(view, "state", None), getattr(view, "gl_widget", None)
    required = [(view, "show_all"), (view, "_show_selection"),
                (view, "clear_sections"), (view, "set_section"),
                (state, "isolate"), (state, "select"),
                (state, "set_depth"), (state, "set_system_alpha"),
                (state, "set_ghost_focus"), (state, "_snapshot"),
                (state, "restore"), (gl, "frame_structures"),
                (gl, "invalidate_labels"), (gl, "update")]
    for owner, name in required:
        if not callable(getattr(owner, name, None)):
            raise StepContractError("Native API unavailable: " + name)
    if not hasattr(state, "selected") or not hasattr(state, "_undo"):
        raise StepContractError("Native selection/undo contract unavailable")
    if not hasattr(state, "system_alpha") or not hasattr(gl, "cut_on"):
        raise StepContractError("Native opacity/cut contract unavailable")
    if len(getattr(gl, "sections", ())) != 3 or len(getattr(view, "section_rows", ())) != 3:
        raise StepContractError("Native three-axis section contract unavailable")
    for key, getter, setter in (("opacity", "value", "setValue"),
                               ("labels", "isChecked", "setChecked"),
                               ("cut", "isChecked", "setChecked")):
        control = getattr(view, key, None)
        if control is not None and not all(callable(getattr(control, name, None)) for name in (getter, setter)):
            raise StepContractError("Native control contract unavailable: " + key)
    for _box, _slider, flip in view.section_rows:
        if not all(callable(getattr(flip, name, None)) for name in ("isChecked", "setChecked", "blockSignals")):
            raise StepContractError("Native section flip control contract unavailable")
    camera = getattr(gl, "camera", None)
    fields = ("target", "distance", "yaw", "pitch", "fov", "ortho", "ortho_width", "_anim")
    if any(not hasattr(camera, key) for key in fields):
        raise StepContractError("Native restorable camera contract unavailable")
    return ([by_pair[_pair(p)] for p in step["focus_parts"]],
            [by_pair[_pair(p)] for p in step["visible_parts"]])


class StaticStepSession:
    """Reversible native visibility/selection/framing only; no simulated biology."""

    def __init__(self, view, bundle):
        self.view = view
        self.bundle = validate_bundle(bundle)
        self._saved = None
        self._closed = False

    def _capture(self):
        view = self.view
        camera = view.gl_widget.camera
        return {"state": deepcopy(view.state._snapshot()),
                "selected": list(view.state.selected),
                "undo": list(view.state._undo),
                "part_alpha_present": hasattr(view.state, "part_alpha"),
                "part_alpha": deepcopy(getattr(view.state, "part_alpha", None)),
                "cut_on": view.gl_widget.cut_on,
                "sections": deepcopy(view.gl_widget.sections),
                "section_flips": [flip.isChecked() for _box, _slider, flip in view.section_rows],
                "controls": {key: (getattr(view, key).value() if key == "opacity" else getattr(view, key).isChecked())
                             for key in ("opacity", "labels", "cut") if getattr(view, key, None) is not None},
                "camera": {key: deepcopy(getattr(camera, key)) for key in
                           ("target", "distance", "yaw", "pitch", "fov", "ortho", "ortho_width")}}

    def _restore(self, saved):
        view = self.view
        for key, value in saved["controls"].items():
            control = getattr(view, key)
            (control.setValue if key == "opacity" else control.setChecked)(value)
        for axis, section in enumerate(saved["sections"]):
            view.set_section(axis, section is not None)
        # set_section updates actions/bar widgets, but may choose a default
        # flip when re-enabling an axis. Restore the reader's exact flip flags.
        for row, value in zip(view.section_rows, saved["section_flips"]):
            flip = row[2]
            previous = flip.blockSignals(True)
            flip.setChecked(value)
            flip.blockSignals(previous)
        view.gl_widget.sections = deepcopy(saved["sections"])
        view.gl_widget.cut_on = saved["cut_on"]
        view.state.restore(deepcopy(saved["state"]))
        if saved["part_alpha_present"]:
            view.state.part_alpha = deepcopy(saved["part_alpha"])
        elif hasattr(view.state, "part_alpha"):
            delattr(view.state, "part_alpha")
        view.state.select(saved["selected"])
        view.state._undo = list(saved["undo"])
        camera = view.gl_widget.camera
        camera._anim = None
        for key, value in saved["camera"].items():
            setattr(camera, key, deepcopy(value))
        view._show_selection()
        view.gl_widget.invalidate_labels()
        view.gl_widget.update()

    def apply(self, sequence_id, step_id):
        if self._closed:
            raise StepContractError("Static-step session is closed")
        sequence, step = _step(self.bundle, sequence_id, step_id)
        focus, visible = _preflight(self.view, self.bundle, step)
        # Capture only after every identity/API/selector prerequisite succeeds.
        before = self._capture()
        if self._saved is None:
            self._saved = before
        try:
            self.view.show_all()
            self.view.state.set_depth(0.0, band=0.0)
            for system in range(len(self.view.state.system_alpha)):
                self.view.state.set_system_alpha(system, 1.0)
            if getattr(self.view, "opacity", None) is not None:
                self.view.opacity.setValue(100)
            # Renderer defaults to each original material's alpha when the
            # reader's per-item multiplier is absent/None; source Looks stay
            # unchanged. The accepted tooth materials are opaque.
            self.view.state.part_alpha = None
            self.view.clear_sections()
            if getattr(self.view, "cut", None) is not None:
                self.view.cut.setChecked(False)
            self.view.gl_widget.cut_on = False
            if getattr(self.view, "labels", None) is not None:
                self.view.labels.setChecked(True)
            self.view.state.isolate(visible)
            self.view.state.select(focus)
            self.view.state.set_ghost_focus(focus)
            self.view._show_selection()
            # The built-in focus_parts queues a 250 ms callback. Immediate,
            # zero-duration framing avoids an older step moving a newer view.
            self.view.gl_widget.frame_structures(focus, duration=0.0)
            self.view.gl_widget.invalidate_labels()
            self.view.gl_widget.update()
        except Exception:
            self._restore(before)
            raise
        return {"model_id": "tooth", "sequence_id": sequence_id,
                "step_id": step_id, "title": step["title"],
                "text": step["text"], "focused_indices": focus,
                "visible_indices": visible,
                "schematic_limitations": sequence["schematic_limitations"]}

    def close(self):
        """Restore state, selection, undo history and the pre-lesson camera."""
        if not self._closed and self._saved is not None:
            self._restore(self._saved)
        self._closed = True


def native_lessons(bundle):
    """JSON records accepted by app.lessons.load_lessons; no app import."""
    validate_bundle(bundle)
    lesson = {"id": "tooth_structure_function_static", "title": "Tooth: structure and function",
              "system": "digestive", "region": "head_neck", "level": "core",
              "summary": "A static guided explanation of tissue roles, pulpal supply and drainage, periodontal support and dentin sensitivity.",
              "objectives": bundle["objectives"], "steps": [],
              "tags": ["tooth", "structure-function", "static teaching"]}
    for sequence in bundle["functional_sequences"]:
        for step in sequence["steps"]:
            lesson["steps"].append({"title": step["title"], "text": step["text"],
                                    "micro": "tooth",
                                    "micro_focus": [p["name"] for p in step["focus_parts"]],
                                    "tooth_static": {"schema_version": 1,
                                                     "sequence_id": sequence["id"], "step_id": step["id"]},
                                    "pitfall": " ".join(sequence["schematic_limitations"]),
                                    "check": deepcopy(step["check"])})
    return [lesson]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate/export tooth static teaching only")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--export-lessons", type=Path)
    args = parser.parse_args(argv)
    bundle = load_bundle(args.bundle)
    if args.export_lessons is not None:
        if args.export_lessons.exists():
            parser.error("Refusing to overwrite an existing lesson output")
        args.export_lessons.write_text(json.dumps(native_lessons(bundle), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"model_id": "tooth", "sequences": len(bundle["functional_sequences"]),
                      "steps": sum(len(s["steps"]) for s in bundle["functional_sequences"]),
                      "geometry_processed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
