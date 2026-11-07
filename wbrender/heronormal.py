"""The info panel's portraits lit as a period scanline renderer lit them: local light only, from each
surface's direction -- no cast shadows, no light bounced -- and overexposed, each channel clipped
on its own.

Read off the game's portraits (wbrender/lightprobe.py; AUDIT.md): their flat faces are flat, not
graded, so the lights are far (directional); the duck's upward slopes are darker than its sides, so
the lights stand low, about the horizon, the key from the right; nothing casts a shadow; and a
yellow's red is 255 on every face, lit or shaded, only its green telling the light -- the renders
were overexposed, which turns a shaded yellow orange and keeps a lit one lemon, the game's
vibrancy.

So each portrait is rendered as the colours' ids, each pixel's surface direction in the camera's
frame, and the sky's light (for the corners the sky does not reach), and lit here:

    v   = (ambient * A**occlusion + sum_i  w_i * max(0, n . l_i)) ** gamma
    rgb = clip(palette[colour] * v  +  shine * sum_i w_i * max(0, n . h_i) ** power)
    glass: rgb = behind * (1 - opacity) + rgb * opacity

with the lights' directions free (any elevation and azimuth, in the camera's frame) and fitted to
the game's portraits of the units built and posed as the game's (heroshade.references(): the duck,
the buggy, the dirtbuggy ...), registered onto them to the pixel.

    python -m wbrender.heronormal fit [UNIT ...]
    python -m wbrender.heronormal show UNIT [UNIT ...]       # beside the game's: out/heronormal.png
"""
import argparse
import json
import os

import numpy as np
from PIL import Image

from . import blender
from .units import UNITS, ROOT, model_path, hero_ref
from .heroshade import camera, boxed, registered, fill_codes, references

PAL = os.path.join(ROOT, 'config', 'hero_light.json')
V = np.array([0.0, 0.0, 1.0], np.float32)          # towards the viewer
NEUTRAL = ('0', '256', '15', '7', '8', '71', '72', '503', '151')     # black, rubber, white, the greys: grey
LIGHT0 = {'ambient': 0.4, 'occlusion': 0.5, 'gamma': 0.8, 'shine': 0.3, 'power': 20.0, 'opacity': 0.45,
          'lights': [{'w': 1.0, 'elevation': 0.0, 'azimuth': 90.0}, {'w': 0.6, 'elevation': -10.0, 'azimuth': -60.0},
                     {'w': 0.3, 'elevation': 40.0, 'azimuth': 180.0}]}


def light_dir(e, a):
    """A light's direction in the camera's frame (x right, y up, z towards the viewer): azimuth 0 from the
    camera, 90 from the right."""
    e, a = np.radians(e), np.radians(a)
    return np.array([np.cos(e) * np.sin(a), np.sin(e), np.cos(e) * np.cos(a)], np.float32)


# The game's portraits were not all lit alike: the duck's tops are darker than its sides, the buggy's
# brighter. They were lit in batches -- the animals, the vehicles, the buildings -- each its own rig,
# fitted on its own references; a new unit takes its kind's.
GROUPS = {'animal': ['duck', 'frog', 'snail', 'fish'], 'vehicle': ['buggy', 'dirtbuggy', 'dozer', 'dumptruck'],
          'building': ['house', 'nursery', 'garage']}
ANIMALS = ('duck', 'frog', 'snail', 'fish', 'bluebird', 'gator', 'crab', 'watercrab', 'scorpion', 'trex', 'shark', 'lion')
FITTED = ('ambient', 'occlusion', 'gamma', 'lights', 'slope')


def group_of(unit):
    if UNITS.get(unit, {}).get('sprite', '').startswith('building'):
        return 'building'
    return 'animal' if unit in ANIMALS else 'vehicle'


def settings(unit=None, rig_from=None):
    """The light and palette, for a unit: its kind's rig over the shared settings. rig_from: lit with that
    unit's portrait's rig (and exposure), the colours as for a portrait of no game's."""
    P = json.load(open(PAL, encoding='utf-8')) if os.path.exists(PAL) else {'colours': {}, 'light': LIGHT0}
    G = None
    own = False
    lender = None
    if rig_from and rig_from != unit and (P.get('units') or {}).get(rig_from):
        G = P['units'][rig_from]
        lender = G
        ex = G.get('exposures', {}).get(rig_from, 1.0)
        G = dict(G, exposures={unit: ex})
    elif unit:
        # (a portrait of the game's own: the rig fitted on it alone; any other: its kind's)
        G = (P.get('units') or {}).get(unit)
        own = G is not None
        # (a new unit: the rig of the game's portrait most like it -- config/units.json 'hero_rig_from' --
        # the lights stand as against the camera, and so carry over; else its kind's)
        like = UNITS.get(unit, {}).get('hero_rig_from')
        if G is None and like:
            G = (P.get('units') or {}).get(like)
            if G is not None:
                lender = G
                G = dict(G, exposures={})
        G = G or (P.get('groups') or {}).get(group_of(unit))
    if G:
        P = dict(P)
        P['light'] = dict(P['light'], **{k: v for k, v in G['light'].items() if k in FITTED})
        for k in ('colours', 'world_scale', 'reflect'):
            if k in G:
                P[k] = G[k]
        P['exposures'] = dict(P.get('exposures', {}), **G.get('exposures', {}))
        if own:
            # (every colour fitted on the portrait itself: its own)
            P['trusted'] = list(P['colours'])
        else:
            # (a portrait of no game's: each colour as the game's own portraits agree it -- the median over
            # the rigs fitted on them -- but black and dark grey, which the recreations build where the game
            # has grey; the rest the world palette's)
            # (each portrait's colours are as against its own rig's light: brought to the world palette's
            # terms -- over that rig's scale to it -- for the median, then to this rig's)
            cons = {}
            for u_, R in (json.load(open(PAL, encoding='utf-8')).get('units') or {}).items():
                k_ = R.get('world_scale') or world_scale(R) or 1.0
                for c, v in R.get('colours', {}).items():
                    cons.setdefault(c, []).append(np.array(v, np.float32) / k_)
            here = P.get('world_scale') or 1.0
            P['colours'] = dict(P['colours'])
            for c, vs in cons.items():
                if c not in DISTRUST:
                    P['colours'][c] = [int(x) for x in np.median(np.array(vs), 0) * here]
            P['trusted'] = [c for c in P['colours'] if c not in DISTRUST]
            if lender is not None:
                # (a borrowed rig: the lender's own colours, fitted under the very rig lent, and every other
                # the world palette's at the lender's scale -- not the portraits' consensus, whose rigs'
                # scales, fitted each with its own reflections, do not agree)
                P['world_scale'] = lender.get('world_scale') or world_scale(lender)
                # (but not one far from the world palette's at that scale: fitted on a few pixels -- the
                # buggy's yellow is its headlights)
                from .shade import palette as world
                Wp = world()['colours']
                P['colours'] = {}
                for c, v in lender.get('colours', {}).items():
                    w_ = Wp.get(c)
                    if w_ is not None and c not in DISTRUST:
                        ratio = (sum(v) + 1) / (sum(w_) * (P['world_scale'] or 1.0) + 1)
                        if not 0.5 <= ratio <= 2.0:
                            continue
                    P['colours'][c] = v
                P['trusted'] = list(P['colours'])
    return P


DISTRUST = ('0', '8', '72', '71', '15')     # black, the greys and white: the recreations' are the game's grey in places, and the references' whites mostly shaded


# ---------- the passes ----------

def render(unit, size=384, samples=64, consistent=False, work=None, shadows=None):
    cam = camera(unit, consistent)
    work = work or os.path.join(ROOT, 'work', 'heronormal', unit + ('_c' if consistent else ''))
    os.makedirs(work, exist_ok=True)
    params = {'hero': True, 'hero_elevation': cam['elevation'], 'hero_lens': cam['lens'], 'hero_roll': cam.get('roll', 0.0), 'passes': [('ambient', None)],
              'softness': 0.3, 'height_pass': False, 'normal_pass': True, 'seam_pass': True, 'reflect_pass': True}
    model = model_path(unit, hero=not consistent)
    stamp = json.dumps({'cam': cam, 'model': model, 'size': size, 'samples': samples, 'v': 3}, sort_keys=True)
    done = os.path.join(work, 'made.json')
    if os.path.exists(done) and json.load(open(done)).get('stamp') == stamp:
        legend = json.load(open(done))['legend']
    else:
        shots = [{'path': os.path.join(work, 'full'), 'heading': cam['heading']}]
        r = blender.run({'model': model, 'mode': 'passes', 'size': size, 'samples': samples, 'shots': shots, 'studs': 'full', 'params': params})
        legend = r['legend']
        glass = [v['code'] for v in legend.values() if (v.get('alpha') or 1) < 0.99]
        if glass:
            shots = [{'path': os.path.join(work, 'behind'), 'heading': cam['heading'], 'hide_codes': glass}]
            blender.run({'model': model, 'mode': 'passes', 'size': size, 'samples': samples, 'shots': shots, 'studs': 'full', 'params': params})
        json.dump({'stamp': stamp, 'legend': legend}, open(done, 'w'))
    glass = [v['code'] for v in legend.values() if (v.get('alpha') or 1) < 0.99]
    out = read(os.path.join(work, 'full'), legend)
    if glass:
        out['behind'] = read(os.path.join(work, 'behind'), legend)
    out['glass'] = glass
    if shadows:
        shadow_passes(unit, out, shadows, size, consistent, work, stamp)
    return out


