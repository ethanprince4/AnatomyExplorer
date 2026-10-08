"""Back and forward through the places a study session has been.

A place is what is on screen once a click has settled: the lesson step being read (if any) and the scene beside it -
the atlas and its selection, a 3D model and its selected part, a histology image, a radiology case or a library page.
The main window records one whenever navigation settles and restores them for Back, Forward and the recent-places menu,
so a reader who wanders from a lesson into a model, its details and a micrograph can always find the way back.
"""


class PlaceHistory:
    LIMIT = 60

    def __init__(self):
        self.entries = []          # [(key, label)]; a key is a hashable description of the place
        self.pos = -1

    def push(self, key, label):
        """Record a new current place; returns False when it is the place already current (only its label updates)."""
        if 0 <= self.pos < len(self.entries) and self.entries[self.pos][0] == key:
            self.entries[self.pos] = (key, label)
            return False
        del self.entries[self.pos + 1:]
        self.entries.append((key, label))
        if len(self.entries) > self.LIMIT:
            del self.entries[0]
        self.pos = len(self.entries) - 1
        return True

    def can_go(self, step):
        return bool(step) and 0 <= self.pos + step < len(self.entries)

    def go(self, step):
        """Make the place `step` entries away current and return its key; None at either end."""
        return self.jump(self.pos + step) if self.can_go(step) else None

    def jump(self, index):
        if not 0 <= index < len(self.entries):
            return None
        self.pos = index
        return self.entries[index][0]

    def label(self, step):
        return self.entries[self.pos + step][1] if self.can_go(step) else ""

    def recent(self, limit=15):
        """[(index, label, is_current)], newest first."""
        first = max(0, len(self.entries) - limit)
        return [(i, self.entries[i][1], i == self.pos) for i in range(len(self.entries) - 1, first - 1, -1)]
