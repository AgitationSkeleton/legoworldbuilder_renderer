"""The info panel's portraits fitted to the game's: for a unit, its outline rendered in perspective
from many turns, heights and lenses, and compared with the game's portrait (whatever their sizes:
the render brought to the portrait's box, its proportions counted too).

    python -m wbrender.herofit UNIT [UNIT ...] | all

Writes config/hero/<unit>.json: {heading, elevation, lens, score}, and config/hero/_shared.json,
the camera the fitted portraits share (their median elevation and lens, and their turn as against
each unit's map turn 'right'), for a unit the game has no portrait of.

The game's portraits are not all of the unit's own model (config/units.json: hero_model, hero_as);
a unit whose portrait is of another unit's model is not fitted (hero_as)."""
import argparse
import glob
import json
import os
import shutil

import numpy as np
from PIL import Image

from . import blender, post
from .fit import crop
from .units import UNITS, ROOT, model_path, hero_ref

HEADINGS = list(range(0, 360, 10))
ELEVATIONS = [15, 25, 35, 45, 55, 65]
LENSES = [30, 50, 85, 150, 300]


def hero_mask(path):
    """A portrait's drawn pixels: anything but its white."""
    a = np.asarray(Image.open(path).convert('RGBA')).astype(int)
    return (a[..., 3] > 0) & ((a[..., :3] < 245).any(-1))


def fit_score(render_mask, ref_mask):
    """The render's outline brought to the portrait's box: their overlap, times how alike their proportions are."""
    a, b = crop(render_mask), crop(ref_mask)
    if a.size < 4 or b.size < 4:
        return 0.0
    ra, rb = a.shape[1] / a.shape[0], b.shape[1] / b.shape[0]
    im = Image.fromarray(np.uint8(a) * 255).resize((b.shape[1], b.shape[0]), Image.BILINEAR)
    A = np.asarray(im) >= 128
    u = (A | b).sum()
    return float((A & b).sum() / u) * min(ra / rb, rb / ra) if u else 0.0


def fit_hero(unit, size=160, keep=False, headings=None):
    ref = hero_ref(unit)
    if not ref or UNITS[unit].get('hero_as'):
        return None
    # (a camera set by eye -- 'pinned' -- is kept: a model whose outline is alike from the front and
    # the back, or posed unlike the game's, fits its outline best from the wrong side)
    f = os.path.join(ROOT, 'config', 'hero', unit + '.json')
    if os.path.exists(f) and json.load(open(f)).get('pinned'):
        return json.load(open(f))
    R = hero_mask(ref)
    work = os.path.join(ROOT, 'work', 'herofit', unit)
    os.makedirs(work, exist_ok=True)

    def sweep(hs, es, ls):
        shots = [{'path': os.path.join(work, 'h%g_e%g_l%g.png' % (h, e, l)), 'heading': h, 'hero': True, 'hero_elevation': e, 'hero_lens': l}
                 for h in hs for e in es for l in ls]
        blender.run({'model': model_path(unit, hero=True), 'mode': 'silhouette', 'size': size, 'shots': shots})
        out = {}
        for s in shots:
            out[(s['heading'], s['hero_elevation'], s['hero_lens'])] = fit_score(post.mask_of(Image.open(s['path'])), R)
        return out

    scores = sweep(headings or HEADINGS, ELEVATIONS, LENSES)
    (h, e, l), best = max(scores.items(), key=lambda kv: kv[1])
    # (a finer look round it)
    scores2 = sweep([(h + d) % 360 for d in (-6, -3, 0, 3, 6)], [e - 5, e, e + 5], sorted({max(18, l * 0.75), l, l * 1.3}))
    (h, e, l), best = max(scores2.items(), key=lambda kv: kv[1])
    result = {'unit': unit, 'heading': h, 'elevation': e, 'lens': round(l, 1), 'score': round(best, 4),
              'model': UNITS[unit].get('hero_model') or UNITS[unit]['model']}
    os.makedirs(os.path.join(ROOT, 'config', 'hero'), exist_ok=True)
    json.dump(result, open(os.path.join(ROOT, 'config', 'hero', unit + '.json'), 'w'), indent=1)
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    return result


def group(unit):
    """A unit's kind of portrait: 'building', or 'unit' (vehicles, robots, animals, monsters)."""
    return 'building' if UNITS[unit]['sprite'].startswith('building') else 'unit'


def circ_median(angles):
    a = np.radians(angles)
    mean = np.degrees(np.arctan2(np.sin(a).mean(), np.cos(a).mean())) % 360
    return float((mean + np.median([((x - mean + 180) % 360) - 180 for x in angles])) % 360)


def shared():
    """The camera the fitted portraits share, each kind its own (units, buildings): their median elevation
    and lens, and their median turn -- the turn itself, not as against the map's: the recreations are all
    built facing one way, and the game's portraits all look at them from one side (the units from about
    325 degrees, the front to the left).  The well-fitted ones (score 0.8 and up) only."""
    by = {}
    for f in glob.glob(os.path.join(ROOT, 'config', 'hero', '*.json')):
        if os.path.basename(f).startswith('_'):
            continue
        h = json.load(open(f))
        u = h['unit']
        if u not in UNITS or h['score'] < 0.8:
            continue
        by.setdefault(group(u), []).append(h)
    out = {}
    for g, hs in by.items():
        out[g] = {'heading': round(circ_median([h['heading'] for h in hs]), 1), 'elevation': float(np.median([h['elevation'] for h in hs])),
                  'lens': float(np.median([h['lens'] for h in hs])), 'from': len(hs)}
    if out:
        json.dump(out, open(os.path.join(ROOT, 'config', 'hero', '_shared.json'), 'w'), indent=1)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('units', nargs='+')
    ap.add_argument('--keep', action='store_true')
    a = ap.parse_args()
    # (not the pickups: they have no portraits; the buildings, single on the map, do)
    units = [u for u in (list(UNITS) if a.units == ['all'] else a.units)
             if not (UNITS[u].get('unused') or UNITS[u].get('colours') or UNITS[u]['sprite'].startswith('resource'))]
    for u in units:
        r = fit_hero(u, keep=a.keep)
        if r:
            print('%-12s heading %5.1f  elevation %4.1f  lens %5.1f  score %.3f' % (u, r['heading'], r['elevation'], r['lens'], r['score']), flush=True)
    sh = shared()
    print('shared:', sh)
    # A portrait's outline is alike turned either way (a car from the front left, from the front right):
    # one turned far from the turn its kind's portraits share is fitted again near it, and kept if it
    # is nearly as good (the mirror image is the likelier mistake than the game's turning one portrait).
    if sh:
        for u in units:
            f = os.path.join(ROOT, 'config', 'hero', u + '.json')
            if not os.path.exists(f) or group(u) not in sh:
                continue
            old = json.load(open(f))
            want = sh[group(u)]['heading']
            if abs(((old['heading'] - want + 180) % 360) - 180) > 45:
                r = fit_hero(u, keep=a.keep, headings=[(want + d) % 360 for d in range(-40, 41, 10)])
                if r['score'] < old['score'] - 0.05:
                    json.dump(old, open(f, 'w'), indent=1)
                    print('%-12s turned %5.1f, far from the shared %5.1f; near it only %.3f against %.3f: kept as it was' % (u, old['heading'], want, r['score'], old['score']), flush=True)
                else:
                    print('%-12s turned %5.1f, far from the shared %5.1f: fitted again near it: %5.1f, score %.3f (was %.3f)' % (u, old['heading'], want, r['heading'], r['score'], old['score']), flush=True)
        print('shared:', shared())


if __name__ == '__main__':
    main()
