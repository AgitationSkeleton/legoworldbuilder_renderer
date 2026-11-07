"""Contact sheets of sprites, scaled up with nearest-neighbour, on a backdrop: for comparing by eye.

    python -m wbrender.sheet OUT.png NAME [NAME ...] [--dir reference] [--scale 6]
NAME: a sprite's name without .png (vehicle.duck.right); a row per NAME ending in '/', e.g.
'vehicle.duck.right vehicle.duck.left /'."""
import argparse
import os
from PIL import Image, ImageDraw


def sheet(rows, scale=6, bg=(110, 150, 190, 255), pad=8, label=True):
    ims = [[(n, Image.open(p).convert('RGBA')) for n, p in row] for row in rows]
    cw = max((im.width for row in ims for _, im in row), default=1) * scale + pad
    ch = max((im.height for row in ims for _, im in row), default=1) * scale + pad + (14 if label else 0)
    out = Image.new('RGBA', (cw * max(len(r) for r in ims), ch * len(ims)), bg)
    d = ImageDraw.Draw(out)
    for r, row in enumerate(ims):
        for c, (n, im) in enumerate(row):
            out.alpha_composite(im.resize((im.width * scale, im.height * scale), Image.NEAREST), (c * cw + pad // 2, r * ch + (14 if label else 0)))
            if label:
                d.text((c * cw + 2, r * ch + 1), n[-34:], fill=(0, 0, 0, 255))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('names', nargs='+')
    ap.add_argument('--dir', action='append', default=None)
    ap.add_argument('--scale', type=int, default=6)
    a = ap.parse_args()
    dirs = a.dir or ['reference']
    rows, row = [], []
    for n in a.names + ['/']:
        if n == '/':
            if row: rows.append(row)
            row = []
            continue
        for d in dirs:
            p = n if n.endswith('.png') else os.path.join(d, n + '.png')
            if os.path.exists(p):
                row.append((os.path.basename(os.path.dirname(p)) + ':' + os.path.basename(p)[:-4] if len(dirs) > 1 else os.path.basename(p)[:-4], p))
    sheet(rows, a.scale).save(a.out)


if __name__ == '__main__':
    main()
