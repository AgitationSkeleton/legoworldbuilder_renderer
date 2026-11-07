"""Where the game's portrait lights stood, read off its portraits: each portrait's render from its
fitted camera (the colours' ids, the sky's light, each pixel's surface direction), registered onto
the game's portrait to the pixel, then the game's brightness -- each colour's own, as against its
median -- gathered by surface direction: a picture of the light on a ball, as the game lit it.

    python -m wbrender.lightprobe duck buggy dirtbuggy

writes out/lightprobe.png (per unit and all together: the ball lit as the game's portraits are, and
how many pixels each direction had) and work/lightprobe/<unit>.npz (the registered samples)."""
import argparse
import json
import os

import numpy as np
from PIL import Image

from . import blender
from .units import ROOT, model_path, hero_ref
from .heroshade import camera

N = 15   # the ball's cells across


def render(unit, size=384, samples=16):
    cam = camera(unit)
    work = os.path.join(ROOT, 'work', 'lightprobe', unit)
    os.makedirs(work, exist_ok=True)
    params = {'hero': True, 'hero_elevation': cam['elevation'], 'hero_lens': cam['lens'], 'hero_roll': cam.get('roll', 0.0), 'passes': [('ambient', None)],
              'softness': 0.3, 'height_pass': False, 'normal_pass': True}
    r = blender.run({'model': model_path(unit, hero=True), 'mode': 'passes', 'size': size, 'samples': samples,
                     'shots': [{'path': os.path.join(work, 'p'), 'heading': cam['heading']}], 'studs': 'full', 'params': params})
    base = os.path.join(work, 'p')
    idim = np.asarray(Image.open(base + '.id.png').convert('RGBA'))
    codes = np.full(idim.shape[:2], '', dtype=object)
    for key, v in r['legend'].items():
        rgb = tuple(int(x) for x in key.split(','))
        codes[(idim[..., 0] == rgb[0]) & (idim[..., 1] == rgb[1]) & (idim[..., 2] == rgb[2]) & (idim[..., 3] > 0)] = v['code']
    nim = np.asarray(Image.open(base + '.normal.png'))
    n = nim[..., :3].astype(np.float32) / (65535.0 if nim.dtype == np.uint16 else 255.0) * 2 - 1
    alpha = nim[..., 3].astype(np.float32) / (65535.0 if nim.dtype == np.uint16 else 255.0)
    glass = [v['code'] for v in r['legend'].values() if (v.get('alpha') or 1) < 0.99]
    return codes, n, alpha, glass


def register(alpha, ref_alpha):
    """The render's crop and scale onto the game's portrait: (scale, dy, dx) maximising the outlines' overlap."""
    ys, xs = np.nonzero(alpha > 0.5)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    ry, rx = np.nonzero(ref_alpha)
    k0 = min((ry.max() - ry.min() + 1) / (y1 - y0), (rx.max() - rx.min() + 1) / (x1 - x0))
    best = None
    for f in np.linspace(0.94, 1.06, 13):
        k = k0 * f
        w, h = max(1, round((x1 - x0) * k)), max(1, round((y1 - y0) * k))
        m = np.asarray(Image.fromarray(np.uint8(alpha[y0:y1, x0:x1] > 0.5) * 255).resize((w, h), Image.BILINEAR)) > 127
        for dy in range(ry.min() - 4, ry.min() + 5):
            for dx in range(rx.min() - 4, rx.min() + 5):
                if dy < 0 or dx < 0 or dy + h > ref_alpha.shape[0] or dx + w > ref_alpha.shape[1]:
                    continue
                R = ref_alpha[dy:dy + h, dx:dx + w]
                inter = (R & m).sum()
                union = ref_alpha.sum() + m.sum() - inter
                sc = inter / union
                if best is None or sc > best[0]:
                    best = (sc, k, dy, dx, w, h)
    return best, (y0, y1, x0, x1)


