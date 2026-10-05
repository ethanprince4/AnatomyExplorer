"""Small native teaching-stage controller; no mesh loading, rendering or app imports.

The host supplies ModelView.gl_widget and a JSON document. QTimer.timeout can
call advance(); previous/next buttons call previous()/advance(); reset calls
restore(). Timer intervals are instructional pacing, never physiological time.
"""
from copy import deepcopy


class NativeSequenceController:
    def __init__(self, viewport, document):
        self.viewport = viewport
        self.document = document
        keys = [item.key for item in viewport.model.items]
        expected = document["part_inventory"]
        if len(keys) != len(set(keys)) or set(keys) != set(expected):
            raise ValueError("Functional sequences require the exact document part inventory")
        self.by_key = {item.key: item.index for item in viewport.model.items}
        self.sequences = {seq["id"]: seq for seq in document["functional_sequences"]}
        for seq in self.sequences.values():
            for step in seq["steps"]:
                if step["native_view"] not in viewport.model.cameras:
                    raise ValueError("Missing native camera: " + step["native_view"])
                if not set(step.get("focus_parts", [])) <= set(keys):
                    raise ValueError("Missing exact functional target")
        self.sequence_id = None
        self.index = 0
        self.saved = None

    def begin(self, sequence_id):
        if sequence_id not in self.sequences:
            raise ValueError("Unknown functional sequence: " + sequence_id)
        if self.saved is None:
            g = self.viewport
            c = g.camera
            self.saved = {
                "scene": deepcopy(g.state._snapshot()),
                "selected": list(g.state.selected),
                "undo": deepcopy(g.state._undo),
                "camera": {"type": "ORTHO" if c.ortho else "PERSP",
                           "position": list(c.eye()), "target": list(c.target),
                           "fov_deg": c.fov, "ortho_width": c.ortho_width},
                "sections": deepcopy(g.sections), "cut_on": g.cut_on,
                "explode": g.explode,
                "reveal_state": g.reveal_state, "reveal_amount": g.reveal_amount,
                "reveal_target": g.reveal_target,
            }
        self.sequence_id, self.index = sequence_id, 0
        return self.apply()

    def apply(self):
        if self.sequence_id is None:
            raise ValueError("Choose a functional sequence first")
        seq = self.sequences[self.sequence_id]
        step = seq["steps"][self.index]
        g = self.viewport
        g.set_playing(False)
        g.set_explode(0.0)
        g.state.clear_selection()
        g.state.clear_ghost()
        g.set_named_view(step["native_view"], animate=False, visibility=True)
        g.cut_on = False
        g.sections = [None, None, None]
        if step.get("focus_parts"):
            focus = [self.by_key[key] for key in step["focus_parts"]]
            g.frame_structures(focus, duration=0.0)
        g.invalidate_labels()
        g.update()
        # The host presents the full text beside the specimen. No selection glow
        # is used to simulate secretion, activation or force.
        return {"sequence_id": self.sequence_id, "title": seq["title"],
                "step_index": self.index, "step_count": len(seq["steps"]),
                "label": step["label"], "caption": step["caption"],
                "scale_note": seq["scale_note"],
                "timing_note": "Instructional stages; tissue geometry remains at rest.",
                "finished": self.index == len(seq["steps"]) - 1}

    def advance(self):
        if self.sequence_id is None:
            raise ValueError("Choose a functional sequence first")
        self.index = min(self.index + 1, len(self.sequences[self.sequence_id]["steps"]) - 1)
        return self.apply()

    def previous(self):
        if self.sequence_id is None:
            raise ValueError("Choose a functional sequence first")
        self.index = max(0, self.index - 1)
        return self.apply()

    def restore(self):
        if self.saved is None:
            return
        g, saved = self.viewport, self.saved
        g.set_playing(False)
        g.state.restore(deepcopy(saved["scene"]))
        g.state.select(saved["selected"])
        g.state._undo = deepcopy(saved["undo"])
        g.camera.set_record(saved["camera"], duration=0.0)
        g.sections = deepcopy(saved["sections"])
        g.cut_on = saved["cut_on"]
        g.set_explode(saved["explode"])
        g.reveal_state = saved["reveal_state"]
        g.reveal_amount = saved["reveal_amount"]
        g.reveal_target = saved["reveal_target"]
        g.invalidate_labels()
        g.update()
        self.saved = None
        self.sequence_id = None
