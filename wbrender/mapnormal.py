"""The map sprites lit as the portraits are (wbrender/heronormal.py), as a trial against the passes'
compositor (wbrender/shade.py): each unit's sprites rendered from its fitted map camera as colour
ids, the sky's light and each pixel's surface direction, brought to the game's size, laid on the
game's sprites, and a light rig -- lights from any direction, the sky, a gamma, the palette solved
alongside, every channel clipped as the game's are -- fitted face by face over many units at once.
The game's map sprites were rendered in one batch, so one rig for them all.

    python -m wbrender.mapnormal fit [UNIT ...]     # the rig, and how it compares with the sprites made now
"""
import argparse
import json
import os

import numpy as np
from PIL import Image

from . import blender, post
from .units import UNITS, ROOT, model_path, ref_path
from .fit import DIRS, ortho_size
from .render import load_fit, style
from .shade import shrink_field, shrink_codes, fill_codes, align, crop, erode
from .heronormal import light_dir

OUT = os.path.join(ROOT, 'config', 'map_light.json')
REFS = ['buggy', 'duck', 'dirtbuggy', 'dozer', 'dumptruck', 'frog', 'fish', 'snail', 'speedboat', 'defender', 'repairbot', 'treebot', 'tugboat', 'forklift']
NEUTRAL = ('0', '256', '15', '7', '8', '71', '72')


def passes(unit, size=320, samples=16):
    """{direction: {codes, alpha, A, N}} at render size, and the pixels per blender unit."""
    fit = load_fit(unit)
    work = os.path.join(ROOT, 'work', 'mapnormal', unit)
    os.makedirs(work, exist_ok=True)
    dirs = [d for d in DIRS if ref_path(unit, d)]
    params = {'elevation': fit['elevation'], 'skew': fit.get('skew', 0.0), 'passes': [('ambient', None)],
              'height_pass': False, 'normal_pass': True}
    shots = [{'path': os.path.join(work, d), 'heading': fit['headings'][d]} for d in dirs]
    r = blender.run({'model': model_path(unit), 'mode': 'passes', 'size': size, 'samples': samples, 'shots': shots,
                     'studs': UNITS[unit].get('studs', style().get('studs', 'none')), 'params': params})
    legend = r['legend']
    out = {}
    for d in dirs:
        base = os.path.join(work, d)
        idim = np.asarray(Image.open(base + '.id.png').convert('RGBA'))
        codes = np.full(idim.shape[:2], '', dtype=object)
        for key, v in legend.items():
            rgb = tuple(int(x) for x in key.split(','))
            codes[(idim[..., 0] == rgb[0]) & (idim[..., 1] == rgb[1]) & (idim[..., 2] == rgb[2]) & (idim[..., 3] > 0)] = v['code']

        def img(name):
            a = np.asarray(Image.open(base + '.' + name + '.png'))
            return a.astype(np.float32) / (65535.0 if a.dtype == np.uint16 else 255.0)
        A = img('ambient')
        n = img('normal')[..., :3] * 2 - 1
        n[..., 2] *= -1
        out[d] = {'codes': codes, 'alpha': A[..., 3], 'A': A[..., 0] / 0.8, 'N': n}
    ppu = size / ortho_size(r['radius'], fit.get('skew', 0.0))
    return out, ppu / fit['scale']


