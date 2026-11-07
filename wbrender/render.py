"""A unit's sprites, rendered as the game's were: its four standing directions, and, for a unit
that goes on water, its four partly submerged ones too; written to out/<unit>/ under the
game's own names (vehicle.duck.right.png, vehicle.duck.water.right.png ...), with a sheet
setting them beside the game's own (out/<unit>/compare.png) and how near they come.

    python -m wbrender.render UNIT [UNIT ...] [--size 768] [--samples 64] [--style config/style.json]
    python -m wbrender.render all

The camera is the unit's fitted one (config/fit/<unit>.json, python -m wbrender.fit), or, for a
unit the game has no sprites of (the cut Bluebird and Cargo Copter), the fitted ones' average.
The look is config/style.json's."""
import argparse
import glob
import json
import os

import numpy as np
from PIL import Image

from . import blender, post
from .fit import iou, DIRS, ortho_size
from .units import UNITS, ROOT, model_path, ref_path, hero_ref
from .sheet import sheet


def load_fit(unit):
    p = os.path.join(ROOT, 'config', 'fit', unit + '.json')
    if os.path.exists(p):
        f = json.load(open(p))
        # (a direction the game has no sprite of, fitted none: turned from 'right' as the four always are)
        for d, off in (('left', 180), ('up', 90), ('down', 270)):
            if d not in f['headings'] and 'right' in f['headings']:
                f['headings'][d] = (f['headings']['right'] + off) % 360
        return f
    # (no sprites to fit to: the camera all the fitted units share, their turns their median)
    fits = [json.load(open(f)) for f in glob.glob(os.path.join(ROOT, 'config', 'fit', '*.json'))]
    # (a building's: the fitted buildings' alone; another's: the units')
    kind = UNITS[unit]['sprite'].split('.')[0]
    alike = [f for f in fits if f.get('unit') in UNITS and UNITS[f['unit']]['sprite'].split('.')[0] == kind]
    fits = alike or fits
    if not fits:
        raise SystemExit('no fitted units yet: run python -m wbrender.fit first')
    el = float(np.median([f['elevation'] for f in fits]))
    ppl = float(np.median([f['scale'] for f in fits]))
    rel = {d: float(np.median([((f['headings'][d] - f['headings']['right']) % 360) for f in fits if d in f['headings']])) for d in DIRS}
    sk = float(np.median([f.get('skew', 0.0) for f in fits]))
    # (their 'right' turned as theirs are: a vehicle's about 90, a building's about 0)
    a = np.radians([f['headings']['right'] for f in fits if 'right' in f['headings']])
    right = float(np.degrees(np.arctan2(np.sin(a).mean(), np.cos(a).mean())) % 360)
    rel = {d: (rel[d] if not np.isnan(rel[d]) else {'right': 0, 'left': 180, 'up': 90, 'down': 270}[d]) for d in DIRS}
    return {'elevation': el, 'skew': sk, 'scale': ppl, 'headings': {d: (right + rel[d]) % 360 for d in DIRS}, 'guessed': True}


def style():
    return json.load(open(os.path.join(ROOT, 'config', 'style.json'), encoding='utf-8'))


def colour_error_white(a, b):
    """Mean colour difference between two pictures on white (a portrait, an icon), brought to one size."""
    A = np.asarray(a.convert('RGB').resize(b.size, Image.BOX), dtype=np.float32)
    B = np.asarray(b.convert('RGB'), dtype=np.float32)
    m = (A < 245).any(-1) | (B < 245).any(-1)
    return float(np.sqrt(((A - B) ** 2).sum(-1))[m].mean()) if m.any() else 0.0


