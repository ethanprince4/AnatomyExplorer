"""Caps gather cost split: stages and scissor. python cut_prof2.py <model>"""
import sys, time, os
import numpy as np
sys.path.insert(0, os.getcwd())
from tools.perf import perfkit as pk
pk.env_setup()
from tools.perf.viewer_session import ViewerSession, timed_prepare
from app.gpu.renderer import WgpuRenderer
from app.gpu import caps as capsmod
entry, model, load = timed_prepare(sys.argv[1])
sess = ViewerSession(entry, model, backend="wgpu", renderer_factory=lambda gpu: WgpuRenderer(gpu, profile=True))
r, w, m = sess.r, sess.w, model
cl = [i for i in range(len(m.items)) if m.items[i].clip]
cx = [float((m.item_bounds([i])[0][0] + m.item_bounds([i])[1][0]) / 2) for i in (cl or range(len(m.items)))]
C = capsmod.CapPasses
orig = C.encode_gather
CFG = {"stages": ("parity", "cap"), "tiny": False}
def gather(self, enc, plan):
    w_, h_ = plan.size
    v = self.v
    first = True
    for ci in plan.items:
        x0, y0, x1, y1 = ci.rect
        scissor = (x0, h_ - y1, x1 - x0, y1 - y0)
        if CFG["tiny"]: scissor = (x0, h_ - y1, 2, 2)
        for stage in CFG["stages"]:
            if stage == "parity":
                rp = enc.begin_render_pass(color_attachments=[], depth_stencil_attachment={"view": v["parity"], "depth_load_op": "load", "depth_store_op": "store"})
                rp.set_scissor_rect(*scissor)
                rp.set_pipeline(self._pipe(("reset",))); rp.draw(3)
                rp.set_pipeline(self._pipe(("parity",)))
            else:
                op = "clear" if first else "load"
                rp = enc.begin_render_pass(color_attachments=[{"view": v[n], "load_op": op, "store_op": "store", "clear_value": (0, 0, 0, 0)} for n, _f in capsmod.CAP_TARGETS],
                    depth_stencil_attachment={"view": v["key"], "depth_load_op": op, "depth_store_op": "store", "depth_clear_value": 1.0})
                first = False
                rp.set_scissor_rect(*scissor)
                rp.set_pipeline(self._pipe(("cap",)))
                rp.set_bind_group(3, self._bg_parity)
            rp.set_bind_group(0, self._bg0)
            current = None
            for di, page, first_index, count in ci.draws:
                rp.set_bind_group(1, self._bg_su, [di * self.shade_stride])
                if current != page:
                    rp.set_bind_group(2, plan.pages[page][0])
                    rp.set_index_buffer(plan.pages[page][1].buffer, "uint32", plan.pages[page][1].index_byte_offset, plan.pages[page][1].index_bytes)
                    current = page
                rp.draw_indexed(count, 1, first_index, 0, di)
            rp.end()
C.encode_gather = gather
def run(name, sect, **cfg):
    CFG.update({"stages": ("parity", "cap"), "tiny": False}); CFG.update(cfg)
    w.sections[0] = sect
    sess.warm(4)
    for _ in range(6): sess.paint()
    walls = []
    for row in sess.orbit_run(frames=40, step_deg=3.0):
        walls.append(row["wall_ms"])
    print(name, "wall", round(float(np.median(walls)), 1), flush=True)
cut = [float(np.median(cx)), False]
tris = sum(c for ci in [0] for c in [0])
run("cut_full", cut)
run("cut_parity_only", cut, stages=("parity",))
run("cut_cap_only", cut, stages=("cap",))
run("cut_tiny_scissor", cut, tiny=True)
run("cut_no_gather", cut, stages=())
sess.close()
