"""Validate the lesson library: every name resolves, every key is real, every cross-reference exists."""
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR                                     # noqa: E402
from app.data import Dataset                                        # noqa: E402
from app.lessons import LEVEL_NAME, REGION_NAME, SYSTEM_NAME        # noqa: E402
from app.lessons import Resolver, load_lessons                      # noqa: E402


def main():
    ds = Dataset(DATA_DIR)
    res = Resolver(ds)                              # no fuzzy fallback: names must be exact
    pool = list(res.by_lower) + list(res.groups) + list(res.collections)
    from app.content import ContentIndex
    from app.micro.registry import MODELS
    tissues = set(ContentIndex(ds).tissues)
    systems = {s["key"] for s in ds.systems}
    regions = {r["key"] for r in ds.regions}
    lessons = load_lessons()
    ids = {x.id for x in lessons}
    try:
        from app.radiology import load_cases
        cases = {c.id for c in load_cases()}
    except (ImportError, OSError, ValueError):
        cases = set()

    bad = 0

    def fail(msg):
        nonlocal bad
        bad += 1
        print(msg)

    for lesson in lessons:
        where = lesson.id
        if lesson.system not in SYSTEM_NAME:
            fail(f"{where}: system {lesson.system!r} is not one of {sorted(SYSTEM_NAME)}")
        if lesson.region not in REGION_NAME:
            fail(f"{where}: region {lesson.region!r} is not one of {sorted(REGION_NAME)}")
        if lesson.level not in LEVEL_NAME:
            fail(f"{where}: level {lesson.level!r} is not one of {sorted(LEVEL_NAME)}")
        if not lesson.objectives:
            fail(f"{where}: no objectives")
        if not lesson.takeaways:
            fail(f"{where}: no takeaways")
        for other in lesson.prereq:
            if other not in ids:
                fail(f"{where}: prereq {other!r} is not a lesson")
        for other in lesson.see_also.get("lessons", []):
            if other not in ids:
                fail(f"{where}: see_also lesson {other!r} does not exist")
        for cid in lesson.see_also.get("radiology", []):
            if cases and cid not in cases:
                fail(f"{where}: see_also radiology {cid!r} is not a case")
        for mid in lesson.see_also.get("micro", []):
            if mid not in MODELS:
                fail(f"{where}: see_also micro {mid!r} is not a model")
        for tid in lesson.see_also.get("histology", []):
            if tid not in tissues:
                fail(f"{where}: see_also histology {tid!r} is not a tissue")

        for i, step in enumerate(lesson.steps, 1):
            for field in ("show", "focus", "ghost_focus", "frame_on"):
                for name in step.get(field, []):
                    if not res.resolve(name):
                        near = difflib.get_close_matches(name.lower(), pool, n=4, cutoff=0.6)
                        fail(f"{where} step {i} [{field}] {name!r} -> {near}")
            if step.get("micro") and step["micro"] not in MODELS:
                fail(f"{where} step {i} micro {step['micro']!r} is not a model")
            if step.get("histology") and step["histology"] not in tissues:
                fail(f"{where} step {i} histology {step['histology']!r} is not a tissue")
            for key in step.get("systems", []):
                if key not in systems:
                    fail(f"{where} step {i} system {key!r} is unknown")
            for key in step.get("regions", []):
                if key not in regions:
                    fail(f"{where} step {i} region {key!r} is unknown")
            check = step.get("check")
            if check is not None and (not isinstance(check, dict) or not check.get("q") or not check.get("a")):
                fail(f"{where} step {i}: check needs both a question and an answer")

    steps = sum(len(x) for x in lessons)
    checks = sum(len(x.checks()) for x in lessons)
    print(f"{len(lessons)} lessons, {steps} steps, {checks} recall questions")
    print("OK" if not bad else f"{bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
