"""The Blender add-on as a zip to install (Edit > Preferences > Add-ons > Install from Disk):
addon/__init__.py with blender/wbsprite.py, wbrender/models.py (as wb_models.py) and the fitted
looks and cameras (config/), written to dist/wb_sprite_renderer.zip."""
import glob
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = 'wb_sprite_renderer'


def main():
    os.makedirs(os.path.join(ROOT, 'dist'), exist_ok=True)
    out = os.path.join(ROOT, 'dist', PKG + '.zip')
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(ROOT, 'addon', '__init__.py'), PKG + '/__init__.py')
        z.write(os.path.join(ROOT, 'blender', 'wbsprite.py'), PKG + '/wbsprite.py')
        z.write(os.path.join(ROOT, 'wbrender', 'models.py'), PKG + '/wb_models.py')
        for p in glob.glob(os.path.join(ROOT, 'config', '**', '*.json'), recursive=True):
            z.write(p, PKG + '/config/' + os.path.relpath(p, os.path.join(ROOT, 'config')).replace(os.sep, '/'))
    print(out)


if __name__ == '__main__':
    main()
