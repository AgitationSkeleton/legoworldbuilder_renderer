"""LEGO World Builder sprites from LDraw models, inside Blender (4.2+).

Used by the command line (blender/render_cli.py, which the wbrender package runs) and by the
add-on (addon/): the model imported with ImportLDraw, the look of the game's 1999 renders set
up (flat-ish plastic, a strong key light from the upper left, a soft fill, no shadows on the
ground, no bevels), an orthographic camera placed as the game's sprites were shot, and each
direction rendered large, to be brought down to the game's size afterwards (wbrender/post.py).

Directions: the game's map is drawn obliquely (a tile 50 px on in its row, each row 50 px down
and 25 px left), so its four headings are, on screen, right (east), left (west), up (north, up
and to the right) and down (south, down and to the left).  A unit is turned to each heading
under one fixed camera.
"""
import json
import math
import os
import re
import sys

import bpy
from mathutils import Vector

DIRECTIONS = ('right', 'left', 'up', 'down')
LOADER = None             # ImportLDraw's loadldraw, once a model is imported

# The look, as fitted to the game's own sprites (wbrender/fit.py tunes these per unit).
DEFAULTS = {
    'elevation': 30.0,        # camera's angle above the ground, degrees
    'azimuth': 0.0,           # camera turned about the vertical, degrees (0: looking north)
    'headings': {'right': 0.0, 'left': 180.0, 'up': 90.0, 'down': 270.0},  # model's turn per direction
    'model_heading': 0.0,     # the model's own front, as it was built (degrees)
    'key': {'elevation': 55.0, 'azimuth': -35.0, 'strength': 3.2},
    'fill': {'elevation': 20.0, 'azimuth': 150.0, 'strength': 0.9},
    'ambient': 0.55,
    'saturation': 1.15,
    'roughness': 0.55,
    'specular': 0.25,
    'waterline': None,        # height (fraction of the model's height) of the water, or None
    'water_color': (0.10, 0.75, 0.80),
    'water_mix': 0.55,
    'deep_color': (0.08, 0.32, 0.55),
    'ortho_margin': 1.08,
    'skew': 0.0,              # the oblique shear of the game's view (x' = x + skew * y), fitted
}


def ensure_importer(addon_dir):
    """ImportLDraw's loader, from its folder (the add-on need not be installed)."""
    if addon_dir not in sys.path:
        sys.path.insert(0, addon_dir)
    from loadldraw import loadldraw  # noqa: E402
    global LOADER
    LOADER = loadldraw
    return loadldraw


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_model(path, ldraw_dir, addon_dir, resolution='Standard', studs_dir=None):
    L = ensure_importer(addon_dir)
    O = L.Options
    O.ldrawDirectory = ldraw_dir
    O.resolution = resolution
    O.useColourScheme = 'lgeo'
    O.gaps = False
    O.addBevelModifier = False
    O.curvedWalls = False
    O.addGroundPlane = False
    O.addWorldEnvironmentTexture = False
    O.setRenderSettings = False
    O.positionCamera = False
    O.removeDefaultObjects = True
    O.importCameras = False
    O.positionObjectOnGroundAtOrigin = True
    O.flattenHierarchy = True
    O.instructionsLook = False
    # (studs: as the parts have them, or none -- empty stud parts searched before the library's)
    O.useLogoStuds = bool(studs_dir)
    O.studLogoDirectory = studs_dir or ""
    O.smoothShading = True
    O.edgeSplit = True
    O.verbose = 0
    # (its messages to the console only: in the background there is no window to report them in)
    L.internalPrint = lambda message: print('[importldraw] ' + message)
    seen = set()

    def warn_once(key, message=None):
        if key not in seen:
            seen.add(key)
            print('[importldraw] WARNING: ' + (message or key))
    L.printWarningOnce = warn_once
    L.printError = lambda message: print('[importldraw] ERROR: ' + message)
    L.loadFromFile(bpy.context, os.path.abspath(path), True)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    # (one root to turn the model by, under one that skews the world as the game's map is skewed)
    skew = bpy.data.objects.new('WB_Skew', None)
    root = bpy.data.objects.new('WB_Root', None)
    bpy.context.scene.collection.objects.link(skew)
    bpy.context.scene.collection.objects.link(root)
    for o in bpy.context.scene.objects:
        if o.parent is None and o not in (root, skew):
            o.parent = root
    root.parent = skew
    return root, meshes


def set_skew(root, amount):
    """The game's oblique view: what is further north drawn further right, by amount per unit of
    northing (x' = x + amount * y), after the model is turned.  Vertical edges stay vertical.
    (A shear is no camera's: it goes in the root's parent-inverse matrix, which Blender renders as
    it is, normals and all.)"""
    from mathutils import Matrix
    M = Matrix.Identity(4)
    M[0][1] = amount
    root.matrix_parent_inverse = M
    bpy.context.view_layer.update()


