"""Female reproductive system: a midsagittally hemisected pelvis with the vulva in place, and magnified insets.

Unlike the tissue blocks this is an organ-level model, drawn the way an atlas draws the female pelvis. Units are
decimetres (1 unit = 100 mm); +y is superior, +z anterior and x lateral, so the midsagittal plane is x = 0 and the
viewer's cut-away removes the x > 0 half to show the classic median section (anterior to the left when viewed from
the right). The uterus is anteverted (cervix ~90 deg to the vagina) and anteflexed (body tipped forward over the
bladder at the isthmus); the ovaries hang from the back of the broad ligaments near the side walls.

Hollow organs are signed-distance fields with their walls cut from exact distance transforms, so every layer -
perimetrium, myometrium, the functional and basal endometrium, the vaginal mucosa - nests and sections cleanly.
Sheet-like structures (broad ligament, pelvic floor) are closed slabs over parametric surfaces. Bilateral parts are
built on the left side and mirrored.

Beside the pelvis sit four specimens that the scale of the pelvis cannot show, each already cut open: a breast in
sagittal section on its chest wall, an ovary cut through its follicles, a transverse section of the ampulla and a
block of secretory endometrium with an implanted conceptus, above a row of the first week's stages."""
import math

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

from .base import Part
from .geometry import Mesh, compute_normals, ellipsoid as ellipsoid_mesh, smooth_path, tube
from .kit import Volume
from .organic import Sweep, noise_field, warp_parts
from .sdf import fbm3, smin

CUTAWAY = ((-1.0, 0.0, 0.0), (1.0, 0.0, 0.0))       # both planes x = 0: the cut removes the whole x > 0 half


# =============================================================================== field helpers
def _smooth(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _grid(lo, hi, vox):
    return Volume(lo, hi, vox)


def _eval(vol, f):
    x, y, z = vol.axes()
    return np.broadcast_to(np.asarray(f(x, y, z), np.float32), vol.shape).astype(np.float32)


def _signed(mask, vox):
    """Exact signed distance (negative inside) of a voxel mask."""
    mask = np.asarray(mask, bool)
    if not mask.any():
        return np.full(mask.shape, 1.0, np.float32)
    out = ndimage.distance_transform_edt(~mask).astype(np.float32)
    inn = ndimage.distance_transform_edt(mask).astype(np.float32)
    return np.where(mask, -(inn - 0.5), out - 0.5).astype(np.float32) * vox


def _flat_tube(path, a, b, cap0=None, cap1=None, side=(1.0, 0.0, 0.0)):
    """Distance-like field of a tube with an elliptical section swept along a polyline.

    a is the half-width along `side` (lateral), b the half-thickness across it; both taper along the path. The ends
    are closed by half-ellipsoids of axial radius cap0 / cap1. Returns f(x, y, z) -> (distance, arc length of the
    nearest axis point). Distances are exact on the surface and scaled inside, so layers are cut from _signed()."""
    path = np.asarray(path, np.float64)
    n = len(path)
    seg = np.diff(path, axis=0)
    L = np.maximum(np.linalg.norm(seg, axis=1), 1e-9)
    U = seg / L[:, None]
    arc = np.concatenate([[0.0], np.cumsum(L)])

    def prof(v):
        v = np.asarray(v, np.float64)
        if v.ndim and len(v) != n:          # a profile given at any number of evenly spaced stations
            v = np.interp(arc / arc[-1], np.linspace(0, 1, len(v)), v)
        return np.broadcast_to(v, (n,))
    a, b = prof(a), prof(b)
    side = np.asarray(side, np.float64)
    S, N = [], []
    for u in U:
        s = side - u * (side @ u)
        if np.linalg.norm(s) < 1e-6:                    # axis runs along `side`: any perpendicular will do
            alt = np.array([0.0, 1.0, 0.0]) if abs(u[1]) < 0.9 else np.array([0.0, 0.0, 1.0])
            s = alt - u * (alt @ u)
        s /= np.linalg.norm(s)
        S.append(s)
        N.append(np.cross(u, s))
    cap0 = b[0] if cap0 is None else cap0
    cap1 = b[-1] if cap1 is None else cap1

    def f(x, y, z):
        best = None
        best_s = None
        for i in range(n - 1):
            A, u, s_, n_ = path[i], U[i], S[i], N[i]
            dx, dy, dz = x - A[0], y - A[1], z - A[2]
            tr = (dx * u[0] + dy * u[1] + dz * u[2]) / L[i]
            t = np.clip(tr, 0.0, 1.0)
            over = (tr - t) * L[i]
            qs = dx * s_[0] + dy * s_[1] + dz * s_[2]
            qn = dx * n_[0] + dy * n_[1] + dz * n_[2]
            at = a[i] + (a[i + 1] - a[i]) * t
            bt = b[i] + (b[i + 1] - b[i]) * t
            if i == 0 and i == n - 2:
                cap = np.where(tr < 0, cap0, cap1)
            elif i == 0:
                cap = np.where(tr < 0, cap0, bt)
            elif i == n - 2:
                cap = np.where(tr > 1, cap1, bt)
            else:
                cap = bt
            k = np.sqrt((qs / at) ** 2 + (qn / bt) ** 2 + (over / cap) ** 2)
            d = (k - 1.0) * np.minimum(np.minimum(at, bt), cap)
            sv = arc[i] + t * L[i]
            if best is None:
                best, best_s = d, np.broadcast_to(sv, d.shape).copy()
            else:
                m = d < best
                best = np.where(m, d, best)
                best_s = np.where(m, sv, best_s)
        return best, best_s
    f.arc = arc
    ext = float(max(a.max(), b.max(), cap0, cap1))
    f.bmin, f.bmax = path.min(0) - ext, path.max(0) + ext
    return f


def _tube_d(path, radius):
    """Round tapered tube as a plain distance field (union of round cones)."""
    fl = _flat_tube(path, radius, radius)
    g = lambda x, y, z: fl(x, y, z)[0]      # noqa: E731
    g.bmin, g.bmax = fl.bmin, fl.bmax
    return g


def _dist(f):
    """Distance part of a _flat_tube field, keeping its bounding box."""
    g = lambda x, y, z: f(x, y, z)[0]       # noqa: E731
    g.bmin, g.bmax = f.bmin, f.bmax
    return g


def _apply(V, d, f, op="min", k=0.0, pad=0.0):
    """Combine field f into the array d (on volume V), evaluating f only inside its bounding box."""
    bmin = getattr(f, "bmin", None)
    if bmin is None:
        r = (tuple(slice(0, n) for n in V.shape), V.axes())
    else:
        r = V.region(np.asarray(bmin) - pad - k - 3 * V.voxel, np.asarray(f.bmax) + pad + k + 3 * V.voxel)
        if r is None:
            return d
    sl, (x, y, z) = r
    v = np.asarray(f(x, y, z), np.float32)
    cur = d[sl]
    if op == "min":
        d[sl] = np.minimum(cur, v)
    elif op == "smin":
        d[sl] = smin(cur, v, k)
    elif op == "sub":
        d[sl] = np.maximum(cur, -v)
    elif op == "ssub":
        d[sl] = -smin(-cur, v, k)
    return d


def _empty(V, v=1.0):
    return np.full(V.shape, v, np.float32)


def _cloud_d(pts, thick, vol):
    """Distance to a dense point sampling of a surface, minus a half-thickness (per point), on a volume grid.

    Turns any parametric sheet - a wing of the ilium, a peritoneal fold - into a closed solid with rounded edges."""
    pts = np.asarray(pts, np.float64).reshape(-1, 3)
    thick = np.broadcast_to(np.asarray(thick, np.float64).reshape(-1), (len(pts),))
    tree = cKDTree(pts)
    x, y, z = vol.axes()
    X, Y, Z = np.broadcast_arrays(x, y, z)
    q = np.stack([X.ravel(), Y.ravel(), Z.ravel()], -1)
    d = np.full(len(q), 1.0, np.float32)
    lim = float(thick.max()) + vol.voxel * 6
    # only query voxels near the sheet's bounding box
    lo, hi = pts.min(0) - lim, pts.max(0) + lim
    sel = np.all((q >= lo) & (q <= hi), axis=1)
    dist, idx = tree.query(q[sel], k=1, distance_upper_bound=lim * 2)
    ok = np.isfinite(dist)
    out = np.full(sel.sum(), lim, np.float32)
    out[ok] = dist[ok] - thick[idx[ok]]
    d[sel] = out
    d[~sel] = lim
    return d.reshape(vol.shape)


def _mesh(vol, d, smooth=0.9, step=1):
    v = vol.copy(d)
    return v.mesh(smooth, step=step)


def _clean(mesh, min_tris=40):
    """Drop tiny disconnected fragments that marching cubes leaves where a layer pinches out."""
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    out = Mesh()
    for pos, nrm, idx in mesh.parts:
        n = len(pos)
        e = np.concatenate([idx[:, [0, 1]], idx[:, [1, 2]]])
        g = sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
        nc, lab = connected_components(g, directed=False)
        tl = lab[idx[:, 0]]
        keep = np.bincount(tl, minlength=nc)[tl] >= min_tris
        if keep.any():
            out.parts.append((pos, nrm, idx[keep]))
    return out


def _mirror(mesh):
    out = Mesh()
    for p, n, i in mesh.parts:
        q = p.copy()
        q[:, 0] *= -1
        m = n.copy()
        m[:, 0] *= -1
        out.parts.append((q, m, i[:, ::-1].copy()))
    return out


def _both(mesh):
    return Mesh().extend(mesh).extend(_mirror(mesh))


def _sheet(P, thick):
    """Closed slab of (possibly varying) thickness over a parametric grid of points P (nu, nv, 3)."""
    P = np.asarray(P, np.float64)
    nu, nv, _ = P.shape
    thick = np.broadcast_to(np.asarray(thick, np.float64), (nu, nv))
    du = np.gradient(P, axis=0)
    dv = np.gradient(P, axis=1)
    nrm = np.cross(du, dv)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=2, keepdims=True), 1e-12)
    top = P + nrm * (thick[..., None] / 2)
    bot = P - nrm * (thick[..., None] / 2)
    a = np.arange(nu * nv).reshape(nu, nv)
    q0, q1, q2, q3 = a[:-1, :-1].ravel(), a[1:, :-1].ravel(), a[1:, 1:].ravel(), a[:-1, 1:].ravel()
    tri = np.concatenate([np.stack([q0, q1, q2], 1), np.stack([q0, q2, q3], 1)])
    pos = np.vstack([top.reshape(-1, 3), bot.reshape(-1, 3)])
    n = nu * nv
    idx = [tri, tri[:, ::-1] + n]
    for line, flip in ((a[0, :], False), (a[-1, :], True), (a[:, 0], True), (a[:, -1], False)):
        i0, i1 = line[:-1], line[1:]
        t = np.vstack([np.stack([i0, i1, i1 + n], 1), np.stack([i0, i1 + n, i0 + n], 1)])
        idx.append(t[:, ::-1] if flip else t)
    from .cells import orient_outward
    return orient_outward(Mesh().add(pos, np.vstack(idx)))


def _part(mesh, name, group, color, desc, category="organ", alpha=1.0, clip=True, rank=0.0, detail=None, label=True,
          micro=False):
    """A part of the organ-level model. At 1 unit = 100 mm cells are invisible, so cut faces get a fine grain and a
    mottle but no nuclei - unless the part belongs to a magnified inset (micro=True)."""
    if detail is None and not micro:
        from .base import DETAIL_DEFAULTS
        mot, _, _, axis = DETAIL_DEFAULTS.get(category, DETAIL_DEFAULTS["other"])
        detail = (mot, 320.0, 0.0, 0)
    return Part(name, group, color, mesh, desc, alpha=alpha, category=category, clip=clip, rank=rank, detail=detail,
                label=label)


def _sagittal(pts_yz, x=0.0):
    p = np.asarray(pts_yz, np.float64)
    return np.stack([np.full(len(p), x), p[:, 0], p[:, 1]], -1)


def _resample(path, spacing):
    path = np.asarray(path, np.float64)
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(2, int(arc[-1] / spacing) + 1)
    s = np.linspace(0, arc[-1], n)
    return np.stack([np.interp(s, arc, path[:, c]) for c in range(3)], -1)


def _spline(points, spacing=0.02):
    return _resample(smooth_path(np.asarray(points, np.float64), 200), spacing)


# =============================================================================== skeleton
SACRUM_A = np.array([(0.40, -0.35), (0.21, -0.50), (0.0, -0.61), (-0.20, -0.655), (-0.36, -0.63)])   # (y, z)
COCCYX = np.array([(-0.39, -0.615), (-0.45, -0.58), (-0.505, -0.535), (-0.55, -0.49)])
SYMPH_C = np.array([0.0, -0.45, 0.55])          # centre of the pubic symphysis
SYMPH_AX = np.array([0.0, 0.906, 0.423])        # its long axis: upper end tilted forward

