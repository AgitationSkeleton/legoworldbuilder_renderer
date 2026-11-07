"""Blender's side of a render, run by wbrender (python -m wbrender.render):

    blender -b --factory-startup -P blender/render_cli.py -- JOB.json

JOB.json: {model, ldraw, importer, params, size, engine, samples, and either shots: [{path,
heading, ...}] (mode 'final' or 'silhouette') or out, name, directions}.
Prints one line 'WB_DONE <json>' with the files written."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wbsprite  # noqa: E402


def main():
    job = json.load(open(sys.argv[sys.argv.index('--') + 1], encoding='utf-8'))
    P = json.loads(json.dumps(wbsprite.DEFAULTS))
    for k, v in (job.get('params') or {}).items():
        if isinstance(v, dict) and isinstance(P.get(k), dict):
            P[k].update(v)
        else:
            P[k] = v
    wbsprite.clear_scene()
    studs = None
    if job.get('studs') == 'none':
        # (empty stud parts, found before the library's: smooth tops, as the game's sprites have)
        studs = os.path.join(os.path.dirname(os.path.abspath(job['model'])), '_nostuds')
        os.makedirs(studs, exist_ok=True)
        wbsprite.write_no_studs(studs, job['ldraw'])
    root, meshes = wbsprite.import_model(job['model'], job['ldraw'], job['importer'], job.get('resolution', 'Standard'), studs)
    if job.get('mode') == 'passes':
        out = wbsprite.run_passes(root, meshes, P, job['shots'], job.get('size', 384), job.get('samples', 32))
    elif job.get('shots'):
        out = wbsprite.run_batch(root, meshes, P, job['shots'], job.get('size', 256), job.get('mode', 'final'),
                                 job.get('engine', 'CYCLES'), job.get('samples', 48))
    else:
        out = wbsprite.render_directions(root, meshes, P, os.path.abspath(job['out']), job['name'], job.get('size', 512),
                                         job.get('directions', wbsprite.DIRECTIONS), job.get('engine', 'CYCLES'), job.get('samples', 48))
    print('WB_DONE ' + json.dumps(out))


main()
