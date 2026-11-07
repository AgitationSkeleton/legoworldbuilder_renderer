"""The game's look, composited: a sprite's pixel is its brick's colour (the game's own, more
saturated than LDraw's: config/palette.json) times the light on it, in the picture's values, the
brightest tops lit past white; as a 1999 renderer did it, not as a physical one.

Blender renders each shot as passes (blender/wbsprite.py, run_passes): which LDraw colour each
pixel is, and how much of each light falls on it (several key lights, a fill, the sky).  Here
they are brought down to the sprite's size and put together:

    light = ambient*A + key*K + fill*F            (linear, per pixel)
    v     = light ** gamma
    rgb   = palette[colour] * v + highlight * max(0, K - knee) / (1 - knee)   (clipped)

and the edge smoothed against the fringe colour and cut out (wbrender/post.py).

    python -m wbrender.shade fit [--units buggy,duck,...]   # palette and light fitted to the game's sprites
    python -m wbrender.shade show UNIT                       # the unit composited, beside the game's

The fit: the passes of each unit's four directions, laid on the game's sprites where they overlap
best, every inner pixel a sample; the palette (each colour's own, by least squares) and the
lights (a few numbers, by a simplex search) in turn."""
import argparse
import json
import os

import numpy as np
from PIL import Image

from . import blender, post
from .fit import DIRS, ortho_size, iou, crop
from .units import UNITS, ROOT, model_path, ref_path
from .render import load_fit, style

PAL = os.path.join(ROOT, 'config', 'palette.json')
KEYS = [(e, a) for e in (30, 45, 60, 75) for a in (-135, -90, -45, 0, 45)]   # the key lights rendered, (elevation, azimuth)
FILL = {'elevation': 20.0, 'azimuth': 160.0}
MIN_IOU = 0.85    # directions matching the game's outline less than this are not sampled
LIGHT0 = {'ambient': 0.35, 'key': 1.1, 'fill': 0.25, 'gamma': 0.75, 'highlight': 0.25, 'knee': 0.75, 'key_index': 5}


def palette():
    return json.load(open(PAL, encoding='utf-8')) if os.path.exists(PAL) else {'colours': {}, 'light': dict(LIGHT0)}


# ---------- rendering the passes ----------

def render_passes(unit, dirs, size=320, samples=24, studs=None, recolour=None, water=None, work=None):
    """{direction: {'id': codes (H, W) str array, 'legend', 'alpha', 'A', 'F', 'K': [12 arrays]}} at render size."""
    fit = load_fit(unit)
    S = style()
    work = work or os.path.join(ROOT, 'work', 'passes', unit)
    os.makedirs(work, exist_ok=True)
    passes = [('k%d' % i, {'elevation': e, 'azimuth': a, 'strength': 1}) for i, (e, a) in enumerate(KEYS)]
    passes += [('fill', dict(FILL, strength=1)), ('ambient', None)]
    params = {'elevation': fit['elevation'], 'skew': fit.get('skew', 0.0), 'passes': passes, 'normal_pass': True}
    if recolour:
        params['recolour'] = recolour
    shots = [{'path': os.path.join(work, d), 'heading': fit['headings'][d]} for d in dirs]
    r = blender.run({'model': model_path(unit), 'mode': 'passes', 'size': size, 'samples': samples, 'shots': shots,
                     'studs': studs or UNITS[unit].get('studs', S.get('studs', 'none')), 'params': params})
    legend = r['legend']
    out = {}
    for d in dirs:
        base = os.path.join(work, d)
        idim = np.asarray(Image.open(base + '.id.png').convert('RGBA'))
        codes = np.full(idim.shape[:2], '', dtype=object)
        for key, v in legend.items():
            rgb = tuple(int(x) for x in key.split(','))
            codes[(idim[..., 0] == rgb[0]) & (idim[..., 1] == rgb[1]) & (idim[..., 2] == rgb[2]) & (idim[..., 3] > 0)] = v['code']

        def lum(name):
            a = np.asarray(Image.open(base + '.' + name + '.png'))
            a = a.astype(np.float32) / (65535.0 if a.dtype == np.uint16 else 255.0)
            return a
        K = [lum('k%d' % i) for i in range(len(KEYS))]
        F, A = lum('fill'), lum('ambient')
        H = lum('height')[..., 0] if os.path.exists(base + '.height.png') else np.zeros(A.shape[:2], np.float32)
        # (a sun of strength 1 lights white plastic to 0.8/pi where it faces it; the sky of strength 1 to 0.8:
        # both brought to 1, so that the lights' weights say how strong each is against the other)
        out[d] = {'codes': codes, 'legend': {v['code']: v['rgb'] for v in legend.values()}, 'alpha': A[..., 3],
                  'A': A[..., 0] / 0.8, 'F': F[..., 0] * np.pi / 0.8, 'K': [k[..., 0] * np.pi / 0.8 for k in K], 'H': H}
        out[d]['unit'] = unit
        if os.path.exists(base + '.normal.png'):
            # (each pixel's surface direction, the camera's frame, +z towards it: for the map's light rig)
            n = lum('normal')[..., :3] * 2 - 1
            n[..., 2] *= -1
            out[d]['N'] = n
    out['_ppu'] = size / ortho_size(r['radius'], fit.get('skew', 0.0))
    out['_scale'] = fit['scale']
    return out