DESC = {
    # ------------------------------------------------------------------ bony pelvis
    "sacrum": "Sacrum: five fused vertebrae forming the posterior wall of the pelvis, concave forwards (the sacral "
              "hollow, where the rectum lies). Its promontory (front of S1) is the posterior landmark of the pelvic "
              "inlet; four pairs of anterior sacral foramina transmit the ventral rami of S1-S4, and the sacral "
              "canal carries the cauda equina. The female sacrum is shorter, wider and less curved than the male.",
    "coccyx": "Coccyx: three to five small fused vertebrae below the sacrum. It anchors the anococcygeal body, "
              "levator ani and coccygeus, and moves backwards during childbirth to enlarge the outlet.",
    "l5": "Fifth lumbar vertebra: the lowest mobile vertebra, sitting on the sacrum at the lumbosacral angle. Shown for "
          "orientation; in the median section its body, vertebral canal and spinous process are cut.",
    "disc": "Lumbosacral intervertebral disc (L5/S1): anulus fibrosus round a nucleus pulposus, wedge-shaped because "
            "of the lumbosacral angle. The commonest level, with L4/5, for disc prolapse.",
    "hip": "Hip bone (os coxae): ilium, ischium and pubis fused at the acetabulum. The arcuate line and pecten pubis "
           "form the pelvic brim, which divides the false (greater) pelvis above from the true (lesser) pelvis "
           "below. The female pelvis has a wide, round inlet, a subpubic angle of 80-90 degrees, everted ischial "
           "spines and a wide sciatic notch - the dimensions a baby's head must pass.",
    "symphysis": "Pubic symphysis: a secondary cartilaginous joint (fibrocartilage disc) between the pubic bodies. "
                 "Relaxin loosens it in late pregnancy; symphysis pubis dysfunction causes pelvic girdle pain. The "
                 "bladder lies directly behind it and the mons pubis in front.",
    # ------------------------------------------------------------------ pelvic floor
    "levator": "Levator ani (pubococcygeus, puborectalis, iliococcygeus): the funnel-shaped muscular pelvic "
               "diaphragm, from the pubis, the tendinous arch over obturator internus and the ischial spine, to the "
               "perineal body, anococcygeal body and coccyx. Puborectalis slings behind the anorectal junction and "
               "keeps the anorectal angle (continence). The urethra and vagina pass through the urogenital hiatus "
               "in front. Nerve to levator ani (S3-S4) and pudendal nerve. Stretching or avulsion in vaginal birth "
               "weakens the floor and predisposes to prolapse and stress incontinence; pelvic floor (Kegel) "
               "exercises strengthen it.",
    "coccygeus": "Coccygeus (ischiococcygeus): the posterior part of the pelvic diaphragm, from the ischial spine to "
                 "the side of the coccyx and lower sacrum, lying on the sacrospinous ligament. S4-S5.",
    # ------------------------------------------------------------------ uterus
    "fundus": "Fundus of uterus: the rounded top of the body above the entry of the uterine tubes. Its height is "
              "measured in pregnancy (symphysis-fundal height: at the umbilicus at ~20 weeks, near the xiphisternum "
              "at 36). Shown here is its wall, the myometrium - thick interlacing smooth muscle (outer longitudinal, "
              "a vascular middle layer with the arcuate arteries, inner mainly circular).",
    "body": "Body (corpus) of uterus: the main part, between fundus and isthmus, flattened front to back round a "
            "slit-like triangular cavity. The wall is mostly myometrium, which hypertrophies and multiplies in "
            "pregnancy and contracts in labour (oxytocin). Leiomyomas (fibroids) - benign, oestrogen-sensitive "
            "smooth-muscle tumours in up to 70% of women - arise here: submucosal, intramural or subserosal, "
            "causing heavy bleeding, pain, pressure or subfertility. Adenomyosis is endometrium within the "
            "myometrium.",
    "isthmus": "Isthmus of uterus: the constricted ~1 cm between body and cervix, level with the internal os. In "
               "pregnancy it thins and expands into the lower uterine segment, where the transverse incision of a "
               "caesarean section is made; the uterine arteries reach the uterus at this level.",
    "perimetrium": "Perimetrium: the serosa (visceral peritoneum) of the uterus, a mesothelium on thin connective "
                   "tissue. It covers the fundus and body, reflects forwards onto the bladder at the isthmus "
                   "(vesicouterine pouch) and backwards over the posterior fornix onto the rectum (rectouterine "
                   "pouch), and continues laterally as the two layers of the broad ligament.",
    "endo_f": "Endometrium - functional layer (stratum functionalis): the superficial two thirds, with coiled uterine "
              "glands in a cellular stroma and spiral arteries. Under oestrogen it proliferates (days 5-14); after "
              "ovulation progesterone makes the glands secrete glycogen and the stroma decidualise, ready for "
              "implantation (days 15-28). When the corpus luteum fails, falling progesterone makes the spiral "
              "arteries constrict and the layer is shed as menstruation. Shown here in the secretory phase. "
              "Endometriosis is endometrial tissue outside the uterus; endometrial hyperplasia and carcinoma follow "
              "unopposed oestrogen (obesity, PCOS, tamoxifen) and present as postmenopausal bleeding.",
    "endo_b": "Endometrium - basal layer (stratum basalis): the deep third, next to the myometrium, supplied by "
              "straight (basal) arteries. It is not shed and regenerates the functional layer after each period. "
              "Over-vigorous curettage that removes it causes intrauterine adhesions (Asherman syndrome).",
    "cavity": "Uterine cavity: a narrow triangular slit in the coronal plane - the tubal ostia at the upper corners, "
              "the internal os at the apex below. It holds only a few millilitres; the site of implantation and of "
              "intrauterine devices. The fertilised ovum usually implants in its upper posterior wall.",
    "cervix": "Cervix of uterus: the lower, narrow, mostly fibrous (collagenous, little smooth muscle) part, about "
              "2.5-3 cm long, with a supravaginal part and a vaginal part (portio) projecting into the vault. It "
              "softens and dilates in labour (10 cm at full dilatation). Cervical insufficiency causes painless "
              "mid-trimester loss and is treated with a cerclage stitch.",
    "ectocervix": "Ectocervix and transformation zone: the vaginal surface of the cervix is covered by non-keratinised "
                  "stratified squamous epithelium, which meets the columnar endocervical epithelium at the "
                  "squamocolumnar junction round the external os. The transformation zone, where columnar "
                  "epithelium undergoes squamous metaplasia, is where high-risk HPV (16, 18) causes cervical "
                  "intraepithelial neoplasia and squamous carcinoma. A Pap smear or liquid-based cytology samples "
                  "this zone with a spatula or brush; HPV vaccination and screening have cut cervical cancer "
                  "deaths dramatically.",
    "endocervix": "Endocervical mucosa: simple columnar mucus-secreting epithelium thrown into branching folds "
                  "(plicae palmatae, the arbor vitae) with deep crypt-like glands. Its mucus is thin and stretchy "
                  "(spinnbarkeit) at ovulation, letting sperm through, and thick after it (progesterone, and the "
                  "progestogen pill). Blocked glands form Nabothian cysts; adenocarcinoma arises here.",
    "canal": "Cervical canal: the spindle-shaped (fusiform) passage through the cervix, from the internal os above "
             "to the external os below, normally plugged with mucus - a barrier to ascending infection that is "
             "expelled as the 'show' at the start of labour.",
    "int_os": "Internal os: the upper, narrow end of the cervical canal, where it opens into the uterine cavity at "
              "the isthmus.",
    "ext_os": "External os (opening of the cervix): the opening of the cervical canal into the vagina - small and "
              "round in a woman who has not given birth vaginally, a transverse slit after childbirth. The "
              "squamocolumnar junction lies round it, so it is the target of the cervical smear.",
    # ------------------------------------------------------------------ vagina
    "vagina": "Vagina: a fibromuscular tube 7-9 cm long, from the cervix to the vestibule, running upwards and "
              "backwards at about 90 degrees to the uterus. Its walls (mucosa, a smooth muscle coat, adventitia) "
              "normally lie collapsed together, H-shaped in cross-section. It receives the penis, is the birth canal "
              "and drains menstrual flow. The urethra is embedded in its anterior wall; the rectum and perineal "
              "body lie behind. Weakness of its supports causes prolapse: cystocele (bladder bulging into the "
              "anterior wall), rectocele (posterior wall) or uterine descent.",
    "rugae": "Vaginal rugae: transverse ridges of the mucosa, most marked in the lower vagina before childbirth, that "
             "let the canal stretch enormously in labour. The mucosa is non-keratinised stratified squamous "
             "epithelium without glands, rich in glycogen under oestrogen; lactobacilli ferment it to lactic acid "
             "(pH ~4), which protects against infection. Loss of lactobacilli gives bacterial vaginosis; "
             "oestrogen loss after menopause gives atrophic vaginitis.",
    "fornix": "Fornix of vagina: the vault of the vagina round the projecting cervix - shallow anterior, two lateral "
              "and a deep posterior fornix. The posterior fornix lies directly below the rectouterine pouch, so "
              "fluid or pus there can be felt or drained through it (culdocentesis), and the ureters and uterine "
              "arteries are palpable through the lateral fornices. Sperm pool here after intercourse.",
    "orifice": "Vaginal orifice (introitus): the opening of the vagina into the posterior part of the vestibule, "
               "behind the urethral orifice, partly closed by the hymen. It is widened by episiotomy in childbirth.",
    "vag_lumen": "Vaginal canal: the potential space of the vagina, a transverse slit between the anterior and "
                 "posterior walls except where the cervix holds the vault open.",
    "hymen": "Hymen: a thin fold of mucosa that partly closes the vaginal orifice, usually crescentic or annular, and "
             "is torn or stretched by tampons, exercise or intercourse - it is not a reliable sign of virginity. "
             "An imperforate hymen presents at puberty with cyclical pain and haematocolpos.",
    # ------------------------------------------------------------------ tubes and ovaries
    "tube_im": "Uterine (intramural) part of the uterine tube: the ~1 cm that runs through the myometrium at the "
               "cornu to open into the uterine cavity at the uterine ostium. Its lumen is only ~1 mm. Interstitial "
               "(cornual) ectopic pregnancies here rupture late and bleed catastrophically.",
    "tube_isth": "Isthmus of the uterine tube: the narrow, thick-walled medial third next to the uterus, with a "
                 "strong muscular coat and few mucosal folds. The site of tubal ligation (sterilisation) and of "
                 "isthmic ectopic pregnancies, which rupture early.",
    "tube_amp": "Ampulla of the uterine tube: the widest and longest part (over half the tube), thin-walled with a "
                "labyrinth of branched mucosal folds. Fertilisation normally happens here, within about 24 hours of "
                "ovulation. It is also the commonest site of ectopic pregnancy (~95% of ectopics are tubal): risk "
                "factors are previous pelvic inflammatory disease, tubal surgery, IVF, smoking and an IUD in place; "
                "a positive pregnancy test with an empty uterus, pain and bleeding - rupture causes "
                "haemoperitoneum and shock.",
    "tube_inf": "Infundibulum of the uterine tube: the funnel-shaped lateral end that opens into the peritoneal "
                "cavity near the ovary, its rim fringed with fimbriae. The tube is not attached to the ovary, so "
                "the ovulated oocyte must be swept in - which is why the female genital tract is open to the "
                "peritoneal cavity and ascending infection (pelvic inflammatory disease, from chlamydia or "
                "gonorrhoea) can spread to it, causing salpingitis, tubo-ovarian abscess, perihepatic adhesions "
                "(Fitz-Hugh-Curtis) and tubal infertility.",
    "fimbriae": "Fimbriae: finger-like fringes on the rim of the infundibulum; at ovulation they move over the "
                "ovary and their ciliated epithelium sweeps the oocyte and its cumulus into the tube. One long "
                "ovarian fimbria is attached to the tubal pole of the ovary. Many high-grade serous 'ovarian' "
                "carcinomas are now thought to begin in the fimbrial epithelium.",
    "ostium": "Abdominal ostium of the uterine tube: the opening at the bottom of the infundibulum (about 2 mm "
              "across) through which the oocyte enters the tube and through which the genital tract communicates "
              "with the peritoneal cavity.",
    "ovary": "Ovary: the female gonad, an almond-shaped organ about 3 x 1.5 x 1 cm lying in the ovarian fossa on the "
             "lateral pelvic wall, behind the broad ligament. It produces oocytes and the steroid hormones "
             "(oestrogens, progesterone, some androgens). Its surface becomes scarred with age from repeated "
             "ovulation. Held by the mesovarium, the ovarian ligament and the suspensory ligament. Ovarian cysts "
             "(functional follicular and corpus luteum cysts, dermoid cysts, endometriomas) are common; torsion "
             "causes sudden severe pain. Ovarian cancer presents late with bloating; CA-125 and ultrasound; BRCA "
             "mutations raise the risk. Pain from the ovary is referred to the medial thigh (obturator nerve).",
    # ------------------------------------------------------------------ ligaments
    "mesosalpinx": "Broad ligament - mesosalpinx: the upper part of the broad ligament, between the uterine tube in "
                   "its free edge and the level of the ovarian ligament and mesovarium. It carries the tubal "
                   "branches of the uterine and ovarian arteries. Paratubal (hydatid of Morgagni) cysts lie in it.",
    "mesometrium": "Broad ligament - mesometrium: the largest part of the broad ligament, below the mesovarium, "
                   "running from the side of the uterus to the pelvic side wall and floor. The broad ligament is a "
                   "double fold of peritoneum; between its layers (the parametrium) run the uterine vessels, the "
                   "round and ovarian ligaments and, at its base, the ureter. It limits lateral movement of the "
                   "uterus but is not a major support.",
    "mesovarium": "Broad ligament - mesovarium: a short fold from the posterior layer of the broad ligament to the "
                  "anterior (hilar) border of the ovary, through which the ovarian vessels and nerves enter the "
                  "hilum. The ovary itself is not covered by peritoneum but by the germinal (surface) epithelium.",
    "ov_lig": "Ovarian ligament (ligament of the ovary proper): a fibromuscular cord in the broad ligament from the "
              "uterine pole of the ovary to the lateral angle of the uterus, just below the tube. Together with the "
              "round ligament it is the remnant of the gubernaculum.",
    "susp": "Suspensory ligament of the ovary (infundibulopelvic ligament): a peritoneal fold from the tubal pole of "
            "the ovary up over the pelvic brim, carrying the ovarian artery, vein, lymphatics and nerves. It is "
            "clamped at oophorectomy, where the ureter, running just medial to it at the brim, must be protected. "
            "Ovarian lymph drains along it to the para-aortic nodes.",
    "round": "Round ligament of the uterus: a cord of smooth muscle and connective tissue from the uterine angle, "
             "below and in front of the tube, through the deep inguinal ring and the inguinal canal to the "
             "subcutaneous tissue of the labium majus. It helps hold the uterus anteverted. It stretches in "
             "pregnancy (round ligament pain), and its course explains why some lymph from the uterine angle drains "
             "to the superficial inguinal nodes. Homologue of the gubernaculum testis.",
    "uterosacral": "Uterosacral ligament: a fibromuscular band from the back of the cervix and upper vagina, round "
                   "the side of the rectum, to the front of the sacrum. It raises the rectouterine folds that bound "
                   "the rectouterine pouch, and with the cardinal ligament is the main level-1 support of the cervix "
                   "and vault. Deep endometriosis nodules often form on it (painful intercourse).",
    "cardinal": "Cardinal (transverse cervical, Mackenrodt) ligament: condensed fibrous tissue and smooth muscle in "
                "the base of the broad ligament, from the cervix and lateral fornix to the pelvic side wall, around "
                "the uterine vessels. The most important passive support of the uterus; stretching of it and the "
                "uterosacral ligaments in childbirth leads to uterovaginal prolapse. The ureter passes through it "
                "just below the uterine artery.",
    # ------------------------------------------------------------------ vessels and neighbours
    "int_iliac": "Internal iliac artery: supplies the pelvic organs, perineum and gluteal region. The uterine artery "
                 "arises from its anterior division. Tied bilaterally (or embolised) to control catastrophic "
                 "post-partum haemorrhage.",
    "ut_art": "Uterine artery: from the anterior division of the internal iliac artery, it runs medially in the base "
              "of the broad ligament and crosses ABOVE the ureter about 2 cm lateral to the cervix ('water under the "
              "bridge') - where the ureter can be clamped or cut during hysterectomy. At the isthmus it divides into "
              "a tortuous ascending branch along the side of the uterus, which anastomoses with the ovarian artery "
              "in the mesosalpinx, and a descending cervicovaginal branch. Its arcuate, radial and spiral branches "
              "supply the endometrium. Uterine artery embolisation treats fibroids and post-partum bleeding.",
    "ov_art": "Ovarian artery: arises from the abdominal aorta at L2, runs down on psoas, crosses the external iliac "
              "vessels at the brim and enters the suspensory ligament to reach the ovary through the mesovarium; a "
              "tubal branch anastomoses with the uterine artery.",
    "ov_vein": "Ovarian vein: a pampiniform plexus at the hilum that becomes a single vein in the suspensory "
               "ligament; the right drains to the inferior vena cava, the left to the left renal vein (so left "
               "renal vein obstruction can cause pelvic congestion). Ovarian vein thrombosis is a rare post-partum "
               "complication.",
    "bladder": "Urinary bladder: lies behind the pubic symphysis, below and in front of the uterus, its base against "
               "the cervix and anterior vaginal wall. Detrusor smooth muscle round a lumen lined by urothelium. "
               "Because the uterus rests on it, the pregnant uterus presses on it (frequency), and loss of anterior "
               "vaginal support lets it bulge into the vagina (cystocele). Injured in caesarean section.",
    "urine": "Urine in the bladder lumen (the bladder is shown moderately full).",
    "urethra": "Female urethra: only about 4 cm long, running down and forwards from the bladder neck, embedded in "
               "the anterior vaginal wall, through the urogenital hiatus and perineal membrane to the external "
               "urethral orifice in the vestibule. Its shortness and nearness to the perineum make urinary tract "
               "infection much commoner in women. Stress incontinence follows loss of its support.",
    "ureter": "Ureter: enters the pelvis over the common iliac bifurcation, runs down the lateral wall behind the "
              "ovary (forming the posterior boundary of the ovarian fossa), then forwards and medially in the base "
              "of the broad ligament beneath the uterine artery, about 2 cm lateral to the cervix and close to the "
              "lateral fornix, to the bladder. It is at risk during hysterectomy and oophorectomy.",
    "rectum": "Rectum: follows the curve of the sacrum and coccyx from S3 to the anorectal junction, where "
              "puborectalis kinks it forwards. Its upper part is covered in front by peritoneum, which reflects "
              "onto the posterior fornix to form the rectouterine pouch; below that it is separated from the vagina "
              "by the rectovaginal septum. Transverse folds project into its lumen. Deep endometriosis can invade "
              "it; a rectocele bulges into the posterior vaginal wall.",
    "anal": "Anal canal and anus: the last 3-4 cm of the gut, from the anorectal junction down and back to the anus, "
            "closed by the internal and external anal sphincters. The perineal body separates it from the vagina; "
            "third- and fourth-degree perineal tears in childbirth involve the sphincters.",
    "vu_pouch": "Vesicouterine pouch: the shallow peritoneal recess between the bladder and the front of the "
                "uterus, at the level of the isthmus. It is opened to reach the lower uterine segment at caesarean "
                "section; endometriosis deposits are common here.",
    "ru_pouch": "Rectouterine pouch (of Douglas): the deep peritoneal recess between the uterus and posterior "
                "fornix in front and the rectum behind - the lowest point of the peritoneal cavity in a standing or "
                "supine woman. Blood (ruptured ectopic pregnancy), pus (pelvic inflammatory disease), ascites and "
                "metastatic deposits collect here, where they can be felt on vaginal or rectal examination, seen on "
                "ultrasound or drained through the posterior fornix. A common site of endometriosis.",
    # ------------------------------------------------------------------ vulva and perineum
    "mons": "Mons pubis: the rounded pad of subcutaneous fat over the pubic symphysis, covered by skin and, after "
            "puberty, pubic hair. The labia majora run back from it.",
    "majora": "Labia majora: two prominent folds of skin over fat and smooth muscle, from the mons to the perineum, "
              "enclosing the pudendal cleft; hair-bearing on their outer surface, with sebaceous, sweat and "
              "apocrine glands. The round ligament ends in them. Homologue of the scrotum; their lymph drains to "
              "the superficial inguinal nodes (vulval cancer, Bartholin abscess spread).",
    "minora": "Labia minora: thin, hairless folds of skin rich in sebaceous glands, venous plexuses and nerve "
              "endings, lying inside the labia majora and enclosing the vestibule. In front each splits round the "
              "clitoris into a lateral part forming the prepuce and a medial part forming the frenulum; behind "
              "they meet at the fourchette. Homologue of the ventral penile skin and spongy urethra floor.",
    "vestibule": "Vestibule of the vagina: the space between the labia minora, from the clitoris to the "
                 "fourchette, into which open (front to back) the external urethral orifice, the vaginal orifice "
                 "and the ducts of the greater and lesser vestibular glands. Its floor is lined by non-keratinised "
                 "stratified squamous epithelium. Order on examination: clitoris, urethral opening, vaginal opening, "
                 "anus.",
    "cleft": "Pudendal cleft (rima pudendi): the slit between the two labia majora, opening into the vestibule when "
             "the labia are parted. Shown as a faint film so it can be picked.",
    "glans": "Glans of the clitoris: the small, exposed, highly innervated tip of the clitoris (dorsal nerve of the "
             "clitoris, a branch of the pudendal nerve), capped by the prepuce. Homologue of the glans penis.",
    "prepuce": "Prepuce of the clitoris (clitoral hood): the fold formed where the lateral limbs of the labia minora "
               "unite over the glans. Homologue of the penile foreskin.",
    "clit_body": "Body and crura of the clitoris: erectile tissue (paired corpora cavernosa) that runs from the glans "
                 "up to the pubic symphysis, bends back at the angle (suspended by a suspensory ligament) and "
                 "divides into the two crura, which are attached along the ischiopubic rami under the "
                 "ischiocavernosus muscles. It fills with blood in sexual arousal. Homologue of the penis, but it "
                 "carries no urethra.",
    "ureth_orif": "External urethral orifice: a small median slit or pucker in the vestibule, about 2-2.5 cm behind "
                  "the glans and just in front of the vaginal orifice; the openings of the paraurethral (Skene) "
                  "glands lie beside it. Catheters are passed here.",
    "bartholin": "Greater vestibular (Bartholin) glands: pea-sized mucous glands behind and lateral to the vaginal "
                 "orifice, under the bulb of the vestibule, whose ducts open into the vestibule at about 5 and 7 "
                 "o'clock between the hymen and labia minora. They lubricate the vestibule in arousal. A blocked "
                 "duct forms a Bartholin cyst, which can become an abscess (marsupialisation). Homologue of the "
                 "bulbourethral glands.",
    "perineum": "Perineal body (clinical perineum): the fibromuscular node between the vaginal orifice and the anus, "
                "where the bulbospongiosus, superficial and deep transverse perineal muscles, external anal "
                "sphincter and levator ani meet. The obstetric (clinical) perineum is the skin over it. It is "
                "stretched and may tear in childbirth, or be cut in an episiotomy (usually mediolateral, away from "
                "the anal sphincter); poor repair weakens pelvic support. The anatomical perineum is the whole "
                "diamond-shaped outlet: urogenital triangle in front, anal triangle behind.",
    # ------------------------------------------------------------------ ovary specimen
    "germinal": "Germinal (surface) epithelium: a single layer of cuboidal cells (modified mesothelium) covering the "
                "ovary - despite the name it does not produce germ cells. It is repaired after every ovulation; "
                "most ovarian epithelial tumours were once thought to arise from it.",
    "albuginea": "Tunica albuginea of the ovary: a thin layer of dense connective tissue beneath the surface "
                 "epithelium, giving the ovary its whitish colour.",
    "cortex": "Ovarian cortex: the outer zone - a very cellular stroma of spindle-shaped fibroblast-like cells that "
              "holds the follicles at all stages, with corpora lutea and albicantia. The follicle count is fixed "
              "before birth (~1-2 million primordial follicles at birth, ~400 000 at puberty, ~400 ovulated in a "
              "lifetime); when they run out, menopause follows.",
    "medulla": "Ovarian medulla: the central zone of loose connective tissue with large, coiled (helicine) blood "
               "vessels, lymphatics and nerves entering from the hilum. Hilus cells (Leydig-like) here can form "
               "androgen-secreting tumours.",
    "ov_art_in": "Ovarian arteries in the medulla: branches of the ovarian artery (and the anastomosis with the "
                 "uterine artery) entering at the hilum and coiling (helicine arteries) through the medulla to "
                 "supply the cortex and the thecae of growing follicles.",
    "ov_vein_in": "Ovarian veins of the medulla: follow the arteries out through the hilum to the pampiniform plexus "
                  "of the ovary.",
    "mesovarium_cut": "Mesovarium (cut edge): the peritoneal fold attaching the anterior border of the ovary to the "
                      "broad ligament; the vessels enter the hilum between its layers.",
    "primordial": "Primordial follicles: a primary oocyte (arrested in prophase I of meiosis since fetal life) "
                  "surrounded by a single layer of flat follicular cells. They form the resting pool in the outer "
                  "cortex; a few are recruited every day.",
    "primary": "Primary follicles: the follicular cells have become cuboidal granulosa cells (one layer in a unilaminar, "
               "several in a multilaminar primary follicle) and the zona pellucida appears between them and the "
               "growing primary oocyte. The stroma round them begins to form the theca.",
    "secondary": "Secondary (antral) follicles: many layers of granulosa cells in which small fluid-filled spaces "
                 "(Call-Exner bodies, vesicles) appear and coalesce into the antrum, under FSH. The oocyte, still "
                 "primary, has reached nearly full size.",
    "sec_theca": "Theca of secondary follicles: the stromal cells round the growing follicle organise into the theca "
                 "interna (steroidogenic) and theca externa, separated from the granulosa by a basement membrane.",
    "theca_ext": "Theca externa: the outer, fibrous layer of the follicle wall - concentric smooth-muscle-like "
                 "fibroblasts that merge with the stroma and may help expel the oocyte at ovulation.",
    "theca_int": "Theca interna: vascular layer of steroid-secreting cells with LH receptors that make androgens "
                 "(androstenedione). The two-cell model: theca makes androgen under LH, the granulosa cells convert "
                 "it to oestradiol with aromatase under FSH. Excess theca androgen underlies polycystic ovary "
                 "syndrome.",
    "granulosa": "Membrana granulosa: the stratified layer of granulosa cells lining the antrum, avascular behind "
                 "their basement membrane. They make oestradiol (aromatase, FSH-driven) and inhibin, and after "
                 "ovulation become the granulosa lutein cells of the corpus luteum. Granulosa cell tumours secrete "
                 "oestrogen.",
    "antrum": "Antrum: the large cavity of the vesicular follicle, full of follicular fluid (liquor folliculi) rich "
              "in oestrogen, which swells before ovulation to 2-2.5 cm. A follicle that fails to rupture can persist "
              "as a follicular (functional) cyst, which usually resolves in a cycle or two.",
    "cumulus": "Cumulus oophorus: the hillock of granulosa cells that projects into the antrum and holds the oocyte; "
               "it frees itself before ovulation and leaves with the oocyte.",
    "oocyte": "Oocytes: primary oocytes (arrested in prophase I since before birth) in the primordial, primary and "
              "secondary follicles; the oocyte of the mature vesicular follicle completes meiosis I just before "
              "ovulation (throwing off the first polar body) and is ovulated as a secondary oocyte arrested in "
              "metaphase II, which only completes meiosis if a sperm enters it.",
    "zona": "Zona pellucida: a thick glycoprotein coat (ZP1-ZP4) between the oocyte and the granulosa cells, pierced "
            "by their processes. ZP3 binds sperm and triggers the acrosome reaction; after fertilisation the "
            "cortical reaction hardens it to block polyspermy.",
    "corona": "Corona radiata: the innermost granulosa cells of the cumulus, radially arranged round the zona "
              "pellucida, which accompany the ovulated oocyte and must be penetrated by sperm (hyaluronidase).",
    "cl": "Corpus luteum: after ovulation, under LH, the collapsed follicle wall folds and its cells fill with lipid "
          "(yellow): large granulosa lutein cells make progesterone (and oestrogen, inhibin), smaller theca lutein "
          "cells make androgen and progesterone. Progesterone prepares the endometrium (secretory phase). Without "
          "pregnancy it regresses after ~14 days (luteolysis), progesterone falls and menstruation starts; in "
          "pregnancy hCG from the trophoblast rescues it until the placenta takes over at 8-10 weeks. Corpus "
          "luteum cysts may bleed and mimic an ectopic pregnancy.",
    "cl_clot": "Central clot of the corpus luteum (corpus haemorrhagicum): blood that fills the cavity of the "
               "ruptured follicle, later replaced by connective tissue.",
    "ca": "Corpus albicans: the white hyaline scar of dense collagen left when a corpus luteum degenerates; it is "
          "slowly resorbed over months.",
    "atretic": "Atretic follicle: most follicles never ovulate but degenerate (atresia) by apoptosis at any stage; "
               "the oocyte and granulosa break down and the thickened, wavy zona pellucida and glassy membrane are "
               "the last to go.",
    # ------------------------------------------------------------------ tube specimen
    "tube_serosa": "Serosa of the uterine tube: the peritoneum of the mesosalpinx wrapped round the tube - "
                   "mesothelium on a thin connective-tissue layer with the vessels and nerves.",
    "tube_muscle": "Muscular layer of the uterine tube: smooth muscle, an inner circular and a thinner outer "
                   "longitudinal layer, thin in the ampulla and thick in the isthmus. Its peristalsis (with the "
                   "cilia) carries the oocyte and embryo to the uterus in 3-4 days.",
    "tube_mucosa": "Mucosa of the uterine tube: in the ampulla a labyrinth of tall, branched longitudinal folds "
                   "(plicae) with a cellular lamina propria core, leaving only narrow clefts of lumen. Salpingitis "
                   "glues the folds together, trapping the embryo (ectopic pregnancy) or blocking the tube "
                   "(infertility, hydrosalpinx).",
    "tube_epi": "Tubal epithelium: simple columnar with two cell types - ciliated cells, most numerous in the "
                "infundibulum and ampulla, beating towards the uterus (oestrogen increases them), and non-ciliated "
                "secretory (peg) cells whose fluid nourishes the oocyte and helps capacitate sperm. Chlamydial "
                "damage to the cilia raises the risk of ectopic pregnancy.",
    "tube_vessels": "Blood vessels of the tube wall: branches of the uterine and ovarian arteries in the lamina "
                    "propria and muscle.",
    # ------------------------------------------------------------------ endometrium specimen
    "endo_myo": "Myometrium (inner layer): the thick smooth muscle of the uterine wall beneath the endometrium, "
                "crossed by the radial arteries. There is no submucosa: the endometrium sits directly on it.",
    "basalis": "Stratum basalis: the deep, permanent layer of the endometrium with the blind ends of the uterine "
               "glands, a dense stroma and the straight (basal) arteries. It regenerates the functional layer "
               "after menstruation.",
    "functionalis": "Stratum functionalis: the thick, shed layer of the endometrium. Shown in the mid-secretory "
                    "phase: oedematous stroma, saw-toothed glands and coiled spiral arteries, with stromal cells "
                    "beginning to decidualise round the implanting conceptus.",
    "ut_epi": "Uterine surface epithelium: simple columnar epithelium with ciliated and secretory cells, continuous "
              "with the glands. The conceptus attaches to it and invades through it around day 7; it then closes "
              "over the implantation site.",
    "ut_glands": "Uterine glands: simple tubular glands running from the surface into the basal layer. Straight and "
                 "narrow in the proliferative phase; coiled, saw-toothed and full of glycogen-rich secretion in "
                 "the secretory phase (histiotrophic nutrition of the embryo before the placenta works).",
    "spiral": "Spiral (coiled) arteries: continuations of the radial arteries that coil through the functional "
              "layer and respond to hormones. At the end of the cycle, falling progesterone makes them constrict "
              "rhythmically, the functional layer becomes ischaemic and is shed (menstruation). In pregnancy "
              "trophoblast remodels them into wide, low-resistance channels; failure of this remodelling underlies "
              "pre-eclampsia and fetal growth restriction.",
    "straight": "Straight (basal) arteries: short branches of the radial arteries supplying the basal layer. They do "
                "not respond to the hormones, so the basal layer survives menstruation.",
    "trophoblast_imp": "Trophoblast of the implanted blastocyst: the outer cells of the conceptus, invading the "
                       "endometrium as an outer syncytiotrophoblast (which secretes hCG - the basis of pregnancy "
                       "tests - and erodes maternal vessels into lacunae) and an inner cytotrophoblast; it forms the "
                       "chorion and the fetal part of the placenta. Abnormal trophoblast forms hydatidiform moles and "
                       "choriocarcinoma.",
    "chorionic": "Chorionic cavity (extraembryonic coelom): the fluid space inside the chorion in which the embryo, "
                 "amnion and yolk sac hang by the connecting stalk; it is obliterated as the amnion expands.",
    "amnion": "Amniotic sac (amnion): the thin membrane that forms above the epiblast in the second week and later "
              "surrounds the whole embryo.",
    "amn_cavity": "Amniotic cavity: the fluid-filled space between the amnion and the epiblast; amniotic fluid "
                  "later cushions the fetus and allows movement and lung development.",
    "epiblast": "Embryonic disc - epiblast (primitive ectoderm): the upper, columnar layer of the bilaminar disc, "
                "facing the amniotic cavity. In week 3 its cells migrate through the primitive streak to form all "
                "three germ layers: ectoderm (epidermis, nervous system, adrenal medulla), mesoderm (muscle, bone, "
                "connective tissue, blood, kidneys, gonads) and endoderm (lining of the gut and respiratory tract "
                "and their glands).",
    "hypoblast": "Embryonic disc - hypoblast (primitive endoderm): the lower, cuboidal layer of the bilaminar disc, "
                 "facing the yolk sac; it is replaced by definitive endoderm from the epiblast during gastrulation.",
    "yolk": "Yolk sac: the sac beneath the hypoblast. Human yolk sacs hold no yolk but make the first blood cells and "
            "primordial germ cells, and part of it is taken into the embryo as the gut.",
    "stalk": "Connecting stalk: the band of extraembryonic mesoderm that tethers the embryo to the chorion; it "
             "carries the allantois and the umbilical vessels and becomes the umbilical cord.",
    # ------------------------------------------------------------------ fertilisation row
    "ovulated": "Ovulated secondary oocyte: released at mid-cycle (about day 14, 36 hours after the LH surge), "
                "arrested in metaphase II, with its zona pellucida and corona radiata. It survives about 24 hours; "
                "sperm survive up to 5 days in the tract, so the fertile window is the 5 days before ovulation and "
                "the day of it.",
    "corona_ov": "Corona radiata of the ovulated oocyte: cumulus cells still attached to the zona pellucida; sperm "
                 "push through them with hyaluronidase and tail beating.",
    "sperm": "Sperm cells (drawn much larger than life relative to the oocyte): capacitated in the female tract, "
             "they reach the ampulla, pass the corona, bind ZP3 and undergo the acrosome reaction; one fuses with "
             "the oocyte membrane, which triggers the cortical reaction (block to polyspermy) and the completion of "
             "meiosis II.",
    "zona_emb": "Zona pellucida of the early embryo: persists round the cleaving embryo and prevents premature "
                "implantation in the tube; the blastocyst hatches from it (day 5-6) before implanting.",
    "zygote": "Zygote: the fertilised egg (day 1), with the second polar body extruded. Its cytoplasm is the "
              "oocyte's.",
    "pn_egg": "Egg (female) pronucleus: the haploid nucleus left when the oocyte completes meiosis II after sperm "
              "entry.",
    "pn_sperm": "Sperm (male) pronucleus: the decondensed sperm nucleus. The two pronuclei replicate their DNA, "
                "approach and their chromosomes mingle on the first mitotic spindle (syngamy), restoring the "
                "diploid number and setting the sex.",
    "cell2": "2-cell stage (about 30 hours): the first cleavage divides the zygote into two blastomeres inside the "
             "zona pellucida; cleavage divisions make the cells smaller without growth.",
    "cell4": "4-cell stage (about 40-48 hours), still travelling down the uterine tube.",
    "cell8": "8-cell stage (about day 3): the blastomeres flatten against one another (compaction).",
    "morula": "Morula (days 3-4, 12-32 cells): a solid mulberry-like ball of blastomeres that enters the uterus.",
    "trophoblast": "Blastocyst - trophoblast: the outer layer of flattened cells of the blastocyst (day 5), which "
                   "will attach to and invade the endometrium and form the chorion and fetal placenta.",
    "icm": "Blastocyst - inner cell mass (embryoblast): the cluster of cells at one pole of the blastocyst that forms "
           "the embryo itself (and the amnion and yolk sac); the source of embryonic stem cells. Splitting of the "
           "inner cell mass gives monochorionic twins.",
    "blastocele": "Blastocele (blastocyst cavity): the fluid-filled cavity of the blastocyst, pumped in by the "
                  "trophoblast. The blastocyst hatches from the zona and implants about day 6-7, usually in the "
                  "upper posterior wall of the uterus; implantation elsewhere is an ectopic pregnancy, and low in "
                  "the uterus gives placenta praevia.",
    # ------------------------------------------------------------------ breast
    "br_skin": "Skin of the breast (body of the breast): thin skin over the rounded body of the breast, extending "
               "from the 2nd to 6th ribs and from the sternum to the midaxillary line. Tethering of the skin by a "
               "tumour pulling on Cooper's ligaments dimples it; lymphatic blockage gives peau d'orange.",
    "areola": "Areola: the ring of pigmented, thin skin round the nipple, darkening in pregnancy, with smooth muscle "
              "and many sebaceous (areolar) glands.",
    "areolar_gl": "Areolar glands (of Montgomery): sebaceous glands with rudimentary mammary tissue that raise small "
                  "tubercles on the areola; their oily secretion protects the nipple during breastfeeding.",
    "nipple": "Nipple: a projection of pigmented skin with smooth muscle (erection with cold, touch, suckling) on "
              "which the 15-20 lactiferous ducts open separately. Usually at the 4th intercostal space in men and "
              "girls. New inversion, bloody discharge or eczema (Paget disease of the nipple, from an underlying "
              "carcinoma) need investigation.",
    "br_fat": "Adipose tissue of the breast: most of the non-lactating breast is fat, in lobules separated by "
              "Cooper's ligaments, with a retromammary fat layer over the pectoral fascia. Its amount determines "
              "breast size. Fat necrosis after trauma mimics a carcinoma.",
    "lobes": "Lobes of the mammary gland: 15-20 radially arranged compound tubulo-alveolar glands, each drained by "
             "one lactiferous duct, embedded in fibrous stroma and fat. The mammary gland is a modified apocrine "
             "sweat gland of the skin. Fibroadenomas (mobile 'breast mice' in young women) and fibrocystic change "
             "arise in the glandular tissue. Breast cancer (the commonest cancer in women) is most often invasive "
             "ductal carcinoma arising from the terminal duct-lobular unit, most commonly in the upper outer "
             "quadrant, where most gland tissue lies.",
    "tail": "Axillary tail (of Spence): the extension of the upper outer quadrant of the gland towards the axilla, "
            "sometimes passing through the deep fascia. It may be mistaken for a lymph node or lipoma, and is a "
            "common site of carcinoma because of the volume of gland in the upper outer quadrant.",
    "lobules": "Lobules (alveolar glands): clusters of secretory alveoli at the ends of the ducts - the terminal "
               "duct-lobular units. Few and small in the resting breast; in pregnancy (oestrogen, progesterone, "
               "prolactin) they proliferate enormously, and after delivery they secrete milk (prolactin) that is "
               "ejected by myoepithelial cells (oxytocin, let-down reflex). Lobular carcinoma arises here.",
    "ducts": "Lactiferous ducts: one main duct per lobe carries milk from the lobules to the nipple, lined by "
             "two-layered epithelium (luminal cells on myoepithelial cells). Ductal carcinoma in situ is confined "
             "within them; intraductal papilloma causes bloody nipple discharge; duct ectasia causes a cheesy "
             "discharge.",
    "sinus": "Lactiferous sinuses: the dilated segment of each duct beneath the areola, where milk collects; the "
             "baby's jaws compress the areola over them during suckling.",
    "cooper": "Suspensory ligaments (of Cooper): fibrous septa from the pectoral fascia through the breast to the "
              "dermis, dividing the fat into lobules and supporting the gland. A carcinoma that infiltrates and "
              "shortens them dimples the overlying skin.",
    "pect_fascia": "Pectoral fascia: the deep fascia over pectoralis major on which the breast rests, separated from "
                   "it by the loose retromammary space that lets the breast move. Fixation of a lump to it (on "
                   "contracting the muscle) suggests invasion.",
    "pectoralis": "Pectoralis major: the fan-shaped muscle behind the breast (flexes, adducts and medially rotates "
                  "the arm; lateral and medial pectoral nerves). Tumour invading it or the chest wall fixes the "
                  "breast. It is used as a flap in reconstruction.",
    "ribs": "Ribs (sectioned): the breast lies over the 2nd-6th ribs; carcinoma can invade the chest wall.",
    "intercostal": "Intercostal muscles: between the ribs, deep to pectoralis major; the intercostal perforating "
                   "branches of the internal thoracic artery and their lymphatics pierce them to reach the medial "
                   "breast.",
    "ax_nodes": "Axillary lymph nodes: about 75% of the lymph of the breast drains to the axillary nodes (pectoral, "
                "then central and apical; levels I-III relative to pectoralis minor), mainly from the lateral "
                "quadrants; the medial breast drains to the parasternal (internal thoracic) nodes, and some lymph "
                "crosses to the other breast or to the abdomen. Breast cancer spreads here first: sentinel node "
                "biopsy (blue dye/radiotracer) stages it, and axillary clearance can cause arm lymphoedema and "
                "injure the long thoracic nerve (winged scapula).",
}


