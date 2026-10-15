"""Label anchors and silhouettes for the labels checkpoint, from the renderer's picking buffers (read only).
Same rule as tools/process_plates.py: the largest connected piece of the structure on each side of the body's
midline, anchored at its most inscribed pixel. Also exports each plate's silhouette (alpha) as runs of cells, so the
placer knows where the body is. Writes app/specimen-labels/labels-data.js.
Usage: python anchors.py RAW_DIR   (RAW_DIR holds <id>__ids.npz and <id>__ids.json from tools/capture, as for
process_plates.py). Reads only; prints which wanted structures are not visible in each picking buffer."""
import json, sys
import numpy as np
from PIL import Image
from scipy import ndimage
from pathlib import Path
RAW = sys.argv[1]
D = str(Path(__file__).resolve().parents[2])
PL = json.load(open(f'{D}/assets/plates/plates.json'))['plates']

JOBS = {
  'hero26_sel_7cc8da': ('hero26', 'hero26_sel_ffffff', 6, {
    'biceps': ['Long head of biceps brachii', 'Short head of biceps brachii'],
    'deltoid': ['Acromial part of deltoid muscle', 'Clavicular part of deltoid muscle'],
    'serratus': ['Serratus anterior muscle'], 'rectus_abdominis': ['Rectus abdominis muscle'],
    'pectoralis': ['Clavicular head of pectoralis major muscle', 'Sternocostal head of pectoralis major muscle', 'Abdominal part of pectoralis major muscle'],
    'sternocleidomastoid': ['Sternocleidomastoid muscle'], 'temporalis': ['Temporalis muscle'],
    'ext_oblique': ['External abdominal oblique muscle'],
    'sternohyoid': ['Sternohyoid muscle'], 'int_oblique': ['Internal abdominal oblique muscle'],
    'sartorius': ['Sartorius muscle'], 'rectus_femoris': ['Rectus femoris muscle'],
    'tibialis_anterior': ['Tibialis anterior muscle'], 'brachioradialis': ['Brachioradialis muscle'],
    'temporal_bone': ['Temporal bone'], 'mandible': ['Mandible'], 'pec_minor': ['Pectoralis minor muscle'],
  }),
  'section_inferior': ('secinf', 'section_inferior', 4, {
    'pec': ['Sternocostal head of pectoralis major muscle', 'Abdominal part of pectoralis major muscle'],
    'lung_r': ['Middle lobe of right lung', 'Inferior lobe of right lung', 'Superior lobe of right lung'],
    'lung_l': ['Inferior lobe of left lung', 'Superior lobe of left lung'],
    'liver': ['Posterior medial segment of liver (VIII)', 'Liver'], 'diaphragm': ['Diaphragm'],
    'ra': ['Right atrium'], 'la': ['Left atrium'], 'rv': ['Right ventricle'], 'lv': ['Left ventricle'],
    'lat': ['Latissimus dorsi muscle'], 'serratus': ['Serratus anterior muscle'], 'humerus': ['Humerus'],
    'triceps': ['Long head of triceps brachii', 'Lateral head of triceps brachii', 'Medial head of triceps brachii'],
    'biceps': ['Long head of biceps brachii', 'Short head of biceps brachii'],
    'sternum': ['Body of sternum'], 'oesophagus': ['Oesophagus', 'Esophagus'], 'aorta': ['Thoracic aorta'],
    'vert': ['Vertebra T8'], 'trapezius': ['Descending part of trapezius muscle'], 'pleura': ['Pleura'],
    'teres_major': ['Teres major muscle'], 'scapula': ['Scapula'], 'deltoid': ['Scapular spinal part of deltoid muscle', 'Clavicular part of deltoid muscle'],
  }),
}

def anchor(big, x0, y0):
    dist = ndimage.distance_transform_edt(np.pad(big, 1))[1:-1, 1:-1]
    y, x = np.unravel_index(int(np.argmax(dist)), dist.shape)
    ys, xs = np.nonzero(big)
    return {'x': int(x - x0), 'y': int(y - y0), 'r': round(float(dist[y, x]), 1),
            'bbox': [int(xs.min() - x0), int(ys.min() - y0), int(xs.max() - x0), int(ys.max() - y0)], 'area': int(big.sum())}

def largest(m):
    lab, n = ndimage.label(m)
    if n == 0: return None
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    return lab == (1 + int(np.argmax(sizes)))

out, report = {}, []
for plate, (idn, alpha_plate, step, targets) in JOBS.items():
    ids = np.load(f'{RAW}/{idn}__ids.npz')['ids']
    names = {int(k): v for k, v in json.load(open(f'{RAW}/{idn}__ids.json')).items()}
    x0, y0, x1, y1 = PL[plate]['box']
    body = ids >= 0
    xs = np.nonzero(body.any(axis=0))[0]; mid = (xs.min() + xs.max()) / 2
    A = {}
    for key, wanted in targets.items():
        mask = np.isin(ids, [s for s, n in names.items() if n in wanted])
        if mask.sum() < 30:
            report.append(f'{plate}: {key} NOT VISIBLE ({int(mask.sum())} px)'); continue
        for side, sl in (('vl', slice(0, int(mid))), ('vr', slice(int(mid), ids.shape[1]))):
            m = np.zeros_like(mask); m[:, sl] = mask[:, sl]
            if m.sum() < 30: continue
            A[f'{key}.{side}'] = anchor(largest(m), x0, y0)
        A[f'{key}.c'] = anchor(largest(mask), x0, y0)
        report.append(f'{plate}: {key} ' + ' '.join(f"{k.split('.')[1]}=({v['x']},{v['y']}) r{v['r']} a{v['area']}" for k, v in A.items() if k.split('.')[0] == key))
    # silhouette: plate alpha in cells of `step` plate pixels, as runs per row
    a = np.asarray(Image.open(f'{D}/assets/plates/{alpha_plate}.webp').convert('RGBA'))[:, :, 3] > 24
    H, W = a.shape; R, C = (H + step - 1) // step, (W + step - 1) // step
    pad = np.zeros((R * step, C * step), bool); pad[:H, :W] = a
    cells = pad.reshape(R, step, C, step).any(axis=(1, 3))
    rows = []
    for r in range(R):
        v = np.concatenate([[0], cells[r].astype(np.int8), [0]]); d = np.diff(v)
        st, en = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
        rows.append([int(t) for pair in zip(st, en) for t in pair])
    out[plate] = {'anchors': A, 'sil': {'step': step, 'cols': C, 'rows': rows}, 'size': [W, H]}
js = '/* Label anchors and plate silhouettes for the labels checkpoint (generated by cp2-labels/anchors.py from the\n   renderer picking buffers; same rule as tools/process_plates.py). sil.rows: per row of `step` plate pixels, [start, end) runs of cells. */\nwindow.LBL_DATA = ' + json.dumps(out, separators=(',', ':')) + ';\n'
open(f'{D}/app/specimen-labels/labels-data.js', 'w').write(js)
print('\n'.join(report)); print(len(js), 'bytes')
