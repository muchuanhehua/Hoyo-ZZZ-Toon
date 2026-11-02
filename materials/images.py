"""Owned image copies with explicit color/data semantics and per-build reuse."""
from pathlib import Path
import bpy
import numpy as np
from ..ownership import tag


class ImageCache:
    def __init__(self, uid):
        self.uid, self.images, self.alpha, self.groups = uid, {}, {}, {}

    def load(self, source, *, colorspace='sRGB', alpha_mode=None):
        identity = source.as_pointer() if isinstance(source, bpy.types.Image) else str(source)
        key = identity, colorspace, alpha_mode
        if key in self.images:
            return self.images[key]
        if isinstance(source, Path):
            image = bpy.data.images.load(str(source), check_existing=False)
        elif source.packed_file or source.source == 'GENERATED':
            image = source.copy()
        else:
            path = bpy.path.abspath(source.filepath, library=source.library)
            image = bpy.data.images.load(path, check_existing=False)
        tag(image, self.uid)
        image.name = 'HZZ • ' + image.name
        image.colorspace_settings.name = colorspace
        if alpha_mode is not None:
            image.alpha_mode = alpha_mode
        self.images[key] = image
        return image

    def alpha_min(self, image):
        key = image.as_pointer()
        if key not in self.alpha:
            if image.channels < 4:
                self.alpha[key] = 1.0
            else:
                pixels = np.empty(len(image.pixels), dtype=np.float32)
                image.pixels.foreach_get(pixels)
                if not len(pixels):
                    raise ValueError(f'贴图无法读取：{image.name}')
                self.alpha[key] = float(pixels[3::4].min())
        return self.alpha[key]
