"""Shared surface, hair and scene response; no character-specific parameters.

SPDX-License-Identifier: GPL-3.0-or-later
Common toon/specular and hair shoulder formulas adapted from RandomPlayToon
graph.py, detail_review.py and scene_response.py, commit
87ebc01de7c6a1ab4796b7da7196b88830d74667, ImLaoBJie (GPL-3.0).
Integration, masked native reflection and input ownership are Hoyo-ZZZ-Toon.
"""
import re
from .surface_inputs import COVERAGE


def skin(data):
    return data.role == 'BODY' and any(re.search(r'肌|皮肤|皮膚|(?:^|[ _])skin(?:$|[ _])', name, re.I)
        for name in (data.source.name, data.source.mmd_material.name_j, data.source.mmd_material.name_e))


def channels(g, color, name):
    node = g.node('ShaderNodeSeparateColor', name)
    g.link(color, node.inputs[0])
    return node.outputs


def decode(g, data, profile, cache, plan):
    geo = g.node('ShaderNodeNewGeometry', 'HZZ Surface Geometry')
    result = dict(normal=geo.outputs['Normal'], bias=.5, metal=0, mask=0, smooth=.5, slot=0)
    if plan is None:
        # PMX-only models keep their authored specular strength. No invented
        # texture mask or automatic material ID meaning is implied.
        result['mask'] = min(1, max(max(data.specular), 0 if data.role == 'HAIR' else .12))
        result['smooth'] = min(.9, max(.1, 1 - 1 / max(data.shininess, 1) ** .37))
        return result
    uv = g.uv(plan['uv'])
    if plan['flip']:
        uv = g.vector('ADD', g.vector('MULTIPLY', uv, (1, -1, 1)), (0, 1, 0))
    decoded = {}
    for key in 'MAN':
        tex = g.node('ShaderNodeTexImage', 'HZZ Original ' + key)
        tex.image = cache.load(plan['paths'][key], colorspace='Non-Color', alpha_mode='CHANNEL_PACKED')
        g.link(uv, tex.inputs['Vector'])
        decoded[key] = channels(g, tex.outputs['Color'], 'HZZ ' + key + ' Channels')
    attr = g.node('ShaderNodeAttribute', 'HZZ Valid Data Region')
    attr.attribute_name = COVERAGE
    weight = g.math('MULTIPLY', attr.outputs['Fac'], g.value('HZZ Data Strength', profile.surface_data_strength))
    m, a, n = (decoded[k] for k in 'MAN')
    authored_mask = m[2]
    if data.role == 'HAIR':
        from . import hair_highlights
        authored_mask = hair_highlights.build(g, authored_mask, profile, cache, plan)
    strength = g.value('HZZ Normal Strength', profile.normal_strength)
    x, y = [g.math('MULTIPLY', g.math('SUBTRACT', g.math('MULTIPLY', n[i], 2), 1), strength) for i in (0, 1)]
    if plan['flip']:
        y = g.math('MULTIPLY', y, -1)
    length = g.math('ADD', g.math('MULTIPLY', x, x), g.math('MULTIPLY', y, y))
    z = g.math('SQRT', g.math('MAXIMUM', 0, g.math('SUBTRACT', 1, length)))
    encoded = g.combine(*[g.math('ADD', g.math('MULTIPLY', v, .5), .5) for v in (x, y, z)])
    normal = g.node('ShaderNodeNormalMap', 'HZZ Packed Tangent Normal')
    normal.uv_map = plan['uv']
    g.link(encoded, normal.inputs['Color'])
    g.link(weight, normal.inputs['Strength'])
    result.update(normal=normal.outputs['Normal'], bias=g.mix(.5, n[2], weight),
        metal=g.math('MULTIPLY', m[1], weight), mask=g.math('MULTIPLY', authored_mask, weight),
        smooth=g.mix(.5, a[1], weight),
        slot=g.math('MAXIMUM', 0, g.math('SUBTRACT', 4, g.math('FLOOR', g.math('MULTIPLY', m[0], 5)))))
    return result


