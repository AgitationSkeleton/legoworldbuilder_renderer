"""Stud.io models (.io: a zip holding the model as LDraw text, model.ldr, and any custom parts
under CustomParts/) made ready for Blender: one LDraw file per submodel, with that submodel as
its main model and every other submodel after it (the ones it uses), and the custom parts' .dat
files beside it, where the LDraw importer looks first.

    python -m wbrender.models MODEL.io [--out models/NAME] [--list]

Writes models/<io name>/<submodel>.mpd for each submodel (or only lists them with --list).
Models are other people's work: models/ is ignored by git and never published."""
import argparse
import os
import re
import zipfile


def read_io(path):
    """The .io's LDraw text (model.ldr) and its custom parts {name.dat: bytes}."""
    z = zipfile.ZipFile(path)
    names = z.namelist()
    text = z.read('model.ldr').decode('utf-8', 'replace')
    parts = {}
    for n in names:
        if n.lower().startswith('customparts/') and n.lower().endswith('.dat') and n.count('/') == 1:
            parts[os.path.basename(n)] = z.read(n)
        elif re.match(r'(?i)customparts/parts/(s/)?[^/]+\.dat$', n):
            parts[n.split('/', 2)[2]] = z.read(n)
    return text, parts


def split_files(text):
    """[(name, lines)] for each '0 FILE' section (ended by the next, or by '0 NOFILE'); lines outside
    any are one section named '' (a file with no sections at all is just that)."""
    out, cur = [], None
    loose = ('', [])
    for line in text.splitlines():
        if line.startswith('0 FILE '):
            cur = (line[7:].strip(), [line])
            out.append(cur)
        elif line.strip() == '0 NOFILE':
            if cur is not None:
                cur[1].append(line)
            cur = None
        elif cur is None:
            loose[1].append(line)
        else:
            cur[1].append(line)
    if loose[1] and (not out or any(l.startswith('1 ') for l in loose[1])):
        out.insert(0, loose)
    return out


def safe(name):
    return re.sub(r'[^A-Za-z0-9._()+ -]+', '_', name).strip() or 'model'


def write_units(io_path, out_dir, only=None, extra_parts=()):
    text, parts = read_io(io_path)
    files = split_files(text)
    os.makedirs(out_dir, exist_ok=True)
    for name, data in parts.items():
        p = os.path.join(out_dir, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').write(data)
    # (parts kept apart from the model, as the recreations' own CustomParts folder)
    for d in extra_parts:
        for root, _, fs in os.walk(d):
            for f in fs:
                if f.lower().endswith('.dat'):
                    rel = os.path.relpath(os.path.join(root, f), d)
                    rel = rel[len('parts' + os.sep):] if rel.lower().startswith('parts' + os.sep) else rel
                    dst = os.path.join(out_dir, rel)
                    if not os.path.exists(dst):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        open(dst, 'wb').write(open(os.path.join(root, f), 'rb').read())
    written = []
    if not any(n for n, _ in files):
        # (a model of one part list: as it is)
        p = os.path.join(out_dir, safe(os.path.splitext(os.path.basename(io_path))[0]) + '.mpd')
        open(p, 'w', encoding='utf-8', newline=chr(10)).write(text)
        return [p]
    for i, (name, lines) in enumerate(files):
        if not name or (only and name not in only):
            continue
        # (the others after it, the ones it uses among them; not the lines outside any, which are another model)
        rest = [l for j, (n, ls) in enumerate(files) if j != i and n for l in ls]
        p = os.path.join(out_dir, safe(name) + '.mpd')
        open(p, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines + rest) + '\n')
        written.append(p)
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('io')
    ap.add_argument('--out')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--only', nargs='*')
    ap.add_argument('--parts', action='append', default=[], help='a folder of custom .dat parts to add')
    a = ap.parse_args()
    if a.list:
        for n, _ in split_files(read_io(a.io)[0]):
            print(n)
        return
    out = a.out or os.path.join('models', safe(os.path.splitext(os.path.basename(a.io))[0]))
    print('\n'.join(write_units(a.io, out, a.only, a.parts)))


if __name__ == '__main__':
    main()


def posed(path, pose, out):
    """The model with its joints turned: each of pose's [{"match": text, "axis": "x"|"y"|"z", "angle": degrees,
    "pivot": [x, y, z]}] turns its main file's placements whose part or submodel name contains the match
    (or whose line number, counting from 1 in the main file, is the match) about the pivot (LDraw's
    units; the placement's own origin if none). Written to out once, and again when the pose changes."""
    import json
    import math
    import numpy as np
    stamp = json.dumps({'from': path, 'pose': pose, 'mtime': os.path.getmtime(path)}, sort_keys=True)
    if os.path.exists(out) and os.path.exists(out + '.json') and open(out + '.json').read() == stamp:
        return out
    files = split_files(open(path, encoding='utf-8').read())
    main, rest = files[0], files[1:]
    lines = list(main[1])
    for p_ in pose:
        a = math.radians(p_['angle'])
        c, s_ = math.cos(a), math.sin(a)
        R = {'x': [[1, 0, 0], [0, c, -s_], [0, s_, c]], 'y': [[c, 0, s_], [0, 1, 0], [-s_, 0, c]],
             'z': [[c, -s_, 0], [s_, c, 0], [0, 0, 1]]}[p_['axis']]
        R = np.array(R)
        for i, line in enumerate(lines):
            t = line.split()
            if not (len(t) >= 15 and t[0] == '1'):
                continue
            ms = p_['match'] if isinstance(p_['match'], list) else [p_['match']]
            name = ' '.join(t[14:]).lower()
            if not any((isinstance(m, int) and i + 1 == m) or (isinstance(m, str) and m.lower() in name) for m in ms):
                continue
            pos = np.array(list(map(float, t[2:5])))
            M = np.array(list(map(float, t[5:14]))).reshape(3, 3)
            piv = np.array(p_.get('pivot') or pos)
            pos = R @ (pos - piv) + piv
            M = R @ M
            lines[i] = ' '.join(t[:2] + ['%.6f' % x for x in pos] + ['%.6f' % x for x in M.ravel()] + t[14:])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, 'w', encoding='utf-8', newline=chr(10)).write(chr(10).join(lines + [l for _, ls in rest for l in ls]) + chr(10))
    open(out + '.json', 'w').write(stamp)
    return out
