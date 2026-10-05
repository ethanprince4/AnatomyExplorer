"""Apply an already-authored tongue teaching step to a loaded native ModelView.

Import-safe: standard library only; does not load models, import the app, render,
create widgets, register lessons, or run work at import time. App orchestration
must call this on its GUI thread after the model's initial reset_view has run.
This is a static selection/view adapter, never a physiology simulation.
"""
import json
from pathlib import Path


class HookUnavailable(ValueError):
    """The loaded source/UI does not meet this teaching contract."""


def load_contract(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def find_step(contract, sequence_id, step_id):
    for sequence in contract["sequences"]:
        if sequence["id"] == sequence_id:
            for step in sequence["steps"]:
                if step["id"] == step_id:
                    return step
    raise HookUnavailable(f"Unknown tongue step: {sequence_id}/{step_id}")


def preflight(view, contract, sequence_id, step_id):
    """Resolve exact item selectors and camera before changing the scene."""
    if getattr(view.entry, "id", None) not in contract["allowed_entry_ids"]:
        raise HookUnavailable("The loaded catalogue entry is not the bound tongue model.")
    step = find_step(contract, sequence_id, step_id)
    if step["camera"] not in view.vmodel.cameras:
        raise HookUnavailable("Missing authored camera: " + step["camera"])
    by_name = {}
    for item in view.vmodel.items:
        by_name.setdefault(item.name, []).append(item.index)
    needed = list(dict.fromkeys(step["focus_selectors"] + step["context_selectors"] +
                               step["required_visible"] + step["removed_tissue_selectors"]))
    ids = {}
    for name in needed:
        if len(by_name.get(name, [])) != 1:
            raise HookUnavailable("Missing or ambiguous exact item: " + name)
        resolved, missing = view.part_ids([name])
        if missing or list(dict.fromkeys(resolved)) != by_name[name]:
            raise HookUnavailable("Selector does not resolve to its exact item: " + name)
        ids[name] = by_name[name][0]
    if set(step["required_visible"]) & set(step["removed_tissue_selectors"]):
        raise HookUnavailable("The authored step removes required context.")
    if getattr(view, "click_hook", None) is not None:
        raise HookUnavailable("Exit practice mode before running a narrated step.")
    if view.gl_widget.anim_kind() is not None:
        raise HookUnavailable("This static contract is not bound to an animated model.")
    for attr in ["clear_sections", "set_named_view", "state", "explode", "labels"]:
        if not hasattr(view, attr):
            raise HookUnavailable("Native ModelView is missing: " + attr)
    return step, ids


def apply_step(view, contract, sequence_id, step_id, context_reset=None):
    """Apply static tissue visibility and selection; return learner-facing text.

    Does not call focus_parts: that method queues a new bounding-box camera and
    ghosts host tissue after 250 ms, defeating a precise intact/open camera pair.
    The app caller remains responsible for presenting returned narration and
    preserving/restoring its lesson session. No new UI control is installed here.
    Pass teaching_sidecar.set_named_view_with_context_reset as context_reset for
    generated contracts to reset group, depth and alpha filters with the camera.
    Camera names are read from the supplied contract; they are not hard-coded.
    Set context_reset_required=true in that generated contract to fail closed
    when its reset implementation is not supplied.
    """
    if context_reset is not None and not callable(context_reset):
        raise HookUnavailable("context_reset must be a callable(view, camera_name).")
    if contract.get("context_reset_required", False) and context_reset is None:
        raise HookUnavailable("This contract requires its teaching context-reset callback.")
    step, ids = preflight(view, contract, sequence_id, step_id)
    view.clear_sections()
    if view.cut is not None:
        view.cut.setChecked(False)
    view.explode.setValue(0)
    if view.opacity is not None:
        view.opacity.setValue(100)
    view.state.clear_ghost()
    if context_reset is None:
        view.set_named_view(step["camera"])
    else:
        context_reset(view, step["camera"])
    view.state.set_hidden([ids[name] for name in step["required_visible"]], False)
    if step["removed_tissue_selectors"]:
        view.state.set_hidden([ids[name] for name in step["removed_tissue_selectors"]], True)
    view.state.select([ids[name] for name in step["focus_selectors"]])
    view.labels.setChecked(True)
    view.gl_widget.update()
    visible = view.state.visible_mask()
    missing_context = [name for name in step["required_visible"] if not visible[ids[name]]]
    if missing_context:
        raise HookUnavailable("Required tissue is still hidden: " + ", ".join(missing_context))
    return {"title": step["title"], "text": step["text"],
            "display_mode": "static_narrated_trace",
            "removed_tissue": step["removed_tissue_selectors"],
            "scale_note": contract["scale_note"],
            "source_ids": step["source_ids"]}