def shoulder(g, color):
    rgb = channels(g, color, 'HZZ Hair Peak')
    peak = g.math('MAXIMUM', g.math('MAXIMUM', rgb[0], rgb[1]), rgb[2])
    excess = g.math('MAXIMUM', g.math('SUBTRACT', peak, .72), 0)
    compressed = g.math('ADD', g.math('MINIMUM', peak, .72),
        g.math('DIVIDE', g.math('MULTIPLY', .18, excess), g.math('ADD', .18, excess)))
    return g.mix(color, g.math('DIVIDE', compressed, g.math('MAXIMUM', peak, .0001)), mode='MULTIPLY')



def multiply(g, a, b):
    return g.mix(a, b, mode='MULTIPLY')


def add(g, a, b):
    return g.mix(a, b, mode='ADD')


def visibility(g, rgb, profile):
    received = g.smooth(g.gray(rgb), .07, .5)
    strength = g.value('HZZ Scene Shadow Strength', profile.scene_shadow_strength)
    return g.math('SUBTRACT', 1, g.math('MULTIPLY', g.math('SUBTRACT', 1, received), strength))


def illumination(g, normal, bias, light, profile, is_hair):
    ndotl = g.vector('DOT_PRODUCT', normal, light)
    offset = g.math('MULTIPLY', g.math('SUBTRACT', bias, .5),
                    g.value('HZZ Bias Strength', profile.bias_strength * 4))
    signal = g.math('ADD', ndotl, offset)
    boundary = g.value('HZZ Surface Threshold', profile.surface_threshold)
    softness = g.value('HZZ Surface Softness', profile.surface_softness)
    hair_shift = g.value('HZZ Hair Shadow Shift', profile.hair_shadow_shift if is_hair else 0)
    high_center = g.math('ADD', boundary, hair_shift)
    high_width = g.math('MULTIPLY', softness, 1.5 if is_hair else 1)
    low_center = g.math('SUBTRACT', boundary, .4)
    low_width = g.math('ADD', softness, .04)
    low = g.smooth(signal, g.math('SUBTRACT', low_center, low_width), g.math('ADD', low_center, low_width))
    high = g.smooth(signal, g.math('SUBTRACT', high_center, high_width), g.math('ADD', high_center, high_width))
    # A key-facing receiver measures occlusion without applying Lambert twice.
    receiver = g.node('ShaderNodeBsdfDiffuse', 'HZZ Scene Irradiance')
    receiver.inputs['Color'].default_value = (1, 1, 1, 1)
    g.link(light, receiver.inputs['Normal'])
    sample = g.node('ShaderNodeShaderToRGB', 'HZZ Received Scene Light')
    g.link(receiver.outputs[0], sample.inputs[0])
    rgb = sample.outputs['Color']
    gate = visibility(g, rgb, profile)
    return ndotl, g.math('MULTIPLY', low, gate), g.math('MULTIPLY', high, gate), rgb


def skin_palette(g, base, lit, profile):
    """One skin colour basis for SDF faces and normal-driven body skin."""
    tint = g.color('HZZ Skin Tint', profile.skin_tint)
    adjust = g.node('ShaderNodeHueSaturation', 'HZZ Skin Color')
    g.link(multiply(g, base, tint), adjust.inputs['Color'])
    adjust.inputs['Saturation'].default_value = profile.skin_saturation
    adjust.inputs['Value'].default_value = profile.skin_brightness
    key = g.color('HZZ Skin Key Color', profile.skin_key_color)
    shadow = g.color('HZZ Skin Shadow Color', profile.skin_shadow_color)
    return multiply(g, adjust.outputs['Color'], g.mix(shadow, key, lit))


