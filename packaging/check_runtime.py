"""Verify frozen imports/QPA plugin on disposable builds, without a GPU requirement."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="AnatomyExplorer-runtime-") as d:
        root = Path(d).resolve()
        report = root / "runtime.json"
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", LOCALAPPDATA=str(root / "profile"), AE_TEST_SETTINGS_DIR=str(root / "settings"))
        subprocess.run([str(executable), "--runtime-check", "--report", str(report)], env=env, check=True, timeout=60)
        result = json.loads(report.read_text())
        assert result["frozen"] and result["runtime_imports"]
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