def samples(unit):
    """Pixel samples laid on the game's sprites: per direction, the codes, sky, normals and the game's colours
    where the render shows one colour's surface well inside; and our sprite's colours there."""
    P, factor = passes(unit)
    rows = []
    for d, p in P.items():
        A, cov = shrink_field(p['A'], p['alpha'], factor)
        N = np.stack([shrink_field(p['N'][..., i], p['alpha'], factor)[0] for i in range(3)], -1)
        N /= np.maximum(np.linalg.norm(N, axis=-1, keepdims=True), 1e-6)
        codes = fill_codes(shrink_codes(p['codes'], factor), cov)
        ref = Image.open(ref_path(unit, d))
        R = post.reference_mask(ref)
        G = np.asarray(ref.convert('RGB'), np.float32) / 255.0
        mine = cov >= 0.5
        ys, xs = np.nonzero(mine)
        y0, x0 = ys.min(), xs.min()
        cm = crop(mine)
        oy, ox = align(cm, crop(R))
        ry, rx = np.nonzero(R)
        inner = erode(erode(cm))
        # our current sprite, laid the same way (out/<unit>/<name>.png)
        name = UNITS[unit]['sprite'] + ('.' + d + UNITS[unit].get('still', '') if not UNITS[unit].get('single') else '')
        ours = None
        op = os.path.join(ROOT, 'out', unit, name + '.png')
        if os.path.exists(op):
            oa = np.asarray(Image.open(op).convert('RGBA'), np.float32) / 255.0
            om = oa[..., 3] > 0.5
            oys, oxs = np.nonzero(om)
            ocm = crop(om)
            ooy, oox = align(ocm, crop(R))
            ours = (oa[oys.min():oys.max() + 1, oxs.min():oxs.max() + 1, :3], ooy, oox)
        for y, x in zip(*np.nonzero(inner)):
            gy, gx = ry.min() + oy + y, rx.min() + ox + x
            if not (0 <= gy < R.shape[0] and 0 <= gx < R.shape[1]) or not R[gy, gx]:
                continue
            c = codes[y0 + y, x0 + x]
            if not c:
                continue
            o = None
            if ours is not None:
                oy2, ox2 = gy - ry.min() - ours[1], gx - rx.min() - ours[2]
                if 0 <= oy2 < ours[0].shape[0] and 0 <= ox2 < ours[0].shape[1]:
                    o = ours[0][oy2, ox2]
            rows.append((d, c, N[y0 + y, x0 + x], A[y0 + y, x0 + x], G[gy, gx], o))
    return rows


