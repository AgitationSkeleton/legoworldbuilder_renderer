"""LEGO World Builder Sprites: a Blender add-on for making sprites in the style of LEGO World Builder's
units from LDraw or Stud.io models, by hand: the model imported, the game's look and camera set
up, the unit turned to each of the game's directions (and stood in water, for a unit that swims),
and the set rendered straight to game-sized sprites.

Its panel is in the 3D view's sidebar (N), under "WB Sprites".  It needs ImportLDraw
(github.com/TobyLobster/ImportLDraw) and the LDraw parts library: say where in the add-on's
preferences.  Built into a zip by tools/make_addon.py (with blender/wbsprite.py and config/)."""

bl_info = {
    'name': 'LEGO World Builder Sprites',
    'author': 'legoworldbuilder_renderer contributors',
    'version': (1, 0, 0),
    'blender': (4, 2, 0),
    'location': 'View3D > Sidebar > WB Sprites',
    'description': 'Sprites in the style of LEGO World Builder (1999) from LDraw and Stud.io models',
    'category': 'Render',
}

import json
import math
import os
import tempfile

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty, PointerProperty

from . import wbsprite, wb_models

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, 'config')
DIRS = wbsprite.DIRECTIONS
WHOLE = '__whole__'      # (the submodel choice for a model of one part list)


def load_json(*p, default=None):
    path = os.path.join(CONFIG, *p)
    return json.load(open(path, encoding='utf-8')) if os.path.exists(path) else default


def units():
    U = load_json('units.json', default={})
    return {k: v for k, v in U.items() if not k.startswith('_')}


def unit_items(self, context):
    return [('custom', 'Custom', 'A model of your own: the shared camera')] + [(k, k.title(), u['sprite']) for k, u in sorted(units().items())]


def submodel_items(self, context):
    names = getattr(bpy.types.Scene, '_wb_submodels', None) or [WHOLE]
    return [(n, 'The whole model' if n == WHOLE else n, '') for n in names]


def prefs():
    return bpy.context.preferences.addons[__name__].preferences


class WBPrefs(bpy.types.AddonPreferences):
    bl_idname = __name__
    ldraw: StringProperty(name='LDraw library', subtype='DIR_PATH', description='The LDraw parts library (its folder has parts/ and p/)')
    importer: StringProperty(name='ImportLDraw', subtype='DIR_PATH', description="ImportLDraw's folder (the one holding loadldraw/)")

    def draw(self, context):
        self.layout.prop(self, 'ldraw')
        self.layout.prop(self, 'importer')


class WBSettings(bpy.types.PropertyGroup):
    model: StringProperty(name='Model', subtype='FILE_PATH', description='A Stud.io .io, or an LDraw .ldr / .mpd / .dat')
    submodel: EnumProperty(name='Submodel', items=submodel_items)
    unit: EnumProperty(name='Unit', items=unit_items, description="A unit of the game's: its fitted camera and its sprites' names")
    sprite_name: StringProperty(name='Sprite name', default='vehicle.custom', description='The sprites are written as <name>.<direction>.png')
    direction: EnumProperty(name='Direction', items=[(d, d.title(), '') for d in DIRS], update=lambda s, c: turn(c))
    elevation: FloatProperty(name='Elevation', default=35.0, min=0, max=90, update=lambda s, c: aim(c))
    skew: FloatProperty(name='Skew', default=0.33, min=-1, max=1, update=lambda s, c: aim(c),
                        description="The game's oblique view: what is further north drawn further right")
    scale: FloatProperty(name='Pixels per unit', default=800.0, min=1, description='The sprite\'s size: pixels per Blender unit of the model')
    h_right: FloatProperty(name='Right', default=79.0)
    h_left: FloatProperty(name='Left', default=257.0)
    h_up: FloatProperty(name='Up', default=166.0)
    h_down: FloatProperty(name='Down', default=347.0)
    water: BoolProperty(name='In water', default=False, description='Partly submerged, as the game draws a unit that swims (its .water. sprites)')
    waterline: FloatProperty(name='Waterline', default=0.35, min=0, max=1, description="The water's height, as a part of the model's")
    studs: BoolProperty(name='Studs', default=False, description="Studs on top of the bricks (the game's sprites have none: its bricks' tops are flat)")
    out_dir: StringProperty(name='Write to', subtype='DIR_PATH', default='//sprites/')
    size: IntProperty(name='Render size', default=768, min=128, max=4096, description='The render, before it is brought down to the sprite')
    samples: IntProperty(name='Samples', default=64, min=1, max=4096)


