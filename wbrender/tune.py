"""The look tuned to the game's sprites: lights, plastic and the cut-out's edge, searched for the
values whose renders come nearest the game's own, over several units at once.

    python -m wbrender.tune [--units buggy,duck,...] [--rounds 3] [--per-round 20] [--write]

Each round tries looks about the best so far (fewer and nearer each round); each look is
rendered in all four directions for every unit (one Blender run per unit per round, the model
imported once), brought down to sprites with each fringe colour and threshold, and scored:
mean colour difference where render and game overlap, plus how far their outlines differ.
With --write the best goes into config/style.json."""
import argparse
import json
import os
import random

import numpy as np
from PIL import Image

from . import blender, post
from .fit import iou, DIRS, ortho_size
from .render import load_fit, colour_error
from .units import ROOT, model_path, ref_path

# name: (low, high, kind) -- each a part of the look (wbsprite's params, or the cut-out's)
SPACE = {
    'ambient': (0.1, 1.2, 'look'),
    'key.strength': (1.0, 7.0, 'look'),
    'key.elevation': (20.0, 85.0, 'look'),
    'key.azimuth': (-150.0, 90.0, 'look'),
    'fill.strength': (0.0, 2.5, 'look'),
    'fill.azimuth': (60.0, 240.0, 'look'),
    'saturation': (0.9, 1.7, 'look'),
    'roughness': (0.25, 1.0, 'look'),
    'specular': (0.0, 0.7, 'look'),
}
# the water: searched with the look held as it is (--water)
WATER_SPACE = {
    'waterline': (0.1, 0.7), 'water_mix': (0.2, 0.95), 'water_depth': (0.05, 0.8),
    'wr': (0.0, 0.4), 'wg': (0.5, 0.9), 'wb': (0.5, 0.95),
    'dr': (0.0, 0.3), 'dg': (0.2, 0.6), 'db': (0.4, 0.9),
}
WATER_FRINGES = [(24, 200, 240), (35, 178, 205), (30, 175, 210), (60, 190, 210)]
FRINGES = [(255, 0, 255), (0, 0, 0), (40, 40, 38), (255, 255, 255), (8, 184, 8), (128, 128, 128)]
THRESHOLDS = [0.35, 0.45, 0.55]
GAMMAS = [0.8, 0.9, 1.0, 1.1]


def to_params(v):
    look = {'key': {}, 'fill': {}}
    for k, x in v.items():
        if SPACE[k][2] != 'look':
            continue
        if '.' in k:
            a, b = k.split('.')
            look[a][b] = x
        else:
            look[k] = x
    return look


def from_style(S):
    L = S['look']
    v = {}
    for k in SPACE:
        if '.' in k:
            a, b = k.split('.')
            v[k] = L.get(a, {}).get(b, (SPACE[k][0] + SPACE[k][1]) / 2)
        else:
            v[k] = L.get(k, (SPACE[k][0] + SPACE[k][1]) / 2)
    return v


def near(v, spread):
    out = {}
    for k, (lo, hi, _) in SPACE.items():
        out[k] = min(hi, max(lo, v[k] + random.gauss(0, (hi - lo) * spread)))
    return out