# ---------- bringing them down ----------

def shrink_field(f, alpha, factor):
    """A light pass averaged down where the model is (premultiplied by its coverage)."""
    pre = np.stack([f * alpha, alpha], -1)
    im = Image.fromarray(np.float32(pre[..., 0]), 'F')
    w, h = im.size
    nw, nh = max(1, round(w / factor)), max(1, round(h / factor))
    num = np.asarray(Image.fromarray(np.float32(pre[..., 0]), 'F').resize((nw, nh), Image.BOX))
    den = np.asarray(Image.fromarray(np.float32(pre[..., 1]), 'F').resize((nw, nh), Image.BOX))
    return num / np.maximum(den, 1e-6), den


def shrink_codes(codes, factor):
    """Each small pixel the colour code covering most of it."""
    h, w = codes.shape
    nw, nh = max(1, round(w / factor)), max(1, round(h / factor))
    names = [c for c in np.unique(codes) if c]
    best = np.zeros((nh, nw), np.float32)
    out = np.full((nh, nw), '', dtype=object)
    for c in names:
        cover = np.asarray(Image.fromarray(np.float32(codes == c), 'F').resize((nw, nh), Image.BOX))
        take = cover > best
        out[take] = c
        best = np.maximum(best, cover)
    return out


def fill_codes(codes, cov):
    """Pixels the model covers but no colour landed on (between two parts): their neighbours' colour."""
    for _ in range(4):
        empty = (codes == '') & (cov > 0.05)
        if not empty.any():
            break
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            src = np.roll(np.roll(codes, dy, 0), dx, 1)
            take = empty & (src != '')
            codes[take] = src[take]
            empty &= ~take
    return codes


def small(p, factor):
    """A direction's passes at sprite size: codes, coverage, A, F, K[]."""
    A, cov = shrink_field(p['A'], p['alpha'], factor)
    F, _ = shrink_field(p['F'], p['alpha'], factor)
    K = [shrink_field(k, p['alpha'], factor)[0] for k in p['K']]
    H, _ = shrink_field(p['H'], p['alpha'], factor)
    out = {'H': H, 'codes': fill_codes(shrink_codes(p['codes'], factor), cov), 'cov': cov, 'A': A, 'F': F, 'K': K, 'legend': p['legend'],
           'unit': p.get('unit')}
    if 'N' in p:
        n = np.stack([shrink_field(p['N'][..., i], p['alpha'], factor)[0] for i in range(3)], -1)
        out['N'] = n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
    return out


# ---------- compositing ----------

def base_colour(code, legend, pal):
    c = pal['colours'].get(code)
    if c is None:
        c = legend.get(code) or [128, 128, 128]
        # (a colour no sprite of the game's showed: LDraw's, brought into the game's as the learned
        # ones are -- config/palette.json 'map', a 3x3 and offset fitted from LDraw's to the game's)
        if pal.get('map'):
            M = np.array(pal['map'], np.float32)
            c = np.clip(M[:, :3] @ np.array(c, np.float32) + M[:, 3], 0, 255)
    return np.array(c, np.float32) / 255.0


_MAP_RIG = {}