def _sacral_frame():
    a = _sagittal(SACRUM_A)
    path = _spline(a, 0.03)
    t = np.gradient(path, axis=0)
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    post = np.stack([np.zeros(len(t)), -t[:, 2], t[:, 1]], -1)      # perpendicular, pointing backwards
    return path, t, post


def build_skeleton():
    parts = []
    # ---------------------------------------------------------------- sacrum and coccyx (midline)
    ant, t, post = _sacral_frame()
    s = np.linspace(0, 1, len(ant))
    b = np.interp(s, [0, 0.3, 0.7, 1], [0.17, 0.13, 0.08, 0.05])
    a = np.interp(s, [0, 0.25, 0.6, 1], [0.50, 0.40, 0.24, 0.11])
    centre = ant + post * b[:, None]
    vox = 0.013
    V = _grid(np.array([-0.56, -0.66, -1.0]), np.array([0.56, 0.60, -0.26]), vox)
    sac = _flat_tube(centre, a, b, cap0=0.035, cap1=0.03)
    x, y, z = V.axes()
    d, arcs = sac(x, y, z)
    # the alae are thin wings on either side of the bodies: pinch the section away from the midline
    d = (d + 0.06 * _smooth((np.abs(x) - 0.16) / 0.25) * (1 - arcs / sac.arc[-1])).astype(np.float32)
    # sacral canal and the four pairs of anterior sacral foramina
    _apply(V, d, _tube_d(centre + post * (b * 0.35)[:, None], np.interp(s, [0, 1], [0.045, 0.018])), "sub")
    for k, f in enumerate((0.2, 0.4, 0.6, 0.78)):
        i = int(f * (len(ant) - 1))
        for sx in (-1, 1):
            xo = np.array([sx * a[i] * 0.38, 0, 0])
            _apply(V, d, _tube_d(np.array([ant[i] + xo - post[i] * 0.03, ant[i] + xo + post[i] * (2.2 * b[i])]),
                                 0.024 - 0.003 * k), "sub")
    parts.append(_part(_clean(_mesh(V, d, 1.0)), "Sacrum", "Bony pelvis", "#e6dcc4", DESC["sacrum"], "bone",
                       rank=-3))
    cd = _empty(V)
    for k, p in enumerate(_sagittal(COCCYX)):
        r = 0.05 - 0.009 * k
        _apply(V, cd, _dist(_flat_tube(np.array([p + (0, 0.02, 0.012), p - (0, 0.02, 0.012)]), r * 1.3, r * 0.75,
                                       r * 0.6, r * 0.6)))
    parts.append(_part(_clean(_mesh(V, cd, 1.0)), "Coccyx", "Bony pelvis", "#e2d6bc", DESC["coccyx"], "bone",
                       rank=-3))

    # ---------------------------------------------------------------- L5 body, disc and spine above the sacrum
    top, up, fwd = centre[0] - t[0] * 0.03, -t[0], -post[0]
    V5 = _grid(np.array([-0.34, 0.25, -1.05]), np.array([0.34, 0.95, -0.15]), vox)
    up2 = up * 0.75 + np.array([0, 1.0, 0]) * 0.25
    up2 /= np.linalg.norm(up2)
    dd = _apply(V5, _empty(V5), _dist(_flat_tube(np.array([top + up * 0.012, top + up2 * 0.085]), 0.22, 0.155,
                                                 0.01, 0.01)))
    base = top + up2 * 0.10
    bd = _apply(V5, _empty(V5), _dist(_flat_tube(np.array([base, base + up2 * 0.24]), 0.22, 0.15, 0.02, 0.02)))
    canal = base + up2 * 0.13 - fwd * 0.25
    ring = [canal + np.array([math.cos(a) * 0.09, 0.0, 0.0]) - fwd * (math.sin(a) * 0.075)
            for a in np.linspace(-0.2, math.pi + 0.2, 9)]
    _apply(V5, bd, _tube_d(_spline(ring, 0.015), 0.028), "smin", 0.015)
    _apply(V5, bd, _dist(_flat_tube(np.array([canal - fwd * 0.07, canal - fwd * 0.26 - up2 * 0.07]), 0.025, 0.07,
                                    0.03, 0.03, side=(1.0, 0.0, 0.0))), "smin", 0.02)
    for sx in (-1, 1):                     # pedicles joining the arch to the body, and the transverse processes
        _apply(V5, bd, _tube_d(np.array([base + up2 * 0.13 + (sx * 0.1, 0, 0) - fwd * 0.12,
                                         canal + (sx * 0.1, 0, 0)]), 0.03), "smin", 0.015)
        _apply(V5, bd, _tube_d(np.array([canal + (sx * 0.1, 0, 0), canal + (sx * 0.27, 0.02, 0.0) - fwd * 0.02]),
                               np.array([0.035, 0.02])), "smin", 0.015)
    parts.append(_part(_clean(_mesh(V5, bd, 1.0)), "Fifth lumbar vertebra (L5)", "Bony pelvis", "#e6dcc4",
                       DESC["l5"], "bone", rank=-3))
    parts.append(_part(_clean(_mesh(V5, dd, 1.0)), "Lumbosacral intervertebral disc", "Bony pelvis", "#c9d7df",
                       DESC["disc"], "cartilage", rank=-3))

    # ---------------------------------------------------------------- hip bones and the symphysis between them
    parts.append(_part(_both(_hip_bone()), "Hip bone", "Bony pelvis", "#d8cdb5", DESC["hip"], "bone",
                       rank=-3))
    Vs = _grid(SYMPH_C - 0.26, SYMPH_C + 0.26, 0.008)
    sy = _dist(_flat_tube(np.array([SYMPH_C - SYMPH_AX * 0.17, SYMPH_C + SYMPH_AX * 0.17]), 0.022, 0.07, 0.05, 0.05))
    parts.append(_part(_clean(_mesh(Vs, _apply(Vs, _empty(Vs), sy), 0.8)), "Pubic symphysis", "Bony pelvis",
                       "#cfdde6", DESC["symphysis"], "cartilage", rank=-3))
    return parts


def _hip_bone():
    vox = 0.019
    V = _grid(np.array([0.0, -0.92, -0.78]), np.array([1.36, 0.86, 0.80]), vox)
    # wing of the ilium: a sheet between the arcuate line and the iliac crest, bowed so the iliac fossa is concave
    crest = _spline([(0.38, 0.36, -0.64), (0.72, 0.62, -0.50), (1.08, 0.72, -0.16), (1.22, 0.60, 0.22),
                     (1.16, 0.36, 0.56)], 0.02)
    base = _spline([(0.42, 0.12, -0.50), (0.55, 0.04, -0.28), (0.63, -0.02, 0.0), (0.70, -0.04, 0.25),
                    (0.86, 0.06, 0.52)], 0.02)
    cu = np.linspace(0, 1, 170)
    Cr = np.stack([np.interp(cu, np.linspace(0, 1, len(crest)), crest[:, c]) for c in range(3)], -1)
    Ba = np.stack([np.interp(cu, np.linspace(0, 1, len(base)), base[:, c]) for c in range(3)], -1)
    U_, V_ = np.meshgrid(cu, np.linspace(0, 1, 100), indexing="ij")
    P = Ba[:, None, :] * (1 - V_[..., None]) + Cr[:, None, :] * V_[..., None]
    bow = np.sin(np.pi * V_) * np.sin(np.pi * np.clip(U_ * 1.1, 0, 1))
    P[..., 0] += 0.07 * bow
    P[..., 2] -= 0.03 * bow
    th = 0.019 + 0.018 * V_ ** 4 + 0.03 * (1 - U_) ** 3 + 0.02 * (1 - V_) ** 3
    d = _cloud_d(P.reshape(-1, 3), th.ravel(), V)
    k = 0.03
    # pubic body beside the symphysis, superior ramus with the pubic tubercle, inferior ramus to the ischium
    _apply(V, d, _dist(_flat_tube(np.array([SYMPH_C + (0.10, 0, 0) - SYMPH_AX * 0.15,
                                            SYMPH_C + (0.10, 0, 0) + SYMPH_AX * 0.14]), 0.075, 0.065, 0.06, 0.06)), "smin", k)
    sup = _spline([(0.12, -0.33, 0.60), (0.28, -0.26, 0.52), (0.45, -0.20, 0.38), (0.56, -0.17, 0.26)], 0.03)
    _apply(V, d, _tube_d(sup, np.linspace(0.045, 0.075, len(sup))), "smin", k)
    _apply(V, d, _tube_d(np.array([(0.15, -0.30, 0.63), (0.17, -0.30, 0.66)]), 0.03), "smin", k)
    _apply(V, d, _tube_d(_spline([(0.13, -0.60, 0.48), (0.24, -0.70, 0.34), (0.34, -0.77, 0.18),
                                  (0.42, -0.80, 0.04)], 0.03), 0.035), "smin", k)
    # ischium: tuberosity, body up to the acetabulum, spine pointing medially and back
    _apply(V, d, _tube_d(_spline([(0.42, -0.82, 0.06), (0.47, -0.78, -0.04), (0.50, -0.66, -0.10),
                                  (0.56, -0.45, -0.02), (0.60, -0.28, 0.10)], 0.03), [0.075, 0.07, 0.085]), "smin", k)
    _apply(V, d, _tube_d(np.array([(0.55, -0.40, -0.12), (0.47, -0.35, -0.25), (0.42, -0.33, -0.33)]),
                         np.array([0.045, 0.028, 0.012])), "smin", k)
    # acetabular mass, body of the ilium, arcuate line (pelvic brim) and the auricular part against the sacrum
    _apply(V, d, _tube_d(np.array([(0.62, -0.26, 0.18), (0.64, -0.05, 0.12)]), 0.13), "smin", k)
    _apply(V, d, _tube_d(_spline([(0.36, 0.24, -0.46), (0.48, 0.10, -0.26), (0.55, -0.02, -0.02),
                                  (0.54, -0.12, 0.26), (0.38, -0.22, 0.48), (0.16, -0.29, 0.62)], 0.03), 0.028),
           "smin", k)
    _apply(V, d, _tube_d(np.array([(0.40, 0.30, -0.52), (0.45, 0.20, -0.40), (0.50, 0.05, -0.30)]),
                         np.array([0.09, 0.10, 0.08])), "smin", k)
    # thick iliac crest and the anterior superior and inferior iliac spines
    _apply(V, d, _tube_d(Cr, 0.028), "smin", 0.02)
    _apply(V, d, _tube_d(np.array([(1.12, 0.40, 0.55), (1.16, 0.36, 0.60)]), 0.04), "smin", 0.02)
    _apply(V, d, _tube_d(np.array([(0.84, 0.03, 0.52), (0.88, 0.02, 0.55)]), 0.035), "smin", 0.02)
    # socket of the acetabulum, opening laterally
    x, y, z = V.axes()
    sock = np.sqrt((x - 0.80) ** 2 + (y + 0.20) ** 2 + (z - 0.18) ** 2) - 0.16
    d = np.maximum(d, -sock)
    return _clean(_mesh(V, d.astype(np.float32), 1.0))


