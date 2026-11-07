"""The units (config/units.json), where their models and the game's sprites of them are."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNITS = {k: v for k, v in json.load(open(os.path.join(ROOT, 'config', 'units.json'), encoding='utf-8')).items() if not k.startswith('_')}


def safe(name):
    import re
    return re.sub(r'[^A-Za-z0-9._()+ -]+', '_', name).strip()


def model_path(unit, hero=False):
    """models/all/<submodel>.mpd (python -m wbrender.models makes them from the recreations); for
    the portrait, its own model if the game's portrait is of another build."""
    if UNITS[unit].get('model_file') and not (hero and UNITS[unit].get('hero_model')):
        return os.path.join(ROOT, UNITS[unit]['model_file'])
    name = UNITS[unit].get('hero_model') if hero and UNITS[unit].get('hero_model') else UNITS[unit]['model']
    p = os.path.join(ROOT, 'models', 'all', safe(name) + '.mpd')
    if not os.path.exists(p):
        raise SystemExit('%s is not there: run python -m wbrender.setup_models first' % p)
    # (posed as the game's: its joints turned -- config/units.json 'pose'; the portrait's too, unless its
    # own build)
    pose = UNITS[unit].get('pose')
    if pose and not (hero and UNITS[unit].get('hero_model')):
        from .models import posed
        return posed(p, pose, os.path.join(ROOT, 'models', 'all', '_posed_' + safe(unit) + '.mpd'))
    return p


def ref_path(unit, direction, water=False):
    """The game's own sprite of the unit standing in that direction (reference/), or None."""
    u = UNITS[unit]
    if u.get('single'):
        # (a pickup: one sprite, fitted as its 'right'; a coloured one by its yellow)
        if direction != 'right' or water:
            return None
        name = u['sprite'].format(colour='yellow')
    else:
        name = '%s.%s%s%s' % (u['sprite'], 'water.' if water else '', direction, '' if water else u.get('still', ''))
    p = os.path.join(ROOT, 'reference', name + '.png')
    return p if os.path.exists(p) else None


def hero_ref(unit):
    """The game's portrait of the unit (reference/<sprite>.hero.png), or None."""
    p = os.path.join(ROOT, 'reference', UNITS[unit]['sprite'] + '.hero.png')
    return p if os.path.exists(p) else None