def fit(units, tries=3000, steps=6000, seed=4):
    data = []
    for u in units:
        try:
            r = samples(u)
        except Exception as e:
            print('  %s: %s' % (u, e), flush=True)
            continue
        for row in r:
            data.append((u,) + row)
        print('  %s: %d pixels' % (u, len(r)), flush=True)
    U = np.array([d[0] for d in data])
    D = np.array([d[1] for d in data])
    C = np.array([d[2] for d in data])
    N = np.array([d[3] for d in data], np.float32)
    A = np.array([d[4] for d in data], np.float32)
    G = np.array([d[5] for d in data], np.float32)
    have_ours = np.array([d[6] is not None for d in data])
    O = np.array([d[6] if d[6] is not None else np.zeros(3) for d in data], np.float32)
    # faces: one colour, one surface direction, in one sprite
    q = np.clip(np.round((N + 1) * 1.5), 0, 3).astype(int)
    key = np.array(['%s|%s|%s|%d%d%d' % (u, d, c, a, b, e) for u, d, c, (a, b, e) in zip(U, D, C, q)])
    keys, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    ok = cnt >= 3
    faces = [np.nonzero(inv == i)[0] for i in np.nonzero(ok)[0]]
    FN = np.array([N[f].mean(0) / max(1e-6, np.linalg.norm(N[f].mean(0))) for f in faces], np.float32)
    FA = np.array([np.median(A[f]) for f in faces], np.float32)
    FG = np.array([np.median(G[f], 0) for f in faces], np.float32)
    FC = np.array([C[f[0]] for f in faces])
    unames = sorted(set(U))
    FU = np.array([unames.index(U[f[0]]) for f in faces])
    nU = len(unames)
    FW = np.sqrt(np.array([len(f) for f in faces], np.float32))
    codes = sorted(set(FC))
    print('%d faces of %d colours' % (len(faces), len(codes)), flush=True)
    # (what the sprites made now give on those faces)
    fo = [np.median(O[f][have_ours[f]], 0) if have_ours[f].any() else None for f in faces]
    cur = [(FW[i] * np.abs(o - FG[i]).mean()) for i, o in enumerate(fo) if o is not None]
    cur_w = [FW[i] for i, o in enumerate(fo) if o is not None]
    current = float(np.sum(cur) / np.sum(cur_w) * 255) if cur else None

    def shade_(x):
        amb, occ, gam = max(x[0], 0.01), np.clip(x[1], 0, 2), np.clip(x[2], 0.3, 3)
        v = amb * np.power(np.clip(FA, 1e-3, 1), occ)
        for i in range(3):
            w, e, a = max(x[3 + 3 * i], 0), np.clip(x[4 + 3 * i], -30, 89), x[5 + 3 * i]
            v = v + w * np.maximum(0, FN @ light_dir(e, a))
        v = np.power(np.maximum(v, 1e-4), gam)
        # (each unit's sprites at their own exposure, as the game's portraits were: the duck's yellow is
        # lemon, the dump truck's ochre)
        ex = np.exp(np.concatenate([[0.0], x[12:12 + nU - 1]]))
        return v * ex[FU]

    def palette_for(v):
        pal = {}
        for c in codes:
            m = FC == c
            qv = FG[m] / v[m][:, None]
            col = np.zeros(3, np.float32)
            for ch in range(3):
                okc = FG[m][:, ch] < 0.94
                if okc.any():
                    o = np.argsort(qv[okc, ch])
                    cw = np.cumsum(FW[m][okc][o])
                    col[ch] = qv[okc, ch][o][np.searchsorted(cw, cw[-1] / 2)]
                else:
                    col[ch] = 0.99 / v[m].min()
            if c in NEUTRAL:
                col[:] = col.mean()
            pal[c] = np.clip(col, 0, 3)
        return pal

    def error(x, want=False):
        v = shade_(x)
        pal = palette_for(v)
        P = np.stack([pal[c] for c in FC])
        pred = np.clip(P * v[:, None], 0, 1)
        e = float((FW * np.abs(pred - FG).mean(1)).sum() / FW.sum() * 255)
        return (e, pal) if want else e

    rng = np.random.default_rng(seed)
    best = None
    for t in range(tries):
        x = np.array([rng.uniform(0.05, 1.0), rng.uniform(0, 1.5), rng.uniform(0.5, 2.0)] +
                     sum([[1.0 if i == 0 else rng.uniform(0, 1.5), rng.uniform(-30, 85), rng.uniform(-180, 180)] for i in range(3)], []) +
                     list(rng.uniform(-0.2, 0.2, nU - 1)))
        e = error(x)
        if best is None or e < best[0]:
            best = (e, x)
    e, x = best
    step = np.array([0.05, 0.1, 0.1, 0, 6, 12, 0.1, 6, 12, 0.1, 6, 12] + [0.04] * (nU - 1))
    for it in range(steps):
        y = x + rng.normal(0, 1, len(x)) * step * (0.5 ** (it / 1500))
        ey = error(y)
        if ey < e:
            e, x = ey, y
    e, pal = error(x, want=True)
    flat = error(np.array([1.0, 0, 1.0] + [0, 0, 0] * 3 + [0.0] * (nU - 1)))
    print('faces: the new rig %.2f, flat light %.2f, the sprites made now %s' % (e, flat, '%.2f' % current if current is not None else '-'))
    L = {'ambient': float(x[0]), 'occlusion': float(x[1]), 'gamma': float(x[2]),
         'lights': [{'w': float(max(x[3 + 3 * i], 0)), 'elevation': float(np.clip(x[4 + 3 * i], -30, 89)),
                     'azimuth': float(((x[5 + 3 * i] + 180) % 360) - 180)} for i in range(3)]}
    for li in L['lights']:
        print('   w %.2f from elevation %.0f, azimuth %.0f' % (li['w'], li['elevation'], li['azimuth']))
    ex = np.exp(np.concatenate([[0.0], x[12:12 + nU - 1]]))
    g = float(np.exp(np.log(ex).mean()))
    # (the palette at the middle exposure; each fitted unit's own kept)
    pal = {c: v * g for c, v in pal.items()}
    print('exposures: ' + ', '.join('%s %.2f' % (u, e_ / g) for u, e_ in zip(unames, ex)))
    out = {'light': L, 'colours': {c: [int(round(float(t) * 255)) for t in pal[c]] for c in codes}, 'fitted_on': units,
           'exposures': {u: round(float(e_ / g), 3) for u, e_ in zip(unames, ex)},
           'face_error': round(e, 2), 'current_face_error': round(current, 2) if current is not None else None}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), indent=1)
    print('written to config/map_light.json')
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('what', choices=['fit'])
    ap.add_argument('units', nargs='*')
    a = ap.parse_args()
    fit(a.units or REFS)


if __name__ == '__main__':
    main()