def refresh_skin(nodes, profile):
    # Saved materials keep their graph until the user explicitly updates it.
    if 'HZZ Skin Color' in nodes:
        nodes['HZZ Skin Tint'].outputs[0].default_value = (*profile.skin_tint, 1)
        nodes['HZZ Skin Color'].inputs['Saturation'].default_value = profile.skin_saturation
        nodes['HZZ Skin Color'].inputs['Value'].default_value = profile.skin_brightness
    for name, value in (('HZZ Skin Key Color', profile.skin_key_color),
                        ('HZZ Skin Shadow Color', profile.skin_shadow_color)):
        nodes[name].outputs[0].default_value = (*value, 1)
    nodes['HZZ Light Color Strength'].outputs[0].default_value = profile.light_color_strength
    nodes['HZZ Scene Shadow Strength'].outputs[0].default_value = profile.scene_shadow_strength


def palette(g, base, low, high, profile, is_hair, is_skin):
    if is_skin:
        middle = g.math('MULTIPLY', low, .6)
        lit = g.math('ADD', middle, g.math('MULTIPLY', g.math('SUBTRACT', 1, middle), high))
        return skin_palette(g, base, lit, profile)
    key = g.color('HZZ Surface Key Color', profile.surface_key_color)
    shadow = g.color('HZZ Body Shadow Color', profile.body_shadow_color)
    middle = g.color('HZZ Surface Mid Color', profile.surface_mid_color)
    luminance = g.gray(base)
    dark = g.math('SUBTRACT', 1, g.smooth(luminance, .025, .22))
    # Regularized cool ambient reflection acts mainly on dark neutrals.
    # Saturated albedos and light hair retain their authored colour hierarchy.
    cast = g.mix((.83, .69, 1.03, 1), (1, .95, 1, 1), high) if is_hair else (.9, .86, 1, 1)
    tinted = multiply(g, base, g.mix((1, 1, 1, 1), cast, dark))
    amount = g.math('MULTIPLY', dark, g.value('HZZ Ambient Tint', profile.ambient_tint_strength))
    if is_hair:
        amount = g.math('MULTIPLY', amount, g.math('SUBTRACT', 1, g.math('MULTIPLY', high, .68)))
        room = g.math('SUBTRACT', 1, g.math('MULTIPLY', g.smooth(luminance, .12, .5), .22))
        tinted = multiply(g, tinted, room)
        lift = (.009, .011, .042, 1)
    else:
        hsv = g.node('ShaderNodeSeparateColor', 'HZZ Source Chroma')
        hsv.mode = 'HSV'
        g.link(base, hsv.inputs[0])
        amount = g.math('MULTIPLY', amount, g.math('SUBTRACT', 1, g.math('MULTIPLY', hsv.outputs[1], .7)))
        lift = (.01, .008, .022, 1)
    tinted = add(g, tinted, multiply(g, lift, amount))
    return multiply(g, tinted, g.mix(g.mix(shadow, middle, low), key, high))


def hair_response(g, color, base, mask, ndotl, profile):
    from .hair_highlights import control
    facing = g.math('ADD', .45, g.math('MULTIPLY', .55, g.math('MAXIMUM', ndotl, 0)))
    band = g.math('MULTIPLY', g.math('POWER', g.math('MAXIMUM', mask, 0), .7), facing)
    strength = g.math('MULTIPLY', g.value('HZZ Specular', profile.specular),
                      control(g, profile, 'HZZ Hair Highlights', 'hair_highlights'))
    band = g.math('MULTIPLY', band, strength)
    tint = g.mix(base, (.62, .68, .94, 1), .22)
    return add(g, color, multiply(g, tint, band))


