"""Bounded, static ear lessons; no mesh, native app, or numerical dependencies.

Supply the native viewport and the JSON mapping after the model and its named
cameras have been attached. Call select() to begin; construction is inert.
"""
from copy import deepcopy
import json
from pathlib import Path


class SequenceController:
    """Choose a lesson and advance captions while applying existing named views."""

    def __init__(self, viewport, data):
        if not callable(getattr(viewport, "set_named_view", None)):
            raise TypeError("viewport must provide set_named_view")
        self.viewport = viewport
        self._view_notes = deepcopy(data.get("view_notes", {}))
        self._sequences = deepcopy(data.get("functional_sequences", []))
        if not self._sequences:
            raise ValueError("functional_sequences must not be empty")
        self._ids = []
        for sequence in self._sequences:
            ident = sequence.get("id")
            if not isinstance(ident, str) or not ident or ident in self._ids:
                raise ValueError("each sequence needs a unique nonempty id")
            steps = sequence.get("steps")
            if not isinstance(steps, list) or not steps:
                raise ValueError("each sequence needs steps")
            if any(not step.get("view") or not step.get("caption") for step in steps):
                raise ValueError("each step needs a view and caption")
            self._ids.append(ident)
        self._sequence_index = 0
        self._step_index = 0

    @classmethod
    def from_file(cls, viewport, path):
        return cls(viewport, json.loads(Path(path).read_text(encoding="utf-8")))

    @staticmethod
    def _clamp(index, count):
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError("index must be an integer")
        return min(max(index, 0), count - 1)

    @property
    def sequence_ids(self):
        return tuple(self._ids)

    @property
    def state(self):
        sequence = self._sequences[self._sequence_index]
        step = sequence["steps"][self._step_index]
        return deepcopy({
            "sequence_id": sequence["id"],
            "title": sequence["title"],
            "mechanism": sequence["mechanism"],
            "sequence_index": self._sequence_index,
            "step_index": self._step_index,
            "step_count": len(sequence["steps"]),
            "caption": step["caption"],
            "view": step["view"],
            "scale_note": self._view_notes.get(step["view"], ""),
            "focus_parts": step.get("parts", []),
            "source_evidence": step.get("source_evidence", []),
            "schematic_limitations": sequence.get("schematic_limitations", []),
            "can_previous": self._step_index > 0,
            "can_next": self._step_index + 1 < len(sequence["steps"]),
            "physical_animation": False,
        })

    def _apply(self, sequence_index, step_index):
        sequence = self._sequences[sequence_index]
        view = sequence["steps"][step_index]["view"]
        model = getattr(self.viewport, "model", None)
        cameras = getattr(model, "cameras", None)
        if cameras is not None and view not in cameras:
            raise ValueError("missing named view: " + view)
        # Native API restores camera/visibility/cut state. No invented physics.
        self.viewport.set_named_view(view, animate=False)
        self._sequence_index, self._step_index = sequence_index, step_index
        return self.state

    def select(self, sequence_id, step_index=0):
        """Select a known ID, or a clamped integer lesson index."""
        if isinstance(sequence_id, str):
            if sequence_id not in self._ids:
                raise ValueError("unknown sequence id: " + sequence_id)
            index = self._ids.index(sequence_id)
        else:
            index = self._clamp(sequence_id, len(self._sequences))
        step = self._clamp(step_index, len(self._sequences[index]["steps"]))
        return self._apply(index, step)

    def set_step(self, step_index):
        count = len(self._sequences[self._sequence_index]["steps"])
        return self._apply(self._sequence_index, self._clamp(step_index, count))

    def next(self):
        return self.set_step(self._step_index + 1)

    def previous(self):
        return self.set_step(self._step_index - 1)

    def restart(self):
        return self.set_step(0)