# =============================================================================== the vulval frame
class _Frame:
    """A curvilinear frame over the surface of the vulva and perineum.

    v is arc length along a median curve C from behind the anus, under the perineum and round the pubic arch to the
    top of the mons; w is distance along the outward normal of C (w > 0 is outside the body); u = x is lateral. The
    external genitalia are modelled as height fields in (u, v) and mapped out with world(u, w, v), so they wrap
    round the pelvic outlet the way they do in life - the mons faces forwards, the vestibule downwards."""

    def __init__(self, pts_yz):
        c = _spline(_sagittal(pts_yz), 0.004)
        self.c = c
        seg = np.linalg.norm(np.diff(c, axis=0), axis=1)
        self.arc = np.concatenate([[0.0], np.cumsum(seg)])
        t = np.gradient(c, axis=0)
        t /= np.linalg.norm(t, axis=1, keepdims=True)
        self.t = t
        self.n = np.stack([np.zeros(len(t)), -t[:, 2], t[:, 1]], -1)     # outward: down under the perineum
        self.length = float(self.arc[-1])

    def _interp(self, arr, v):
        v = np.asarray(v, np.float64)
        return np.stack([np.interp(v, self.arc, arr[:, c]) for c in range(3)], -1)

    def world(self, u, w, v):
        u, w, v = np.broadcast_arrays(np.asarray(u, np.float64), np.asarray(w, np.float64),
                                      np.asarray(v, np.float64))
        c = self._interp(self.c, v)
        n = self._interp(self.n, v)
        out = c + n * w[..., None]
        out[..., 0] = u
        return out

    def v_at_z(self, z):
        i = int(np.argmin(np.abs(self.c[:, 2] - z) + (self.c[:, 1] > -0.7) * 9))
        return float(self.arc[i])


VULVA = _Frame([(-0.86, -0.46), (-0.95, -0.26), (-1.00, -0.06), (-1.015, 0.14), (-0.99, 0.34), (-0.915, 0.53),
                (-0.79, 0.685), (-0.61, 0.80), (-0.40, 0.865), (-0.18, 0.885)])
V_ANUS = VULVA.v_at_z(-0.30)
V_FOURCHETTE = VULVA.v_at_z(0.06)
V_VAG = VULVA.v_at_z(0.17)
V_URETH = VULVA.v_at_z(0.345)
V_GLANS = VULVA.v_at_z(0.50)
V_COMMISSURE = VULVA.v_at_z(0.60)


# =============================================================================== uterus, cervix, vagina
def _unit(v):
    v = np.asarray(v, np.float64)
    return v / np.linalg.norm(v)


def _dirdeg(deg):
    """Unit vector in the median plane, `deg` above the horizontal, pointing forwards."""
    r = math.radians(deg)
    return np.array([0.0, math.sin(r), math.cos(r)])


EXT_OS = np.array([0.0, -0.30, -0.12])             # external os
DIR_CX = _dirdeg(50)                                # cervical axis (anteversion ~95 deg to the vagina)
INT_OS = EXT_OS + DIR_CX * 0.26                     # internal os
DIR_BODY = _dirdeg(15)                              # body tipped forward at the isthmus (anteflexion)
UT_AXIS = _spline([EXT_OS + DIR_CX * 0.035, EXT_OS + DIR_CX * 0.15, INT_OS, INT_OS + _dirdeg(33) * 0.05,
                   INT_OS + _dirdeg(33) * 0.05 + DIR_BODY * 0.14, INT_OS + _dirdeg(33) * 0.05 + DIR_BODY * 0.30],
                  0.012)
_ua = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(UT_AXIS, axis=0), axis=1))])
S_INT = float(_ua[np.argmin(np.linalg.norm(UT_AXIS - INT_OS, axis=1))])     # arc length at the internal os
S_ISTH = S_INT + 0.06
S_CORNU = float(_ua[-1]) - 0.05
UT_END = float(_ua[-1])


def _at(s):
    """Point on the uterine axis at arc length s."""
    return np.stack([np.interp(s, _ua, UT_AXIS[:, c]) for c in range(3)], -1)


def uterus_field():
    st = [0, S_INT, S_INT + 0.05, S_INT + 0.17, S_CORNU, UT_END]
    fr = np.asarray(st) / UT_END
    a = np.interp(_ua / UT_END, fr, [0.112, 0.12, 0.125, 0.19, 0.245, 0.25])
    b = np.interp(_ua / UT_END, fr, [0.100, 0.10, 0.100, 0.128, 0.135, 0.13])
    return _flat_tube(UT_AXIS, a, b, cap0=0.035, cap1=0.10)


def cavity_field():
    m = _ua >= S_INT - 0.005
    path = UT_AXIS[m]
    arc = _ua[m]
    a = np.interp(arc, [S_INT, S_INT + 0.06, S_CORNU, UT_END], [0.012, 0.030, 0.165, 0.17])
    b = np.interp(arc, [S_INT, S_CORNU, UT_END], [0.008, 0.011, 0.011])
    return _flat_tube(path, a, b, cap0=0.01, cap1=0.03)


def canal_field():
    m = _ua <= S_INT + 0.004
    path = np.vstack([EXT_OS - DIR_CX * 0.03, UT_AXIS[m]])
    k = np.linspace(0, 1, len(path))
    a = np.interp(k, [0, 0.12, 0.5, 1], [0.036, 0.034, 0.048, 0.016])
    b = np.interp(k, [0, 0.12, 0.5, 1], [0.016, 0.018, 0.024, 0.009])
    return _flat_tube(path, a, b, cap0=0.02, cap1=0.012)


def cervix_vaginal_d():
    """The part of the cervix that projects into the vault (portio vaginalis), as a distance field."""
    f = uterus_field()

    def g(x, y, z):
        d, s = f(x, y, z)
        ax = (x - EXT_OS[0]) * DIR_CX[0] + (y - EXT_OS[1]) * DIR_CX[1] + (z - EXT_OS[2]) * DIR_CX[2]
        return np.maximum(d, ax - 0.12)
    g.bmin, g.bmax = EXT_OS - 0.2, EXT_OS + 0.25
    return g


VAG_PATH = None


def vagina_path():
    """Centreline from the introitus (in the vestibule) to the vault round the cervix."""
    o = VULVA.world(0.0, -0.105, V_VAG)
    return _spline([o, o + (0, 0.06, -0.035), (0.0, -0.62, 0.0), (0.0, -0.44, -0.10), (0.0, -0.29, -0.18)], 0.015)


def vagina_fields():
    path = vagina_path()
    k = np.linspace(0, 1, len(path))
    st = [0, 0.12, 0.55, 0.78, 1]
    outer = _flat_tube(path, np.interp(k, st, [0.085, 0.10, 0.125, 0.17, 0.20]),
                       np.interp(k, st, [0.050, 0.052, 0.056, 0.085, 0.13]), cap0=0.012, cap1=0.085)
    lumen = _flat_tube(path, np.interp(k, st, [0.045, 0.06, 0.085, 0.13, 0.165]),
                       np.interp(k, st, [0.016, 0.015, 0.016, 0.022, 0.06]), cap0=0.03, cap1=0.05)
    return path, outer, lumen


def _mx(*fs):  # noqa: E302
    """Intersection of fields (negative inside); `-f` is the complement, so A minus B is _mx(A, -B)."""
    out = fs[0]
    for f in fs[1:]:
        out = np.maximum(out, f)
    return out.astype(np.float32)


def _mn(*fs):
    out = fs[0]
    for f in fs[1:]:
        out = np.minimum(out, f)
    return out.astype(np.float32)


def _sph(x, y, z, c, r):
    return np.sqrt((x - c[0]) ** 2 + (y - c[1]) ** 2 + (z - c[2]) ** 2) - r


def _edt_from(field, vox):
    """Distance from the region field < 0, smoothed a little so the layers cut from it have no voxel steps."""
    return ndimage.gaussian_filter(_signed(field < 0, vox), 1.0)


def build_uterus():
    parts = []
    vox = 0.007
    V = _grid(np.array([-0.29, -0.43, -0.30]), np.array([0.29, 0.20, 0.53]), vox)
    x, y, z = V.axes()
    D, s = uterus_field()(x, y, z)
    D = (D + 0.0025 * fbm3(x * 9, y * 9, z * 9, 1.0, 2, 3)).astype(np.float32)
    s = np.broadcast_to(s, V.shape)
    lumen = _mn(cavity_field()(x, y, z)[0], canal_field()(x, y, z)[0])
    FL = _edt_from(lumen, vox)                                    # distance from the cavity and canal
    ax = np.broadcast_to((x - EXT_OS[0]) * DIR_CX[0] + (y - EXT_OS[1]) * DIR_CX[1] + (z - EXT_OS[2]) * DIR_CX[2],
                         V.shape)
    vault = _apply(V, _empty(V), _dist(vagina_fields()[1])) - 0.004
    tissue = _mx(D, -lumen)
    upper = (S_INT - s).astype(np.float32)                        # < 0 above the internal os
    endo_f = _mx(tissue, upper, FL - 0.030)
    endo_b = _mx(tissue, upper, 0.030 - FL, FL - 0.046)
    endocx = _mx(tissue, -upper, FL - 0.018)
    peri = _mx(tissue, (S_INT - 0.02) - s, -(D + 0.014), 0.046 - FL)
    ecto = _mx(tissue, ax - 0.16, vault, -(D + 0.014), 0.018 - FL)
    # os rings: the narrowings at either end of the canal, cut out of their layers so they can be picked
    int_os = _mx(_mn(endocx, endo_b, endo_f), _sph(x, y, z, INT_OS, 0.05), np.abs(s - S_INT) - 0.018)
    ext_os = _mx(_mn(ecto, endocx), _sph(x, y, z, EXT_OS, 0.055), ax - 0.03)
    endo_f, endo_b, endocx, ecto = (_mx(f, -int_os, -ext_os) for f in (endo_f, endo_b, endocx, ecto))
    # the intramural part of each uterine tube crosses the wall at the cornu
    tube_ch = _empty(V)
    for sx in (-1, 1):
        _apply(V, tube_ch, _tube_d(_intramural_path(sx), 0.024))
    myo = _mx(tissue, upper, 0.046 - FL, D + 0.014, -tube_ch)
    stroma = _mx(tissue, -upper, -endocx, -ecto, -peri, -ext_os, -int_os, -tube_ch)
    regions = [("Fundus of uterus (myometrium)", _mx(myo, S_CORNU - s), "#c26b66", "fundus"),
               ("Body of uterus (myometrium)", _mx(myo, S_ISTH - s, s - S_CORNU), "#c9746e", "body"),
               ("Isthmus of uterus (myometrium)", _mx(myo, s - S_ISTH), "#cf8078", "isthmus")]
    for name, f, col, key in regions:
        parts.append(_part(_clean(_mesh(V, f, 0.7)), name, "Uterus", col, DESC[key], "muscle", rank=0.5))
    parts.append(_part(_clean(_mesh(V, _mx(peri, -tube_ch), 0.6)), "Perimetrium", "Uterus", "#efc3b4",
                       DESC["perimetrium"], "serosa", alpha=0.55, rank=1.0))
    parts.append(_part(_clean(_mesh(V, endo_f, 0.7)), "Endometrium - functional layer", "Uterus", "#b8475a",
                       DESC["endo_f"], "mucosa", rank=0.3))
    parts.append(_part(_clean(_mesh(V, endo_b, 0.6)), "Endometrium - basal layer", "Uterus", "#8e3446",
                       DESC["endo_b"], "mucosa", rank=0.2))
    parts.append(_part(_clean(_mesh(V, _mx(lumen, D, upper), 0.7)), "Uterine cavity", "Uterus", "#f4d3d6",
                       DESC["cavity"], "csf", alpha=0.45, rank=0.1))
    parts.append(_part(_clean(_mesh(V, stroma, 0.7)), "Cervix of uterus", "Cervix", "#d38f8c", DESC["cervix"],
                       "fascia", rank=0.4))
    parts.append(_part(_clean(_mesh(V, ecto, 0.6)), "Ectocervix & transformation zone", "Cervix", "#eba7ab",
                       DESC["ectocervix"], "mucosa", rank=0.45))
    parts.append(_part(_clean(_mesh(V, endocx, 0.6)), "Endocervical mucosa (plicae palmatae)", "Cervix", "#c7667a",
                       DESC["endocervix"], "mucosa", rank=0.3))
    parts.append(_part(_clean(_mesh(V, _mx(lumen, -upper), 0.7)), "Cervical canal", "Cervix", "#f6e2cf",
                       DESC["canal"], "csf", alpha=0.5, rank=0.1))
    parts.append(_part(_clean(_mesh(V, int_os, 0.6), 20), "Internal os", "Cervix", "#f0a0b0", DESC["int_os"],
                       "mucosa", rank=0.5))
    parts.append(_part(_clean(_mesh(V, ext_os, 0.6), 20), "External os", "Cervix", "#f2a6b6", DESC["ext_os"],
                       "mucosa", rank=0.5))
    return parts


def _intramural_path(sx):
    c = _at(S_CORNU - 0.012)
    return np.array([c + (sx * 0.14, 0.0, 0.0), c + (sx * 0.2, 0.004, -0.004), c + (sx * 0.27, 0.01, -0.01)])


def build_vagina():
    parts = []
    vox = 0.0085
    path, outer, lumen = vagina_fields()
    V = _grid(np.array([-0.24, -1.02, -0.40]), np.array([0.24, -0.08, 0.30]), vox)
    x, y, z = V.axes()
    cxd = cervix_vaginal_d()(x, y, z)
    O, sv = outer(x, y, z)
    Lm, _ = lumen(x, y, z)
    C = uterus_field()(x, y, z)[0]
    sv = np.broadcast_to(sv, V.shape)
    ridges = (0.003 * np.sin(sv * 2 * math.pi / 0.042) * _smooth((0.6 - sv / outer.arc[-1]) / 0.2)
              * _smooth((0.05 - np.abs(x)) / 0.02))
    Lm = (Lm + ridges).astype(np.float32)
    # the cervix pierces the dome of the vagina; the fornix is the recess left round it
    wall = _mx(O, -Lm, 0.001 - C)
    lum = _mx(Lm, O, 0.001 - C)
    FL = _edt_from(_mn(lum, C), vox)
    fornix = _mx(wall, cxd - 0.075, outer.arc[-1] * 0.6 - sv)
    orifice = _mx(wall, sv - 0.035)
    mucosa = _mx(wall, FL - 0.014, -fornix, -orifice)
    muscular = _mx(wall, -mucosa, -fornix, -orifice)
    parts.append(_part(_clean(_mesh(V, muscular, 0.7)), "Vagina", "Vagina", "#cf8583", DESC["vagina"], "muscle",
                       rank=0.4))
    parts.append(_part(_clean(_mesh(V, mucosa, 0.6)), "Vaginal rugae (mucosa)", "Vagina", "#e59aa3", DESC["rugae"],
                       "mucosa", rank=0.3))
    parts.append(_part(_clean(_mesh(V, fornix, 0.7)), "Fornix of vagina", "Vagina", "#d97f8c", DESC["fornix"],
                       "mucosa", rank=0.5))
    parts.append(_part(_clean(_mesh(V, orifice, 0.6)), "Vaginal orifice (introitus)", "Vagina", "#c96476",
                       DESC["orifice"], "mucosa", rank=0.5))
    parts.append(_part(_clean(_mesh(V, _mx(lum, 0.02 - sv), 0.7)), "Vaginal canal (lumen)", "Vagina", "#f6dde0",
                       DESC["vag_lumen"], "csf", alpha=0.25, rank=0.1))
    # hymen: a thin crescent of mucosa on the posterior rim of the introitus
    t0, t1 = path[0], path[3]
    ax = _unit(t1 - t0)
    nrm = np.cross(ax, (1.0, 0.0, 0.0))
    ang = np.linspace(0.25 * math.pi, 0.75 * math.pi, 24)
    c = t0 + ax * 0.028
    crest = np.stack([c + (0.05 * math.cos(t), 0, 0) - nrm * (0.012 * math.sin(t)) for t in ang])
    hy = _flat_tube(crest, 0.010, 0.003, side=ax)
    Vh = _grid(c - 0.09, c + 0.09, 0.0025)
    parts.append(_part(_clean(_mesh(Vh, _apply(Vh, _empty(Vh), _dist(hy)), 0.7), 10), "Hymen (remnant)", "Vagina",
                       "#f0b9be", DESC["hymen"], "mucosa", rank=0.5))
    return parts


# =============================================================================== neighbouring organs
BLADDER_C = np.array([0.0, -0.335, 0.26])
BLADDER_NECK = np.array([0.0, -0.53, 0.085])
RECTUM_PATH = [(0.0, 0.20, -0.35), (0.0, 0.02, -0.425), (0.0, -0.18, -0.47), (0.0, -0.38, -0.41),
               (0.0, -0.53, -0.29), (0.0, -0.585, -0.255)]


def bladder_field():
    def f(x, y, z):
        px, py, pz = x - BLADDER_C[0], y - BLADDER_C[1], z - BLADDER_C[2]
        # an empty-ish bladder: a flattened dome whose upper surface is pressed in by the uterus
        py2 = py + 0.05 * np.clip(1 - (px / 0.24) ** 2 - (pz / 0.2) ** 2, 0, 1)
        r = np.array([0.25, 0.17, 0.21])
        k0 = np.sqrt((px / r[0]) ** 2 + (py2 / r[1]) ** 2 + (pz / r[2]) ** 2)
        k1 = np.sqrt((px / r[0] ** 2) ** 2 + (py2 / r[1] ** 2) ** 2 + (pz / r[2] ** 2) ** 2)
        e = k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)
        neck = _tube_d(np.array([BLADDER_C + (0, -0.06, -0.06), BLADDER_NECK]), np.array([0.09, 0.035]))(x, y, z)
        return smin(e, neck, 0.05)
    f.bmin, f.bmax = BLADDER_C - 0.3, BLADDER_C + 0.3
    return f


def urethra_path():
    o = VULVA.world(0.0, -0.10, V_URETH)
    return _spline([BLADDER_NECK + (0, 0.03, -0.03), BLADDER_NECK, (0.0, -0.70, 0.165), o], 0.012)


def rectum_path():
    return _spline(RECTUM_PATH, 0.015)


def anal_path():
    a = VULVA.world(0.0, 0.0, V_ANUS)
    return _spline([RECTUM_PATH[-2], RECTUM_PATH[-1], (0.0, -0.74, -0.285), a + (0, 0.04, 0), a - (0, 0.012, 0)],
                   0.012)


def rectum_field():
    rp, ap = rectum_path(), anal_path()
    f1 = _tube_d(rp, [0.14, 0.15, 0.155, 0.14, 0.12, 0.10])
    f2 = _tube_d(ap, [0.10, 0.09, 0.08, 0.065, 0.05])

    def f(x, y, z):
        return np.minimum(f1(x, y, z), f2(x, y, z))
    f.bmin, f.bmax = np.minimum(f1.bmin, f2.bmin), np.maximum(f1.bmax, f2.bmax)
    return f