def write_no_studs(folder, ldraw_dir=None):
    """Empty parts for every stud of the library (and the logo versions ImportLDraw asks for
    instead), found before the library's: the bricks' tops flat, as the game's units have them."""
    import re
    os.makedirs(folder, exist_ok=True)
    names = {'stud', 'stud2', 'stud2a', 'stud3', 'stud4', 'stud4a', 'stud6', 'stud6a', 'stud10', 'stud15', 'studa'}
    if ldraw_dir and os.path.isdir(os.path.join(ldraw_dir, 'p')):
        for f in os.listdir(os.path.join(ldraw_dir, 'p')):
            m = re.match(r'(?i)^(stud[a-z0-9]*)(-logo[0-9]*)?\.dat$', f)
            if m:
                names.add(m.group(1).lower())
    for n in names:
        for v in ('', '-logo', '-logo2', '-logo3', '-logo4', '-logo5'):
            open(os.path.join(folder, n + v + '.dat'), 'w').write('0 BFC CERTIFY CCW' + chr(10))


def bounds(meshes):
    bpy.context.view_layer.update()       # (the matrices as they now are: not as before the import placed the model)
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in meshes:
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector((min(lo[i], w[i]) for i in range(3)))
            hi = Vector((max(hi[i], w[i]) for i in range(3)))
    return lo, hi


def base_colour(mat):
    """The colour ImportLDraw gave a material (its principled or diffuse colour); a material of
    ours keeps the colour it was made from."""
    if mat and 'wb_rgba' in mat:
        return tuple(mat['wb_rgba'])
    if mat and mat.use_nodes:
        for n in mat.node_tree.nodes:
            if n.type in ('BSDF_PRINCIPLED', 'BSDF_DIFFUSE') and 'Base Color' in n.inputs:
                return tuple(n.inputs['Base Color'].default_value)
            if n.type == 'BSDF_DIFFUSE':
                return tuple(n.inputs['Color'].default_value)
        for n in mat.node_tree.nodes:
            if n.type == 'GROUP':
                for i in n.inputs:
                    if i.type == 'RGBA':
                        return tuple(i.default_value)
    if mat:
        return tuple(mat.diffuse_color)
    return (0.5, 0.5, 0.5, 1.0)


def style_materials(meshes, P):
    """Each LDraw colour as the game's plastic: one material per colour, the waterline in it.
    (Again and again: each time from the colours the model came with.)"""
    made = {}
    for o in meshes:
        for slot in o.material_slots:
            m = slot.material
            key = (m['wb_key'] if m and 'wb_key' in m else (m.name if m else 'none'))
            if key not in made:
                rgba = base_colour(m)
                # (a colour code given another: P['recolour'] {"14": "4"}, LDraw codes, from ImportLDraw's table)
                code = re.match(r'Material_(\w+?)(_c)?(_s.*)?$', key)
                to = (P.get('recolour') or {}).get(code.group(1)) if code else None
                if to is not None and ldraw_colour(to):
                    rgba = tuple(ldraw_colour(to)['colour']) + (1.0,)
                # (the game's own colours: config/palette.json, sRGB, for the codes it has learned)
                pc = (P.get('palette') or {}).get(str(to) if to is not None else (code.group(1) if code else ''))
                if pc:
                    rgba = tuple(srgb_to_linear(x / 255.0) for x in pc[:3]) + (rgba[3] if len(rgba) > 3 else 1.0,)
                # (transparency as LDraw's colour table has it: ImportLDraw's material does not say)
                cc = str(to) if to is not None else (code.group(1) if code else None)
                if cc and ldraw_colour(cc):
                    al = ldraw_colour(cc).get('alpha', 1.0)
                    al = al / 255.0 if al > 1 else al
                    rgba = tuple(rgba[:3]) + (al,)
                made[key] = wb_material(key + ('>' + str(to) if to is not None else ''), rgba, P)
                made[key]['wb_key'] = key
            slot.material = made[key]