def score_unit(unit, looks, size, samples, studs, work):
    """{look index: (score, fringe, threshold, gamma)} for one unit."""
    fit = load_fit(unit)
    shots = []
    for i, v in enumerate(looks):
        P = to_params(v)
        for d in DIRS:
            if ref_path(unit, d):
                shots.append(dict(P, path=os.path.join(work, '%s_%d_%s.png' % (unit, i, d)), heading=fit['headings'][d], look_id=i,
                                  elevation=fit['elevation'], skew=fit.get('skew', 0.0)))
    r = blender.run({'model': model_path(unit), 'mode': 'final', 'size': size, 'samples': samples, 'shots': shots, 'studs': studs,
                     'params': {'elevation': fit['elevation'], 'skew': fit.get('skew', 0.0)}})
    ppu = size / ortho_size(r['radius'], fit.get('skew', 0.0))
    refs = {d: Image.open(ref_path(unit, d)) for d in DIRS if ref_path(unit, d)}
    out = {}
    for i in range(len(looks)):
        best = None
        for fr in FRINGES:
            for th in THRESHOLDS:
                for g in GAMMAS:
                    tot = 0
                    for d, ref in refs.items():
                        spr, _ = post.to_sprite(Image.open(os.path.join(work, '%s_%d_%s.png' % (unit, i, d))), ppu / fit['scale'],
                                                tuple(c / 255 for c in fr), th, g)
                        ce = colour_error(spr, ref) or 200
                        sh = 1 - iou(np.asarray(spr)[..., 3] > 0, post.reference_mask(ref))
                        tot += ce + 100 * sh
                    tot /= len(refs)
                    if best is None or tot < best[0]:
                        best = (tot, fr, th, g)
        out[i] = best
    return out


def water_params(v):
    return {'waterline': v['waterline'], 'water_mix': v['water_mix'], 'water_depth': v['water_depth'],
            'water_color': [v['wr'], v['wg'], v['wb']], 'deep_color': [v['dr'], v['dg'], v['db']]}


def score_water(unit, looks, base, size, samples, studs, work):
    """As score_unit, for the unit's partly submerged sprites."""
    fit = load_fit(unit)
    shots = []
    for i, v in enumerate(looks):
        for d in DIRS:
            if ref_path(unit, d, water=True):
                shots.append(dict(water_params(v), path=os.path.join(work, 'w_%s_%d_%s.png' % (unit, i, d)), heading=fit['headings'][d],
                                  look_id=i, elevation=fit['elevation'], skew=fit.get('skew', 0.0)))
    if not shots:
        return {}
    r = blender.run({'model': model_path(unit), 'mode': 'final', 'size': size, 'samples': samples, 'shots': shots, 'studs': studs,
                     'params': dict(base, elevation=fit['elevation'], skew=fit.get('skew', 0.0), waterline=0.3)})
    ppu = size / ortho_size(r['radius'], fit.get('skew', 0.0))
    refs = {d: Image.open(ref_path(unit, d, water=True)) for d in DIRS if ref_path(unit, d, water=True)}
    out = {}
    for i in range(len(looks)):
        best = None
        for fr in WATER_FRINGES:
            tot = 0
            for d, ref in refs.items():
                spr, _ = post.to_sprite(Image.open(os.path.join(work, 'w_%s_%d_%s.png' % (unit, i, d))), ppu / fit['scale'], tuple(c / 255 for c in fr), 0.5)
                tot += (colour_error(spr, ref) or 200) + 100 * (1 - iou(np.asarray(spr)[..., 3] > 0, post.reference_mask(ref)))
            tot /= len(refs)
            if best is None or tot < best[0]:
                best = (tot, fr)
        out[i] = best
    return out


