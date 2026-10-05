"""Presentation-only thyroid function hook; no geometry/native-app imports.

The native procedural viewer can consume frame(names, phase) nested lists.
Every morph weight is zero. Glow means teaching emphasis, never concentration.
Per-variant identity must be supplied by the root's verified artifact manifest.
"""
from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from pathlib import Path

MODEL_ID = "thyroid_follicles"
VARIANTS = ("pre_refine", "post_refine")
MAX_SPEC_BYTES = 65536
MAX_PARTS = 64
EXPECTED_PAIRS = {
    ("Follicular epithelium", "Thyroid follicles"),
    ("Colloid", "Thyroid follicles"),
    ("Resorption vacuoles", "Thyroid follicles"),
    ("Parafollicular C cells", "Thyroid follicles"),
    ("Perifollicular capillaries", "Vessels"),
    ("Arteries (capsular & interlobular)", "Vessels"),
    ("Veins (capsular & interlobular)", "Vessels"),
    ("Interfollicular connective tissue", "Capsule & stroma"),
    ("Interlobular septa", "Capsule & stroma"),
    ("Capsule", "Capsule & stroma"),
    ("Follicular basal lamina", "Thyroid follicles"),
    ("Parathyroid capsule", "Parathyroid gland"),
    ("Parathyroid chief cells", "Parathyroid gland"),
    ("Oxyphil cells", "Parathyroid gland"),
    ("Parathyroid adipocytes", "Parathyroid gland"),
    ("Parathyroid capillaries", "Parathyroid gland"),
}
EXPECTED_SELECTOR_NAMES = {
    "epithelium": "Follicular epithelium", "colloid": "Colloid",
    "resorption": "Resorption vacuoles", "c_cells": "Parafollicular C cells",
    "thyroid_capillaries": "Perifollicular capillaries",
    "arterial_sample": "Arteries (capsular & interlobular)",
    "venous_sample": "Veins (capsular & interlobular)",
    "stroma": "Interfollicular connective tissue", "septa": "Interlobular septa",
    "capsule": "Capsule", "basal_lamina": "Follicular basal lamina",
    "parathyroid_capsule": "Parathyroid capsule",
    "chief_cells": "Parathyroid chief cells", "oxyphil_cells": "Oxyphil cells",
    "adipocytes": "Parathyroid adipocytes",
    "parathyroid_capillaries": "Parathyroid capillaries",
}