def surface_response(g, color, base, normal, light, view, metal, mask, smooth, high, profile, is_skin):
    halfway = g.vector('NORMALIZE', g.vector('ADD', light, view))
    nh = g.math('MAXIMUM', g.vector('DOT_PRODUCT', normal, halfway), 0)
    exponent = g.math('ADD', 12, g.math('MULTIPLY', smooth, 100))
    lobe = g.smooth(g.math('POWER', nh, exponent), .18, .60)
    specular = g.value('HZZ Specular', profile.specular)
    lobe = g.math('MULTIPLY', lobe, g.math('MULTIPLY', mask, specular))
    lobe = g.math('MULTIPLY', lobe, .06 if is_skin else .6)
    lobe = g.math('MULTIPLY', lobe, g.math('ADD', .2, g.math('MULTIPLY', high, .8)))
    color = add(g, color, multiply(g, (1, 1, 1, 1) if is_skin else (.85, .78, .89, 1), lobe))
    if is_skin:
        return color
    # Two broad stylized cards follow the same key and evaluated camera vector.
    # This is an art-directed reflection, not an environment-map reconstruction.
    sky = g.vector('NORMALIZE', g.vector('ADD', g.vector('SCALE', light, scale=-1), (0, 0, .65)))
    other_half = g.vector('NORMALIZE', g.vector('ADD', sky, view))
    card = g.math('POWER', g.math('MAXIMUM', g.vector('DOT_PRODUCT', normal, other_half), 0), 6)
    broad = g.math('ADD', g.math('MULTIPLY', g.math('POWER', nh, 8), .7), g.math('MULTIPLY', card, .5))
    sheen = g.math('MULTIPLY', g.math('POWER', g.math('MAXIMUM', mask, 0), .7), .24)
    sheen = g.math('MULTIPLY', sheen, g.math('SUBTRACT', 1, g.math('MULTIPLY', smooth, .5)))
    amount = g.math('ADD', .004, g.math('ADD', g.math('MULTIPLY', metal, .30), sheen))
    reflection = g.value('HZZ Reflection Strength', profile.reflection_strength)
    amount = g.math('MULTIPLY', amount, g.math('DIVIDE', reflection, .35))
    tint = g.mix((.48, .52, .85, 1), base, g.math('MULTIPLY', metal, .5))
    return add(g, color, multiply(g, tint, g.math('MULTIPLY', broad, amount)))


def scene_chroma(g, color, rgb, profile):
    components = channels(g, rgb, 'HZZ Light Chroma')
    peak = g.math('MAXIMUM', g.math('MAXIMUM', components[0], components[1]), components[2])
    chroma = g.vector('SCALE', g.vector('ADD', rgb, (.03, .03, .03)),
                      scale=g.math('DIVIDE', 1, g.math('ADD', peak, .03)))
    tint = g.mix((1, 1, 1, 1), chroma, g.value('HZZ Light Color Strength', profile.light_color_strength))
    return multiply(g, color, tint)


def build(g, base, data, profile, cache, plan):
    g.tree['hzz_body_version'] = 4
    decoded = decode(g, data, profile, cache, plan)
    normal, bias, metal, mask, smooth = (decoded[k] for k in ('normal', 'bias', 'metal', 'mask', 'smooth'))
    is_hair, is_skin = data.role == 'HAIR', skin(data)
    g.tree['hzz_surface_semantic'] = 'HAIR' if is_hair else 'SKIN' if is_skin else 'SURFACE'
    sun = g.node('ShaderNodeAttribute', 'HZZ Body Sun')
    sun.attribute_name = 'HZZ_SUN'
    light = g.vector('NORMALIZE', sun.outputs['Vector'])
    view = g.vector('NORMALIZE', g.tree.nodes['HZZ Surface Geometry'].outputs['Incoming'])
    ndotl, low, high, rgb = illumination(g, normal, bias, light, profile, is_hair)
    color = palette(g, base, low, high, profile, is_hair, is_skin)
    if not is_hair and not is_skin:
        # A bounded continuous term retains curvature inside a flat toon band.
        # Rough cloth gets most of it; metal retains its masked reflection.
        volume = g.math('ADD', .82, g.math('MULTIPLY', g.smooth(ndotl, -.6, .9), .18))
        color = multiply(g, color, g.mix(volume, 1, metal))
    if is_hair:
        color = hair_response(g, color, base, mask, ndotl, profile)
    else:
        color = surface_response(g, color, base, normal, light, view, metal, mask, smooth, high, profile, is_skin)
    nv = g.math('MAXIMUM', g.vector('DOT_PRODUCT', normal, view), 0)
    edge = g.math('POWER', g.math('SUBTRACT', 1, nv), 3)
    rim = g.math('MULTIPLY', edge, g.math('MULTIPLY', g.math('MAXIMUM', ndotl, 0),
                                        g.value('HZZ Rim Strength', profile.rim_strength)))
    color = add(g, color, multiply(g, (1, 1, 1, 1) if is_skin else (.67, .64, .93, 1), rim))
    color = scene_chroma(g, color, rgb, profile)
    return high, shoulder(g, color) if is_hair else color


