"""Guided lessons: scripted walks through a region or a system, each step setting the view up for you.

A lesson is data, not code - see data/content/lessons*.json. Each step names the structures it is about and the
app does the rest: switch systems on, dissect to the right depth, isolate or x-ray, move the camera, open a
cross-section, or open the matching microanatomy model.

Around the steps sits the teaching scaffolding: what you should be able to do at the end (`objectives`), a
recall question on each step (`check`), the things worth carrying away (`takeaways`), and where to go next
(`see_also`). Every lesson is filed under one body system and one region so the library can be read either way.

Lessons written for the lab course also carry a `course` place (lab or lab practical, and their order within it)
and a list of `practice` items, which Practice mode (app/ui/practice.py) turns into a short graded session.
"""
import datetime
import hashlib
import json
import random
import re
from pathlib import Path

from .config import ROOT, USER_DIR
from .storage import load_json, write_json
from .srs import _count

LESSON_DIR = ROOT / "data" / "content"
PROGRESS_PATH = USER_DIR / "lesson_progress.json"
DIAGRAM_DIRS = [LESSON_DIR / "diagrams"]          # where a "diagram" id is looked up, first match wins

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
        course = raw.get("course")
        self.course = dict(course) if isinstance(course, dict) else None
        self.practice = [dict(x) for x in raw.get("practice", []) if isinstance(x, dict)]
        self.practice_from = [str(x) for x in raw.get("practice_from", [])]

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

    @property
    def unit_key(self):
        """("lab", 3) or ("exam", 1) for a lab-course lesson, None for everything else."""
        c = self.course
        if not c:
            return None
        if c.get("exam") is not None:
            return ("exam", int(c["exam"]))
        if c.get("lab") is not None:
            return ("lab", int(c["lab"]))
        return None

    @property
    def unit_name(self):
        c = self.course or {}
        if c.get("unit"):
            return str(c["unit"])
        key = self.unit_key
        if key is None:
            return ""
        return f"Lab {key[1]}" if key[0] == "lab" else f"Lab Practical {key[1]}"

    def has_practice(self):
        return bool(self.practice or self.practice_from or self.checks())

    def checks(self):
        """(step index, question, answer) for every step that carries a recall question."""
        out = []
        for i, step in enumerate(self.steps):
            check = step.get("check")
            if isinstance(check, dict) and check.get("q"):
                out.append((i, check["q"], check.get("a", "")))
        return out


def load_lessons(extra=()):
    """Every lesson in data/content/lessons*.json, plus any further files named in `extra` (for testing a draft)."""
    out = []
    seen = set()
    for path in sorted(LESSON_DIR.glob("lessons*.json")) + [Path(x) for x in extra]:
        try:
            for raw in json.loads(path.read_text(encoding="utf-8")):
                lesson = Lesson(raw)
                if lesson.id in seen:
                    print(f"Duplicate lesson id {lesson.id!r} in {path.name}")
                    continue
                seen.add(lesson.id)
                out.append(lesson)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"Could not read {path.name}: {exc}")
    out.sort(key=lambda x: (SYSTEM_ORDER.get(x.system, 99), REGION_ORDER.get(x.region, 99),
                            LEVEL_ORDER.get(x.level, 9), x.title))
    return out


