"""Owned morphology of verified M.B hair masks; source textures stay read-only.

SPDX-License-Identifier: GPL-3.0-or-later
Endpoint interpolation follows RandomPlayToon materials/feature_extension.py,
87ebc01de7c6a1ab4796b7da7196b88830d74667 (GPL-3.0). Bounded processing,
soft endpoints, animated controls and per-build ownership are local adaptations.
"""
import json
import math
import bpy
import numpy as np
from ..ownership import tag

MAX_SIZE = 2048
WIDTH_NEAR, WIDTH_FAR = 4, 12


def control(g, profile, name, property_name):
    value = g.value(name, getattr(profile, property_name))
    driver = value.driver_add('default_value').driver
    variable = driver.variables.new()
    variable.name, variable.type = 'v', 'SINGLE_PROP'
    variable.targets[0].id = profile.id_data
    variable.targets[0].data_path = 'hzz_character.' + property_name
    driver.expression = 'v'
    return value


def morphology(signal, radius, maximum, *, border='wrap'):
    """Separable square grayscale extrema in logarithmic radius steps."""
    operation = np.maximum if maximum else np.minimum
    result = np.array(signal, dtype=np.float32, copy=True)
    for axis in (0, 1):
        remaining, step = radius, 1
        while remaining:
            distance = min(step, remaining)
            padding = [(0, 0), (0, 0)]
            padding[axis] = (distance, distance)
            padded = np.pad(result, padding, mode=border)
            lower, upper = [slice(None), slice(None)], [slice(None), slice(None)]
            lower[axis] = slice(0, result.shape[axis])
            upper[axis] = slice(2 * distance, 2 * distance + result.shape[axis])
            operation(result, padded[tuple(lower)], out=result)
            operation(result, padded[tuple(upper)], out=result)
            remaining -= distance
            step *= 2
    return result


def blur(signal, sigma, *, border='wrap'):
    radius = max(1, math.ceil(sigma * 3))
    positions = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-.5 * (positions / sigma) ** 2)
    kernel /= kernel.sum()
    result = signal
    for axis in (0, 1):
        padding = [(0, 0), (0, 0)]
        padding[axis] = (radius, radius)
        padded = np.pad(result, padding, mode=border)
        result = np.zeros(signal.shape, dtype=np.float32)
        for index, weight in enumerate(kernel):
            section = [slice(None), slice(None)]
            section[axis] = slice(index, index + signal.shape[axis])
            result += padded[tuple(section)] * weight
    return result


def mask_pixels(image):
    width, height = image.size
    if min(width, height) < 1 or len(image.pixels) != width * height * 4:
        raise ValueError('头发高光遮罩无法读取：' + image.name)
    pixels = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(pixels)
    mask = pixels.reshape(height, width, 4)[:, :, 2].copy()
    del pixels
    if not np.isfinite(mask).all():
        raise ValueError('头发高光遮罩包含无效像素：' + image.name)
    if max(width, height) <= MAX_SIZE:
        return mask
    scale = MAX_SIZE / max(width, height)
    out_width, out_height = max(1, round(width * scale)), max(1, round(height * scale))
    x = np.clip((np.arange(out_width) + .5) * width / out_width - .5, 0, width - 1)
    y = np.clip((np.arange(out_height) + .5) * height / out_height - .5, 0, height - 1)
    x0, y0 = x.astype(np.int32), y.astype(np.int32)
    x1, y1 = np.minimum(x0 + 1, width - 1), np.minimum(y0 + 1, height - 1)
    tx, ty = (x - x0)[None, :], (y - y0)[:, None]
    lower = mask[y0[:, None], x0] * (1 - tx) + mask[y0[:, None], x1] * tx
    upper = mask[y1[:, None], x0] * (1 - tx) + mask[y1[:, None], x1] * tx
    return np.asarray(lower * (1 - ty) + upper * ty, dtype=np.float32)


