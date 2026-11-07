"""The portrait cameras fitted on the picture's inside, not only its outline: each try rendered flat
(each colour its plastic, no light), laid on the game's portrait as well as it will lie (registered:
scale and place), and scored by how far its colours are from the game's, pixel by pixel. Two cameras
with near the same outline put the faces in different places -- the buggy's tilt, the fish's -- and
only the inside tells them apart. The camera's roll (its turn about its own view) is fitted too.

    python -m wbrender.herocam duck buggy dirtbuggy ...      # config/hero/<unit>.json, refined

Starts from the unit's current camera (herofit's, or the shared one) and walks: turn and elevation
together, then roll, then lens, then all of them finer.  A camera set by eye ('pinned') is left."""
import argparse
import json
import os

import numpy as np
from PIL import Image

from . import blender
from .units import UNITS, ROOT, model_path, hero_ref
from .heroshade import registered, boxed
from .render import hero_camera

LUM = np.array([0.299, 0.587, 0.114], np.float32)


def flat_colours(legend):
    """Each colour's plastic for the flat tries: the world palette's (the game's own colours), else LDraw's."""
    from .shade import base_colour, palette
    W = palette()
    return {c: base_colour(c, legend, W) for c in legend}


def score(codes, alpha, legend, ref_rgba, cols):
    """The flat render against the game's portrait: (error 0..255, registration overlap)."""
    p = {'alpha': alpha, 'A': np.ones_like(alpha), 'K': [], 'S': [], 'R': [], 'codes': codes, 'legend': legend}
    reg = registered(p, ref_rgba)
    if not reg:
        return 255.0, 0.0
    R = np.asarray(ref_rgba.convert('RGB'), np.float32) / 255.0
    s = boxed(p, (R.shape[1], R.shape[0]), k=reg[1], at=reg[2])
    h, w = s['cov'].shape
    y, x = s['at']
    img = np.ones_like(R)
    sub = np.ones((h, w, 3), np.float32)
    for c in np.unique(s['codes']):
        if c:
            m = s['codes'] == c
            sub[m] = cols.get(c, np.array([0.5, 0.5, 0.5]))
    cov = s['cov'][..., None]
    img[y:y + h, x:x + w] = sub * cov + (1 - cov)
    m = (R.min(-1) < 0.95) | (img.min(-1) < 0.95)
    # (colour by its hue and lightness both: the game's lit faces are brighter than the flat plastic, so
    # each pixel's colour is compared as a direction more than as a level)
    a, b = img[m], R[m]
    an = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-3)
    bn = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-3)
    e = 0.5 * np.abs(an - bn).mean(1) + 0.5 * np.abs(a @ LUM - b @ LUM)
    return float(e.mean() * 255), float(reg[0])


def tries(unit, cams, size=256):
    """Each camera (heading, elevation, lens, roll) rendered flat: [(codes, alpha, legend)]."""
    work = os.path.join(ROOT, 'work', 'herocam', unit)
    os.makedirs(work, exist_ok=True)
    out = []
    # (each camera its own job: the camera's elevation, lens and roll are the job's settings)
    shots_by = {}
    for i, (h, e, l, r) in enumerate(cams):
        shots_by.setdefault((e, l, r), []).append((i, h))
    res = [None] * len(cams)
    for (e, l, r), hs in shots_by.items():
        shots = [{'path': os.path.join(work, 't%d' % i), 'heading': h} for i, h in hs]
        params = {'hero': True, 'hero_elevation': e, 'hero_lens': l, 'hero_roll': r, 'ids_only': True, 'height_pass': False}
        job = blender.run({'model': model_path(unit, hero=True), 'mode': 'passes', 'size': size, 'samples': 1, 'shots': shots,
                           'studs': 'full', 'params': params})
        legend = job['legend']
        for (i, h), sh in zip(hs, shots):
            idim = np.asarray(Image.open(sh['path'] + '.id.png').convert('RGBA'))
            codes = np.full(idim.shape[:2], '', dtype=object)
            for key, v in legend.items():
                rgb = tuple(int(x) for x in key.split(','))
                codes[(idim[..., 0] == rgb[0]) & (idim[..., 1] == rgb[1]) & (idim[..., 2] == rgb[2]) & (idim[..., 3] > 0)] = v['code']
            res[i] = (codes, (idim[..., 3] > 0).astype(np.float32), {v['code']: v['rgb'] for v in legend.values()})
    return res


