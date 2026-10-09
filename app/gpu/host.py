"""GpuWidget: a Qt widget that shows what a wgpu renderer draws into an offscreen texture.

There is no window surface. The widget owns one rgba8unorm texture of the widget's physical size (logical size x
devicePixelRatioF), asks a callback to fill it, copies it to a mappable buffer and paints the pixels with
QPainter.drawImage using a QImage whose devicePixelRatio maps it 1:1 to physical pixels. Because it is an ordinary
QWidget, child widgets (the model viewer's translucent label Overlay) stay on top and blend normally; the swapchain
route from the embedding spike mis-blended partial alpha under child widgets, this one does not.

Two present modes (``present_mode`` or ANATOMY_PRESENT_MODE):

``sync``   render, copy, map and wait, paint the same frame. No latency, but CPU and GPU never overlap.
``async``  two buffers in a ring. A frame is mapped asynchronously and the newest completed one is painted; before
           painting, the previous frame is waited for, so the picture is at most one frame behind and the CPU
           prepares frame N+1 while the GPU draws frame N. When rendering stops, a short timer paints the last frame.

Rendering happens only after ``update()`` (or a resize or show): the translucent Overlay child repaints the area
beneath it every frame, and that must only re-blit the cached image, never redraw the 3D scene.
"""
from __future__ import annotations

import os
import time

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QWidget

from .device import Gpu, get_gpu

PRESENT_MODES = ("sync", "async")
DEFAULT_PRESENT_MODE = "async"             # chosen from tools/perf/gpu/present_bench.py numbers
OUTPUT_FORMAT = "rgba8unorm"
OUTPUT_USAGE = "RENDER_ATTACHMENT|COPY_SRC|TEXTURE_BINDING"
_RING = 2


def present_mode_from_env(default: str | None = None) -> str:
    mode = (os.environ.get("ANATOMY_PRESENT_MODE") or default or DEFAULT_PRESENT_MODE).strip().lower()
    return mode if mode in PRESENT_MODES else DEFAULT_PRESENT_MODE


def _promise_done(promise) -> bool:
    """True once the map callback has fired (wgpu-native's poller thread sets the event). wgpu-py 0.32 offers no public
    non-blocking test, and ``promise.then`` needs an asyncio loop that a Qt application does not have."""
    event = getattr(promise, "_thread_event", None)
    return True if event is None else bool(event.is_set())


class _Slot:
    __slots__ = ("buf", "promise", "frame", "w", "h", "view")

    def __init__(self, buf):
        self.buf, self.promise, self.frame, self.w, self.h, self.view = buf, None, -1, 0, 0, None


