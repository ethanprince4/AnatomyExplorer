"""Static thyroid/parathyroid lesson overlays; no app or geometry imports.

Call apply_lesson(view, proposal, state_id) only after the caller has loaded the
intended native ModelView. The future model-scoped lesson selector supplies the
view; this module does not launch or install that selector. It never edits a
source/cache file or a mesh. All physiology remains static explanatory text.
"""

from __future__ import annotations

import json
from pathlib import Path


MODEL_ID = "thyroid_parathyroid_review_v2"
SIGNAL_GROUP = "Endocrine signaling — schematic"


def load_proposal(path: str | Path) -> dict:
    """Read a small source-only lesson sidecar, then validate all references."""
    proposal = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_proposal(proposal)
    return proposal


def validate_proposal(proposal: dict) -> None:
    """Fail closed on unsupported IDs, state references or physical changes."""
    if proposal.get("schema_version") != 1 or proposal.get("model_id") != MODEL_ID:
        raise ValueError("Not the supported thyroid/parathyroid lesson sidecar")
    names = proposal.get("exact_parts", [])
    if len(names) != 30 or len(set(names)) != len(names):
        raise ValueError("Expected 30 distinct source part identities")
    contract = proposal.get("signal_contract", {})
    signals = contract.get("names", [])
    if (contract.get("count") != 9 or len(signals) != 9
            or len(set(signals)) != 9
            or set(signals) != {name for name in names if name.startswith("Signal ")}):
        raise ValueError("Expected the exact nine Signal-prefixed source parts")
    if (contract.get("group") != SIGNAL_GROUP
            or contract.get("clip") is not False
            or contract.get("bulk") is not False
            or contract.get("label") is not True
            or contract.get("geometry_policy") != "exact_copy"):
        raise ValueError("Unsupported static signal contract")
    motion = proposal.get("motion_policy", {})
    if (motion.get("animation") != "none"
            or any(motion.get(key) is not False for key in
                   ("auto_advance", "particle_motion", "transforms", "mesh_changes", "camera_animation"))):
        raise ValueError("Only reader-initiated static lesson states are supported")
    overrides = proposal.get("description_overrides", {})
    if set(overrides) - set(names) or not all(isinstance(x, str) for x in overrides.values()):
        raise ValueError("Invalid description overlay")
    states = proposal.get("states", [])
    state_ids = [state.get("id") for state in states]
    if not states or len(set(state_ids)) != len(state_ids):
        raise ValueError("Missing or duplicate lesson states")
    physical = set(names) - set(signals)
    for state in states:
        visible = state.get("visible_parts", [])
        hidden = state.get("hidden_parts", [])
        if (len(visible) != len(set(visible)) or len(hidden) != len(set(hidden))
                or set(visible) & set(hidden)
                or set(visible) | set(hidden) != set(names)):
            raise ValueError("State visibility must partition exact source parts")
        if set(hidden) - set(signals) or not physical <= set(visible):
            raise ValueError("Static function lessons cannot hide physical tissue")
        if (state.get("focus_part") not in visible
                or state.get("focus_part") not in overrides
                or state.get("selection_changes_only") is not True
                or state.get("physiological_state_simulation") is not False):
            raise ValueError("Invalid state focus or unsupported physiology simulation")
    opening = proposal.get("opening", {})
    if opening.get("state_id") not in state_ids or opening.get("labels_on") is not True:
        raise ValueError("Invalid opening lesson")
    overview = next(state for state in states if state["id"] == opening["state_id"])
    if overview["hidden_parts"]:
        raise ValueError("Opening must show every normal part and all nine cues")
    for sequence in proposal.get("functional_sequences", []):
        step_ids = [step.get("state_id") if isinstance(step, dict) else step
                    for step in sequence.get("steps", [])]
        if set(step_ids) - set(state_ids):
            raise ValueError("Functional sequence references a missing state")


def _view_parts(view, proposal: dict) -> dict:
    """Resolve names using native Items; do not inspect mesh buffers."""
    source = getattr(view.vmodel, "source", None)
    if getattr(source, "id", None) != MODEL_ID:
        raise ValueError("Refusing to modify an unrelated native model")
    items = list(view.vmodel.items)
    names = [item.name for item in items]
    if len(set(names)) != len(names) or set(names) != set(proposal["exact_parts"]):
        raise ValueError("Native part identities do not match the lesson sidecar")
    by_name = {item.name: item for item in items}
    for name in proposal["signal_contract"]["names"]:
        item = by_name[name]
        if (item.group != SIGNAL_GROUP or item.clip is not False
                or item.bulk is not False or item.label is not True):
            raise ValueError("Native cue metadata violates the static contract")
    if not isinstance(view.vmodel.sidecar, dict):
        raise ValueError("Native model lacks a mutable model-scoped sidecar")
    return by_name


def apply_lesson(view, proposal: dict, state_id: str) -> dict:
    """Apply in-memory description/visibility/selection only; return caption.

    This uses inspected native APIs: ModelView.labels.setChecked,
    SceneState.set_hidden/select and ModelViewport.invalidate_labels. It does
    not move the camera, switch a render state, change cut geometry, interpolate,
    mutate vertices, touch stored colors, launch timers or write files.
    """
    validate_proposal(proposal)
    state = next((state for state in proposal["states"] if state["id"] == state_id), None)
    if state is None:
        raise ValueError("Unknown thyroid/parathyroid lesson state")
    by_name = _view_parts(view, proposal)
    # Restore this overlay's defaults before replacing a selected state's prose.
    # The source MicroParts, frozen archives and original metadata remain intact.
    for name, description in proposal["description_overrides"].items():
        by_name[name].description = description
    focus = by_name[state["focus_part"]]
    details = [state["text"]]
    if state.get("limitations"):
        details.append("Simplification: " + " ".join(state["limitations"]))
    focus.description = "\n\n".join(details)
    # Prevent native Details from estimating a molecular dimension for a symbol.
    view.vmodel.sidecar["mixed_schematic_scale"] = True
    visible = [by_name[name].index for name in state["visible_parts"]]
    hidden = [by_name[name].index for name in state["hidden_parts"]]
    view.state.set_hidden(visible, False, undo=False)
    view.state.set_hidden(hidden, True, undo=False)
    view.labels.setChecked(True)
    view.state.select([focus.index])
    view.gl_widget.invalidate_labels()
    return {"id": state_id, "title": state["title"], "text": state["text"],
            "limitations": list(state.get("limitations", [])),
            "source_ids": list(state.get("source_ids", []))}


def apply_opening(view, proposal: dict) -> dict:
    """Retain the preconfigured native opening section; show all cues/layers."""
    return apply_lesson(view, proposal, proposal["opening"]["state_id"])


def apply_sequence_step(view, proposal: dict, sequence_id: str, step_index: int) -> dict:
    """Bridge lead native_adapter's dict-based sequence steps to manual states."""
    validate_proposal(proposal)
    rows = [row for row in proposal.get("functional_sequences", [])
            if row["id"] == sequence_id]
    if len(rows) != 1:
        raise KeyError(sequence_id)
    if not isinstance(step_index, int) or step_index < 0 or step_index >= len(rows[0]["steps"]):
        raise IndexError("Lesson step index is outside the sequence")
    step = rows[0]["steps"][step_index]
    state_id = step["state_id"] if isinstance(step, dict) else step
    payload = apply_lesson(view, proposal, state_id)
    payload.update(sequence=rows[0]["mechanism"], step=step,
                   sequence_limitations=list(rows[0]["schematic_limitations"]),
                   animation=False)
    return payload
