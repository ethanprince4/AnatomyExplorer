"""The shared wgpu device: one adapter, one device and one queue per process, no window surface.

Everything renders into offscreen textures (the Qt presenter in host.py copies them into the widget), so the adapter
is requested without a compatible surface. ``ANATOMY_WGPU_ADAPTER=<text>`` picks an adapter whose name, backend or
type contains the text (case-insensitive, for example ``UHD`` or ``intel d3d12``); without it the
high-performance adapter is used. Adapters that are software rasterisers are never chosen unless asked for by name.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

# Optional features the renderer can use; each is requested only when the adapter has it.
WANTED_FEATURES = (
    "primitive-index",
    "texture-adapter-specific-format-features",     # r32uint multisampling (visibility ids)
    "timestamp-query",
    "timestamp-query-inside-encoders",
    "timestamp-query-inside-passes",
    "float32-filterable",
    "indirect-first-instance",
    "bgra8unorm-storage",
    "depth32float-stencil8",
)
# When several backends expose the same GPU, prefer the native one of the platform.
_BACKEND_RANK = {"Metal": 0, "Vulkan": 1, "D3D12": 2, "D3D11": 3, "OpenGL": 4}
_TYPE_RANK = {"DiscreteGPU": 0, "IntegratedGPU": 1, "Unknown": 2, "VirtualGPU": 3, "CPU": 9}


class GpuUnavailable(RuntimeError):
    """No usable wgpu adapter or device."""


@dataclass
class Gpu:
    adapter: object
    device: object
    queue: object
    features: set = field(default_factory=set)
    limits: dict = field(default_factory=dict)
    info: str = ""
    prim_index: bool = False
    name: str = ""
    backend: str = ""
    adapter_type: str = ""


_lock = threading.Lock()
_gpu: Gpu | None = None
_failure: str | None = None


def _describe(adapter) -> tuple[str, str, str]:
    info = dict(adapter.info)
    return (str(info.get("device") or "").strip(), str(info.get("backend_type") or ""),
            str(info.get("adapter_type") or ""))


def list_adapters() -> list[str]:
    """Readable names of every adapter wgpu can see ("name | backend | type")."""
    import wgpu
    return [" | ".join(_describe(a)) for a in wgpu.gpu.enumerate_adapters_sync()]


def _choose_adapter(wanted: str | None):
    import wgpu
    if not wanted:
        try:
            adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        except Exception as exc:                                   # pragma: no cover - driver specific
            raise GpuUnavailable(f"no wgpu adapter: {exc}") from exc
        if adapter is None:
            raise GpuUnavailable("no wgpu adapter")
        if _describe(adapter)[2] == "CPU":
            raise GpuUnavailable(f"only a software adapter is available ({_describe(adapter)[0]})")
        return adapter
    adapters = list(wgpu.gpu.enumerate_adapters_sync())
    needle = wanted.lower()
    hits = []
    for a in adapters:
        name, backend, kind = _describe(a)
        if needle in f"{name} {backend} {kind}".lower():
            hits.append((_TYPE_RANK.get(kind, 5), _BACKEND_RANK.get(backend, 5), a))
    if not hits:
        raise GpuUnavailable(f"ANATOMY_WGPU_ADAPTER={wanted!r} matches none of: " + "; ".join(list_adapters()))
    hits.sort(key=lambda h: (h[0], h[1]))
    return hits[0][2]


def _create(wanted: str | None) -> Gpu:
    try:
        import wgpu                                              # noqa: F401
    except Exception as exc:
        raise GpuUnavailable(f"wgpu is not installed: {exc}") from exc
    adapter = _choose_adapter(wanted)
    name, backend, kind = _describe(adapter)
    features = [f for f in WANTED_FEATURES if f in adapter.features]
    try:
        # The renderer pages its geometry from the limits, so ask for everything the adapter allows.
        device = adapter.request_device_sync(required_features=features, required_limits=dict(adapter.limits))
    except Exception as exc:
        raise GpuUnavailable(f"could not create a wgpu device on {name}: {exc}") from exc
    return Gpu(adapter=adapter, device=device, queue=device.queue, features=set(device.features),
               limits=dict(device.limits), info=f"{name} - wgpu {backend} ({kind})",
               prim_index="primitive-index" in device.features, name=name, backend=backend, adapter_type=kind)


def get_gpu() -> Gpu:
    """The process-wide device (created on first use). Raises GpuUnavailable, and keeps raising it, if it cannot be made."""
    global _gpu, _failure
    with _lock:
        if _gpu is not None:
            return _gpu
        if _failure is not None:
            raise GpuUnavailable(_failure)
        try:
            _gpu = _create(os.environ.get("ANATOMY_WGPU_ADAPTER") or None)
        except GpuUnavailable as exc:
            _failure = str(exc)
            raise
        except Exception as exc:
            _failure = f"wgpu failed to start: {exc}"
            raise GpuUnavailable(_failure) from exc
        return _gpu


def reset_gpu() -> None:
    """Forget the shared device (tests, adapter changes). Existing users keep their reference."""
    global _gpu, _failure
    with _lock:
        _gpu, _failure = None, None


def wait_idle(gpu: Gpu) -> None:
    """Block until everything submitted so far has finished on the GPU.

    wgpu-py 0.32's ``queue.on_submitted_work_done`` is broken (callback signature mismatch with wgpu-native), so this
    submits a one-word copy and maps its destination: the queue is in order, so the map completes after earlier work."""
    device = gpu.device
    src = getattr(gpu, "_idle_src", None)
    if src is None:
        src = device.create_buffer(size=16, usage="COPY_SRC")
        dst = device.create_buffer(size=16, usage="MAP_READ|COPY_DST")
        gpu._idle_src, gpu._idle_dst = src, dst
    dst = gpu._idle_dst
    enc = device.create_command_encoder()
    enc.copy_buffer_to_buffer(src, 0, dst, 0, 16)
    gpu.queue.submit([enc.finish()])
    dst.map_sync("READ")
    dst.unmap()