def tune_water(a, S, style_path):
    W = S['water']
    v0 = {'waterline': W['waterline'], 'water_mix': W['mix'], 'water_depth': W['depth'],
          'wr': W['color'][0], 'wg': W['color'][1], 'wb': W['color'][2], 'dr': W['deep'][0], 'dg': W['deep'][1], 'db': W['deep'][2]}
    best_v, best = v0, None
    units = [u for u in a.units.split(',')]
    work = os.path.join(ROOT, 'work', 'tune')
    os.makedirs(work, exist_ok=True)
    for rnd in range(a.rounds):
        spread = 0.3 / (rnd + 1)
        looks = [best_v] + [{k: min(hi, max(lo, best_v[k] + random.gauss(0, (hi - lo) * spread))) for k, (lo, hi) in WATER_SPACE.items()}
                            for _ in range(a.per_round - 1)]
        totals = [[0.0, []] for _ in looks]
        for u in units:
            res = score_water(u, looks, S['look'], a.size, a.samples, a.studs, work)
            for i, r in res.items():
                totals[i][0] += r[0] / len(units)
                totals[i][1].append(r[1])
        i = min(range(len(looks)), key=lambda j: totals[j][0])
        if best is None or totals[i][0] < best[0]:
            best = (totals[i][0], looks[i], totals[i][1])
            best_v = looks[i]
        print('water round %d: best %.1f  %s' % (rnd + 1, best[0], {k: round(x, 2) for k, x in best_v.items()}), flush=True)
    from collections import Counter
    fr = Counter(tuple(x) for x in best[2]).most_common(1)[0][0]
    if a.write:
        S['water'].update({'waterline': round(best_v['waterline'], 3), 'mix': round(best_v['water_mix'], 3), 'depth': round(best_v['water_depth'], 3),
                           'color': [round(best_v[k], 3) for k in ('wr', 'wg', 'wb')], 'deep': [round(best_v[k], 3) for k in ('dr', 'dg', 'db')],
                           'fringe': list(fr)})
        json.dump(S, open(style_path, 'w', encoding='utf-8'), indent=1)
        print('written to config/style.json')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--units', default='buggy,dirtbuggy,duck,dumptruck,crab,defender')
    ap.add_argument('--rounds', type=int, default=3)
    ap.add_argument('--per-round', type=int, default=20)
    ap.add_argument('--size', type=int, default=320)
    ap.add_argument('--samples', type=int, default=24)
    ap.add_argument('--studs', default='none', choices=['full', 'none'])
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--water', action='store_true', help='tune the water (on the duck, frog, fish and gator) instead')
    a = ap.parse_args()
    random.seed(a.seed)
    style_path = os.path.join(ROOT, 'config', 'style.json')
    S = json.load(open(style_path, encoding='utf-8'))
    if a.water:
        if a.units == ap.get_default('units'):
            a.units = 'duck,frog,fish,gator'
        return tune_water(a, S, style_path)
    units = a.units.split(',')
    best_v, best = from_style(S), None
    work = os.path.join(ROOT, 'work', 'tune')
    os.makedirs(work, exist_ok=True)
    for rnd in range(a.rounds):
        spread = 0.35 / (rnd + 1)
        looks = [best_v] + [near(best_v, spread) for _ in range(a.per_round - 1)]
        totals = [[0.0, []] for _ in looks]
        for u in units:
            res = score_unit(u, looks, a.size, a.samples, a.studs, work)
            for i, r in res.items():
                totals[i][0] += r[0] / len(units)
                totals[i][1].append((u, r[1], r[2], r[3]))
        i = min(range(len(looks)), key=lambda j: totals[j][0])
        if best is None or totals[i][0] < best[0]:
            best = (totals[i][0], looks[i], totals[i][1])
            best_v = looks[i]
        print('round %d: best %.1f  %s' % (rnd + 1, best[0], {k: round(x, 2) for k, x in best_v.items()}), flush=True)
    # (the fringe, threshold and gamma most of the units liked)
    from collections import Counter
    fr = Counter(tuple(x[1]) for x in best[2]).most_common(1)[0][0]
    th = Counter(x[2] for x in best[2]).most_common(1)[0][0]
    g = Counter(x[3] for x in best[2]).most_common(1)[0][0]
    print('fringe %s threshold %s gamma %s  (per unit: %s)' % (fr, th, g, best[2]))
    if a.write:
        L = to_params(best_v)
        for k in ('key', 'fill'):
            S['look'][k].update(L[k])
        for k, x in L.items():
            if k not in ('key', 'fill'):
                S['look'][k] = round(x, 3)
        S['fringe'], S['threshold'], S['gamma'], S['studs'] = list(fr), th, g, a.studs
        json.dump(S, open(style_path, 'w', encoding='utf-8'), indent=1)
        print('written to config/style.json')


if __name__ == '__main__':
    main()
