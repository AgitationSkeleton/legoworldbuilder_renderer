"""An LDraw model checked as real LEGO: each part on the grid (its place a multiple of half a stud
across, of a plate's height up), no two parts in one another, and none in the air (each standing
on another or on the ground's top).  For models made by hand here (extra/).

    python tools/ldraw_check.py extra/airport_all.ldr [--ldraw PATH] [--print]

Parts' sizes come from the LDraw library's geometry (their outlines: lines of types 2 to 5, through
their subparts).  Prints each part's box with --print."""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = {}


def find(name, ldraw, extra_dirs):
    name = name.replace('\\', '/').lower()
    for d in extra_dirs + [os.path.join(ldraw, 'parts'), os.path.join(ldraw, 'p'), os.path.join(ldraw, 'parts', 's'),
                           os.path.join(ldraw, 'unofficial', 'parts'), os.path.join(ldraw, 'unofficial', 'p')]:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def points(name, ldraw, extra_dirs, depth=0):
    """A part's points (N, 3), in its own frame."""
    key = name.lower()
    if key in CACHE:
        return CACHE[key]
    p = find(name, ldraw, extra_dirs)
    pts = []
    if p and depth < 12:
        for line in open(p, encoding='utf-8', errors='replace'):
            t = line.split()
            if not t:
                continue
            if t[0] in ('2', '3', '4', '5'):
                v = list(map(float, t[2:2 + 3 * (2 if t[0] in ('2', '5') else int(t[0]))]))
                pts += [v[i:i + 3] for i in range(0, len(v), 3)]
            elif t[0] == '1' and len(t) >= 15:
                x, y, z = map(float, t[2:5])
                M = np.array(list(map(float, t[5:14]))).reshape(3, 3)
                sub = points(' '.join(t[14:]), ldraw, extra_dirs, depth + 1)
                if len(sub):
                    pts += list(sub @ M.T + np.array([x, y, z]))
    arr = np.array(pts) if pts else np.zeros((0, 3))
    CACHE[key] = arr
    return arr


def boxes(path, ldraw):
    out = []
    extra = [os.path.dirname(os.path.abspath(path))]
    for n, line in enumerate(open(path, encoding='utf-8')):
        t = line.split()
        if len(t) >= 15 and t[0] == '1':
            x, y, z = map(float, t[2:5])
            M = np.array(list(map(float, t[5:14]))).reshape(3, 3)
            part = ' '.join(t[14:])
            pts = points(part, ldraw, extra)
            if not len(pts):
                out.append({'line': n + 1, 'part': part, 'missing': True})
                continue
            w = pts @ M.T + np.array([x, y, z])
            out.append({'line': n + 1, 'part': part, 'colour': t[1], 'at': (x, y, z), 'lo': w.min(0), 'hi': w.max(0)})
    return out


def check(path, ldraw, show=False):
    B = boxes(path, ldraw)
    problems = []
    for b in B:
        if b.get('missing'):
            problems.append('line %d: %s is not in the library' % (b['line'], b['part']))
            continue
        x, y, z = b['at']
        if abs(x / 10 - round(x / 10)) > 1e-3 or abs(z / 10 - round(z / 10)) > 1e-3 or abs(y / 4 - round(y / 4)) > 1e-3:
            problems.append('line %d: %s at %s is off the grid' % (b['line'], b['part'], b['at']))
        if show:
            print('line %3d %-10s colour %-3s x %6.1f..%6.1f  y %6.1f..%6.1f  z %6.1f..%6.1f' % (
                b['line'], b['part'], b['colour'], b['lo'][0], b['hi'][0], b['lo'][1], b['hi'][1], b['lo'][2], b['hi'][2]))
    B = [b for b in B if not b.get('missing')]
    ground = max(b['hi'][1] for b in B)          # (LDraw's y is down: the lowest point is the greatest)
    for i, a in enumerate(B):
        # (inside one another: their boxes overlapping by more than a stud's height, less the studs)
        for b in B[i + 1:]:
            lo = np.maximum(a['lo'], b['lo'])
            hi = np.minimum(a['hi'], b['hi'])
            d = hi - lo
            if (d > 0.5).all() and d[1] > 4.5 and d[0] > 0.5 and d[2] > 0.5:
                problems.append('lines %d and %d: %s and %s are in one another (%.0f x %.0f x %.0f)' % (a['line'], b['line'], a['part'], b['part'], d[0], d[1], d[2]))
        # (standing on something: its bottom on another's top, under it, or on the ground)
        bottom = a['hi'][1]
        if abs(bottom - ground) < 0.5:
            continue
        held = False
        for b in B:
            if b is a:
                continue
            top = b['lo'][1]
            # (its bottom at the other's body top -- the other's studs reach 4 higher)
            if (abs(bottom - top) < 0.6 or abs(bottom - (top + 4)) < 0.6) and \
                    a['lo'][0] < b['hi'][0] - 1 and b['lo'][0] < a['hi'][0] - 1 and a['lo'][2] < b['hi'][2] - 1 and b['lo'][2] < a['hi'][2] - 1:
                held = True
                break
        if not held:
            problems.append('line %d: %s stands on nothing (its bottom at y %.1f)' % (a['line'], a['part'], bottom))
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('model')
    ap.add_argument('--ldraw')
    ap.add_argument('--print', action='store_true')
    a = ap.parse_args()
    ldraw = a.ldraw or json.load(open(os.path.join(HERE, 'local.json')))['ldraw']
    probs = check(a.model, ldraw, a.print)
    print('\n'.join(probs) if probs else 'all on the grid, none in another, none in the air')
    sys.exit(1 if probs else 0)


if __name__ == '__main__':
    main()
