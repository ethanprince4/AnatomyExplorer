"""Spaced repetition for the quiz.

Anatomy is a memory subject, and the difference between recognising a structure once and still knowing it in six
months is whether you saw it again at the right moment. Every structure you are asked about gets an SM-2 style
schedule: answer it well and the gap before it comes back grows; miss it and the gap collapses to a day.

The schedule lives beside the hit/miss counts in data/user/quiz_stats.json, so nothing else has to change.
"""
import datetime

MIN_EASE = 1.3
START_EASE = 2.5
GRADE_WRONG = 1
GRADE_HELPED = 3
GRADE_GOOD = 4
GRADE_EASY = 5


def today():
    return datetime.date.today()


def _date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def grade_for(correct, helped, wrong_attempts=0):
    """Turn one answer into an SM-2 grade."""
    if not correct:
        return GRADE_WRONG
    if helped or wrong_attempts:
        return GRADE_HELPED
    return GRADE_GOOD


def update(stat, grade, day=None):
    """Advance one structure's schedule in place and return it."""
    day = day or today()
    ease = float(stat.get("ease", START_EASE))
    reps = int(stat.get("reps", 0))
    interval = float(stat.get("interval", 0))
    if grade < 3:
        reps = 0
        interval = 1
        stat["lapses"] = int(stat.get("lapses", 0)) + 1
    else:
        reps += 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 4
        else:
            interval = max(1.0, round(interval * ease))
        ease = max(MIN_EASE, ease + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)))
    stat["ease"] = round(ease, 3)
    stat["reps"] = reps
    stat["interval"] = int(interval)
    stat["due"] = (day + datetime.timedelta(days=int(interval))).isoformat()
    stat["last"] = day.isoformat()
    stat.setdefault("history", [])
    stat["history"] = (stat["history"] + [day.isoformat()])[-40:]
    return stat


def due_bases(stats, day=None, include_new=False):
    """Structures whose review date has arrived, soonest first."""
    day = day or today()
    out = []
    for base, stat in stats.items():
        d = _date(stat.get("due"))
        if d is None:
            if include_new:
                out.append((day, base))
            continue
        if d <= day:
            out.append((d, base))
    out.sort()
    return [b for _, b in out]


def summary(stats, day=None):
    """Numbers for the progress dialog."""
    day = day or today()
    seen = sum(int(s.get("seen", 0)) for s in stats.values())
    miss = sum(int(s.get("miss", 0)) for s in stats.values())
    scheduled = [s for s in stats.values() if _date(s.get("due"))]
    learned = [s for s in scheduled if int(s.get("interval", 0)) >= 21]
    young = [s for s in scheduled if 0 < int(s.get("interval", 0)) < 21]
    upcoming = {}
    for stat in scheduled:
        d = _date(stat.get("due"))
        delta = (d - day).days
        if 0 < delta <= 14:
            upcoming[delta] = upcoming.get(delta, 0) + 1
    return {
        "structures": len(stats),
        "answers": seen,
        "accuracy": (seen - miss) / seen if seen else 0.0,
        "due": len(due_bases(stats, day)),
        "learned": len(learned),
        "young": len(young),
        "upcoming": upcoming,
    }


def weakest(stats, limit=15):
    """The structures you get wrong most often, worst first."""
    rows = []
    for base, s in stats.items():
        seen, miss = int(s.get("seen", 0)), int(s.get("miss", 0))
        if seen >= 2 and miss:
            rows.append((miss / seen, miss, seen, base))
    rows.sort(reverse=True)
    return [(base, miss, seen, rate) for rate, miss, seen, base in rows[:limit]]
