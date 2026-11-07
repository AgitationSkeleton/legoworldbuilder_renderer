"""The info panel's portraits as the game's were made: a period ray tracer's light, composited from
passes and fitted to the game's portraits.

The portraits' light is not a modern renderer's: point lights with hard shadows (the duck's beak
dark beneath), a white rim from a light behind (the buggy's tyres), highlights on the plastic, glass
you see the inside through.  So each portrait is rendered as passes (blender/wbsprite.py,
run_passes) from its fitted camera (config/hero/<unit>.json): which LDraw colour each pixel is;
on white plastic, each of several key lights alone (hard shadows), each alone on shine alone (its
highlights), each of several rim lights from behind, and the sky; and, for a model with glass,
the same again with the glass left out (what is behind it).  Here they are put together:

    v   = (ambient*A + key*K[i] + fill*K[j] + rim*R[m]) ** gamma
    rgb = palette[colour] * v + shine*S[i] + rim_white*R[m]
    glass: rgb = behind * (1 - opacity) + rgb * opacity

on white, its edge smoothed as the game's are.  The fit: the passes laid on each portrait of the
game's (brought to its size), each inner pixel a sample; which lights, how strong, and the
portraits' own palette (config/hero_palette.json), in turn.

    python -m wbrender.heroshade fit [--units duck,frog,...]
    python -m wbrender.heroshade show UNIT [UNIT ...]       # composited beside the game's
"""
import argparse
import json
import os

import numpy as np
from PIL import Image

from . import blender
from .units import UNITS, ROOT, model_path, hero_ref
from .shade import simplex, fill_codes

PAL = os.path.join(ROOT, 'config', 'hero_palette.json')
KEYS = [(e, a) for e in (10, 35, 60) for a in (-150, -100, -50, 0, 50, 100, 150)]   # key and fill lights, (elevation, azimuth): all round
RIMS = [(e, a) for e in (15, 40) for a in (140, 180, 220)]                        # lights from behind the model
ROUGH = 0.45
NEUTRAL = ('0', '256', '15', '7', '8', '71', '72', '503', '151')       # black, rubber, white, the greys
LIGHT0 = {'ambient': 0.35, 'key': 1.2, 'fill': 0.35, 'rim': 0.3, 'gamma': 0.8, 'shine': 0.35, 'rim_white': 0.5,
          'opacity': 0.45, 'key_index': 3, 'fill_index': 9, 'rim_index': 1}


def palette():
    return json.load(open(PAL, encoding='utf-8')) if os.path.exists(PAL) else {'colours': {}, 'light': dict(LIGHT0)}


def camera(unit, consistent=False):
    from .render import hero_camera
    return hero_camera(unit, consistent)