def map_rig():
    """config/map_light.json: the map sprites' light rig and palette (wbrender/mapnormal.py), or None."""
    p = os.path.join(ROOT, 'config', 'map_light.json')
    if not os.path.exists(p):
        return None
    t = os.path.getmtime(p)
    if _MAP_RIG.get('t') != t:
        _MAP_RIG.update(t=t, rig=json.load(open(p, encoding='utf-8')))
    return _MAP_RIG['rig']


def map_colour(code, legend, pal, M):
    """A colour under the map's rig: fitted with it on the game's sprites, or the world palette's brought to
    its scale (the median ratio of the colours both have)."""
    c = M['colours'].get(code)
    if c is not None:
        return np.array(c, np.float32) / 255.0
    if 'scale' not in M:
        r = [sum(v) / max(1, sum(pal['colours'][k])) for k, v in M['colours'].items() if k in pal['colours'] and k not in ('0', '256')]
        M['scale'] = float(np.median(r)) if r else 1.0
    return base_colour(code, legend, pal) * M['scale']


def composite(s, pal, light=None, water=None):
    """RGB 0..1 (H, W, 3) of a direction's small passes; in water (water: {waterline, mix, depth,
    color, deep}), what is below the line taken toward the water's colour, deeper toward its depths."""
    M = map_rig() if light is None and 'N' in s else None
    if M:
        # the map's light rig, fitted face by face on the game's sprites (wbrender/mapnormal.py): lights
        # from any direction on each surface's direction, the sky, a gamma, each channel clipped
        from .heronormal import light_dir
        R = M['light']
        v = R['ambient'] * np.power(np.clip(s['A'], 1e-3, 1), R['occlusion'])
        for li in R['lights']:
            v = v + li['w'] * np.maximum(0, s['N'] @ light_dir(li['elevation'], li['azimuth']))
        v = np.power(np.maximum(v, 1e-4), R['gamma']) * M.get('exposures', {}).get(s.get('unit'), 1.0)
        rgb = np.zeros(s['A'].shape + (3,), np.float32)
        for code in np.unique(s['codes']):
            if code:
                m = s['codes'] == code
                rgb[m] = map_colour(code, s['legend'], pal, M)[None, :] * v[m][:, None]
        rgb = np.clip(rgb, 0, 1)
    else:
        L = light or pal['light']
        K = s['K'][int(L['key_index'])]
        v = np.maximum(0, L['ambient'] * s['A'] + L['key'] * K + L['fill'] * s['F']) ** L['gamma']
        rgb = np.zeros(s['A'].shape + (3,), np.float32)
        for code in np.unique(s['codes']):
            if not code:
                continue
            m = s['codes'] == code
            rgb[m] = base_colour(code, s['legend'], pal)[None, :] * v[m][:, None]
        hl = L['highlight'] * np.clip((K - L['knee']) / max(1e-3, 1 - L['knee']), 0, None)
        rgb = np.clip(rgb + hl[..., None], 0, 1)
    if water:
        under = s['H'] < water['waterline']
        depth = np.clip((water['waterline'] - s['H']) / max(1e-3, water['depth']), 0, 1)[..., None]
        wc = np.array(water['color'], np.float32) * (1 - depth) + np.array(water['deep'], np.float32) * depth
        mixed = rgb * (1 - water['mix']) + wc * water['mix']
        rgb = np.where(under[..., None], mixed, rgb)
    return rgb


def to_sprite(s, pal, fringe, threshold=0.5, light=None, water=None):
    rgb = composite(s, pal, light, water)
    al = s['cov'][..., None]
    out = rgb * al + (1 - al) * np.array(fringe, np.float32) / 255.0
    keep = s['cov'] >= threshold
    a = np.zeros(rgb.shape[:2] + (4,), np.uint8)
    a[..., :3] = np.uint8(np.clip(out * 255 + 0.5, 0, 255))
    # (no pure white: the game draws its map sprites with white as the see-through colour -- a white
    # beak would be a hole)
    white = (a[..., :3] >= 251).all(-1)
    a[white, :3] = 250
    a[..., 3] = np.where(keep, 255, 0)
    ys, xs = np.nonzero(keep)
    return Image.fromarray(a[ys.min():ys.max() + 1, xs.min():xs.max() + 1], 'RGBA'), (ys.min(), xs.min())


# ---------- fitting to the game's sprites ----------