def samples(unit):
    codes, n, alpha, glass = render(unit)
    ref = Image.open(hero_ref(unit)).convert('RGBA')
    R = np.asarray(ref, np.float32) / 255.0
    rgb = R[..., :3]
    ref_alpha = (R[..., 3] > 0.5) & (rgb.min(-1) < 0.96)
    (sc, k, dy, dx, w, h), (y0, y1, x0, x1) = register(alpha, ref_alpha)
    print('  %s: registered, overlap %.3f' % (unit, sc), flush=True)

    def put(f, nearest=False):
        im = Image.fromarray(np.float32(f[y0:y1, x0:x1]), 'F').resize((w, h), Image.NEAREST if nearest else Image.BOX)
        return np.asarray(im)
    nn = np.stack([put(n[..., i]) for i in range(3)], -1)
    nn /= np.maximum(np.linalg.norm(nn, axis=-1, keepdims=True), 1e-6)
    names = [c for c in np.unique(codes) if c]
    cc = np.full((h, w), '', dtype=object)
    best = np.zeros((h, w), np.float32)
    for c in names:
        cv = put(np.float32(codes == c))
        cc[cv > best] = c
        best = np.maximum(best, cv)
    pure = best > 0.99
    # (each pixel: the game's colour where the render shows one colour's surface well inside, not glass)
    inner = np.zeros((h, w), bool)
    inner[1:-1, 1:-1] = pure[1:-1, 1:-1] & pure[:-2, 1:-1] & pure[2:, 1:-1] & pure[1:-1, :-2] & pure[1:-1, 2:]
    G = rgb[dy:dy + h, dx:dx + w]
    keep = inner & ~np.isin(cc, glass) & (cc != '') & ref_alpha[dy:dy + h, dx:dx + w]
    os.makedirs(os.path.join(ROOT, 'work', 'lightprobe'), exist_ok=True)
    np.savez(os.path.join(ROOT, 'work', 'lightprobe', unit + '.npz'), codes=cc[keep].astype(str), n=nn[keep], rgb=G[keep])
    return cc[keep].astype(str), nn[keep], G[keep]


def ball(codes, n, rgb):
    """Each colour's luminance over its median, gathered by direction: (N, N) median, and counts."""
    lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    rel = np.zeros_like(lum)
    for c in np.unique(codes):
        m = codes == c
        if m.sum() >= 20:
            rel[m] = np.log(np.maximum(lum[m], 0.02)) - np.median(np.log(np.maximum(lum[m], 0.02)))
        else:
            rel[m] = np.nan
    ix = np.clip(((n[:, 0] + 1) / 2 * N).astype(int), 0, N - 1)
    iy = np.clip(((1 - n[:, 1]) / 2 * N).astype(int), 0, N - 1)
    med = np.full((N, N), np.nan)
    cnt = np.zeros((N, N), int)
    for y in range(N):
        for x in range(N):
            m = (iy == y) & (ix == x) & ~np.isnan(rel)
            cnt[y, x] = m.sum()
            if m.sum() >= 4:
                med[y, x] = np.median(rel[m])
    return med, cnt


def picture(med, cnt, cell=14):
    im = np.full((N * cell, N * cell, 3), 90, np.uint8)
    for y in range(N):
        for x in range(N):
            if np.isnan(med[y, x]):
                continue
            v = np.clip(0.5 + med[y, x] / 2.0, 0, 1)
            im[y * cell:(y + 1) * cell, x * cell:(x + 1) * cell] = int(v * 255)
    return Image.fromarray(im)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('units', nargs='+')
    a = ap.parse_args()
    allc, alln, allr = [], [], []
    pics = []
    for u in a.units:
        c, n, g = samples(u)
        allc.append(c), alln.append(n), allr.append(g)
        med, cnt = ball(c, n, g)
        pics.append((u, picture(med, cnt)))
    med, cnt = ball(np.concatenate(allc), np.concatenate(alln), np.concatenate(allr))
    pics.append(('all', picture(med, cnt)))
    from PIL import ImageDraw
    W = sum(p.width + 10 for _, p in pics)
    out = Image.new('RGB', (W, pics[0][1].height + 16), (110, 150, 190))
    d = ImageDraw.Draw(out)
    x = 0
    for name, p in pics:
        out.paste(p, (x, 16))
        d.text((x + 2, 2), name, fill='black')
        x += p.width + 10
    out.save(os.path.join(ROOT, 'out', 'lightprobe.png'))
    np.set_printoptions(precision=2, suppress=True, linewidth=200)
    print('all: log brightness against each colour\'s median, by direction (x right, y up; rows top to bottom)')
    print(med)
    print(cnt)


if __name__ == '__main__':
    main()