def wb_material(name, rgba, P):
    m = bpy.data.materials.new('WB_' + name)
    m['wb_rgba'] = list(rgba[:4]) + ([1.0] if len(rgba) < 4 else [])
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Roughness'].default_value = P['roughness']
    if 'Specular IOR Level' in bsdf.inputs:
        bsdf.inputs['Specular IOR Level'].default_value = P['specular']
    r, g, b = [min(1.0, max(0.0, c)) for c in rgba[:3]]
    # (the game's colours are richer than plastic's: saturation up, about the grey of the colour)
    grey = (r + g + b) / 3
    s = P['saturation']
    col = [min(1.0, max(0.0, grey + (c - grey) * s)) for c in (r, g, b)]
    alpha = rgba[3] if len(rgba) > 3 else 1.0
    if P.get('waterline') is not None:
        # Under the water: the colour taken toward the water's, deeper toward its depths
        geo = nt.nodes.new('ShaderNodeNewGeometry')
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        nt.links.new(geo.outputs['Position'], sep.inputs[0])
        under = nt.nodes.new('ShaderNodeMath')
        under.operation = 'LESS_THAN'
        under.inputs[1].default_value = P['waterline_z']
        nt.links.new(sep.outputs['Z'], under.inputs[0])
        depth = nt.nodes.new('ShaderNodeMapRange')
        depth.inputs['From Min'].default_value = P['waterline_z']
        depth.inputs['From Max'].default_value = P['waterline_z'] - P.get('water_depth_z', 0.01)
        nt.links.new(sep.outputs['Z'], depth.inputs['Value'])
        deep = mix_rgb(nt, P['water_color'], P['deep_color'])
        nt.links.new(depth.outputs['Result'], sock(deep.inputs, 'Factor_Float'))
        tint = mix_rgb(nt, col, (0, 0, 0))
        nt.links.new(sock(deep.outputs, 'Result_Color'), sock(tint.inputs, 'B_Color'))
        k = nt.nodes.new('ShaderNodeMath')
        k.operation = 'MULTIPLY'
        k.inputs[1].default_value = P['water_mix']
        nt.links.new(under.outputs[0], k.inputs[0])
        nt.links.new(k.outputs[0], sock(tint.inputs, 'Factor_Float'))
        nt.links.new(sock(tint.outputs, 'Result_Color'), bsdf.inputs['Base Color'])
    else:
        bsdf.inputs['Base Color'].default_value = (*col, 1)
    if alpha < 0.99:
        # (LDraw's transparent colours: glass, tinted, that the parts behind show through, as the
        # portraits' windscreens do; not plastic made faint)
        for name in ('Transmission Weight', 'Transmission'):
            if name in bsdf.inputs:
                bsdf.inputs[name].default_value = 1.0
                break
        bsdf.inputs['Roughness'].default_value = 0.05
        if 'IOR' in bsdf.inputs:
            bsdf.inputs['IOR'].default_value = 1.45
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m


def ldraw_colour(code):
    """ImportLDraw's entry for an LDraw colour code (its table is keyed by numbers), or None."""
    if LOADER is None or code is None:
        return None
    C = LOADER.LegoColours.colours
    for k in (code, str(code)) + ((int(code),) if str(code).lstrip('-').isdigit() else ()):
        if k in C:
            return C[k]
    return None


def srgb_to_linear(x):
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def sock(sockets, identifier):
    """A node's socket by its identifier (the Mix node's names repeat across its data types)."""
    for x in sockets:
        if x.identifier == identifier:
            return x
    raise KeyError(identifier)


def mix_rgb(nt, a, b):
    m = nt.nodes.new('ShaderNodeMix')
    m.data_type = 'RGBA'
    sock(m.inputs, 'A_Color').default_value = (*a[:3], 1)
    sock(m.inputs, 'B_Color').default_value = (*b[:3], 1)
    return m


def sun(name, elevation, azimuth, strength, softness=8.0):
    """A sun: softness, its apparent size in degrees (a 1999 ray tracer's lights were points:
    hard shadows, about 0)."""
    d = bpy.data.lights.new(name, 'SUN')
    d.energy = strength
    d.angle = math.radians(softness)
    o = bpy.data.objects.new(name, d)
    bpy.context.scene.collection.objects.link(o)
    o.rotation_euler = (math.radians(90 - elevation), 0, math.radians(azimuth))
    return o


def setup_world(P):
    sc = bpy.context.scene
    if not sc.world:
        sc.world = bpy.data.worlds.new('WB')
    w = sc.world
    w.use_nodes = True
    bg = w.node_tree.nodes.get('Background') or w.node_tree.nodes.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (1, 1, 1, 1)
    bg.inputs['Strength'].default_value = P['ambient']
    for o in [o for o in sc.objects if o.type == 'LIGHT']:
        bpy.data.objects.remove(o)
    soft = P.get('softness', 8.0)
    sun('WB_Key', softness=soft, **P['key'])
    sun('WB_Fill', softness=soft, **P['fill'])
    if P.get('rim'):
        # (the portraits' white edge: a light from behind and above, as the camera sees it)
        sun('WB_Rim', softness=soft, **P['rim'])