def align(mask, ref_mask, slack=3):
    """The offset (dy, dx) of the render's crop on the game's crop where they overlap most."""
    a, b = crop(mask), crop(ref_mask)
    best, at = -1, (0, 0)
    for dy in range(-slack, slack + 1):
        for dx in range(-slack, slack + 1):
            y0 = (b.shape[0] - a.shape[0]) // 2 + dy
            x0 = (b.shape[1] - a.shape[1]) // 2 + dx
            ys = slice(max(0, y0), min(b.shape[0], y0 + a.shape[0]))
            xs = slice(max(0, x0), min(b.shape[1], x0 + a.shape[1]))
            if ys.stop <= ys.start or xs.stop <= xs.start:
                continue
            ov = (a[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0] & b[ys, xs]).sum()
            if ov > best:
                best, at = ov, (y0, x0)
    return at


def erode(m):
    e = m.copy()
    e[1:] &= m[:-1]
    e[:-1] &= m[1:]
    e[:, 1:] &= m[:, :-1]
    e[:, :-1] &= m[:, 1:]
    return e


def samples_for(unit, size=320, samples=24):
    """Pixel samples of a unit: codes, A, F, K[] (each (N,)), and the game's colour (N, 3) 0..1."""
    dirs = [d for d in DIRS if ref_path(unit, d)]
    P = render_passes(unit, dirs, size, samples)
    factor = P['_ppu'] / P['_scale']
    out = {'codes': [], 'A': [], 'F': [], 'K': [[] for _ in KEYS], 'ref': [], 'legend': {}}
    for d in dirs:
        s = small(P[d], factor)
        mine = s['cov'] >= 0.5
        ref = Image.open(ref_path(unit, d))
        R = post.reference_mask(ref)
        rgb = np.asarray(ref.convert('RGB'), np.float32) / 255.0
        ys, xs = np.nonzero(mine)
        y0, x0 = ys.min(), xs.min()
        cm = crop(mine)
        # (a direction whose outline the render does not match well says little of its colours)
        if iou(mine, R) < MIN_IOU:
            print('  %s %s: outlines overlap %.2f, left out' % (unit, d, iou(mine, R)), flush=True)
            continue
        ry, rx = np.nonzero(R)
        oy, ox = align(cm, crop(R))
        inner = erode(cm)
        # (inner pixels of the render inside one colour's patch, landing inside the game's sprite
        # where its colours are alike about the pixel: where the two show the same surface)
        Rin = erode(R)
        cc = s['codes'][y0:y0 + cm.shape[0], x0:x0 + cm.shape[1]]
        for y, x in zip(*np.nonzero(inner)):
            gy, gx = ry.min() + oy + y, rx.min() + ox + x
            if 1 <= gy < R.shape[0] - 1 and 1 <= gx < R.shape[1] - 1 and Rin[gy, gx]:
                code = s['codes'][y0 + y, x0 + x]
                if not code or y < 1 or x < 1 or y >= cc.shape[0] - 1 or x >= cc.shape[1] - 1:
                    continue
                if not (cc[y - 1:y + 2, x - 1:x + 2] == code).all():
                    continue
                patch = rgb[gy - 1:gy + 2, gx - 1:gx + 2].reshape(-1, 3)
                if np.abs(patch - rgb[gy, gx]).max() > 0.35:
                    continue
                out['codes'].append(code)
                out['A'].append(s['A'][y0 + y, x0 + x])
                out['F'].append(s['F'][y0 + y, x0 + x])
                for i in range(len(KEYS)):
                    out['K'][i].append(s['K'][i][y0 + y, x0 + x])
                out['ref'].append(rgb[gy, gx])
        out['legend'].update(s['legend'])
    return {k: (np.array(v, dtype=object if k == 'codes' else np.float32) if k not in ('K', 'legend') else v) for k, v in out.items()}


