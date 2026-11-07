"""Every unit's model made ready (models/all/<submodel>.mpd), from JappaWakka's recreations:
the combined model of all the units, with its custom parts.

    python -m wbrender.setup_models [RECREATIONS_FOLDER]

The folder defaults to local.json's "recreations"."""
import os
import sys

from . import blender, models
from .units import UNITS, ROOT


def main():
    rec = sys.argv[1] if len(sys.argv) > 1 else blender.local()['recreations']
    io = os.path.join(rec, 'Models', 'Lego World Builder Models (with Custom Parts).io')
    out = models.write_units(io, os.path.join(ROOT, 'models', 'all'), {u['model'] for u in UNITS.values()} | {u['hero_model'] for u in UNITS.values() if u.get('hero_model')},
                             [os.path.join(rec, 'CustomParts')])
    # (where a recreation takes a liberty with the game's build: its own parts swapped, at its top level)
    for k, u in UNITS.items():
        if not u.get('replace_parts') or u.get('model_file'):
            continue
        path = os.path.join(ROOT, 'models', 'all', models.safe(u['model']) + '.mpd')
        files = models.split_files(open(path, encoding='utf-8').read())
        main, rest = files[0], files[1:]
        lines = []
        for line in main[1]:
            t = line.split()
            if len(t) >= 15 and t[0] == '1' and t[-1].lower() in u['replace_parts']:
                line = ' '.join(t[:14] + [u['replace_parts'][t[-1].lower()]])
            lines.append(line)
        open(path, 'w', encoding='utf-8', newline=chr(10)).write(chr(10).join(lines + [l for _, ls in rest for l in ls]) + chr(10))
    print('%d models in models/all' % len(out))
    missing = [k for k, u in UNITS.items() if not u.get('model_file') and not os.path.exists(os.path.join(ROOT, 'models', 'all', models.safe(u['model']) + '.mpd'))]
    if missing:
        print('not found in the recreations:', ', '.join(missing))


if __name__ == '__main__':
    main()