def ortho_size(radius, P):
    """The frame's width in blender units: the model's whole turn, and its skew, inside it."""
    return radius * 2 * P.get('ortho_margin', 1.08) * (1 + abs(P.get('skew', 0.0)))


def setup_camera(P, lo, hi):
    """An orthographic camera, elevation and azimuth as fitted, framing the model whatever its turn."""
    sc = bpy.context.scene
    cam = sc.camera
    if not cam:
        cam = bpy.data.objects.new('WB_Camera', bpy.data.cameras.new('WB_Camera'))
        sc.collection.objects.link(cam)
        sc.camera = cam
    cam.data.type = 'ORTHO'
    centre = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 0.01)
    el = math.radians(P['elevation'])
    az = math.radians(P['azimuth'])
    d = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    cam.location = centre + d * radius * 6
    cam.rotation_euler = (math.radians(90) - el, 0, az)
    cam.data.ortho_scale = ortho_size(radius, P)
    cam.data.clip_start = 0.001
    cam.data.clip_end = radius * 20
    return cam


def setup_render(size, engine='CYCLES', samples=48):
    sc = bpy.context.scene
    sc.render.engine = engine
    if engine == 'CYCLES':
        sc.cycles.samples = samples
        sc.cycles.use_denoising = False
        sc.cycles.max_bounces = 4
        try:
            prefs = bpy.context.preferences.addons['cycles'].preferences
            for kind in ('OPTIX', 'CUDA'):
                try:
                    prefs.compute_device_type = kind
                    prefs.get_devices()
                    if any(d.type == kind for d in prefs.devices):
                        for d in prefs.devices:
                            d.use = d.type == kind
                        sc.cycles.device = 'GPU'
                        break
                except TypeError:
                    continue
        except Exception:
            sc.cycles.device = 'CPU'
    sc.render.resolution_x = size
    sc.render.resolution_y = size
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = True
    sc.render.dither_intensity = 0.0      # (exact values: the id pass is read colour for colour)
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.render.image_settings.color_depth = '8'
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'


def render_directions(root, meshes, P, out_dir, name, size=512, directions=DIRECTIONS, engine='CYCLES', samples=48):
    """Each direction rendered to out_dir/<name>.<dir>.png (large: brought down afterwards)."""
    os.makedirs(out_dir, exist_ok=True)
    root.rotation_euler = (0, 0, 0)
    bpy.context.view_layer.update()
    lo, hi = bounds(meshes)
    if P.get('waterline') is not None:
        P['waterline_z'] = lo.z + (hi.z - lo.z) * P['waterline']
    style_materials(meshes, P)
    setup_world(P)
    setup_render(size, engine, samples)
    # (the frame fits the model at any turn: its radius about the centre)
    centre = (lo + hi) / 2
    r = max((Vector((x, y, z)) - centre).length for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z))
    setup_camera(P, centre - Vector((r, r, r)), centre + Vector((r, r, r)))
    root.location = (0, 0, 0)
    written = {}
    for d in directions:
        root.rotation_euler = (0, 0, math.radians(P['headings'][d] + P['model_heading']))
        bpy.context.view_layer.update()
        p = os.path.join(out_dir, '%s.%s.png' % (name, d))
        bpy.context.scene.render.filepath = p
        bpy.ops.render.render(write_still=True)
        written[d] = p
    return written


# ---------- batches: the model imported once, many shots of it ----------

def frame(meshes):
    """The model's centre and the radius that holds it at any turn."""
    lo, hi = bounds(meshes)
    centre = (lo + hi) / 2
    r = max((Vector((x, y, z)) - centre).length for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z))
    return lo, hi, centre, r


def silhouette_mode():
    """Flat white on nothing: the shape alone, quickly (Workbench), for fitting the camera."""
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sh = sc.display.shading
    sh.light = 'FLAT'
    sh.color_type = 'SINGLE'
    sh.single_color = (1, 1, 1)
    sh.show_object_outline = False
    sh.show_cavity = False
    sh.show_shadows = False
    sc.render.film_transparent = True
    sc.display.render_aa = '8'


def setup_hero_camera(P, centre, r):
    """The info panel's portrait: a perspective camera (lens in mm) close up, above the model by
    elevation, framing the whole of it."""
    sc = bpy.context.scene
    cam = sc.camera
    if not cam:
        cam = bpy.data.objects.new('WB_Camera', bpy.data.cameras.new('WB_Camera'))
        sc.collection.objects.link(cam)
        sc.camera = cam
    cam.data.type = 'PERSP'
    cam.data.lens = P.get('hero_lens', 50.0)
    cam.data.sensor_fit = 'AUTO'
    fov = cam.data.angle
    dist = r / math.sin(fov / 2) * P.get('hero_margin', 1.02)
    el = math.radians(P.get('hero_elevation', 30.0))
    cam.location = centre + Vector((0, -math.cos(el), math.sin(el))) * dist
    cam.rotation_euler = (math.radians(90) - el, 0, 0)
    # (turned about its own view: the game's portraits are not all level -- the buggy's, the fish's)
    if P.get('hero_roll'):
        cam.rotation_euler.rotate_axis('Z', math.radians(P['hero_roll']))
    cam.data.clip_start = dist * 0.01
    cam.data.clip_end = dist * 10
    return cam


