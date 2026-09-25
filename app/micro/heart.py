"""The whole heart: chambers, valves, coronary circulation, conduction system and pericardium.

Unlike the tissue blocks, this is a whole organ at gross scale (1 unit = 6 cm, so the heart is ~2 units from base
to apex). It is built in a *heart frame* and turned into the body at the end:

* heart frame: y runs from apex (-) to base (+) along the long axis, x from the right chambers (-) to the left
  chambers (+), and z = 0 is the four-chamber plane (the plane through both atrioventricular valves and the apex),
  with the anterior (sternocostal) side at +z;
* body frame (the app's): y superior, x to the patient's left, z anterior. The heart frame is tilted 48 degrees
  about z (apex swings to the left) and then 33 degrees about x (apex comes forward), so the apex points
  anteriorly, inferiorly and to the left, the right atrium forms the right border and the right ventricle most of
  the sternocostal surface - the heart as it sits in the middle mediastinum.

The great vessels, pericardial sac and every path that must follow the body (SVC vertical, the arch passing over
the left bronchus) are laid out in body coordinates and pulled back into the heart frame, so after the final turn
they are exactly where they should be. The default cut removes everything on the anterior side of the
four-chamber plane, which opens all four chambers, both AV valves, the septa and the conduction system at once.

Muscle, cavities and wall layers are signed-distance fields on one voxel grid, so every junction (auricle on
atrium, infundibulum on ventricle, papillary muscle on wall) is a smooth fillet and the wall layers nest exactly;
valves, chordae, coronary vessels and Purkinje fibres are swept or parametric meshes laid onto those fields.
"""
import math

import numpy as np
from scipy.spatial import cKDTree

from .base import Part
from .geometry import Mesh, compute_normals, ellipsoid as ell_mesh, smooth_path, tube
from .organic import noise_field
from .sdf import BIG, Volume, round_cone, smin

# ----------------------------------------------------------------------------------------------- frame
_A, _B = math.radians(48.0), math.radians(-33.0)
_RZ = np.array([[math.cos(_A), -math.sin(_A), 0.0], [math.sin(_A), math.cos(_A), 0.0], [0.0, 0.0, 1.0]])
_RX = np.array([[1.0, 0.0, 0.0], [0.0, math.cos(_B), -math.sin(_B)], [0.0, math.sin(_B), math.cos(_B)]])
R_BODY = _RX @ _RZ                      # heart frame -> body frame
CUT_NORMAL = R_BODY @ np.array([0.0, 0.0, 1.0])     # body-frame normal of the four-chamber plane (anterior side)


def to_heart(p_body):
    """Body-frame point(s) or vector(s) into the heart frame."""
    return np.asarray(p_body, float) @ R_BODY


def to_body(p_heart):
    return np.asarray(p_heart, float) @ R_BODY.T


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


VOX = 0.013                             # main grid; wall layers are 2-3 voxels thick

# ----------------------------------------------------------------------------------------------- layout (heart frame)
Y_AV = 0.24                              # atrioventricular (valve) plane
# ventricles are tapering round cones (apex point, apex radius, base point, base radius): exact distances, so the
# wall layers keep their thickness
LV_O = ((0.24, -1.02, -0.02), 0.27, (0.20, 0.02, -0.04), 0.50)
LV_C = ((0.24, -0.97, -0.02), 0.085, (0.21, 0.02, -0.04), 0.31)
LV_C_MID = ((0.235, -0.40, -0.03), 0.33)                  # bulges the cavity into a bullet, not a cone
RV_O = ((-0.16, -0.68, 0.12), 0.20, (-0.36, 0.02, 0.10), 0.52)
RV_WALL = 0.068                          # ~4 mm: a third of the LV wall
ATRIAL_WALL = 0.042


def _rot_body():
    """Heart-frame columns of the body axes, for ellipsoids laid out along the body."""
    return np.stack([to_heart((1.0, 0.0, 0.0)), to_heart((0.0, 1.0, 0.0)), to_heart((0.0, 0.0, 1.0))], 1)


# atria as ellipsoids along the body axes (centre, radii across / vertical / front-to-back): the right atrium is a
# tall chamber between the venae cavae, the left atrium a wide, flat box between the pulmonary veins
RA_C = (to_heart((-0.64, 0.08, -0.12)), np.array([0.27, 0.36, 0.27]))
LA_C = (to_heart((-0.30, 0.39, -0.44)), np.array([0.38, 0.23, 0.22]))
ROT_B = _rot_body()
IAS_HALF = 0.03                          # half thickness of the interatrial septum

TV_C, TV_R = np.array([-0.38, Y_AV, 0.01]), 0.22        # tricuspid annulus
MV_C, MV_R = np.array([0.25, Y_AV + 0.01, -0.08]), 0.20  # mitral annulus
AO_C, AO_R = np.array([-0.03, 0.37, 0.16]), 0.155        # aortic valve (annulus centre)

# Everything that has to line up with the body is written in body coordinates (B) and pulled into the heart frame.
AO_B = to_body(AO_C)
# the valve axes lean from the heart's long axis towards the vessel they open into
AO_AX = unit(0.55 * unit(to_heart(unit((-0.20, 0.92, 0.33)))) + 0.45 * np.array([0.0, 1.0, 0.0]))
PV_B = AO_B + np.array([0.30, 0.22, 0.24])               # pulmonary valve: left, above and in front of the aortic
PV_C, PV_R = to_heart(PV_B), 0.145
PV_AX = unit(0.55 * unit(to_heart(unit((0.25, 0.85, -0.45)))) + 0.45 * np.array([0.0, 1.0, 0.0]))
RVOT_BASE = np.array([-0.20, -0.02, 0.30])               # where the infundibulum leaves the RV body

# auricles as chains of flattened lobes lying on the heart: (body-frame points, widths, thicknesses, outward
# body direction). The right one is a broad triangular flap against the root of the aorta; the left one a slim,
# crenated, hooked finger curling round the left side of the pulmonary trunk.
RAU = (to_heart([[-0.70, 0.30, 0.08], [-0.60, 0.40, 0.22], [-0.49, 0.45, 0.31], [-0.38, 0.45, 0.36]]),
       [0.17, 0.15, 0.12, 0.07], [0.085, 0.075, 0.062, 0.045], to_heart(unit((-0.3, 0.2, 1.0))))
LAU = (to_heart([[0.02, 0.58, -0.26], [0.24, 0.66, -0.12], [0.35, 0.62, 0.04], [0.33, 0.57, 0.18],
                 [0.25, 0.52, 0.27]]),
       [0.10, 0.11, 0.10, 0.08, 0.055], [0.075, 0.075, 0.065, 0.055, 0.04], to_heart(unit((1.0, 0.1, 0.6))))

# great veins in body coordinates, each starting at the atrium except the SVC, which runs down into it
VEINS_B = {
    "svc": ([[-0.66, 1.34, -0.05], [-0.67, 0.82, -0.08], [-0.70, 0.30, -0.10]], 0.125),
    "ivc": ([[-0.66, -0.24, -0.18], [-0.65, -0.46, -0.20], [-0.64, -0.66, -0.20]], 0.145),
    "rspv": ([[-0.46, 0.55, -0.52], [-0.72, 0.60, -0.53], [-0.96, 0.64, -0.50]], 0.078),
    "ripv": ([[-0.46, 0.30, -0.56], [-0.72, 0.26, -0.57], [-0.96, 0.22, -0.54]], 0.078),
    "lspv": ([[-0.04, 0.58, -0.56], [0.22, 0.64, -0.52], [0.50, 0.68, -0.46]], 0.074),
    "lipv": ([[-0.04, 0.36, -0.60], [0.22, 0.38, -0.56], [0.50, 0.38, -0.50]], 0.074),
}


def _inlets():
    """Where each great vein opens into its atrium: (heart-frame point, direction out of the atrium, lumen radius)."""
    out = {}
    for k, (pts, r) in VEINS_B.items():
        pts = np.asarray(pts, float)
        if k == "svc":
            pts = pts[::-1]
        out[k] = (to_heart(pts[0]), to_heart(unit(pts[1] - pts[0])), r - 0.028)
    return out


VEIN_INLETS = _inlets()
# opening of the coronary sinus: in the floor of the right atrium between the IVC opening and the tricuspid orifice
CS_OSTIUM = np.array([-0.35, 0.33, -0.15])
CS_DIR = unit((0.10, -0.25, -1.0))       # the sinus approaches from behind, in the posterior coronary sulcus


# ----------------------------------------------------------------------------------------------- field helpers
def _ell(c, r):
    c = np.asarray(c, np.float32)
    r = np.asarray(r, np.float32)

    def f(x, y, z):
        px, py, pz = x - c[0], y - c[1], z - c[2]
        k0 = np.sqrt((px / r[0]) ** 2 + (py / r[1]) ** 2 + (pz / r[2]) ** 2)
        k1 = np.sqrt((px / r[0] ** 2) ** 2 + (py / r[1] ** 2) ** 2 + (pz / r[2] ** 2) ** 2)
        return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)
    return f


def _cap(a, b, r1, r2=None):
    """Round cone as a stampable shape (fn, bmin, bmax)."""
    return round_cone(np.asarray(a, float), np.asarray(b, float), r1, r1 if r2 is None else r2)


def _chain(path, radii, per=8):
    """A tapering tube through control points, as a list of stampable round cones."""
    path = smooth_path(np.asarray(path, float), per * len(path))
    radii = np.interp(np.linspace(0, 1, len(path)), np.linspace(0, 1, len(radii)), radii)
    return [_cap(path[i], path[i + 1], radii[i], radii[i + 1]) for i in range(len(path) - 1)]


def vmin(arrs):
    out = arrs[0]
    for a in arrs[1:]:
        out = np.minimum(out, a)
    return out


def vmax(arrs):
    out = arrs[0]
    for a in arrs[1:]:
        out = np.maximum(out, a)
    return out


def _smax(a, b, k):
    return -smin(-a, -b, k)


def _torus(c, axis, R, r):
    c = np.asarray(c, np.float32)
    a = unit(axis).astype(np.float32)

    def f(x, y, z):
        px, py, pz = x - c[0], y - c[1], z - c[2]
        h = px * a[0] + py * a[1] + pz * a[2]
        q = np.sqrt(np.maximum(px * px + py * py + pz * pz - h * h, 0.0)) - R
        return np.sqrt(q * q + h * h) - r
    return f


class Grid:
    """One voxel grid over the heart frame. Fields are plain float32 arrays on it."""

    def __init__(self, lo, hi, voxel=VOX):
        self.vol = Volume(lo, hi, voxel)
        self.voxel = voxel
        self.shape = self.vol.shape
        self.x, self.y, self.z = self.vol.axes()

    def eval(self, f):
        return np.broadcast_to(np.asarray(f(self.x, self.y, self.z), np.float32), self.shape).copy()

    def shapes(self, shapes):
        """Union of stampable shapes; far from them the field is BIG, not a true distance."""
        return self.stamp([shapes] if isinstance(shapes, tuple) else shapes)

    def stamp(self, shapes, base=None, pad=0.08):
        """Union of many small primitives (fn, bmin, bmax), each evaluated only inside its own box."""
        v = Volume.__new__(Volume)
        v.voxel, v.lo, v.shape, v._slices = self.voxel, self.vol.lo.copy(), self.shape, None
        v.d = np.full(self.shape, BIG, np.float32) if base is None else base.copy()
        for s in shapes:
            v.add(s, "union", pad)
        return v.d

    def mesh(self, d, smooth=0.8, step=1):
        """Polygonise d < 0, cropped to where it lives."""
        inside = np.nonzero(d < self.voxel * 2)
        if len(inside[0]) == 0:
            return Mesh()
        pad = 6 * step
        i0 = [max(int(a.min()) - pad, 0) for a in inside]
        i1 = [min(int(a.max()) + pad + 1, s) for a, s in zip(inside, self.shape)]
        v = Volume.__new__(Volume)
        v.voxel = self.voxel
        v.lo = self.vol.lo + np.array(i0) * self.voxel
        v.d = np.ascontiguousarray(d[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]])
        v.shape = v.d.shape
        v._slices = None
        return v.mesh(smooth, step=step)


def band(d, inner, outer):
    """Region inner < d < outer (a shell around the surface of d)."""
    return np.maximum(inner - d, d - outer)


def shell_normals(g, mesh, f, lo, hi):
    """Normals for a thin shell band(f, lo, hi) taken from the smooth field f itself. The band's own field has a
    kink a voxel inside each face, which leaves a faint grid-locked ripple in marching-cubes normals - glossy
    shading turns that into contour rings on a large, smooth surface like the epicardium."""
    from scipy.ndimage import gaussian_filter, map_coordinates
    fs = gaussian_filter(np.minimum(f, 1.0), 1.0)
    grads = np.gradient(fs, g.voxel)
    out = Mesh()
    for pos, nrm, idx in mesh.parts:
        ix = ((pos - g.vol.lo) / g.voxel).T
        gv = np.stack([map_coordinates(gc, ix, order=1, mode="nearest") for gc in grads], 1)
        fv = map_coordinates(fs, ix, order=1, mode="nearest")
        outer = np.abs(fv - hi) < np.abs(fv - lo)
        n = gv * np.where(outer, 1.0, -1.0)[:, None]
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        on_face = np.minimum(np.abs(fv - hi), np.abs(fv - lo)) < g.voxel * 0.8     # not where a cut forms the edge
        out.parts.append((pos, np.where(on_face[:, None], n, nrm).astype(np.float32), idx))
    return out