def render(unit, size=384, samples=32, consistent=False, work=None):
    """The unit's portrait passes at render size: codes, legend, alpha, A, K[], S[], R[], and behind (the same
    without the glass) if it has glass."""
    cam = camera(unit, consistent)
    work = work or os.path.join(ROOT, 'work', 'heropasses', unit + ('_c' if consistent else ''))
    os.makedirs(work, exist_ok=True)
    passes = [('k%d' % i, {'elevation': e, 'azimuth': a, 'strength': 1}) for i, (e, a) in enumerate(KEYS)]
    passes += [('s%d' % i, {'elevation': e, 'azimuth': a, 'strength': 1}, 'spec:%g' % ROUGH) for i, (e, a) in enumerate(KEYS)]
    passes += [('r%d' % i, {'elevation': e, 'azimuth': a, 'strength': 1}) for i, (e, a) in enumerate(RIMS)]
    passes += [('ambient', None)]
    params = {'hero': True, 'hero_elevation': cam['elevation'], 'hero_lens': cam['lens'], 'hero_roll': cam.get('roll', 0.0), 'passes': passes, 'softness': 0.3, 'height_pass': False}
    model = model_path(unit, hero=not consistent)
    # (made already for this camera and model: read again, not rendered again)
    stamp = json.dumps({'cam': cam, 'model': model, 'size': size, 'samples': samples, 'keys': KEYS, 'rims': RIMS, 'rough': ROUGH}, sort_keys=True)
    done = os.path.join(work, 'made.json')
    if os.path.exists(done) and json.load(open(done)).get('stamp') == stamp:
        legend = json.load(open(done))['legend']
    else:
        shots = [{'path': os.path.join(work, 'full'), 'heading': cam['heading']}]
        r = blender.run({'model': model, 'mode': 'passes', 'size': size, 'samples': samples, 'shots': shots, 'studs': 'full', 'params': params})
        legend = r['legend']
        if [v['code'] for v in legend.values() if (v.get('alpha') or 1) < 0.99]:
            glass_ = [v['code'] for v in legend.values() if (v.get('alpha') or 1) < 0.99]
            shots = [{'path': os.path.join(work, 'behind'), 'heading': cam['heading'], 'hide_codes': glass_}]
            blender.run({'model': model, 'mode': 'passes', 'size': size, 'samples': samples, 'shots': shots, 'studs': 'full', 'params': params})
        json.dump({'stamp': stamp, 'legend': legend}, open(done, 'w'))
    glass = [v['code'] for v in legend.values() if (v.get('alpha') or 1) < 0.99]
    out = read(os.path.join(work, 'full'), legend)
    if glass:
        out['behind'] = read(os.path.join(work, 'behind'), legend)
    out['glass'] = glass
    return out


def smooth(a):
    """A shine pass's noise taken out (few samples, small bright highlights): a 5-pixel median, then a
    slight blur -- the period's highlights are soft spots, not sparkles."""
    a = np.asarray(a, np.float32)
    p = np.pad(a, 2, mode='edge')
    h, w = a.shape
    a = np.median(np.stack([p[y:y + h, x:x + w] for y in range(5) for x in range(5)]), 0)
    g = np.exp(-0.5 * (np.arange(-3, 4) / 1.2) ** 2)
    g /= g.sum()
    p = np.pad(a, 3, mode='edge')
    a = sum(g[i] * p[i:i + h, 3:3 + w] for i in range(7))
    p = np.pad(a, ((0, 0), (3, 3)), mode='edge')
    return np.float32(sum(g[i] * p[:, i:i + w] for i in range(7)))


def read(base, legend):
    idim = np.asarray(Image.open(base + '.id.png').convert('RGBA'))
    codes = np.full(idim.shape[:2], '', dtype=object)
    for key, v in legend.items():
        rgb = tuple(int(x) for x in key.split(','))
        codes[(idim[..., 0] == rgb[0]) & (idim[..., 1] == rgb[1]) & (idim[..., 2] == rgb[2]) & (idim[..., 3] > 0)] = v['code']

    def lum(name):
        a = np.asarray(Image.open(base + '.' + name + '.png'))
        return a.astype(np.float32) / (65535.0 if a.dtype == np.uint16 else 255.0)
    A = lum('ambient')
    # (suns' passes brought to the sky's: a sun of strength 1 gives white plastic 0.8/pi facing it, the sky 0.8)
    pi = np.pi
    return {'codes': codes, 'legend': {v['code']: v['rgb'] for v in legend.values()}, 'alpha': A[..., 3], 'A': A[..., 0] / 0.8,
            'K': [lum('k%d' % i)[..., 0] * pi / 0.8 for i in range(len(KEYS))], 'S': [smooth(lum('s%d' % i)[..., 0]) * pi for i in range(len(KEYS))],
            'R': [lum('r%d' % i)[..., 0] * pi / 0.8 for i in range(len(RIMS))]}


# ---------- brought to the portrait's box ----------

