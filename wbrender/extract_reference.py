"""The original game's unit sprites, for comparing renders against: read from a copy of the
LEGO World Builder HTML5 port's data (data/<game>.json and assets/<game>/bitmaps.bin, which hold
every bitmap of the original Shockwave movies), written to reference/ as PNG files named as the
game names them (vehicle.duck.right.png, vehicle.duck.water.right.png, monster.crab.down.png ...),
with reference/index.json giving each one's size and registration point.

    python -m wbrender.extract_reference PATH/TO/lego-worldbuilder-html5[-online] [--game merged]

The game's art is The LEGO Group's: reference/ is ignored by git and is never published.
"""
import argparse
import json
import os
import re

KINDS = re.compile(r'^(vehicle|monster|building)[.][a-z_0-9]+([.].+)?$|^resource[.][a-z_0-9]+([.][0-9])?$', re.I)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('port', nargs='?', help="a checkout of the LEGO World Builder HTML5 port (default: local.json's port)")
    ap.add_argument('--game', default='merged', help='merged (both games), wb1 or wb2')
    ap.add_argument('--out', default='reference')
    a = ap.parse_args()
    if not a.port:
        from .blender import local
        a.port = local()['port']
    data = json.load(open(os.path.join(a.port, 'data', a.game + '.json'), encoding='utf-8'))
    blob = open(os.path.join(a.port, 'assets', a.game, 'bitmaps.bin'), 'rb').read()
    os.makedirs(a.out, exist_ok=True)
    index = {}
    for cast in data['casts']:
        for m in cast['members'].values():
            name = m.get('name') or ''
            if m.get('type') != 'bitmap' or not m.get('png') or not KINDS.match(name):
                continue
            off, n = json.loads(m['png']) if isinstance(m['png'], str) else m['png']
            with open(os.path.join(a.out, name + '.png'), 'wb') as f:
                f.write(blob[off:off + n])
            index[name] = {'w': int(m['width']), 'h': int(m['height']), 'regX': int(m['regX']), 'regY': int(m['regY'])}
    json.dump(index, open(os.path.join(a.out, 'index.json'), 'w'), indent=1, sort_keys=True)
    print('%d sprites in %s' % (len(index), a.out))


if __name__ == '__main__':
    main()