def refresh(material, profile):
    if material.node_tree.get('hzz_body_version') == 2:
        refresh_legacy(material, profile)
        return
    nodes = material.node_tree.nodes
    semantic = material.node_tree['hzz_surface_semantic']
    values = {'HZZ Surface Threshold': profile.surface_threshold,
        'HZZ Surface Softness': profile.surface_softness,
        'HZZ Hair Shadow Shift': profile.hair_shadow_shift if semantic == 'HAIR' else 0,
        'HZZ Bias Strength': profile.bias_strength * 4, 'HZZ Specular': profile.specular,
        'HZZ Scene Shadow Strength': profile.scene_shadow_strength,
        'HZZ Reflection Strength': profile.reflection_strength, 'HZZ Hair Highlights': profile.hair_highlights,
        'HZZ Normal Strength': profile.normal_strength, 'HZZ Data Strength': profile.surface_data_strength,
        'HZZ Rim Strength': profile.rim_strength, 'HZZ Light Color Strength': profile.light_color_strength,
        'HZZ Ambient Tint': profile.ambient_tint_strength}
    for name, value in values.items():
        if name in nodes:
            nodes[name].outputs[0].default_value = value
    if 'HZZ Skin Key Color' in nodes:
        refresh_skin(nodes, profile)
    for name, value in {
        'HZZ Surface Key Color': profile.skin_key_color if semantic == 'SKIN' else profile.surface_key_color,
        'HZZ Body Shadow Color': profile.skin_shadow_color if semantic == 'SKIN' else profile.body_shadow_color,
        'HZZ Surface Mid Color': profile.surface_mid_color}.items():
        if name in nodes:
            nodes[name].outputs[0].default_value = (*value, 1)


def refresh_legacy(material, profile):
    nodes = material.node_tree.nodes
    semantic = material.node_tree['hzz_surface_semantic']
    values = {'HZZ Surface Threshold': profile.surface_threshold,
        'HZZ Surface Softness': profile.surface_softness * (1.6 if semantic == 'SKIN' else 1),
        'HZZ Bias Strength': profile.bias_strength * 4, 'HZZ Specular': profile.specular,
        'HZZ Scene Shadow Strength': profile.scene_shadow_strength,
        'HZZ Reflection Strength': profile.reflection_strength, 'HZZ Hair Highlights': profile.hair_highlights,
        'HZZ Normal Strength': profile.normal_strength, 'HZZ Data Strength': profile.surface_data_strength,
        'HZZ Rim Strength': profile.rim_strength, 'HZZ Light Color Strength': profile.light_color_strength}
    for name, value in values.items():
        if name in nodes:
            nodes[name].outputs[0].default_value = value
    nodes['HZZ Body Shadow Color'].outputs[0].default_value = (*(profile.skin_shadow_color if semantic == 'SKIN' else profile.body_shadow_color), 1)
