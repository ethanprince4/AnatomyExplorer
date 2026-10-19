"""The status-bar readout of a model's 3D view: renderer in use, frame rate, triangles drawn."""
from types import SimpleNamespace

from app.ui.model_view import frame_rate, perf_readout


def _view(label="Fast renderer", note="", drawn=4210000):
    return SimpleNamespace(renderer_label=label, renderer_note=note, renderer=SimpleNamespace(drawn_tris=drawn),
                           rsettings=SimpleNamespace(msaa=4), gl_info="NVIDIA GeForce RTX 3080",
                           _render_size=lambda: (3840, 2160))


def test_frame_rate_needs_an_unbroken_run():
    assert frame_rate([]) is None
    assert frame_rate([1.0, 1.02]) is None
    assert abs(frame_rate([0.0, 0.02, 0.04, 0.06]) - 50.0) < 1e-6
    assert frame_rate([0.0, 0.02, 0.04, 5.0]) is None                 # a redraw after a pause starts a new run
    assert abs(frame_rate([0.0, 5.0, 5.1, 5.2]) - 10.0) < 1e-6


def test_readout_names_renderer_rate_and_triangles():
    text, tip = perf_readout(_view(), 3.2, 61.4)
    assert text == "Fast renderer · 61 fps · 4,210,000 triangles drawn"
    assert "NVIDIA GeForce RTX 3080" in tip
    assert "3840 × 2160 pixels, 4x anti-aliasing" in tip


def test_readout_says_when_the_fast_renderer_did_not_start():
    text, tip = perf_readout(_view("Standard renderer", "No module named 'wgpu'"), 3.2, None)
    assert text == "Standard renderer (fast renderer did not start) · draw 3.2 ms · 4,210,000 triangles drawn"
    assert "No module named 'wgpu'" in tip


def test_readout_without_a_live_renderer():
    view = _view()
    view.renderer = None
    assert perf_readout(view, 1.0, None)[0] == "Fast renderer · draw 1.0 ms"
