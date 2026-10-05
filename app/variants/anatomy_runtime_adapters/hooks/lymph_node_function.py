"""Resolve lymph-node manual frames without importing builders or native apps."""

import argparse
from copy import deepcopy
import json
from pathlib import Path


def validate(document):
    if document.get("schema_version") != 1 or document.get("model_id") != "lymph_node":
        raise ValueError("Expected lymph_node function schema version 1")
    names = document["part_names"]
    if len(names) != 21 or len(set(names)) != 21:
        raise ValueError("Expected 21 unique exact part selectors")
    sequences = document["sequences"]
    if len({s["id"] for s in sequences}) != len(sequences):
        raise ValueError("Duplicate sequence identifier")
    for sequence in sequences:
        if len({s["id"] for s in sequence["steps"]}) != len(sequence["steps"]):
            raise ValueError("Duplicate step identifier")
        for step in sequence["steps"]:
            state = step["state"]
            visible, hidden = set(state["visible_parts"]), set(state["hidden_parts"])
            if len(visible) != len(state["visible_parts"]) or len(hidden) != len(state["hidden_parts"]):
                raise ValueError("Frame part selectors must not repeat")
            if visible & hidden or visible | hidden != set(names):
                raise ValueError("Every frame must partition all exact part selectors")
            if not set(state["focus_parts"]) <= visible or not set(state["labels"]) <= visible:
                raise ValueError("Frame focus and labels must be visible")
            if len(state["labels"]) > 3 or state["layer_separation"] != 0:
                raise ValueError("Unsupported label budget or tissue separation")
            if state["opacity"] != "preserve_part_alpha":
                raise ValueError("Function frames must preserve source transparency")
            if not step["caption"] or not step["schematic_limitations"] or step["advance"] != "manual":
                raise ValueError("Each manual frame needs a caption and explicit limitations")
    for route in document["routes"]:
        if not set(route["ordered_parts"]) <= set(names):
            raise ValueError("Route uses unknown parts")
        if route["geometric_animation_enabled"] is not False:
            raise ValueError("Geometric animation has not been implemented or validated")
    if not set(document["description_overrides"]) <= set(names):
        raise ValueError("Description override uses unknown parts")
    return document


def resolve(document, sequence_id, step_id, variant="design", model_sha256=""):
    validate(document)
    sequence = next((s for s in document["sequences"] if s["id"] == sequence_id), None)
    if sequence is None:
        raise ValueError("Unknown sequence")
    step = next((s for s in sequence["steps"] if s["id"] == step_id), None)
    if step is None:
        raise ValueError("Unknown frame")
    return {"model_id": "lymph_node", "sequence_id": sequence_id, "step_id": step_id,
            "state": deepcopy(step["state"]), "caption": step["caption"],
            "mechanism": step["mechanism"],
            "schematic_limitations": list(step["schematic_limitations"]),
            "source_variant": variant, "model_sha256": model_sha256,
            "simulation": False, "geometric_animation_enabled": False}


def manifest_bindings(document, construction_manifest):
    """Report small prewarp-locus availability; never resolve world-space tracks.

    The builder's final settling deformation changes coordinates. Availability
    of prewarp loci is not certification of saved geometry or connectivity.
    """
    validate(document)
    if construction_manifest is None:
        return {"status": "manifest_not_supplied", "geometric_animation_enabled": False}
    if construction_manifest.get("model_id") not in ("lymph_node", "lymph_node_design", "lymph_node_design_review"):
        raise ValueError("Construction manifest model mismatch")
    availability = {}
    for route in document["routes"]:
        found, missing = [], []
        for binding in route["manifest_bindings"]:
            value = construction_manifest
            for key in binding.split("."):
                value = value.get(key) if isinstance(value, dict) else None
            (found if value is not None else missing).append(binding)
        availability[route["id"]] = {"found": found, "missing": missing}
    return {"status": "prewarp_metadata_only", "availability": availability,
            "geometric_animation_enabled": False,
            "note": "These loci require the final deformation and saved-model checks before physical route display."}


def install_function_presets(model, document, variant="design", model_sha256="", construction_manifest=None):
    """Append camera-menu presets after the teaching adapter on a new model.

    Native camera selection applies hidden and cut_on. Captions, focus and label
    suggestions are accompanying sidecar content, not an automatic native UI.
    Preserve camera geometry and part opacity; original lymph_node is forbidden.
    """
    if getattr(model, "id", None) not in ("lymph_node_design", "lymph_node_design_review", "lymph_node_refinement"):
        raise ValueError("Function presets apply only to a new additive lymph-node model")
    validate(document)
    construction_binding = manifest_bindings(document, construction_manifest)
    cameras = deepcopy(model.viewer_cameras)
    frames = []
    for sequence in document["sequences"]:
        for step in sequence["steps"]:
            frame = resolve(document, sequence["id"], step["id"], variant, model_sha256)
            state = frame["state"]
            preset = state["camera_preset"]
            if preset not in cameras:
                raise ValueError("Teaching camera missing: " + preset)
            record = deepcopy(cameras[preset])
            record["hidden"] = list(state["hidden_parts"])
            record["cut_on"] = state["cut_on"]
            record["note"] = frame["caption"] + " " + " ".join(frame["schematic_limitations"])
            key = "FUNCTION " + sequence["id"] + " " + step["id"]
            if key in cameras:
                raise ValueError("Function preset already installed: " + key)
            cameras[key] = record
            frames.append(dict(frame, installed_camera_preset=key))
    model.viewer_cameras = cameras
    return {"frames": frames, "routes": deepcopy(document["routes"]),
            "construction_binding": construction_binding,
            "caption_display": "Manual accompanying sidecar; native camera notes are not automatically displayed"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar", type=Path, default=Path(__file__).with_name("function_sequences.json"))
    parser.add_argument("--sequence")
    parser.add_argument("--step")
    parser.add_argument("--source-variant", default="design")
    parser.add_argument("--model-sha256", default="")
    parser.add_argument("--construction-manifest", type=Path)
    args = parser.parse_args(argv)
    document = validate(json.loads(args.sidecar.read_text(encoding="utf-8")))
    if args.sequence is None:
        result = {"validated": True, "sequences": [s["id"] for s in document["sequences"]],
                  "frames": sum(len(s["steps"]) for s in document["sequences"])}
    else:
        if not args.step:
            parser.error("--sequence requires --step")
        result = resolve(document, args.sequence, args.step, args.source_variant, args.model_sha256)
    manifest = json.loads(args.construction_manifest.read_text(encoding="utf-8")) if args.construction_manifest else None
    result["construction_binding"] = manifest_bindings(document, manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
