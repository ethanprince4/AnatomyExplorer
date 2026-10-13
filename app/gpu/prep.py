"""What the load thread gets ready for the fast renderer before a model reaches the GUI thread. No Qt, no GPU objects.

``ensure_clusters(model)`` runs at the end of a model's load (app/viewer/model_loading.prepare_model, thread
"model-load"), after the detail levels: when the fast renderer is wanted and its own rule says this model is drawn from
clusters, the cluster set is found in the cluster cache or built there and then, and rides on the model
(cluster_cache.carry). The renderer's request on the GUI thread (geometry.build_geometry -> cluster_cache.get_clusters)
then gets that set at once: nothing is built on the GUI thread, and nothing is built twice when the cache is off, full
or read-only or the model has no identity. The build asks the load's checkpoint() after every part, so a cancelled load
or a closed tab stops it there (clusters.build_clusters drops the parts not started).

Two rules of other modules are repeated here, because the load thread must not import them: which backend the settings
ask for (app/ui/model_view.renderer_backend, Qt widgets) and whether the renderer draws a model from clusters
(app/gpu/renderer.WgpuRenderer.set_model and _wants_cluster_order, wgpu). tests/test_cluster_prepare.py holds each pair
together. If they ever part, the cost is time, not a wrong picture: a set built for nothing, or one built on the GUI
thread as before.
"""
from __future__ import annotations

import logging
import os

from app.config import DEFAULT_SETTINGS
from app.load_control import LoadCancelled, checkpoint

log = logging.getLogger(__name__)

CULL_MIN_TRIS = 1_000_000                # renderer.CULL_MIN_TRIS
_settings = None                         # the app's settings (the main window's own dict, read live); None outside the app


def use_settings(settings):
    """The main window names its settings dict once. Without one (a tool or a test that prepares a model by hand)
    clusters are prepared only when ANATOMY_RENDERER=wgpu asks for the fast renderer by name."""
    global _settings
    _settings = settings


def renderer_backend(settings):
    """ "opengl" or "wgpu": app/ui/model_view.renderer_backend."""
    for value in (os.environ.get("ANATOMY_RENDERER"), settings.get("renderer_backend")):
        value = str(value or "").strip().lower()
        if value in ("opengl", "wgpu"):
            return value
    fast = settings.get("fast_renderer")
    if fast is None:
        fast = DEFAULT_SETTINGS["fast_renderer"]
    return "wgpu" if fast else "opengl"


def fast_renderer_wanted():
    """Will the view of the model being loaded be the fast renderer's, as far as the load thread can tell."""
    settings = _settings
    if settings is None:
        if str(os.environ.get("ANATOMY_RENDERER") or "").strip().lower() != "wgpu":
            return False
    elif renderer_backend(settings) != "wgpu":
        return False
    from . import device                 # no wgpu import; a device that could not be made stays that way for the session
    return device._failure is None


def cull_rule():
    """(mode, triangle threshold) as WgpuRenderer.__init__ reads them from the environment."""
    mode = os.environ.get("ANATOMY_CULL", "auto").strip().lower()
    mode = mode if mode in ("on", "off", "auto", "plain") else "auto"
    return mode, int(float(os.environ.get("ANATOMY_CULL_MIN_TRIS") or CULL_MIN_TRIS))


def wants_clusters(model):
    """Does the fast renderer draw this model from clusters: set_model accepts it (no alpha-cut texture) and
    _wants_cluster_order holds (a static model and, in "auto", at least the threshold of level-0 triangles)."""
    parts = model.parts
    if any(p.look.texture is not None and p.look.alpha_cut > 0.0 for p in parts):
        return False
    mode, min_tris = cull_rule()
    if mode == "off":
        return False
    if getattr(model, "anim_vertices", None) is not None or any(p.has_morph for p in parts):
        return False
    if mode in ("on", "plain"):
        return True
    return sum(int(p.count) for p in parts) // 3 >= min_tris


def _checkpoint(_done, _total):
    checkpoint()


def ensure_clusters(model):
    """Find or build the model's clusters now, on the calling (load) thread, and let them ride on the model. Returns the
    set, or None when the fast renderer is not wanted, the model is not drawn from clusters or the build failed (the
    reason then rides instead, so the GUI thread does not repeat a build that cannot work). Raises only LoadCancelled."""
    try:
        if not (fast_renderer_wanted() and wants_clusters(model)):
            return None
        from . import cluster_cache
        cd = cluster_cache.carried(model)
        if cd is not None:
            return cd
    except Exception as exc:             # noqa: BLE001 - what this rule cannot read (or a failure riding already) is left to the renderer
        log.debug("clusters not prepared on the load thread: %s", exc)
        return None
    try:
        cd = cluster_cache.get_clusters(model, None, progress=_checkpoint)
    except LoadCancelled:
        raise
    except cluster_cache.cl.ClusterError as exc:     # the model's own fault: the same build would fail the same way
        log.warning("the clusters of this model could not be built: %s", exc)
        cluster_cache.carry_failure(model, exc)
        return None
    except Exception as exc:             # noqa: BLE001 - anything else: the renderer tries for itself, as before
        log.warning("the clusters of this model were not prepared on the load thread: %s", exc)
        return None
    cluster_cache.carry(model, cd)
    return cd
