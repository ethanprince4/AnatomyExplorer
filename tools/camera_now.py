"""Print the Anatomy Explorer camera right now, as one JSON line (for screenshot hotkeys).

Turn the feed on once (then restart the app):    setx ANATOMY_CAMERA_FEED 1
Read it:        python tools/camera_now.py
                python tools/camera_now.py --label "femur, lateral" --append shots.jsonl
From a hotkey tool (AutoHotkey, PowerToys, ShareX), run that command next to the screenshot key.
Exit code 2 (message on stderr) means the app is not running or the feed is off. Standard library only.
Options: --pretty, --label TEXT, --append FILE (also add the line to a JSONL file), --path FILE (override).
With 1 the file is <temp folder>/AnatomyExplorer-live_camera.json (the temp folder of the user running the app).
ANATOMY_CAMERA_FEED may also be a file path instead of 1; this script then uses the same file."""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ENV_VAR = "ANATOMY_CAMERA_FEED"
FILE_NAME = "live_camera.json"
MAX_AGE_S = 5.0
NOT_RUNNING = "Anatomy Explorer not running, or ANATOMY_CAMERA_FEED not set"


def default_path():
    """Fixed on purpose: the temp folder, from the standard library only, so the app (whatever its launcher does
    to config.USER_DIR) and tools/camera_now.py always compute the same file."""
    return Path(tempfile.gettempdir()) / f"AnatomyExplorer-{FILE_NAME}"


def feed_path(env=None):
    value = (os.environ if env is None else env).get(ENV_VAR, "").strip()
    if value in ("", "0", "1"):
        return default_path()          # off/unset still looks at the default file; a stale or missing file reports it
    return Path(value)


def read_feed(path, tries=5, delay=0.025):
    """The parsed payload, or None when the file is missing. Retries a reader/writer clash for about 100 ms."""
    last = None
    for i in range(tries):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (PermissionError, ValueError, OSError) as exc:
            last = exc
            if i < tries - 1:
                time.sleep(delay)
    raise last


def main(argv=None):
    ap = argparse.ArgumentParser(description="Print the current Anatomy Explorer camera as one JSON line.")
    ap.add_argument("--pretty", action="store_true", help="indented JSON")
    ap.add_argument("--label", help="text added to the output as \"label\"")
    ap.add_argument("--append", metavar="FILE", help="also append the line to this JSONL file")
    ap.add_argument("--path", help="feed file (default: from ANATOMY_CAMERA_FEED)")
    args = ap.parse_args(argv)
    path = Path(args.path) if args.path else feed_path()
    try:
        data = read_feed(path)
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        print(NOT_RUNNING, file=sys.stderr)
        return 2
    try:
        age = time.time() - float(data["time"])
    except (KeyError, TypeError, ValueError):
        age = None
    if age is None or age > MAX_AGE_S:
        print(NOT_RUNNING, file=sys.stderr)
        return 2
    if args.label is not None:
        data["label"] = args.label
    line = json.dumps(data, indent=2 if args.pretty else None)
    print(line)
    if args.append:
        compact = json.dumps(data) if args.pretty else line
        with open(args.append, "a", encoding="utf-8") as f:
            f.write(compact + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