def diagram_path(diagram_id):
    """The SVG file behind a step's or an item's "diagram" id, or None if there is none."""
    for folder in DIAGRAM_DIRS:
        path = Path(folder) / f"{diagram_id}.svg"
        if path.is_file():
            return path
    return None


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

    def __init__(self, path=PROGRESS_PATH, on_save_error=None, on_saved=None):
        self.path = path
        self.on_save_error = on_save_error
        self.on_saved = on_saved
        self.data, self._backup = load_json(path, self._normalize)

    @staticmethod
    def _normalize(raw):
        if not isinstance(raw, dict):
            return {}
        out = {}
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            rec = dict(value)
            if "done" in rec and not isinstance(rec["done"], bool):
                try:
                    if not isinstance(rec["done"], str):
                        raise ValueError("completion date must be text")
                    datetime.date.fromisoformat(rec["done"])
                except ValueError:
                    rec.pop("done")
            if "seen" in rec:
                seen = rec["seen"]
                rec["seen"] = sorted({i for i in seen if isinstance(i, int) and not isinstance(i, bool) and i >= 0}) \
                    if isinstance(seen, list) else []
            if "last" in rec:
                rec["last"] = _count(rec["last"])
            if "when" in rec and not isinstance(rec["when"], str):
                rec.pop("when")
            practice = rec.get("practice")
            if isinstance(practice, dict):
                practice = dict(practice)
                for field in ("last", "best", "n", "sessions"):
                    if field in practice:
                        practice[field] = _count(practice[field])
                if "when" in practice and not isinstance(practice["when"], str):
                    practice.pop("when")
                rec["practice"] = practice
            elif "practice" in rec:
                rec.pop("practice")
            out[key] = rec
        return out

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
        return min(1.0, sum(index < total for index in self.seen(lesson_id)) / total)

    def totals(self, lessons):
        # Match the library: reading lessons finish when read; practice-only exams
        # finish after a completed practice session, regardless of the score.
        finished = [self.is_done(x.id) if len(x) else bool(self.practice(x.id)) for x in lessons]
        done = sum(finished)
        started = sum(1 for x, complete in zip(lessons, finished)
                      if not complete and self.entry(x.id).get("seen"))
        return done, started, len(lessons)

    def practice(self, lesson_id):
        """{"last": %, "best": %, "n": items, "when": iso} of the most recent Practice session, or {}."""
        rec = self.entry(lesson_id).get("practice")
        return rec if isinstance(rec, dict) else {}

    def in_progress(self, lessons):
        """The lessons you have started and not finished, most recently touched first."""
        rows = [(self.entry(x.id).get("when", ""), x) for x in lessons
                if self.entry(x.id).get("seen") and not self.is_done(x.id)]
        rows.sort(key=lambda r: r[0], reverse=True)
        return [x for _w, x in rows]

    # -------------------------------------------------------------- writing
    def visit(self, lesson_id, index, total):
        rec = self.data.setdefault(lesson_id, {})
        stored = set(rec.get("seen", []))
        seen = {step for step in stored if not total or step < total}
        if seen != stored:
            self._backup = True
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

    def record_practice(self, lesson_id, correct, total):
        if not total:
            return
        pct = round(100 * correct / total)
        rec = self.data.setdefault(lesson_id, {})
        old = rec.get("practice") if isinstance(rec.get("practice"), dict) else {}
        rec["practice"] = {"last": pct, "best": max(pct, int(old.get("best", 0))), "n": int(total),
                           "sessions": int(old.get("sessions", 0)) + 1,
                           "when": datetime.datetime.now().isoformat(timespec="seconds")}
        self.save()

    def save(self):
        try:
            write_json(self.path, self.data, backup=self._backup)
            self._backup = False
            if self.on_saved is not None:
                self.on_saved()
            return True
        except OSError as exc:
            if self.on_save_error is not None:
                self.on_save_error(str(exc))
            return False


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


# ====================================================================== the lab course
def course_sort_key(lesson):
    kind, n = lesson.unit_key or ("zz", 99)
    # the labs in number order, then the lab practicals, and within each by the lesson's own order
    return (0 if kind == "lab" else 1, n, int((lesson.course or {}).get("order", 99)), lesson.id)


def course_units(lessons):
    """[(unit heading, (kind, n), [lesson])] for every lab and lab practical, in course order."""
    units = {}
    for lesson in lessons:
        key = lesson.unit_key
        if key is not None:
            units.setdefault(key, []).append(lesson)
    out = []
    for key in sorted(units, key=lambda k: (0 if k[0] == "lab" else 1, k[1])):
        group = sorted(units[key], key=course_sort_key)
        heading = next((x.unit_name for x in group if (x.course or {}).get("unit")), group[0].unit_name)
        out.append((heading, key, group))
    return out


