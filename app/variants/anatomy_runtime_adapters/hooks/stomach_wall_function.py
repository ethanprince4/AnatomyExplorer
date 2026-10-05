"""Small import-safe compiler for stomach-wall functional teaching data.

Consumes JSON only. Compiles exact native camera fields and tooltip narration;
never imports an application/builder or computes meshes, motion, or physiology.
Apply an episode only to a newly created stomach review alias, before loading it.
"""
from __future__ import annotations

from copy import deepcopy
import argparse
import json
from pathlib import Path

_NATIVE_CAMERA_FIELDS = {"position", "target", "type", "ortho_width", "hidden", "cut_on", "state", "note"}


def compile_episode(payload, teaching, sequence_id):
    """Return a deterministic native view bundle plus separate structured narration."""
    if payload.get("model_id") != "stomach_wall" or teaching.get("model_id") != "stomach_wall":
        raise ValueError("Expected stomach_wall function and teaching records")
    exact = payload["exact_part_names"]
    if len(exact) != len(set(exact)) or set(exact) != set(teaching["exact_part_names"]):
        raise ValueError("Exact part inventory differs or contains duplicates")
    valid = set(exact)
    candidates = [s for s in payload["sequences"] if s["id"] == sequence_id]
    if len(candidates) != 1:
        raise ValueError("Unknown or duplicate functional sequence")
    sequence = candidates[0]
    cameras = teaching["native_defaults"]["viewer_cameras"]
    opening = teaching["native_defaults"]["start_view"]
    if opening not in cameras:
        raise ValueError("Missing opening native camera")
    overview = deepcopy(cameras[opening])
    overview["note"] = payload["global_scale_note"] + " " + payload["implementation_status"]
    result = {
        "schema_version": 1,
        "model_id": "stomach_wall",
        "sequence_id": sequence_id,
        "start_view": "Function overview",
        "viewer_cameras": {"Function overview": overview},
        "narration": [],
        "execution": "manual_named_view_steps",
        "simulation": False,
    }
    seen_ids = set()
    for state in sequence["states"]:
        sid = state["id"]
        if sid in seen_ids:
            raise ValueError("Duplicate state id")
        seen_ids.add(sid)
        shown = state["visible_parts"]
        hidden = state["hidden_parts"]
        emphasized = state["highlight_parts"]
        if len(shown) != len(set(shown)) or len(hidden) != len(set(hidden)):
            raise ValueError("Duplicate part names in state")
        if set(shown) | set(hidden) != valid or set(shown) & set(hidden):
            raise ValueError("State visibility is not a complete, disjoint exact-part partition")
        if not set(emphasized) <= set(shown):
            raise ValueError("Highlighted part is not visible")
        if state["native_view"] not in cameras:
            raise ValueError("Unknown native source camera")
        if not set(state["active_routes"]) <= set(payload["routes"]):
            raise ValueError("Unknown route id")
        if not set(state["source_evidence"]) <= {e["id"] for e in payload["evidence"]}:
            raise ValueError("Unknown evidence id")
        name = state["native_stage_name"]
        if name in result["viewer_cameras"]:
            raise ValueError("Duplicate native stage name")
        camera = deepcopy(cameras[state["native_view"]])
        if set(camera) - _NATIVE_CAMERA_FIELDS:
            raise ValueError("Unsupported native camera field")
        camera["hidden"] = hidden.copy()
        camera["note"] = state["caption"] + " " + state["display_limit"]
        camera["state"] = "assembled"
        result["viewer_cameras"][name] = camera
        result["narration"].append(deepcopy(state))
    if len(result["viewer_cameras"]) > 10:
        raise ValueError("Episode exceeds native named-button teaching budget")
    return result


def attach_functional_episode(review_model, sequence_id, states_path=None, teaching_path=None):
    """Opt-in native cameras for a fresh review alias; no part or geometry mutation.

    Native notes appear as named-view button tooltips in the selected baseline.
    The existing five-view teaching helper remains the normal opening pathway.
    Structured routes/highlights are data for later UI integration, not executed.
    """
    model_id = getattr(review_model, "id", "")
    if model_id == "stomach_wall" or not model_id.startswith("stomach_wall_"):
        raise ValueError("Use a fresh stomach_wall_ review alias, preserving original registration")
    here = Path(__file__).resolve().parent
    sp = Path(states_path) if states_path else here / "functional_states.json"
    tp = Path(teaching_path) if teaching_path else here / "teaching.json"
    payload = json.loads(sp.read_text(encoding="utf-8"))
    teaching = json.loads(tp.read_text(encoding="utf-8"))
    preloaded = getattr(review_model, "_parts", None)
    if preloaded is not None and {p.name for p in preloaded} != set(payload["exact_part_names"]):
        raise ValueError("Preloaded review parts differ; no lazy part builder is called")
    result = compile_episode(payload, teaching, sequence_id)
    review_model.viewer_cameras = deepcopy(result["viewer_cameras"])
    review_model.start_view = result["start_view"]
    native = teaching["native_defaults"]
    review_model.cut_on = native["cut_on"]
    review_model.cut_at = tuple(native["cut_at"])
    review_model.cutaway = tuple(tuple(x) for x in native["cutaway"])
    review_model.home_view = tuple(native["home_view"])
    review_model.metres_per_unit = native["metres_per_unit"]
    review_model.scale_note = payload["global_scale_note"]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compile small stomach functional teaching views from JSON only")
    parser.add_argument("--states", type=Path, required=True)
    parser.add_argument("--teaching", type=Path, required=True)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = compile_episode(json.loads(args.states.read_text(encoding="utf-8")),
                             json.loads(args.teaching.read_text(encoding="utf-8")), args.sequence)
    # A new artifact lane is mandatory. Never overwrite another teaching result.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
