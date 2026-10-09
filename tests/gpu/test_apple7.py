"""ANATOMY_WGPU_LIMITS=apple7: the switch cuts the device to Metal/Apple7 limits (a layout with 9 storage buffers in one
stage must fail), and the main pipelines build and draw under it. Each case runs in a subprocess because the shared device
is created once per process. Skips without a wgpu adapter.

    python -m pytest tests/gpu/test_apple7.py -q -p no:cacheprovider
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _has_gpu():
    try:
        sys.path.insert(0, str(ROOT))
        from app.gpu.device import get_gpu
        get_gpu()
        return True
    except Exception:
        return False


needs_gpu = unittest.skipUnless(_has_gpu(), "no wgpu adapter available")


def probe(code: str, emulate: bool = True) -> dict:
    env = dict(os.environ)
    env.pop("ANATOMY_WGPU_LIMITS", None)
    if emulate:
        env["ANATOMY_WGPU_LIMITS"] = "apple7"
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + str(ROOT / "tests") + os.pathsep + str(ROOT / "tests" / "gpu")
    p = subprocess.run([sys.executable, "-c", code], env=env, cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-1500:]
    return json.loads(p.stdout.strip().splitlines()[-1])


LAYOUT = """
import json, wgpu
from app.gpu.device import get_gpu
g = get_gpu()
def layout(n):
    ents = [dict(binding=i, visibility=wgpu.ShaderStage.COMPUTE, buffer=dict(type="read-only-storage")) for i in range(n)]
    try:
        bgl = g.device.create_bind_group_layout(entries=ents)
        g.device.create_pipeline_layout(bind_group_layouts=[bgl])
        g.device.queue.submit([])
        return "ok"
    except Exception as e:
        return "fail"
print(json.dumps(dict(emulated=g.emulated, info=g.info, nine=layout(9), eight=layout(8),
    bufs=g.limits["max-storage-buffers-per-shader-stage"], inside="timestamp-query-inside-passes" in g.features)))
"""

RENDER = """
import json, numpy as np
import test_visbuf as t
from app.gpu.renderer import WgpuRenderer
from app.viewer.renderer import Settings
m = t.fixture_model(); cam = t.camera_for(m); s = Settings(); s.msaa = 4
r = WgpuRenderer(t.GPU); r.set_model(m)
r.render(t.target(), (t.W, t.H), cam, s, None)
c = t.pixel_of(r, (np.asarray(m.item_bounds([0])[0]) + np.asarray(m.item_bounds([0])[1])) / 2)
print(json.dumps(dict(emulated=t.GPU.emulated, ok=True)))
"""


@needs_gpu
class Apple7(unittest.TestCase):
    def test_switch_bites(self):
        on = probe(LAYOUT, True)
        self.assertEqual(on["emulated"], "apple7")
        self.assertIn("EMULATED", on["info"])
        self.assertEqual(on["bufs"], 8)
        self.assertFalse(on["inside"])
        self.assertEqual(on["eight"], "ok")
        self.assertEqual(on["nine"], "fail", "9 storage buffers in one stage must be refused under the apple7 limits")

    def test_off_by_default(self):
        off = probe(LAYOUT, False)
        self.assertEqual(off["emulated"], "")
        self.assertEqual(off["nine"], "ok")

    def test_main_pipelines_build_under_it(self):
        self.assertTrue(probe(RENDER, True)["ok"])


if __name__ == "__main__":
    unittest.main()
