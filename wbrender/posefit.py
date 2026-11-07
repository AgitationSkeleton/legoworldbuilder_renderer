"""A joint posed as the game's: one of a recreation's joints (a submodel or part of its main file,
turned about an axis through a pivot) tried at each angle, each pose's map sprites fitted to the
game's (the turns square, the camera as the unit's fit has it), and the angle whose outlines match
best kept in config/units.json 'pose'.

    python -m wbrender.posefit freezebot freezebot_gun y [--step 15] [--pivot X,Y,Z]

The game's renders posed some models otherwise than the sets' instructions (and the recreations)
have them: the freezebot holds its gun level and forward, the recreation out to the side."""
import argparse
import json
import os
import shutil

import numpy as np

from .units import UNITS, ROOT
from . import fit as F


def score(unit, pose, work):
    UNITS[unit]['pose'] = pose
    cam = json.load(open(os.path.join(ROOT, 'config', 'fit', unit + '.json')))
    r = F.fit_unit(unit, [cam['elevation']], size=160, skews=[cam['skew']], fixed=True, out=work, axes=True)
    return float(np.mean(list(r['iou'].values()))), r


def hero_score(unit, pose):
    """The pose scored on the portrait: the flat render from the portrait's camera against the game's
    (wbrender/herocam.py), as a match (higher better: 1 - error/255)."""
    from .herocam import tries, score as inside, flat_colours
    from .render import hero_camera
    from .units import hero_ref
    from PIL import Image
    UNITS[unit]['pose'] = pose
    cam = hero_camera(unit)
    (codes, al, lg), = tries(unit, [(cam['heading'], cam['elevation'], cam['lens'], cam.get('roll', 0.0))])
    e, ov = inside(codes, al, lg, Image.open(hero_ref(unit)).convert('RGBA'), flat_colours(lg))
    return 1 - e / 255.0, {'inside_error': round(e, 2), 'overlap': round(ov, 3)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('unit')
    ap.add_argument('match', help='part or submodel name (several: comma-separated, turned together)')
    ap.add_argument('axis', choices=['x', 'y', 'z'])
    ap.add_argument('--step', type=float, default=15)
    ap.add_argument('--range', type=float, default=180)
    ap.add_argument('--pivot')
    ap.add_argument('--hero', action='store_true', help='score on the portrait (the inside), not the map sprites')
    a = ap.parse_args()
    u = a.unit
    if ',' in a.match:
        a.match = a.match.split(',')
    base = [p for p in UNITS[u].get('pose', []) if not (p['match'] == a.match and p['axis'] == a.axis)]
    pivot = [float(x) for x in a.pivot.split(',')] if a.pivot else None
    work = os.path.join(ROOT, 'work', 'posefit', u)
    os.makedirs(work, exist_ok=True)
    rows = []
    for ang in np.arange(-a.range, a.range + 1e-6, a.step):
        if a.range >= 180 and ang >= 180:
            continue
        j = {'match': a.match, 'axis': a.axis, 'angle': float(ang)}
        if pivot:
            j['pivot'] = pivot
        s, r = hero_score(u, base + [j]) if a.hero else score(u, base + [j], work)
        rows.append((s, float(ang), r))
        print('  %s %s %+6.1f: match %.4f  %s' % (a.match, a.axis, ang, s, r if a.hero else r['iou']), flush=True)
    s, ang, r = max(rows, key=lambda x: x[0])
    s0 = next(x[0] for x in rows if abs(x[1]) < 1e-6)
    print('best: %+.1f degrees, %.3f (unposed %.3f)' % (ang, s, s0))
    if s > s0 + 0.005:
        cfg = os.path.join(ROOT, 'config', 'units.json')
        U = json.load(open(cfg, encoding='utf-8'))
        j = {'match': a.match, 'axis': a.axis, 'angle': ang}
        if pivot:
            j['pivot'] = pivot
        U[u]['pose'] = base + [j]
        json.dump(U, open(cfg, 'w', encoding='utf-8'), indent=1)
        print('written to config/units.json')
    shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