# ----------------------------------------------------------------------------------------------- mesh helpers
def thick_sheet(P, th):
    """Close a parametric sheet P (nu x nv x 3) into a thin solid of thickness th (a valve cusp, a flap)."""
    nu, nv, _ = P.shape
    tmp = Mesh().add(P.reshape(-1, 3), _grid(nu, nv))
    n = compute_normals(*tmp.arrays()[::2]).reshape(nu, nv, 3)
    top = (P + n * th / 2).reshape(-1, 3)
    bot = (P - n * th / 2).reshape(-1, 3)
    N = nu * nv
    idx = [_grid(nu, nv), _grid(nu, nv)[:, ::-1] + N]
    a = np.arange(N).reshape(nu, nv)
    rim = np.concatenate([a[0, :], a[1:, -1], a[-1, -2::-1], a[-2:0:-1, 0]])
    r0, r1 = rim, np.roll(rim, -1)
    idx.append(np.stack([r0, r1, r1 + N], 1))
    idx.append(np.stack([r0, r1 + N, r0 + N], 1))
    m = Mesh().add(np.vstack([top, bot]), np.vstack(idx))
    return _orient(m)


def _grid(nu, nv):
    a = np.arange(nu * nv).reshape(nu, nv)
    q0, q1, q2, q3 = a[:-1, :-1].ravel(), a[1:, :-1].ravel(), a[1:, 1:].ravel(), a[:-1, 1:].ravel()
    return np.concatenate([np.stack([q0, q1, q2], 1), np.stack([q0, q2, q3], 1)])


def _orient(m):
    from .cells import orient_outward
    return orient_outward(m)


def tube_path(points, radius, segments=10, samples=None, caps=True):
    p = np.asarray(points, float)
    if samples:
        p = smooth_path(p, samples)
    return tube(p, radius, segments, caps=caps)


def nudge(mesh, field):
    """Displace vertices by a small smooth field but keep the original normals: marching-cubes geometry normals
    carry a faint grid-aligned ripple that glossy shading on large smooth surfaces shows as contour rings, while the
    field-gradient normals do not."""
    out = Mesh()
    for pos, nrm, idx in mesh.parts:
        p = pos.astype(np.float64)
        out.parts.append(((p + field(p)).astype(np.float32), nrm, idx))
    return out


def resample(path, spacing):
    path = np.asarray(path, float)
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(int(s[-1] / spacing), 2)
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, path[:, k]) for k in range(3)], -1)