def shoot(root, meshes, P, frame_info, path, heading):
    """One render: the model turned to heading (degrees), the camera at P's elevation and azimuth,
    the frame P['ortho'] blender units across (or the model's own)."""
    lo, hi, centre, r = frame_info
    root.rotation_euler = (0, 0, math.radians(heading))
    if P.get('hero'):
        # (the portrait: no skew, its own camera)
        set_skew(root, 0.0)
        setup_hero_camera(P, centre, r)
    else:
        set_skew(root, P.get('skew', 0.0))
        cam = setup_camera(P, centre - Vector((r, r, r)), centre + Vector((r, r, r)))
        if P.get('ortho'):
            cam.data.ortho_scale = P['ortho']
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


def run_batch(root, meshes, P, shots, size, mode='final', engine='CYCLES', samples=48):
    """shots: [{path, heading, (elevation, azimuth, ...)}]; each rendered at size x size."""
    info = frame(meshes)
    lo, hi = info[0], info[1]
    if P.get('waterline') is not None:
        P['waterline_z'] = lo.z + (hi.z - lo.z) * P['waterline']
        P['water_depth_z'] = (hi.z - lo.z) * P.get('water_depth', 0.3)
    if mode == 'silhouette':
        setup_render(size, 'BLENDER_WORKBENCH')
        silhouette_mode()
    else:
        style_materials(meshes, P)
        setup_world(P)
        setup_render(size, engine, samples)
    done = []
    looked = None
    for s in shots:
        Q = json.loads(json.dumps(P))
        for k, v in s.items():
            if k in ('path', 'heading'):
                continue
            if isinstance(v, dict) and isinstance(Q.get(k), dict):
                Q[k].update(v)
            else:
                Q[k] = v
        if mode != 'silhouette' and s.get('look_id') is not None and s['look_id'] != looked:
            # (another look for these shots: the lights and the plastic made anew)
            if Q.get('waterline') is not None:
                Q['waterline_z'] = lo.z + (hi.z - lo.z) * Q['waterline']
                Q['water_depth_z'] = (hi.z - lo.z) * Q.get('water_depth', 0.3)
            style_materials(meshes, Q)
            setup_world(Q)
            looked = s['look_id']
        done.append(shoot(root, meshes, Q, info, os.path.abspath(s['path']), s['heading']))
    return {'files': done, 'radius': info[3], 'size': [list(lo), list(hi)]}


# ---------- a render brought down to a sprite, in Blender (numpy; wbrender/post.py does the same with PIL) ----------

def area_shrink(a, factor):
    """An array (H, W, C) averaged down by a factor (fractional too): each new pixel the mean of the
    area of the old it covers."""
    import numpy as np
    H, W = a.shape[:2]
    nh, nw = max(1, round(H / factor)), max(1, round(W / factor))

    def weights(n_old, n_new):
        f = n_old / n_new
        M = np.zeros((n_new, n_old), dtype=np.float32)
        for i in range(n_new):
            x0, x1 = i * f, (i + 1) * f
            for j in range(int(x0), min(n_old, int(math.ceil(x1)))):
                M[i, j] = min(x1, j + 1) - max(x0, j)
        return M / M.sum(1, keepdims=True)

    Wy, Wx = weights(H, nh), weights(W, nw)
    return np.einsum('ih,hwc,jw->ijc', Wy, a, Wx)


