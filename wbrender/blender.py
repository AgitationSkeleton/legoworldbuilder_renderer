"""Running Blender for a job (blender/render_cli.py), with the paths of local.json."""
import json
import os
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def local():
    """This machine's paths (local.json, never published): blender, ldraw, importer, port, recreations."""
    p = os.path.join(ROOT, 'local.json')
    if not os.path.exists(p):
        raise SystemExit('local.json is missing: copy local.example.json to local.json and fill in its paths')
    return json.load(open(p, encoding='utf-8'))


def run(job, timeout=3600, quiet=True):
    """Runs a job in Blender; answers what it printed after WB_DONE."""
    L = local()
    job = dict(job)
    job.setdefault('ldraw', L['ldraw'])
    job.setdefault('importer', L['importer'])
    job['model'] = os.path.abspath(job['model'])
    fd, path = tempfile.mkstemp(suffix='.json', prefix='wbjob_')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(job, f)
    try:
        r = subprocess.run([L['blender'], '-b', '--factory-startup', '-P', os.path.join(ROOT, 'blender', 'render_cli.py'), '--', path],
                           capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace')
    finally:
        os.remove(path)
    for line in r.stdout.splitlines():
        if line.startswith('WB_DONE '):
            return json.loads(line[8:])
    raise RuntimeError('Blender failed:\n' + (r.stdout[-3000:] + r.stderr[-2000:]))
