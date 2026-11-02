"""Assemble albedo, shading, responses and coverage without changing source data."""
import bpy
from .graph import Graph
from .images import ImageCache
from . import face, responses, surface
from ..adapters.pmx import UNLIT
from ..ownership import tag


def texture(graph, image, vector, name):
    node = graph.node('ShaderNodeTexImage', name)
    node.image = image
    graph.link(vector, node.inputs['Vector'])
    return node


def layout(tree):
    for index, node in enumerate(tree.nodes):
        node.location = ((index // 6) * 240, -(index % 6) * 180)


def material_name(source, role):
    return f'HZZ • {source.name} • {role}'


def build(data, binding, profile, cache, surface_plan=None):
    material = tag(bpy.data.materials.new(material_name(data.source, data.role)), profile.uid)
    material.use_nodes = True
    material['hzz_role'] = data.role
    material['hzz_source'] = data.source.name
    material['hzz_face_mode'] = profile.face_mode if data.role == 'FACE' else 'NONE'
    material.node_tree.nodes.clear()
    graph = Graph(material.node_tree)
    uv = graph.uv(data.uv)
    base = texture(graph, cache.load(data.textures['base']), uv, 'PMX Base Color') if 'base' in data.textures else None
    color = base.outputs['Color'] if base else (1, 1, 1, 1)
    source_color = graph.color('PMX Diffuse', data.diffuse)
    color = graph.mix(color, source_color, mode='MULTIPLY')
    tint = graph.color('HZZ Tint', binding.tint)
    color = graph.mix(color, tint, mode='MULTIPLY')
    alpha_value = graph.value('PMX Alpha', data.alpha)
    alpha = graph.math('MULTIPLY', base.outputs['Alpha'], alpha_value) if base else alpha_value
    if data.role == 'OVERLAY':
        alpha = graph.math('MULTIPLY', alpha, graph.gray(color))
    if data.role not in UNLIT:
        if data.role == 'FACE':
            color = face_color(graph, color, uv, data, profile, cache)
        else:
            color = body_color(graph, color, data, profile, cache, surface_plan)
    if 'sphere' in data.textures:
        color = responses.sphere(graph, color, data, cache.load(data.textures['sphere']), texture)
    graph.surface(color, alpha)
    transparent = data.alpha < 1 or data.role == 'OVERLAY' or (base and cache.alpha_min(base.image) < 1)
    # An atlas can contain transparent pixels outside the iris UVs. Opaque
    # eye surfaces still need a depth-writing coverage pass: Blended overlap
    # can otherwise paint the rear sclera over the iris on the same mesh.
    depth_eye = data.role in {'EYE', 'WHITE'} and data.alpha >= .999
    # Independent hair surfaces need depth coverage for overlapping strands.
    # Coincident fur/highlight decals retain blending; their depth equals the
    # backing surface, so a dithered pass can expose black or lose the decal.
    hair_decal = data.role == 'HAIR' and data.coplanar_faces > 0 and transparent
    depth_hair = data.role == 'HAIR' and not hair_decal
    material.surface_render_method = 'DITHERED' if depth_eye or depth_hair else ('BLENDED' if transparent else 'DITHERED')
    material['hzz_coplanar_faces'] = data.coplanar_faces
    material['hzz_coverage'] = 'COPLANAR_OVERLAY' if hair_decal else ('HAIR_DEPTH' if depth_hair else 'DEFAULT')
    material.use_transparency_overlap = data.role in UNLIT
    material.use_backface_culling = not data.double_sided
    layout(material.node_tree)
    return material


def toon(graph, data, cache, lit):
    node = texture(graph, cache.load(data.textures['toon']), graph.combine(.5, lit), 'PMX Toon')
    node.extension = 'EXTEND'
    return node.outputs['Color']


def face_color(graph, color, uv, data, profile, cache):
    if profile.face_mode == 'SDF':
        lit = face.lighting(graph, uv, profile, cache)
    else:
        factor = lighting(graph, 'FACE')
        position = graph.value('HZZ Shadow Position', profile.shadow_position)
        softness = graph.value('HZZ Shadow Softness', profile.shadow_softness)
        lit = graph.smooth(factor, graph.math('SUBTRACT', position, softness), graph.math('ADD', position, softness))
    shadow = graph.color('HZZ Shadow Color', profile.shadow_color)
    color = graph.mix(color, graph.mix(shadow, (1, 1, 1, 1), lit), mode='MULTIPLY')
    if 'toon' in data.textures:
        color = graph.mix(color, toon(graph, data, cache, lit), mode='MULTIPLY')
    color = graph.mix(color, graph.color('HZZ Face Key Color', profile.face_key_color), mode='MULTIPLY')
    return color


def body_color(graph, albedo, data, profile, cache, plan):
    lit, color = surface.build(graph, albedo, data, profile, cache, plan)
    if 'toon' in data.textures:
        source_shade = graph.mix(albedo, toon(graph, data, cache, lit), mode='MULTIPLY')
        strength = graph.value('HZZ PMX Toon Strength', profile.pmx_toon_strength)
        color = graph.mix(color, source_shade, strength)
    return color


def lighting(graph, role):
    if role == 'FACE':
        # A controllable generic face approximation. No character SDF is implied.
        attributes = {}
        for name in ('HZZ_SUN', 'HZZ_FRONT'):
            node = graph.node('ShaderNodeAttribute', name)
            node.attribute_name = name
            attributes[name] = node.outputs['Vector']
        geometry = graph.node('ShaderNodeNewGeometry', 'Face Surface')
        normal = graph.vector('NORMALIZE', graph.vector('ADD',
            graph.vector('SCALE', geometry.outputs['Normal'], scale=.65),
            graph.vector('SCALE', attributes['HZZ_FRONT'], scale=.35)))
        dot = graph.vector('DOT_PRODUCT', normal, attributes['HZZ_SUN'])
        direction = graph.math('ADD', graph.math('MULTIPLY', dot, .5), .5)
        # Shape the face once. Native reception supplies visibility; using the
        # mesh normal again would darken the whole face before the Toon ramp.
        actual = actual_lighting(graph, attributes['HZZ_SUN'])
        return graph.math('MINIMUM', direction, actual)
    return actual_lighting(graph)


def actual_lighting(graph, normal=None):
    diffuse = graph.node('ShaderNodeBsdfDiffuse', 'Native Diffuse Lighting')
    diffuse.inputs['Color'].default_value = (1, 1, 1, 1)
    if normal is not None:
        graph.link(normal, diffuse.inputs['Normal'])
    sample = graph.node('ShaderNodeShaderToRGB', 'Native Light And Shadow')
    graph.link(diffuse.outputs[0], sample.inputs[0])
    return graph.gray(sample.outputs['Color'])


def build_outline(data, profile, cache):
    material = tag(bpy.data.materials.new(material_name(data.source, 'Outline')), profile.uid)
    material.use_nodes = True
    material.node_tree.nodes.clear()
    graph = Graph(material.node_tree)
    color = (*data.edge_color[:3], 1)
    albedo = (*data.diffuse[:3], 1)
    alpha = data.alpha * data.edge_color[3]
    if 'base' in data.textures:
        base = texture(graph, cache.load(data.textures['base']), graph.uv(data.uv), 'PMX Outline Coverage')
        alpha = graph.math('MULTIPLY', base.outputs['Alpha'], alpha)
        albedo = graph.mix(base.outputs['Color'], albedo, mode='MULTIPLY')
    follow = graph.value('HZZ Outline Color Mix', profile.outline_color_mix)
    color = graph.mix(color, albedo, follow)
    # Skin contours use a warm ink; other surfaces share a cool, darker ink.
    # The source atlas supplies colour only. PMX Alpha still controls coverage.
    tint = (2, .55, .75, 1) if data.role == 'FACE' or surface.skin(data) else (.58, .54, .82, 1)
    color = graph.mix(color, tint, mode='MULTIPLY')
    color = graph.mix(color, graph.value('HZZ Outline Brightness', profile.outline_brightness), mode='MULTIPLY')
    emission = graph.node('ShaderNodeEmission', 'Outline Color')
    graph.link(color, emission.inputs['Color'])
    transparent = graph.node('ShaderNodeBsdfTransparent', 'No Outline Shadow')
    light_path = graph.node('ShaderNodeLightPath', 'Outline Ray')
    coverage = graph.math('MULTIPLY', alpha, graph.math('SUBTRACT', 1, light_path.outputs['Is Shadow Ray']))
    mix = graph.node('ShaderNodeMixShader', 'Outline Coverage')
    graph.link(coverage, mix.inputs[0])
    graph.link(transparent.outputs[0], mix.inputs[1])
    graph.link(emission.outputs[0], mix.inputs[2])
    output = graph.node('ShaderNodeOutputMaterial', 'Material Output')
    graph.link(mix.outputs[0], output.inputs['Surface'])
    material.use_backface_culling = True
    material.surface_render_method = 'DITHERED'
    layout(material.node_tree)
    return material


def refresh(material, binding, profile):
    nodes = material.node_tree.nodes
    nodes['HZZ Tint'].outputs[0].default_value = (*binding.tint, 1)
    if material.node_tree.get('hzz_body_version', 0) >= 2:
        surface.refresh(material, profile)
        if 'HZZ PMX Toon Strength' in nodes:
            nodes['HZZ PMX Toon Strength'].outputs[0].default_value = profile.pmx_toon_strength
        return
    if material['hzz_role'] not in UNLIT:
        if material.get('hzz_face_mode') != 'SDF':
            nodes['HZZ Shadow Position'].outputs[0].default_value = profile.shadow_position
            nodes['HZZ Shadow Softness'].outputs[0].default_value = profile.shadow_softness
        if material['hzz_role'] == 'FACE':
            nodes['HZZ Shadow Color'].outputs[0].default_value = (*profile.shadow_color, 1)
            if 'HZZ Face Key Color' in nodes:
                nodes['HZZ Face Key Color'].outputs[0].default_value = (*profile.face_key_color, 1)
        else:
            nodes['HZZ Specular'].outputs[0].default_value = profile.specular * (1.5 if material['hzz_role'] == 'HAIR' else 1)
            # Saved 0.2 materials remain editable until the explicit reapply.
            # workflow.refresh reports that the new body pipeline is pending.
            if not material.node_tree.get('hzz_body_version'):
                nodes['HZZ Shadow Color'].outputs[0].default_value = (*profile.shadow_color, 1)
                return
            nodes['HZZ Body Shadow Color'].outputs[0].default_value = (*profile.body_shadow_color, 1)
            nodes['HZZ Light Color Strength'].outputs[0].default_value = profile.light_color_strength
            nodes['HZZ Hair Shadow Shift'].outputs[0].default_value = profile.hair_shadow_shift if material['hzz_role'] == 'HAIR' else 0
            if 'HZZ PMX Toon Strength' in nodes:
                nodes['HZZ PMX Toon Strength'].outputs[0].default_value = profile.pmx_toon_strength