def fit(unit, rounds=2, wide=True):
    f = os.path.join(ROOT, 'config', 'hero', unit + '.json')
    old = json.load(open(f)) if os.path.exists(f) else {}
    if old.get('pinned'):
        print('%s: pinned, left' % unit)
        return old
    ref = Image.open(hero_ref(unit)).convert('RGBA')
    cam = hero_camera(unit)
    best = [float(cam['heading']), float(cam['elevation']), float(cam['lens']), float(cam.get('roll', 0.0))]
    cols = None

    def evaluate(cs):
        nonlocal cols
        rs = tries(unit, cs)
        if cols is None:
            cols = flat_colours(rs[0][2])
        return [score(c, a, lg, ref, cols) for c, a, lg in rs]
    e0 = evaluate([tuple(best)])[0]
    print('%s: from heading %.1f elevation %.1f lens %.0f roll %.1f: error %.2f (overlap %.3f)' % ((unit,) + tuple(best) + e0), flush=True)
    cur = e0[0]
    # (first a wide look: the outline's fit can sit in the wrong valley, the faces turned)
    if wide:
        cs = [((best[0] + dh) % 360, el, ln, 0.0) for dh in range(-40, 41, 10) for el in (12, 22, 32, 42, 52) for ln in (22, 40, 75)]
        sc = evaluate(cs)
        i = int(np.argmin([x[0] for x in sc]))
        print('  wide: heading %.1f elevation %.1f lens %.0f: error %.2f' % (cs[i][0], cs[i][1], cs[i][2], sc[i][0]), flush=True)
        if sc[i][0] < cur:
            cur, best = sc[i][0], list(cs[i])
    for rnd in range(rounds):
        k = 1.0 if rnd == 0 else 0.4
        # turn and elevation together
        cs = [(best[0] + dh * k, best[1] + de * k, best[2], best[3]) for dh in (-12, -8, -4, 0, 4, 8, 12) for de in (-10, -5, 0, 5, 10)]
        # roll
        cs += [(best[0], best[1], best[2], best[3] + dr * k) for dr in (-14, -10, -6, -3, 3, 6, 10, 14)]
        # lens (the perspective's strength)
        cs += [(best[0], best[1], best[2] * f_, best[3]) for f_ in ((0.55, 0.75, 1.35, 1.8) if rnd == 0 else (0.85, 1.15))]
        sc = evaluate(cs)
        # (each axis's best, then together)
        i = int(np.argmin([s[0] for s in sc]))
        if sc[i][0] < cur:
            cur = sc[i][0]
            best = list(cs[i])
        # and roll again at the new turn
        cs2 = [(best[0], best[1], best[2], best[3] + dr * k) for dr in (-8, -4, -2, 2, 4, 8)] + \
              [(best[0] + dh * k * 0.5, best[1] + de * k * 0.5, best[2], best[3]) for dh in (-3, 0, 3) for de in (-3, 0, 3) if dh or de]
        sc2 = evaluate(cs2)
        j = int(np.argmin([s[0] for s in sc2]))
        if sc2[j][0] < cur:
            cur = sc2[j][0]
            best = list(cs2[j])
        print('  round %d: heading %.1f elevation %.1f lens %.0f roll %.1f: error %.2f' % ((rnd + 1,) + tuple(best) + (cur,)), flush=True)
    out = dict(old, unit=unit, heading=round(best[0] % 360, 1), elevation=round(best[1], 1), lens=round(best[2], 1), roll=round(best[3], 1),
               inside_error=round(cur, 2), model=UNITS[unit].get('hero_model') or UNITS[unit]['model'])
    out.setdefault('score', cam.get('score'))
    json.dump(out, open(f, 'w'), indent=1)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('units', nargs='+')
    ap.add_argument('--rounds', type=int, default=2)
    a = ap.parse_args()
    for u in a.units:
        if hero_ref(u):
            fit(u, a.rounds)


if __name__ == '__main__':
    main()