class GpuWidget(QWidget):
    presentFailed = Signal(str)

    def __init__(self, parent=None, present_mode: str | None = None, gpu: Gpu | None = None):
        QWidget.__init__(self, parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.gpu = gpu
        self.render_callback = None            # callable(texture, w, h) -> bool|None (False: nothing was drawn)
        self.present_mode = present_mode_from_env(present_mode)
        self.frame_cap_hz = None               # None: the screen's refresh rate; 0: uncapped (benchmarks)
        self.background = QColor(0, 0, 0)
        self.present_error = ""
        self._dirty = True
        self._tex = None
        self._size = (0, 0)
        self._slots: list[_Slot] = []
        self._ring_size = (0, 0)
        self._stride = 0
        self._frame = 0                        # frames rendered so far
        self._shown_frame = -1                 # newest frame whose pixels are in _disp
        self._disp = None                      # async: persistent copy of the newest completed frame
        self._disp_size = (0, 0)
        self._last_render_t = 0.0
        self._poll = QTimer(self)
        self._poll.setSingleShot(True)
        self._poll.setTimerType(Qt.PreciseTimer)
        self._poll.timeout.connect(self._poll_pending)
        self._kick_timer = QTimer(self)
        self._kick_timer.setSingleShot(True)
        self._kick_timer.timeout.connect(lambda: QWidget.update(self))
        self.stats = {"renders": 0, "paints": 0, "render_ms": 0.0, "copy_ms": 0.0, "wait_ms": 0.0, "draw_ms": 0.0,
                      "paint_ms": 0.0}

    # ------------------------------------------------------------------ sizes and requests
    def _physical_size(self):
        dpr = self.devicePixelRatioF()
        return max(int(self.width() * dpr), 2), max(int(self.height() * dpr), 2)

    def update(self, *args):
        """Ask for a new frame (a plain repaint request from Qt only re-blits the last one)."""
        self._dirty = True
        if not args and self._tex is not None and self.isVisible():
            interval = self._frame_interval()
            wait = interval - (time.perf_counter() - self._last_render_t)
            if interval and wait > 0.0005:
                # too early for another frame: come back when the cap allows it instead of painting the old image twice
                if not self._kick_timer.isActive():
                    self._kick_timer.start(max(1, int(wait * 1000)))
                return
        QWidget.update(self, *args)

    def request_present_only(self):
        QWidget.update(self)

    def set_present_mode(self, mode: str):
        if mode not in PRESENT_MODES:
            raise ValueError(f"present mode must be one of {PRESENT_MODES}")
        if mode != self.present_mode:
            self._release_ring()
            self.present_mode = mode
            self._dirty = True
            QWidget.update(self)

    def render_frame(self, texture, w, h):
        """Fill ``texture`` (w x h, rgba8unorm). Return False when nothing was drawn."""
        if self.render_callback is not None:
            return self.render_callback(texture, w, h)
        return False

    def on_present_error(self, message: str):
        self.present_error = message
        self.presentFailed.emit(message)

    # ------------------------------------------------------------------ resources
    def _ensure_gpu(self) -> Gpu:
        if self.gpu is None:
            self.gpu = get_gpu()
        return self.gpu

    def make_output_texture(self, w, h):
        return self._ensure_gpu().device.create_texture(size=(w, h, 1), format=OUTPUT_FORMAT, usage=OUTPUT_USAGE)

    def _ensure_texture(self, w, h):
        if self._tex is None or self._size != (w, h):
            self._release_ring()
            if self._tex is not None:
                self._tex.destroy()
            self._tex = self.make_output_texture(w, h)
            self._size = (w, h)
        return self._tex

    def _ensure_ring(self, w, h):
        if self._ring_size == (w, h) and self._slots:
            return
        self._release_ring()
        self._stride = (w * 4 + 255) & ~255                      # bytes_per_row must be a multiple of 256
        device = self._ensure_gpu().device
        count = _RING if self.present_mode == "async" else 1
        self._slots = [_Slot(device.create_buffer(size=self._stride * h, usage="MAP_READ|COPY_DST"))
                       for _ in range(count)]
        self._ring_size = (w, h)

    def _release_ring(self):
        """Settle every pending map, then free the buffers. Nothing of the old size is ever shown afterwards."""
        self._poll.stop()
        for s in self._slots:
            s.view = None
            try:
                if s.promise is not None:
                    s.promise.sync_wait()
                if s.buf.map_state == "mapped":
                    s.buf.unmap()
            except Exception:
                pass
            try:
                s.buf.destroy()
            except Exception:
                pass
        self._slots = []
        self._ring_size = (0, 0)
        self._disp = None
        self._shown_frame = -1

    def release_surface(self):
        """Free the texture and buffers (hidden tab). The next show renders again."""
        self._release_ring()
        if self._tex is not None:
            try:
                self._tex.destroy()
            except Exception:
                pass
        self._tex, self._size = None, (0, 0)
        self._dirty = True

    # ------------------------------------------------------------------ events
    def resizeEvent(self, event):
        QWidget.resizeEvent(self, event)
        self._dirty = True

    def showEvent(self, event):
        QWidget.showEvent(self, event)
        self._dirty = True

    def hideEvent(self, event):
        self.release_surface()
        QWidget.hideEvent(self, event)

    def paintEvent(self, event):
        t0 = time.perf_counter()
        w, h = self._physical_size()
        painter = QPainter(self)
        try:
            self._maybe_render(w, h)
            self._present(painter, w, h)
        except Exception as exc:                     # a Qt paint handler must never raise
            self.on_present_error(f"{type(exc).__name__}: {exc}")
        finally:
            painter.end()
        st = self.stats
        st["paints"] += 1
        st["paint_ms"] += (time.perf_counter() - t0) * 1000.0

    # ------------------------------------------------------------------ render and read back
    def _frame_interval(self) -> float:
        hz = self.frame_cap_hz
        if hz is None:
            screen = self.screen()
            hz = float(screen.refreshRate()) if screen is not None else 60.0
        return 0.0 if not hz else 0.92 / hz

    def _maybe_render(self, w, h):
        if self.present_error:
            return
        need = self._dirty or self._tex is None or self._size != (w, h)
        if not need:
            return
        interval = self._frame_interval()
        now = time.perf_counter()
        if interval and self._tex is not None and self._size == (w, h) and now - self._last_render_t < interval:
            if not self._kick_timer.isActive():
                self._kick_timer.start(max(1, int((interval - (now - self._last_render_t)) * 1000)))
            return
        self._dirty = False                          # cleared first: update() calls made while rendering ask for the next frame
        self._last_render_t = now
        tex = self._ensure_texture(w, h)
        r0 = time.perf_counter()
        drew = self.render_frame(tex, w, h)
        r1 = time.perf_counter()
        self.stats["render_ms"] += (r1 - r0) * 1000.0
        if drew is False:
            return
        self.stats["renders"] += 1
        self._ensure_ring(w, h)
        self._queue_copy(tex, w, h)
        self.stats["copy_ms"] += (time.perf_counter() - r1) * 1000.0
        if self.present_mode == "sync":
            self._resolve_sync(self._slots[0])

    def _drop_view(self, slot: _Slot):
        """Sync mode keeps the newest frame mapped so a repaint can blit it again; let it go before the buffer is reused."""
        if slot.view is not None:
            slot.view = None
            if slot.buf.map_state == "mapped":
                slot.buf.unmap()

    def _resolve_sync(self, slot: _Slot):
        t0 = time.perf_counter()
        promise, slot.promise = slot.promise, None
        promise.sync_wait()
        self.stats["wait_ms"] += (time.perf_counter() - t0) * 1000.0
        slot.view = slot.buf.read_mapped(copy=False)
        self._shown_frame = slot.frame

    def _queue_copy(self, tex, w, h):
        gpu = self._ensure_gpu()
        slot = self._free_slot()
        self._drop_view(slot)
        enc = gpu.device.create_command_encoder()
        enc.copy_texture_to_buffer({"texture": tex, "mip_level": 0, "origin": (0, 0, 0)},
                                   {"buffer": slot.buf, "offset": 0, "bytes_per_row": self._stride, "rows_per_image": h},
                                   (w, h, 1))
        gpu.queue.submit([enc.finish()])
        slot.promise = slot.buf.map_async("READ")
        slot.frame, slot.w, slot.h = self._frame, w, h
        self._frame += 1

    def _free_slot(self) -> _Slot:
        for s in self._slots:
            if s.promise is None:
                return s
        # Ring full: wait for the oldest, keep its pixels if they are the newest we have.
        oldest = min(self._slots, key=lambda s: s.frame)
        self._take(oldest)
        return oldest

    def _take(self, slot: _Slot, keep=True):
        """Resolve a slot's map and (async mode) copy its pixels into the persistent display array, then unmap."""
        promise, slot.promise = slot.promise, None
        t0 = time.perf_counter()
        promise.sync_wait()
        self.stats["wait_ms"] += (time.perf_counter() - t0) * 1000.0
        try:
            if keep and slot.frame > self._shown_frame and (slot.w, slot.h) == self._ring_size:
                view = slot.buf.read_mapped(copy=False)
                src = np.frombuffer(view, dtype=np.uint8)
                if self._disp is None or self._disp.size != src.size:
                    self._disp = np.empty(src.size, dtype=np.uint8)
                self._disp[:] = src
                self._disp_size = (slot.w, slot.h)
                self._shown_frame = slot.frame
                del src, view
        finally:
            if slot.buf.map_state == "mapped":
                slot.buf.unmap()

    def _collect(self, wait_below=None):
        """Take every completed map; with ``wait_below`` also wait for frames older than that number."""
        for s in sorted((s for s in self._slots if s.promise is not None), key=lambda s: s.frame):
            if (wait_below is not None and s.frame < wait_below) or _promise_done(s.promise):
                self._take(s)

    def _pending(self) -> bool:
        return any(s.promise is not None for s in self._slots)

    def _poll_pending(self):
        if not self._slots:
            return
        before = self._shown_frame
        try:
            self._collect()
        except Exception as exc:
            self.on_present_error(f"{type(exc).__name__}: {exc}")
            return
        if self._shown_frame != before:
            QWidget.update(self)                     # paint the frame that just completed (not a new render)
        if self._pending():
            self._poll.start(1)

    # ------------------------------------------------------------------ present
    def _blit(self, painter, data, w, h):
        dpr = self.devicePixelRatioF()
        img = QImage(data, w, h, self._stride, QImage.Format_RGBX8888)
        img.setDevicePixelRatio(dpr)
        if img.deviceIndependentSize().width() < self.width() or img.deviceIndependentSize().height() < self.height():
            painter.fillRect(self.rect(), self.background)
        t0 = time.perf_counter()
        painter.drawImage(QPointF(0, 0), img)
        self.stats["draw_ms"] += (time.perf_counter() - t0) * 1000.0
        del img

    def _present(self, painter, w, h):
        if self.present_mode == "sync":
            slot = self._slots[0] if self._slots else None
            if slot is not None and slot.view is not None and (slot.w, slot.h) == (w, h):
                self._blit(painter, slot.view, w, h)
            else:
                painter.fillRect(self.rect(), self.background)
            return
        newest = self._frame - 1
        self._collect(wait_below=newest)             # at most one frame behind: frames older than the newest are settled
        if self._slots and (self._disp is None or self._disp_size != (w, h)):
            # nothing of this size yet (first frame or just resized): wait for the newest frame rather than show nothing
            self._collect(wait_below=newest + 1)
        if self._disp is not None and self._disp_size == (w, h):
            self._blit(painter, self._disp.data, w, h)
        else:
            painter.fillRect(self.rect(), self.background)
        if self._pending():
            self._poll.start(1)

    # ------------------------------------------------------------------ for tests and screenshots
    def present_image(self) -> np.ndarray:
        """Render now (when a frame was requested) and return the (h, w, 4) uint8 pixels the presenter would paint, read
        back through the active present mode's path."""
        w, h = self._physical_size()
        saved, self.frame_cap_hz = self.frame_cap_hz, 0
        try:
            self._maybe_render(w, h)
        finally:
            self.frame_cap_hz = saved
        if not self._slots:
            raise RuntimeError("nothing has been rendered")
        if self.present_mode == "async":
            self._collect(wait_below=self._frame)
            raw = self._disp
        else:
            raw = np.frombuffer(self._slots[0].view, dtype=np.uint8)
        return raw.reshape(h, self._stride)[:, :w * 4].reshape(h, w, 4).copy()