def image_channels(cache, name, values):
    height, width = values[0].shape
    image = tag(bpy.data.images.new('HZZ • Hair ' + name, width=width, height=height,
                                  alpha=True, float_buffer=False, is_data=True), cache.uid)
    image.colorspace_settings.name = 'Non-Color'
    image.alpha_mode = 'CHANNEL_PACKED'
    pixels = np.stack(values, axis=-1).astype(np.float32)
    image.pixels.foreach_set(np.clip(pixels, 0, 1).ravel())
    image.pack()
    return image


def endpoints(cache, source, extension, signature):
    key = ('hair_highlight_endpoints', signature, extension)
    if key in cache.groups:
        return cache.groups[key]
    mask = mask_pixels(source)
    scale = max(mask.shape) / 1024
    near, far = max(1, round(WIDTH_NEAR * scale)), max(1, round(WIDTH_FAR * scale))
    border = 'wrap' if extension == 'REPEAT' else 'edge'
    raw = [morphology(mask, radius, maximum, border=border)
           for maximum, radius in ((True, near), (True, far), (False, near), (False, far))]
    soft = [blur(value, 2.5 * scale, border=border) for value in raw]
    original_soft = blur(mask, 2.5 * scale, border=border)
    images = (image_channels(cache, 'Band Extents', raw),
              image_channels(cache, 'Soft Band Extents', soft),
              image_channels(cache, 'Soft Original Band', [original_soft] * 3 + [np.ones_like(mask)]))
    cache.groups[key] = images
    return images


def lerp(g, a, b, factor):
    return g.math('ADD', a, g.math('MULTIPLY', g.math('SUBTRACT', b, a), factor))


def width_mask(g, original, samples, positive, near, far):
    small = lerp(g, samples[2], samples[0], positive)
    large = lerp(g, samples[3], samples[1], positive)
    return lerp(g, lerp(g, original, small, near), large, far)


def build(g, original, profile, cache, plan):
    source = g.tree.nodes['HZZ Original M']
    images = endpoints(cache, source.image, source.extension, plan['sha256']['M'])
    nodes = []
    for label, image in zip(('Raw', 'Soft', 'Soft Original'), images):
        node = g.node('ShaderNodeTexImage', 'HZZ Hair Band ' + label)
        node.image = image
        node.interpolation, node.extension = source.interpolation, source.extension
        g.link(source.inputs['Vector'].links[0].from_socket, node.inputs['Vector'])
        nodes.append(node)
    samples = []
    for node in nodes[:2]:
        channels = g.node('ShaderNodeSeparateColor', node.name + ' Channels')
        g.link(node.outputs['Color'], channels.inputs[0])
        samples.append([*channels.outputs[:3], node.outputs['Alpha']])
    width = control(g, profile, 'HZZ Hair Band Width', 'hair_band_width')
    softness = control(g, profile, 'HZZ Hair Band Softness', 'hair_band_softness')
    positive = g.math('GREATER_THAN', width, 0)
    amount = g.math('ABSOLUTE', width)
    near = g.math('MINIMUM', g.math('DIVIDE', amount, WIDTH_NEAR), 1)
    far = g.math('MAXIMUM', g.math('DIVIDE', g.math('SUBTRACT', amount, WIDTH_NEAR), WIDTH_FAR - WIDTH_NEAR), 0)
    raw = width_mask(g, original, samples[0], positive, near, far)
    soft = width_mask(g, nodes[2].outputs['Color'], samples[1], positive, near, far)
    g.tree['hzz_hair_band_version'] = 1
    g.tree['hzz_hair_band_source'] = json.dumps({'sha256': plan['sha256']['M'], 'channel': 'M.B',
        'uv': plan['uv'], 'source_size': list(source.image.size), 'derived_size': list(images[0].size),
        'width_unit': 'pixels relative to 1024-pixel longest texture edge'}, sort_keys=True)
    return lerp(g, raw, soft, softness)