def to_sprite_array(rgba, factor, fringe=(1.0, 0.0, 1.0), threshold=0.5, gamma=1.0):
    """A float RGBA render (H, W, 4; top row first) to a sprite: uint8 RGBA, hard alpha, cropped."""
    import numpy as np
    pre = np.concatenate([rgba[..., :3] * rgba[..., 3:4], rgba[..., 3:4]], -1)
    s = area_shrink(pre, factor)
    al = s[..., 3:4]
    rgb = s[..., :3] + (1 - al) * np.array(fringe, dtype=np.float32)
    if gamma != 1.0:
        rgb = np.clip(rgb, 0, 1) ** gamma
    keep = al[..., 0] >= threshold
    out = np.zeros(s.shape, dtype=np.uint8)
    out[..., :3] = np.uint8(np.clip(rgb * 255 + 0.5, 0, 255))
    out[..., 3] = np.where(keep, 255, 0)
    ys, xs = np.nonzero(keep)
    if not len(xs):
        return out[:1, :1]
    return out[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def save_rgba(arr, path):
    """A uint8 RGBA array (top row first) saved as a PNG through Blender's images."""
    import numpy as np
    h, w = arr.shape[:2]
    img = bpy.data.images.new('wb_sprite_out', w, h, alpha=True)
    img.pixels.foreach_set((np.flipud(arr).astype(np.float32) / 255.0).ravel())
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def load_rgba(path):
    """A PNG as float RGBA (top row first), through Blender's images."""
    import numpy as np
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    a = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    bpy.data.images.remove(img)
    return np.flipud(a.reshape(h, w, 4))


# ---------- passes: the game's 1999 look composited afterwards (wbrender/shade.py) ----------
# A pixel's colour there is its brick's colour times the light on it, in the picture's own
# values, tops lit past white; not a physical render.  So each shot is rendered as: which LDraw
# colour each pixel is (an id pass, flat, no smoothing), and how much of each light falls on it
# (white plastic lit by one light at a time: key, fill and the ambient sky), with the alpha.

def code_of(mat_name):
    m = re.match(r'(?:WB_)?Material_(\w+?)(_c)?(_s.*)?$', mat_name or '')
    return m.group(1) if m else (mat_name or 'none')


def id_colour(i):
    """A distinct flat colour for the i-th code (i from 1), exact in an 8-bit PNG."""
    return ((i * 37) % 251 + 2, (i * 91) % 249 + 3, (i * 157) % 241 + 7)


def setup_passes(meshes, P):
    """Materials for the passes: each original colour's code kept, one white plastic, one id each."""
    codes = {}
    white = bpy.data.materials.get('WB_white') or bpy.data.materials.new('WB_white')
    white.use_nodes = True
    nt = white.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    d = nt.nodes.new('ShaderNodeBsdfDiffuse')
    d.inputs['Color'].default_value = (0.8, 0.8, 0.8, 1)
    d.inputs['Roughness'].default_value = 0.0
    nt.links.new(d.outputs[0], out.inputs[0])
    ids = {}
    for o in meshes:
        slots = []
        for slot in o.material_slots:
            m = slot.material
            key = m['wb_key'] if m and 'wb_key' in m else (m.name if m else 'none')
            c = code_of(key)
            to = (P.get('recolour') or {}).get(c)
            c = str(to) if to is not None else c
            if c not in codes:
                codes[c] = len(codes) + 1
            slots.append(c)
        o['wb_codes'] = slots
    for c, i in codes.items():
        mat = bpy.data.materials.get('WB_id_' + c) or bpy.data.materials.new('WB_id_' + c)
        r, g, b = id_colour(i)
        mat.diffuse_color = (r / 255.0, g / 255.0, b / 255.0, 1)
        ids[c] = mat
    def rgb(c):
        # (the code's own colour, sRGB 0..255, for a code the palette has not learned)
        col = ldraw_colour(c)
        if not col:
            return None
        return [round(255 * (x * 12.92 if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055)) for x in col['colour'][:3]]
    def alpha(c):
        col = ldraw_colour(c)
        a = col.get('alpha', 1.0) if col else 1.0
        return a / 255.0 if a > 1 else a
    return white, ids, {('%d,%d,%d' % id_colour(i)): {'code': c, 'rgb': rgb(c), 'alpha': alpha(c)} for c, i in codes.items()}


def set_materials(meshes, which, ids=None, white=None):
    for o in meshes:
        for slot, c in zip(o.material_slots, o.get('wb_codes', [])):
            slot.material = white if which == 'white' else ids[c]


def gloss_material(roughness):
    """White shine and nothing else: a light's highlights alone (the specular pass)."""
    name = 'WB_gloss_%g' % roughness
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    g = nt.nodes.new('ShaderNodeBsdfGlossy')
    g.inputs['Color'].default_value = (1, 1, 1, 1)
    g.inputs['Roughness'].default_value = roughness
    nt.links.new(g.outputs[0], out.inputs[0])
    return m


def light_only(P, which):
    """The scene lit by one light: a sun at P[which]'s angles (strength 1; 'ambient': the sky, strength 1)."""
    sc = bpy.context.scene
    for o in [o for o in sc.objects if o.type == 'LIGHT']:
        bpy.data.objects.remove(o)
    w = sc.world or bpy.data.worlds.new('WB')
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get('Background') or w.node_tree.nodes.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (1, 1, 1, 1)
    bg.inputs['Strength'].default_value = 1.0 if which == 'ambient' else 0.0
    if which != 'ambient':
        L = P[which]
        sun('WB_' + which, L['elevation'], L['azimuth'], 1.0, softness=P.get('softness', 8.0))


def run_passes(root, meshes, P, shots, size, samples=32):
    """Each shot: <path>.id.png (flat ids, no smoothing), <path>.<light>.png for each of P['passes']
    (default key, fill, ambient: 16-bit, linear) and <path>.alpha.png.  Answers the ids' codes."""
    info = frame(meshes)
    white, ids, legend = setup_passes(meshes, P)
    # (each code's id number, as id_colour has it: for the reflection pass)
    ids_index = {}
    for key, v in legend.items():
        ids_index[v['code']] = next(i for i in range(1, 4096) if ','.join(str(x) for x in id_colour(i)) == key)
    sc = bpy.context.scene
    done = []
    lights = P.get('passes') or [('key', P['key']), ('fill', P['fill']), ('ambient', None)]
    for s in shots:
        Q = json.loads(json.dumps(P))
        Q.update({k: v for k, v in s.items() if k not in ('path', 'heading')})
        base = os.path.abspath(s['path'])
        # (parts of these colours left out: what is behind the glass, for compositing it through)
        hide = set(str(c) for c in (s.get('hide_codes') or []))
        for o in meshes:
            codes = set(o.get('wb_codes', []))
            o.hide_render = bool(hide) and bool(codes) and codes <= hide
        # the ids: flat, unsmoothed
        set_materials(meshes, 'id', ids=ids)
        setup_render(size, 'BLENDER_WORKBENCH')
        sh = sc.display.shading
        sh.light = 'FLAT'
        sh.color_type = 'MATERIAL'
        sh.show_object_outline = False
        sh.show_cavity = False
        sh.show_shadows = False
        sc.display.render_aa = 'OFF'
        sc.view_settings.view_transform = 'Raw'
        shoot(root, meshes, Q, info, base + '.id.png', s['heading'])
        if P.get('ids_only'):
            for o in meshes:
                o.hide_render = False
            done.append(base)
            continue
        # the seams: each part outlined where it meets another (Workbench's object outline, on flat
        # white): the dark lines between the bricks the game's portraits show
        if P.get('seam_pass'):
            set_materials(meshes, 'white', white=white)
            sh.color_type = 'SINGLE'
            sh.single_color = (1, 1, 1)
            sh.show_object_outline = True
            sh.object_outline_color = (0, 0, 0)
            sc.display.render_aa = '8'
            shoot(root, meshes, Q, info, base + '.seams.png', s['heading'])
            sh.show_object_outline = False
            sh.color_type = 'MATERIAL'
            sc.display.render_aa = 'OFF'
        # each light on white plastic (linear, 16 bits), and the alpha with it
        set_materials(meshes, 'white', white=white)
        setup_render(size, 'CYCLES', samples)
        sc.view_settings.view_transform = 'Raw'
        sc.render.image_settings.color_depth = '16'
        for entry in lights:
            name, L = entry[0], entry[1]
            kind = entry[2] if len(entry) > 2 else 'diffuse'
            if L is not None:
                Q[name] = L
            # (a specular pass: the same light on shine alone)
            if kind.startswith('spec'):
                gm = gloss_material(float(kind.split(':')[1]) if ':' in kind else 0.25)
                for o in meshes:
                    for slot in o.material_slots:
                        slot.material = gm
            light_only(Q, name)
            shoot(root, meshes, Q, info, base + '.' + name + '.png', s['heading'])
            if kind.startswith('spec'):
                set_materials(meshes, 'white', white=white)
        # each pixel's height on the model, 0 (its lowest) to 1 (its top): for the waterline
        if P.get('height_pass', True):
            hmat = height_material(info[0].z, info[1].z)
            for o in meshes:
                for slot in o.material_slots:
                    slot.material = hmat
            bpy.context.scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.0
            for o in [o for o in sc.objects if o.type == 'LIGHT']:
                bpy.data.objects.remove(o)
            shoot(root, meshes, Q, info, base + '.height.png', s['heading'])
        # each pixel's surface direction as the camera sees it (x right, y up, z towards it), 0.5 + 0.5 n:
        # for measuring where the game's lights stood
        if P.get('normal_pass'):
            nmat = normal_material()
            for o in meshes:
                for slot in o.material_slots:
                    slot.material = nmat
            bpy.context.scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.0
            for o in [o for o in sc.objects if o.type == 'LIGHT']:
                bpy.data.objects.remove(o)
            shoot(root, meshes, Q, info, base + '.normal.png', s['heading'])
        # what each pixel reflects: the part (its colour's id) or the world (the direction the ray leaves in)
        if P.get('reflect_pass'):
            for o in [o for o in sc.objects if o.type == 'LIGHT']:
                bpy.data.objects.remove(o)
            sc.cycles.max_bounces = 2
            sc.cycles.glossy_bounces = 1
            sc.cycles.transparent_max_bounces = 8
            for which, emit, world_on in (('reflect', True, False), ('reflectdir', False, True)):
                for o in meshes:
                    for slot, c in zip(o.material_slots, o.get('wb_codes', [])):
                        rgb = [x / 255.0 for x in id_colour(ids_index[c])]
                        slot.material = mirror_material(c, rgb, emit)     # (Raw: written as given)
                world_direction(world_on)
                shoot(root, meshes, Q, info, base + '.' + which + '.png', s['heading'])
        sc.render.image_settings.color_depth = '8'
        for o in meshes:
            o.hide_render = False
        done.append(base)
    return {'files': done, 'radius': info[3], 'legend': legend}


def normal_material():
    """Glowing with its surface's direction in the camera's frame, 0.5 + 0.5 n."""
    m = bpy.data.materials.get('WB_normal') or bpy.data.materials.new('WB_normal')
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    vt = nt.nodes.new('ShaderNodeVectorTransform')
    vt.vector_type = 'NORMAL'
    vt.convert_from = 'WORLD'
    vt.convert_to = 'CAMERA'
    sc = nt.nodes.new('ShaderNodeVectorMath')
    sc.operation = 'MULTIPLY_ADD'
    sc.inputs[1].default_value = (0.5, 0.5, 0.5)
    sc.inputs[2].default_value = (0.5, 0.5, 0.5)
    em = nt.nodes.new('ShaderNodeEmission')
    nt.links.new(geo.outputs['Normal'], vt.inputs['Vector'])
    nt.links.new(vt.outputs['Vector'], sc.inputs[0])
    nt.links.new(sc.outputs['Vector'], em.inputs['Color'])
    nt.links.new(em.outputs[0], out.inputs[0])
    return m


def mirror_material(code, rgb, emit=True):
    """Seen by the camera: a perfect mirror. Seen in another part's reflection: its colour's id (emit) or
    black. So a mirror pass shows, at each pixel, which part it reflects."""
    name = 'WB_mirror_%s_%d' % (code, int(emit))
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    lp = nt.nodes.new('ShaderNodeLightPath')
    mix = nt.nodes.new('ShaderNodeMixShader')
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = (rgb[0], rgb[1], rgb[2], 1) if emit else (0, 0, 0, 1)
    gl = nt.nodes.new('ShaderNodeBsdfGlossy')
    gl.inputs['Color'].default_value = (1, 1, 1, 1)
    gl.inputs['Roughness'].default_value = 0.0
    nt.links.new(lp.outputs['Is Camera Ray'], mix.inputs[0])
    nt.links.new(em.outputs[0], mix.inputs[1])
    nt.links.new(gl.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs[0])
    return m


def world_direction(on):
    """The world: black, or glowing with the direction a ray leaves in (0.5 + 0.5 d, the world's axes)."""
    sc = bpy.context.scene
    w = sc.world or bpy.data.worlds.new('WB')
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputWorld')
    bg = nt.nodes.new('ShaderNodeBackground')
    bg.inputs['Strength'].default_value = 1.0
    if on:
        tc = nt.nodes.new('ShaderNodeTexCoord')
        ma = nt.nodes.new('ShaderNodeVectorMath')
        ma.operation = 'MULTIPLY_ADD'
        ma.inputs[1].default_value = (0.5, 0.5, 0.5)
        ma.inputs[2].default_value = (0.5, 0.5, 0.5)
        nt.links.new(tc.outputs['Generated'], ma.inputs[0])
        nt.links.new(ma.outputs['Vector'], bg.inputs['Color'])
    else:
        bg.inputs['Color'].default_value = (0, 0, 0, 1)
    nt.links.new(bg.outputs[0], out.inputs[0])


def height_material(z0, z1):
    """Glowing with its own height: (z - z0) / (z1 - z0), before the model is turned or skewed (object space
    would turn with it: the height is the world's, and the turn is about the upright)."""
    m = bpy.data.materials.get('WB_height') or bpy.data.materials.new('WB_height')
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    rng = nt.nodes.new('ShaderNodeMapRange')
    rng.inputs['From Min'].default_value = z0
    rng.inputs['From Max'].default_value = z1
    em = nt.nodes.new('ShaderNodeEmission')
    nt.links.new(geo.outputs['Position'], sep.inputs[0])
    nt.links.new(sep.outputs['Z'], rng.inputs['Value'])
    nt.links.new(rng.outputs['Result'], em.inputs['Color'])
    nt.links.new(em.outputs[0], out.inputs[0])
    return m