# The game's vehicles cast hard shadows: faces turned to the low key light but behind something are
# half as bright and less (the buggy's, the dirtbuggy's: wbrender/heronormal.py shadow test, AUDIT.md).
# A light's shadow, any light's: a hard sun's pass on white plastic over its light without shadows.
SHADOW_GRID = [(e, a) for e in (0, 10, 20, 35, 50, 70) for a in range(-175, 180, 25)]


def shadow_passes(unit, out, dirs, size, consistent, work, stamp):
    """out['shadow']: {(elevation, azimuth): mask, 1 lit .. 0 in shadow}, each direction's pass rendered once."""
    cam = camera(unit, consistent)
    made = os.path.join(work, 'shadows.json')
    have = json.load(open(made)) if os.path.exists(made) else {}
    if have.get('stamp') != stamp or (out.get('glass') and have.get('v') != 2):
        have = {'stamp': stamp, 'dirs': [], 'v': 2}
    need = [d for d in dirs if [float(d[0]), float(d[1])] not in have['dirs']]
    if need:
        passes = [('sh_%g_%g' % (e, a), {'elevation': e, 'azimuth': a, 'strength': 1}) for e, a in need]
        params = {'hero': True, 'hero_elevation': cam['elevation'], 'hero_lens': cam['lens'], 'hero_roll': cam.get('roll', 0.0),
                  'passes': passes, 'softness': 0.02, 'height_pass': False}
        shots = [{'path': os.path.join(work, 'shadow'), 'heading': cam['heading']}]
        if out.get('glass'):
            # (and behind the glass: the shadows inside, the glass itself left out)
            shots.append({'path': os.path.join(work, 'behind_shadow'), 'heading': cam['heading'], 'hide_codes': out['glass']})
        blender.run({'model': model_path(unit, hero=not consistent), 'mode': 'passes', 'size': size, 'samples': 16,
                     'shots': shots, 'studs': 'full', 'params': params})
        have['dirs'] += [[float(e), float(a)] for e, a in need]
        json.dump(have, open(made, 'w'))
    for target, name in ((out, 'shadow'), (out.get('behind'), 'behind_shadow')):
        if target is None:
            continue
        target['shadow'] = {}
        for e, a in dirs:
            f = os.path.join(work, '%s.sh_%g_%g.png' % (name, e, a))
            if not os.path.exists(f):
                continue
            im = np.asarray(Image.open(f))
            K = im[..., 0].astype(np.float32) / (65535.0 if im.dtype == np.uint16 else 255.0) * np.pi / 0.8
            lam = np.maximum(0, target['N'] @ light_dir(e, a))
            target['shadow'][(float(e), float(a))] = np.where(lam > 0.08, np.clip(K / np.maximum(lam, 1e-3), 0, 1), 1.0).astype(np.float32)


def read(base, legend):
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
    n[..., 2] *= -1          # (Cycles' camera looks down +z: turned so +z is towards the viewer)
    out = {'codes': codes, 'legend': {v['code']: v['rgb'] for v in legend.values()}, 'alpha': A[..., 3], 'A': A[..., 0] / 0.8,
           'N': n, 'K': [], 'S': [], 'R': []}
    if os.path.exists(base + '.seams.png'):
        # (1 where a seam runs, 0 on a face)
        out['K'] = [1.0 - img('seams')[..., :3].mean(-1)]
    if os.path.exists(base + '.reflect.png'):
        # what each pixel reflects: a part (the nearest colour id; robj how much of the pixel) or the world
        # (rdir: the direction the reflected ray leaves in, the world's axes, z up)
        r = img('reflect')[..., :3] * 255.0
        keys = [(k_, np.array([int(x) for x in k_.split(',')], np.float32)) for k_ in legend]
        d = np.stack([np.abs(r - c).sum(-1) for _, c in keys], -1)
        near = d.argmin(-1)
        hit = r.max(-1) > 12
        rc = np.full(r.shape[:2], '', dtype=object)
        for i, (k_, _) in enumerate(keys):
            rc[hit & (near == i)] = legend[k_]['code']
        out['rcodes'] = rc
        out['robj'] = np.clip(r.max(-1) / 60.0, 0, 1).astype(np.float32)
        out['rdir'] = img('reflectdir')[..., :3] * 2 - 1
    return out


# ---------- the light ----------

RUBBER = ('256',)          # the tyres' rubber: the only surface the game's portraits show shining


def up_of(unit, consistent=False):
    """The world's up in the portrait camera's frame."""
    e = np.radians(camera(unit, consistent)['elevation'])
    return np.array([0.0, np.cos(e), np.sin(e)], np.float32)


def slopes(s):
    """Where a slope's top shows: a surface between level and upright (facing up 0.3 to 0.93), of a
    plastic -- not the rubber, not the greys, whose rounded parts would count. LEGO's slopes are grained
    on top, matte, and the game's render them darker than the bricks' smooth faces: the duck's beak."""
    wu = s['N'] @ s.get('up', up_of_default())
    return (wu > 0.3) & (wu < 0.93) & ~np.isin(s['codes'], NEUTRAL)


def up_of_default():
    e = np.radians(25.0)
    return np.array([0.0, np.cos(e), np.sin(e)], np.float32)


def lit(s, L):
    """(v, white): the light on white plastic, and the white added (highlights, rims)."""
    n = s['N']
    v = L['ambient'] * np.power(np.clip(s['A'], 1e-3, 1), L['occlusion'])
    spec = np.zeros_like(v)
    for li in L['lights']:
        l = light_dir(li['elevation'], li['azimuth'])
        lam = np.maximum(0, n @ l)
        if li.get('shadow') and s.get('shadow'):
            sh = s['shadow'].get((float(li['elevation']), float(li['azimuth'])))
            if sh is not None:
                lam = lam * sh
        v = v + li['w'] * lam
        h = (l + V) / np.linalg.norm(l + V)
        spec = spec + li['w'] * np.power(np.maximum(0, n @ h), L['power'])
    if L.get('slope'):
        v = v * (1 - L['slope'] * slopes(s))
    if L.get('seams') and s.get('K'):
        v = v * (1 - L['seams'] * np.clip(s['K'][0], 0, 1))
    # (the white added: the highlights -- on the rubber its own -- and the white the edges turning away
    # catch, the tyres' rims)
    rub = np.isin(s['codes'], RUBBER)
    white = L['shine'] * spec
    if L.get('rubber_shine'):
        # (the rubber's highlights: tight, bright, from a light of their own -- the tread blocks' edges)
        rl = L.get('rubber_light') or {'elevation': 40.0, 'azimuth': -60.0}
        l = light_dir(rl['elevation'], rl['azimuth'])
        h = (l + V) / np.linalg.norm(l + V)
        white = white + L['rubber_shine'] * rub * np.power(np.maximum(0, n @ h), L.get('rubber_power', 30.0))
    white = white + L.get('rim', 0.0) * np.power(1 - np.clip(n @ V, 0, 1), L.get('rim_power', 4.0)) * (rub if L.get('rim_rubber', True) else 1)
    return np.power(np.maximum(v, 0), L['gamma']), white


TRUSTED = ('14', '4', '256')     # colours whose parts in the reference portraits are the recreations' (yellow, red, rubber)


def base_of(code, legend, pal):
    """A colour's plastic under the portraits' light: fitted on the reference portraits where they and the
    recreations agree on it (TRUSTED); any other, the world palette's -- learned from hundreds of the
    game's sprites -- brought to the portraits' exposure. (The references are no guide to the rest:
    where JappaWakka built in black, the game's buggy and dirtbuggy are grey.)"""
    if code in pal.get('trusted', TRUSTED) and code in pal['colours']:
        return np.array(pal['colours'][code], np.float32) / 255.0
    k = pal.get('world_scale')
    if k:
        from .shade import base_colour, palette as world
        return base_colour(code, legend, world()) * k
    c = pal['colours'].get(code) or legend.get(code) or [128, 128, 128]
    return np.array(c, np.float32) / 255.0


def world_scale(pal):
    """The portraits' plastic against the world sprites' palette: the median of their brightness's ratio
    over the trusted colours, or, a rig with none of them (the frog's), over every colour the two share
    but black, the greys and white."""
    from .shade import palette as world
    W = world()['colours']
    r = [sum(pal['colours'][c]) / max(1, sum(W[c])) for c in TRUSTED if c in pal['colours'] and c in W]
    if not r:
        r = [sum(v) / max(1, sum(W[c])) for c, v in pal['colours'].items() if c in W and c not in DISTRUST]
    return float(np.median(r)) if r else None


def reflected(s, pal, L, R):
    """(rgb, r): what each pixel reflects, and how much: the part it sees (its own colour, as lit on
    average) or the world (a sky above, a ground below, blended about the horizon); the plastic's
    reflectivity rising toward the edges (Fresnel)."""
    rgb = np.zeros(s['N'].shape, np.float32)
    rc = s.get('rcodes')
    if rc is not None:
        from .shade import palette as world
        Wp = world()['colours']
        k0 = pal.get('world_scale') or 1.0
        for code in np.unique(rc):
            if code:
                m = rc == code
                v = Wp.get(code) or s['legend'].get(code) or [128, 128, 128]
                rgb[m] = np.array(v, np.float32)[None, :] / 255.0 * k0 * R['part']
    z = s['rdir'][..., 2] if s.get('rdir') is not None else np.zeros(s['N'].shape[:2], np.float32)
    t = np.clip(0.5 + z / max(R['horizon'], 1e-3), 0, 1)
    env = np.array(R['ground'], np.float32) + (np.array(R['sky'], np.float32) - np.array(R['ground'], np.float32)) * t[..., None]
    w = s.get('robj', np.zeros(z.shape, np.float32))[..., None] if rc is not None else 0
    out = rgb * w + env * (1 - w)
    r = R['r0'] + R['fresnel'] * np.power(1 - np.clip(s['N'] @ V, 0, 1), 5)
    return out, np.clip(r, 0, 1)