def fit(units, size=320, samples=24, iterations=4):
    data = [samples_for(u, size, samples) for u in units]
    codes = np.concatenate([d['codes'] for d in data])
    A = np.concatenate([d['A'] for d in data])
    F = np.concatenate([d['F'] for d in data])
    K = [np.concatenate([np.array(d['K'][i], np.float32) for d in data]) for i in range(len(KEYS))]
    ref = np.concatenate([d['ref'] for d in data])
    legend = {}
    for d in data:
        legend.update(d['legend'])
    names = [c for c in np.unique(codes) if np.sum(codes == c) >= 15]
    pal = palette()
    light = dict(pal['light'])

    def shade(L):
        return np.maximum(0, L['ambient'] * A + L['key'] * K[int(L['key_index'])] + L['fill'] * F) ** L['gamma']

    def colours_for(L):
        v = shade(L)
        cols = {}
        for c in names:
            m = (codes == c) & (v < 1.0)            # (not those lit past white: they say nothing of the colour)
            if m.sum() < 10:
                m = codes == c
            vv = v[m][:, None]
            # (robust: the median of the game's colour over the light, not a mean pulled by strays)
            cols[c] = np.clip(np.median(ref[m] / np.maximum(vv, 0.05), axis=0), 0, 1)
        return cols

    def error(L, cols):
        v = shade(L)
        K_ = K[int(L['key_index'])]
        hl = L['highlight'] * np.clip((K_ - L['knee']) / max(1e-3, 1 - L['knee']), 0, None)
        pred = np.zeros_like(ref)
        for c in names:
            m = codes == c
            pred[m] = cols[c][None, :] * v[m][:, None]
        pred = np.clip(pred + hl[:, None], 0, 1)
        keep = np.isin(codes, names)
        e = np.abs(pred[keep] - ref[keep]).mean(1)
        # (trimmed: the worst fifth, where render and game still disagree on the surface, left out)
        e = np.sort(e)[: max(1, int(len(e) * 0.8))]
        return float(e.mean() * 255)

    keys = ['ambient', 'key', 'fill', 'gamma', 'highlight', 'knee']
    bounds = {'ambient': (0, 1.5), 'key': (0, 3), 'fill': (0, 3), 'gamma': (0.3, 2.2), 'highlight': (0, 1.5), 'knee': (0.3, 0.98)}
    best = None
    for ki in range(len(KEYS)):
        L = dict(light, key_index=ki)
        cols = colours_for(L)
        e = error(L, cols)
        if best is None or e < best[0]:
            best = (e, ki)
    light['key_index'] = best[1]
    print('key light: elevation %g, azimuth %g (error %.1f)' % (KEYS[best[1]] + (best[0],)), flush=True)
    for it in range(iterations):
        cols = colours_for(light)
        light = simplex(lambda x: error(dict(light, **dict(zip(keys, x))), cols), [light[k] for k in keys],
                        [bounds[k] for k in keys], keys, light)
        print('round %d: error %.1f  %s' % (it + 1, error(light, colours_for(light)), {k: round(light[k], 3) for k in keys}), flush=True)
    cols = colours_for(light)
    pal = {'colours': {c: [int(round(x * 255)) for x in v] for c, v in sorted(cols.items())}, 'light': light,
           'key': {'elevation': KEYS[light['key_index']][0], 'azimuth': KEYS[light['key_index']][1]}, 'fill': FILL,
           'samples': {c: int(np.sum(codes == c)) for c in names}, 'fitted_on': units}
    json.dump(pal, open(PAL, 'w', encoding='utf-8'), indent=1)
    print('palette:', pal['colours'])
    return pal


def learn_colours(units, least_iou=0.72, least=40, size=320, samples=24):
    """The palette widened: with the light as fitted, each colour of every unit's sprites the core fit
    did not sample (tan, brown, the greens ...) learned the same way -- the median of the game's colour
    over the light -- from directions matching the game's outline at least least_iou; then the map from
    LDraw's colours to the game's, for colours no sprite shows."""
    global MIN_IOU
    pal = palette()
    L = pal['light']
    MIN_IOU, was = least_iou, MIN_IOU
    ratios, legend = {}, {}
    try:
        for u in units:
            try:
                d = samples_for(u, size, samples)
            except Exception as e:
                print('  %s: %s' % (u, e), flush=True)
                continue
            legend.update(d['legend'])
            if not len(d['codes']):
                continue
            K = np.array(d['K'][int(L['key_index'])], np.float32)
            v = np.maximum(0, L['ambient'] * d['A'] + L['key'] * K + L['fill'] * d['F']) ** L['gamma']
            for c in np.unique(d['codes']):
                m = (d['codes'] == c) & (v < 1.0) & (v > 0.15)
                if m.sum():
                    ratios.setdefault(c, []).append(d['ref'][m] / v[m][:, None])
            print('  %s: %d samples' % (u, len(d['codes'])), flush=True)
    finally:
        MIN_IOU = was
    added = {}
    for c, rs in ratios.items():
        r = np.concatenate(rs)
        if c in pal['colours'] or len(r) < least:
            continue
        added[c] = [int(round(x * 255)) for x in np.clip(np.median(r, 0), 0, 1)]
    pal['colours'].update(added)
    pal.setdefault('learned_later', {}).update({c: True for c in added})
    drop_strays(pal)
    # (LDraw's colour -> the game's, by least squares over every colour learned)
    X, Y = [], []
    for c, v in pal['colours'].items():
        ld = ldraw_rgb(c)
        if ld is not None:
            X.append(list(ld) + [1.0])
            Y.append(v)
    if len(X) >= 6:
        M, *_ = np.linalg.lstsq(np.array(X, np.float64), np.array(Y, np.float64), rcond=None)
        pal['map'] = [[round(float(x), 4) for x in row] for row in M.T]
    json.dump(pal, open(PAL, 'w', encoding='utf-8'), indent=1)
    print('added:', added)
    return pal


