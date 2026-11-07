"""The camera fitted to the game's own sprites: for a unit, its outline rendered from many angles
(flat, quick) and compared with the game's sprite for each direction; the angle, the turn per
direction and the size (pixels per LDraw unit) that match best.

    python -m wbrender.fit UNIT [UNIT ...] [--elevations 20,25,30,35,40] [--step 6]

Writes config/fit/<unit>.json: {elevation, scale, headings: {dir: degrees}, iou: {dir: score}}.
The match is the overlap of the two outlines (intersection over union), the render's moved a
pixel or two to sit best on the game's."""
import argparse
import json
import os
import shutil

import numpy as np
from PIL import Image

from . import blender, post
from .units import UNITS, model_path, ref_path

ROOT = blender.ROOT
DIRS = ('right', 'left', 'up', 'down')
WINDOW = 35       # degrees a direction's turn may stray from the others' pattern


def crop(m):
    ys, xs = np.nonzero(m)
    if not len(xs):
        return m[:1, :1]
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def iou(a, b, slack=2):
    """The best overlap of two masks, their centres aligned, moved up to slack pixels."""
    a, b = crop(a), crop(b)
    H, W = max(a.shape[0], b.shape[0]) + 2 * slack + 2, max(a.shape[1], b.shape[1]) + 2 * slack + 2
    A = np.zeros((H, W), bool)
    ay, ax = (H - a.shape[0]) // 2, (W - a.shape[1]) // 2
    A[ay:ay + a.shape[0], ax:ax + a.shape[1]] = a
    best = 0.0
    by0, bx0 = (H - b.shape[0]) // 2, (W - b.shape[1]) // 2
    for dy in range(-slack, slack + 1):
        for dx in range(-slack, slack + 1):
            B = np.zeros((H, W), bool)
            y, x = by0 + dy, bx0 + dx
            if y < 0 or x < 0 or y + b.shape[0] > H or x + b.shape[1] > W:
                continue
            B[y:y + b.shape[0], x:x + b.shape[1]] = b
            u = (A | B).sum()
            if u:
                best = max(best, (A & B).sum() / u)
    return best


def ortho_size(radius, skew):
    """As blender/wbsprite.py's ortho_size: the frame's width in blender units."""
    return radius * 2 * 1.08 * (1 + abs(skew))


def sweep(unit, elevations, step, size, work, headings=None, skews=(0.0,)):
    """Silhouettes of the unit from each elevation, skew and heading: {(elev, skew, heading): path},
    and the frame."""
    os.makedirs(work, exist_ok=True)
    hs = headings if headings is not None else list(range(0, 360, step))
    shots = [{'path': os.path.join(work, 'e%g_s%g_h%g.png' % (e, k, h)), 'heading': h, 'elevation': e, 'skew': k}
             for e in elevations for k in skews for h in hs]
    from .units import UNITS as U
    r = blender.run({'model': model_path(unit), 'mode': 'silhouette', 'size': size, 'shots': shots, 'studs': U[unit].get('studs', 'none')})
    return {(s['elevation'], s['skew'], s['heading']): s['path'] for s in shots}, r