class Surface:
    """Snap points onto a meshed surface (nearest vertex, then lifted along its normal)."""

    def __init__(self, mesh):
        pos, nrm, _ = mesh.arrays()
        self.pos, self.nrm = pos.astype(float), nrm.astype(float)
        self.tree = cKDTree(self.pos)

    def snap(self, pts, lift=0.0, k=6):
        pts = np.atleast_2d(np.asarray(pts, float))
        d, j = self.tree.query(pts, k=k)
        w = 1.0 / np.maximum(d, 1e-6)
        w /= w.sum(axis=1, keepdims=True)
        p = (self.pos[j] * w[..., None]).sum(axis=1)
        n = (self.nrm[j] * w[..., None]).sum(axis=1)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        return p + n * lift, n

    def path(self, ctrl, lift, samples=80, relax=3):
        """A smooth curve through control points that stays on the surface."""
        p = smooth_path(np.asarray(ctrl, float), samples)
        for _ in range(relax):
            p, _ = self.snap(p, lift)
            p = smooth_path(p[::max(1, len(p) // 24)], samples) if len(p) > 30 else p
        p, _ = self.snap(p, lift)
        return p


DESC = {
    # ---- ventricles
    "lv": "Left ventricle: forms the apex, the left (obtuse) border and most of the diaphragmatic surface. Its wall "
          "(myocardium) is ~10-15 mm thick, about three times the right ventricle's, because it pumps against "
          "systemic pressure (~120/80 mmHg); in section the cavity is circular, embraced by the crescentic RV. "
          "Fine trabeculae carneae line its lower two-thirds; the outflow (aortic vestibule) below the aortic "
          "valve is smooth-walled. Pressure overload (hypertension, aortic stenosis) causes concentric "
          "hypertrophy; volume overload (aortic or mitral regurgitation) eccentric dilatation. Supplied mainly by "
          "the LAD and circumflex arteries.",
    "ivs": "Interventricular septum: the thick muscular wall between the ventricles, functionally part of the left "
           "ventricle (it bulges into the right ventricle, so the RV cavity is crescentic). Its lower, muscular "
           "part carries the bundle branches on each face; the small, thin membranous part at the top, just below "
           "the aortic valve, is where most ventricular septal defects (VSDs) occur. The anterior two-thirds are "
           "supplied by septal branches of the LAD, the posterior third by the posterior interventricular artery. "
           "Hypertrophic cardiomyopathy thickens it asymmetrically and can obstruct the LV outflow.",
    "rv": "Right ventricle: forms most of the sternocostal (anterior) surface and the inferior (acute) margin. Its "
          "wall is thin (3-5 mm) since it pumps into the low-pressure pulmonary circulation (~25/10 mmHg). Coarse "
          "trabeculae carneae, three papillary muscles (anterior, posterior, septal) and the moderator band fill "
          "its inflow part; the smooth-walled infundibulum (conus arteriosus) leads up to the pulmonary valve, "
          "separated from the inflow by the supraventricular crest. Hypertrophies in pulmonary hypertension "
          "(cor pulmonale) and pulmonary stenosis; infarcts with right coronary occlusion.",
    "apex": "Apex of heart: the blunt tip of the left ventricle, pointing anteriorly, inferiorly and to the left. It "
            "lies behind the left 5th intercostal space in the midclavicular line (~9 cm from the midline), where "
            "the apex beat is felt and the mitral valve is best heard. A displaced, diffuse apex beat means LV "
            "dilatation. The apical wall is the thinnest part of the LV and the site of apical aneurysm and "
            "thrombus after an anterior (LAD) infarct.",
    # ---- atria
    "ra": "Right atrium: receives systemic venous blood from the superior and inferior venae cavae and the heart's "
          "own veins through the coronary sinus. Its smooth posterior part (sinus venarum, from the embryonic "
          "sinus venosus) is separated from the rough, pectinate anterior part and auricle by the crista "
          "terminalis (externally the sulcus terminalis). Forms the right border of the heart shadow. The SA node "
          "lies in its wall at the SVC junction, the AV node in the triangle of Koch near the coronary sinus "
          "opening. Empties through the tricuspid valve.",
    "la": "Left atrium: the most posterior chamber, receiving oxygenated blood from the four pulmonary veins and "
          "emptying through the mitral valve. Its wall is smooth except in the auricle. It lies directly in front "
          "of the oesophagus, so an enlarged LA (mitral stenosis) indents a barium swallow and a transoesophageal "
          "echo probe sees it best. Atrial fibrillation often starts from muscle sleeves in the pulmonary vein "
          "ostia (target of pulmonary vein isolation).",
    "base": "Base of the heart: the posterior surface, facing backwards and to the right, formed mainly by the left "
            "atrium with the four pulmonary veins and a little of the right atrium. It lies opposite the apex, in "
            "front of the oesophagus and descending aorta (T5-T8 vertebrae), bounded below by the posterior part "
            "of the coronary sulcus carrying the coronary sinus. The great vessels leave near it, so in clinical "
            "usage 'base' also means the upper border where the valves are auscultated.",
    "ias": "Interatrial septum: the wall between the atria, facing forwards and to the right. Its thin central "
           "depression on the right side is the fossa ovalis; the anterior edge abuts the aortic root. "
           "Atrial septal defects (secundum type at the fossa, primum type low near the AV valves, sinus venosus "
           "type near the SVC) cause a left-to-right shunt with fixed splitting of S2.",
    "fossa": "Fossa ovalis: a thin oval depression on the right atrial face of the interatrial septum - the floor is "
             "the fetal septum primum, the raised rim (limbus fossae ovalis) the septum secundum. In the fetus "
             "oxygenated IVC blood crossed here through the foramen ovale into the left atrium. After birth rising "
             "left atrial pressure closes the flap; in ~25% of adults the seal is incomplete (patent foramen "
             "ovale), which can let a venous clot reach the brain (paradoxical embolism).",
    "rau": "Right auricle (right atrial appendage): a broad, triangular muscular pouch projecting forwards and to the "
           "left over the root of the ascending aorta, lined internally by pectinate muscles. Its base is the "
           "embryonic primitive atrium. Surgeons cannulate it for cardiopulmonary bypass.",
    "lau": "Left auricle (left atrial appendage): a long, narrow, hooked finger curling forwards round the left side "
           "of the pulmonary trunk, overlapping the origin of the left coronary artery and circumflex branch. "
           "Its pectinate-lined recess is where >90% of thrombi form in atrial fibrillation - the source of "
           "cardioembolic stroke, hence anticoagulation or appendage occlusion devices.",
    "pectinate": "Pectinate muscles: parallel comb-like muscular ridges on the inner wall of the auricles and the "
                 "anterior (rough) part of the right atrium, running forwards from the crista terminalis. The "
                 "left atrium has them only in its auricle. Blood stagnates between them in atrial fibrillation.",
    "crista": "Crista terminalis: a smooth muscular ridge on the right atrial wall running from the front of the SVC "
              "opening to the front of the IVC opening, dividing the smooth sinus venarum from the pectinate "
              "part. Its external counterpart is the sulcus terminalis. The SA node lies at its upper end, and it "
              "conducts impulses preferentially downwards (a common site of atrial tachycardia).",
    "trabeculae": "Trabeculae carneae: irregular muscular ridges and bridges on the inner walls of the ventricles - "
                  "coarse in the right ventricle, fine and numerous in the left, sparing the smooth outflow tracts. "
                  "They are thought to reduce suction on the endocardium during contraction. Excessive "
                  "trabeculation is seen in LV non-compaction cardiomyopathy.",
    "pap_lv": "Papillary muscles of the left ventricle: two large cones - anterolateral and posteromedial - rising "
              "from the wall below the mitral commissures. Each sends chordae to both mitral cusps and contracts "
              "with the ventricle so the cusps cannot evert into the atrium. The posteromedial muscle has a single "
              "blood supply (posterior interventricular artery) and is the one that ruptures after an inferior "
              "infarct (acute mitral regurgitation, ~3-5 days post-MI).",
    "pap_rv": "Papillary muscles of the right ventricle: anterior (the largest, joined by the moderator band), "
              "posterior (inferior) and a small septal group, tethering the three tricuspid cusps through their "
              "chordae tendineae.",
    "chordae": "Chordae tendineae: fine fibrous cords of collagen covered by endocardium, running from the tips of the "
               "papillary muscles (and, in the RV, straight from the septum) to the free edges and ventricular "
               "surfaces of the atrioventricular valve cusps. Like the rigging of a parachute they stop the cusps "
               "prolapsing into the atria in systole. Rupture (myxomatous degeneration, endocarditis, infarction) "
               "gives a flail leaflet and acute regurgitation.",
    "moderator": "Moderator band (septomarginal trabecula): a muscular bridge crossing the right ventricle from the "
                 "lower septum to the base of the anterior papillary muscle. It carries the right bundle branch, "
                 "a short-cut that lets the anterior papillary muscle contract in time with the wall. A "
                 "landmark that identifies a ventricle as morphologically right on echocardiography.",
    # ---- valves
    "tricuspid": "Tricuspid (right atrioventricular) valve: three cusps - anterior (largest), posterior (inferior) "
                 "and septal - attached to a fibrous annulus, their free edges tethered by chordae tendineae to "
                 "three papillary muscles. It closes at the start of ventricular systole (part of S1). Heard best "
                 "at the left lower sternal border (4th-5th intercostal space). Tricuspid regurgitation follows RV "
                 "dilatation; endocarditis of this valve is typical of intravenous drug use.",
    "mitral": "Mitral (bicuspid, left atrioventricular) valve: an anterior (aortic) cusp, large and in continuity "
              "with the aortic valve, and a posterior (mural) cusp with three scallops, attached to the mitral "
              "annulus and tethered by chordae to two papillary muscles. Closes with S1; heard best at the apex "
              "(left 5th intercostal space, midclavicular line). Mitral stenosis is almost always rheumatic (mid-"
              "diastolic rumble, opening snap, AF); regurgitation causes a pansystolic murmur radiating to the "
              "axilla; mitral valve prolapse gives a mid-systolic click.",
    "aortic": "Aortic valve: three semilunar cusps - right coronary, left coronary and non-coronary (posterior) - each "
              "a pocket attached by a crescentic line to the aortic root, with a nodule (of Arantius) at the centre "
              "of its free edge. Behind each cusp the wall bulges as an aortic sinus (of Valsalva); the right and "
              "left coronary arteries arise from the right and left sinuses and fill in diastole. Closure makes "
              "A2 of the second heart sound. Heard best at the right 2nd intercostal space. Aortic stenosis "
              "(calcific in the elderly, earlier with a bicuspid valve) gives an ejection systolic murmur to the "
              "carotids, angina, syncope and heart failure; regurgitation an early diastolic murmur.",
    "pulmonary": "Pulmonary valve: three semilunar cusps - anterior, right and left - at the top of the "
                 "infundibulum, slightly higher and anterior to the aortic valve, each with a sinus behind it. "
                 "Closure is P2 of the second heart sound (splits from A2 on inspiration). Heard best at the left "
                 "2nd intercostal space. Pulmonary stenosis is usually congenital (part of tetralogy of Fallot).",
    "skeleton": "Fibrous skeleton of the heart: four collagenous rings (annuli fibrosi) around the tricuspid, mitral, "
                "aortic and pulmonary orifices, joined by the right and left fibrous trigones (the right trigone = "
                "central fibrous body). It anchors the valves and the muscle, and it electrically insulates the "
                "atria from the ventricles - the bundle of His is the only normal path through it. Accessory "
                "pathways across it cause pre-excitation (Wolff-Parkinson-White).",
    "membranous": "Membranous part of the interventricular septum: a small thin fibrous area at the top of the "
                  "septum, just below the right and non-coronary aortic cusps, next to the bundle of His. The "
                  "commonest site of ventricular septal defect (perimembranous VSD: harsh pansystolic murmur at "
                  "the left sternal border).",
    "cs_opening": "Opening of the coronary sinus: in the right atrium between the IVC opening and the tricuspid "
                  "orifice, guarded by a thin valve (Thebesian valve). With the tendon of Todaro and the septal "
                  "tricuspid cusp it bounds the triangle of Koch, whose apex marks the AV node.",
    # ---- wall layers & pericardium
    "epi": "Epicardium (visceral layer of serous pericardium): a single layer of mesothelium on loose connective "
           "tissue and fat that covers the heart surface and the roots of the great vessels. The coronary arteries "
           "and veins run in it. At the vessel roots it reflects onto the inner surface of the fibrous pericardium "
           "as the parietal layer. Inflammation (pericarditis) roughens it: sharp pleuritic chest pain eased by "
           "leaning forwards and a friction rub.",
    "myo": "Myocardium: the thick middle layer of branching cardiac muscle cells joined by intercalated discs "
           "(gap junctions make it an electrical syncytium), arranged in spiralling sheets. Thickest in the left "
           "ventricle, thinnest in the atria.",
    "endo": "Endocardium: endothelium (simple squamous epithelium) on a thin subendothelial connective tissue layer, "
            "lining every chamber and covering the valves, papillary muscles and chordae; continuous with the "
            "intima of the great vessels. The Purkinje fibres run in the subendocardial layer. Infective "
            "endocarditis forms vegetations on it, mainly on the valves.",
    "fat": "Epicardial (subepicardial) fat: yellow adipose tissue filling the coronary and interventricular sulci "
           "around the coronary vessels and increasing with age and obesity; it is what makes the sulci look "
           "smooth on a whole heart. On a dissected sheep heart it hides most of the vessels.",
    "fibrous_peri": "Fibrous pericardium: the tough outer bag of dense collagen that encloses the heart, fused to the "
                    "adventitia of the great vessels above and to the central tendon of the diaphragm below, and "
                    "attached to the sternum by sternopericardial ligaments. It is inelastic, so fluid that "
                    "collects quickly compresses the heart (cardiac tamponade). The phrenic nerves run on its "
                    "sides and carry its pain (referred to the shoulder).",
    "parietal": "Parietal layer of serous pericardium: mesothelium lining the inside of the fibrous pericardium, "
                "reflecting onto the heart as the visceral layer (epicardium) around the great vessels (the "
                "reflections form the transverse and oblique pericardial sinuses). Parietal and visceral serous "
                "layers together form a closed sac: the pericardial cavity lies between them, not inside the heart.",
    "cavity": "Pericardial cavity: the potential space between the parietal and visceral layers of serous "
              "pericardium, holding ~15-50 mL of serous fluid that lets the beating heart glide. Rapid "
              "accumulation of blood or fluid causes cardiac tamponade - Beck's triad of hypotension, raised JVP "
              "and muffled heart sounds, plus pulsus paradoxus - treated by pericardiocentesis (needle from the "
              "subxiphoid angle).",
    # ---- great vessels
    "svc": "Superior vena cava: formed behind the right 1st costal cartilage by the two brachiocephalic veins, it "
           "descends to the upper posterior part of the right atrium, receiving the azygos vein; it has no valve. "
           "SVC obstruction (lung cancer, lymphoma) swells the face and arms and dilates chest wall veins.",
    "ivc": "Inferior vena cava: pierces the central tendon of the diaphragm at T8 and after a very short thoracic "
           "course opens into the lower right atrium, guarded by the rudimentary valve of the IVC (Eustachian "
           "valve) that in the fetus steered blood towards the foramen ovale.",
    "pt": "Pulmonary trunk: carries deoxygenated blood (coloured blue by convention) from the right ventricle. It "
          "rises from the pulmonary valve, anterior and then to the left of the ascending aorta, and divides "
          "under the aortic arch at T4-T5 into the right and left pulmonary arteries. Its bifurcation is joined "
          "to the arch by the ligamentum arteriosum. A saddle embolus at the bifurcation is often fatal.",
    "rpa": "Right pulmonary artery: the longer branch, running horizontally to the right behind the ascending aorta "
           "and superior vena cava and in front of the right main bronchus to the hilum of the right lung.",
    "lpa": "Left pulmonary artery: the shorter branch, passing to the left in front of the descending aorta and over "
           "the left main bronchus to the left hilum, joined at its origin to the arch by the ligamentum "
           "arteriosum.",
    "pulm_vein": "Pulmonary vein: returns oxygenated blood (coloured red by convention) from the lung to the left "
                 "atrium - two from each lung (superior and inferior), opening separately into the posterior "
                 "part of the LA with no valves. Their muscular sleeves are the usual trigger of atrial "
                 "fibrillation. Pulmonary veins and arteries are the only veins carrying oxygenated blood, and "
                 "arteries carrying deoxygenated blood, after birth.",
    "asc_aorta": "Ascending aorta: ~5 cm long, rising from the aortic valve behind the pulmonary trunk and to the "
                 "right, inside the pericardium. Its root has the three aortic sinuses (of Valsalva), from which "
                 "the right and left coronary arteries arise. Dilates with hypertension, Marfan syndrome and "
                 "bicuspid valves; type A aortic dissection starts here and can rupture into the pericardium.",
    "arch": "Arch of the aorta: behind the manubrium, it runs backwards and to the left over the left pulmonary "
            "artery and left main bronchus, from the level of the 2nd right sternocostal joint to the left side of "
            "T4. Its three branches, from right to left, are the brachiocephalic trunk, left common carotid and "
            "left subclavian arteries; the ligamentum arteriosum ties its underside to the pulmonary artery, and "
            "the left recurrent laryngeal nerve hooks under it there. Coarctation usually lies just beyond it.",
    "desc_aorta": "Thoracic (descending) aorta: continues the arch from T4 down the left side of the vertebral bodies "
                  "behind the left atrium and oesophagus to the aortic hiatus of the diaphragm at T12, giving "
                  "posterior intercostal, bronchial and oesophageal branches.",
    "bct": "Brachiocephalic trunk: the first and largest arch branch, rising to the right behind the manubrium to "
           "divide behind the right sternoclavicular joint into the right subclavian and right common carotid "
           "arteries.",
    "lcca": "Left common carotid artery: the second arch branch, rising into the neck along the left side of the "
            "trachea (the right one comes from the brachiocephalic trunk). Its sinus holds the baroreceptors of the "
            "carotid reflex.",
    "lsa": "Left subclavian artery: the third arch branch, arching over the apex of the left lung to the arm; its "
           "vertebral and internal thoracic branches matter in subclavian steal and coronary bypass grafting "
           "(the left internal thoracic artery is the usual graft to the LAD).",
    "lig_art": "Ligamentum arteriosum: a fibrous cord from the origin of the left pulmonary artery to the underside "
               "of the aortic arch - the remnant of the fetal ductus arteriosus, which shunted blood from the "
               "pulmonary trunk into the aorta, bypassing the lungs. It closes within days of birth (falling "
               "prostaglandins, rising oxygen). A patent ductus causes a continuous machinery murmur; the left "
               "recurrent laryngeal nerve hooks round it.",
    # ---- coronary arteries
    "lca": "Left coronary artery (left main stem): arises from the left aortic sinus, runs 1-2 cm between the "
           "pulmonary trunk and the left auricle and divides into the anterior interventricular (LAD) and "
           "circumflex arteries. Left main occlusion threatens most of the left ventricle ('widow maker' "
           "territory) and is treated by bypass grafting.",
    "lad": "Anterior interventricular artery (LAD, left anterior descending): runs down the anterior "
           "interventricular sulcus to the apex, often round it onto the diaphragmatic surface, giving diagonal "
           "branches to the anterior LV wall and septal perforators to the anterior two-thirds of the septum "
           "(including the bundle branches). The most commonly occluded coronary artery: anterior MI, ST "
           "elevation in V1-V4; proximal occlusion may cause bundle branch block.",
    "lcx": "Circumflex artery: runs to the left in the coronary sulcus round the obtuse margin to the back of the "
           "heart, supplying the left atrium and lateral/posterior LV wall; it gives the SA nodal artery in ~40% of "
           "people and the posterior interventricular artery in left-dominant hearts (~10%). Occlusion: lateral "
           "MI (ST elevation in I, aVL, V5-V6).",
    "lma": "Left marginal artery (obtuse marginal): branch of the circumflex running down the left (obtuse) border "
           "of the heart over the lateral wall of the left ventricle.",
    "rca": "Right coronary artery: arises from the right (anterior) aortic sinus, runs between the pulmonary trunk "
           "and right auricle into the right coronary sulcus, round the acute margin to the back of the heart. It "
           "supplies the right atrium, right ventricle, the SA node (~60%) and AV node (~80%), and in "
           "right-dominant hearts (~70-80%) the posterior interventricular artery. Occlusion: inferior MI (ST "
           "elevation in II, III, aVF), often with bradycardia or heart block.",
    "rma": "Right marginal artery: branch of the right coronary artery running along the inferior (acute) margin of "
           "the right ventricle towards the apex.",
    "pda": "Posterior interventricular artery (posterior descending): runs in the posterior interventricular sulcus "
           "towards the apex, supplying the posterior third of the septum and the inferior walls of both "
           "ventricles; the artery that decides coronary dominance (from the RCA in most people).",
    # ---- veins
    "cs": "Coronary sinus: a wide venous channel (~2-3 cm long) in the posterior part of the coronary sulcus, "
          "collecting most of the heart's venous blood (great, middle, small and posterior cardiac veins) and "
          "opening into the right atrium. Cardiac resynchronisation pacing leads are passed through it to pace "
          "the left ventricle.",
    "gcv": "Great cardiac vein: begins at the apex, ascends in the anterior interventricular sulcus beside the LAD, "
           "then turns left in the coronary sulcus with the circumflex artery to become the coronary sinus at the "
           "back of the heart.",
    "mcv": "Middle cardiac vein: ascends in the posterior interventricular sulcus beside the posterior "
           "interventricular artery to end in the coronary sinus near its opening.",
    "scv": "Small cardiac vein: runs in the right coronary sulcus with the right coronary artery (often receiving the "
           "right marginal vein) and ends in the coronary sinus near its right atrial end.",
    "pvlv": "Posterior vein of the left ventricle: ascends on the diaphragmatic surface of the left ventricle into "
            "the coronary sinus; a common target branch for a left-ventricular pacing lead.",
    # ---- conduction system
    "sa": "Sinoatrial (SA) node: the pacemaker, a spindle of small specialised myocytes ~1.5 cm long lying just "
          "under the epicardium at the junction of the superior vena cava and right atrium, at the top of the "
          "crista terminalis. Its cells depolarise spontaneously (the 'funny' current If, then Ca2+), 60-100 "
          "times a minute; sympathetic nerves speed it, the vagus slows it. Supplied by the SA nodal artery "
          "(RCA in ~60%). The impulse spreads through both atria - the P wave. Sick sinus syndrome causes "
          "bradycardia and pauses.",
    "internodal": "Internodal pathways and Bachmann's bundle: preferential conduction routes (anterior, middle and "
                  "posterior tracts) of well-aligned atrial muscle carrying the impulse from the SA node to the AV "
                  "node, and Bachmann's bundle across the roof to the left atrium. They are not insulated tracts "
                  "like the His-Purkinje system.",
    "av": "Atrioventricular (AV) node: a compact knot of small conducting cells in the floor of the right atrium, at "
          "the apex of the triangle of Koch (between the coronary sinus opening, tendon of Todaro and septal "
          "tricuspid cusp). It conducts slowly (~0.1 s), delaying the impulse so the atria finish emptying before "
          "the ventricles contract - most of the PR interval. It is the backup pacemaker (junctional rhythm, "
          "40-60/min). First-degree block = PR > 0.2 s; Wenckebach (Mobitz I) is usually nodal. Supplied by the "
          "AV nodal artery (RCA in ~80%), so inferior MI often slows it.",
    "his": "Atrioventricular bundle (bundle of His): continues from the AV node through the central fibrous body - "
           "the only normal electrical connection across the fibrous skeleton - and runs along the crest of the "
           "muscular septum under the membranous septum before dividing into the bundle branches. Disease below "
           "the node (Mobitz II, complete heart block with a slow broad escape rhythm) usually needs a pacemaker.",
    "rbb": "Right bundle branch: a thin cord running down the right side of the interventricular septum and across "
           "the moderator band to the base of the anterior papillary muscle, then spreading into Purkinje fibres of "
           "the right ventricle. Right bundle branch block: broad QRS with RSR' in V1.",
    "lbb": "Left bundle branch: a broad sheet that leaves the His bundle, pierces to the left side of the septum and "
           "fans out under the endocardium into an anterior (superior) fascicle, a posterior (inferior) fascicle "
           "and septal fibres, towards the two papillary muscles. It depolarises the septum from left to right "
           "(the small septal q wave). Left bundle branch block: broad QRS, deep S in V1, notched R in V6 - new "
           "LBBB with chest pain is treated as a myocardial infarction.",
    "purkinje": "Purkinje fibres (subendocardial branches): large, pale, glycogen-rich conducting cells forming a "
                "network under the endocardium of both ventricles, including the papillary muscles and 'false "
                "tendons' crossing the cavity. Conducting at 2-4 m/s, they activate the ventricles from apex to "
                "base and endocardium to epicardium almost at once - the narrow QRS complex. They can pace at "
                "20-40/min as a last-resort escape rhythm.",
}


for _k in ("lv", "rv", "ra", "la"):
    DESC[_k] += " " + DESC["myo"]


# ----------------------------------------------------------------------------------------------- chambers
EPI, ENDO = 0.024, 0.018                 # epicardium (outside H) and endocardium (inside C), exaggerated


def _inlet(key, length=0.34, extra=0.0):
    c, d, r = VEIN_INLETS[key]
    d = unit(d)
    return _cap(c - d * 0.12, c + d * length, r + extra)


def _cone(spec, grow=0.0):
    a, ra, b, rb = spec
    return _cap(a, b, ra + grow, rb + grow)


def _lobes(spec, shrink=0.0, grow=0.0):
    """An auricle: flattened ellipsoids along its path, with a scalloped (crenated) rim."""
    from .sdf import ellipsoid
    pts, widths, thick, out = spec
    path = smooth_path(np.asarray(pts, float), 6 * len(pts))
    w = np.interp(np.linspace(0, 1, len(path)), np.linspace(0, 1, len(widths)), widths)
    t_ = np.interp(np.linspace(0, 1, len(path)), np.linspace(0, 1, len(thick)), thick)
    shapes = []
    for i in range(0, len(path) - 1):
        tan = unit(path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)])
        n = unit(out - tan * np.dot(out, tan))
        bi = np.cross(tan, n)
        L = np.linalg.norm(path[i + 1] - path[i]) * 1.6
        rad = np.array([L + 0.02, w[i], t_[i]]) - shrink + grow
        if np.any(rad <= 0.004):
            continue
        rot = np.stack([tan, bi, n], 1)
        shapes.append(ellipsoid(path[i], rad, rot))
        if shrink == 0.0 and i % 3 == 1:               # crenations on both edges
            for sgn in (-1, 1):
                shapes.append(ellipsoid(path[i] + bi * sgn * w[i] * 0.8, np.array([0.03, 0.03, t_[i] * 0.7]) + grow,
                                        rot))
    return shapes


def septal_plane():
    """Point and normal (right atrium -> left atrium) of the interatrial septum: the bisector of the two atria."""
    from .sdf import ellipsoid
    fr = ellipsoid(RA_C[0], RA_C[1], ROT_B)[0]
    fl = ellipsoid(LA_C[0], LA_C[1], ROT_B)[0]
    best, p0 = 1e9, None
    for t in np.linspace(0, 1, 201):
        p = RA_C[0] * (1 - t) + LA_C[0] * t
        d = abs(float(fr(*[np.float32(v) for v in p])) - float(fl(*[np.float32(v) for v in p])))
        if d < best:
            best, p0 = d, p
    n = unit(LA_C[0] - RA_C[0])
    # the septum faces forwards and to the right: tilt its normal towards the body's left
    n = unit(n + to_heart((0.25, 0.0, -0.1)))
    return p0, n


def chamber_fields(g):
    """Outer surface H, cavity C and the region fields that divide the muscle into named chambers."""
    from .sdf import ellipsoid
    x, y, z = g.x, g.y, g.z
    below_av = np.broadcast_to((y - Y_AV).astype(np.float32), g.shape)
    lvo = g.shapes(_cone(LV_O))
    rvo = g.shapes(_cone(RV_O))
    rv_in = g.shapes(_cone(RV_O, -RV_WALL))

    # ---- cavities
    a_, ra_, b_, rb_ = LV_C
    lvc = np.maximum(g.shapes([_cap(a_, LV_C_MID[0], ra_, LV_C_MID[1]), _cap(LV_C_MID[0], b_, LV_C_MID[1], rb_)]),
                     below_av)
    lvot = g.shapes(_cap((0.14, -0.30, 0.02), AO_C - AO_AX * 0.02, 0.17, AO_R))
    rvc = vmax([rv_in, -lvo, below_av])
    rvot = g.shapes(_chain([RVOT_BASE - (0.02, 0.14, 0.02), RVOT_BASE, (RVOT_BASE + PV_C) / 2 + (0, 0.02, 0.03),
                            PV_C - PV_AX * 0.03], [0.19, 0.16, 0.145, PV_R]))
    p0, n = septal_plane()
    sp = (x - p0[0]) * n[0] + (y - p0[1]) * n[1] + (z - p0[2]) * n[2]      # signed distance to the septal plane
    rac = np.maximum(g.eval(ellipsoid(*RA_C, ROT_B)[0]), sp + IAS_HALF)
    # fossa ovalis: an oval depression pressed into the septum from the right, leaving a thin floor
    up = unit(np.array([0.0, 1.0, 0.0]) - n * n[1])
    side = np.cross(n, up)
    # low on the septum, and centred on the four-chamber plane so the default cut shows its thin floor
    fc = p0 - up * 0.07
    fc = fc + side * ((-0.02 - fc[2]) / side[2] if abs(side[2]) > 1e-3 else 0.0)
    disc = g.eval(ellipsoid(fc, np.array([0.11, 0.09, 0.2]), np.stack([side, up, n], 1))[0])
    rac = np.minimum(rac, vmax([disc, sp - (IAS_HALF - 0.022), -sp - IAS_HALF - 0.01]))
    lac = np.maximum(g.eval(ellipsoid(*LA_C, ROT_B)[0]), -sp + IAS_HALF)
    rauc = g.shapes(_lobes(RAU, ATRIAL_WALL))
    lauc = g.shapes(_lobes(LAU, ATRIAL_WALL))
    tvc = g.shapes(_cap(TV_C + (0.0, 0.16, -0.02), TV_C - (0.0, 0.10, 0.0), TV_R))
    mvc = g.shapes(_cap(MV_C + (0.0, 0.16, -0.03), MV_C - (0.0, 0.10, 0.0), MV_R))
    inlets = g.shapes([_inlet(k) for k in VEIN_INLETS] + [_cap(CS_OSTIUM - CS_DIR * 0.04, CS_OSTIUM + CS_DIR * 0.12,
                                                                   0.035, 0.035)])
    ra_side = vmin([rac, rauc, tvc])
    la_side = vmin([lac, lauc, mvc])
    cav = vmin([lvc, lvot, rvc, rvot, ra_side, la_side, inlets])

    # ---- outer surface
    vent = _smax(smin(lvo, rvo, 0.10), below_av, 0.07)
    # interventricular sulci: a shallow furrow wherever the two ventricles' surfaces meet
    diff = lvo - rvo
    protect = np.clip((cav - 0.05) / 0.05, 0.0, 1.0)
    fade = np.clip((Y_AV - 0.05 - y) / 0.1, 0, 1) * np.clip((y + 0.98) / 0.25, 0, 1)      # none at the apex
    vent = vent + 0.03 * np.exp(-(diff / 0.05) ** 2) * protect * fade
    rao = g.eval(ellipsoid(RA_C[0], RA_C[1] + ATRIAL_WALL, ROT_B)[0])
    lao = g.eval(ellipsoid(LA_C[0], LA_C[1] + ATRIAL_WALL, ROT_B)[0])
    rau = g.shapes(_lobes(RAU))
    lau = g.shapes(_lobes(LAU))
    atria = _smax(smin(rao, lao, 0.10), (Y_AV - 0.07 - y).astype(np.float32), 0.05)
    atria = smin(atria, np.minimum(rau, lau), 0.04)          # the auricles may overhang the ventricles
    body = smin(vent, atria, 0.08)
    # coronary (atrioventricular) sulcus: a furrow circling the heart at the valve plane
    body = body + 0.028 * np.exp(-((y - (Y_AV + 0.035)) / 0.05) ** 2) * protect
    infund = g.shapes(_chain([RVOT_BASE - (0.0, 0.1, 0.0), RVOT_BASE, (RVOT_BASE + PV_C) / 2 + (0, 0.02, 0.03),
                              PV_C], [0.24, RV_WALL + 0.16, RV_WALL + 0.145, PV_R + 0.045]))
    root = g.shapes(_cap((0.10, -0.1, 0.04), AO_C, AO_R + 0.10, AO_R + 0.03))
    H = smin(smin(body, infund, 0.06), root, 0.06)

    # ---- regions (negative inside)
    ventricular = vmin([below_av - 0.02, infund - 0.02, root - 0.02])
    aur = np.minimum(g.shapes(_lobes(RAU, grow=0.03)), g.shapes(_lobes(LAU, grow=0.03)))
    ventricular = np.maximum(ventricular, np.minimum(-aur, vent))      # auricle overhanging a ventricle
    ivs = vmax([lvo, rv_in + 0.01, ventricular, -(rvot - 0.02)])
    lv_side = np.minimum(lvo, lvot - 0.03)
    ias = np.maximum(np.abs(sp) - 0.08, -ventricular)
    rau_r = np.maximum(g.shapes(_lobes(RAU, grow=0.03)), -(rao - 0.01))
    lau_r = np.maximum(g.shapes(_lobes(LAU, grow=0.03)), -(lao - 0.01))
    return dict(H=H, C=cav, lvc=lvc, rvc=rvc, rac=rac, lac=lac, lvo=lvo, rvo=rvo, rv_in=rv_in, lvot=lvot,
                rvot=rvot, ventricular=ventricular, ivs=ivs, lv_side=lv_side, ias=ias, rau=rau_r, lau=lau_r,
                ra_side=ra_side, la_side=la_side, sp=sp, p0=p0, n=n, vent=vent, disc=disc)


def _part(g, d, name, group, color, desc, category="muscle", smooth=0.8, step=1, **kw):
    return Part(name, group, color, g.mesh(d, smooth, step), desc, category=category, clip=kw.pop("clip", True),
                **kw)


def wall_parts(g, F, C2, fossa, memb):
    """Epicardium, endocardium and the myocardium split into its chambers. C2 is the cavity with the papillary
    muscles, trabeculae and pectinate muscles taken out of it, so the endocardium wraps them too."""
    H, C = F["H"], F["C"]
    y, z = g.y, g.z
    myo = np.maximum(H, -C)
    vent, ivs = F["ventricular"], F["ivs"]
    apex = np.broadcast_to((y - (-1.10)).astype(np.float32), g.shape)
    lv = vmax([myo, vent, F["lv_side"], -ivs, -apex])
    rv = vmax([myo, vent, -F["lv_side"], -ivs, -apex, -memb])
    atrial = np.maximum(myo, -vent)
    sep = F["ias"]
    right = np.broadcast_to(F["sp"], g.shape)
    base = np.broadcast_to((z - (-0.31)).astype(np.float32), g.shape)
    lv = np.maximum(lv, -memb)
    sep = np.maximum(sep, -fossa)
    parts = [
        _part(g, vmax([myo, memb]), "Membranous part of interventricular septum", "Ventricles", "#d9c3a5",
              DESC["membranous"], "ligament", smooth=0.7),
        _part(g, vmax([atrial, fossa]), "Fossa ovalis", "Atria", "#c9806a", DESC["fossa"], smooth=0.6),
        _part(g, vmax([lv]), "Left ventricle (myocardium)", "Ventricles", "#8a2f2a", DESC["lv"], step=2),
        _part(g, vmax([myo, ivs, -memb]), "Interventricular septum", "Ventricles", "#7d2a26", DESC["ivs"], step=2),
        _part(g, rv, "Right ventricle (myocardium)", "Ventricles", "#9b3d35", DESC["rv"]),
        _part(g, vmax([myo, vent, apex]), "Apex of heart", "Ventricles", "#842d29", DESC["apex"], step=2),
        _part(g, vmax([atrial, sep]), "Interatrial septum", "Atria", "#a24a3f", DESC["ias"]),
        _part(g, vmax([atrial, -sep, F["rau"]]), "Right auricle", "Atria", "#ab4d41",
              DESC["rau"]),
        _part(g, vmax([atrial, -sep, F["lau"], -F["rau"]]), "Left auricle", "Atria", "#a1463c",
              DESC["lau"]),
        _part(g, vmax([atrial, -sep, right, -F["rau"], -F["lau"]]), "Right atrium (myocardium)", "Atria",
              "#a8483d", DESC["ra"]),
        _part(g, vmax([atrial, -sep, -right, -F["lau"], -F["rau"], -base]), "Left atrium (myocardium)", "Atria",
              "#9c4339", DESC["la"]),
        _part(g, vmax([atrial, -sep, -right, -F["lau"], -F["rau"], base]), "Base of heart (posterior left atrium)",
              "Atria", "#96433a", DESC["base"]),
        _part(g, np.maximum(band(H, 0.0, EPI), -C), "Epicardium (visceral pericardium)", "Heart wall", "#a8483c",
              DESC["epi"],
              "heart", smooth=0.6, rank=1.0),
        _part(g, np.maximum(band(C, -ENDO, 0.0), H), "Endocardium", "Heart wall", "#b9665a", DESC["endo"],
              "heart", smooth=0.6),
    ]
    for p in parts:
        if p.name.startswith("Epicardium"):
            p.mesh = shell_normals(g, p.mesh, H, 0.0, EPI)
        elif p.name == "Endocardium":
            p.mesh = shell_normals(g, p.mesh, C, -ENDO, 0.0)
    return parts


# ----------------------------------------------------------------------------------------------- valves
TV_AX = unit((0.06, -1.0, 0.04))
MV_AX = unit((-0.06, -1.0, 0.03))
# cusps as (name, start, end) angles in degrees, measured in the valve's own frame from +x (towards the septum /
# the left) through +z (anterior)
TV_CUSPS = [("septal", -62, 58, 0.26), ("anterior", 62, 188, 0.30), ("posterior", 192, 294, 0.24)]
MV_CUSPS = [("anterior", 62, 198, 0.31), ("posterior", 202, 418, 0.20)]
AO_CUSPS = [("right coronary", 90), ("left coronary", -30), ("non-coronary", 210)]
PV_CUSPS = [("anterior", 90), ("left", -30), ("right", 210)]


def valve_frame(axis):
    a = unit(axis)
    ref = np.array([1.0, 0.0, 0.0])
    u = unit(ref - a * np.dot(ref, a))
    v = np.cross(a, u)
    if np.dot(v, (0.0, 0.0, 1.0)) < 0:
        v = -v
    return a, u, v


def _dir(u, v, deg):
    t = math.radians(deg)
    return u * math.cos(t) + v * math.sin(t)


def av_closed(C, R, axis, cusps, kind, th=0.016, depth=0.30, belly=0.10):
    """Atrioventricular valve closed (as at the start of systole): cusps hang from a flat annulus and meet along
    their free edges - a three-pointed star for the tricuspid, a curved 'smile' for the mitral, whose coaptation
    line lies close to the posterior annulus because the anterior cusp is the deep one.

    Returns the mesh and, per cusp, its free-edge and rough-zone points (where the chordae insert) with the annulus
    angle of each."""
    a, u, v = valve_frame(axis)
    m = Mesh()
    edges = {}
    ns, nt = 34, 16
    if kind == "mitral":
        c0, c1 = cusps[0][1], cusps[0][2]                       # the two commissures
        P0 = C + R * 0.97 * _dir(u, v, c0)
        P1 = C + R * 0.97 * _dir(u, v, c1)
        M = C + R * 0.30 * _dir(u, v, (c0 + c1) / 2 + 180.0)
        ctrl = 2 * M - (P0 + P1) / 2

        def curve(q):
            q = q[:, None]
            return (1 - q) ** 2 * P0 + 2 * q * (1 - q) * ctrl + q ** 2 * P1
    else:
        centre = C

    for i, (name, t0, t1, _) in enumerate(cusps):
        s = np.linspace(0.0, 1.0, ns)
        deg = t0 + s * (t1 - t0)
        D = np.stack([_dir(u, v, d) for d in deg])
        A = C + R * D
        if kind == "mitral":
            F = curve(s if i == 0 else 1.0 - s)
        else:
            e0, e1 = C + R * 0.97 * _dir(u, v, t0), C + R * 0.97 * _dir(u, v, t1)
            F = np.where((s < 0.5)[:, None], e0 + (centre - e0) * (2 * s)[:, None],
                         centre + (e1 - centre) * (2 * s - 1)[:, None])
            F = F + _dir(u, v, (t0 + t1) / 2) * 0.006        # a hair's gap along the lines of coaptation
        k = np.sin(math.pi * s) ** 0.6
        F = F + a * (R * depth * (0.25 + 0.75 * k))[:, None]
        t = np.linspace(0.0, 1.0, nt)
        S, T = np.meshgrid(s, t, indexing="ij")
        P = A[:, None, :] * (1 - T[..., None]) + F[:, None, :] * T[..., None]
        P = P - a * (R * belly * np.sin(math.pi * T) * np.sin(math.pi * S) ** 0.7)[..., None]
        m.extend(thick_sheet(P, th))
        edges[name] = (P[:, -1, :], P[:, -4, :], deg)
    return m, edges


def semilunar_valve(C, R, axis, cusps, th=0.013):
    """Three pocket-shaped cusps, closed: crescentic attachment on the wall, free edges meeting at the centre."""
    a, u, v = valve_frame(axis)
    m = Mesh()
    ns, nt = 34, 16
    for name, mid in cusps:
        s = np.linspace(0.0, 1.0, ns)
        t0, t1 = mid - 58.0, mid + 58.0
        deg = t0 + s * (t1 - t0)
        D = np.stack([_dir(u, v, d) for d in deg])
        k = np.abs(2 * s - 1)
        h_att = -0.62 * R + 0.95 * R * k ** 1.7
        A = C + a[None] * h_att[:, None] + R * D
        # free edge: from one commissure straight in to the centre and out to the other (lines of coaptation)
        d0, d1 = _dir(u, v, t0), _dir(u, v, t1)
        rad = np.where(s < 0.5, 1 - 2 * s, 2 * s - 1)[:, None] * R
        Fd = np.where((s < 0.5)[:, None], d0[None], d1[None]) * rad
        inward = _dir(u, v, mid) * 0.005            # a hair's gap along the coaptation lines
        F = C + a[None] * (0.26 * R + 0.06 * R * (1 - k))[:, None] + Fd + inward
        t = np.linspace(0.0, 1.0, nt)
        S, T = np.meshgrid(s, t, indexing="ij")
        P = A[:, None, :] * (1 - T[..., None]) + F[:, None, :] * T[..., None]
        P = P - a * (0.30 * R * np.sin(math.pi * T) ** 0.9 * np.sin(math.pi * S) ** 0.8)[..., None]
        m.extend(thick_sheet(P, th))
        # nodule of Arantius at the middle of the free edge
        m.extend(ell_mesh(C + a * 0.30 * R + inward, (0.018, 0.018, 0.018), res=8))
    return m


def annulus_ring(C, R, axis, r, n=72, wave=0.0):
    a, u, v = valve_frame(axis)
    ang = np.linspace(0, 2 * math.pi, n, endpoint=False)
    pts = C + R * (np.cos(ang)[:, None] * u + np.sin(ang)[:, None] * v) + a * (wave * np.cos(3 * ang))[:, None]
    pts = np.vstack([pts, pts[:1]])
    return tube(pts, r, 10, caps=False)


def chordae(tip, targets, rng, r=0.0055):
    """Chordae from a papillary head: first-order cords split once on their way to the cusp."""
    m = Mesh()
    targets = np.asarray(targets)
    for i in range(0, len(targets) - 1, 2):
        p1, p2 = targets[i], targets[i + 1]
        start = tip + rng.normal(0, 0.012, 3)
        fork = start + (0.5 * (p1 + p2) - start) * rng.uniform(0.55, 0.72)
        m.extend(tube(np.linspace(start, fork, 6), r * 1.25, 6, caps=True))
        for p in (p1, p2):
            m.extend(tube(np.linspace(fork, p, 6), r, 6, caps=True))
    return m


# ----------------------------------------------------------------------------------------------- chamber interiors
def papillary_layout(lv_s, rv_s, sept_s):
    """Papillary muscles: (name, base on the wall, tip under the commissure it serves, base radius)."""
    a, u, v = valve_frame(MV_AX)
    al_comm = MV_C + MV_R * 0.72 * _dir(u, v, 60)
    pm_comm = MV_C + MV_R * 0.72 * _dir(u, v, 200)
    lvb = np.asarray(LV_O[2])

    def base(surf, p, lift=0.03):
        return surf.snap(p, lift)[0][0]
    lv = [("anterolateral", base(lv_s, lvb + (0.30, -0.58, 0.10)), al_comm + a * 0.44, 0.09),
          ("posteromedial", base(lv_s, lvb + (0.00, -0.60, -0.24)), pm_comm + a * 0.44, 0.085)]
    a, u, v = valve_frame(TV_AX)
    rvb = np.asarray(RV_O[2])
    rv = [("anterior", base(rv_s, rvb + (-0.40, -0.55, 0.02)), TV_C + TV_R * 0.7 * _dir(u, v, 150) + a * 0.36, 0.07),
          ("posterior", base(rv_s, rvb + (-0.18, -0.48, -0.30)), TV_C + TV_R * 0.7 * _dir(u, v, 245) + a * 0.34,
           0.055),
          ("septal", base(sept_s, TV_C + (0.18, -0.12, 0.10), 0.02), TV_C + TV_R * 0.7 * _dir(u, v, 20) + a * 0.18,
           0.035)]
    return lv, rv


def papillary_shapes(entries, rng):
    shapes = []
    for name, base, tip, rb in entries:
        shapes.append(_cap(base, tip, rb, rb * 0.45))
        axis = unit(tip - base)
        for k in range(2 if rb < 0.05 else 3):       # the tip splits into two or three heads
            off = rng.normal(0, 1, 3)
            off -= axis * np.dot(off, axis)
            off = unit(off) * rb * 0.35
            shapes.append(_cap(tip - axis * 0.08, tip + off + axis * 0.02, rb * 0.4, rb * 0.25))
    return shapes


def trabeculae_shapes(surfaces, rng):
    """Muscular ridges and bridges on the ventricular walls: coarse in the RV, fine and many in the LV. The outflow
    tracts and the upper septum stay smooth."""
    shapes = []
    for surf, count, rad, keep in surfaces:
        cand = np.nonzero(keep(surf.pos))[0]
        for i in rng.choice(cand, size=min(count, len(cand)), replace=False):
            p, nrm = surf.pos[i], surf.nrm[i]                     # nrm points into the wall
            along = np.array([0.0, 1.0, 0.0]) - nrm * nrm[1]
            side = np.cross(nrm, along)
            ang = rng.uniform(-1.0, 1.0)
            t = unit(unit(along) * math.cos(ang) + unit(side) * math.sin(ang))
            L = rng.uniform(0.10, 0.24)
            rr = rng.uniform(*rad)
            a, _ = surf.snap(p - t * L / 2, -(ENDO + rr * 0.35))
            b, _ = surf.snap(p + t * L / 2, -(ENDO + rr * 0.35))
            mid = (a[0] + b[0]) / 2 - nrm * (rng.uniform(0.0, 0.03) if rng.random() < 0.25 else 0.0)
            shapes.append(_cap(a[0], mid, rr, rr * 0.85))
            shapes.append(_cap(mid, b[0], rr * 0.85, rr))
    return shapes


def crista_path(ra_s):
    svc = VEIN_INLETS["svc"][0]
    ivc = VEIN_INLETS["ivc"][0]
    lateral = to_heart((-1.0, 0.0, 0.35))
    c = RA_C[0]
    ctrl = [svc + lateral * 0.10 - VEIN_INLETS["svc"][1] * 0.05, c + lateral * 0.35 + (svc - c) * 0.35,
            c + lateral * 0.35, c + lateral * 0.35 + (ivc - c) * 0.4, ivc + lateral * 0.12]
    return ra_s.path(ctrl, -(ENDO + 0.012), samples=40)


def pectinate_shapes(ra_s, crista, rng):
    """Crista terminalis on the lateral RA wall, pectinate muscles combing forwards from it, and pectinate ridges
    lining both auricles."""
    crista_shapes = [_cap(crista[i], crista[i + 1], 0.034, 0.034) for i in range(len(crista) - 1)]
    pect = []
    fwd = to_heart(unit((0.35, -0.1, 1.0)))              # towards the auricle and the tricuspid orifice
    for i in range(3, len(crista) - 3, 3):
        p = crista[i]
        ctrl = [p, p + fwd * 0.12 + rng.normal(0, 0.015, 3), p + fwd * 0.26 + rng.normal(0, 0.03, 3)]
        path = ra_s.path(ctrl, -(ENDO + 0.008), samples=12)
        for k in range(len(path) - 1):
            r = 0.024 * (1 - 0.4 * k / len(path))
            pect.append(_cap(path[k], path[k + 1], r, r * 0.95))
    for spec, wall in ((RAU, ATRIAL_WALL), (LAU, ATRIAL_WALL)):
        pts, widths, thick, out = spec
        sp = smooth_path(np.asarray(pts, float), 30)
        w = np.interp(np.linspace(0, 1, len(sp)), np.linspace(0, 1, len(widths)), widths) - wall
        th = np.interp(np.linspace(0, 1, len(sp)), np.linspace(0, 1, len(thick)), thick) - wall
        for i in range(2, len(sp) - 3, 3):
            tan = unit(sp[i + 1] - sp[i - 1])
            n = unit(out - tan * np.dot(out, tan))
            bi = np.cross(tan, n)
            ang = np.linspace(0.25, 2 * math.pi - 0.25, 16) + rng.uniform(0, 1)
            ring = [sp[i] + bi * math.cos(t) * (w[i] - ENDO) + n * math.sin(t) * max(th[i] - ENDO, 0.01) for t in ang]
            for k in range(len(ring) - 1):
                pect.append(_cap(ring[k], ring[k + 1], 0.016, 0.016))
    return crista_shapes, pect


def moderator_band(sept_s, rv_pap):
    ant_base, ant_tip = rv_pap[0][1], rv_pap[0][2]
    s, _ = sept_s.snap(np.asarray(RV_O[2]) + (-0.02, -0.42, -0.02), 0.01)
    s = s[0]
    e = ant_base + (ant_tip - ant_base) * 0.2
    mid = (s + e) / 2 + np.array([0.0, 0.04, 0.0])
    return [_cap(s, mid, 0.032, 0.026), _cap(mid, e, 0.026, 0.034)], np.array([s, mid, e])


def _ang_near(a, b, tol):
    return abs((a - b + 180.0) % 360.0 - 180.0) < tol


def _chordae_for(tip, edges, cusp_names, comm, rng, tol=58.0):
    targets = []
    for name in cusp_names:
        free, rough, ang = edges[name]
        for i in range(0, len(ang), 2):
            if _ang_near(ang[i], comm, tol):
                targets.append(free[i] if (i // 2) % 2 == 0 else rough[i])
    if len(targets) % 2:
        targets = targets[:-1]
    return chordae(tip, targets, rng)


def interior_parts(g, F, rng):
    C = F["C"]
    lv_s = Surface(g.mesh(F["lvc"], 0.8, 2))
    rv_s = Surface(g.mesh(F["rvc"], 0.8, 2))
    ra_s = Surface(g.mesh(F["rac"], 0.8, 2))
    sept_s = Surface(g.mesh(F["lvo"], 0.8, 2))
    lvp, rvp = papillary_layout(lv_s, rv_s, sept_s)
    pap_lv = g.shapes(papillary_shapes(lvp, rng))
    pap_rv = g.shapes(papillary_shapes(rvp, rng))
    lvb = np.asarray(LV_O[2])

    def keep_lv(p):
        septal = (p[:, 0] < lvb[0] - 0.12) & (p[:, 1] > -0.45)
        return (p[:, 1] < -0.05 + 0.05 * np.sin(p[:, 2] * 20)) & ~septal

    def keep_rv(p):
        return (p[:, 1] < -0.10) & (np.linalg.norm(p - RVOT_BASE, axis=1) > 0.22)
    trab = g.shapes(trabeculae_shapes([(lv_s, 120, (0.009, 0.015), keep_lv), (rv_s, 70, (0.015, 0.026), keep_rv)],
                                      rng))
    cr = crista_path(ra_s)
    cr_shapes, pe_shapes = pectinate_shapes(ra_s, cr, rng)
    crista = g.shapes(cr_shapes)
    pect = g.shapes(pe_shapes)
    mod_shapes, mod_path = moderator_band(sept_s, rvp)
    moder = g.shapes(mod_shapes)
    inner = vmin([pap_lv, pap_rv, trab, crista, pect, moder])
    C2 = np.maximum(C, -inner)
    C = C + ENDO                                        # interior structures stand on the endocardium
    grp = "Chamber interior"
    parts = [
        _part(g, np.maximum(pap_lv, C), "Papillary muscles (left ventricle)", grp, "#973a33", DESC["pap_lv"],
              smooth=0.7),
        _part(g, np.maximum(pap_rv, C), "Papillary muscles (right ventricle)", grp, "#a0423a", DESC["pap_rv"],
              smooth=0.7),
        _part(g, vmax([moder, C, -pap_rv]), "Moderator band (septomarginal trabecula)", grp, "#a5463c",
              DESC["moderator"], smooth=0.7),
        _part(g, vmax([trab, C, -pap_lv, -pap_rv, -moder]), "Trabeculae carneae", grp, "#8f362f", DESC["trabeculae"],
              smooth=0.6),
        _part(g, np.maximum(crista, C), "Crista terminalis", grp, "#a94c40", DESC["crista"], smooth=0.7),
        _part(g, vmax([pect, C, -crista]), "Pectinate muscles", grp, "#b0543f", DESC["pectinate"], smooth=0.6),
    ]
    # ---- valves and their tethers
    tv, tv_edges = av_closed(TV_C, TV_R * 0.98, TV_AX, TV_CUSPS, "tricuspid")
    mv, mv_edges = av_closed(MV_C, MV_R * 0.98, MV_AX, MV_CUSPS, "mitral")
    ch = Mesh()
    tips = {n: tip for n, b, tip, r in lvp + rvp}
    ch.extend(_chordae_for(tips["anterolateral"], mv_edges, ["anterior", "posterior"], 60, rng))
    ch.extend(_chordae_for(tips["posteromedial"], mv_edges, ["anterior", "posterior"], 200, rng))
    ch.extend(_chordae_for(tips["anterior"], tv_edges, ["anterior", "posterior"], 190, rng))
    ch.extend(_chordae_for(tips["posterior"], tv_edges, ["posterior", "septal"], 296, rng))
    ch.extend(_chordae_for(tips["septal"], tv_edges, ["septal", "anterior"], 60, rng, tol=40))
    vg = "Valves"
    parts += [
        Part("Tricuspid valve", vg, "#e3cbb0", tv, DESC["tricuspid"], category="ligament", clip=True),
        Part("Mitral (bicuspid) valve", vg, "#e6cfb2", mv, DESC["mitral"], category="ligament", clip=True),
        Part("Chordae tendineae", vg, "#f1e6d2", ch, DESC["chordae"], category="tendon", clip=True),
        Part("Aortic valve", vg, "#e8d3b6", semilunar_valve(AO_C, AO_R * 0.97, AO_AX, AO_CUSPS), DESC["aortic"],
             category="ligament", clip=True),
        Part("Pulmonary valve", vg, "#e5cfb4", semilunar_valve(PV_C, PV_R * 0.97, PV_AX, PV_CUSPS), DESC["pulmonary"],
             category="ligament", clip=True),
    ]
    sk = Mesh()
    sk.extend(annulus_ring(TV_C, TV_R + 0.012, TV_AX, 0.018))
    sk.extend(annulus_ring(MV_C, MV_R + 0.012, MV_AX, 0.02))
    sk.extend(annulus_ring(AO_C - AO_AX * 0.02, AO_R + 0.012, AO_AX, 0.02, wave=0.05))
    sk.extend(annulus_ring(PV_C - PV_AX * 0.02, PV_R + 0.012, PV_AX, 0.016, wave=0.045))
    cfb = (AO_C - AO_AX * 0.06) * 0.45 + MV_C * 0.3 + TV_C * 0.25
    sk.extend(ell_mesh(cfb, (0.06, 0.035, 0.05), res=12))
    parts.append(Part("Fibrous skeleton (valve annuli)", vg, "#efe4cf", sk, DESC["skeleton"], category="ligament",
                      clip=True))
    oc, _ = ra_s.snap(CS_OSTIUM, -0.004)
    parts.append(Part("Opening of coronary sinus", "Chamber interior", "#e7c9b5",
                      annulus_ring(oc[0], 0.042, CS_DIR, 0.011), DESC["cs_opening"], category="ligament", clip=True))
    return parts, C2, dict(lvp=lvp, rvp=rvp, crista=cr, moderator=mod_path, cfb=cfb,
                           surfs=(lv_s, rv_s, ra_s, sept_s))


# ----------------------------------------------------------------------------------------------- great vessels
# Centrelines in body coordinates (x left, y up, z forwards), pulled into the heart frame when used.
AORTA_B = [AO_B - to_body(AO_AX) * 0.03, AO_B + np.array([-0.10, 0.28, 0.08]),
           [-0.46, 0.84, 0.12], [-0.42, 1.08, 0.08], [-0.24, 1.23, 0.00], [-0.02, 1.26, -0.18], [0.15, 1.18, -0.40],
           [0.22, 1.00, -0.64], [0.24, 0.70, -0.80], [0.22, 0.10, -0.84], [0.20, -0.62, -0.80]]
AORTA_R = [0.165, 0.19, 0.19, 0.185, 0.175, 0.17, 0.165, 0.16, 0.155, 0.15, 0.145]
AO_SPLIT = (3, 7)                         # control points where ascending -> arch -> descending
BRANCHES_B = {
    "bct": ([[-0.22, 1.20, 0.04], [-0.34, 1.42, 0.10], [-0.44, 1.64, 0.13]], [0.10, 0.092, 0.088]),
    "lcca": ([[-0.04, 1.24, -0.08], [-0.05, 1.48, -0.05], [-0.04, 1.70, -0.02]], [0.065, 0.06, 0.058]),
    "lsa": ([[0.11, 1.20, -0.27], [0.19, 1.44, -0.28], [0.32, 1.63, -0.25]], [0.075, 0.07, 0.068]),
}
PT_B = [PV_B - to_body(PV_AX) * 0.03, PV_B + np.array([0.10, 0.22, -0.10]), [0.14, 0.88, -0.08]]
PA_B = {
    "rpa": ([[0.14, 0.88, -0.08], [-0.12, 0.93, -0.20], [-0.42, 0.91, -0.34], [-0.68, 0.88, -0.38],
             [-0.94, 0.84, -0.38]], [0.13, 0.125, 0.12, 0.115, 0.11]),
    "lpa": ([[0.14, 0.88, -0.08], [0.32, 0.93, -0.14], [0.52, 0.91, -0.22], [0.78, 0.85, -0.26]],
            [0.125, 0.12, 0.115, 0.11]),
}
LIG_ART_B = ([0.18, 0.98, -0.12], [0.16, 1.04, -0.33])
VWALL = 0.028                            # great vessel wall (exaggerated)


def _vessel(pts_body, radii, per=10, extend=(0.0, 0.0)):
    """Round-cone chain along a body-frame centreline: (outer shapes, lumen shapes, heart-frame path)."""
    path = smooth_path(to_heart(pts_body), per * len(pts_body))
    radii = np.broadcast_to(np.asarray(radii, float), (len(pts_body),))
    radii = np.interp(np.linspace(0, 1, len(path)), np.linspace(0, 1, len(radii)), radii)
    outer = [_cap(path[i], path[i + 1], radii[i], radii[i + 1]) for i in range(len(path) - 1)]
    lp = path.copy()
    lp[0] = lp[0] - unit(path[1] - path[0]) * extend[0]           # lumens run out through open ends
    lp[-1] = lp[-1] + unit(path[-1] - path[-2]) * extend[1]
    ri = radii - VWALL
    lumen = [_cap(lp[i], lp[i + 1], ri[i], ri[i + 1]) for i in range(len(lp) - 1)]
    return outer, lumen, path


def _sinuses(C, R, axis, cusps, grow=0.0):
    """The aortic / pulmonary sinuses: a bulge of the root wall behind each cusp."""
    from .sdf import sphere
    a, u, v = valve_frame(axis)
    return [sphere(C + a * 0.25 * R + _dir(u, v, mid) * 0.42 * R, 0.66 * R + grow) for _, mid in cusps]


def vessel_specs():
    ao_o, ao_l, ao_p = _vessel(AORTA_B, AORTA_R, extend=(0.14, 0.08))
    ao_o += _sinuses(AO_C, AO_R, AO_AX, AO_CUSPS, VWALL)
    ao_l += _sinuses(AO_C, AO_R, AO_AX, AO_CUSPS)
    pt_o, pt_l, pt_p = _vessel(PT_B, [0.16, 0.165, 0.15], extend=(0.14, 0.0))
    pt_o += _sinuses(PV_C, PV_R, PV_AX, PV_CUSPS, VWALL)
    pt_l += _sinuses(PV_C, PV_R, PV_AX, PV_CUSPS)
    V = {"aorta": (ao_o, ao_l, ao_p), "pt": (pt_o, pt_l, pt_p)}
    for k, (pts, r) in BRANCHES_B.items():
        V[k] = _vessel(pts, r, extend=(0.05, 0.06))
    for k, (pts, r) in PA_B.items():
        V[k] = _vessel(pts, r, extend=(0.05, 0.06))
    for k, (pts, r) in VEINS_B.items():
        V[k] = _vessel(pts, [r] * len(pts), extend=(0.06, 0.2) if k == "svc" else (0.2, 0.06))
    return V


def shapes_bbox(shapes):
    return np.min([s[1] for s in shapes], axis=0), np.max([s[2] for s in shapes], axis=0)


def _plane(g, p, n):
    n = unit(n)
    return np.broadcast_to(((g.x - p[0]) * n[0] + (g.y - p[1]) * n[1] + (g.z - p[2]) * n[2]).astype(np.float32),
                           g.shape)


def vessel_parts(g, H, V):
    fld = {k: (g.shapes(o), g.shapes(l)) for k, (o, l, p) in V.items()}
    lumen = vmin([l for o, l in fld.values()])
    outside_heart = EPI - H                  # vessel walls stop at the epicardium
    ao_o = fld["aorta"][0]
    pt_o = fld["pt"][0]
    ap = V["aorta"][2]
    per = len(ap) // len(AORTA_B)
    i3, i7 = AO_SPLIT[0] * per, AO_SPLIT[1] * per
    cut3 = _plane(g, ap[i3], ap[i3 + 1] - ap[i3 - 1])
    cut7 = _plane(g, ap[i7], ap[i7 + 1] - ap[i7 - 1])
    asc_o = g.shapes(_vessel(AORTA_B[:AO_SPLIT[0] + 2], AORTA_R[:AO_SPLIT[0] + 2])[0]
                     + _sinuses(AO_C, AO_R, AO_AX, AO_CUSPS, VWALL))
    arch_o = g.shapes(_vessel(AORTA_B[AO_SPLIT[0] - 1:AO_SPLIT[1] + 2], AORTA_R[AO_SPLIT[0] - 1:AO_SPLIT[1] + 2])[0])
    desc_o = g.shapes(_vessel(AORTA_B[AO_SPLIT[1] - 1:], AORTA_R[AO_SPLIT[1] - 1:])[0])
    wall = lambda o: vmax([o, -lumen, outside_heart])                       # noqa: E731
    gv = "Great vessels"
    A, Vn = "#c63a33", "#3d5bb0"
    P = "#4a66c0"
    parts = [
        _part(g, vmax([wall(asc_o), cut3]), "Ascending aorta", gv, A, DESC["asc_aorta"], "artery"),
        _part(g, vmax([wall(arch_o), -cut3, cut7]), "Arch of aorta", gv, A, DESC["arch"], "artery"),
        _part(g, vmax([wall(desc_o), -cut7]), "Thoracic (descending) aorta", gv, "#bf3730", DESC["desc_aorta"],
              "artery"),
        _part(g, vmax([wall(fld["bct"][0]), -ao_o]), "Brachiocephalic trunk", gv, "#cc423a", DESC["bct"], "artery"),
        _part(g, vmax([wall(fld["lcca"][0]), -ao_o]), "Left common carotid artery", gv, "#cc423a", DESC["lcca"],
              "artery"),
        _part(g, vmax([wall(fld["lsa"][0]), -ao_o]), "Left subclavian artery", gv, "#cc423a", DESC["lsa"], "artery"),
        _part(g, wall(pt_o), "Pulmonary trunk", gv, P, DESC["pt"], "artery"),
        _part(g, vmax([wall(fld["rpa"][0]), -pt_o]), "Right pulmonary artery", gv, "#4f6cc4", DESC["rpa"], "artery"),
        _part(g, vmax([wall(fld["lpa"][0]), -pt_o]), "Left pulmonary artery", gv, "#4f6cc4", DESC["lpa"], "artery"),
        _part(g, wall(fld["svc"][0]), "Superior vena cava", gv, Vn, DESC["svc"], "vein"),
        _part(g, wall(fld["ivc"][0]), "Inferior vena cava", gv, Vn, DESC["ivc"], "vein"),
    ]
    for k, name in (("rspv", "Right superior pulmonary vein"), ("ripv", "Right inferior pulmonary vein"),
                    ("lspv", "Left superior pulmonary vein"), ("lipv", "Left inferior pulmonary vein")):
        parts.append(_part(g, wall(fld[k][0]), name, gv, "#c9544a", DESC["pulm_vein"], "vein"))
    a, b = to_heart(LIG_ART_B[0]), to_heart(LIG_ART_B[1])
    lig = vmax([g.shapes(_cap(a, b, 0.024, 0.02)), -ao_o, -fld["lpa"][0], -pt_o])
    parts.append(_part(g, lig, "Ligamentum arteriosum", gv, "#d9c9a8", DESC["lig_art"], "ligament", smooth=0.6))
    outers = vmin([o for o, l in fld.values()])
    return parts, outers, lumen, fld


# ----------------------------------------------------------------------------------------------- pericardium
PERI_GAP, PARIETAL, FIBROUS = 0.05, 0.04, 0.05


def pericardium_parts(g, H, V, outers):
    """The pericardial sac, opened by a window over the front of the heart. Its layers are stepped at the edge of the
    window - fibrous cut back furthest, the parietal serous layer showing as a lip inside it - so all of them read."""
    roots = []
    for k, frac, from_end in (("aorta", 0.2, False), ("pt", 0.8, False), ("svc", 0.45, True), ("ivc", 0.5, False),
                              ("rspv", 0.35, False), ("ripv", 0.35, False), ("lspv", 0.35, False),
                              ("lipv", 0.35, False)):
        o = V[k][0]
        n = max(int(len(o) * frac), 1)
        roots += o[-n:] if from_end else o[:n]
    root_f = g.shapes(roots)
    S = smin(H - (EPI + PERI_GAP), root_f - PERI_GAP * 0.6, 0.12)
    body_z = np.broadcast_to((g.x * R_BODY[2, 0] + g.y * R_BODY[2, 1] + g.z * R_BODY[2, 2]).astype(np.float32),
                             g.shape)
    inside_vessel = -outers
    fib = vmax([band(S, PARIETAL, PARIETAL + FIBROUS), inside_vessel, body_z - 0.0])
    par = vmax([band(S, 0.0, PARIETAL), inside_vessel, body_z - 0.07])
    cav = vmax([S, EPI - H, -outers, body_z - 0.0])
    grp = "Pericardium"
    parts = [
        _part(g, fib, "Fibrous pericardium", grp, "#d8c8a4", DESC["fibrous_peri"], "fascia", smooth=0.8, step=2),
        _part(g, par, "Parietal layer of serous pericardium", grp, "#e2aea0", DESC["parietal"], "serosa",
              smooth=0.7, step=2),
        Part("Pericardial cavity", grp, "#9fd0f0", g.mesh(cav, 0.9, 2), DESC["cavity"], alpha=0.28, category="csf",
             clip=True),
    ]
    parts[0].mesh = shell_normals(g, parts[0].mesh, S, PARIETAL, PARIETAL + FIBROUS)
    parts[1].mesh = shell_normals(g, parts[1].mesh, S, 0.0, PARIETAL)
    return parts


# ----------------------------------------------------------------------------------------------- field sampling
def sample(g, d, pts):
    """Trilinear sample of a grid field at heart-frame points (BIG outside the grid)."""
    from scipy.ndimage import map_coordinates
    pts = np.atleast_2d(np.asarray(pts, float))
    idx = ((pts - g.vol.lo) / g.voxel).T
    return map_coordinates(d, idx, order=1, mode="constant", cval=BIG)


def ray_hits(g, d, origins, dirs, lift=0.0, reach=1.6, n=400):
    """First crossing of d = 0 on rays cast inwards from origin + dir * reach; lifted outwards by `lift`."""
    origins = np.atleast_2d(np.asarray(origins, float))
    dirs = np.atleast_2d(np.asarray(dirs, float))
    dirs = dirs / np.linalg.norm(dirs, axis=1, keepdims=True)
    t = np.linspace(reach, 0.0, n)
    P = origins[:, None, :] + dirs[:, None, :] * t[None, :, None]
    v = sample(g, d, P.reshape(-1, 3)).reshape(len(origins), n)
    hit = np.argmax(v < 0, axis=1)
    ok = v[np.arange(len(origins)), hit] < 0
    th = t[hit]
    return origins + dirs * (th + lift)[:, None], ok


# ----------------------------------------------------------------------------------------------- coronary vessels
AXIS_C = np.array([-0.04, 0.0, 0.03])     # the ventricles' long axis (x, -, z), for casting rays round the heart


def _ring(g, vent, y, angles, lift, keep_misses=False):
    angles = np.atleast_1d(np.asarray(angles, float))
    o = np.stack([np.full_like(angles, AXIS_C[0]), np.full_like(angles, y), np.full_like(angles, AXIS_C[2])], 1)
    d = np.stack([np.cos(angles), np.zeros_like(angles), np.sin(angles)], 1)
    p, ok = ray_hits(g, vent, o, d, lift)
    if keep_misses:
        p[~ok] = np.nan
        return p
    return p[ok]


def sulci(g, vent):
    """The interventricular sulci, traced where the two ventricular cones meet on the surface: returns the anterior
    and posterior sulcus as top-to-bottom polylines, and the angle of each at every level."""
    fl, fr = _cone(LV_O)[0], _cone(RV_O)[0]
    ang = np.linspace(-math.pi, math.pi, 360, endpoint=False)
    ant, post = [], []
    for y in np.linspace(Y_AV - 0.02, -1.02, 44):
        p = _ring(g, vent, y, ang, 0.0, keep_misses=True)
        if np.isnan(p).any():
            continue
        diff = fl(*p.T.astype(np.float32)) - fr(*p.T.astype(np.float32))
        sgn = np.sign(diff)
        idx = np.nonzero(sgn != np.roll(sgn, -1))[0]
        for i in idx:
            a = ang[i]
            (ant if math.sin(a) > -0.15 else post).append((y, a))
    def line(lst, front):
        lst = sorted(lst, key=lambda t: -t[0])
        ys = sorted(set(round(t[0], 5) for t in lst), reverse=True)
        out = []
        for y in ys:
            c = [a for yy, a in lst if round(yy, 5) == y]
            out.append((y, max(c, key=lambda a: math.sin(a)) if front else min(c, key=lambda a: math.sin(a))))
        return out
    return line(ant, True), line(post, False)


def _smooth_angles(pairs, k=5):
    ys = np.array([p[0] for p in pairs])
    a = np.unwrap(np.array([p[1] for p in pairs]))
    if len(a) > k:
        a = np.convolve(np.pad(a, k // 2, mode="edge"), np.ones(k) / k, mode="valid")
    return ys, a


def _on_ring(g, vent, ys, angs, lift):
    pts = [_ring(g, vent, y, np.array([a]), lift) for y, a in zip(ys, angs)]
    pts = np.array([p[0] for p in pts if len(p)])
    # drop anything that jumps away from its neighbours (a ray that grazed a different surface)
    keep = [0]
    for i in range(1, len(pts)):
        if np.linalg.norm(pts[i] - pts[keep[-1]]) < 0.25:
            keep.append(i)
    return pts[keep]


def coronary_layout(g, vent, H):
    """Centrelines of the coronary arteries and cardiac veins on the ventricular surface (heart frame)."""
    ant, post = sulci(g, vent)
    ya, aa = _smooth_angles(ant)
    yp, ap = _smooth_angles(post)
    L = {}
    lift_a, lift_v = 0.02, 0.024
    # coronary sulcus: a full ring just above the ventricular base
    ring_ang = np.linspace(-math.pi, math.pi, 181)
    a_top, p_top = aa[0], ap[0]

    def arc(a0, a1, lift, y=Y_AV - 0.005, n=60):
        a = np.linspace(a0, a1, n)
        return _ring(g, vent, y, a, lift)

    # which way round is "right"? the right side of the heart frame is -x, i.e. angles near pi
    def towards_right(a0, a1):
        """Shortest arc from a0 to a1 that passes the -x side."""
        d = (a1 - a0) % (2 * math.pi)
        mid = a0 + d / 2
        return (a0, a0 + d) if math.cos(mid) < 0 else (a0, a0 - (2 * math.pi - d))

    r0, r1 = towards_right(a_top, p_top)
    l0, l1 = (a_top, a_top - (r1 - r0) / abs(r1 - r0) * (2 * math.pi - abs(r1 - r0)))
    ao_a, ao_u, ao_v = valve_frame(AO_AX)
    rca_origin = AO_C + ao_a * 0.30 * AO_R + _dir(ao_u, ao_v, 90) * (AO_R + VWALL + 0.03)
    lca_origin = AO_C + ao_a * 0.30 * AO_R + _dir(ao_u, ao_v, -30) * (AO_R + VWALL + 0.03)
    # right coronary artery: out of the right sinus, down into the right coronary sulcus, round the acute margin
    rca_ring = arc(r0 + (r1 - r0) * 0.10, r1, lift_a)
    L["rca"] = np.vstack([rca_origin[None], (rca_origin + rca_ring[0]) / 2 + (0.0, 0.0, 0.04), rca_ring])
    # posterior interventricular artery from the crux two-thirds of the way to the apex
    n_pda = int(len(yp) * 0.72)
    L["pda"] = _on_ring(g, vent, yp[:n_pda], ap[:n_pda], lift_a)
    # right marginal artery along the acute margin
    am = r0 + (r1 - r0) * 0.52
    ys = np.linspace(Y_AV - 0.01, -0.62, 16)
    L["rma"] = _on_ring(g, vent, ys, np.full_like(ys, am) + np.linspace(0, 0.25, 16) * np.sign(l1 - l0), lift_a)
    # left coronary artery: short left main between the pulmonary trunk and left auricle, then LAD and circumflex
    bif = _ring(g, vent, Y_AV - 0.005, np.array([a_top + 0.12 * np.sign(l1 - l0)]), lift_a)[0]
    L["lca"] = smooth_path(np.array([lca_origin, (lca_origin + bif) / 2 + (0.03, 0.03, 0.0), bif]), 12)
    apex = ray_hits(g, vent, [[LV_O[0][0], -0.6, LV_O[0][2]]], [[0.0, -1.0, 0.0]], lift_a)[0][0]
    lad = _on_ring(g, vent, ya, aa, lift_a)
    wrap = ray_hits(g, vent, [[LV_O[0][0], -1.0, LV_O[0][2]]], [[0.05, -0.6, -1.0]], lift_a)[0][0]
    L["lad"] = np.vstack([bif[None], lad, apex[None], wrap[None]])
    # circumflex round the left side, stopping short of the crux
    L["lcx"] = arc(l0 + (l1 - l0) * 0.06, l0 + (l1 - l0) * 0.78, lift_a)
    om = l0 + (l1 - l0) * 0.34
    ys = np.linspace(Y_AV - 0.01, -0.78, 18)
    L["lma"] = _on_ring(g, vent, ys, np.full_like(ys, om) + np.linspace(0, -0.2, 18) * np.sign(l1 - l0), lift_a)
    # diagonal branches of the LAD onto the anterior LV wall
    diags = []
    for f, spread in ((0.22, 0.55), (0.48, 0.5)):
        i = int(len(ya) * f)
        ys = np.linspace(ya[i], ya[i] - 0.42, 10)
        diags.append(_on_ring(g, vent, ys, aa[i] + np.linspace(0.02, spread, 10) * np.sign(l1 - l0), lift_a))
    L["diag"] = diags
    # veins
    off = 0.10 * np.sign(l1 - l0)
    gcv_up = _on_ring(g, vent, ya[::-1][2:], aa[::-1][2:] + off, lift_v)
    cs_ang = np.linspace(a_top + off, l1 - 0.25 * np.sign(l1 - l0), 70)
    gcv_ring = _ring(g, vent, Y_AV - 0.03, cs_ang, lift_v)
    split = int(len(gcv_ring) * 0.62)
    L["gcv"] = np.vstack([gcv_up, gcv_ring[:split + 1]])
    L["cs"] = np.vstack([gcv_ring[split:], CS_OSTIUM + CS_DIR * 0.16, CS_OSTIUM + CS_DIR * 0.03])
    L["mcv"] = _on_ring(g, vent, yp[:int(len(yp) * 0.8)][::-1], ap[:int(len(yp) * 0.8)][::-1] + off, lift_v)
    L["scv"] = arc(r0 + (r1 - r0) * 0.55, r1 - 0.06 * np.sign(r1 - r0), lift_v, y=Y_AV - 0.03)
    pv = l0 + (l1 - l0) * 0.64
    ys = np.linspace(-0.55, Y_AV + 0.02, 12)
    L["pvlv"] = _on_ring(g, vent, ys, np.full_like(ys, pv), lift_v)
    L["ring"] = _ring(g, vent, Y_AV - 0.02, ring_ang, 0.0)
    L["ant"], L["post"] = _on_ring(g, vent, ya, aa, 0.0), _on_ring(g, vent, yp, ap, 0.0)
    return L


def _vtube(path, r0, r1, seg=10, samples=None):
    path = smooth_path(np.asarray(path, float), samples or max(12, len(path) * 2))
    r = np.linspace(r0, r1, len(path))
    return tube(path, r, seg, caps=True)


def coronary_parts(g, F, L):
    ca, cv = "Coronary arteries", "Cardiac veins"
    A, V = "#d0342c", "#3558b5"
    parts = [
        Part("Left coronary artery (left main)", ca, A, _vtube(L["lca"], 0.038, 0.035), DESC["lca"], category="artery"),
        Part("Anterior interventricular artery (LAD)", ca, A,
             Mesh().extend(_vtube(L["lad"], 0.033, 0.016, samples=90)).extend(
                 Mesh().extend(_vtube(L["diag"][0], 0.02, 0.011)).extend(_vtube(L["diag"][1], 0.018, 0.01))),
             DESC["lad"], category="artery"),
        Part("Circumflex artery", ca, A, _vtube(L["lcx"], 0.031, 0.02, samples=70), DESC["lcx"], category="artery"),
        Part("Left marginal artery", ca, A, _vtube(L["lma"], 0.021, 0.012), DESC["lma"], category="artery"),
        Part("Right coronary artery", ca, A, _vtube(L["rca"], 0.036, 0.024, samples=100), DESC["rca"],
             category="artery"),
        Part("Right marginal artery", ca, A, _vtube(L["rma"], 0.021, 0.012), DESC["rma"], category="artery"),
        Part("Posterior interventricular artery", ca, A, _vtube(L["pda"], 0.024, 0.013, samples=60), DESC["pda"],
             category="artery"),
        Part("Great cardiac vein", cv, V, _vtube(L["gcv"], 0.022, 0.04, samples=120), DESC["gcv"], category="vein"),
        Part("Coronary sinus", cv, "#2f4fa8", _vtube(L["cs"], 0.042, 0.058, samples=40), DESC["cs"], category="vein"),
        Part("Middle cardiac vein", cv, V, _vtube(L["mcv"], 0.018, 0.034, samples=60), DESC["mcv"], category="vein"),
        Part("Small cardiac vein", cv, V, _vtube(L["scv"], 0.016, 0.026, samples=50), DESC["scv"], category="vein"),
        Part("Posterior vein of left ventricle", cv, V, _vtube(L["pvlv"], 0.016, 0.026), DESC["pvlv"],
             category="vein"),
    ]
    for p in parts:
        p.clip = True
    # epicardial fat filling the coronary and interventricular sulci
    from .sdf import sphere
    rng = np.random.default_rng(3)
    shapes = []
    for key, r in (("ring", 0.06), ("ant", 0.05), ("post", 0.05)):
        pts = L[key]
        if key == "ring":
            pts = np.vstack([pts, pts[:1]])
        for i in range(len(pts) - 1):
            if np.linalg.norm(pts[i + 1] - pts[i]) < 0.3:
                shapes.append(_cap(pts[i], pts[i + 1], r, r))
        # lobules of fat bulging out of the furrow
        for p in resample(pts, 0.035):
            shapes.append(sphere(p + rng.normal(0, 0.012, 3), r * rng.uniform(1.0, 1.45)))
    for key in ("rca", "lcx", "gcv", "cs", "lca"):
        pts = smooth_path(L[key], 40)
        for i in range(len(pts) - 1):
            shapes.append(_cap(pts[i], pts[i + 1], 0.05, 0.05))
    fat = g.shapes(shapes)
    E = F["H"] - EPI
    fat = vmax([fat, -E, E - 0.052, F["vent"] - 0.2])       # a layer on the epicardium, kept off the atria
    parts.append(_part(g, fat, "Epicardial fat", "Heart wall", "#d8b865", DESC["fat"], "fat", smooth=1.2))
    return parts


# ----------------------------------------------------------------------------------------------- conduction system
COND = "#2fd67c"                          # a teaching colour no tissue has


def _cond_tube(surf, ctrl, lift, r0, r1, samples=40):
    path = surf.path(ctrl, lift, samples=samples)
    return tube(path, np.linspace(r0, r1, len(path)), 8, caps=True), path


def conduction_parts(g, F, marks, epi_s, surfs, rng):
    """SA node -> atrial pathways -> AV node -> bundle of His -> bundle branches -> Purkinje network."""
    from .geometry import rotation_to
    lv_s, rv_s, ra_s, sept_s = surfs
    on_lv, on_rv = -(ENDO + 0.006), ENDO + 0.006       # just under the endocardium, standing proud of it
    grp = "Conduction system"
    parts = []
    # SA node: a subepicardial spindle at the top of the crista terminalis, where the SVC meets the right atrium
    cr = marks["crista"]
    sa_c, _ = epi_s.snap(cr[1] * 0.6 + cr[0] * 0.4, -0.012)
    sa_c = sa_c[0]
    sa_dir = unit(cr[5] - cr[0])
    sa = ell_mesh(sa_c, (0.032, 0.11, 0.026), res=14, rotation=rotation_to(sa_dir))
    parts.append(Part("Sinoatrial (SA) node", grp, COND, sa, DESC["sa"], category="nerve"))
    # AV node: in the floor of the right atrium at the apex of the triangle of Koch
    a, u, v = valve_frame(TV_AX)
    septal_annulus = TV_C + TV_R * _dir(u, v, 0) - a * 0.02
    av_c, _ = ra_s.snap(CS_OSTIUM * 0.45 + septal_annulus * 0.55 + (0.0, 0.07, 0.0), -(ENDO + 0.012))
    av_c = av_c[0]
    parts.append(Part("Atrioventricular (AV) node", grp, COND,
                      ell_mesh(av_c, (0.045, 0.028, 0.03), res=12, rotation=rotation_to(unit(av_c - CS_OSTIUM))),
                      DESC["av"], category="nerve"))
    # internodal pathways (anterior, middle, posterior) and Bachmann's bundle to the left atrium
    m = Mesh()
    ivc = VEIN_INLETS["ivc"][0]
    septal = F["p0"] - F["n"] * (IAS_HALF + 0.05)
    routes = [[sa_c, RA_C[0] + to_heart((0.25, 0.35, 0.9)) * 0.2, septal + to_heart((0, 0.12, 0.05)), av_c],
              [sa_c, septal + to_heart((0.0, 0.1, -0.15)), av_c],
              [sa_c, cr[len(cr) // 2], cr[-4], ivc * 0.5 + av_c * 0.5, av_c]]     # anterior, middle, posterior
    for ctrl in routes:
        path = ra_s.path(ctrl, -(ENDO + 0.006), samples=36)
        m.extend(tube(path, 0.009, 7, caps=True))
    bach_end = LA_C[0] + to_heart((0.1, 0.2, 0.15)) * 1.0
    bach = smooth_path(np.array([sa_c, (sa_c + bach_end) / 2 + to_heart((0, 0.12, 0.1)), bach_end]), 24)
    bach, _ = epi_s.snap(bach, -0.018)
    m.extend(tube(bach, 0.01, 7, caps=True))
    parts.append(Part("Internodal pathways & Bachmann's bundle", grp, "#5fe39a", m, DESC["internodal"],
                      category="nerve"))
    # bundle of His: through the central fibrous body to the crest of the muscular septum
    crest, _ = sept_s.snap(marks["cfb"] + (0.02, -0.14, 0.0), 0.0)
    crest = crest[0]
    his = smooth_path(np.array([av_c, marks["cfb"] + (0.0, -0.03, 0.0), crest]), 20)
    parts.append(Part("Atrioventricular bundle (bundle of His)", grp, COND, tube(his, 0.02, 10, caps=True),
                      DESC["his"], category="nerve"))
    # right bundle branch: down the right septal surface, across the moderator band to the anterior papillary
    mod = marks["moderator"]
    rbb1, p1 = _cond_tube(sept_s, [crest, crest * 0.5 + mod[0] * 0.5 + (0.0, 0.0, 0.03), mod[0]], on_rv, 0.014, 0.012)
    rbb2 = tube(smooth_path(mod + np.array([0.0, 0.028, 0.0]), 20), 0.012, 8, caps=True)
    parts.append(Part("Right bundle branch", grp, COND, Mesh().extend(rbb1).extend(rbb2), DESC["rbb"],
                      category="nerve"))
    # left bundle branch: pierces the septum and fans out as anterior, septal and posterior fascicles
    lstart, _ = lv_s.snap(crest + (0.08, -0.02, 0.0), on_lv)
    lstart = lstart[0]
    ends = []
    m = Mesh()
    targets = [marks["lvp"][0][1] + (0.0, 0.08, 0.0), marks["lvp"][1][1] + (0.0, 0.08, 0.0),
               np.asarray(LV_C[0]) + (-0.22, 0.10, 0.02)]
    for k, tgt in enumerate(targets):
        mid = lstart * 0.5 + tgt * 0.5 + (-0.05, 0.0, 0.0)
        tb, path = _cond_tube(lv_s, [lstart, mid, tgt], on_lv, 0.016, 0.01)
        m.extend(tb)
        ends.append(path[-1])
    m.extend(ell_mesh(lstart, (0.03, 0.02, 0.03), res=10))
    parts.append(Part("Left bundle branch", grp, COND, m, DESC["lbb"], category="nerve"))
    # Purkinje fibres: a branching subendocardial net over the lower two-thirds of both ventricles
    pk = Mesh()
    seeds = [(lv_s, e, on_lv) for e in ends] + [(rv_s, mod[2], -(ENDO + 0.006))]
    for surf, lift, n in ((lv_s, on_lv, 12), (rv_s, -(ENDO + 0.006), 9)):
        cand = np.nonzero(surf.pos[:, 1] < -0.15)[0]
        for i in rng.choice(cand, n, replace=False):
            seeds.append((surf, surf.pos[i], lift))
    for surf, start, lift in seeds:
        stack = [(np.asarray(start, float), unit(rng.normal(0, 1, 3)), 0)]
        while stack:
            p, d, depth = stack.pop()
            pts = [p]
            for step in range(rng.integers(4, 8)):
                d = unit(d + rng.normal(0, 0.45, 3))
                q, n_ = surf.snap(pts[-1] + d * 0.05, lift)
                d = unit(d - n_[0] * np.dot(d, n_[0]))
                pts.append(q[0])
                if pts[-1][1] > -0.05:
                    break
            if len(pts) > 2:
                pk.extend(tube(np.array(pts), 0.0065, 6, caps=True))
            if depth < 2:
                for _ in range(2 if rng.random() < 0.7 else 1):
                    stack.append((pts[-1], unit(d + rng.normal(0, 0.8, 3)), depth + 1))
    parts.append(Part("Purkinje fibres", grp, "#5fe39a", pk, DESC["purkinje"], category="nerve", clip=True))
    return parts


def septum_regions(g, F, sept_s, cfb):
    """Regions of the fossa ovalis (floor and limbus) and the membranous septum, and the coronary sinus opening."""
    fossa = np.maximum(F["disc"] - 0.03, np.abs(F["sp"]) - IAS_HALF - 0.035)
    crest, _ = sept_s.snap(cfb + (0.02, -0.14, 0.0), 0.0)
    ms_c = crest[0] * 0.4 + (AO_C - AO_AX * 0.12) * 0.6
    memb = np.maximum(g.shapes(_cap(ms_c, ms_c, 0.075)), F["ventricular"])
    return fossa, memb


def build_heart():
    rng = np.random.default_rng(11)
    V = vessel_specs()
    lo, hi = shapes_bbox([sh for o, l, p in V.values() for sh in o])
    lo = np.minimum(lo, (-1.08, -1.52, -0.80)) - 0.03
    hi = np.maximum(hi, (1.08, 1.20, 0.90)) + 0.03
    g = Grid(lo, hi)
    F = chamber_fields(g)
    inner, C2, marks = interior_parts(g, F, rng)
    fossa, memb = septum_regions(g, F, marks["surfs"][3], marks["cfb"])
    parts = wall_parts(g, F, C2, fossa, memb) + inner
    vparts, outers, lumen, fld = vessel_parts(g, F["H"], V)
    parts += vparts
    epi_s = Surface(g.mesh(F["H"] - EPI, 0.8, 2))
    L = coronary_layout(g, F["vent"] - EPI, F["H"])
    parts += coronary_parts(g, F, L)
    parts += conduction_parts(g, F, marks, epi_s, marks["surfs"], rng)
    parts += pericardium_parts(g, F["H"], V, outers)
    # one gentle warp shared by every part takes the machined look off without moving layers apart
    field = noise_field(0.009, 2.2, octaves=3, seed=5)
    for p in parts:
        p.mesh = nudge(p.mesh, field).transformed(R_BODY)
    return parts
