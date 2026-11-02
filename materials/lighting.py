"""Separate key direction, native received light, and lit/shade color formation."""
import bpy
from .graph import Graph
from ..ownership import tag


def curve(graph, name, source, middle, handle):
    node = graph.node('ShaderNodeFloatCurve', name)
    mapping = node.mapping
    mapping.initialize()
    mapping.extend, mapping.use_clip = 'EXTRAPOLATED', True
    mapping.clip_min_x, mapping.clip_min_y, mapping.clip_max_x, mapping.clip_max_y = 0, 0, 1, 1
    mapping.curves[0].points.new(*middle).handle_type = handle
    mapping.update()
    graph.link(source, node.inputs['Value'])
    return node.outputs[0]


def palette(uid):
    tree = tag(bpy.data.node_groups.new('HZZ • Lit and Shade Colors', 'ShaderNodeTree'), uid)
    tree['hzz_kind'], tree['hzz_palette_version'] = 'palette', 1
    for name, direction in (('Base', 'INPUT'), ('Shadow Tint', 'INPUT'), ('Lit', 'OUTPUT'), ('Shade', 'OUTPUT')):
        tree.interface.new_socket(name=name, in_out=direction, socket_type='NodeSocketColor')
    graph = Graph(tree)
    inputs, outputs = graph.node('NodeGroupInput', 'Inputs'), graph.node('NodeGroupOutput', 'Outputs')
    hsv = graph.node('ShaderNodeSeparateColor', 'Base HSV')
    hsv.mode = 'HSV'
    graph.link(inputs.outputs['Base'], hsv.inputs[0])
    saturation = curve(graph, 'Shade Saturation', hsv.outputs[1], (.25, .5), 'VECTOR')
    value = curve(graph, 'Shade Value', hsv.outputs[2], (.625, .25), 'AUTO')
    combine = graph.node('ShaderNodeCombineColor', 'Shade HSV')
    combine.mode = 'HSV'
    for source, socket in zip((hsv.outputs[0], saturation, value), combine.inputs):
        graph.link(source, socket)
    shade = graph.mix(combine.outputs[0], inputs.outputs['Shadow Tint'], mode='MULTIPLY')
    graph.link(inputs.outputs['Base'], outputs.inputs['Lit'])
    graph.link(shade, outputs.inputs['Shade'])
    for index, node in enumerate(tree.nodes):
        node.location = ((index // 4) * 260, -(index % 4) * 180)
    return tree


def body(graph, base_color, role, profile, cache):
    sun = graph.node('ShaderNodeAttribute', 'HZZ Body Sun')
    sun.attribute_name = 'HZZ_SUN'
    surface = graph.node('ShaderNodeNewGeometry', 'Body Surface')
    dot = graph.vector('DOT_PRODUCT', surface.outputs['Normal'], sun.outputs['Vector'])
    position = graph.value('HZZ Shadow Position', profile.shadow_position)
    softness = graph.value('HZZ Shadow Softness', profile.shadow_softness)
    shift = graph.value('HZZ Hair Shadow Shift', profile.hair_shadow_shift if role == 'HAIR' else 0)
    boundary = graph.math('ADD', position, shift)
    band = graph.smooth(dot, graph.math('SUBTRACT', boundary, softness), graph.math('ADD', boundary, softness))
    band.node.name = 'HZZ Key Band'
    band.node.label = 'HZZ Key Band'
    # Face the receiver toward the key so visibility is not a second Lambert.
    diffuse = graph.node('ShaderNodeBsdfDiffuse', 'Body Light Receiver')
    diffuse.inputs['Color'].default_value = (1, 1, 1, 1)
    graph.link(sun.outputs['Vector'], diffuse.inputs['Normal'])
    received = graph.node('ShaderNodeShaderToRGB', 'Body Received Light')
    graph.link(diffuse.outputs[0], received.inputs[0])
    luminance = graph.gray(received.outputs['Color'])
    gate = graph.node('ShaderNodeMath', 'Body Visibility and Intensity')
    gate.operation, gate.use_clamp = 'MULTIPLY', True
    graph.link(luminance, gate.inputs[0])
    gate.inputs[1].default_value = 1
    lit = graph.math('MULTIPLY', band, gate.outputs[0])
    # Retain the sampled light's chromaticity instead of throwing all RGB away.
    safe = graph.math('MAXIMUM', luminance, .001)
    chroma = graph.mix(received.outputs['Color'], safe, mode='DIVIDE')
    strength = graph.value('HZZ Light Color Strength', profile.light_color_strength)
    light_color = graph.mix((1, 1, 1, 1), chroma, strength)
    if 'palette' not in cache.groups:
        cache.groups['palette'] = palette(profile.uid)
    colors = graph.node('ShaderNodeGroup', 'HZZ Lit and Shade')
    colors.node_tree = cache.groups['palette']
    graph.link(base_color, colors.inputs['Base'])
    tint = graph.color('HZZ Body Shadow Color', profile.body_shadow_color)
    graph.link(tint, colors.inputs['Shadow Tint'])
    color = graph.mix(colors.outputs['Shade'], colors.outputs['Lit'], lit)
    return lit, color, light_color