def colour_error(a, b, slack=2):
    """Mean colour difference (0..441) where the two sprites overlap best."""
    A = np.asarray(a.convert('RGBA'), dtype=np.float32)
    B = np.asarray(b.convert('RGBA'), dtype=np.float32)
    ma, mb = A[..., 3] > 0, post.reference_mask(b)
    best = None
    for dy in range(-slack, slack + 1):
        for dx in range(-slack, slack + 1):
            ya, xa = (A.shape[0] - B.shape[0]) // 2 + dy, (A.shape[1] - B.shape[1]) // 2 + dx
            ys = slice(max(0, ya), min(A.shape[0], ya + B.shape[0]))
            xs = slice(max(0, xa), min(A.shape[1], xa + B.shape[1]))
            yb = slice(ys.start - ya, ys.stop - ya)
            xb = slice(xs.start - xa, xs.stop - xa)
            both = ma[ys, xs] & mb[yb, xb]
            if both.sum() < 10:
                continue
            e = np.sqrt(((A[ys, xs][..., :3] - B[yb, xb][..., :3]) ** 2).sum(-1))[both].mean()
            best = e if best is None else min(best, e)
    return best


def render_unit(unit, size=768, samples=64, out_root=None, compare=True, water_only=False, hero=True, consistent=False):
    u = UNITS[unit]
    if u.get('hero_only'):
        # (a building: its portrait only, beside the game's)
        out = os.path.join(out_root or os.path.join(ROOT, 'out'), unit)
        os.makedirs(out, exist_ok=True)
        mine = render_hero(unit, out, consistent=consistent)
        report = {}
        ref = hero_ref(unit)
        row = ([('game hero', ref)] if ref else []) + [('render hero', mine)]
        if ref:
            from .herofit import hero_mask, fit_score
            report[u['sprite'] + '.hero'] = {'shape': round(fit_score(hero_mask(mine), hero_mask(ref)), 3),
                                             'colour': round(float(colour_error_white(Image.open(mine), Image.open(ref))), 1)}
        sheet([row], scale=3, label=True).save(os.path.join(out, 'compare.png'))
        json.dump(report, open(os.path.join(out, 'report.json'), 'w'), indent=1)
        return {}, report
    fit = load_fit(unit)
    S = style()
    out = os.path.join(out_root or os.path.join(ROOT, 'out'), unit)
    raw = os.path.join(ROOT, 'work', 'raw', unit)
    os.makedirs(out, exist_ok=True)
    os.makedirs(raw, exist_ok=True)
    looks = []
    if u['on'] in ('land', 'both') and not water_only:
        looks.append(('', None))
    if u['on'] in ('water', 'both'):
        looks.append(('water.' if u['on'] == 'both' else '', S['water']))
    written = {}
    # (a pickup in colours: the model's yellow made each colour in turn; others once, as they are)
    colours = list(u['colours'].items()) if u.get('colours') else [(None, None)]
    cache_passes = {}
    regs = {}      # (sprites whose registration point is not their middle: flyers)
    dirs = ('right',) if u.get('single') else DIRS
    from . import shade
    pal = shade.palette()
    for prefix, water in looks:
        for colour, code in colours:
            # (the passes once per colour: land and water are both composited from them)
            key = (colour, code)
            if key not in cache_passes:
                cache_passes[key] = shade.render_passes(unit, list(dirs), size, samples,
                                                        recolour={'14': code} if code is not None else None,
                                                        work=os.path.join(raw, 'passes', colour or 'own'))
            P = cache_passes[key]
            factor = P['_ppu'] / P['_scale']
            fringe = (water or S)['fringe']
            wl = None
            if water:
                wl = {'waterline': water['waterline'], 'mix': water['mix'], 'depth': water['depth'], 'color': water['color'], 'deep': water['deep']}
            for d in dirs:
                sm = shade.small(P[d], factor)
                spr, _ = shade.to_sprite(sm, pal, fringe, S['threshold'], water=wl)
                if u.get('single'):
                    name = u['sprite'].format(colour=colour or '')
                else:
                    name = '%s.%s%s%s' % (u['sprite'], prefix, d, '' if prefix else u.get('still', ''))
                if u.get('flies'):
                    spr, reg = hover(spr, u['flies'])
                    regs[name] = reg
                p = os.path.join(out, name + '.png')
                spr.save(p)
                written[(prefix, colour, d)] = (p, name)
                if not prefix and colour is None:
                    # (the plan icon's view: this direction composited large, on nothing)
                    big = shade.small(P[d], 1.0 * factor / 6)
                    bimg, _ = shade.to_sprite(big, pal, (255, 255, 255), 0.5)
                    bimg.save(os.path.join(raw, '%s.png' % d))
    if regs:
        json.dump(regs, open(os.path.join(out, 'sprites.json'), 'w'), indent=1)
    extras = []
    if hero and not u.get('colours') and not u['sprite'].startswith('resource'):
        # (the portrait and the plan icon, from the land renders)
        raws = {d: os.path.join(raw, '%s.png' % d) for d in DIRS if os.path.exists(os.path.join(raw, '%s.png' % d))}
        if raws:
            pp, pdir = render_plan(unit, out, raws)
            extras.append(('plan', pp))
        try:
            extras.append(('hero', render_hero(unit, out, consistent=consistent)))
        except FileNotFoundError:
            pass
    report = {}
    if compare:
        rows = []
        if extras:
            from .herofit import hero_mask, fit_score
            row = []
            for kind, mine in extras:
                ref = os.path.join(ROOT, 'reference', '%s.%s.png' % (u['sprite'], kind))
                if os.path.exists(ref):
                    row.append(('game ' + kind, ref))
                    report[u['sprite'] + '.' + kind] = {'shape': round(fit_score(hero_mask(mine), hero_mask(ref)), 3),
                                                        'colour': round(float(colour_error_white(Image.open(mine), Image.open(ref))), 1)}
                row.append(('render ' + kind, mine))
            rows.append(row)
        for prefix, _ in looks:
            for colour, _ in colours:
                row = []
                for d in dirs:
                    mine = written.get((prefix, colour, d))
                    if not mine:
                        continue
                    mine, name = mine
                    ref = os.path.join(ROOT, 'reference', name + '.png')
                    ref = ref if os.path.exists(ref) else None
                    if ref:
                        row.append(('game ' + name.split('.', 1)[1], ref))
                    row.append(('render ' + name.split('.', 1)[1], mine))
                    if ref:
                        a, b = Image.open(mine), Image.open(ref)
                        report[name] = {'iou': round(float(iou(np.asarray(a)[..., 3] > 0, post.reference_mask(b))), 3),
                                        'colour': round(float(colour_error(a, b) or -1), 1)}
                rows.append(row)
        sheet(rows, scale=4, label=True).save(os.path.join(out, 'compare.png'))
        json.dump(report, open(os.path.join(out, 'report.json'), 'w'), indent=1)
    return written, report