def fit_unit(unit, elevations, step=6, size=192, scales=None, refine=True, keep=False, skews=(0.0,), fixed=False, out=None, axes=False):
    """axes: the turns square, 0/90/180/270 only (the game's well-matched units all are, within a few
    degrees: its renders were turned square; a unit whose recreation is posed unlike the game's
    otherwise fits each direction its own odd turn)"""
    work = os.path.join(ROOT, 'work', 'fit', unit)
    refs = {}
    for d in DIRS:
        p = ref_path(unit, d)
        if p:
            refs[d] = post.reference_mask(Image.open(p))
    if not refs:
        raise SystemExit('%s has no sprites in the game to fit to' % unit)
    shots, info = sweep(unit, elevations, step, size, work, headings=[0, 90, 180, 270] if axes else None, skews=skews)
    radius = info['radius']
    if scales is None:
        # (about the size the game's sprites are: their areas against the silhouettes' -- each
        # silhouette measured in blender units, the median of them all)
        ref_area = np.median([crop(m).sum() for m in refs.values()])
        areas = []
        for key in list(shots)[::max(1, len(shots) // 40)]:
            m = post.mask_of(Image.open(shots[key]))
            areas.append(m.sum() / (size / ortho_size(radius, key[1])) ** 2)
        base = float(np.sqrt(ref_area / np.median(areas)))
        scales = [float(x) for x in np.round(base * np.linspace(0.75, 1.3, 15), 3)]
    cache = {}

    def masks(key, k):
        # key: (elevation, skew, heading); k: final pixels per blender unit
        if (key, k) not in cache:
            ppu = size / ortho_size(radius, key[1])
            cache[(key, k)] = post.mask_of(Image.open(shots[key]), 0.5, ppu / k)
        return cache[(key, k)]

    # (each elevation, skew and size: every direction's score at every heading)
    table = {}   # (elev, skew, k) -> {d: {heading: score}}
    for key in shots:
        e, sk, h = key
        for k in scales:
            m = masks(key, k)
            row = table.setdefault((e, sk, k), {})
            for d, R in refs.items():
                row.setdefault(d, {})[h] = iou(m, R)

    def choose(row):
        """The four turns kept together: left about right + 180, up about + 90, down about + 270
        (within WINDOW degrees), so that a unit alike from either side is not turned the wrong way."""
        best = (-1, None)
        for b in row.get('right', {0: 0}):
            total, picks = row.get('right', {}).get(b, 0), ({'right': b} if 'right' in row else {})
            for d, off in (('left', 180), ('up', 90), ('down', 270)):
                if d not in row:
                    continue
                cands = [(sc, h) for h, sc in row[d].items() if abs(((h - b - off + 180) % 360) - 180) <= WINDOW]
                if cands:
                    sc, h = max(cands)
                    total += sc
                    picks[d] = h
            if total > best[0]:
                best = (total, picks)
        return best

    (e, sk, k), (total, picks) = max(((ek, choose(row)) for ek, row in table.items()), key=lambda x: x[1][0])
    row = table[(e, sk, k)]
    result = {'unit': unit, 'elevation': e, 'skew': sk, 'scale': float(k), 'radius': radius,
              'headings': {d: int(h) for d, h in picks.items()}, 'iou': {d: round(float(row[d][h]), 4) for d, h in picks.items()}}
    if refine:
        # a finer look round the best: elevation and skew a little either side, each turn to the degree
        es = [e] if fixed else sorted({e - 2.5, e, e + 2.5})
        sks = [sk] if fixed else sorted({round(sk - 0.08, 3), sk, round(sk + 0.08, 3)})
        spread = range(0, 1) if axes else range(-step + 1, step)
        hs = sorted({(h + dh) % 360 for h in result['headings'].values() for dh in spread})
        shots2, _ = sweep(unit, es, 1, size, work, hs, sks)
        shots.update(shots2)
        ks = [round(k * f, 4) for f in (0.96, 0.98, 1.0, 1.02, 1.04)]
        best = None
        for e2 in es:
            for s2 in sks:
                for k2 in ks:
                    row2 = {}
                    for d, R in refs.items():
                        h0 = result['headings'][d]
                        for dh in spread:
                            h2 = (h0 + dh) % 360
                            if (e2, s2, h2) not in shots:
                                continue
                            sc = iou(masks((e2, s2, h2), k2), R)
                            if sc > row2.get(d, (0, None))[0]:
                                row2[d] = (sc, h2)
                    total = sum(v[0] for v in row2.values())
                    if best is None or total > best[0]:
                        best = (total, e2, s2, k2, row2)
        _, e2, s2, k2, row2 = best
        result.update({'elevation': e2, 'skew': s2, 'scale': float(k2), 'headings': {d: int(v[1]) for d, v in row2.items()},
                       'iou': {d: round(float(v[0]), 4) for d, v in row2.items()}})
    dest = out or os.path.join(ROOT, 'config', 'fit')
    os.makedirs(dest, exist_ok=True)
    json.dump(result, open(os.path.join(dest, unit + '.json'), 'w'), indent=1)
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('units', nargs='+')
    ap.add_argument('--elevations', default='20,25,30,35,40,45')
    ap.add_argument('--step', type=int, default=6)
    ap.add_argument('--size', type=int, default=192)
    ap.add_argument('--skews', default='-0.25,0,0.25,0.5')
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--fixed', action='store_true', help='the elevation and skew as given (one each): the shared camera; only the turns and size fitted')
    ap.add_argument('--out', help='write the fits to this folder instead of config/fit')
    ap.add_argument('--axes', action='store_true', help='the turns square: 0, 90, 180, 270 only')
    a = ap.parse_args()
    els = [float(x) for x in a.elevations.split(',')]
    for u in (UNITS if a.units == ['all'] else a.units):
        if UNITS[u].get('unused'):
            continue
        r = fit_unit(u, els, a.step, a.size, keep=a.keep, skews=[float(x) for x in a.skews.split(',')], fixed=a.fixed, out=a.out, axes=a.axes)
        print('%-12s elevation %5.1f  skew %5.2f  scale %.3f  headings %s  iou %s  mean %.3f' % (u, r['elevation'], r['skew'], r['scale'], r['headings'], r['iou'], np.mean(list(r['iou'].values()))), flush=True)


if __name__ == '__main__':
    main()