def settings(context):
    return context.scene.wb_sprites


def params(context):
    """The look (config/style.json) with the panel's camera."""
    S = load_json('style.json', default={})
    P = json.loads(json.dumps(wbsprite.DEFAULTS))
    for k, v in S.get('look', {}).items():
        if isinstance(v, dict):
            P[k].update(v)
        else:
            P[k] = v
    s = settings(context)
    P['elevation'] = s.elevation
    P['skew'] = s.skew
    if s.water:
        w = S.get('water', {})
        P.update({'waterline': s.waterline, 'water_color': w.get('color', P['water_color']), 'deep_color': w.get('deep', P['deep_color']),
                  'water_mix': w.get('mix', P['water_mix']), 'water_depth': w.get('depth', 0.3)})
    return P, S


def root_and_meshes():
    root = bpy.data.objects.get('WB_Root')
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    return root, meshes


def heading(s, d):
    return {'right': s.h_right, 'left': s.h_left, 'up': s.h_up, 'down': s.h_down}[d]


def turn(context):
    root, _ = root_and_meshes()
    if root:
        root.rotation_euler = (0, 0, math.radians(heading(settings(context), settings(context).direction)))
        wbsprite.set_skew(root, settings(context).skew)


def aim(context):
    root, meshes = root_and_meshes()
    if not root or not meshes:
        return
    P, _ = params(context)
    turn(context)
    info = wbsprite.frame(meshes)
    lo, hi, centre, r = info
    from mathutils import Vector
    wbsprite.setup_camera(P, centre - Vector((r, r, r)), centre + Vector((r, r, r)))


class WB_OT_open(bpy.types.Operator):
    """Read the model's submodels (a Stud.io .io or an LDraw file of several)"""
    bl_idname = 'wb_sprites.open'
    bl_label = 'Read submodels'

    def execute(self, context):
        s = settings(context)
        path = bpy.path.abspath(s.model)
        if path.lower().endswith('.io'):
            text, _ = wb_models.read_io(path)
        else:
            text = open(path, encoding='utf-8', errors='replace').read()
        bpy.types.Scene._wb_submodels = [n for n, _ in wb_models.split_files(text) if n] or [WHOLE]
        return {'FINISHED'}