def light_rgb(s, pal, L):
    v, spec = lit(s, L)
    # (each of the game's portraits was rendered with its own exposure -- the dirtbuggy's yellow a
    # fifth darker than the duck's -- fitted per portrait; a new one takes the references' middle, 1)
    v = v * s.get('exposure', 1.0)
    rgb = np.zeros(v.shape + (3,), np.float32)
    for code in np.unique(s['codes']):
        if code:
            m = s['codes'] == code
            rgb[m] = base_of(code, s['legend'], pal)[None, :] * v[m][:, None]
    R = pal.get('reflect')
    if R and s.get('rdir') is not None:
        refl, r = reflected(s, pal, L, R)
        rgb = rgb * (1 - r[..., None]) + refl * r[..., None]
    return rgb + spec[..., None]


def composite(s, pal, L=None):
    L = L or pal['light']
    rgb = light_rgb(s, pal, L)
    if s.get('behind') is not None and s['glass']:
        s['behind']['exposure'] = s.get('exposure', 1.0)
        back = light_rgb(s['behind'], pal, L)
        g = np.isin(s['codes'], s['glass'])
        G = pal.get('glass')
        if G:
            rgb[g] = glass_rgb(s, back, g, L, G)
        else:
            _, spec = lit(s, L)
            rgb[g] = back[g] * (1 - L['opacity']) + rgb[g] * L['opacity'] + spec[g][:, None]
    rgb = np.clip(rgb, 0, 1)
    cov = s['cov'][..., None]
    return rgb * cov + (1 - cov)


def glass_rgb(s, back, g, L, G):
    """The game's glass: what is behind it greyed and dimmed (the buggy's red seat is near grey through
    it), the glass's own grey over it, and its reflections -- the lights' highlights on the glass's own
    surface, sharp, and the white it catches turned away (the streaks across the windscreens)."""
    lum = np.array([0.299, 0.587, 0.114], np.float32)
    b = back[g]
    lb = (b @ lum)[:, None]
    through = lb + (b - lb) * (1 - G['desaturate'])
    n = s['N'][g]
    spec = np.zeros(len(n), np.float32)
    for li in L['lights']:
        l = light_dir(li['elevation'], li['azimuth'])
        h = (l + V) / np.linalg.norm(l + V)
        spec = spec + li['w'] * np.power(np.maximum(0, n @ h), G['power'])
    fres = np.power(1 - np.clip(n @ V, 0, 1), 3)
    return G['transmit'] * through + (1 - G['transmit']) * G['grey'] + (G['shine'] * spec + G['fresnel'] * fres)[:, None]


def glass_fit(units=('buggy', 'dirtbuggy'), tries=3000, seed=5):
    """The glass, fitted on the game's windscreens: each part of the glass by what is behind it (the
    median colour over each), and the spread of the glass's brightness (its streaks)."""
    data = []
    Q = (0.1, 0.3, 0.5, 0.7, 0.9, 0.97)
    lumw = np.array([0.299, 0.587, 0.114], np.float32)
    for u in units:
        im = Image.open(hero_ref(u))
        P = settings(u)
        shadows = [(float(l['elevation']), float(l['azimuth'])) for l in P['light']['lights'] if l.get('shadow')]
        p = render(u, shadows=shadows or None)
        reg = registered(p, im)
        s = boxed(p, im.size, k=reg[1], at=reg[2])
        s['up'] = up_of(u)
        s['exposure'] = P.get('exposures', {}).get(u, 1.0)
        s['behind']['up'] = s['up']
        s['behind']['exposure'] = s['exposure']
        back = light_rgb(s['behind'], P, P['light'])
        R = np.asarray(im.convert('RGB'), np.float32) / 255.0
        h, w = s['cov'].shape
        y, x = s['at']
        Rc = R[y:y + h, x:x + w]
        g = np.isin(s['codes'], s['glass']) & (s['cov'] > 0.98)
        data.append((s, back, g, Rc[g], s['behind']['codes'][g], P['light']))
    rng = np.random.default_rng(seed)

    def err(G):
        e = 0.0
        for s, back, g, game, bc, L in data:
            mine = np.clip(glass_rgb(s, back, g, L, G), 0, 1)
            for c in np.unique(bc):
                m = bc == c
                if m.sum() >= 15:
                    e += np.sqrt(m.sum()) * np.abs(np.median(mine[m], 0) - np.median(game[m], 0)).mean()
            e += 8 * np.abs(np.quantile(mine @ lumw, Q) - np.quantile(game @ lumw, Q)).mean() * np.sqrt(len(game))
        return e
    best = None
    for t in range(tries):
        G = {'transmit': rng.uniform(0.1, 0.9), 'desaturate': rng.uniform(0, 1), 'grey': rng.uniform(0.1, 0.9),
             'shine': rng.uniform(0, 2), 'power': float(rng.choice([10, 30, 80, 200])), 'fresnel': rng.uniform(0, 1)}
        e = err(G)
        if best is None or e < best[0]:
            best = (e, G)
    e, G = best
    for it in range(1500):
        H = {k: (float(np.clip(v + rng.normal(0, 0.04), 0, 2)) if k != 'power' else v) for k, v in G.items()}
        H['transmit'] = min(H['transmit'], 1.0)
        H['desaturate'] = min(H['desaturate'], 1.0)
        eh = err(H)
        if eh < e:
            e, G = eh, H
    print('glass: %s' % {k: round(v, 3) for k, v in G.items()})
    for s, back, g, game, bc, L in data:
        mine = np.clip(glass_rgb(s, back, g, L, G), 0, 1)
        print('  brightness quantiles %s: game %s, ours %s' % (Q, np.round(np.quantile(game @ lumw, Q) * 255), np.round(np.quantile(mine @ lumw, Q) * 255)))
    P = json.load(open(PAL, encoding='utf-8'))
    P['glass'] = G
    json.dump(P, open(PAL, 'w', encoding='utf-8'), indent=1)
    print('written to config/hero_light.json')
    return G


def soften(rgb, sigma):
    """A gaussian blur (sigma in pixels): the game's portraits are softer than a sharp render brought to
    their size -- rendered larger and scaled down smoothly."""
    if sigma <= 0.05:
        return rgb
    r = max(1, int(np.ceil(sigma * 3)))
    g = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    g /= g.sum()
    h, w = rgb.shape[:2]
    p = np.pad(rgb, ((r, r), (0, 0), (0, 0)), mode='edge')
    rgb = sum(g[i] * p[i:i + h] for i in range(2 * r + 1))
    p = np.pad(rgb, ((0, 0), (r, r), (0, 0)), mode='edge')
    return sum(g[i] * p[:, i:i + w] for i in range(2 * r + 1))


def picture(s, pal, box, L=None):
    L = L or pal['light']
    rgb = composite(s, pal, L)
    out = np.ones((box[1], box[0], 3), np.float32)
    h, w = rgb.shape[:2]
    y, x = s['at']
    hh, ww = min(h, box[1] - y), min(w, box[0] - x)
    out[y:y + hh, x:x + ww] = rgb[:hh, :ww]
    out = soften(out, L.get('blur', 0.0))
    im = Image.fromarray(np.uint8(np.clip(out * 255 + 0.5, 0, 255)), 'RGB')
    if L.get('jpeg'):
        im = jpeg(im, L['jpeg'])
    return im


def jpeg(im, quality):
    """Through JPEG and back: the game's portraits were kept JPEG-compressed (the white about them
    rings: 251,255,248 ...), which is half their crispness."""
    import io
    b = io.BytesIO()
    im.save(b, 'JPEG', quality=int(quality), subsampling=0)
    return Image.open(io.BytesIO(b.getvalue())).convert('RGB')


# ---------- fitting ----------

def samples(unit):
    im = Image.open(hero_ref(unit))
    ref = im.convert('RGB')
    p = render(unit)
    reg = registered(p, im)
    s = boxed(p, ref.size, k=reg[1], at=reg[2]) if reg and reg[0] > 0.8 else boxed(p, ref.size)
    s['up'] = up_of(unit)
    if s.get('behind') is not None:
        s['behind']['up'] = s['up']
    R = np.asarray(ref, np.float32) / 255.0
    h, w = s['cov'].shape
    y, x = s['at']
    Rc = R[y:y + h, x:x + w]
    c = s['codes']
    inner = s['cov'] > 0.98
    same = np.zeros_like(inner)
    same[1:-1, 1:-1] = (c[1:-1, 1:-1] == c[:-2, 1:-1]) & (c[1:-1, 1:-1] == c[2:, 1:-1]) & (c[1:-1, 1:-1] == c[1:-1, :-2]) & (c[1:-1, 1:-1] == c[1:-1, 2:])
    keep = inner & same & (Rc.min(-1) < 0.97) & (c != '') & ~np.isin(c, s['glass'])
    print('  %s: registered %.3f, %d samples' % (unit, reg[0] if reg else 0, keep.sum()), flush=True)
    return s, Rc, keep


