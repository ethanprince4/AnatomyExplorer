"""English display spelling without changing authored identifiers or source assets."""
import re


# Match the British root, including common compounds. A bare substring replace
# would corrupt already-American gastroesophageal and tracheoesophageal.
_BRITISH = re.compile(r"(?<![a-z])(?P<prefix>trans|mega|juxta|para|peri|retro|gastro|tracheo|cardio|broncho|pharyngo|endo)?o+esophag",
                      re.IGNORECASE)
# HTML/SVG attributes and links carry stable targets, even when their visible
# labels use American English. Leave those spans byte-for-byte intact.
_PROTECTED = re.compile(r"(<[^>]*>|(?:[a-z][a-z0-9+.-]*:(?://)?|www\.)[^\s<>]+|"
                        r"(?:[a-z]:[\\/]|(?:\.{1,2}|data|models|app)[\\/])[^\s<>]+|"
                        r"\b[\w.-]+\.(?:glb|gltf|npz|json|svg|png|jpg|jpeg|webp|md|pdf)\b)", re.IGNORECASE)
_DISPLAY_FIELDS = frozenset({
    "name", "base", "title", "summary", "text", "note", "description", "caption",
    "q", "a", "prompt", "answer", "answers", "options", "choices", "explanation", "why", "hint",
    "clinical", "action", "blood_supply", "innervation", "objectives", "takeaways",
    "tags", "reading", "features", "unit", "scale_note", "atlas_note", "label",
    "focus", "show", "ghost_focus", "frame_on", "structure", "structures", "atlas",
    "subsystem", "collections", "micro_focus", "items", "contains",
})
_IDENTITY_FIELDS = frozenset({
    "id", "key", "latin", "file", "path", "url", "source", "href", "link",
    "model", "model_id", "diagram", "view", "camera", "state", "group", "groups",
    "histology", "related", "prereq", "practice_from", "see_also", "def",
})


def _replace(match):
    prefix = match.group("prefix") or ""
    word = match.group()[len(prefix):]
    result = word.lstrip("oO")
    return prefix + (result[:1].upper() + result[1:] if word[0].isupper() else result)


def american_text(text):
    """Use esophagus/esophageal (and derivatives) in English text only."""
    if not isinstance(text, str) or not _BRITISH.search(text):
        return text
    spans = _PROTECTED.split(text)
    return "".join(span if i % 2 else _BRITISH.sub(_replace, span) for i, span in enumerate(spans))


def canonical_name(text):
    """One lookup/search form for American and legacy British human names."""
    return _BRITISH.sub(_replace, str(text or "").strip().casefold())


class NameAliases(dict):
    """Lookup English names in either spelling while retaining saved dict keys."""

    def _authored_key(self, key):
        if dict.__contains__(self, key):
            return key
        if isinstance(key, str) and key.startswith(("card:", "micro:")):
            return key
        normalized = canonical_name(key)
        return next((stored for stored in self if canonical_name(stored) == normalized), key)

    def __contains__(self, key):
        return dict.__contains__(self, self._authored_key(key))

    def __getitem__(self, key):
        return dict.__getitem__(self, self._authored_key(key))

    def get(self, key, default=None):
        return dict.get(self, self._authored_key(key), default)

    def __setitem__(self, key, value):
        dict.__setitem__(self, self._authored_key(key), value)

    def setdefault(self, key, default=None):
        return dict.setdefault(self, self._authored_key(key), default)

    def pop(self, key, *default):
        return dict.pop(self, self._authored_key(key), *default)


def display_content(value, *, text=False):
    """Copy known English fields; preserve dictionary keys, IDs, links and Latin.

    This is for teaching-content schemas, not geometry or control documents.
    Unknown string fields stay authored unless nested inside an English field.
    """
    if isinstance(value, dict):
        return {key: (item if key in _IDENTITY_FIELDS else
                      display_content(item, text=text or key in _DISPLAY_FIELDS))
                for key, item in value.items()}
    if isinstance(value, list):
        return [display_content(item, text=text) for item in value]
    if isinstance(value, tuple):
        return tuple(display_content(item, text=text) for item in value)
    return american_text(value) if text else value