def _number(value, field, minimum=0.0, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(field + " must be a finite number")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(field + " is outside its allowed range")
    return float(value)


def validate_spec(spec):
    """Bounded structural/identity checks; does not certify anatomy or geometry."""
    required = {"schema_version", "model_id", "default_sequence", "selectors",
                "sequences", "sources", "limitations", "policy"}
    if not isinstance(spec, dict) or set(spec) != required:
        raise ValueError("Unsupported specification fields")
    if type(spec["schema_version"]) is not int or spec["schema_version"] != 1:
        raise ValueError("Unsupported schema_version")
    if spec["model_id"] != MODEL_ID:
        raise ValueError("This hook is exclusive to thyroid_follicles")
    if spec["policy"] != {"geometry_mutation": False, "particle_paths": False,
                           "autoplay": False, "time_semantics": "schematic",
                           "visibility_mutation": False, "material_mutation": False}:
        raise ValueError("Presentation safety policy differs from this hook")
    selectors = spec["selectors"]
    if not isinstance(selectors, dict) or not 1 <= len(selectors) <= MAX_PARTS:
        raise ValueError("Invalid selector count")
    pairs = []
    for key, rec in selectors.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key):
            raise ValueError("Invalid selector id")
        if not isinstance(rec, dict) or set(rec) != {"name", "group"}:
            raise ValueError("Selectors must contain exact name and group only")
        if any(not isinstance(rec[x], str) or not 1 <= len(rec[x]) <= 160
               for x in ("name", "group")):
            raise ValueError("Invalid exact selector")
        pairs.append((rec["name"], rec["group"]))
    if len(set(pairs)) != len(pairs) or len({p[0] for p in pairs}) != len(pairs):
        raise ValueError("Selector identities must be unambiguous")
    if set(pairs) != EXPECTED_PAIRS:
        raise ValueError("Exact thyroid_follicles selector inventory is required")
    if {key: rec["name"] for key, rec in selectors.items()} != EXPECTED_SELECTOR_NAMES:
        raise ValueError("Exact semantic selector-to-part mapping is required")
    sequences = spec["sequences"]
    if not isinstance(sequences, dict) or not 1 <= len(sequences) <= 8:
        raise ValueError("Invalid sequence count")
    if spec["default_sequence"] not in sequences:
        raise ValueError("Missing default sequence")
    if not isinstance(spec["sources"], dict) or not 1 <= len(spec["sources"]) <= 16:
        raise ValueError("Invalid sources")
    for source in spec["sources"].values():
        if not isinstance(source, dict) or set(source) != {"title", "url", "verified"}:
            raise ValueError("Invalid source fields")
        if not isinstance(source["url"], str) or not source["url"].startswith("https://"):
            raise ValueError("Invalid source URL")
    if (not isinstance(spec["limitations"], list) or
            not 1 <= len(spec["limitations"]) <= 16 or
            any(not isinstance(s, str) or not 1 <= len(s) <= 1500
                for s in spec["limitations"])):
        raise ValueError("Invalid limitations")
    for sequence_id, rec in sequences.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", sequence_id):
            raise ValueError("Invalid sequence id")
        if not isinstance(rec, dict) or set(rec) != {"title", "steps"}:
            raise ValueError("Invalid sequence fields")
        if not isinstance(rec["title"], str) or not 1 <= len(rec["title"]) <= 160:
            raise ValueError("Invalid sequence title")
        if not isinstance(rec["steps"], list) or not 1 <= len(rec["steps"]) <= 16:
            raise ValueError("Invalid step count")
        ids = set()
        for step in rec["steps"]:
            if not isinstance(step, dict) or set(step) != {
                    "id", "title", "caption", "duration_s", "highlight",
                    "compartment", "source_ids"}:
                raise ValueError("Unsupported step fields; no path data accepted")
            for field in ("id", "title", "caption", "compartment"):
                if not isinstance(step[field], str) or not 1 <= len(step[field]) <= 1500:
                    raise ValueError("Invalid step text")
            if step["id"] in ids:
                raise ValueError("Duplicate step id")
            ids.add(step["id"])
            _number(step["duration_s"], "duration_s", 1, 30)
            for field, available in (("highlight", selectors),
                                     ("source_ids", spec["sources"])):
                values = step[field]
                if not isinstance(values, list) or not 1 <= len(values) <= 16:
                    raise ValueError("Invalid " + field)
                if any(not isinstance(x, str) or x not in available for x in values):
                    raise ValueError("Unknown " + field)
                if len(set(values)) != len(values):
                    raise ValueError("Duplicate " + field)
    return deepcopy(spec)


def load_spec(path):
    """Explicit bounded file read; importing this module does no I/O."""
    with Path(path).open("rb") as handle:
        raw = handle.read(MAX_SPEC_BYTES + 1)
    if len(raw) > MAX_SPEC_BYTES:
        raise ValueError("Function specification exceeds size budget")
    return validate_spec(json.loads(raw.decode("utf-8")))