def unit_matches(lesson, ref):
    """True when `ref` ("lab03", "lab3", "exam1" or a lesson id) names this lesson or the unit it belongs to."""
    if ref == lesson.id:
        return True
    m = re.fullmatch(r"(lab|exam)0*(\d+)", (ref or "").strip().lower())
    return bool(m and lesson.unit_key == (m.group(1), int(m.group(2))))


# ====================================================================== practice items
PRACTICE_TYPES = ("find", "name", "find_micro", "mcq", "recall", "order")
TYPE_NAME = {"find": "Find it in 3D", "name": "Name it", "find_micro": "Find it in the model",
             "mcq": "Question", "recall": "Recall", "order": "Put in order"}


def _short(text, n=70):
    t = " ".join(re.sub(r"<[^>]+>", "", str(text or "")).split())
    return t if len(t) <= n else t[: n - 1] + "…"


def item_key(item):
    """The name an item is scheduled under in the spaced-repetition store (data/user/quiz_stats.json).

    Finding or naming an atlas structure is the same fact whichever lesson asks it, so it shares the quiz's key:
    the structure's own name. Everything else is keyed by where it came from and what it asks."""
    kind = item.get("type")
    if kind in ("find", "name"):
        return item.get("_base") or item.get("structure", "")
    if kind == "find_micro":
        return f"micro:{item.get('model')}:{item.get('part')}"
    text = item.get("q", "")
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
    return f"card:{item.get('_lesson', '')}:{_short(text, 48)}#{digest}"


def practice_items(lesson):
    """Every practice item a lesson offers: its own `practice` list, then its step `check`s as recall cards."""
    out = []
    seen_q = set()
    for raw in lesson.practice:
        if raw.get("type") not in PRACTICE_TYPES:
            continue
        item = dict(raw)
        item["_lesson"] = lesson.id
        out.append(item)
        if item.get("q"):
            seen_q.add(_short(item["q"], 200).lower())
    for i, q, a in lesson.checks():
        if _short(q, 200).lower() in seen_q:
            continue
        seen_q.add(_short(q, 200).lower())
        out.append({"type": "recall", "q": q, "a": a, "_lesson": lesson.id, "_step": i})
    return out


def practice_pool(lesson, lessons):
    """The items a session on `lesson` draws from. A lab practical adds every item of the units it names."""
    pool = practice_items(lesson)
    if lesson.practice_from:
        for other in sorted(lessons, key=course_sort_key):
            if other.id != lesson.id and any(unit_matches(other, ref) for ref in lesson.practice_from):
                pool.extend(practice_items(other))
    return pool


def default_length(lesson, pool_size):
    """Bite-sized: a mini lesson runs 8-15 items, a lab practical 40."""
    if lesson.practice_from:
        return min(40, pool_size)
    return pool_size if pool_size <= 15 else 12


def _due_weight(stat, day):
    if not stat:
        return 2.0                              # never seen: worth asking
    try:
        due = datetime.date.fromisoformat(stat.get("due", ""))
    except (TypeError, ValueError):
        due = None
    miss = int(stat.get("miss", 0)) / max(1, int(stat.get("seen", 0)))
    if due is None or due <= day:
        return 3.0 + 2.0 * miss                 # due for review, more so if often missed
    return 0.6 + 2.0 * miss


def build_session(pool, n, stats=None, rng=None):
    """Draw n items from pool (all of them when n is 0 or larger), favouring what is due or often missed, and
    shuffle them. Two items asking exactly the same thing are never both drawn."""
    rng = rng or random.Random()
    stats = stats or {}
    day = datetime.date.today()
    unique = {}
    for item in pool:
        unique.setdefault((item.get("type"), item_key(item)), item)
    items = list(unique.values())
    if not n or n >= len(items):
        rng.shuffle(items)
        return items
    weighted = [(rng.random() ** (1.0 / _due_weight(stats.get(item_key(x)), day)), x) for x in items]
    weighted.sort(key=lambda r: r[0], reverse=True)          # weighted sampling without replacement
    out = [x for _w, x in weighted[:n]]
    rng.shuffle(out)
    return out
