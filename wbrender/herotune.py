"""The info panel's look tuned to the game's portraits: their lights (a key, a fill, the white rim
from behind that edges them), the plastic's shine and the sky's light, searched for the values whose
portraits come nearest the game's, each unit from its fitted portrait camera, in the game's colours
(config/palette.json).

    python -m wbrender.herotune [--units duck,frog,...] [--rounds 3] [--per-round 16] [--write]

Writes config/style.json's "hero_look" with --write."""
import argparse
import json
import os
import random

import numpy as np
from PIL import Image

from . import blender
from .render import on_white, colour_error_white, style
from .herofit import hero_mask, fit_score
from .shade import palette
from .units import ROOT, UNITS, model_path, hero_ref

SPACE = {
    'ambient': (0.0, 1.5), 'key.strength': (0.5, 8.0), 'key.elevation': (10.0, 80.0), 'key.azimuth': (-150.0, 150.0),
    'fill.strength': (0.0, 4.0), 'fill.azimuth': (-180.0, 180.0),
    'rim.strength': (0.0, 12.0), 'rim.elevation': (0.0, 70.0), 'rim.azimuth': (120.0, 240.0),
    'roughness': (0.1, 0.9), 'specular': (0.0, 1.0), 'saturation': (0.8, 1.4),
}
START = {'ambient': 0.5, 'key.strength': 3.5, 'key.elevation': 45.0, 'key.azimuth': -40.0, 'fill.strength': 1.0, 'fill.azimuth': 60.0,
         'rim.strength': 5.0, 'rim.elevation': 30.0, 'rim.azimuth': 180.0, 'roughness': 0.35, 'specular': 0.5, 'saturation': 1.0}


def to_look(v):
    L = {'key': {}, 'fill': {'elevation': 20.0}, 'rim': {}}
    for k, x in v.items():
        if '.' in k:
            a, b = k.split('.')
            L[a][b] = x
        else:
            L[k] = x
    return L


def score(unit, looks, size, samples, work, pal):
    cam = json.load(open(os.path.join(ROOT, 'config', 'hero', unit + '.json')))
    ref = Image.open(hero_ref(unit))
    R = hero_mask(hero_ref(unit))
    shots = []
    for i, v in enumerate(looks):
        L = to_look(v)
        shots.append(dict(L, path=os.path.join(work, 'hero_%s_%d.png' % (unit, i)), heading=cam['heading'], look_id=i, hero=True,
                          hero_elevation=cam['elevation'], hero_lens=cam['lens']))
    blender.run({'model': model_path(unit, hero=True), 'mode': 'final', 'size': size, 'samples': samples, 'shots': shots, 'studs': 'full',
                 'params': {'palette': pal['colours'], 'hero': True}})
    out = []
    for i in range(len(looks)):
        im = on_white(Image.open(os.path.join(work, 'hero_%s_%d.png' % (unit, i))), ref.size)
        out.append(colour_error_white(im, ref) + 100 * (1 - fit_score(hero_mask_img(im), R)))
    return out


def hero_mask_img(im):
    a = np.asarray(im.convert('RGBA')).astype(int)
    return (a[..., 3] > 0) & ((a[..., :3] < 245).any(-1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--units', default='duck,frog,snail,dozer,dumptruck,speedboat,fish,tugboat')
    ap.add_argument('--rounds', type=int, default=3)
    ap.add_argument('--per-round', type=int, default=16)
    ap.add_argument('--size', type=int, default=256)
    ap.add_argument('--samples', type=int, default=32)
    ap.add_argument('--seed', type=int, default=2)
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()
    random.seed(a.seed)
    units = [u for u in a.units.split(',') if hero_ref(u) and os.path.exists(os.path.join(ROOT, 'config', 'hero', u + '.json'))]
    pal = palette()
    S = style()
    best_v = dict(START)
    if S.get('hero_look'):
        for k in START:
            if '.' in k:
                x, y = k.split('.')
                best_v[k] = S['hero_look'].get(x, {}).get(y, best_v[k])
            else:
                best_v[k] = S['hero_look'].get(k, best_v[k])
    best = None
    work = os.path.join(ROOT, 'work', 'herotune')
    os.makedirs(work, exist_ok=True)
    for rnd in range(a.rounds):
        spread = 0.3 / (rnd + 1)
        looks = [best_v] + [{k: min(hi, max(lo, best_v[k] + random.gauss(0, (hi - lo) * spread))) for k, (lo, hi) in SPACE.items()}
                            for _ in range(a.per_round - 1)]
        tot = np.zeros(len(looks))
        for u in units:
            tot += np.array(score(u, looks, a.size, a.samples, work, pal)) / len(units)
        i = int(np.argmin(tot))
        if best is None or tot[i] < best:
            best, best_v = float(tot[i]), looks[i]
        print('round %d: %.1f  %s' % (rnd + 1, best, {k: round(x, 2) for k, x in best_v.items()}), flush=True)
    if a.write:
        S['hero_look'] = to_look(best_v)
        S['hero_look']['palette'] = True
        json.dump(S, open(os.path.join(ROOT, 'config', 'style.json'), 'w', encoding='utf-8'), indent=1)
        print('written to config/style.json')


if __name__ == '__main__':
    main()