# ---------- the info panel's portrait, and the plans bar's icon ----------

HERO_SIZE = (107, 100)     # a portrait's box when the game has none to go by (its portraits' usual size)
PLAN_SIZE = (29, 22)       # and a plan icon's


def on_white(im, box, margin=1):
    """A render's drawn part (alpha) brought into box (w, h), proportions kept, smoothed onto white."""
    a = np.asarray(im.convert('RGBA'), dtype=np.float32) / 255.0
    ys, xs = np.nonzero(a[..., 3] > 0.02)
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = a.shape[:2]
    k = min((box[0] - 2 * margin) / w, (box[1] - 2 * margin) / h)
    nw, nh = max(1, round(w * k)), max(1, round(h * k))
    pre = np.concatenate([a[..., :3] * a[..., 3:4], a[..., 3:4]], -1)
    small = np.asarray(Image.fromarray(np.uint8(np.clip(pre * 255 + 0.5, 0, 255)), 'RGBA').resize((nw, nh), Image.BOX), dtype=np.float32) / 255.0
    rgb = small[..., :3] + (1 - small[..., 3:4])      # over white
    out = np.ones((nh + 2 * margin, nw + 2 * margin, 3), dtype=np.float32)
    out[margin:margin + nh, margin:margin + nw] = rgb
    return Image.fromarray(np.uint8(np.clip(out * 255 + 0.5, 0, 255)), 'RGB').convert('RGBA')


