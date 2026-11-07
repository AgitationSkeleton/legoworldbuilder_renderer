"""A large render brought down to a game sprite, as the game's were made: shrunk with its edges
smoothed against a backdrop colour (the colour of where the sprite will stand: grass, water, or
the magenta or white a sprite was keyed from), then cut out with a hard edge, so that the edge
pixels keep a little of that colour; cropped to what is drawn, with its registration point.

    sprite, reg = post.to_sprite(rgba_image, scale, fringe=(r, g, b), threshold=0.5)
"""
import numpy as np
from PIL import Image


def shrink(im, factor):
    """Premultiplied box shrink by a (fractional) factor: an RGBA float array, 0..1."""
    a = np.asarray(im.convert('RGBA'), dtype=np.float32) / 255.0
    rgb, al = a[..., :3] * a[..., 3:4], a[..., 3:4]
    w, h = im.size
    nw, nh = max(1, round(w / factor)), max(1, round(h / factor))
    pre = Image.fromarray(np.uint8(np.clip(np.concatenate([rgb, al], -1) * 255 + 0.5, 0, 255)), 'RGBA')
    # (PIL's reduce is a true box filter for whole factors; resize with BOX for the rest)
    small = pre.resize((nw, nh), Image.BOX)
    return np.asarray(small, dtype=np.float32) / 255.0


def to_sprite(im, factor, fringe=(1.0, 0.0, 1.0), threshold=0.5, gamma=1.0):
    """The sprite (RGBA, hard alpha) and the offset of its crop in the shrunk image."""
    s = shrink(im, factor)
    al = s[..., 3:4]
    rgb = s[..., :3] + (1 - al) * np.array(fringe, dtype=np.float32)    # premultiplied over the backdrop
    if gamma != 1.0:
        rgb = np.clip(rgb, 0, 1) ** gamma
    keep = al[..., 0] >= threshold
    out = np.zeros(s.shape, dtype=np.uint8)
    out[..., :3] = np.uint8(np.clip(rgb * 255 + 0.5, 0, 255))
    out[..., 3] = np.where(keep, 255, 0)
    ys, xs = np.nonzero(keep)
    if not len(xs):
        return Image.new('RGBA', (1, 1)), (0, 0)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    return Image.fromarray(out[y0:y1, x0:x1], 'RGBA'), (int(x0), int(y0))


def mask_of(im, threshold=0.5, factor=1.0):
    """A boolean mask: alpha above threshold, after shrinking by factor."""
    a = shrink(im, factor)[..., 3] if factor != 1.0 else np.asarray(im.convert('RGBA'), dtype=np.float32)[..., 3] / 255.0
    return a >= threshold


def reference_mask(im):
    """A game sprite's drawn pixels: alpha on, and not the pure white its ink keys out."""
    a = np.asarray(im.convert('RGBA'))
    return (a[..., 3] > 0) & ~((a[..., 0] == 255) & (a[..., 1] == 255) & (a[..., 2] == 255))