def build_neighbours():
    parts = []
    vox = 0.011
    # bladder: a wall round an irregular lumen, kept clear of the uterus and vagina it rests against
    V = _grid(BLADDER_C - (0.31, 0.25, 0.3), BLADDER_C + (0.31, 0.22, 0.3), vox)
    bd = _apply(V, _empty(V), bladder_field())
    ut = _apply(V, _empty(V), _dist(uterus_field()))
    vg = _apply(V, _empty(V), _dist(vagina_fields()[1]))
    inside = (bd < 0) & (ut > 0.012) & (vg > 0.012)
    depth = -_signed(inside, vox)
    wall = inside & (depth < 0.034)
    lum = inside & ~wall
    parts.append(_part(_clean(_mesh(V, _signed(wall, vox), 1.0)), "Urinary bladder", "Neighbouring organs",
                       "#d6a88e", DESC["bladder"], "organ", rank=-1))
    parts.append(_part(_clean(_mesh(V, _signed(lum, vox), 1.0)), "Urine in bladder", "Neighbouring organs",
                       "#f1e6a8", DESC["urine"], "csf", alpha=0.25, rank=-1, label=False))
    # urethra and ureters
    up = urethra_path()
    sw = Sweep(up, 40, max(20, len(up)))
    parts.append(_part(sw.shell(lambda T, S: 0.006 + 0.004 * np.cos(2 * T) ** 2, 0.03), "Urethra",
                       "Neighbouring organs", "#d69482", DESC["urethra"], "organ", rank=-1))
    ur = _spline([(0.40, 0.52, -0.40), (0.47, 0.22, -0.37), (0.46, -0.05, -0.30), (0.40, -0.21, -0.18),
                  (0.26, -0.27, -0.05), (0.16, -0.35, 0.07), (0.10, -0.42, 0.13)], 0.015)
    parts.append(_part(_both(tube(ur, 0.021, 16)), "Ureter", "Neighbouring organs", "#eadba4", DESC["ureter"],
                       "organ", rank=-1))
    # rectum and anal canal, hollow, lying in the hollow of the sacrum
    rp = rectum_path()
    sw = Sweep(rp, 72, len(rp))
    prof = lambda T, S: np.interp(S, np.linspace(0, 1, 6), [0.14, 0.15, 0.155, 0.14, 0.12, 0.10])  # noqa: E731
    fold = lambda T, S: sum(0.035 * np.exp(-((S - s0) / 0.035) ** 2) * np.clip(np.cos(T - ph), 0, 1) ** 2  # noqa
                            for s0, ph in ((0.22, 2.0), (0.45, -1.2), (0.62, 2.2)))
    parts.append(_part(sw.shell(lambda T, S: prof(T, S) - 0.022 - fold(T, S), prof), "Rectum",
                       "Neighbouring organs", "#b98070", DESC["rectum"], "organ", rank=-1))
    ap = anal_path()
    sw = Sweep(ap, 56, len(ap))
    ar = lambda T, S: np.interp(S, [0, 0.25, 0.5, 0.8, 1], [0.10, 0.09, 0.08, 0.065, 0.05])  # noqa: E731
    parts.append(_part(sw.shell(lambda T, S: ar(T, S) * 0.18 * (1 + 0.5 * np.cos(4 * T) ** 2), ar),
                       "Anal canal & anus", "Neighbouring organs", "#a86e64", DESC["anal"], "organ", rank=-1))
    return parts


# =============================================================================== pelvic floor
def _floor_surface(nu=60, nv=24):
    """Left levator ani as a (s, r) grid: s runs from the pubis to the ischial spine along its origin, r from the
    origin down to the free medial edge (hiatus in front, anococcygeal raphe and coccyx behind)."""
    origin = _spline([(0.10, -0.50, 0.46), (0.26, -0.47, 0.35), (0.38, -0.42, 0.20), (0.47, -0.37, 0.0),
                      (0.47, -0.33, -0.18), (0.43, -0.31, -0.31)], 0.01)
    medial = _spline([(0.10, -0.60, 0.40), (0.125, -0.72, 0.14), (0.115, -0.79, -0.08), (0.055, -0.76, -0.36),
                      (0.0, -0.66, -0.47), (0.0, -0.55, -0.565)], 0.01)
    su = np.linspace(0, 1, nu)
    O = np.stack([np.interp(su, np.linspace(0, 1, len(origin)), origin[:, c]) for c in range(3)], -1)
    M = np.stack([np.interp(su, np.linspace(0, 1, len(medial)), medial[:, c]) for c in range(3)], -1)
    r = np.linspace(0, 1, nv)
    P = O[:, None, :] * (1 - r[None, :, None]) + M[:, None, :] * r[None, :, None]
    P[..., 1] -= 0.05 * np.sin(np.pi * r)[None, :] * np.sin(np.pi * np.clip(su * 1.2, 0, 1))[:, None]
    return P


def build_floor():
    parts = []
    P = _floor_surface()
    nu, nv, _ = P.shape
    th = 0.028 + 0.012 * np.sin(np.pi * np.linspace(0, 1, nv))[None, :] * np.ones((nu, 1))
    lev = _both(_sheet(P, th))
    parts.append(_part(lev, "Levator ani", "Pelvic floor", "#9e443e", DESC["levator"], "muscle", rank=-0.5,
                       detail=(0.07, 320.0, 0.0, 0)))
    # coccygeus: a triangle from the ischial spine fanning to the side of the coccyx and lower sacrum
    ant, t, post = _sacral_frame()
    apex = np.array([0.42, -0.325, -0.325])
    edge = _spline([(0.06, -0.52, -0.585), (0.10, -0.44, -0.635), (0.15, -0.30, -0.675)], 0.01)
    k = np.linspace(0, 1, 30)
    E = np.stack([np.interp(k, np.linspace(0, 1, len(edge)), edge[:, c]) for c in range(3)], -1)
    r = np.linspace(0, 1, 16)
    Q = apex[None, None, :] * (1 - r[None, :, None]) + E[:, None, :] * r[None, :, None]
    Q = Q + np.array([0.0, 0.0, 0.0])
    parts.append(_part(_both(_sheet(Q, 0.03)), "Coccygeus", "Pelvic floor", "#8f3d39", DESC["coccygeus"], "muscle",
                       rank=-0.5, detail=(0.07, 320.0, 0.0, 0)))
    return parts


# =============================================================================== adnexa, ligaments and vessels
def _half_width(s_vals):
    """Lateral half-width of the uterus at axis stations s (probed from its field)."""
    fl = uterus_field()
    xs = np.linspace(0.0, 0.4, 400)
    out = []
    for sv in np.atleast_1d(s_vals):
        p = _at(sv)
        d = fl(xs, np.full(400, p[1]), np.full(400, p[2]))[0]
        out.append(xs[int(np.argmax(d > 0))])
    return np.array(out)


class _Adnexa:
    """Left-sided layout of the tube, ovary and broad ligament (mirrored for the right)."""

    def __init__(self):
        sm = np.linspace(S_CORNU - 0.012, S_INT - 0.07, 16)
        hw = _half_width(sm)
        self.U = np.array([_at(sv) + (w - 0.004, 0.0, 0.0) for sv, w in zip(sm, hw)])        # uterine margin
        t0 = _intramural_path(1)[-1]
        self.T = _spline([t0, (0.36, 0.02, 0.29), (0.46, 0.06, 0.22), (0.56, 0.10, 0.12), (0.605, 0.11, 0.05)],
                         0.01)                                                                 # free edge (tube)
        self.W = _spline([self.T[-1], (0.60, -0.06, -0.02), (0.55, -0.20, -0.08), (0.50, -0.31, -0.12)], 0.01)
        self.B = _spline([self.U[-1], (0.24, -0.29, -0.09), (0.38, -0.32, -0.12), self.W[-1]], 0.01)

    @staticmethod
    def _curve(c, t):
        k = np.linspace(0, 1, len(c))
        return np.stack([np.interp(t, k, c[:, i]) for i in range(3)], -1)

    def sheet(self, u, v):
        """Coons patch of the broad ligament; u from the uterus (0) to the side wall (1), v from the free edge (0)
        down to the base (1)."""
        u, v = np.broadcast_arrays(np.asarray(u, float), np.asarray(v, float))
        T, B = self._curve(self.T, u), self._curve(self.B, u)
        Uc, Wc = self._curve(self.U, v), self._curve(self.W, v)
        u_, v_ = u[..., None], v[..., None]
        c = ((1 - u_) * (1 - v_) * self.T[0] + u_ * (1 - v_) * self.T[-1] + (1 - u_) * v_ * self.B[0]
             + u_ * v_ * self.B[-1])
        return (1 - v_) * T + v_ * B + (1 - u_) * Uc + u_ * Wc - c

    def normal(self, u, v, eps=1e-3):
        du = self.sheet(u + eps, v) - self.sheet(u - eps, v)
        dv = self.sheet(u, v + eps) - self.sheet(u, v - eps)
        n = np.cross(du, dv)
        n = n / np.linalg.norm(n)
        return n if n[1] > 0 else -n            # the posterior surface faces up and back

    def ovary(self):
        c = self.sheet(0.72, 0.40) + self.normal(0.72, 0.40) * 0.085
        ax = _unit((0.22, 1.0, -0.12))
        return c, ax


ADNEXA = None


def _adnexa():
    global ADNEXA
    if ADNEXA is None:
        ADNEXA = _Adnexa()
    return ADNEXA


def _split_v(u):
    """Line on the broad ligament through the ovarian ligament and mesovarium: mesosalpinx above, mesometrium
    below."""
    return 0.30 + 0.10 * u


def _tube_path():
    ad = _adnexa()
    oc, ax = ad.ovary()
    pn = ad.normal(0.9, 0.3)
    top = oc + ax * 0.19
    mouth = oc + ax * 0.05 + pn * 0.075 + np.array([0.07, 0.0, 0.0])
    free = _spline([ad.T[-6], ad.T[-1], top + (0.07, 0.02, 0.02), top + (0.09, -0.02, 0.0) + pn * 0.06,
                    mouth + (0.02, 0.03, 0.0), mouth], 0.01)
    return np.vstack([_intramural_path(1)[:-1], ad.T[:-6], free])


def build_adnexa():
    parts = []
    ad = _adnexa()
    oc, ax = ad.ovary()
    # ------------------------------------------------------------------ uterine tube, segment by segment
    path = _tube_path()
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
    L = arc[-1]
    s_im = float(np.linalg.norm(_intramural_path(1)[-1] - _intramural_path(1)[0]))
    s_is = s_im + 0.30
    s_amp = L - 0.07
    n_s = max(80, int(L / 0.006))
    sw = Sweep(path, 36, n_s)
    S = sw.S * L

    def r_out(T, S_):
        a = S_ * L
        r = np.interp(a, [0, s_im, s_is, s_is + 0.12, s_amp, L], [0.013, 0.015, 0.02, 0.034, 0.042, 0.085])
        return r * (1 + 0.05 * np.sin(3 * T + a * 20))

    def r_in(T, S_):
        a = S_ * L
        base = np.interp(a, [0, s_im, s_is, s_is + 0.12, s_amp, L], [0.003, 0.004, 0.006, 0.02, 0.028, 0.074])
        return base * (1 - 0.25 * np.clip(np.cos(7 * T + a * 6), 0, 1))
    segs = [("Uterine (intramural) part of uterine tube", 0, s_im, "#e0948a", "tube_im"),
            ("Isthmus of uterine tube", s_im, s_is, "#e39c90", "tube_isth"),
            ("Ampulla of uterine tube", s_is, s_amp, "#e8a597", "tube_amp"),
            ("Infundibulum of uterine tube", s_amp, L, "#e6908c", "tube_inf")]
    for name, a0, a1, col, key in segs:
        k0, k1 = int(a0 / L * (n_s - 1)), int(np.ceil(a1 / L * (n_s - 1)))
        sub = Sweep(sw.path[k0:k1 + 1], 36, k1 - k0 + 1)
        sub.S = sw.S[:, k0:k1 + 1]
        m = sub.shell(r_in, r_out)
        parts.append(_part(_both(m), name, "Uterine tubes", col, DESC[key], "mucosa", rank=1.2))
    # fimbriae round the mouth, and the abdominal ostium
    mouth, tdir = path[-1], _unit(path[-1] - path[-4])
    side = _unit(np.cross(tdir, (0.0, 1.0, 0.0)))
    up = np.cross(side, tdir)
    rng = np.random.default_rng(12)
    fim = Mesh()
    for i in range(20):
        th = 2 * math.pi * i / 20 + rng.uniform(-0.12, 0.12)
        rad = side * math.cos(th) + up * math.sin(th)
        base = mouth + rad * 0.074 - tdir * 0.004
        length = rng.uniform(0.05, 0.085)
        tip = base + (tdir * 0.6 + rad * 0.8) * length + rng.normal(0, 0.012, 3)
        mid = (base + tip) / 2 + rad * 0.012 + rng.normal(0, 0.006, 3)
        fp = smooth_path(np.array([base, mid, tip]), 12)
        fim.extend(tube(fp, np.linspace(0.012, 0.004, len(fp)), 8))
    # the ovarian fimbria: one long fringe running to the tubal pole of the ovary
    top_pole = oc + ax * 0.13
    fp = smooth_path(np.array([mouth - up * 0.06, (mouth + top_pole) / 2 - up * 0.02, top_pole + (0.02, 0.01, 0)]), 20)
    fim.extend(tube(fp, np.linspace(0.016, 0.008, len(fp)), 10))
    parts.append(_part(_both(fim), "Fimbriae", "Uterine tubes", "#e8837f", DESC["fimbriae"], "mucosa", rank=1.3))
    ring = np.array([mouth + (side * math.cos(t) + up * math.sin(t)) * 0.07 + tdir * 0.002
                     for t in np.linspace(0, 2 * math.pi, 48)])
    ost = tube(np.vstack([ring, ring[:1]]), 0.007, 8)
    parts.append(_part(_both(ost), "Abdominal ostium of uterine tube", "Uterine tubes", "#b04c5c",
                       DESC["ostium"], "mucosa", rank=1.3))

    # ------------------------------------------------------------------ ovary in place
    Vo = _grid(oc - 0.17, oc + 0.17, 0.0068)
    x, y, z = Vo.axes()
    rot = np.stack([_unit(np.cross(ax, (0.0, 0.0, 1.0))), ax, _unit(np.cross(_unit(np.cross(ax, (0, 0, 1.0))), ax))],
                   1)
    from .sdf import ellipsoid as sdf_ellipsoid, sphere as sdf_sphere
    f, _, _ = sdf_ellipsoid(oc, (0.052, 0.145, 0.078), rot)
    d = np.broadcast_to(f(x, y, z), Vo.shape).astype(np.float32)
    rng = np.random.default_rng(4)
    for k in range(9):                     # follicles and a corpus luteum bulging the surface; a few scars
        dirn = _unit(rng.normal(size=3))
        r = 0.045 if k == 0 else rng.uniform(0.012, 0.024)
        c = oc + rot @ (np.array([0.052, 0.145, 0.078]) * dirn * 0.86)
        g, _, _ = sdf_sphere(c, r)
        d = smin(d, g(x, y, z), 0.012).astype(np.float32)
    d += (0.0035 * fbm3(x * 40, y * 40, z * 40, 1.0, 2, 8)).astype(np.float32)
    parts.append(_part(_both(_clean(_mesh(Vo, d, 0.9))), "Ovary", "Ovaries", "#eedcc8", DESC["ovary"], "gland",
                       rank=1.4))

    # ------------------------------------------------------------------ broad ligament and its three parts
    nu, nv = 60, 40
    uu = np.linspace(0.0, 1.0, nu)
    for name, v0f, v1f, key, col in (("Broad ligament - mesosalpinx", lambda u: 0.0 * u, _split_v, "mesosalpinx",
                                      "#f1d6c8"),
                                     ("Broad ligament - mesometrium", _split_v, lambda u: 1.0 + 0 * u, "mesometrium",
                                      "#efd0c0")):
        U_ = np.repeat(uu[:, None], nv, 1)
        V_ = v0f(U_) + (v1f(U_) - v0f(U_)) * np.linspace(0, 1, nv)[None, :]
        P = ad.sheet(U_, V_)
        parts.append(_part(_both(_sheet(P, 0.012)), name, "Ligaments", col, DESC[key], "serosa", alpha=0.55,
                           rank=0.8))
    # mesovarium: a short fold from the back of the broad ligament to the anterior (hilar) border of the ovary
    us = np.linspace(0.58, 0.86, 24)
    base = ad.sheet(us, _split_v(us))
    hil = oc + rot @ np.array([0.0, 0.0, 0.07])
    tgt = np.array([hil + ax * ((u_ - 0.72) / 0.14) * 0.11 for u_ in us])
    r = np.linspace(0, 1, 10)
    P = base[:, None, :] * (1 - r[None, :, None]) + tgt[:, None, :] * r[None, :, None]
    parts.append(_part(_both(_sheet(P, 0.012)), "Broad ligament - mesovarium", "Ligaments", "#f0cdb9",
                       DESC["mesovarium"], "serosa", alpha=0.7, rank=0.8))
    return parts


def _cord(path, r, spacing=0.008, segments=14):
    p = _resample(smooth_path(np.asarray(path, float), 120), spacing)
    return tube(p, np.broadcast_to(np.asarray(r, float), (len(p),)) if np.ndim(r) == 0 else
                np.interp(np.linspace(0, 1, len(p)), np.linspace(0, 1, len(r)), r), segments)


def _wiggle(path, amp, wavelength, seed=0, in_face=False):
    """Tortuous course (helicine arteries): a meander about a smooth path. By default it swings laterally, so the
    uterine artery stays within the sheet of the broad ligament; in_face keeps it in the y-z plane of a specimen's
    cut face instead."""
    p = _resample(smooth_path(np.asarray(path, float), 200), 0.005)
    arc = np.arange(len(p)) * 0.005
    ph = np.random.default_rng(seed).uniform(0, 6.28)
    w = amp * np.sin(arc * 2 * math.pi / wavelength + ph)
    out = p.copy()
    if in_face:
        t = np.gradient(p, axis=0)
        n = np.stack([np.zeros(len(t)), -t[:, 2], t[:, 1]], -1)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        out += n * w[:, None]
    else:
        out[:, 0] += w
    return out


