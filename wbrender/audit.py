"""Every rendered unit against the game's: each picture's outline match (IoU on the map, the
portrait's outline score) and colour error, worst first, and a sheet of each unit's pictures beside
the game's (out/audit/<unit>.png) with an index (out/audit/index.png, out/audit/audit.json).

    python -m wbrender.audit [UNIT ...]

A low outline match on the map is the model or the camera; a low one on the portrait is often the
game's portrait being of another build (config/units.json: hero_model, hero_as); a high colour
error with a good outline is the light or the palette."""
import argparse
import glob
import json
import os

from PIL import Image, ImageDraw

from .units import UNITS, ROOT, ref_path, hero_ref

OUT = os.path.join(ROOT, 'out')
SCALE = 2


def pictures(unit):
    """(name, game's path or None, render's path) for each of the unit's pictures."""
    u = UNITS[unit]
    folder = os.path.join(OUT, unit)
    out = []
    for d in ('right', 'left', 'up', 'down'):
        name = u['sprite'] + ('' if u.get('single') else '.' + d)
        mine = os.path.join(folder, name + '.png')
        if not os.path.exists(mine):
            mine = os.path.join(folder, name + u.get('still', '') + '.png')
        if os.path.exists(mine):
            try:
                ref = ref_path(unit, d, False)
            except Exception:
                ref = None
            out.append((d, ref if ref and os.path.exists(ref) else None, mine))
        if u.get('single'):
            break
    for kind in ('hero', 'plan'):
        mine = os.path.join(folder, u['sprite'] + '.' + kind + '.png')
        if os.path.exists(mine):
            ref = hero_ref(unit) if kind == 'hero' else os.path.join(ROOT, 'reference', u['sprite'] + '.plan.png')
            out.append((kind, ref if ref and os.path.exists(ref) else None, mine))
    return out


def on_white(p):
    im = Image.open(p).convert('RGBA')
    bg = Image.new('RGBA', im.size, 'white')
    bg.alpha_composite(im)
    return bg.convert('RGB').resize((im.width * SCALE, im.height * SCALE), Image.NEAREST)


def sheet(unit, report):
    cols = []
    for name, ref, mine in pictures(unit):
        a = on_white(ref) if ref else Image.new('RGB', (40, 40), (230, 200, 200))
        b = on_white(mine)
        cols.append((name, a, b))
    if not cols:
        return None
    w = sum(max(a.width, b.width) + 10 for _, a, b in cols) + 10
    h = max(a.height for _, a, _ in cols) + max(b.height for _, _, b in cols) + 50
    im = Image.new('RGB', (w, h), (110, 150, 190))
    d = ImageDraw.Draw(im)
    x = 10
    top = max(a.height for _, a, _ in cols) + 25
    d.text((10, 2), unit + '   (top: game, bottom: render)', fill='black')
    for name, a, b in cols:
        im.paste(a, (x, 15))
        im.paste(b, (x, top))
        r = next((v for k, v in report.items() if k.endswith('.' + name) or (name in ('right',) and k == UNITS[unit]['sprite'])), {})
        txt = '%s %s c%.0f' % (name, ('%.2f' % r.get('iou', r.get('shape', 0))) if r else '', r.get('colour', 0)) if r else name
        d.text((x, top - 12), txt, fill='black')
        x += max(a.width, b.width) + 10
    return im


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('units', nargs='*')
    a = ap.parse_args()
    units = a.units or [os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(OUT, '*', 'report.json'))]
    units = [u for u in units if u in UNITS]
    os.makedirs(os.path.join(OUT, 'audit'), exist_ok=True)
    rows = []
    for u in units:
        rp = os.path.join(OUT, u, 'report.json')
        report = json.load(open(rp)) if os.path.exists(rp) else {}
        world = [v['iou'] for v in report.values() if 'iou' in v]
        col = [v['colour'] for k, v in report.items() if 'iou' in v]
        hero = next((v for k, v in report.items() if k.endswith('.hero')), {})
        rows.append({'unit': u, 'map_iou': round(min(world), 3) if world else None, 'map_colour': round(sum(col) / len(col), 1) if col else None,
                     'hero_shape': hero.get('shape'), 'hero_colour': hero.get('colour'), 'notes': UNITS[u].get('notes', '')})
        s = sheet(u, report)
        if s:
            s.save(os.path.join(OUT, 'audit', u + '.png'))
    rows.sort(key=lambda r: (r['map_iou'] if r['map_iou'] is not None else 1))
    json.dump(rows, open(os.path.join(OUT, 'audit', 'audit.json'), 'w'), indent=1)
    print('%-14s %8s %8s %8s %8s' % ('unit', 'map iou', 'colour', 'hero', 'colour'))
    for r in rows:
        f = lambda v, p='%.2f': (p % v) if v is not None else '-'
        print('%-14s %8s %8s %8s %8s  %s' % (r['unit'], f(r['map_iou']), f(r['map_colour'], '%.0f'), f(r['hero_shape']), f(r['hero_colour'], '%.0f'), r['notes']))


if __name__ == '__main__':
    main()