def consistent_like(unit):
    """The game's portrait a consistent portrait of the unit stands for."""
    u = UNITS[unit]
    return u.get('consistent_like') or u.get('hero_as') or unit


def hero_camera(unit, consistent=False):
    """The portrait's camera: the unit's fitted one, or the shared one turned as against its map turn."""
    if consistent:
        # (a consistent portrait: the camera of the game's portrait it stands for -- config/units.json
        # 'consistent_like' (the dirtbuggy's map model is the buggy's portrait build in yellow), the
        # portrait it shows in the game (the freighter's: the tugboat's), or its own; the recreations
        # all face one way, so a camera carries over)
        like = consistent_like(unit)
        p = os.path.join(ROOT, 'config', 'hero', like + '.json')
        if os.path.exists(p):
            cam = json.load(open(p))
            if like != unit:
                # (its turn and height, not its lens: a lens fitted to a short model -- the tugboat's,
                # 10 mm -- stretches a long one, the freighter, out of all shape)
                cam = dict(cam, lens=max(cam['lens'], 30.0))
            return cam
    p = os.path.join(ROOT, 'config', 'hero', unit + '.json')
    if os.path.exists(p) and not (consistent and UNITS[unit].get('hero_model')):
        return json.load(open(p))
    sh = json.load(open(os.path.join(ROOT, 'config', 'hero', '_shared.json')))
    from .herofit import group
    g = sh.get(group(unit)) or next(iter(sh.values()))
    return {'heading': g['heading'], 'elevation': g['elevation'], 'lens': g['lens'], 'shared': True}


def render_hero(unit, out, size=640, samples=96, consistent=False):
    """<sprite>.hero.png: the info panel's portrait.  The game's portraits are not all of the unit's
    map model (the buggy and dirtbuggy are other builds; the freighter shows the tugboat): as the
    game has it, or, consistent, every one from the map's model with the shared camera."""
    u = UNITS[unit]
    S = style()
    source = unit
    if u.get('hero_as') and not consistent:
        source = u['hero_as']
    # (the period's light -- a scanline renderer's: local light from each surface's direction, no
    # shadows, overexposed, kept as JPEG -- fitted to the game's portraits: wbrender/heronormal.py)
    if os.path.exists(os.path.join(ROOT, 'config', 'hero_light.json')):
        from . import heronormal
        p = os.path.join(out, u['sprite'] + '.hero.png')
        ref = hero_ref(unit)
        box = Image.open(ref).size if ref and not consistent else HERO_SIZE
        heronormal.portrait(unit, consistent, box, source=source).save(p)
        return p
    # (the earlier composite of light passes: wbrender/heroshade.py)
    if os.path.exists(os.path.join(ROOT, 'config', 'hero_palette.json')):
        from . import heroshade
        p = os.path.join(out, u['sprite'] + '.hero.png')
        ref = hero_ref(unit)
        box = Image.open(ref).size if ref and not consistent else HERO_SIZE
        s = heroshade.boxed(heroshade.render(source, consistent=consistent), box)
        heroshade.picture(s, heroshade.palette(), box).save(p)
        return p
    cam = hero_camera(source, consistent)
    look = dict(S['look'], **S.get('hero_look', {}))
    look.update({'hero': True, 'hero_elevation': cam['elevation'], 'hero_lens': cam['lens']})
    # (a 1999 ray tracer's lights: points, the shadows hard)
    look.setdefault('softness', 0.5)
    if look.get('palette') is True:
        from .shade import palette
        look['palette'] = palette()['colours']
    raw = os.path.join(ROOT, 'work', 'raw', unit, 'hero.png')
    os.makedirs(os.path.dirname(raw), exist_ok=True)
    hero_model = source if not consistent else unit
    from .units import model_path as mp
    model = mp(hero_model, hero=not consistent)
    blender.run({'model': model, 'mode': 'final', 'size': size, 'samples': samples, 'params': look, 'studs': S.get('hero_studs', 'full'),
                 'shots': [{'path': raw, 'heading': cam['heading']}]})
    ref = hero_ref(unit)
    box = Image.open(ref).size if ref and not consistent else HERO_SIZE
    im = on_white(Image.open(raw), box)
    p = os.path.join(out, u['sprite'] + '.hero.png')
    im.save(p)
    return p