def build_ligaments():
    parts = []
    ad = _adnexa()
    oc, ax = ad.ovary()
    low_pole, top_pole = oc - ax * 0.13, oc + ax * 0.13
    # ovarian ligament: ovary (uterine pole) to the uterus just below and behind the tube
    ov_l = [low_pole + (-0.01, 0.0, 0.0), (low_pole + ad.U[3]) / 2 + (0, -0.02, -0.02), ad.U[3] + (0.0, -0.01, -0.03)]
    parts.append(_part(_both(_cord(ov_l, 0.017)), "Ovarian ligament", "Ligaments", "#dcb89c", DESC["ov_lig"],
                       "ligament", rank=0.9))
    # suspensory ligament of the ovary: peritoneal fold from the tubal pole to the pelvic brim, carrying the vessels
    brim = np.array([0.66, 0.36, -0.24])
    susp = [top_pole + (0.02, 0.0, 0.0), top_pole + (0.08, 0.10, -0.08), brim + (0, -0.08, 0.03), brim]
    parts.append(_part(_both(_cord(susp, 0.034)), "Suspensory ligament of ovary", "Ligaments", "#efd8c4",
                       DESC["susp"], "serosa", alpha=0.45, rank=0.9))
    # round ligament: from the uterine angle through the deep inguinal ring and canal into the labium majus
    c = _at(S_CORNU - 0.05)
    start = c + (_half_width([S_CORNU - 0.05])[0] - 0.01, -0.01, 0.05)
    rl = [start, (0.36, 0.0, 0.46), (0.47, 0.03, 0.62), (0.30, -0.12, 0.70), (0.18, -0.26, 0.73),
          (0.15, -0.46, 0.745), (0.13, -0.66, 0.70)]
    parts.append(_part(_both(_cord(rl, 0.016)), "Round ligament of uterus", "Ligaments", "#d9ae94", DESC["round"],
                       "ligament", rank=0.9))
    # uterosacral ligaments: from the back of the cervix round the rectum to the front of the sacrum
    pc = _at(0.17) + np.array([0.075, 0.0, 0.0]) + np.array([0.0, 0.643, -0.766]) * 0.07
    us = [pc, pc + (0.08, 0.03, -0.12), (0.21, -0.10, -0.40), (0.19, 0.0, -0.53), (0.17, 0.06, -0.575)]
    parts.append(_part(_both(_cord(us, [0.022, 0.024, 0.02, 0.018])), "Uterosacral ligament", "Ligaments",
                       "#d4ae96", DESC["uterosacral"], "ligament", rank=0.9))
    # cardinal (transverse cervical) ligament: a thick fan at the base of the broad ligament
    Vc = _grid(np.array([0.06, -0.46, -0.30]), np.array([0.62, -0.10, 0.10]), 0.01)
    card = _flat_tube(_spline([(0.10, -0.25, -0.05), (0.28, -0.29, -0.10), (0.46, -0.33, -0.15),
                               (0.54, -0.35, -0.17)], 0.02), [0.045, 0.06, 0.085], [0.028, 0.03, 0.035],
                      side=(0.0, 1.0, 0.0))
    cd = _apply(Vc, _empty(Vc), _dist(card))
    cd = np.maximum(cd, -_apply(Vc, _empty(Vc), _dist(uterus_field()))).astype(np.float32)
    cd = np.maximum(cd, -_apply(Vc, _empty(Vc), _dist(vagina_fields()[1]))).astype(np.float32)
    parts.append(_part(_both(_clean(_mesh(Vc, cd, 1.0))), "Cardinal ligament (transverse cervical)", "Ligaments",
                       "#cfa98f", DESC["cardinal"], "ligament", rank=0.9))

    # ------------------------------------------------------------------ vessels
    ii = [(0.34, 0.54, -0.42), (0.44, 0.28, -0.47), (0.50, 0.06, -0.445)]
    parts.append(_part(_both(_cord(ii, [0.034, 0.03, 0.026])), "Internal iliac artery", "Vessels", "#b93434",
                       DESC["int_iliac"], "artery", rank=1.1))
    marg = ad.U[::-1] + np.array([0.036, 0.0, -0.012])
    ua_main = [(0.50, 0.06, -0.445), (0.51, -0.12, -0.30), (0.42, -0.215, -0.15), (0.28, -0.205, -0.05),
               marg[3] + (0.02, -0.02, 0)]
    asc = _wiggle(np.vstack([marg[3:], ad.sheet(np.linspace(0.05, 0.55, 8), 0.07)]), 0.011, 0.05, seed=3)
    desc = [marg[3] + (0.02, -0.02, 0), (0.15, -0.34, -0.07), (0.14, -0.52, -0.02)]
    ua = Mesh().extend(_cord(ua_main, [0.02, 0.017, 0.016])).extend(tube(asc, np.linspace(0.013, 0.007, len(asc)),
                                                                         10))
    ua.extend(_cord(desc, [0.012, 0.009]))
    parts.append(_part(_both(ua), "Uterine artery", "Vessels", "#c8302f", DESC["ut_art"], "artery", rank=1.1))
    hil = oc + np.array([0.0, 0.0, 0.07])
    top = [(0.40, 0.95, -0.30), (0.52, 0.62, -0.31), brim + (0, 0.02, 0.0), brim + (-0.02, -0.08, 0.03)]
    oa = _cord(top + [top_pole + (0.06, 0.08, -0.06), top_pole + (0.01, 0.0, 0.02), hil + (0.0, 0.05, 0.0)], 0.011)
    oa.extend(_cord([top_pole + (0.01, 0.0, 0.02)] + list(ad.sheet(np.linspace(0.82, 0.55, 5), 0.09)), 0.008))
    parts.append(_part(_both(oa), "Ovarian artery", "Vessels", "#d3403a", DESC["ov_art"], "artery", rank=1.1))
    off = np.array([0.028, 0.0, -0.025])
    ov = _cord([np.asarray(p_) + off for p_ in top] + [top_pole + (0.07, 0.07, -0.07), top_pole + (0.03, -0.02, 0.0),
                                                      hil + (0.02, -0.02, 0.0)], 0.017)
    parts.append(_part(_both(ov), "Ovarian vein", "Vessels", "#3b5aa6", DESC["ov_vein"], "vein", rank=1.1))

    # ------------------------------------------------------------------ peritoneal pouches
    Vp = _grid(np.array([-0.26, -0.40, -0.62]), np.array([0.26, 0.26, 0.52]), 0.009)
    x, y, z = Vp.axes()
    U = _apply(Vp, _empty(Vp), _dist(uterus_field()))
    Vg = _apply(Vp, _empty(Vp), _dist(vagina_fields()[1]))
    Bl = _apply(Vp, _empty(Vp), bladder_field())
    Rc = _apply(Vp, _empty(Vp), rectum_field())
    ax_ = np.abs(np.broadcast_to(x, Vp.shape))
    Y = np.broadcast_to(y, Vp.shape)
    vu = _mx(0.004 - U, 0.004 - Bl, U + Bl - 0.10, ax_ - 0.2, -0.25 - Y)
    UV = np.minimum(U, Vg)
    ru = _mx(0.004 - UV, 0.004 - Rc, UV + Rc - (0.06 + 0.9 * np.clip(Y + 0.335, 0, None)), ax_ - 0.19,
             -0.335 - Y, Y + 0.10)
    parts.append(_part(_clean(_mesh(Vp, vu, 1.0)), "Vesicouterine pouch", "Peritoneum", "#74b4dc", DESC["vu_pouch"],
                       "serosa", alpha=0.6, rank=0.7))
    parts.append(_part(_clean(_mesh(Vp, ru, 1.0)), "Rectouterine pouch (of Douglas)", "Peritoneum", "#6aaed8",
                       DESC["ru_pouch"], "serosa", alpha=0.6, rank=0.7))
    return parts


# =============================================================================== vulva and perineum
def _bump(t):
    """Smooth 0..1..0 profile over t in [0, 1]."""
    return np.maximum(np.sin(np.pi * np.clip(t, 0.0, 1.0)), 0.0)


def _vwin(v, v0, v1, soft=0.02):
    """Field that is negative for v0 < v < v1."""
    return np.maximum(v0 - v, v - v1) - 0.0 * soft


def build_vulva():
    parts = []
    F = VULVA
    vox = 0.0085
    V = _grid(np.array([-0.34, -0.30, 0.0]), np.array([0.34, 0.17, F.length]), vox)
    u, w, v = V.axes()
    au = np.abs(u)
    grain = (0.004 * fbm3(u * 22, w * 22, v * 22, 1.0, 2, 17)).astype(np.float32)

    def world_field(f, lo_uwv, hi_uwv):
        """Evaluate a world-space field on part of the frame's grid (mapped through F.world)."""
        out = np.full(V.shape, 1.0, np.float32)
        r = V.region(lo_uwv, hi_uwv)
        if r is None:
            return out
        sl, (uu, ww, vv) = r
        pw = F.world(*np.broadcast_arrays(uu, ww, vv))
        out[sl] = np.asarray(f(pw[..., 0], pw[..., 1], pw[..., 2]), np.float32)
        return out

    vag = world_field(_dist(vagina_fields()[1]), (-0.16, -0.30, V_VAG - 0.15), (0.16, 0.0, V_VAG + 0.12))
    ure = world_field(_tube_d(urethra_path(), 0.032), (-0.08, -0.30, V_URETH - 0.08), (0.08, 0.0, V_URETH + 0.08))
    anal = world_field(rectum_field(), (-0.16, -0.30, 0.0), (0.16, 0.05, V_ANUS + 0.2))
    holes = _mn(vag, ure, anal)
    v_back, v_front = V_FOURCHETTE - 0.13, V_COMMISSURE + 0.06

    def lens(cu, cv, ru, rv, base, height, power=0.55):
        """Skin-covered pad: a lens between a base surface and a dome that meets it at the footprint's edge."""
        r2 = ((u - cu) / ru) ** 2 + ((v - cv) / rv) ** 2
        top = base + height * np.clip(1 - r2, 0, 1) ** power
        return _mx(w - top - grain, base - 0.001 - w, np.sqrt(r2) - 1.0)

    # labia majora: two rounded skin folds full of fat, meeting in front at the mons, behind at the perineum
    vm, rvm = (v_back + v_front) / 2, (v_front - v_back) / 2
    maj = _mn(lens(0.112, vm, 0.08, rvm, -0.09, 0.18), lens(-0.112, vm, 0.08, rvm, -0.09, 0.18))
    maj = _mx(maj, -holes)
    parts.append(_part(_clean(_mesh(V, maj, 1.0)), "Labia majora", "External genitalia (vulva)", "#d4a086",
                       DESC["majora"], "skin", rank=2))
    # mons pubis: the fat pad over the symphysis, continuous with the labia majora
    vmo = (V_COMMISSURE - 0.02 + F.length) / 2
    mons = _mx(lens(0.0, vmo, 0.27, (F.length - V_COMMISSURE + 0.02) / 2, -0.15, 0.185, 0.45), -maj)
    parts.append(_part(_clean(_mesh(V, mons, 1.0)), "Mons pubis", "External genitalia (vulva)", "#d6a489",
                       DESC["mons"], "skin", rank=2))
    # labia minora: thin folds inside the majora, joined behind at the fourchette and splitting in front round
    # the clitoris into the prepuce and the frenulum
    v0, v1 = V_FOURCHETTE + 0.005, V_GLANS + 0.012
    tn = np.clip((v - v0) / (v1 - v0), 0, 1)
    ucn = 0.012 + 0.036 * _bump(tn * 0.9 + 0.05) ** 0.5
    wtop = -0.012 + 0.03 * _bump(tn) + 0.004 * np.sin(v * 90)
    thick = 0.010 - 0.004 * np.clip((w + 0.1) / 0.1, 0, 1)
    mino = _mx(np.abs(au - ucn) - thick, w - wtop, -0.115 - w, _vwin(v, v0, v1), -holes + 0.004)
    parts.append(_part(_clean(_mesh(V, mino, 0.9)), "Labia minora", "External genitalia (vulva)", "#c47881",
                       DESC["minora"], "mucosa", rank=2.1))
    # vestibule: the floor between the labia minora, pierced by the urethral and vaginal orifices
    vest = _mx(au - (ucn - 0.004), w + 0.100, -0.126 - w, _vwin(v, V_FOURCHETTE, V_GLANS - 0.03), 0.004 - holes)
    parts.append(_part(_clean(_mesh(V, vest, 0.9)), "Vestibule", "External genitalia (vulva)", "#e3929c",
                       DESC["vestibule"], "mucosa", rank=2.05))
    # pudendal cleft: the slit between the labia majora (shown as a faint film)
    cleft = _mx(au - 0.05, w - 0.05, -0.098 - w, _vwin(v, V_FOURCHETTE - 0.02, V_COMMISSURE - 0.02), -maj, -mino,
                -vest)
    parts.append(_part(_clean(_mesh(V, cleft, 1.0)), "Pudendal cleft", "External genitalia (vulva)", "#f3e4dc",
                       DESC["cleft"], "csf", alpha=0.18, rank=2.2, label=False))
    # glans and prepuce of the clitoris
    g = np.array([0.0, -0.038, V_GLANS])
    dg = np.sqrt((u / 0.026) ** 2 + ((w - g[1]) / 0.025) ** 2 + ((v - g[2]) / 0.032) ** 2)
    glans = ((dg - 1.0) * 0.025).astype(np.float32)
    parts.append(_part(_clean(_mesh(V, glans, 0.8)), "Glans of clitoris", "External genitalia (vulva)", "#bf5468",
                       DESC["glans"], "mucosa", rank=2.3))
    dh = np.sqrt(u ** 2 + (w - g[1]) ** 2 + (v - g[2] - 0.006) ** 2)
    hood = _mx(dh - 0.052, 0.031 - dh, g[1] - 0.012 - w, (g[2] - 0.012) - v, w - 0.012)
    parts.append(_part(_clean(_mesh(V, hood, 0.8)), "Prepuce of clitoris", "External genitalia (vulva)", "#cc8584",
                       DESC["prepuce"], "mucosa", rank=2.2))
    # perineal body: the fibromuscular node between the vaginal orifice and the anus (the clinical perineum)
    vpb = (V_ANUS + 0.07 + V_FOURCHETTE) / 2
    pb = _mx(lens(0.0, vpb, 0.13, (V_FOURCHETTE - V_ANUS - 0.07) / 2 + 0.02, -0.23, 0.235, 0.35), 0.006 - holes,
             -maj)
    parts.append(_part(_clean(_mesh(V, pb, 1.0)), "Perineal body (clinical perineum)", "External genitalia (vulva)",
                       "#c38e7c", DESC["perineum"], "fascia", rank=2))
    out = []
    for p in parts:
        m = Mesh()
        for pos, nrm, idx in p.mesh.parts:
            q = F.world(pos[:, 0], pos[:, 1], pos[:, 2]).astype(np.float32)
            m.add(q, idx)
        p.mesh = m
        out.append(p)
    # world-space parts: clitoral body and crura, Bartholin glands
    gw = F.world(0.0, -0.05, V_GLANS + 0.01)
    knee = np.array([0.0, -0.72, 0.565])
    body = _cord([gw, gw + (0, 0.07, 0.06), knee], [0.02, 0.026, 0.03])
    for sx in (-1, 1):
        body.extend(_cord([knee, (sx * 0.07, -0.70, 0.49), (sx * 0.14, -0.72, 0.41), (sx * 0.22, -0.77, 0.29),
                           (sx * 0.29, -0.81, 0.17)], [0.03, 0.028, 0.022, 0.012]))
    out.append(_part(body, "Body of clitoris (with crura)", "External genitalia (vulva)", "#a8475a",
                     DESC["clit_body"], "muscle", rank=2))
    # external urethral orifice: a small puckered ring in the vestibule
    ring = np.array([F.world(0.017 * math.cos(t_), -0.097 + 0.002 * math.cos(4 * t_), V_URETH + 0.02 * math.sin(t_))
                     for t_ in np.linspace(0, 2 * math.pi, 40)])
    out.append(_part(tube(ring, 0.0075, 10), "External urethral orifice", "External genitalia (vulva)", "#b04f63",
                     DESC["ureth_orif"], "mucosa", rank=2.3))
    bart = Mesh()
    for sx in (-1, 1):
        c = F.world(sx * 0.075, -0.165, V_VAG - 0.035)
        bart.extend(ellipsoid_mesh(c, (0.026, 0.02, 0.03), 14))
        bart.extend(_cord([c, F.world(sx * 0.05, -0.14, V_VAG - 0.02), F.world(sx * 0.037, -0.108, V_VAG - 0.012)],
                          0.005, segments=8))
    out.append(_part(bart, "Greater vestibular (Bartholin) glands", "External genitalia (vulva)", "#ecd48e",
                     DESC["bartholin"], "gland", rank=2))
    return out


# =============================================================================== specimen helpers
FACE = -0.002          # the cut face of every specimen, just behind the median plane so the viewer's cut spares it


def _cut(d, x):
    """Keep only the x < FACE half of a field: the specimen is already sectioned."""
    return np.maximum(d, x - FACE).astype(np.float32)