def telling(data):
    """Each colour's telling channel per unit -- its brightest one not clipped -- as (s, pixels, log value)."""
    out = []
    for s, Rc, k in data:
        for c in np.unique(s['codes'][k]):
            m = k & (s['codes'] == c)
            if m.sum() < 20:
                continue
            g = Rc[m]
            best = None
            for ch in range(3):
                q, md = np.quantile(g[:, ch], 0.9), np.median(g[:, ch])
                if q < 0.97 and md > 0.12 and (best is None or md > best[1]):
                    best = (ch, md)
            if best is None:
                continue
            mm = m & (Rc[..., best[0]] < 0.97)
            out.append((s, mm, np.log(np.maximum(Rc[mm][:, best[0]], 0.02))))
    return out


def pack(L):
    x = [L['ambient'], L['occlusion'], L['gamma']]
    for li in L['lights']:
        x += [li['w'], li['elevation'], li['azimuth']]
    return np.array(x, np.float64)


def unpack(x, L):
    L = dict(L)
    L['ambient'], L['occlusion'], L['gamma'] = float(max(x[0], 0.01)), float(np.clip(x[1], 0, 2)), float(np.clip(x[2], 0.3, 3))
    L['lights'] = [{'w': float(max(x[3 + 3 * i], 0)), 'elevation': float(np.clip(x[4 + 3 * i], -60, 89)), 'azimuth': float(((x[5 + 3 * i] + 180) % 360) - 180)}
                   for i in range((len(x) - 3) // 3)]
    return L


def fit(units, tries=3000, steps=4000, seed=1, refine=1500):
    data = [samples(u) for u in units]
    for u, (s, _, _) in zip(units, data):
        s['unit'] = u
    T = telling(data)
    L = dict(LIGHT0)

    def shading_error(Lx):
        e, n = 0.0, 0
        for s, m, y in T:
            v, _ = lit(s, Lx)
            lv = np.log(np.maximum(v[m], 1e-3))
            d = y - lv
            d = np.abs(d - np.median(d))
            # (trimmed: the worst fifth -- edges a pixel off, parts built otherwise -- left out)
            d = np.sort(d)[: max(1, int(len(d) * 0.8))]
            e += d.sum()
            n += len(d)
        return e / n

    # 1. the lights: where they stand, how strong, against the sky (scale-free: each colour's own light
    #    and shade about its middle), by a wide random search, then a narrowing walk
    rng = np.random.default_rng(seed)
    best = None
    for t in range(tries):
        x = np.array([rng.uniform(0.05, 1.0), rng.uniform(0, 1.5), rng.uniform(0.5, 2.0)] +
                     sum([[rng.uniform(0, 1.5) if i else 1.0, rng.uniform(-45, 80), rng.uniform(-180, 180)] for i in range(3)], []))
        e = shading_error(unpack(x, L))
        if best is None or e < best[0]:
            best = (e, x)
    e, x = best
    print('lights, the search: %.4f' % e, flush=True)
    step = np.array([0.05, 0.1, 0.1] + [0.1, 6, 12] * 3)
    step[3] = 0          # (the key's strength fixed at 1: the palette carries the scale)
    for it in range(steps):
        y = x + rng.normal(0, 1, len(x)) * step * (0.5 ** (it / 1200))
        ey = shading_error(unpack(y, L))
        if ey < e:
            e, x = ey, y
    L = unpack(x, L)
    flat = shading_error(dict(L, lights=[], occlusion=0))
    print('lights: %.4f (no lights: %.4f)  ambient %.2f occlusion %.2f gamma %.2f' % (e, flat, L['ambient'], L['occlusion'], L['gamma']))
    for li in L['lights']:
        print('   w %.2f from elevation %.0f, azimuth %.0f' % (li['w'], li['elevation'], li['azimuth']))

    # 2. the palette under that light, clipping and all: each channel the median of the game's over the
    #    light where it is not clipped; one clipped nearly everywhere bright enough to clip in the shade
    def colours_for(Lx):
        acc = {}
        for s, Rc, k in data:
            v, spec = lit(s, Lx)
            v = v * s.get('exposure', 1.0)
            add = spec
            for c in np.unique(s['codes'][k]):
                m = k & (s['codes'] == c) & (v > 0.1) & (add < 0.08)
                if m.sum():
                    acc.setdefault(c, []).append(((Rc[m] - add[m][:, None]) / v[m][:, None], Rc[m] >= 0.94, v[m]))
        cols = {}
        for c, r in acc.items():
            q = np.concatenate([a[0] for a in r])
            if len(q) < 20:
                continue
            clipped = np.concatenate([a[1] for a in r])
            v = np.concatenate([a[2] for a in r])
            col = np.zeros(3, np.float32)
            for ch in range(3):
                ok = ~clipped[:, ch]
                # (clipped on nearly every face, the shaded too, as a yellow's red: strong enough to clip
                # under the dimmest light the colour has)
                # (unclipped in any portrait -- the dirtbuggy's yellow is, the duck's not -- that says it)
                col[ch] = np.median(q[ok, ch]) if ok.sum() >= 50 else 0.99 / max(np.quantile(v, 0.03), 0.2)
            cols[c] = np.clip(col, 0, 3)
        return cols

    def rgb_error(Lx, cols):
        P = {'colours': {c: list(v * 255) for c, v in cols.items()}}
        e = []
        for s, Rc, k in data:
            rgb = np.clip(light_rgb(s, P, Lx), 0, 1)
            e.append(np.abs(rgb[k] - Rc[k]).mean(1))
        e = np.sort(np.concatenate(e))
        return float(e[: int(len(e) * 0.9)].mean() * 255)

    def exposures(Lx, rounds=3):
        """Each portrait's exposure, against the palette the others agree on, in turn; their geometric
        mean kept 1."""
        for r in range(rounds):
            for s, Rc, k in data:
                best = None
                for f in np.exp(np.linspace(-0.45, 0.45, 19)):
                    s['exposure'] = f * 1.0
                    e = rgb_error(Lx, colours_for(Lx))
                    if best is None or e < best[0]:
                        best = (e, f)
                s['exposure'] = best[1]
            g = np.exp(np.mean([np.log(s['exposure']) for s, _, _ in data]))
            for s, _, _ in data:
                s['exposure'] /= g
        print('exposures: ' + ', '.join('%s %.2f' % (s['unit'], s['exposure']) for s, _, _ in data), flush=True)

    # 2b. the lights again, now against the picture itself -- each colour's palette solved anew under
    #     each light tried, clipping and all
    L['shine'], L['rim'] = 0.0, 0.0
    x = pack(L)
    e = rgb_error(L, colours_for(L))
    print('the picture under those lights: %.2f' % e, flush=True)
    for rnd in range(2):
        for it in range(refine):
            y = x + rng.normal(0, 1, len(x)) * step * 0.6 * (0.5 ** (it / 400))
            Ly = unpack(y, L)
            ey = rgb_error(Ly, colours_for(Ly))
            if ey < e:
                e, x = ey, y
        L = unpack(x, L)
        exposures(L)
        e = rgb_error(L, colours_for(L))
    print('refined on the picture: %.2f  ambient %.2f occlusion %.2f gamma %.2f' % (e, L['ambient'], L['occlusion'], L['gamma']))
    for li in L['lights']:
        print('   w %.2f from elevation %.0f, azimuth %.0f' % (li['w'], li['elevation'], li['azimuth']))

    # 3. the shine: how much, how tight
    cols = colours_for(L)
    best = None
    for sh in (0.0, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0):
        for pw in (5, 10, 20, 40, 80):
            Lx = dict(L, shine=sh, power=pw)
            e = rgb_error(Lx, colours_for(Lx))
            if best is None or e < best[0]:
                best = (e, sh, pw)
    L['shine'], L['power'] = best[1], best[2]
    best = None
    for rim in (0.0, 0.1, 0.2, 0.35, 0.5, 0.8):
        for rp in (2, 4, 8):
            Lx = dict(L, rim=rim, rim_power=rp)
            e = rgb_error(Lx, colours_for(Lx))
            if best is None or e < best[0]:
                best = (e, rim, rp)
    L['rim'], L['rim_power'] = best[1], best[2]
    cols = colours_for(L)
    print('shine %.2f, power %g, rim %.2f, rim power %g: colour error %.1f' % (L['shine'], L['power'], L['rim'], L['rim_power'], rgb_error(L, cols)))
    out = {'colours': {c: [int(round(x * 255)) for x in v] for c, v in sorted(cols.items())}, 'light': L, 'fitted_on': units,
           'exposures': {s['unit']: round(float(s['exposure']), 3) for s, _, _ in data}}
    out['world_scale'] = world_scale(out)
    print('the world palette brought to the portraits: x%.2f' % out['world_scale'])
    if group:
        P = json.load(open(PAL, encoding='utf-8')) if os.path.exists(PAL) else dict(out)
        P.setdefault('groups', {})[group] = out
        json.dump(P, open(PAL, 'w', encoding='utf-8'), indent=1)
        print('written to config/hero_light.json, group %s' % group)
    else:
        json.dump(out, open(PAL, 'w', encoding='utf-8'), indent=1)
        print('written to config/hero_light.json')
    return out


def portrait(unit, consistent=False, box=None, source=None):
    """The unit's portrait (PIL RGB): its kind's rig, the shadows its lights cast, at the exposure the game
    gave it if it is one the rig was fitted on. source: the model shown (the freighter shows the tugboat)."""
    from .render import HERO_SIZE
    source = source or unit
    ref = hero_ref(unit)
    box = box or (Image.open(ref).size if ref and not consistent else HERO_SIZE)
    if consistent:
        # (lit as the game's portrait it stands for: its rig, its exposure)
        from .render import consistent_like
        like = consistent_like(unit)
        P = settings(source, rig_from=like)
        if like == source:
            P = settings(source)
    else:
        P = settings(source)
    shadows = [(float(l['elevation']), float(l['azimuth'])) for l in P['light']['lights'] if l.get('shadow')]
    s = boxed(render(source, consistent=consistent, shadows=shadows or None), box)
    s['up'] = up_of(source, consistent)
    if s.get('behind') is not None:
        s['behind']['up'] = s['up']
    s['exposure'] = P.get('exposures', {}).get(source, 1.0)
    # (a borrowed rig: the exposure too, so the portrait is as bright as the one the rig was fitted on --
    # a model turned otherwise to the lights, the freighter's long hull, takes less of them)
    lender = (consistent and consistent_like_of(unit)) or UNITS.get(unit, {}).get('hero_rig_from')
    if lender and lender != source:
        s['exposure'] *= exposure_match(s, P, lender)
    return picture(s, P, box)


def consistent_like_of(unit):
    from .render import consistent_like
    return consistent_like(unit)


def exposure_match(s, P, lender):
    """How much brighter the lender's own portrait is lit than this one, by their median light."""
    try:
        Q = settings(lender)
        shadows = [(float(l['elevation']), float(l['azimuth'])) for l in Q['light']['lights'] if l.get('shadow')]
        ref = hero_ref(lender)
        box = Image.open(ref).size if ref else (107, 100)
        t = boxed(render(lender, shadows=shadows or None), box)
        t['up'] = up_of(lender)
        vt, _ = lit(t, Q['light'])
        vs, _ = lit(s, P['light'])
        a = np.median(vt[(t['cov'] > 0.98) & (t['codes'] != '')])
        b = np.median(vs[(s['cov'] > 0.98) & (s['codes'] != '')])
        return float(np.clip(a / max(b, 1e-3), 0.6, 1.8))
    except Exception:
        return 1.0


def render_portrait(unit, out_path, consistent=False, box=None):
    portrait(unit, consistent, box).save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('what', choices=['fit', 'faces', 'shadows', 'glass', 'reflect', 'reflect-rigs', 'finish', 'show'])
    ap.add_argument('units', nargs='*')
    ap.add_argument('--consistent', action='store_true')
    ap.add_argument('--front-key', action='store_true', help='shadows: the key light in front of the model (azimuth within 110)')
    ap.add_argument('--group', choices=sorted(GROUPS), help='faces: fit the rig of this kind of unit on its references')
    a = ap.parse_args()
    if a.what == 'fit':
        fit(a.units or references())
        return
    if a.what == 'faces':
        if a.group:
            face_fit(a.units or GROUPS[a.group], group=a.group)
        else:
            face_fit(a.units or references())
        return
    if a.what == 'shadows':
        kf = (lambda e, az: abs(az) <= 110) if a.front_key else None
        shadow_fit(a.units or GROUPS[a.group or 'vehicle'], group=a.group, key_from=kf)
        return
    if a.what == 'reflect-rigs':
        for u in (a.units or sorted(json.load(open(PAL, encoding='utf-8')).get('units', {}))):
            reflect_rig(u)
        return
    if a.what == 'reflect':
        reflect_fit(a.units or ['fish', 'duck', 'frog', 'snail', 'buggy', 'dirtbuggy', 'dozer', 'dumptruck'])
        return
    if a.what == 'glass':
        glass_fit(tuple(a.units) if a.units else ('buggy', 'dirtbuggy'))
        return
    if a.what == 'finish':
        finish(a.units or references())
        return
    from .sheet import sheet
    rows = []
    for u in a.units:
        os.makedirs(os.path.join(ROOT, 'out', u), exist_ok=True)
        p = render_portrait(u, os.path.join(ROOT, 'out', u, 'heronormal%s.png' % ('_c' if a.consistent else '')), a.consistent)
        rows.append(([('game', hero_ref(u))] if hero_ref(u) else []) + [('render', p)])
    sheet(rows, scale=3).save(os.path.join(ROOT, 'out', 'heronormal.png'))
    print(os.path.join(ROOT, 'out', 'heronormal.png'))



# ---------- fitting on faces ----------
# The pixel-by-pixel fit is at the mercy of the pixels a build or a registration puts a little off:
# its error trims the worst of them, and a face lit wholly wrong can hide among them. The game's faces
# are flat, so each face -- one colour, one surface direction, in one portrait -- is one sample: its
# median colour in the game's, its median direction and sky in the render; weighed by its size.

def faces_of(s, Rc, k, least=25):
    out = []
    q = np.round(s['N'] * 3) / 3
    for c in np.unique(s['codes'][k]):
        m0 = k & (s['codes'] == c)
        keys = q[m0]
        uniq, inv = np.unique(keys, axis=0, return_inverse=True)
        idx = np.nonzero(m0)
        for i in range(len(uniq)):
            sel = inv.ravel() == i
            if sel.sum() < least:
                continue
            ys, xs = idx[0][sel], idx[1][sel]
            n = np.median(s['N'][ys, xs], 0)
            n = n / np.linalg.norm(n)
            wu = float(n @ s.get('up', up_of_default()))
            out.append({'code': c, 'n': n, 'slope': bool(0.3 < wu < 0.93 and c not in NEUTRAL), 'A': float(np.median(s['A'][ys, xs])),
                        'game': np.median(Rc[ys, xs], 0), 'count': int(sel.sum())})
    return out


def face_fit(units, tries=4000, steps=12000, seed=2, group=None):
    data = [samples(u) for u in units]
    F = []
    for ui, (s, Rc, k) in enumerate(data):
        for f in faces_of(s, Rc, k):
            f['unit'] = ui
            F.append(f)
    codes = sorted({f['code'] for f in F})
    N = np.array([f['n'] for f in F], np.float32)
    A = np.array([f['A'] for f in F], np.float32)
    G = np.array([f['game'] for f in F], np.float32)
    W = np.sqrt(np.array([f['count'] for f in F], np.float32))
    U = np.array([f['unit'] for f in F])
    C = np.array([f['code'] for f in F])
    S = np.array([f['slope'] for f in F], np.float32)
    nU = len(units)
    print('%d faces of %d colours in %d portraits' % (len(F), len(codes), nU), flush=True)

    def shade(x):
        amb, occ, gam = max(x[0], 0.01), np.clip(x[1], 0, 2), np.clip(x[2], 0.3, 3)
        v = amb * np.power(np.clip(A, 1e-3, 1), occ)
        for i in range(3):
            w, e, a = max(x[3 + 3 * i], 0), np.clip(x[4 + 3 * i], -30, 89), x[5 + 3 * i]
            v = v + w * np.maximum(0, N @ light_dir(e, a))
        v = v * (1 - np.clip(x[12 + nU - 1], 0, 0.9) * S)
        v = np.power(np.maximum(v, 1e-4), gam)
        ex = np.exp(np.concatenate([[0.0], x[12:12 + nU - 1]]))
        return v * ex[U]

    def palette_for(v):
        pal = {}
        for c in codes:
            m = C == c
            q = G[m] / v[m][:, None]
            col = np.zeros(3, np.float32)
            for ch in range(3):
                ok = G[m][:, ch] < 0.94
                if ok.any():
                    ww = W[m][ok]
                    o = np.argsort(q[ok, ch])
                    cw = np.cumsum(ww[o])
                    col[ch] = q[ok, ch][o][np.searchsorted(cw, cw[-1] / 2)]
                else:
                    col[ch] = 0.99 / v[m].min()
            if c in NEUTRAL:
                col[:] = col.mean()
            pal[c] = np.clip(col, 0, 3)
        return pal

    def error(x, rim=0.0, rim_power=4.0):
        v = shade(x)
        pal = palette_for(v)
        P = np.stack([pal[c] for c in C])
        pred = np.clip(P * v[:, None] + rim * np.power(1 - np.clip(N @ V, 0, 1), rim_power)[:, None], 0, 1)
        return float((W * np.abs(pred - G).mean(1)).sum() / W.sum() * 255)

    rng = np.random.default_rng(seed)
    best = None
    for t in range(tries):
        x = np.array([rng.uniform(0.05, 1.0), rng.uniform(0, 1.5), rng.uniform(0.5, 2.0)] +
                     sum([[1.0 if i == 0 else rng.uniform(0, 1.5), rng.uniform(-30, 85), rng.uniform(-180, 180)] for i in range(3)], []) +
                     list(rng.uniform(-0.3, 0.3, nU - 1)) + [rng.uniform(0, 0.7)])
        e = error(x)
        if best is None or e < best[0]:
            best = (e, x)
    e, x = best
    print('faces, the search: %.2f' % e, flush=True)
    step = np.array([0.05, 0.1, 0.1] + [0, 6, 12] + [0.1, 6, 12] * 2 + [0.05] * (nU - 1) + [0.05])
    for it in range(steps):
        y = x + rng.normal(0, 1, len(x)) * step * (0.5 ** (it / 3000))
        ey = error(y)
        if ey < e:
            e, x = ey, y
    flat = error(np.array([1.0, 0, 1.0] + [0, 0, 0] * 3 + [0.0] * (nU - 1) + [0.0]))
    print('faces: %.2f (flat light: %.2f)' % (e, flat), flush=True)
    best = (e, 0.0, 4.0)
    for rim in (0.05, 0.1, 0.2, 0.35):
        for rp in (2, 4, 8):
            er = error(x, rim, rp)
            if er < best[0]:
                best = (er, rim, rp)
    L = dict(LIGHT0)
    L.update({'ambient': float(max(x[0], 0.01)), 'occlusion': float(np.clip(x[1], 0, 2)), 'gamma': float(np.clip(x[2], 0.3, 3)),
              'lights': [{'w': float(max(x[3 + 3 * i], 0)), 'elevation': float(np.clip(x[4 + 3 * i], -30, 89)),
                          'azimuth': float(((x[5 + 3 * i] + 180) % 360) - 180)} for i in range(3)],
              'shine': 0.0, 'power': 20.0, 'rim': best[1], 'rim_power': best[2], 'rim_rubber': False,
              'slope': float(np.clip(x[12 + nU - 1], 0, 0.9))})
    ex = np.exp(np.concatenate([[0.0], x[12:12 + nU - 1]]))
    ex = ex / np.exp(np.log(ex).mean())
    # (the palette at the middle exposure)
    x2 = x.copy()
    x2[12:12 + nU - 1] = np.log(ex[1:])
    v = shade(x2) / ex[U] * ex[U]
    pal = palette_for(v)
    print('faces with rim %.2f (power %g): %.2f' % (best[1], best[2], best[0]))
    print('ambient %.2f occlusion %.2f gamma %.2f' % (L['ambient'], L['occlusion'], L['gamma']))
    for li in L['lights']:
        print('   w %.2f from elevation %.0f, azimuth %.0f' % (li['w'], li['elevation'], li['azimuth']))
    print('exposures: ' + ', '.join('%s %.2f' % (u, f) for u, f in zip(units, ex)))
    out = {'colours': {c: [int(round(float(t) * 255)) for t in pal[c]] for c in codes}, 'light': L, 'fitted_on': units,
           'exposures': {u: round(float(f), 3) for u, f in zip(units, ex)}, 'face_error': round(best[0], 2)}
    out['world_scale'] = world_scale(out)
    print('the world palette brought to the portraits: x%.2f' % out['world_scale'])
    if group:
        P = json.load(open(PAL, encoding='utf-8')) if os.path.exists(PAL) else dict(out)
        P.setdefault('groups', {})[group] = out
        json.dump(P, open(PAL, 'w', encoding='utf-8'), indent=1)
        print('written to config/hero_light.json, group %s' % group)
    else:
        json.dump(out, open(PAL, 'w', encoding='utf-8'), indent=1)
        print('written to config/hero_light.json')
    return out



def finish(units):
    """The last touches, matched as the pictures' statistics, not pixel by pixel (a pixel-by-pixel error
    on pictures a pixel apart likes them blurred, and cannot see a highlight a pixel wide): the softening
    blur, by the pictures' sharpness -- their mean edge strength; the rubber's shine and rims, by how its
    pixels' brightness spreads -- the tyres' white rims are the bright tail of it."""
    P = settings()
    L0 = P['light']
    data = []
    for u in units:
        s, Rc, k = samples(u)
        s['exposure'] = P.get('exposures', {}).get(u, 1.0)
        ref = np.asarray(Image.open(hero_ref(u)).convert('RGB'), np.float32) / 255.0
        # (the rubber's pixels: the render's, where they lie in the game's portrait)
        rub = np.zeros(ref.shape[:2], bool)
        h, w = s['codes'].shape
        y, x = s['at']
        rub[y:y + h, x:x + w] = np.isin(s['codes'], RUBBER) & (s['cov'] > 0.98)
        data.append((s, ref, rub))
    lum = np.array([0.299, 0.587, 0.114], np.float32)

    def interior_sharpness(im):
        """The mean edge strength inside the model (every pixel about it not white): seams and faces."""
        l = im @ lum
        g = np.abs(np.diff(l, axis=0))[:, :-1] + np.abs(np.diff(l, axis=1))[:-1, :]
        solid = im.min(-1) < 0.9
        inside = solid.copy()
        inside[1:-1, 1:-1] = solid[1:-1, 1:-1] & solid[:-2, 1:-1] & solid[2:, 1:-1] & solid[1:-1, :-2] & solid[1:-1, 2:]
        return float(g[inside[:-1, :-1]].mean())

    def ringing(im):
        """The white about the model: how far from white, on average, within a few pixels of it."""
        solid = im.min(-1) < 0.9
        near = solid.copy()
        for _ in range(3):
            near[1:, :] |= near[:-1, :]
            near[:-1, :] |= near[1:, :]
            near[:, 1:] |= near[:, :-1]
            near[:, :-1] |= near[:, 1:]
        ring = near & ~solid & (im.min(-1) > 0.85)
        return float((1 - im[ring]).mean()) if ring.any() else 0.0

    def pic(s, ref, L):
        return np.asarray(picture(s, P, (ref.shape[1], ref.shape[0]), L), np.float32) / 255.0
    want_ring = np.mean([ringing(ref) for _, ref, _ in data])
    best = None
    for q in (40, 50, 60, 70, 80, 90, 0):
        L = dict(L0, jpeg=q)
        have = np.mean([ringing(pic(s, ref, L)) for s, ref, _ in data])
        if best is None or abs(have - want_ring) < best[0]:
            best = (abs(have - want_ring), q, have)
    L0 = dict(L0, jpeg=best[1])
    print('ringing of the white: the game portraits %.4f; JPEG quality %s gives %.4f' % (want_ring, best[1] or 'none', best[2]), flush=True)
    want = np.mean([interior_sharpness(ref) for _, ref, _ in data])
    best = None
    for seams in (0.0, 0.1, 0.2, 0.3):
        L = dict(L0, seams=seams, blur=0.0)
        have = np.mean([interior_sharpness(pic(s, ref, L)) for s, ref, _ in data])
        if best is None or abs(have - want) < best[0]:
            best = (abs(have - want), seams, have)
    L0 = dict(L0, seams=best[1], blur=0.0)
    print('sharpness inside: the game portraits %.4f; seams %.2f give %.4f' % (want, best[1], best[2]), flush=True)
    Q = (0.5, 0.75, 0.9, 0.95, 0.98)
    gq = np.quantile(np.concatenate([ref[rub] @ lum for _, ref, rub in data]), Q)
    best = None
    import itertools
    for (re_, ra), rs, pw, rim in itertools.product([(e, a) for e in (10, 35, 60, 80) for a in range(-180, 180, 45)],
                                                    (0.6, 1.2, 2.5), (10, 30, 80), (0.0, 0.3)):
                    L = dict(L0, rubber_shine=rs, rubber_power=pw, rubber_light={'elevation': re_, 'azimuth': ra}, rim=rim, rim_power=4, rim_rubber=True)
                    mq = np.quantile(np.concatenate([pic(s, ref, L)[rub] @ lum for s, ref, rub in data]), Q)
                    # (the tyres' middle kept dark above all: a sheen all over is not the game's)
                    e = float(np.abs(mq - gq).mean() + 3 * max(0, mq[0] - gq[0]))
                    if best is None or e < best[0]:
                        best = (e, L, mq)
    L0 = best[1]
    print('rubber brightness, quantiles %s: game %s, ours %s' % (Q, np.round(gq, 2), np.round(best[2], 2)))
    print('rubber shine %.2f (power %g) from %s, rims %.2f' % (L0['rubber_shine'], L0['rubber_power'], L0['rubber_light'], L0['rim']))
    P['light'] = L0
    json.dump(P, open(PAL, 'w', encoding='utf-8'), indent=1)
    print('written to config/hero_light.json')


# ---------- fitting with shadows ----------

def shadow_fit(units, group=None, tries=1500, rounds=3, seed=3, key_from=None, start=None, unit_rig=False):
    """The rig fitted with its lights' hard shadows: each light from SHADOW_GRID (its shadow rendered),
    the key's shadow cast always, the others' if they fit better so. The samples are the faces split by
    their shadows -- a face half in the key's shadow is two -- each its median colour in the game's and
    median light in the render."""
    data = []
    for u in units:
        im = Image.open(hero_ref(u))
        p = render(u, shadows=SHADOW_GRID)
        reg = registered(p, im)
        s = boxed(p, im.size, k=reg[1], at=reg[2])
        s['up'] = up_of(u)
        R = np.asarray(im.convert('RGB'), np.float32) / 255.0
        h, w = s['cov'].shape
        y, x = s['at']
        Rc = R[y:y + h, x:x + w]
        c = s['codes']
        keep = (s['cov'] > 0.98) & (c != '') & ~np.isin(c, s['glass']) & (Rc.min(-1) < 0.97)
        same = np.zeros_like(keep)
        same[1:-1, 1:-1] = (c[1:-1, 1:-1] == c[:-2, 1:-1]) & (c[1:-1, 1:-1] == c[2:, 1:-1]) & (c[1:-1, 1:-1] == c[1:-1, :-2]) & (c[1:-1, 1:-1] == c[1:-1, 2:])
        keep &= same
        print('  %s: registered %.3f, %d pixels' % (u, reg[0], keep.sum()), flush=True)
        data.append({'unit': u, 'N': s['N'][keep], 'A': s['A'][keep], 'code': c[keep].astype(str), 'G': Rc[keep],
                     'sh': {d: s['shadow'][d][keep] for d in s['shadow']}, 'slope': slopes(s)[keep]})
    nU = len(data)
    codes = sorted({c for d in data for c in np.unique(d['code'])})
    cidx = {c: i for i, c in enumerate(codes)}
    for d in data:
        d['ci'] = np.array([cidx[c] for c in d['code']])
        q = np.clip(np.round((d['N'] + 1) * 1.5), 0, 3).astype(int)
        d['base'] = d['ci'] * 64 + q[:, 0] * 16 + q[:, 1] * 4 + q[:, 2]
    dirs = [(float(e), float(a)) for e, a in SHADOW_GRID]
    LD = np.array([light_dir(e, a) for e, a in dirs])
    # (the key's directions allowed: all, or those key_from(elevation, azimuth) passes)
    key_ok = [i for i, d in enumerate(dirs) if key_from is None or key_from(*d)]

    def evaluate(P, want=False):
        amb, occ, gam, slope = P['amb'], P['occ'], P['gam'], P['slope']
        rows_v, rows_g, rows_w, rows_c = [], [], [], []
        for ui, d in enumerate(data):
            v = amb * np.power(np.clip(d['A'], 1e-3, 1), occ)
            key = d['base'].copy()
            for j, (di, w, shad) in enumerate(P['lights']):
                lam = np.maximum(0, d['N'] @ LD[di])
                if shad:
                    m = d['sh'][dirs[di]]
                    lam = lam * m
                    key = key * 2 + (m > 0.5)
                v = v + w * lam
            v = v * (1 - slope * d['slope'])
            v = np.power(np.maximum(v, 1e-4), gam) * np.exp(P['ex'][ui])
            uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
            for k_ in np.nonzero(cnt >= 12)[0]:
                m = inv == k_
                rows_v.append(np.median(v[m]))
                rows_g.append(np.median(d['G'][m], 0))
                rows_w.append(np.sqrt(cnt[k_]))
                rows_c.append(d['ci'][m][0])
        V_, G_, W_, C_ = np.array(rows_v), np.array(rows_g), np.array(rows_w), np.array(rows_c)
        pal = np.zeros((len(codes), 3))
        for ci in range(len(codes)):
            m = C_ == ci
            if not m.any():
                continue
            q = G_[m] / V_[m][:, None]
            for ch in range(3):
                okc = G_[m][:, ch] < 0.94
                if okc.any():
                    o = np.argsort(q[okc, ch])
                    cw = np.cumsum(W_[m][okc][o])
                    pal[ci, ch] = q[okc, ch][o][np.searchsorted(cw, cw[-1] / 2)]
                else:
                    pal[ci, ch] = 0.99 / V_[m].min()
            if codes[ci] in NEUTRAL:
                pal[ci] = pal[ci].mean()
        pred = np.clip(pal[C_] * V_[:, None], 0, 1)
        e = float((W_ * np.abs(pred - G_).mean(1)).sum() / W_.sum() * 255)
        return (e, pal) if want else e

    rng = np.random.default_rng(seed)

    def rand():
        return {'amb': rng.uniform(0.05, 0.9), 'occ': rng.uniform(0, 1.5), 'gam': rng.uniform(0.6, 1.8), 'slope': rng.uniform(0, 0.5),
                'ex': np.concatenate([[0.0], rng.uniform(-0.3, 0.3, nU - 1)]),
                'lights': [(int(rng.choice(key_ok)), 1.0, True)] +
                          [(int(rng.integers(len(dirs))), rng.uniform(0, 1.2), bool(rng.integers(2))) for _ in range(2)]}
    best = None
    if start:
        # (the period's usual rig to start from: two low lights from either side, a little behind)
        for amb in (0.1, 0.25, 0.4):
            for w2 in (0.5, 1.0, 1.5):
                P = {'amb': amb, 'occ': 0.5, 'gam': 1.0, 'slope': 0.1, 'ex': np.zeros(nU),
                     'lights': [(dirs.index((float(start[0][0]), float(start[0][1]))), 1.0, True),
                                (dirs.index((float(start[1][0]), float(start[1][1]))), w2, True), (0, 0.0, False)]}
                e = evaluate(P)
                if best is None or e < best[0]:
                    best = (e, P)
    for t in range(tries):
        P = rand()
        e = evaluate(P)
        if best is None or e < best[0]:
            best = (e, P)
    e, P = best
    print('shadowed rig, the search: %.2f' % e, flush=True)
    for r in range(rounds):
        # each light's direction (and whether it casts) over the whole grid
        for j in range(3):
            for di in (key_ok if j == 0 else range(len(dirs))):
                for shad in ((True,) if j == 0 else (True, False)):
                    Q = dict(P, lights=list(P['lights']))
                    Q['lights'][j] = (di, P['lights'][j][1], shad)
                    eq = evaluate(Q)
                    if eq < e:
                        e, P = eq, Q
        # the rest, a walk
        for it in range(600):
            Q = dict(P, lights=[(di, max(0.0, w + (rng.normal(0, 0.08) if j else 0)), sh) for j, (di, w, sh) in enumerate(P['lights'])],
                     amb=max(0.01, P['amb'] + rng.normal(0, 0.03)), occ=float(np.clip(P['occ'] + rng.normal(0, 0.06), 0, 2)),
                     gam=float(np.clip(P['gam'] + rng.normal(0, 0.05), 0.4, 2.5)), slope=float(np.clip(P['slope'] + rng.normal(0, 0.03), 0, 0.8)),
                     ex=np.concatenate([[0.0], P['ex'][1:] + rng.normal(0, 0.03, nU - 1)]))
            eq = evaluate(Q)
            if eq < e:
                e, P = eq, Q
        print('  round %d: %.2f  lights %s' % (r + 1, e, [(dirs[di], round(w, 2), sh) for di, w, sh in P['lights']]), flush=True)
    noshadow = evaluate(dict(P, lights=[(di, w, False) for di, w, _ in P['lights']]))
    print('with the shadows %.2f, without %.2f' % (e, noshadow))
    e, pal = evaluate(P, want=True)
    ex = np.exp(P['ex'] - P['ex'].mean())
    L = {'ambient': P['amb'], 'occlusion': P['occ'], 'gamma': P['gam'], 'slope': P['slope'],
         'lights': [{'w': float(w), 'elevation': dirs[di][0], 'azimuth': dirs[di][1], 'shadow': bool(sh)} for di, w, sh in P['lights']]}
    # (the palette at the middle exposure)
    pal = pal * np.exp(P['ex'].mean())
    out = {'colours': {c: [int(round(float(t) * 255)) for t in pal[i]] for i, c in enumerate(codes)}, 'light': L, 'fitted_on': units,
           'exposures': {d['unit']: round(float(f), 3) for d, f in zip(data, ex)}, 'face_error': round(e, 2),
           'face_error_without_shadows': round(noshadow, 2)}
    out['world_scale'] = world_scale(out)
    P_ = json.load(open(PAL, encoding='utf-8')) if os.path.exists(PAL) else dict(out)
    if unit_rig:
        P_.setdefault('units', {})[units[0]] = out
    elif group:
        P_.setdefault('groups', {})[group] = out
    else:
        P_.update(out)
    json.dump(P_, open(PAL, 'w', encoding='utf-8'), indent=1)
    print('written to config/hero_light.json%s' % (', unit ' + units[0] if unit_rig else ', group ' + group if group else ''))
    return out


# ---------- reflections ----------

def reflect_fit(units, tries=2500, steps=2500, seed=7):
    """The plastic's reflections, fitted on the game's portraits (each lit by its own rig): how much it
    reflects face on and at the edges, how bright the parts it reflects are, and the world about it (a
    sky above, a ground below). The fish shows them best: its jaw's top mirrors the head above it."""
    data = []
    for u in units:
        im = Image.open(hero_ref(u))
        P = settings(u)
        shadows = [(float(l['elevation']), float(l['azimuth'])) for l in P['light']['lights'] if l.get('shadow')]
        p = render(u, shadows=shadows or None)
        reg = registered(p, im)
        s = boxed(p, im.size, k=reg[1], at=reg[2])
        s['up'] = up_of(u)
        s['exposure'] = P.get('exposures', {}).get(u, 1.0)
        R_ = np.asarray(im.convert('RGB'), np.float32) / 255.0
        h, w = s['cov'].shape
        y, x = s['at']
        Rc = R_[y:y + h, x:x + w]
        c = s['codes']
        keep = (s['cov'] > 0.98) & (c != '') & ~np.isin(c, s['glass']) & (Rc.min(-1) < 0.97)
        P0 = dict(P)
        P0.pop('reflect', None)
        base = light_rgb(s, P0, P0['light'])[keep]
        data.append((u, s, keep, base, Rc[keep], P0))
        print('  %s: registered %.3f, %d pixels' % (u, reg[0], keep.sum()), flush=True)

    def err(R):
        e = []
        for u, s, keep, base, game, P0 in data:
            refl, r = reflected(s, P0, P0['light'], R)
            mine = np.clip(base * (1 - r[keep][:, None]) + refl[keep] * r[keep][:, None], 0, 1)
            d = np.abs(mine - game).mean(1)
            e.append(np.sort(d)[: int(len(d) * 0.85)].mean())
        return float(np.mean(e) * 255)

    none = {'r0': 0.0, 'fresnel': 0.0, 'part': 1.0, 'sky': [0, 0, 0], 'ground': [0, 0, 0], 'horizon': 0.3}
    e0 = err(none)
    rng = np.random.default_rng(seed)
    best = (e0, none)
    for t in range(tries):
        R = {'r0': rng.uniform(0, 0.5), 'fresnel': rng.uniform(0, 0.8), 'part': rng.uniform(0.3, 1.5),
             'sky': list(rng.uniform(0, 1.2, 3)), 'ground': list(rng.uniform(0, 1.2, 3)), 'horizon': rng.uniform(0.05, 1.0)}
        e = err(R)
        if e < best[0]:
            best = (e, R)
    e, R = best
    for it in range(steps):
        k = 0.5 ** (it / 800)
        Q = {'r0': float(np.clip(R['r0'] + rng.normal(0, 0.03 * k), 0, 0.9)), 'fresnel': float(np.clip(R['fresnel'] + rng.normal(0, 0.05 * k), 0, 1)),
             'part': float(np.clip(R['part'] + rng.normal(0, 0.06 * k), 0.1, 2)),
             'sky': [float(np.clip(v + rng.normal(0, 0.05 * k), 0, 1.5)) for v in R['sky']],
             'ground': [float(np.clip(v + rng.normal(0, 0.05 * k), 0, 1.5)) for v in R['ground']],
             'horizon': float(np.clip(R['horizon'] + rng.normal(0, 0.04 * k), 0.02, 1.5))}
        eq = err(Q)
        if eq < e:
            e, R = eq, Q
    print('reflections: error %.2f (without them %.2f)' % (e, e0))
    print('  %s' % {k: (round(v, 3) if not isinstance(v, list) else [round(x, 2) for x in v]) for k, v in R.items()})
    P = json.load(open(PAL, encoding='utf-8'))
    P['reflect'] = R
    P['reflect_error'] = {'with': round(e, 2), 'without': round(e0, 2), 'fitted_on': list(units)}
    json.dump(P, open(PAL, 'w', encoding='utf-8'), indent=1)
    print('written to config/hero_light.json')
    return R


def reflect_rig(unit, steps=3000, seed=11):
    """A portrait's rig refined with the plastic's reflections in it: the lights where the rig has them,
    their strengths, the sky, the gamma and the exposure walked again together with how much the plastic
    reflects (face on, and toward its edges), how bright the parts it reflects are and the world about it.
    Fitted together, the reflections are not pre-empted by the lights (a rig fitted without them darkens
    the tops itself). Pixel by pixel, the palette solved anew each step."""
    im = Image.open(hero_ref(unit))
    P = json.load(open(PAL, encoding='utf-8'))
    rig = P['units'][unit]
    Pu = settings(unit)
    shadows = [(float(l['elevation']), float(l['azimuth'])) for l in rig['light']['lights'] if l.get('shadow')]
    p = render(unit, shadows=shadows or None)
    reg = registered(p, im)
    s = boxed(p, im.size, k=reg[1], at=reg[2])
    s['up'] = up_of(unit)
    R_ = np.asarray(im.convert('RGB'), np.float32) / 255.0
    h, w = s['cov'].shape
    y, x = s['at']
    Rc = R_[y:y + h, x:x + w]
    c = s['codes']
    keep = (s['cov'] > 0.98) & (c != '') & ~np.isin(c, s['glass']) & (Rc.min(-1) < 0.97)
    G = Rc[keep]
    codes = c[keep].astype(str)
    from .shade import palette as world
    Wp = world()['colours']
    # (the parts reflected: their colour as the world palette has it, brought to this rig's scale)
    k0 = rig.get('world_scale') or 1.0

    def part_rgb(code):
        v = Wp.get(code) or s['legend'].get(code) or [128, 128, 128]
        return np.array(v, np.float32) / 255.0 * k0
    rc = s['rcodes']
    partcol = np.zeros(s['N'].shape, np.float32)
    for code in np.unique(rc):
        if code:
            partcol[rc == code] = part_rgb(code)
    partcol = partcol[keep]
    robj = s['robj'][keep][:, None]
    rz = s['rdir'][..., 2][keep]
    nv = np.clip(s['N'] @ V, 0, 1)[keep]

    def unpackL(x):
        L = dict(Pu['light'])
        L['ambient'], L['occlusion'], L['gamma'], L['slope'] = float(max(x[0], 0.01)), float(np.clip(x[1], 0, 2)), float(np.clip(x[2], 0.4, 2.5)), float(np.clip(x[3], 0, 0.8))
        L['lights'] = [dict(li, w=float(max(x[4 + i], 0)) if i else 1.0) for i, li in enumerate(rig['light']['lights'])]
        R = {'r0': float(np.clip(x[7], 0, 0.8)), 'fresnel': float(np.clip(x[8], 0, 1)), 'part': float(np.clip(x[9], 0, 2)),
             'sky': [float(np.clip(v, 0, 1.6)) for v in x[10:13]], 'ground': [float(np.clip(v, 0, 1.6)) for v in x[13:16]],
             'horizon': float(np.clip(x[16], 0.02, 1.5))}
        return L, R, float(np.exp(x[17]))

    def evaluate(x, want=False):
        L, R, ex = unpackL(x)
        v, white = lit(s, L)
        v = v[keep] * ex
        white = white[keep]
        t = np.clip(0.5 + rz / max(R['horizon'], 1e-3), 0, 1)[:, None]
        env = np.array(R['ground'], np.float32) + (np.array(R['sky'], np.float32) - np.array(R['ground'], np.float32)) * t
        refl = partcol * R['part'] * robj + env * (1 - robj)
        r = np.clip(R['r0'] + R['fresnel'] * np.power(1 - nv, 5), 0, 1)[:, None]
        # (the palette: what is left once the reflection is taken off, over the light)
        rest = (G - r * refl - white[:, None]) / np.maximum(v[:, None] * (1 - r), 1e-3)
        pal = {}
        pred = np.zeros_like(G)
        for code in np.unique(codes):
            m = codes == code
            col = np.zeros(3, np.float32)
            for ch in range(3):
                ok = G[m][:, ch] < 0.94
                col[ch] = np.median(rest[m][ok, ch]) if ok.sum() >= 10 else 0.99 / max(np.quantile(v[m], 0.03), 0.1)
            if code in NEUTRAL:
                col[:] = col.mean()
            pal[code] = np.clip(col, 0, 4)
            pred[m] = pal[code] * v[m][:, None] * (1 - r[m]) + r[m] * refl[m] + white[m][:, None]
        d = np.abs(np.clip(pred, 0, 1) - G).mean(1)
        e = float(np.sort(d)[: int(len(d) * 0.85)].mean() * 255)
        return (e, pal, L, R, ex) if want else e

    L0 = rig['light']
    ws = [li['w'] for li in L0['lights']] + [0.0, 0.0, 0.0]
    # (0..3 ambient, occlusion, gamma, slope; 4..5 the second and third lights' strengths; 6 spare;
    # 7..16 the reflections; 17 the exposure's log)
    x = np.array([L0['ambient'], L0['occlusion'], L0['gamma'], L0.get('slope', 0.0), ws[1], ws[2], 0.0,
                  0.0, 0.0, 0.8, 0.1, 0.1, 0.1, 0.8, 0.8, 0.8, 0.3, np.log(rig.get('exposures', {}).get(unit, 1.0))], np.float64)
    x_none = x.copy()
    x_none[7] = x_none[8] = 0.0
    e0 = evaluate(x_none)
    e = evaluate(x)
    rng = np.random.default_rng(seed)
    step = np.array([0.04, 0.06, 0.05, 0.03, 0.06, 0.06, 0, 0.03, 0.05, 0.08, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.05, 0.03])
    # (a wide look at the reflections first)
    best = (e, x)
    for t in range(800):
        y_ = x.copy()
        y_[7:17] = [rng.uniform(0, 0.5), rng.uniform(0, 0.8), rng.uniform(0.3, 1.5)] + list(rng.uniform(0, 1.2, 6)) + [rng.uniform(0.05, 1)]
        ey = evaluate(y_)
        if ey < best[0]:
            best = (ey, y_)
    e, x = best
    for it in range(steps):
        y_ = x + rng.normal(0, 1, len(x)) * step * (0.5 ** (it / 1000))
        ey = evaluate(y_)
        if ey < e:
            e, x = ey, y_
    e, pal, L, R, ex = evaluate(x, want=True)
    print('%s: %.2f with reflections (its rig without them %.2f); reflectivity %.2f + %.2f at the edges, parts x%.2f, sky %s, ground %s'
          % (unit, e, e0, R['r0'], R['fresnel'], R['part'], [round(v, 2) for v in R['sky']], [round(v, 2) for v in R['ground']]), flush=True)
    if e < e0 - 0.2:
        rig = dict(rig, light=dict(rig['light'], **{k: L[k] for k in ('ambient', 'occlusion', 'gamma', 'slope', 'lights')}),
                   reflect=R, colours={c_: [int(round(float(t) * 255)) for t in v] for c_, v in pal.items()},
                   exposures={unit: round(ex, 3)}, reflect_error=round(e, 2))
        rig['world_scale'] = world_scale(rig)     # (the palette refitted: its scale to the world's anew)
        P = json.load(open(PAL, encoding='utf-8'))
        P['units'][unit] = rig
        json.dump(P, open(PAL, 'w', encoding='utf-8'), indent=1)
        print('  written')
    return e, e0


if __name__ == '__main__':
    main()