def drop_strays(pal, limit=55.0):
    """A colour learned late (from whatever sprites happened to show it) that strays far from what
    the map from LDraw's colours says it should be: learned off a recreation built otherwise than the
    game's model (the marina's cyan parts, where JappaWakka built in medium blue, taught medium blue
    as cyan), not a finding. Dropped; the map gives it."""
    if not pal.get('map'):
        return []
    M = np.array(pal['map'], np.float32)
    dropped = []
    for c in list(pal.get('learned_later', {})):
        if c in pal.get('pinned', {}):
            continue
        ld = ldraw_rgb(c)
        v = pal['colours'].get(c)
        if ld is None or v is None:
            continue
        mapped = np.clip(M[:, :3] @ np.array(ld, np.float32) + M[:, 3], 0, 255)
        if np.abs(np.array(v, np.float32) - mapped).max() > limit:
            del pal['colours'][c]
            pal['learned_later'].pop(c, None)
            dropped.append(c)
    if dropped:
        print('dropped as strays (the map gives them):', dropped)
    return dropped


def ldraw_rgb(code):
    """An LDraw colour's RGB from the library's LDConfig.ldr, or None."""
    from .blender import local
    path = os.path.join(local()['ldraw'], 'LDConfig.ldr')
    if not os.path.exists(path):
        return None
    for line in open(path, encoding='utf-8', errors='replace'):
        t = line.split()
        if len(t) > 6 and t[0] == '0' and t[1] == '!COLOUR' and 'CODE' in t and t[t.index('CODE') + 1] == str(code):
            h = t[t.index('VALUE') + 1].lstrip('#')
            return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return None


