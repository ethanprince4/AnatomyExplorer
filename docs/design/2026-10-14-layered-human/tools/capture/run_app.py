"""Start the app for a scripted capture. GC stays off: long --script runs crashed in the garbage collector under
PySide6 on Python 3.13 (use Python 3.12). plates.py is importable because this folder is on sys.path."""
import gc, runpy, sys
from pathlib import Path
gc.disable()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[5]))   # repository root
sys.path.insert(0, str(HERE))
sys.argv = ["app"] + sys.argv[1:]
runpy.run_module("app", run_name="__main__", alter_sys=True)
