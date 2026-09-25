"""Entry point of the packaged app (PyInstaller cannot start a package's __main__ directly).

Runs app/__main__.py exactly as `python -m app` does, including its error dialog."""
import os
import runpy
import sys

# a windowed build has no console: give print() and tracebacks somewhere harmless to go
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))
if sys.__stderr__ is None:
    sys.__stderr__ = sys.stderr
sys.dont_write_bytecode = True      # never write __pycache__ into the installed (read-only / signed) app folder

runpy.run_module("app", run_name="__main__", alter_sys=True)