def simplex(f, x0, bounds, keys, base, iters=160):
    """Nelder-Mead, kept inside bounds: the x (dict of keys onto base) where f is least."""
    def clip(x):
        return np.array([min(hi, max(lo, v)) for v, (lo, hi) in zip(x, bounds)])
    n = len(x0)
    pts = [clip(np.array(x0, float))]
    for i in range(n):
        p = np.array(x0, float)
        p[i] += (bounds[i][1] - bounds[i][0]) * 0.15
        pts.append(clip(p))
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = np.argsort(vals)
        pts = [pts[i] for i in order]
        vals = [vals[i] for i in order]
        c = np.mean(pts[:-1], 0)
        r = clip(c + (c - pts[-1]))
        fr = f(r)
        if fr < vals[0]:
            e = clip(c + 2 * (c - pts[-1]))
            fe = f(e)
            pts[-1], vals[-1] = (e, fe) if fe < fr else (r, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = r, fr
        else:
            k = clip(c + 0.5 * (pts[-1] - c))
            fk = f(k)
            if fk < vals[-1]:
                pts[-1], vals[-1] = k, fk
            else:
                pts = [pts[0]] + [clip(pts[0] + 0.5 * (p - pts[0])) for p in pts[1:]]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
    out = dict(base)
    out.update(dict(zip(keys, [float(v) for v in pts[int(np.argmin(vals))]])))
    return out


def fit_water(units=('duck', 'frog', 'fish', 'gator'), size=320, samples=24, tries=240, seed=3):
    """The water's look fitted to the game's partly submerged sprites: waterline, how much of the
    water's colour, how deep before it is the depths' colour, both colours and the edge's."""
    import random
    from .render import colour_error
    random.seed(seed)
    pal = palette()
    S = style()
    sets = []
    for u in units:
        dirs = [d for d in DIRS if ref_path(u, d, water=True)]
        if not dirs:
            continue
        P = render_passes(u, dirs, size, samples)
        factor = P['_ppu'] / P['_scale']
        for d in dirs:
            sets.append((small(P[d], factor), Image.open(ref_path(u, d, water=True))))
    W = dict(S['water'])
    space = {'waterline': (0.05, 0.75), 'mix': (0.2, 1.0), 'depth': (0.05, 1.0)}

    def look(v):
        return {'waterline': v['waterline'], 'mix': v['mix'], 'depth': v['depth'], 'color': v['color'], 'deep': v['deep']}

    def err(v, fringe):
        tot = 0
        for s, ref in sets:
            spr, _ = to_sprite(s, pal, fringe, S['threshold'], water=look(v))
            tot += (colour_error(spr, ref) or 200) + 100 * (1 - iou(np.asarray(spr)[..., 3] > 0, post.reference_mask(ref)))
        return tot / len(sets)

    v = {'waterline': W['waterline'], 'mix': W['mix'], 'depth': W['depth'], 'color': list(W['color']), 'deep': list(W['deep'])}
    fringe = tuple(W['fringe'])
    best = err(v, fringe)
    for i in range(tries):
        spread = 0.25 * (1 - i / tries) + 0.03
        c = {k: min(hi, max(lo, v[k] + random.gauss(0, (hi - lo) * spread))) for k, (lo, hi) in space.items()}
        c['color'] = [min(1, max(0, x + random.gauss(0, spread * 0.5))) for x in v['color']]
        c['deep'] = [min(1, max(0, x + random.gauss(0, spread * 0.5))) for x in v['deep']]
        f = tuple(int(min(255, max(0, x + random.gauss(0, 60 * spread)))) for x in fringe)
        e = err(c, f)
        if e < best:
            best, v, fringe = e, c, f
            print('water %d: %.1f  %s fringe %s' % (i, best, {k: (round(x, 3) if not isinstance(x, list) else [round(y, 2) for y in x]) for k, x in v.items()}, fringe), flush=True)
    S['water'].update({'waterline': round(v['waterline'], 3), 'mix': round(v['mix'], 3), 'depth': round(v['depth'], 3),
                       'color': [round(x, 3) for x in v['color']], 'deep': [round(x, 3) for x in v['deep']], 'fringe': list(fringe)})
    json.dump(S, open(os.path.join(ROOT, 'config', 'style.json'), 'w', encoding='utf-8'), indent=1)
    print('written to config/style.json')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('what', choices=['fit', 'show', 'fit-water', 'colours'])
    ap.add_argument('units', nargs='*')
    ap.add_argument('--units', dest='unit_list', default='buggy,duck,dumptruck,dozer,speedboat,crab,defender,fish')
    a = ap.parse_args()
    if a.what == 'fit-water':
        fit_water(tuple(a.units) if a.units else ('duck', 'frog', 'fish', 'gator'))
    elif a.what == 'colours':
        from .units import UNITS as U
        us = a.units or [u for u in U if not (U[u].get('unused') or U[u].get('colours')) and any(ref_path(u, d) for d in DIRS)]
        learn_colours(us)
    elif a.what == 'fit':
        fit((a.units or a.unit_list.split(',')))
    else:
        from .sheet import sheet
        pal = palette()
        S = style()
        for u in a.units:
            dirs = [d for d in DIRS if ref_path(u, d)]
            P = render_passes(u, dirs)
            factor = P['_ppu'] / P['_scale']
            row = []
            os.makedirs(os.path.join(ROOT, 'out', u), exist_ok=True)
            for d in dirs:
                spr, _ = to_sprite(small(P[d], factor), pal, S['fringe'], S['threshold'])
                p = os.path.join(ROOT, 'out', u, 'shaded.%s.png' % d)
                spr.save(p)
                row += [('game ' + d, ref_path(u, d)), ('shaded ' + d, p)]
            sheet([row], scale=4).save(os.path.join(ROOT, 'out', u, 'shaded.png'))
            print(os.path.join(ROOT, 'out', u, 'shaded.png'))


if __name__ == '__main__':
    main()