def boxed(p, box, margin=1, k=None, at=None):
    """The passes cropped to the model, brought into box (w, h) as the portrait is (render.on_white), each
    field averaged where the model covers, the codes by majority; and where in the box they lie.  Or
    at the scale k and place at (y, x) given: registered onto a portrait of the game's (registered())."""
    al = p['alpha']
    ys, xs = np.nonzero(al > 0.02)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    h, w = y1 - y0, x1 - x0
    if k is None:
        k = min((box[0] - 2 * margin) / w, (box[1] - 2 * margin) / h)
    nw, nh = max(1, round(w * k)), max(1, round(h * k))

    def field(f):
        num = Image.fromarray(np.float32(f[y0:y1, x0:x1] * al[y0:y1, x0:x1]), 'F').resize((nw, nh), Image.BOX)
        den = Image.fromarray(np.float32(al[y0:y1, x0:x1]), 'F').resize((nw, nh), Image.BOX)
        return np.asarray(num) / np.maximum(np.asarray(den), 1e-6), np.asarray(den)
    A, cov = field(p['A'])
    out = {'cov': cov, 'A': A, 'K': [field(x)[0] for x in p['K']], 'S': [field(x)[0] for x in p['S']], 'R': [field(x)[0] for x in p['R']],
           'legend': p['legend'], 'at': at or ((box[1] - nh) // 2, (box[0] - nw) // 2)}     # (centred in the box)
    names = [c for c in np.unique(p['codes']) if c]
    best = np.zeros((nh, nw), np.float32)
    codes = np.full((nh, nw), '', dtype=object)
    for c in names:
        cv = np.asarray(Image.fromarray(np.float32(p['codes'][y0:y1, x0:x1] == c), 'F').resize((nw, nh), Image.BOX))
        codes[cv > best] = c
        best = np.maximum(best, cv)
    out['codes'] = fill_codes(codes, cov)
    if p.get('shadow'):
        out['shadow'] = {k_: field(v)[0] for k_, v in p['shadow'].items()}
    if p.get('rcodes') is not None:
        # (what each pixel reflects: the part by majority, as the codes; how much, and the world's direction, averaged)
        rb = np.zeros((nh, nw), np.float32)
        rcs = np.full((nh, nw), '', dtype=object)
        for c in [c for c in np.unique(p['rcodes']) if c]:
            cv = np.asarray(Image.fromarray(np.float32(p['rcodes'][y0:y1, x0:x1] == c), 'F').resize((nw, nh), Image.BOX))
            rcs[cv > rb] = c
            rb = np.maximum(rb, cv)
        out['rcodes'] = rcs
        out['robj'] = field(p['robj'])[0]
        rd = np.stack([field(p['rdir'][..., i])[0] for i in range(3)], -1)
        out['rdir'] = rd / np.maximum(np.linalg.norm(rd, axis=-1, keepdims=True), 1e-6)
    if 'N' in p:
        # (surface directions: averaged, then made unit again)
        n = np.stack([field(p['N'][..., i])[0] for i in range(3)], -1)
        out['N'] = n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
    if 'behind' in p:
        # (behind the glass: the same crop and size, so that it lies under the glass where it should)
        b = p['behind']
        out['behind'] = {'A': field(b['A'])[0], 'K': [field(x)[0] for x in b['K']], 'S': [field(x)[0] for x in b['S']],
                         'R': [field(x)[0] for x in b['R']], 'legend': b['legend']}
        if 'N' in b:
            n = np.stack([field(b['N'][..., i])[0] for i in range(3)], -1)
            out['behind']['N'] = n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
        if b.get('shadow'):
            out['behind']['shadow'] = {k_: field(v)[0] for k_, v in b['shadow'].items()}
        bc = np.full((nh, nw), '', dtype=object)
        best = np.zeros((nh, nw), np.float32)
        for c in [c for c in np.unique(b['codes']) if c]:
            cv = np.asarray(Image.fromarray(np.float32(b['codes'][y0:y1, x0:x1] == c), 'F').resize((nw, nh), Image.BOX))
            bc[cv > best] = c
            best = np.maximum(best, cv)
        out['behind']['codes'] = bc
    out['glass'] = p.get('glass', [])
    return out


def base_of(code, legend, pal):
    c = pal['colours'].get(code)
    if c is None:
        c = legend.get(code) or [128, 128, 128]
    return np.array(c, np.float32) / 255.0


def light_rgb(s, pal, L):
    i, j, m = int(L['key_index']), int(L['fill_index']), int(L['rim_index'])
    v = np.maximum(0, L['ambient'] * s['A'] + L['key'] * s['K'][i] + L['fill'] * s['K'][j] + L['rim'] * s['R'][m]) ** L['gamma'] / L.get('norm', 1.0)
    rgb = np.zeros(s['A'].shape + (3,), np.float32)
    for code in np.unique(s['codes']):
        if code:
            msk = s['codes'] == code
            rgb[msk] = base_of(code, s['legend'], pal)[None, :] * v[msk][:, None]
    add = L['shine'] * s['S'][i] + L['rim_white'] * s['R'][m]
    return rgb + add[..., None]


def composite(s, pal, L=None):
    """RGB 0..1 on white, the portrait's size."""
    L = L or pal['light']
    rgb = light_rgb(s, pal, L)
    if s.get('behind') is not None and s['glass']:
        back = light_rgb(s['behind'], pal, L)
        g = np.isin(s['codes'], s['glass'])
        rgb[g] = back[g] * (1 - L['opacity']) + rgb[g] * L['opacity']
    rgb = np.clip(rgb, 0, 1)
    cov = s['cov'][..., None]
    return rgb * cov + (1 - cov)


def picture(s, pal, box, L=None):
    rgb = composite(s, pal, L)
    out = np.ones((box[1], box[0], 3), np.float32)
    h, w = rgb.shape[:2]
    y, x = s['at']
    out[y:y + h, x:x + w] = rgb[:box[1] - y, :box[0] - x]
    return Image.fromarray(np.uint8(np.clip(out * 255 + 0.5, 0, 255)), 'RGB')


# ---------- fitting ----------

def registered(p, ref):
    """The scale and place (k, (y, x)) laying the render's outline best on the game's portrait (RGBA):
    the portraits are the same build from the same camera, but framed by the game's own hand, a pixel
    or few from where fitting the box puts them -- and a pixel off, light and shade are compared
    across the edges of faces."""
    R = np.asarray(ref.convert('RGBA'), np.float32) / 255.0
    ref_alpha = (R[..., 3] > 0.5) & (R[..., :3].min(-1) < 0.96)
    al = p['alpha']
    ys, xs = np.nonzero(al > 0.02)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    ry, rx = np.nonzero(ref_alpha)
    k0 = min((ry.max() - ry.min() + 1) / (y1 - y0), (rx.max() - rx.min() + 1) / (x1 - x0))
    best = None
    for f in np.linspace(0.94, 1.08, 15):
        k = k0 * f
        w, h = max(1, round((x1 - x0) * k)), max(1, round((y1 - y0) * k))
        m = np.asarray(Image.fromarray(np.float32(al[y0:y1, x0:x1]), 'F').resize((w, h), Image.BOX)) > 0.5
        for dy in range(ry.min() - 5, ry.min() + 6):
            for dx in range(rx.min() - 5, rx.min() + 6):
                if dy < 0 or dx < 0 or dy + h > ref_alpha.shape[0] or dx + w > ref_alpha.shape[1]:
                    continue
                inter = (ref_alpha[dy:dy + h, dx:dx + w] & m).sum()
                sc = inter / (ref_alpha.sum() + m.sum() - inter)
                if best is None or sc > best[0]:
                    best = (sc, k, (dy, dx))
    return best


def samples(unit, size=384, samples_n=32):
    im = Image.open(hero_ref(unit))
    ref = im.convert('RGB')
    p = render(unit, size, samples_n)
    reg = registered(p, im)
    if reg and reg[0] > 0.8:
        s = boxed(p, ref.size, k=reg[1], at=reg[2])
    else:
        s = boxed(p, ref.size)
    R = np.asarray(ref, np.float32) / 255.0
    h, w = s['cov'].shape
    y, x = s['at']
    Rc = R[y:y + h, x:x + w]
    inner = s['cov'] > 0.98
    # (inside one colour's patch in the render, and not white in the game's: the same surface, mostly)
    c = s['codes']
    same = np.zeros_like(inner)
    same[1:-1, 1:-1] = (c[1:-1, 1:-1] == c[:-2, 1:-1]) & (c[1:-1, 1:-1] == c[2:, 1:-1]) & (c[1:-1, 1:-1] == c[1:-1, :-2]) & (c[1:-1, 1:-1] == c[1:-1, 2:])
    keep = inner & same & (Rc.min(-1) < 0.97) & (c != '') & ~np.isin(c, s['glass'])
    return s, Rc, keep


def fit(units, iterations=3, by_pixel=True):
    data = []
    for u in units:
        try:
            data.append((u,) + samples(u))
            print('  %s: %d samples' % (u, data[-1][3].sum()), flush=True)
        except FileNotFoundError as e:
            print('  %s: %s' % (u, e))
    # (from the neutral start, not the last fit's: a light at its bounds -- all sky, no key -- is a
    # well the search does not climb out of)
    L = dict(LIGHT0, norm=1.0)
    names = sorted({c for _, s, _, k in data for c in np.unique(s['codes'][k])})

    def lightv(s, Lx):
        i, j, m = int(Lx['key_index']), int(Lx['fill_index']), int(Lx['rim_index'])
        return np.maximum(0, Lx['ambient'] * s['A'] + Lx['key'] * s['K'][i] + Lx['fill'] * s['K'][j] + Lx['rim'] * s['R'][m]) ** Lx['gamma'] / Lx.get('norm', 1.0)

    def colours_for(Lx):
        num, cnt = {}, {}
        ratios = {c: [] for c in names}
        for _, s, Rc, k in data:
            v = lightv(s, Lx)
            add = Lx['shine'] * s['S'][int(Lx['key_index'])] + Lx['rim_white'] * s['R'][int(Lx['rim_index'])]
            for c in names:
                m = k & (s['codes'] == c) & (v > 0.15) & (add < 0.1)
                if m.any():
                    ratios[c].append(((Rc[m] - add[m][:, None]) / v[m][:, None], Rc[m] >= 0.97, v[m]))
        out = {}
        for c, r in ratios.items():
            if not r or sum(len(x[0]) for x in r) < 20:
                continue
            q = np.concatenate([x[0] for x in r])
            clipped = np.concatenate([x[1] for x in r])
            v = np.concatenate([x[2] for x in r])
            col = np.zeros(3, np.float32)
            for ch in range(3):
                ok = ~clipped[:, ch]
                if ok.mean() > 0.3:
                    col[ch] = np.median(q[ok, ch])
                else:
                    # (clipped nearly everywhere: bright enough to clip even in the shade -- at least
                    # white over the dimmer light it is clipped under)
                    col[ch] = 1.0 / max(np.quantile(v[clipped[:, ch]], 0.1), 0.4)
            out[c] = np.clip(col, 0, 2.5)
        return out

    def error(Lx, cols):
        """The colours' spreads, channel by channel (as above: quantiles, not pixels), 0..255."""
        P = {'colours': {c: list(v * 255) for c, v in cols.items()}, 'light': Lx}
        e = []
        if by_pixel:
            for _, s, Rc, k in data:
                rgb = np.clip(light_rgb(s, P, Lx), 0, 1)
                e.append(np.abs(rgb[k] - Rc[k]).mean(1))
            e = np.sort(np.concatenate(e))
            return float(e[: int(len(e) * 0.9)].mean() * 255)
        for _, s, Rc, k in data:
            rgb = np.clip(light_rgb(s, P, Lx), 0, 1)
            for c in names:
                m = k & (s['codes'] == c)
                if m.sum() < 30:
                    continue
                e.append(np.abs(np.quantile(rgb[m], Q, axis=0) - np.quantile(Rc[m], Q, axis=0)).mean())
        return float(np.mean(e) * 255)

    # 1. The light rig from the shading alone: within each colour, how much brighter or darker each pixel
    #    is than the colour's middle (log luminance less its median), which the palette does not touch.
    #    Each colour read in its telling channel: the brightest not clipped. The game's renders are
    #    overexposed, channel by channel -- a yellow's red is 255 on every face, lit or shaded, and
    #    only its green tells the light -- and the dark colours (the tyres) are left to the shine and
    #    rim: on a black, a highlight is all the variation there is.
    lum_ref = []
    for _, s, Rc, k in data:
        lr = np.zeros(k.shape, np.float32)
        k2 = np.zeros_like(k)
        for c in names:
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
            lr[mm] = np.log(np.maximum(Rc[mm][:, best[0]], 0.02))
            k2 |= mm
        lum_ref.append((lr, s, k2))

    # (each colour's shading as a spread -- its quantiles about its median -- not pixel by pixel: the
    # game's builds lie a pixel or few off the recreations', and a pixel-by-pixel fit then likes
    # flat light best, the mean of misplaced light and shade)
    Q = np.linspace(0.04, 0.96, 24)

    def spreads(vals, ks):
        out = []
        for v, (s, k) in zip(vals, ks):
            for c in names:
                m = k & (s['codes'] == c)
                if m.sum() < 30:
                    continue
                q = np.quantile(v[m], Q)
                out.append(q - np.median(v[m]))
        return out
    ref_spread = spreads([lr for lr, _, _ in lum_ref], [(s, k) for _, s, k in lum_ref])

    def shading_error(Lx):
        if by_pixel:
            # (registered: pixel by pixel, each colour's light and shade about its median)
            e = []
            for lr, s, k in lum_ref:
                v = np.log(np.maximum(lightv(s, Lx), 0.02))
                for c in names:
                    m = k & (s['codes'] == c)
                    if m.sum() < 8:
                        continue
                    e.append(np.abs((lr[m] - np.median(lr[m])) - (v[m] - np.median(v[m]))))
            e = np.sort(np.concatenate(e))
            return float(e[: int(len(e) * 0.9)].mean())
        vals = [np.log(np.maximum(lightv(s, Lx), 0.02)) for _, s, _ in lum_ref]
        mine = spreads(vals, [(s, k) for _, s, k in lum_ref])
        return float(np.mean([np.abs(a - b).mean() for a, b in zip(ref_spread, mine)]))

    best = None
    for i in range(len(KEYS)):
        for m_ in range(len(RIMS)):
            Lx = dict(L, key_index=i, rim_index=m_)
            e = shading_error(Lx)
            if best is None or e < best[0]:
                best = (e, i, m_)
    L['key_index'], L['rim_index'] = best[1], best[2]
    best = None
    for j_ in range(len(KEYS)):
        e = shading_error(dict(L, fill_index=j_))
        if best is None or e < best[0]:
            best = (e, j_)
    L['fill_index'] = best[1]
    print('lights: key %s, fill %s, rim %s (shading error %.3f)' % (KEYS[int(L['key_index'])], KEYS[int(L['fill_index'])], RIMS[int(L['rim_index'])], best[0]), flush=True)
    keys = ['ambient', 'key', 'fill', 'rim', 'gamma']
    bounds = [(0, 1.5), (0, 4), (0, 3), (0, 3), (0.4, 2)]
    for it in range(iterations):
        L = simplex(lambda x: shading_error(dict(L, **dict(zip(keys, x)))), [L[k] for k in keys], bounds, keys, L)
        print('shading round %d: %.3f  %s' % (it + 1, shading_error(L), {k: round(L[k], 3) for k in keys}), flush=True)
    # (the light brought to 1 on the middle of the lit plastic, so the palette is the plastic's own colour,
    # and colours not fitted -- glass, those of no portrait fitted -- take the LDraw colour at its light)
    L['norm'] = 1.0
    L['norm'] = float(np.median(np.concatenate([lightv(s, L)[k] for _, s, _, k in data])))
    # 2. the palette under that light; 3. the white the plastic shines and the rim adds, on what is left
    L['shine'], L['rim_white'] = 0.0, 0.0
    cols = colours_for(L)
    keys2 = ['shine', 'rim_white']
    L = simplex(lambda x: error(dict(L, **dict(zip(keys2, x))), cols), [0.2, 0.2], [(0, 1.2), (0, 2)], keys2, L)
    print('shine %.3f, rim white %.3f: error %.1f' % (L['shine'], L['rim_white'], error(L, colours_for(L))), flush=True)
    cols = colours_for(L)
    # (the greys and blacks grey: the game's are, and a few pixels of the red beside a tyre warm them)
    for c in NEUTRAL:
        if c in cols:
            cols[c] = np.full(3, cols[c].mean())
    out = {'colours': {c: [int(round(x * 255)) for x in v] for c, v in sorted(cols.items())}, 'light': L,
           'lights': {'key': KEYS[int(L['key_index'])], 'fill': KEYS[int(L['fill_index'])], 'rim': RIMS[int(L['rim_index'])]}, 'fitted_on': units}
    json.dump(out, open(PAL, 'w', encoding='utf-8'), indent=1)
    print('written to config/hero_palette.json')
    return out


def render_portrait(unit, out_path, consistent=False):
    """<sprite>.hero.png, composited (the box the game's portrait has, or the usual)."""
    from .render import HERO_SIZE
    ref = hero_ref(unit)
    box = Image.open(ref).size if ref and not consistent else HERO_SIZE
    s = boxed(render(unit, consistent=consistent), box)
    picture(s, palette(), box).save(out_path)
    return out_path


def references(least=0.8):
    """The portraits the light is measured on: those of the unit's own build, posed as the game's -- their
    outline matching the game's portrait (config/hero/<unit>.json score) at least so well, the camera
    fitted, not set by eye.  The buildings are left out: the game's are drawn flatter, a light of their own.
    (A portrait of another build, or posed otherwise -- the defender, the treebot -- lights other
    surfaces than the game's, and would teach the light wrong.)"""
    import glob
    from .herofit import group
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, 'config', 'hero', '*.json'))):
        h = json.load(open(f))
        u = h.get('unit')
        if isinstance(u, str) and u in UNITS and not h.get('pinned') and (h.get('score') or 0) >= least and group(u) == 'unit' and not UNITS[u].get('hero_as'):
            out.append(u)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('what', choices=['fit', 'show'])
    ap.add_argument('units', nargs='*')
    ap.add_argument('--units', dest='unit_list', help='the portraits to fit on (by default: references())')
    ap.add_argument('--consistent', action='store_true')
    a = ap.parse_args()
    if a.what == 'fit':
        fit(a.units or (a.unit_list.split(',') if a.unit_list else references()))
        return
    from .sheet import sheet
    rows = []
    for u in a.units:
        os.makedirs(os.path.join(ROOT, 'out', u), exist_ok=True)
        p = render_portrait(u, os.path.join(ROOT, 'out', u, 'heroshade%s.png' % ('_c' if a.consistent else '')), a.consistent)
        rows.append(([('game', hero_ref(u))] if hero_ref(u) else []) + [('render', p)])
    sheet(rows, scale=3).save(os.path.join(ROOT, 'out', 'heroshade.png'))
    print(os.path.join(ROOT, 'out', 'heroshade.png'))


if __name__ == '__main__':
    main()
