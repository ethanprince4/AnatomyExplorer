"""Guided lessons: scripted walks through a region or a system, each step setting the view up for you.

A lesson is data, not code - see data/content/lessons*.json. Each step names the structures it is about and the
app does the rest: switch systems on, dissect to the right depth, isolate or x-ray, move the camera, open a
cross-section, or open the matching microanatomy model.

Around the steps sits the teaching scaffolding: what you should be able to do at the end (`objectives`), a
recall question on each step (`check`), the things worth carrying away (`takeaways`), and where to go next
(`see_also`). Every lesson is filed under one body system and one region so the library can be read either way.
"""
import datetime
import json

from .config import ROOT

LESSON_DIR = ROOT / "data" / "content"
PROGRESS_PATH = ROOT / "data" / "user" / "lesson_progress.json"

# The two ways the library is segmented. Keys are what a lesson file writes; the name is what the panel shows.
SYSTEMS = [
    ("skeletal", "Skeletal"),
    ("muscular", "Muscular"),
    ("cardiovascular", "Cardiovascular"),
    ("respiratory", "Respiratory"),
    ("digestive", "Digestive"),
    ("urinary", "Urinary"),
    ("reproductive", "Reproductive"),
    ("endocrine", "Endocrine"),
    ("lymphatic", "Lymphatic & immune"),
    ("nervous", "Nervous"),
    ("sensory", "Special senses"),
    ("integumentary", "Skin & fascia"),
]
REGIONS = [
    ("head_neck", "Head & neck"),
    ("back", "Back & spine"),
    ("thorax", "Thorax"),
    ("abdomen", "Abdomen"),
    ("pelvis", "Pelvis & perineum"),
    ("upper_limb", "Upper limb"),
    ("lower_limb", "Lower limb"),
    ("general", "Whole body"),
]
LEVELS = [
    ("foundation", "Foundation"),
    ("core", "Core"),
    ("advanced", "Advanced"),
]
SYSTEM_NAME = dict(SYSTEMS)
REGION_NAME = dict(REGIONS)
LEVEL_NAME = dict(LEVELS)
SYSTEM_ORDER = {k: i for i, (k, _n) in enumerate(SYSTEMS)}
REGION_ORDER = {k: i for i, (k, _n) in enumerate(REGIONS)}
LEVEL_ORDER = {k: i for i, (k, _n) in enumerate(LEVELS)}

# a lesson written before the library was split by system and region still has to land somewhere sensible
LEGACY_CATEGORY = {
    "head & neck": ("nervous", "head_neck"),
    "neuroanatomy": ("nervous", "head_neck"),
    "joints": ("skeletal", "general"),
    "trunk": ("muscular", "thorax"),
    "viscera": ("digestive", "abdomen"),
    "upper limb": ("muscular", "upper_limb"),
    "lower limb": ("muscular", "lower_limb"),
}


class Lesson:
    def __init__(self, raw):
        self.id = raw["id"]
        self.title = raw["title"]
        self.summary = raw.get("summary", "")
        self.steps = raw.get("steps", [])
        legacy = LEGACY_CATEGORY.get(str(raw.get("category", "")).lower(), ("skeletal", "general"))
        self.system = raw.get("system") or legacy[0]
        self.region = raw.get("region") or legacy[1]
        self.level = raw.get("level", "core")
        self.category = raw.get("category") or REGION_NAME.get(self.region, "General")
        self.minutes = int(raw.get("minutes", 0)) or max(3, 2 * len(self.steps))
        self.objectives = list(raw.get("objectives", []))
        self.takeaways = list(raw.get("takeaways", []))
        self.prereq = list(raw.get("prereq", []))
        self.see_also = dict(raw.get("see_also", {}))
        self.tags = list(raw.get("tags", []))

    def __len__(self):
        return len(self.steps)

    @property
    def system_name(self):
        return SYSTEM_NAME.get(self.system, self.system.title())

    @property
    def region_name(self):
        return REGION_NAME.get(self.region, self.region.title())

    @property
    def level_name(self):
        return LEVEL_NAME.get(self.level, self.level.title())

    def names(self):
        """Every structure name the lesson points at, in order, without repeats."""
        out = []
        for step in self.steps:
            for key in ("focus", "show", "ghost_focus", "frame_on"):
                for n in step.get(key, []):
                    if n not in out:
                        out.append(n)
        return out

    def checks(self):
        """(step index, question, answer) for every step that carries a recall question."""
        out = []
        for i, step in enumerate(self.steps):
            check = step.get("check")
            if isinstance(check, dict) and check.get("q"):
                out.append((i, check["q"], check.get("a", "")))
        return out


def load_lessons():
    out = []
    seen = set()
    for path in sorted(LESSON_DIR.glob("lessons*.json")):
        try:
            for raw in json.loads(path.read_text(encoding="utf-8")):
                lesson = Lesson(raw)
                if lesson.id in seen:
                    print(f"Duplicate lesson id {lesson.id!r} in {path.name}")
                    continue
                seen.add(lesson.id)
                out.append(lesson)
        except (OSError, ValueError) as exc:
            print(f"Could not read {path.name}: {exc}")
    out.sort(key=lambda x: (SYSTEM_ORDER.get(x.system, 99), REGION_ORDER.get(x.region, 99),
                            LEVEL_ORDER.get(x.level, 9), x.title))
    return out