class WB_OT_import(bpy.types.Operator):
    """Import the submodel, as the game's units are rendered (no bevels, no gaps, no ground)"""
    bl_idname = 'wb_sprites.import_model'
    bl_label = 'Import'

    def execute(self, context):
        s = settings(context)
        P = prefs()
        if not P.ldraw or not P.importer:
            self.report({'ERROR'}, "Set the LDraw library and ImportLDraw's folder in the add-on's preferences")
            return {'CANCELLED'}
        path = bpy.path.abspath(s.model)
        work = tempfile.mkdtemp(prefix='wbsprites_')
        sub = '' if s.submodel == WHOLE else s.submodel
        if path.lower().endswith('.io') or sub:
            only = {sub} if sub else None
            files = wb_models.write_units(path, work, only) if path.lower().endswith('.io') else None
            if files is None:
                text = open(path, encoding='utf-8', errors='replace').read()
                parts = wb_models.split_files(text)
                pick = [i for i, (n, _) in enumerate(parts) if n == sub]
                lines = (parts[pick[0]][1] if pick else []) + [l for j, (n, ls) in enumerate(parts) if not pick or j != pick[0] for l in ls]
                files = [os.path.join(os.path.dirname(path), '_wb_' + wb_models.safe(sub or 'model') + '.mpd')]
                open(files[0], 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
            path = files[0]
        for o in list(context.scene.objects):
            bpy.data.objects.remove(o)
        studs = None
        if not s.studs:
            studs = os.path.join(work, '_nostuds')
            os.makedirs(studs, exist_ok=True)
            wbsprite.write_no_studs(studs, bpy.path.abspath(P.ldraw))
        wbsprite.import_model(path, bpy.path.abspath(P.ldraw), bpy.path.abspath(P.importer), 'Standard', studs)
        bpy.ops.wb_sprites.look()
        return {'FINISHED'}


class WB_OT_fit(bpy.types.Operator):
    """The chosen unit's camera, as fitted to the game's own sprites of it"""
    bl_idname = 'wb_sprites.fit'
    bl_label = "Use the unit's camera"

    def execute(self, context):
        s = settings(context)
        f = load_json('fit', s.unit + '.json') if s.unit != 'custom' else None
        if not f:
            f = load_json('shared_camera.json', default={})
        if f:
            s.elevation = f.get('elevation', s.elevation)
            s.skew = f.get('skew', s.skew)
            s.scale = f.get('scale', s.scale)
            for d in DIRS:
                if d in f.get('headings', {}):
                    setattr(s, 'h_' + d, f['headings'][d])
        if s.unit != 'custom':
            u = units()[s.unit]
            s.sprite_name = u['sprite']
        aim(context)
        return {'FINISHED'}


class WB_OT_look(bpy.types.Operator):
    """The game's look: its plastic, its lights, its camera"""
    bl_idname = 'wb_sprites.look'
    bl_label = 'Apply the look'

    def execute(self, context):
        root, meshes = root_and_meshes()
        if not meshes:
            self.report({'ERROR'}, 'Import a model first')
            return {'CANCELLED'}
        P, _ = params(context)
        lo, hi, centre, r = wbsprite.frame(meshes)
        if P.get('waterline') is not None:
            P['waterline_z'] = lo.z + (hi.z - lo.z) * P['waterline']
            P['water_depth_z'] = (hi.z - lo.z) * P.get('water_depth', 0.3)
        wbsprite.style_materials(meshes, P)
        wbsprite.setup_world(P)
        aim(context)
        return {'FINISHED'}


class WB_OT_render(bpy.types.Operator):
    """Render each direction and write the game-sized sprites"""
    bl_idname = 'wb_sprites.render'
    bl_label = 'Render sprites'

    def execute(self, context):
        s = settings(context)
        root, meshes = root_and_meshes()
        if not root:
            self.report({'ERROR'}, 'Import a model first')
            return {'CANCELLED'}
        bpy.ops.wb_sprites.look()
        P, S = params(context)
        out = bpy.path.abspath(s.out_dir)
        os.makedirs(out, exist_ok=True)
        wbsprite.setup_render(s.size, 'CYCLES', s.samples)
        lo, hi, centre, r = wbsprite.frame(meshes)
        ppu = s.size / wbsprite.ortho_size(r, P['skew'])
        fringe = tuple(c / 255 for c in ((S.get('water', {}).get('fringe') if s.water else None) or S.get('fringe', (255, 0, 255))))
        tmp = tempfile.mkdtemp(prefix='wbsprites_')
        for d in DIRS:
            p = os.path.join(tmp, d + '.png')
            wbsprite.shoot(root, meshes, P, (lo, hi, centre, r), p, heading(s, d))
            spr = wbsprite.to_sprite_array(wbsprite.load_rgba(p), ppu / s.scale, fringe, S.get('threshold', 0.5), S.get('gamma', 1.0))
            name = '%s.%s%s.png' % (s.sprite_name, 'water.' if s.water else '', d)
            wbsprite.save_rgba(spr, os.path.join(out, name))
        turn(context)
        self.report({'INFO'}, 'Sprites written to ' + out)
        return {'FINISHED'}


class WB_PT_panel(bpy.types.Panel):
    bl_label = 'LEGO World Builder Sprites'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'WB Sprites'

    def draw(self, context):
        s = settings(context)
        L = self.layout
        b = L.box()
        b.label(text='Model')
        b.prop(s, 'model')
        b.operator('wb_sprites.open')
        b.prop(s, 'submodel')
        b.prop(s, 'studs')
        b.operator('wb_sprites.import_model')
        b = L.box()
        b.label(text='Camera')
        b.prop(s, 'unit')
        b.operator('wb_sprites.fit')
        b.prop(s, 'elevation')
        b.prop(s, 'skew')
        b.prop(s, 'scale')
        c = b.column(align=True)
        c.label(text='Turn for each direction')
        for d in DIRS:
            c.prop(s, 'h_' + d)
        b.prop(s, 'direction', expand=True)
        b = L.box()
        b.label(text='Water')
        b.prop(s, 'water')
        r = b.row()
        r.enabled = s.water
        r.prop(s, 'waterline', slider=True)
        b = L.box()
        b.label(text='Sprites')
        b.prop(s, 'sprite_name')
        b.prop(s, 'out_dir')
        b.prop(s, 'size')
        b.prop(s, 'samples')
        b.operator('wb_sprites.look')
        b.operator('wb_sprites.render', icon='RENDER_STILL')


CLASSES = (WBPrefs, WBSettings, WB_OT_open, WB_OT_import, WB_OT_fit, WB_OT_look, WB_OT_render, WB_PT_panel)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.wb_sprites = PointerProperty(type=WBSettings)


def unregister():
    del bpy.types.Scene.wb_sprites
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
