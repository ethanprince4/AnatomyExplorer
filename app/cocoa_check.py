"""Frozen native Cocoa test entry; exits before updater activation or preferences."""
import sys
from pathlib import Path


def main():
    if sys.platform != "darwin":
        raise RuntimeError("Native Cocoa check requires macOS")
    # Source checks use the same bridge files collected as explicit frozen imports.
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging/diagnostics/mac_ax"))
    from tree_ax_repro import main as tree_main
    return tree_main([argument for argument in sys.argv[1:] if argument != "--cocoa-check"])


if __name__ == "__main__":
    raise SystemExit(main())