class FunctionAnimation:
    """Native-compatible glow hook plus an explanatory panel-state interface.

    Construct one instance per loaded Pre/Post variant. It binds exact names and
    groups from already-loaded metadata; it never opens a geometry artifact.
    No prefix matching, inferred vascular routing or chemical concentrations.
    """
    speeds = (0.5, 0.25, 0.1)  # Avoid the current UI's misleading “real time” label.

    def __init__(self, spec, part_metadata, *, model_id, variant_id,
                 artifact_sha256, sequence_id=None):
        self.spec = validate_spec(spec)
        if model_id != MODEL_ID or variant_id not in VARIANTS:
            raise ValueError("Model or root-selected variant is not supported")
        if (not isinstance(artifact_sha256, str) or
                not re.fullmatch(r"[0-9a-f]{64}", artifact_sha256)):
            raise ValueError("A verified variant artifact SHA256 is required")
        if not isinstance(part_metadata, (list, tuple)):
            raise ValueError("Part metadata must be a bounded list or tuple")
        metadata = part_metadata
        if not 1 <= len(metadata) <= MAX_PARTS:
            raise ValueError("Part metadata count exceeds budget")
        pairs = [(x["name"], x["group"]) for x in metadata]
        if len(set(pairs)) != len(pairs) or len({p[0] for p in pairs}) != len(pairs):
            raise ValueError("Duplicate part identity")
        expected = {(x["name"], x["group"]) for x in self.spec["selectors"].values()}
        if set(pairs) != expected:
            raise ValueError("Exact name/group inventory mismatch")
        self.names = tuple(p[0] for p in pairs)
        self.identity = {"model_id": model_id, "variant_id": variant_id,
                         "artifact_sha256": artifact_sha256}
        self.select_sequence(sequence_id or self.spec["default_sequence"])

    def select_sequence(self, sequence_id):
        """Variant-local UI choice; root remains owner of actual variant selection."""
        if sequence_id not in self.spec["sequences"]:
            raise ValueError("Unknown teaching sequence")
        self.sequence_id = sequence_id
        self._sequence = self.spec["sequences"][sequence_id]
        self.title = self._sequence["title"]
        self.period = sum(s["duration_s"] for s in self._sequence["steps"])
        edge = 0.0
        self.phases = []
        for step in self._sequence["steps"]:
            end = edge + step["duration_s"] / self.period
            self.phases.append((edge, end, "Schematic: " + step["title"]))
            edge = end

    def state_at(self, seconds):
        """Non-looping state; at/after period hold the last teaching step."""
        seconds = _number(seconds, "elapsed seconds")
        cursor = 0.0
        steps = self._sequence["steps"]
        chosen = len(steps) - 1
        local = 1.0
        for i, step in enumerate(steps):
            end = cursor + step["duration_s"]
            if seconds < end:
                chosen = i
                local = (seconds - cursor) / step["duration_s"]
                break
            cursor = end
        step = steps[chosen]
        return {"identity": dict(self.identity), "sequence_id": self.sequence_id,
                "step_id": step["id"], "step_index": chosen,
                "title": step["title"], "caption": step["caption"],
                "compartment": step["compartment"],
                "highlight": [dict(self.spec["selectors"][x]) for x in step["highlight"]],
                "source_ids": list(step["source_ids"]),
                "step_fraction": local, "complete": seconds >= self.period,
                "schematic": True, "geometry_unchanged": True,
                "limitations": list(self.spec["limitations"])}

    def _state_for_phase(self, phase):
        phase = _number(phase, "phase", 0, 1)
        return self.state_at((phase % 1.0) * self.period)

    def phase_label(self, phase):
        state = self._state_for_phase(phase)
        return "Schematic: " + state["title"]

    def frame(self, names, phase):
        """Native (2,n,4) nested lists; all displacements zero and mode=0."""
        if tuple(names) != self.names:
            raise ValueError("Native item order differs from bound metadata")
        state = self._state_for_phase(phase)
        emphasized = {x["name"] for x in state["highlight"]}
        # This pulse is a display cue. It carries no physiological time/rate claim.
        cue = 0.12 + 0.08 * math.sin(math.pi * state["step_fraction"]) ** 2
        weights = [[0.0, 0.0, 0.0, 0.0] for _ in self.names]
        styles = [[0.0, cue if name in emphasized else 0.0, 0.08, 1.0]
                  for name in self.names]
        return [weights, styles]


def configure_model(model, *, spec, part_metadata, variant_id, artifact_sha256,
                    sequence_id=None):
    """Attach only a runtime hook to an already-created model, without parts().

    The native adapter owns artifact hash verification and metadata extraction.
    Call separately for Pre/Post and rebuild the viewer on variant changes.
    This function does not persist preferred variants, modify parts or launch UI.
    """
    hook = FunctionAnimation(spec, part_metadata, model_id=getattr(model, "id", None),
                             variant_id=variant_id, artifact_sha256=artifact_sha256,
                             sequence_id=sequence_id)
    model.animation = hook
    return hook