def group_lessons(lessons, by):
    """[(heading, key, [lesson])] for by = 'system' | 'region' | 'level', in the library's own order."""
    if by == "region":
        order, names = REGION_ORDER, REGION_NAME
        key_of = lambda x: x.region                                      # noqa: E731
    elif by == "level":
        order, names = LEVEL_ORDER, LEVEL_NAME
        key_of = lambda x: x.level                                       # noqa: E731
    else:
        order, names = SYSTEM_ORDER, SYSTEM_NAME
        key_of = lambda x: x.system                                      # noqa: E731
    buckets = {}
    for lesson in lessons:
        buckets.setdefault(key_of(lesson), []).append(lesson)
    return [(names.get(k, k.title()), k, buckets[k]) for k in sorted(buckets, key=lambda k: order.get(k, 99))]


class LessonProgress:
    """How far through each lesson you are, kept between runs in data/user/lesson_progress.json."""

    def __init__(self, path=PROGRESS_PATH):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        if not isinstance(self.data, dict):
            self.data = {}

    # -------------------------------------------------------------- reading
    def entry(self, lesson_id):
        rec = self.data.get(lesson_id)
        return rec if isinstance(rec, dict) else {}

    def seen(self, lesson_id):
        return set(self.entry(lesson_id).get("seen", []))

    def last_step(self, lesson_id):
        return int(self.entry(lesson_id).get("last", 0))

    def is_done(self, lesson_id):
        return bool(self.entry(lesson_id).get("done"))

    def fraction(self, lesson_id, total):
        if not total:
            return 0.0
        if self.is_done(lesson_id):
            return 1.0
        return min(1.0, len(self.seen(lesson_id)) / total)

    def totals(self, lessons):
        done = sum(1 for x in lessons if self.is_done(x.id))
        started = sum(1 for x in lessons if not self.is_done(x.id) and self.entry(x.id).get("seen"))
        return done, started, len(lessons)

    def in_progress(self, lessons):
        """The lessons you have started and not finished, most recently touched first."""
        rows = [(self.entry(x.id).get("when", ""), x) for x in lessons
                if self.entry(x.id).get("seen") and not self.is_done(x.id)]
        rows.sort(key=lambda r: r[0], reverse=True)
        return [x for _w, x in rows]

    # -------------------------------------------------------------- writing
    def visit(self, lesson_id, index, total):
        rec = self.data.setdefault(lesson_id, {})
        seen = set(rec.get("seen", []))
        seen.add(int(index))
        rec["seen"] = sorted(seen)
        rec["last"] = int(index)
        rec["when"] = datetime.datetime.now().isoformat(timespec="seconds")
        if total and len(seen) >= total:
            rec.setdefault("done", datetime.date.today().isoformat())
        self.save()

    def set_done(self, lesson_id, total, done=True):
        rec = self.data.setdefault(lesson_id, {})
        if done:
            rec["done"] = datetime.date.today().isoformat()
            rec["seen"] = list(range(total))
        else:
            rec.pop("done", None)
            rec["seen"] = []
            rec["last"] = 0
        rec["when"] = datetime.datetime.now().isoformat(timespec="seconds")
        self.save()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        except OSError:
            pass


class Resolver:
    """Turns the plain names used in a lesson into structure ids."""

    def __init__(self, ds, search=None):
        self.ds = ds
        self.search = search
        self.by_lower = {}
        for name, sids in ds.by_name.items():
            self.by_lower.setdefault(name.lower(), []).extend(sids)
        self.groups = {}
        for nid, node in ds.nodes.items():
            if node["kind"] == "group" and node["count"] > 1:
                self.groups.setdefault(node["name"].lower(), []).append(nid)
        self.collections = {}
        for s in ds.structures:
            for c in s.get("collections", ()):
                self.collections.setdefault(c.lower(), []).append(s["id"])
        self.landmarks = {}          # bony points live as landmarks, not as structures of their own
        for i, lm in enumerate(ds.landmarks):
            self.landmarks.setdefault(lm["name"].lower(), []).append(i)

    def resolve(self, name):
        """[structure ids] for a structure name, a group name or a collection name. Empty if nothing matches."""
        key = (name or "").strip().lower()
        if not key:
            return []
        if key in self.by_lower:
            return list(self.by_lower[key])
        if key in self.groups:
            out = []
            for nid in self.groups[key]:
                out.extend(self.ds.node_structures(nid))
            return out
        if key in self.collections:
            return list(self.collections[key])
        if key in self.landmarks:
            return sorted({self.ds.landmarks[i]["sid"] for i in self.landmarks[key]})
        if self.search is not None:
            hits = self.search.search(name, limit=1)
            if hits:
                entry = hits[0]
                if entry.sids:
                    return list(entry.sids)
                if entry.node:
                    return self.ds.node_structures(entry.node)
        return []

    def landmark(self, name):
        """Index of a named landmark, so a lesson can point straight at a bony feature."""
        hits = self.landmarks.get((name or "").strip().lower())
        return hits[0] if hits else None

    def resolve_all(self, names):
        out = []
        for n in names or ():
            out.extend(self.resolve(n))
        return sorted(set(out))