def _half_ball(c, r, res=14, squash=(1.0, 1.0, 1.0)):
    """Closed hemisphere (x <= FACE side) of a sphere centred on the cut face: a sectioned cell or nucleus."""
    c = np.asarray(c, float)
    th = np.linspace(0, math.pi, res)                 # polar angle from -x
    ph = np.linspace(0, 2 * math.pi, res * 2, endpoint=False)
    T, P = np.meshgrid(th[: res // 2 + 1], ph, indexing="ij")
    T = T * (math.pi / 2) / T.max()
    unit = np.stack([-np.cos(T), np.sin(T) * np.cos(P), np.sin(T) * np.sin(P)], -1)
    pos = c + unit * r * np.asarray(squash)
    pos[..., 0] = np.minimum(pos[..., 0], FACE)
    nt, npp = T.shape
    a = np.arange(nt * npp).reshape(nt, npp)
    q0, q1 = a[:-1, :].ravel(), a[1:, :].ravel()
    q2, q3 = np.roll(a[1:, :], -1, 1).ravel(), np.roll(a[:-1, :], -1, 1).ravel()
    tri = np.concatenate([np.stack([q0, q1, q2], 1), np.stack([q0, q2, q3], 1)])
    pts = pos.reshape(-1, 3)
    rim = a[-1, :]
    cen = len(pts)
    pts = np.vstack([pts, [[FACE, c[1], c[2]]]])
    cap = np.stack([np.full(npp, cen), rim, np.roll(rim, -1)], 1)
    from .cells import orient_outward
    return orient_outward(Mesh().add(pts, np.vstack([tri, cap])))


def _half_shell(c, r_in, r_out, res=16, squash=(1.0, 1.0, 1.0)):
    """Closed hemispherical shell sectioned on the cut face (zona pellucida, a ring of follicle cells)."""
    o = _half_ball(c, r_out, res, squash)
    i = _half_ball(c, r_in, res, squash)
    po, _, io = o.arrays()
    pi_, _, ii = i.arrays()
    # drop the flat caps and replace them with an annulus between the two rims
    no, ni = len(po) - 1, len(pi_) - 1
    io = io[np.all(io < no, axis=1)]
    ii = ii[np.all(ii < ni, axis=1)]
    npp = res * 2
    ro = np.arange(no - npp, no)
    rin = np.arange(ni - npp, ni) + no
    ann = np.vstack([np.stack([ro, rin, np.roll(rin, -1)], 1), np.stack([ro, np.roll(rin, -1), np.roll(ro, -1)], 1)])
    pos = np.vstack([po[:no], pi_[:ni]])
    idx = np.vstack([io, ii[:, ::-1] + no, ann])
    m = Mesh().add(pos, idx)
    # orient: outer faces outward, the annulus facing +x
    return m


def _ball(c, r, res=12, squash=(1.0, 1.0, 1.0)):
    return ellipsoid_mesh(c, np.asarray(squash) * r, res)


# =============================================================================== specimen: ovary cut through its follicles
OVARY_O = np.array([0.0, 0.78, -1.46])
OV_R = np.array([0.20, 0.25, 0.44])          # half-thickness (x), height (y), length (z): about 2.5x life size


def build_ovary_specimen():
    parts = []
    G = "Magnified: ovary (sectioned)"
    o = OVARY_O
    vox = 0.0075
    V = _grid(o - OV_R - 0.08, np.array([0.01, o[1] + OV_R[1] + 0.08, o[2] + OV_R[2] + 0.08]), vox)
    x, y, z = V.axes()
    px, py, pz = x - o[0], y - o[1], z - o[2]
    # an almond with a hilum on its lower (mesovarian) border
    k0 = np.sqrt((px / OV_R[0]) ** 2 + (py / OV_R[1]) ** 2 + (pz / OV_R[2]) ** 2)
    body = (k0 - 1.0) * 0.2
    body = body + 0.012 * fbm3(x * 10, y * 10, z * 10, 1.0, 2, 21)
    rng = np.random.default_rng(5)
    # follicles and luteal bodies (centres on the cut face, so each is sectioned through its middle)
    graaf_c = o + np.array([0.0, 0.10, 0.25])
    cl_c = o + np.array([0.0, 0.05, -0.27])
    ca_c = o + np.array([0.0, -0.13, -0.12])
    atr_c = o + np.array([0.0, -0.12, 0.28])
    sec = [o + np.array([0.0, 0.17, -0.06]), o + np.array([0.0, -0.12, -0.335])]
    body = smin(body, _sph(x, y, z, graaf_c + (0, 0.06, 0.05), 0.12), 0.05)          # the mature follicle bulges
    body = smin(body, _sph(x, y, z, cl_c + (0, 0.02, -0.06), 0.09), 0.05)
    body = body.astype(np.float32)
    depth = -_edt_from(body, vox)
    X = np.broadcast_to(x, V.shape)
    notch = _sph(x, y, z, o + (0, -OV_R[1] - 0.02, 0.0), 0.085)             # hilum: vessels enter from below
    fol_r = 0.13
    graaf = _sph(x, y, z, graaf_c, fol_r)
    cl = _sph(x, y, z, cl_c, 0.105) + (0.012 * np.sin(np.arctan2(py - 0.05, pz + 0.27) * 11)).astype(np.float32)
    ca = _sph(x, y, z, ca_c, 0.06) + (0.018 * np.sin(np.arctan2(py + 0.13, pz + 0.12) * 5)).astype(np.float32)
    atr = _sph(x, y, z, atr_c, 0.045)
    secs = _mn(*[_sph(x, y, z, c, 0.052) for c in sec])
    holes = _mn(graaf - 0.03, cl, ca, atr, secs - 0.01)
    # small follicles on the cut face: primordial ones crowded just under the albuginea, primary ones deeper
    from .lymphoid import _thin
    i0 = int(round((FACE - 0.004 - V.lo[0]) / vox))
    ok = (body[i0] < -0.03) & (holes[i0] > 0.03)

    def face_pts(lo_d, hi_d, spacing, n, seed):
        idx = np.argwhere(ok & (depth[i0] > lo_d) & (depth[i0] < hi_d))
        cand = np.stack([np.zeros(len(idx)), V.lo[1] + idx[:, 0] * vox, V.lo[2] + idx[:, 1] * vox], -1)
        return _thin(cand, spacing, seed=seed)[:n]
    pri_pts = face_pts(0.06, 0.10, 0.09, 7, 11)
    prm_pts = face_pts(0.028, 0.06, 0.028, 140, 3)
    if len(pri_pts):
        prm_pts = np.array([p_ for p_ in prm_pts if np.linalg.norm(pri_pts - p_, axis=1).min() > 0.04])
    small = _mn(*([_sph(x, y, z, c, 0.021) for c in pri_pts] + [_sph(x, y, z, c, 0.0105) for c in prm_pts]))
    # vessels fan from the hilum through the medulla; their channels are kept open on the cut face
    hc = o + np.array([-0.0, -OV_R[1] - 0.03, 0.0])
    vpaths = []
    for k in range(5):
        ang = -0.85 + k * 0.42
        tgt = o + np.array([0.0, -0.03 + 0.05 * abs(math.cos(ang * 2)), 0.19 * math.sin(ang)])
        pa = _wiggle([hc + (0.0, -0.1, 0.0), hc + (0.0, 0.03, 0.01 * k), tgt], 0.0055, 0.035, seed=k, in_face=True)
        pa[:, 0] = -0.006
        pv = smooth_path(np.array([hc + (0.0, -0.1, 0.02), hc + (0.0, 0.02, 0.015 * k),
                                   tgt + (0.0, -0.03, 0.025)]), 30)
        pv[:, 0] = -0.03
        vpaths.append((pa, pv))
    chan = _empty(V)
    for pa, pv in vpaths:
        _apply(V, chan, _tube_d(pa, 0.012))
        _apply(V, chan, _tube_d(pv, 0.016))
    holes = _mn(holes, small, chan)
    epi = _cut(_mx(body, -(body + 0.014)), X)
    alb = _cut(_mx(body + 0.014, -(body + 0.034), -holes), X)
    cortex = _cut(_mx(body + 0.034, depth - 0.12, -holes), X)
    medulla = _cut(_mx(body + 0.034, 0.12 - depth, -holes), X)
    parts.append(_part(_clean(_mesh(V, epi, 0.6)), "Germinal (surface) epithelium", G, "#f2e1d0", DESC["germinal"],
                       "mucosa", micro=True, rank=3))
    parts.append(_part(_clean(_mesh(V, alb, 0.6)), "Tunica albuginea of ovary", G, "#efe9e0", DESC["albuginea"],
                       "fascia", micro=True, rank=3))
    parts.append(_part(_clean(_mesh(V, cortex, 0.8)), "Ovarian cortex", G, "#e7c7b8", DESC["cortex"], "organ",
                       micro=True, rank=3, detail=(0.1, 140.0, 0.8, 0)))
    parts.append(_part(_clean(_mesh(V, medulla, 0.8)), "Ovarian medulla", G, "#dca79f", DESC["medulla"], "fascia",
                       micro=True, rank=3, detail=(0.1, 90.0, 0.4, 0)))
    # vesicular (Graafian) follicle: theca externa, theca interna, membrana granulosa, antrum, cumulus
    cum_c = graaf_c + np.array([0.0, -0.06, -0.035])
    cum = _sph(x, y, z, cum_c, 0.045)
    the = _cut(_mx(graaf - 0.03, -(graaf - 0.014)), X)
    thi = _cut(_mx(graaf - 0.014, -graaf), X)
    gran = _cut(_mx(_mn(graaf, smin(graaf + 0.0, cum, 0.02)), -(graaf + 0.02), -(cum)), X)
    gran = _cut(_mx(graaf, -(graaf + 0.02)), X)
    antrum = _cut(_mx(graaf + 0.02, -smin(-(graaf + 0.02) * 0 + cum, graaf + 1.0, 0.0)), X)
    antrum = _cut(_mx(graaf + 0.02, -cum), X)
    cumulus = _cut(_mx(cum, graaf + 0.005, -_sph(x, y, z, cum_c + (0, 0.002, -0.004), 0.037)), X)
    parts.append(_part(_clean(_mesh(V, the, 0.7)), "Theca externa", G, "#d69a8a", DESC["theca_ext"], "fascia",
                       micro=True, rank=3.2))
    parts.append(_part(_clean(_mesh(V, thi, 0.7)), "Theca interna", G, "#e6b07a", DESC["theca_int"], "gland",
                       micro=True, rank=3.2))
    parts.append(_part(_clean(_mesh(V, gran, 0.7)), "Membrana granulosa (granulosa cells)", G, "#c889a8",
                       DESC["granulosa"], "gland", micro=True, rank=3.3))
    parts.append(_part(_clean(_mesh(V, antrum, 0.8)), "Antrum (follicular fluid)", G, "#f4e9c6", DESC["antrum"], "csf",
                       alpha=0.55, micro=True, rank=3.1))
    parts.append(_part(_clean(_mesh(V, cumulus, 0.7)), "Cumulus oophorus", G, "#b9789b", DESC["cumulus"], "gland",
                       micro=True, rank=3.3))
    # corpus luteum (folded, yellow, with a central clot) and corpus albicans (white scar), atretic follicle
    clot = _sph(x, y, z, cl_c, 0.035)
    parts.append(_part(_clean(_mesh(V, _cut(_mx(cl, -clot), X), 0.8)), "Corpus luteum", G, "#e7b53c",
                       DESC["cl"], "gland", micro=True, rank=3.2))
    parts.append(_part(_clean(_mesh(V, _cut(clot, X), 0.8)), "Corpus luteum - central clot", G, "#a8423c",
                       DESC["cl_clot"], "vein", micro=True, rank=3.2))
    parts.append(_part(_clean(_mesh(V, _cut(ca, X), 0.8)), "Corpus albicans", G, "#f3f0ea", DESC["ca"], "fascia",
                       micro=True, rank=3.2))
    parts.append(_part(_clean(_mesh(V, _cut(_mx(atr, -(atr + 0.012)), X), 0.7)), "Atretic follicle", G, "#c9a5a3",
                       DESC["atretic"], "fascia", micro=True, rank=3.2))
    # secondary follicles: granulosa with small fluid-filled vesicles, a thin theca
    sec_g = _mx(secs, -(secs + 0.010) * 0 - _mn(*[_sph(x, y, z, c, 0.018) for c in sec]))
    ves = _mn(*[_sph(x, y, z, c + rng.normal(0, 0.017, 3) * (0, 1, 1), 0.008) for c in sec for _ in range(5)])
    parts.append(_part(_clean(_mesh(V, _cut(_mx(sec_g, -ves), X), 0.6)), "Secondary follicles", G, "#cf8aa9",
                       DESC["secondary"], "gland", micro=True, rank=3.3))
    parts.append(_part(_clean(_mesh(V, _cut(_mx(secs - 0.01, -secs), X), 0.6)), "Theca of secondary follicles", G,
                       "#e2b384", DESC["sec_theca"], "gland", micro=True, rank=3.3))

    # small follicles and every oocyte, zona and corona as sectioned meshes
    oo, zona, prim, pri_g, corona = Mesh(), Mesh(), Mesh(), Mesh(), Mesh()
    ooc = cum_c + np.array([0.0, 0.002, -0.004])
    oo.extend(_half_ball(ooc, 0.020, 16))
    zona.extend(_half_shell(ooc, 0.020, 0.025, 16))
    corona.extend(_half_shell(ooc, 0.025, 0.036, 16))
    for c in sec:
        oo.extend(_half_ball(c, 0.013, 14))
        zona.extend(_half_shell(c, 0.013, 0.0165, 14))
    # primary follicles: one layer of cuboidal granulosa and a thin zona
    for c in pri_pts:
        oo.extend(_half_ball(c, 0.010, 12))
        zona.extend(_half_shell(c, 0.010, 0.012, 12))
        pri_g.extend(_half_shell(c, 0.012, 0.019, 12))
    # primordial follicles: an oocyte in a single layer of flat cells
    for c in prm_pts:
        oo.extend(_half_ball(c, 0.0065, 10))
        prim.extend(_half_shell(c, 0.0065, 0.0095, 10))
    parts.append(_part(prim, "Primordial follicles", G, "#d99bb2", DESC["primordial"], "gland", micro=True, rank=3.4))
    parts.append(_part(pri_g, "Primary follicles", G, "#cc86a6", DESC["primary"], "gland", micro=True, rank=3.4))
    parts.append(_part(oo, "Oocytes", G, "#f3d2dc", DESC["oocyte"], "nucleus", micro=True, rank=3.5))
    parts.append(_part(zona, "Zona pellucida", G, "#f7f3ff", DESC["zona"], "mucosa", micro=True, rank=3.5))
    parts.append(_part(corona, "Corona radiata", G, "#b775a0", DESC["corona"], "gland", micro=True, rank=3.5))
    # hilum: mesovarium stub and the coiled vessels spreading through the medulla
    Vm = _grid(hc - (0.14, 0.14, 0.14), np.array([0.01, hc[1] + 0.04, hc[2] + 0.14]), 0.006)
    xm, ym, zm = Vm.axes()
    meso = _mx(np.abs(zm - hc[2]) - 0.035, ym - (hc[1] + 0.03), (hc[1] - 0.13) - ym, np.abs(xm + 0.06) - 0.055)
    meso = _mx(meso, -_apply(Vm, _empty(Vm), _dist(_flat_tube(np.array([o - (0.0, 0.0, 0.0), o + (0, 0.001, 0)]),
                                                               OV_R[0], OV_R[1], OV_R[2], OV_R[2]))))
    parts.append(_part(_clean(_mesh(Vm, _cut(meso, np.broadcast_to(xm, Vm.shape)), 0.8)),
                       "Mesovarium (cut edge)", G, "#f0d3c2", DESC["mesovarium_cut"], "serosa", micro=True, rank=3))
    art, vein = Mesh(), Mesh()
    for pa, pv in vpaths:
        art.extend(tube(pa, np.linspace(0.008, 0.0035, len(pa)), 8))
        vein.extend(tube(pv, np.linspace(0.011, 0.005, len(pv)), 8))
    parts.append(_part(art, "Ovarian blood vessels - arteries", G, "#c93333", DESC["ov_art_in"], "artery",
                       micro=True, rank=3.1))
    parts.append(_part(vein, "Ovarian blood vessels - veins", G, "#3e5ea8", DESC["ov_vein_in"], "vein", micro=True,
                       rank=3.1))
    return parts


# =============================================================================== specimen: breast in sagittal section
BREAST_O = np.array([0.0, 1.50, 0.10])        # centre of the breast's base on the chest wall (world)


def build_breast():
    parts = []
    G = "Mammary gland (breast)"
    o = BREAST_O
    vox = 0.0095
    V = _grid(o + (-0.80, -0.62, -0.01), o + (0.01, 0.82, 0.42), vox)
    x, y, z = V.axes()
    X = np.broadcast_to(x, V.shape)
    Y, Z = y - o[1], z - o[2]
    R, H, yc = 0.44, 0.30, -0.04
    r = np.sqrt(x ** 2 + (Y - yc) ** 2)
    ztop = H * np.clip(1 - (r / R) ** 2, 0, 1) ** 0.72 * (1 + 0.16 * np.clip(-(Y - yc) / R, -1, 1))
    dome = (np.maximum(Z - ztop, -Z) + 0.0 * x).astype(np.float32)
    # axillary tail (of Spence): a tongue of gland running up and out towards the axilla
    tail_path = np.array([(-0.20, o[1] + 0.18, o[2] + 0.02), (-0.40, o[1] + 0.36, o[2] + 0.01),
                          (-0.56, o[1] + 0.49, o[2] - 0.01)])
    tail = _flat_tube(tail_path, [0.16, 0.11, 0.07], [0.095, 0.07, 0.045], side=(0.6, -0.8, 0.0))
    tail_d = _apply(V, _empty(V), _dist(tail))
    tail_d = np.maximum(tail_d, -Z)
    body = smin(dome.astype(np.float32), tail_d, 0.06).astype(np.float32)
    nip_c = np.array([0.0, o[1] + yc - 0.01, o[2] + H * 1.02])
    nip = _dist(_flat_tube(np.array([nip_c - (0, 0, 0.03), nip_c + (0, 0, 0.045)]), 0.034, 0.034, 0.02, 0.018))
    nip_d = _apply(V, _empty(V), nip)
    body = _mn(body, nip_d)
    body = (body + 0.004 * fbm3(x * 8, y * 8, z * 8, 1.0, 2, 44)).astype(np.float32)
    depth = -_edt_from(np.maximum(body, -Z - 0.001), vox)
    # glandular lobes, their lobules and ducts, radiating from beneath the areola
    rng = np.random.default_rng(8)
    lobes = _empty(V)
    lobules = _empty(V)
    ducts = _empty(V)
    sinus = _empty(V)
    ax_n = np.array([0.0, 0.0, 1.0])
    for th in np.radians([90, 113, 136, 159, 182, 205, 228, 251, 270]):
        dirn = np.array([math.cos(th), math.sin(th), 0.0])
        if dirn[0] > 1e-6:
            continue
        L = 0.34 if abs(math.sin(th)) > 0.3 else 0.30
        if abs(th - math.radians(136)) < 0.1:
            L = 0.42                                             # the upper outer lobe feeds the axillary tail
        pts = []
        for t_ in np.linspace(0.12, L, 7):
            c = nip_c * 0 + np.array([0.0, o[1] + yc, o[2]]) + dirn * t_
            zt = H * max(1 - (t_ / R) ** 2, 0) ** 0.72
            c[2] = o[2] + 0.35 * zt + 0.03
            pts.append(c)
        pts = np.array(pts)
        for c in pts:
            sz = rng.uniform(0.045, 0.06)
            f_ = _dist(_flat_tube(np.array([c - dirn * 0.03, c + dirn * 0.03]), sz, sz * 0.75, sz * 0.8, sz * 0.8,
                                  side=np.cross(ax_n, dirn)))
            _apply(V, lobes, f_, "smin", 0.03)
        # main lactiferous duct: nipple tip -> sinus under the areola -> along the lobe, branching to lobules
        s_c = nip_c + np.array([0.0, 0.0, -0.075]) + dirn * 0.055
        _apply(V, sinus, _dist(_flat_tube(np.array([s_c - dirn * 0.018, s_c + dirn * 0.022]), 0.016, 0.014,
                                          0.012, 0.012, side=np.cross(ax_n, dirn))))
        main = np.vstack([[nip_c + (0, 0, 0.04) + dirn * 0.012, nip_c + dirn * 0.02, s_c], pts])
        _apply(V, ducts, _tube_d(_spline(main, 0.01), 0.0065))
        for k, c in enumerate(pts[1:]):
            for side in (-1, 1, 0):
                off = np.cross(ax_n, dirn) * side * rng.uniform(0.02, 0.035) + np.array([0, 0, rng.uniform(-0.02,
                                                                                                         0.03)])
                end = c + off + dirn * rng.uniform(0.0, 0.03)
                _apply(V, ducts, _tube_d(np.array([c, end]), 0.0045))
                for _ in range(6):
                    end_j = end + rng.normal(0, 0.016, 3)
                    _apply(V, lobules, _tube_d(np.array([end, end_j]), 0.003), "smin", 0.004)
                    _apply(V, lobules, _tube_d(np.array([end_j, end_j + (0.001, 0, 0)]), 0.0125), "smin", 0.005)
    # Cooper's (suspensory) ligaments: fibrous septa from the deep fascia through the fat to the dermis
    lig = _empty(V)
    for rk in (0.06, 0.15, 0.24, 0.33):
        rr = rk + 0.75 * Z + 0.012 * np.sin(np.arctan2(Y - yc, x) * 7 + rk * 30)
        lig = np.minimum(lig, (np.abs(r - rr) - 0.0065).astype(np.float32))
    inside = _mx(body, -Z)
    skin_zone = depth < 0.013
    skin = _mx(inside, depth - 0.013, -nip_d)
    are_r = np.sqrt(x ** 2 + (Y - (nip_c[1] - o[1])) ** 2)
    areola = _mx(inside, depth - 0.015, are_r - 0.12, -nip_d)
    skin = _mx(skin, -areola)
    gl = _mx(inside, 0.026 - depth, _mn(lobes, tail_d + 0.018))
    lobules_d = _mx(lobules, inside, 0.02 - depth)
    duct_d = _mx(_mn(ducts, sinus), inside - 0.0, 0.004 - depth + 0.0 * x)
    duct_d = _mn(_mx(ducts, nip_d), duct_d)
    lig_d = _mx(lig, inside, 0.012 - depth, -gl, Z - ztop + 0.0)
    lobe_d = _mx(gl, -lobules_d, -duct_d, -nip_d)
    fat = _mx(inside, 0.013 - depth, -lobe_d, -lobules_d, -duct_d, -lig_d, -nip_d, -areola)
    tailpart = _mx(lobe_d, 0.004 - dome)
    lobe_main = _mx(lobe_d, -tailpart)
    nip_only = _mx(nip_d, -duct_d)
    glands = Mesh()
    for k in range(12):                        # Montgomery tubercles on the kept half of the areola
        t_ = math.radians(95 + k * 15)
        rr_ = rng.uniform(0.065, 0.105)
        pxy = np.array([rr_ * math.cos(t_), nip_c[1] + rr_ * math.sin(t_)])
        if pxy[0] > -0.006:
            continue
        rr0 = math.hypot(pxy[0], pxy[1] - o[1] - yc)
        zt = o[2] + H * max(1 - (rr0 / R) ** 2, 0) ** 0.72 * (1 + 0.16 * np.clip(-(pxy[1] - o[1] - yc) / R, -1, 1))
        glands.extend(ellipsoid_mesh((pxy[0], pxy[1], zt + 0.002), (0.011, 0.011, 0.008), 10))
    C = lambda f: _cut(f, X)      # noqa: E731
    parts.append(_part(_clean(_mesh(V, C(skin), 0.8)), "Skin of breast", G, "#e2b597", DESC["br_skin"], "skin",
                       micro=True, rank=4))
    parts.append(_part(_clean(_mesh(V, C(areola), 0.8)), "Areola", G, "#a8645a", DESC["areola"], "skin", micro=True,
                       rank=4.1))
    parts.append(_part(glands, "Areolar glands (of Montgomery)", G, "#b3736a", DESC["areolar_gl"], "gland",
                       micro=True, rank=4.2))
    parts.append(_part(_clean(_mesh(V, C(nip_only), 0.8)), "Nipple", G, "#98524a", DESC["nipple"], "skin", micro=True,
                       rank=4.2))
    parts.append(_part(_clean(_mesh(V, C(fat), 0.9)), "Adipose tissue of breast", G, "#f1d98c", DESC["br_fat"], "fat",
                       micro=True, rank=3.8, detail=(0.06, 60.0, 0.1, 0)))
    parts.append(_part(_clean(_mesh(V, C(lobe_main), 0.8)), "Lobes of mammary gland", G, "#e7a39b", DESC["lobes"],
                       "gland", micro=True, rank=3.9))
    parts.append(_part(_clean(_mesh(V, C(tailpart), 0.8)), "Axillary tail (of Spence)", G, "#e3998f",
                       DESC["tail"], "gland", micro=True, rank=3.9))
    parts.append(_part(_clean(_mesh(V, C(lobules_d), 0.6)), "Lobules (alveolar glands)", G, "#c9606f",
                       DESC["lobules"], "gland", micro=True, rank=4.0))
    parts.append(_part(_clean(_mesh(V, C(_mx(ducts, -sinus, inside)), 0.5)), "Lactiferous ducts", G, "#f3e7d8",
                       DESC["ducts"], "gland", micro=True, rank=4.0))
    parts.append(_part(_clean(_mesh(V, C(_mx(sinus, inside)), 0.6)), "Lactiferous sinuses", G, "#f6ead6",
                       DESC["sinus"], "gland", micro=True, rank=4.0))
    parts.append(_part(_clean(_mesh(V, C(lig_d), 0.6)), "Suspensory ligaments (of Cooper)", G, "#f7f3ec",
                       DESC["cooper"], "ligament", micro=True, rank=3.9))
    # chest wall: pectoral fascia, pectoralis major, ribs and intercostal muscles (coarser grid: big plain surfaces)
    V = _grid(o + (-0.80, -0.62, -0.20), o + (0.01, 0.82, 0.005), 0.012)
    x, y, z = V.axes()
    X = np.broadcast_to(x, V.shape)
    Y, Z = y - o[1], z - o[2]
    wall_fp = (np.sqrt(((x + 0.18) / 0.62) ** 2 + ((Y - 0.06) / 0.66) ** 4) - 1.0) * 0.4 + 0.0 * Z
    fasc = _mx(-Z - 0.014, Z - 0.0, wall_fp)
    pect = _mx(-Z - 0.105, Z + 0.014, wall_fp, -0.46 - Y - 0.25 * (x + 0.4))
    pect = (pect + 0.004 * fbm3(x * 4, y * 30, z * 30, 1.0, 2, 9)).astype(np.float32)
    ribs = _empty(V)
    for y0 in (-0.48, -0.22, 0.04, 0.30, 0.56):
        ribs = np.minimum(ribs, _apply(V, _empty(V), _dist(_flat_tube(
            np.array([(-0.80, o[1] + y0 - 0.14, o[2] - 0.150), (0.02, o[1] + y0, o[2] - 0.140)]), 0.05, 0.03,
            side=(0.0, 1.0, 0.0)))))
    ribs = _mx(ribs, wall_fp - 0.02)
    icm = _mx(np.abs(Z + 0.145) - 0.018, wall_fp - 0.02, -ribs + 0.002)
    parts.append(_part(_clean(_mesh(V, C(fasc), 0.7)), "Pectoral fascia", G, "#d9cfc0", DESC["pect_fascia"],
                       "fascia", micro=True, rank=3.5))
    parts.append(_part(_clean(_mesh(V, C(pect), 0.8)), "Pectoralis major", G, "#a8413c", DESC["pectoralis"],
                       "muscle", micro=True, rank=3.4, detail=(0.08, 60.0, 0.3, 1)))
    parts.append(_part(_clean(_mesh(V, C(ribs), 0.8)), "Ribs", G, "#e8dcc2", DESC["ribs"], "bone", micro=True,
                       rank=3.3))
    parts.append(_part(_clean(_mesh(V, C(icm), 0.8)), "Intercostal muscles", G, "#94403b", DESC["intercostal"],
                       "muscle", micro=True, rank=3.3))
    nodes = Mesh()
    for k, c in enumerate([(-0.70, o[1] + 0.62, o[2] + 0.04), (-0.62, o[1] + 0.70, o[2] - 0.02),
                           (-0.75, o[1] + 0.52, o[2] + 0.0)]):
        nodes.extend(ellipsoid_mesh(c, (0.035, 0.024, 0.022), 12))
    parts.append(_part(nodes, "Axillary lymph nodes", G, "#c7b36b", DESC["ax_nodes"], "lymph", micro=True, rank=4))
    return parts


# =============================================================================== specimen: ampulla in cross-section
TUBE_O = np.array([0.0, 0.08, -1.46])


def build_tube_specimen():
    parts = []
    G = "Magnified: uterine tube wall (ampulla)"
    o = TUBE_O
    vox = 0.0058
    V = _grid(o + (-0.05, -0.31, -0.31), o + (0.004, 0.31, 0.31), vox)
    x, y, z = V.axes()
    X = np.broadcast_to(x, V.shape)
    yy, zz = y - o[1], z - o[2]
    tw = 0.35 * x                                                      # the folds spiral slightly along the tube
    ang = np.arctan2(yy, zz) + tw
    rad = np.sqrt(yy ** 2 + zz ** 2)
    wall_r = 0.28 * (1 + 0.025 * np.cos(3 * ang) + 0.015 * np.sin(5 * ang + 1))
    outer = (rad - wall_r).astype(np.float32)
    # branching mucosal folds (plicae): primary folds from the wall, secondary and tertiary branches off them
    rng = np.random.default_rng(21)
    folds = _empty(V)
    segs = []
    for i in range(8):
        phi = 2 * math.pi * i / 8 + rng.uniform(-0.15, 0.15)
        tip_r = rng.uniform(0.04, 0.08)
        trunk = [(0.19 * math.cos(phi), 0.19 * math.sin(phi))]
        for t_ in np.linspace(0.19, tip_r, 5)[1:]:
            phi += rng.uniform(-0.12, 0.12)
            trunk.append((t_ * math.cos(phi), t_ * math.sin(phi)))
        segs += [(trunk[k], trunk[k + 1], 0.013) for k in range(len(trunk) - 1)]
        for k in (1, 2, 3):
            b0 = np.array(trunk[k])
            for sd in (-1, 1):
                if rng.random() < 0.3:
                    continue
                dirn = -b0 / np.linalg.norm(b0)
                rot = sd * rng.uniform(0.7, 1.1)
                d2 = np.array([dirn[0] * math.cos(rot) - dirn[1] * math.sin(rot),
                               dirn[0] * math.sin(rot) + dirn[1] * math.cos(rot)])
                b1 = b0 + d2 * rng.uniform(0.035, 0.06)
                segs.append((tuple(b0), tuple(b1), 0.008))
                d3 = np.array([d2[0] * math.cos(-rot * 0.7) - d2[1] * math.sin(-rot * 0.7),
                               d2[0] * math.sin(-rot * 0.7) + d2[1] * math.cos(-rot * 0.7)])
                segs.append((tuple(b1), tuple(b1 + d3 * rng.uniform(0.02, 0.035)), 0.006))
    # evaluate the fold skeleton in the rotating section plane
    cy, cz = rad * np.sin(ang), rad * np.cos(ang)
    for (a0, a1, w) in segs:
        a0, a1 = np.array(a0), np.array(a1)
        ba = a1 - a0
        L2 = float(ba @ ba)
        t_ = np.clip(((cz - a0[0]) * ba[0] + (cy - a0[1]) * ba[1]) / L2, 0, 1)
        dd = np.sqrt((cz - a0[0] - ba[0] * t_) ** 2 + (cy - a0[1] - ba[1] * t_) ** 2) - w
        folds = smin(folds, dd.astype(np.float32), 0.008).astype(np.float32)
    mucosa = smin(folds, (0.172 - rad).astype(np.float32), 0.012)
    mucosa = _mx(mucosa, rad - 0.195)
    epi_band = _mx(mucosa, -(mucosa + 0.008))
    lam = mucosa + 0.008
    musc = _mx(rad - (wall_r - 0.013), 0.192 - rad)
    ser = _mx(outer, (wall_r - 0.013) - rad)
    back = -0.042 - x
    C = lambda f: _cut(_mx(f, back), X)       # noqa: E731
    parts.append(_part(_clean(_mesh(V, C(ser), 0.6)), "Serosa of uterine tube", G, "#efd6c9", DESC["tube_serosa"],
                       "serosa", micro=True, rank=3))
    parts.append(_part(_clean(_mesh(V, C(musc), 0.7)), "Muscular layer of uterine tube", G, "#c0625c",
                       DESC["tube_muscle"], "muscle", micro=True, rank=3, detail=(0.08, 70.0, 0.35, 0)))
    parts.append(_part(_clean(_mesh(V, C(lam), 0.6)), "Mucosa of uterine tube (lamina propria folds)", G,
                       "#e8aab0", DESC["tube_mucosa"], "mucosa", micro=True, rank=3.1))
    parts.append(_part(_clean(_mesh(V, C(epi_band), 0.5)), "Tubal epithelium (ciliated & peg cells)", G, "#9c6bb0",
                       DESC["tube_epi"], "mucosa", micro=True, rank=3.2, detail=(0.1, 200.0, 0.95, 0)))
    # a few vessels in the wall
    ves = Mesh()
    for k in range(7):
        a_ = 2 * math.pi * k / 7 + 0.3
        rr = 0.23 if k % 2 else 0.185
        c = o + np.array([0.0, rr * math.sin(a_), rr * math.cos(a_)])
        ves.extend(tube(np.array([c + (-0.04, 0, 0), c + (FACE, 0, 0)]), 0.009 if k % 2 else 0.006, 10))
    parts.append(_part(ves, "Blood vessels of tube wall", G, "#c43b3b", DESC["tube_vessels"], "artery",
                       micro=True, rank=3.1))
    return parts


# =============================================================================== specimen: endometrium with an implanted conceptus
ENDO_O = np.array([0.0, -0.62, -1.46])


def build_endometrium_specimen():
    parts = []
    G = "Magnified: endometrium & implantation"
    o = ENDO_O
    vox = 0.009
    V = _grid(o + (-0.30, -0.36, -0.46), o + (0.004, 0.30, 0.46), vox)
    x, y, z = V.axes()
    X = np.broadcast_to(x, V.shape)
    Y, Zl = y - o[1], z - o[2]
    top = 0.24 + 0.012 * np.sin(Zl * 18 + 0.5) * np.cos(x * 14) + 0.006 * fbm3(x * 9, 0.0, z * 9, 1.0, 2, 3)
    box = _mx(np.abs(Zl) - 0.45 + 0.0 * x, -0.30 - x, -0.35 - Y)
    cc = o + np.array([0.0, 0.12, 0.22])                                   # conceptus centre
    cz_r = 0.10
    conc = _sph(x, y, z, cc, cz_r + 0.004)
    # uterine glands: saw-toothed (secretory phase) tubes from the surface down into the basal layer
    rng = np.random.default_rng(2)
    gl_out, gl_in = _empty(V), _empty(V)
    for xg in (-0.01, -0.12, -0.23):
        for zg in np.arange(-0.40, 0.42, 0.105) + (0.05 if xg < -0.05 else 0.0):
            if abs(zg - 0.22) < 0.13 and xg > -0.2:
                continue
            ys = np.linspace(0.235, -0.17, 26)
            amp = 0.012 * np.clip((ys + 0.12) / 0.2, 0, 1)
            zz_ = zg + amp * np.sign(np.sin(ys * 95 + rng.uniform(0, 6)))
            xx_ = xg + 0.4 * amp * np.cos(ys * 60)
            path = np.stack([o[0] + xx_, o[1] + ys, o[2] + zz_], -1)
            r_o = np.interp(ys, [-0.17, 0.0, 0.235], [0.013, 0.019, 0.014])
            _apply(V, gl_out, _tube_d(path, r_o), "smin", 0.004)
            _apply(V, gl_in, _tube_d(path + (0, 0.004, 0), r_o * 0.45))
    # radial arteries rising through the myometrium, straight (basal) branches and the coiled spiral arteries
    art_sp, art_st = Mesh(), Mesh()
    chan = _empty(V)
    for k, zs in enumerate((-0.33, -0.1, 0.12, 0.36)):
        base = o + np.array([-0.018, -0.36, zs])
        rise = np.array([base, base + (0, 0.16, 0.0)])
        t_ = np.linspace(0, 1, 160)
        hel = np.stack([o[0] - 0.018 + 0.011 * np.cos(t_ * 14 * math.pi), o[1] - 0.20 + t_ * 0.40,
                        o[2] + zs + 0.022 * np.sin(t_ * 14 * math.pi)], -1)
        hel = hel[hel[:, 1] < o[1] + (0.05 if abs(zs - 0.12) < 0.05 else 0.22)]
        sp = np.vstack([rise, hel])
        art_sp.extend(tube(sp, np.linspace(0.012, 0.006, len(sp)), 10))
        _apply(V, chan, _tube_d(sp[::3], 0.017))
        _apply(V, chan, _tube_d(np.array([sp[0], sp[0] + (0.05, 0, 0)]), 0.016))
        for sd in (-1, 1):
            b0 = base + (0, 0.155, 0)
            st = np.array([b0, b0 + (0.004, 0.02, sd * 0.03), b0 + (0.008, 0.05, sd * 0.045)])
            art_st.extend(tube(st, 0.005, 8))
            _apply(V, chan, _tube_d(st, 0.009))
    # open the channels only near the cut face, so the vessels show as sectioned coils in grooves
    chan = np.maximum(chan, -0.03 - x).astype(np.float32)
    D = lambda lo, hi: _mx(box, lo - Y, Y - hi)       # noqa: E731
    holes = _mn(gl_out, conc, chan)
    myo = _mx(D(-0.35, -0.20), -conc, -chan)
    basal = _mx(D(-0.20, -0.12), -gl_out, -chan)
    func = _mx(box, -0.12 - Y, Y - (top - 0.016), -holes)
    epi = _mx(box, (top - 0.016) - Y, Y - top, -_sph(x, y, z, cc, cz_r - 0.02))
    glands = _mx(gl_out, -gl_in, Y - top + 0.004, box)
    C = lambda f: _cut(f, X)       # noqa: E731
    parts.append(_part(_clean(_mesh(V, C(myo), 0.8)), "Myometrium (inner layer)", G, "#bf625c", DESC["endo_myo"],
                       "muscle", micro=True, rank=3, detail=(0.08, 70.0, 0.35, 0)))
    parts.append(_part(_clean(_mesh(V, C(basal), 0.8)), "Stratum basalis (basal layer)", G, "#9c3e52",
                       DESC["basalis"], "mucosa", micro=True, rank=3.1, detail=(0.08, 180.0, 0.9, 0)))
    parts.append(_part(_clean(_mesh(V, C(func), 0.8)), "Stratum functionalis (functional layer)", G, "#d4798a",
                       DESC["functionalis"], "mucosa", micro=True, rank=3.2, detail=(0.08, 150.0, 0.85, 0)))
    parts.append(_part(_clean(_mesh(V, C(epi), 0.6)), "Uterine surface epithelium", G, "#8a5aa6", DESC["ut_epi"],
                       "mucosa", micro=True, rank=3.3, detail=(0.1, 220.0, 0.95, 0)))
    parts.append(_part(_clean(_mesh(V, C(glands), 0.6)), "Uterine glands", G, "#a95e9a", DESC["ut_glands"], "gland",
                       micro=True, rank=3.3))
    for m, name, col, key in ((art_sp, "Spiral arteries", "#c62f35", "spiral"),
                              (art_st, "Straight (basal) arteries", "#d9544c", "straight")):
        clipped = Mesh()
        for pos_, nrm_, idx_ in m.parts:
            pos_ = pos_.copy()
            pos_[:, 0] = np.minimum(pos_[:, 0], FACE)
            clipped.add(pos_, idx_)
        parts.append(_part(clipped, name, G, col, DESC[key], "artery", micro=True, rank=3.4))
    # the conceptus, about day 12-13, sectioned: trophoblast round the chorionic cavity, the bilaminar disc between
    # the amniotic cavity and the yolk sac, hung from the wall by the connecting stalk
    tro = Mesh().extend(_half_shell(cc, cz_r - 0.02, cz_r, 22))
    for k in range(26):
        th = rng.uniform(0, 2 * math.pi)
        c = cc + np.array([0.0, math.sin(th), math.cos(th)]) * (cz_r + 0.004)
        tro.extend(_half_ball(c + (-0.002, 0, 0), 0.012, 8))
    parts.append(_part(tro, "Trophoblast of implanted blastocyst", G, "#b77a5a", DESC["trophoblast_imp"], "gland",
                       micro=True, rank=3.5))
    parts.append(_part(_half_ball(cc, cz_r - 0.021, 20), "Chorionic cavity (extraembryonic coelom)", G, "#fbf3ea",
                       DESC["chorionic"], "csf", alpha=0.22, micro=True, rank=3.4))
    am_c = cc + np.array([0.0, -0.042, 0.0])
    parts.append(_part(_half_shell(am_c, 0.024, 0.030, 16, squash=(1.0, 0.75, 1.0)), "Amniotic sac (amnion)", G,
                       "#9ec3e6", DESC["amnion"], "serosa", micro=True, rank=3.6))
    parts.append(_part(_half_ball(am_c, 0.0235, 16, squash=(1.0, 0.72, 1.0)), "Amniotic cavity", G, "#dbeefa",
                       DESC["amn_cavity"], "csf", alpha=0.6, micro=True, rank=3.55))
    parts.append(_part(_half_ball(cc + (0, -0.022, 0), 0.034, 16, squash=(1.0, 0.16, 1.0)),
                       "Embryonic disc - ectoderm (epiblast)", G, "#4f86c9", DESC["epiblast"], "nucleus",
                       micro=True, rank=3.7))
    parts.append(_part(_half_ball(cc + (0, -0.0135, 0), 0.034, 16, squash=(1.0, 0.13, 1.0)),
                       "Embryonic disc - endoderm (hypoblast)", G, "#e0c34c", DESC["hypoblast"], "nucleus",
                       micro=True, rank=3.7))
    ys_c = cc + np.array([0.0, 0.014, 0.0])
    parts.append(_part(_half_shell(ys_c, 0.022, 0.027, 16, squash=(1.0, 0.8, 1.0)), "Yolk sac", G, "#e8d27a",
                       DESC["yolk"], "gland", micro=True, rank=3.6))
    parts.append(_part(_half_ball(cc + (0, -0.078, 0.004), 0.016, 12, squash=(1.0, 1.6, 1.0)), "Connecting stalk", G,
                       "#c9a47c", DESC["stalk"], "fascia", micro=True, rank=3.6))
    return parts


# =============================================================================== specimen row: fertilisation to blastocyst
ROW_Y = 1.36
ROW_Z = [-0.52, -0.76, -1.00, -1.24, -1.48, -1.72, -1.97]


def _packed(n, R, r, seed):
    """n sphere centres of radius r packed inside radius R (a few relaxation steps of mutual repulsion)."""
    rng = np.random.default_rng(seed)
    p = rng.normal(size=(n, 3))
    p = p / np.linalg.norm(p, axis=1, keepdims=True) * (R - r) * rng.uniform(0.3, 1.0, (n, 1)) ** 0.33
    for _ in range(80):
        d = p[:, None, :] - p[None, :, :]
        dist = np.linalg.norm(d, axis=2) + np.eye(n)
        push = np.clip(2 * r * 0.93 - dist, 0, None)
        p += (d / dist[..., None] * push[..., None]).sum(1) * 0.5
        ln = np.linalg.norm(p, axis=1, keepdims=True)
        p = np.where(ln > R - r, p / ln * (R - r), p)
    return p


def build_embryo_row():
    parts = []
    G = "Magnified: fertilization to blastocyst"
    cen = [np.array([0.0, ROW_Y, zz]) for zz in ROW_Z]
    zona, cells, oo, cor, sperm = Mesh(), {}, Mesh(), Mesh(), Mesh()
    rz_in, rz_out = 0.046, 0.054
    # 0: ovulated secondary oocyte in its corona radiata, sperm arriving
    c = cen[0]
    oo.extend(_half_ball(c, rz_in - 0.002, 18))
    zona.extend(_half_shell(c, rz_in, rz_out, 18))
    rng = np.random.default_rng(6)
    for k in range(70):
        d = _unit(rng.normal(size=3))
        if d[0] > 0.2:
            continue
        cor.extend(ellipsoid_mesh(c + d * rng.uniform(0.062, 0.078), (0.009, 0.009, 0.009), 7))
    for k in range(5):
        th = rng.uniform(0, 2 * math.pi)
        d = np.array([-0.3, math.sin(th), math.cos(th)])
        d /= np.linalg.norm(d)
        head = c + d * 0.088
        tail = smooth_path(np.array([head + d * 0.012, head + d * 0.05 + rng.normal(0, 0.01, 3),
                                     head + d * 0.10 + rng.normal(0, 0.015, 3)]), 20)
        sperm.extend(ellipsoid_mesh(head, (0.005, 0.008, 0.008), 8))
        sperm.extend(tube(tail, np.linspace(0.0035, 0.001, len(tail)), 6))
    # 1: zygote with its two pronuclei
    c = cen[1]
    zona.extend(_half_shell(c, rz_in, rz_out, 18))
    zyg = _half_ball(c, rz_in - 0.002, 18)
    pn_egg = _half_ball(c + (0, 0.004, -0.014), 0.012, 12)
    pn_sp = _half_ball(c + (0, -0.004, 0.015), 0.011, 12)
    # 2-5: cleavage, blastomeres getting smaller while the whole stays the size of the zygote
    for i, (n, r) in zip(range(2, 6), ((2, 0.03), (4, 0.025), (8, 0.02), (18, 0.0145))):
        c = cen[i]
        zona.extend(_half_shell(c, rz_in, rz_out, 18))
        pts = _packed(n, rz_in - 0.002, r, i) if n > 2 else np.array([[0, 0, -0.022], [0, 0.0, 0.022]])
        m = Mesh()
        for q in pts:
            m.extend(ellipsoid_mesh(c + q, (r, r, r) * np.array([1.0, 1.0, 1.0]), 12))
        cells[i] = m
    # 6: blastocyst - trophoblast, inner cell mass and the blastocele, hatching from the zona
    c = cen[6]
    zona.extend(_half_shell(c, 0.058, 0.063, 18))
    tb = _half_shell(c, 0.049, 0.056, 20)
    icm = Mesh()
    for q in _packed(9, 0.024, 0.0105, 7):
        icm.extend(_half_ball(c + np.array([0.0, 0.028, 0.0]) + q * (0, 1, 1), 0.0105, 10))
    parts.append(_part(oo, "Ovulated secondary oocyte", G, "#f3d6dc", DESC["ovulated"], "nucleus", micro=True,
                       rank=4))
    parts.append(_part(cor, "Corona radiata cells (ovulated oocyte)", G, "#c483a8", DESC["corona_ov"], "gland",
                       micro=True, rank=4))
    parts.append(_part(sperm, "Sperm cells", G, "#e8e2a8", DESC["sperm"], "nucleus", micro=True, rank=4))
    parts.append(_part(zona, "Zona pellucida (early embryo)", G, "#f5f1ff", DESC["zona_emb"], "mucosa", alpha=0.8,
                       micro=True, rank=4))
    parts.append(_part(zyg, "Zygote", G, "#f1cfd6", DESC["zygote"], "nucleus", micro=True, rank=4))
    parts.append(_part(pn_egg, "Egg pronucleus", G, "#c85a86", DESC["pn_egg"], "nucleus", micro=True, rank=4.1))
    parts.append(_part(pn_sp, "Sperm pronucleus", G, "#5a78c8", DESC["pn_sperm"], "nucleus", micro=True, rank=4.1))
    for i, name, key in ((2, "2-cell stage", "cell2"), (3, "4-cell stage", "cell4"), (4, "8-cell stage", "cell8"),
                         (5, "Morula", "morula")):
        parts.append(_part(cells[i], name, G, "#eab9c6", DESC[key], "nucleus", micro=True, rank=4))
    parts.append(_part(tb, "Blastocyst - trophoblast", G, "#c58a6a", DESC["trophoblast"], "gland", micro=True,
                       rank=4))
    parts.append(_part(icm, "Blastocyst - inner cell mass", G, "#7f6bc0", DESC["icm"], "nucleus", micro=True,
                       rank=4.1))
    parts.append(_part(_half_ball(c, 0.048, 18), "Blastocele (blastocyst cavity)", G, "#e8f1f8", DESC["blastocele"],
                       "csf", alpha=0.35, micro=True, rank=3.9))
    return parts


SECTIONS = {"skeleton": build_skeleton, "uterus": build_uterus, "vagina": build_vagina, "neighbours": build_neighbours,
            "floor": build_floor, "adnexa": build_adnexa, "ligaments": build_ligaments, "vulva": build_vulva,
            "ovary": build_ovary_specimen, "breast": build_breast, "tube": build_tube_specimen,
            "endometrium": build_endometrium_specimen, "embryo": build_embryo_row}
PELVIS = ("skeleton", "uterus", "vagina", "neighbours", "floor", "adnexa", "ligaments", "vulva")


def build_female():
    """The whole model: the pelvis (with one gentle shared warp, so its organs lose their machined look but stay in
    register) followed by the four specimens and the row of early embryos."""
    pelvis = []
    for k in PELVIS:
        pelvis += SECTIONS[k]()
    warp_parts(pelvis, noise_field((0.006, 0.006, 0.006), 2.2, 2, seed=7))
    out = [p for p in pelvis if p.mesh.parts]
    for k in SECTIONS:
        if k not in PELVIS:
            out += [p for p in SECTIONS[k]() if p.mesh.parts]
    return out