def render_plan(unit, out, raws):
    """<sprite>.plan.png: the plans bar's icon, the map view (of raws: {direction: large render})
    most like the game's icon, small on white."""
    u = UNITS[unit]
    ref = os.path.join(ROOT, 'reference', u['sprite'] + '.plan.png')
    box = Image.open(ref).size if os.path.exists(ref) else PLAN_SIZE
    best = ('right' if 'right' in raws else next(iter(raws)), -1)
    if os.path.exists(ref):
        from .herofit import hero_mask, fit_score
        R = hero_mask(ref)
        for d, raw in raws.items():
            sc = fit_score(np.asarray(Image.open(raw))[..., 3] > 128, R)
            if sc > best[1]:
                best = (d, sc)
    im = on_white(Image.open(raws[best[0]]), box, margin=0)
    p = os.path.join(out, u['sprite'] + '.plan.png')
    im.save(p)
    return p, best[0]



def hover(spr, lift):
    """A flyer's sprite: the unit lifted by lift pixels over a dithered shadow (a checkerboard of
    black, the period's way of half a shade), the registration point where the ground is."""
    a = np.asarray(spr.convert('RGBA'))
    h, w = a.shape[:2]
    sh_h = max(3, round(w * 0.22))
    out = np.zeros((h + lift + sh_h // 2, w, 4), np.uint8)
    # (the shadow: an ellipse as wide as the unit's footprint, under where it was standing)
    cy, cx = h + lift - 1, (w - 1) / 2
    yy, xx = np.mgrid[0:out.shape[0], 0:w]
    ell = ((xx - cx) / (w * 0.42)) ** 2 + ((yy - cy) / (sh_h / 2)) ** 2 <= 1
    out[ell & ((xx + yy) % 2 == 0)] = (0, 0, 0, 255)
    keep = a[..., 3] > 0
    out[:h][keep] = a[keep]
    # (the ground under the unit, as its own sprite's middle was: the unit stands lift higher)
    return Image.fromarray(out, 'RGBA'), {'regX': w // 2, 'regY': h // 2 + lift}

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('units', nargs='+')
    ap.add_argument('--size', type=int, default=384)
    ap.add_argument('--samples', type=int, default=24)
    ap.add_argument('--out')
    ap.add_argument('--no-hero', action='store_true', help='not the portrait and plan icon')
    ap.add_argument('--consistent-heroes', action='store_true',
                    help="portraits from the map's model, even where the game's are of another build (buggy, dirtbuggy, freighter)")
    a = ap.parse_args()
    for un in (list(UNITS) if a.units == ['all'] else a.units):
        _, rep = render_unit(un, a.size, a.samples, a.out, hero=not a.no_hero, consistent=a.consistent_heroes)
        if rep:
            sc = lambda v: v.get('iou', v.get('shape', 0))
            print('%-12s match %.3f  colour %.1f   %s' % (un, np.mean([sc(v) for v in rep.values()]), np.mean([v['colour'] for v in rep.values()]),
                                                     ' '.join('%s:%.2f/%.0f' % (k.split('.', 2)[-1], sc(v), v['colour']) for k, v in rep.items())), flush=True)
        else:
            print('%-12s rendered (no game sprites to compare)' % un, flush=True)


if __name__ == '__main__':
    main()