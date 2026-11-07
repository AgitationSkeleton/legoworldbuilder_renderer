"""The README's comparison images (docs/showcase/): the game's pictures beside the renders.

    python tools/showcase.py

Reads reference/ (the game's, from your copy) and out/ (the renders)."""
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from wbrender.units import UNITS, hero_ref  # noqa: E402

BG = (110, 150, 190)
OUT = os.path.join(HERE, 'docs', 'showcase')


def label(d, xy, t):
    d.text(xy, t, fill=(0, 0, 0))


def out(u, name):
    return os.path.join(HERE, 'out', u, name)


def pairs_sheet(pairs, path, cols=2, S=2):
    """pairs: [(caption, left image, right image)] side by side, cols to a row."""
    cw, ch = 2 * 110 * S + 24, 130 * S + 22
    rows = (len(pairs) + cols - 1) // cols
    c = Image.new('RGB', (cols * cw + 8, rows * ch + 4), BG)
    d = ImageDraw.Draw(c)
    for i, (cap, a, b) in enumerate(pairs):
        x, y = (i % cols) * cw + 6, (i // cols) * ch + 4
        label(d, (x, y), cap)
        if a is not None:
            c.paste(a.resize((a.width * S, a.height * S), Image.NEAREST), (x, y + 16))
        c.paste(b.resize((b.width * S, b.height * S), Image.NEAREST), (x + 110 * S + 10, y + 16))
    c.save(path)


def main():
    os.makedirs(OUT, exist_ok=True)
    # the portraits
    us = ['duck', 'buggy', 'dirtbuggy', 'fish', 'frog', 'snail', 'dozer', 'dumptruck', 'speedboat', 'tugboat']
    pairs_sheet([('%s: game | render' % u, Image.open(hero_ref(u)).convert('RGB'),
                  Image.open(out(u, UNITS[u]['sprite'] + '.hero.png')).convert('RGB')) for u in us],
                os.path.join(OUT, 'portraits.png'))
    # the map sprites: the game's above, the render's below
    S = 3
    rows = []
    for u in ['duck', 'buggy', 'dirtbuggy', 'dozer', 'dumptruck', 'frog', 'snail', 'speedboat']:
        sp, still = UNITS[u]['sprite'], UNITS[u].get('still', '')
        row = []
        for dd in ('right', 'left', 'up', 'down'):
            a = os.path.join(HERE, 'reference', '%s.%s%s.png' % (sp, dd, still))
            b = out(u, '%s.%s%s.png' % (sp, dd, still))
            if os.path.exists(a) and os.path.exists(b):
                row.append((Image.open(a).convert('RGBA'), Image.open(b).convert('RGBA')))
        rows.append((u, row))
    W = max(sum(max(a.width, b.width) * S + 10 for a, b in r) for _, r in rows) + 110
    H = sum(max(max(a.height, b.height) for a, b in r) * S * 2 + 14 for _, r in rows) + 6
    c = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(c)
    y = 4
    for u, r in rows:
        hh = max(max(a.height, b.height) for a, b in r) * S
        label(d, (4, y + hh - 8), u)
        label(d, (4, y + hh + 4), 'game / render')
        x = 110
        for a, b in r:
            a3 = a.resize((a.width * S, a.height * S), Image.NEAREST)
            b3 = b.resize((b.width * S, b.height * S), Image.NEAREST)
            c.paste(a3, (x, y), a3)
            c.paste(b3, (x, y + hh + 4), b3)
            x += max(a3.width, b3.width) + 10
        y += hh * 2 + 14
    c.save(os.path.join(OUT, 'map_sprites.png'))
    # the new units
    parts = []
    for u, names in (('bluebird', ['right', 'left', 'up', 'down']), ('cargocopter', ['right', 'left', 'up', 'down']), ('airport', [None])):
        sp = UNITS[u]['sprite']
        sprites = [Image.open(out(u, sp + ('.' + n if n else '') + '.png')).convert('RGBA') for n in names]
        parts.append((u, sprites, Image.open(out(u, sp + '.hero.png')).convert('RGB')))
    H = sum(max(max(i.height * S for i in s_), h.height * 2) + 30 for _, s_, h in parts)
    c = Image.new('RGB', (1000, H), BG)
    d = ImageDraw.Draw(c)
    y = 4
    for u, s_, hero in parts:
        label(d, (6, y), u + ': map sprites, info panel portrait')
        x, yy = 6, y + 16
        for i in s_:
            i3 = i.resize((i.width * S, i.height * S), Image.NEAREST)
            c.paste(i3, (x, yy), i3)
            x += i3.width + 12
        c.paste(hero.resize((hero.width * 2, hero.height * 2), Image.NEAREST), (x + 20, yy))
        y += max(max(i.height * S for i in s_), hero.height * 2) + 30
    c.save(os.path.join(OUT, 'new_units.png'))
    # the consistent portraits, beside the game's portrait each stands for
    from wbrender.render import consistent_like
    pairs = []
    for u in ('buggy', 'dirtbuggy', 'freighter'):
        b = out(u, os.path.join('consistent', UNITS[u]['sprite'] + '.hero.png'))
        like = consistent_like(u)
        if os.path.exists(b):
            pairs.append(('%s: game %s | consistent' % (u, like if like != u else 'portrait'),
                          Image.open(hero_ref(like)).convert('RGB'), Image.open(b).convert('RGB')))
    pairs_sheet(pairs, os.path.join(OUT, 'consistent_portraits.png'), cols=3)
    print('written to docs/showcase/')


if __name__ == '__main__':
    main()
