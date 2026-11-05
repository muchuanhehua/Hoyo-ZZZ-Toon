"""Automatic rest-space bangs and premultiplied eye AOVs, without source edits.

Selective eye/depth composition follows RandomPlayToon effects/layers.py,
87ebc01de7c6a1ab4796b7da7196b88830d74667 (GPL-3.0). Head-frame inference,
multi-mesh input and reversible scene integration are local implementations.
"""
import math
import unicodedata
import re
import bpy
from mathutils import Vector, Matrix
from . import controllers
from .materials.graph import Graph
from .ownership import tag

BANGS = 'HZZ_AUTO_BANGS'
EYES = {'EYE', 'WHITE', 'HIGHLIGHT'}


def blink_side(name):
    """Standard MMD/English expression semantics, never character identities."""
    name = re.sub(r'[\s_.-]', '', unicodedata.normalize('NFKC', name).casefold())
    if name in {'まばたき', '瞬き', '瞬目', '眨眼', '闭眼', '両目閉じ', 'blink', 'eyeclose', 'eyesclosed', 'closeeyes'}:
        return 'BOTH'
    if name in {'ウィンク', 'ウィンク2', '左ウィンク', '左目閉じ', '左眼闭', 'winkl', 'winkleft', 'blinkl', 'blinkleft', 'eyeclosel'}:
        return 'LEFT'
    if name in {'ウィンク右', 'ウィンク2右', '右ウィンク', '右目閉じ', '右眼闭', 'winkr', 'winkright', 'blinkr', 'blinkright', 'eyecloser'}:
        return 'RIGHT'


def bind_blink(material, keys):
    graph = Graph(material.node_tree)
    coords = material.node_tree.nodes['HZZ Eye Socket Position'].outputs['X']
    side_values = []
    for side in ('LEFT', 'RIGHT'):
        value = graph.value('HZZ Eye ' + side + ' Openness', 1)
        groups = []
        variables = []
        for key_data in keys:
            group = []
            for key in key_data.key_blocks:
                if blink_side(key.name) in {'BOTH', side}:
                    name = 'b' + str(len(variables))
                    variables.append((name, key_data, key.path_from_id('value')))
                    group.append(name)
            if group:
                groups.append('(' + '+'.join(group) + ')')
        if variables:
            driver = value.driver_add('default_value').driver
            driver.type = 'SCRIPTED'
            for name, key_data, path in variables:
                variable = driver.variables.new()
                variable.name, variable.type = name, 'SINGLE_PROP'
                variable.targets[0].id_type = 'KEY'
                variable.targets[0].id, variable.targets[0].data_path = key_data, path
            closed = 'max(' + ','.join(groups) + ')' if len(groups) > 1 else groups[0]
            driver.expression = 'min(1,max(0,1-' + closed + '))'
        side_values.append(value)
    selected = graph.mix(side_values[0], side_values[1], graph.math('GREATER_THAN', coords, 0))
    opacity = material.node_tree.nodes['HZZ Eye Support Alpha']
    graph.link(selected, opacity.inputs[1])


def aov_names(uid):
    return {kind: 'HZZ_' + uid + '_' + kind for kind in ('Hair', 'Eye', 'Color')}


def drive(socket, root, property_name):
    driver = socket.driver_add('default_value').driver
    variable = driver.variables.new()
    variable.name, variable.type = 'v', 'SINGLE_PROP'
    variable.targets[0].id = root
    variable.targets[0].data_path = 'hzz_character.' + property_name
    driver.expression = 'v'


def controls(g, root, name):
    output = g.value('HZZ Eye ' + name, getattr(root.hzz_character, name))
    drive(output, root, name)
    return output


def shader(graph, color, alpha, data, profile):
    names = aov_names(profile.uid)
    root = profile.id_data
    if data.role in EYES | {'BROW'}:
        if data.role in EYES:
            # Some PMX sclera meshes also contain forehead/eyelid patches.
            # Bound eye support in the live head frame, including blink morphs.
            coordinates = graph.node('ShaderNodeTexCoord', 'HZZ Eye Head Coordinates')
            components = graph.node('ShaderNodeSeparateXYZ', 'HZZ Eye Socket Position')
            graph.link(coordinates.outputs['Object'], components.inputs[0])
            region = 1
            for axis in ('X', 'Z'):
                lower = graph.value('HZZ Eye ' + axis + ' Min', 1)
                upper = graph.value('HZZ Eye ' + axis + ' Max', -1)
                inside = graph.math('MULTIPLY', graph.math('GREATER_THAN', components.outputs[axis], lower),
                    graph.math('LESS_THAN', components.outputs[axis], upper))
                region = graph.math('MULTIPLY', region, inside)
            alpha = graph.math('MULTIPLY', alpha, region)
            support_alpha = graph.node('ShaderNodeMath', 'HZZ Eye Support Alpha')
            support_alpha.operation = 'MULTIPLY'
            graph.link(alpha, support_alpha.inputs[0])
            support_alpha.inputs[1].default_value = 1
            alpha = support_alpha.outputs[0]
        support = graph.math('MULTIPLY', alpha,
            controls(graph, root, 'eye_brow_strength') if data.role == 'BROW' else 1)
        for kind, value in (('Eye', support), ('Color', graph.vector('SCALE', color, scale=support))):
            node = graph.node('ShaderNodeOutputAOV', 'HZZ Eye ' + kind)
            node.aov_name = names[kind]
            graph.link(value, node.inputs['Color'])
    elif data.role == 'HAIR':
        attribute = graph.node('ShaderNodeAttribute', 'HZZ Front Bangs')
        attribute.attribute_name = BANGS
        front = graph.node('ShaderNodeAttribute', 'HZZ Head Front')
        front.attribute_name = 'HZZ_FRONT'
        geometry = graph.node('ShaderNodeNewGeometry', 'HZZ Eye View')
        cosine = graph.vector('DOT_PRODUCT', front.outputs['Vector'], geometry.outputs['Incoming'])
        start = controls(graph, root, 'eye_front_angle')
        end = controls(graph, root, 'eye_side_angle')
        # Enforce a nonempty fade range even when sliders cross.
        end = graph.math('MAXIMUM', end, graph.math('ADD', start, 1))
        fade = graph.smooth(cosine,
            graph.math('COSINE', graph.math('MULTIPLY', end, math.pi / 180)),
            graph.math('COSINE', graph.math('MULTIPLY', start, math.pi / 180)))
        node = graph.node('ShaderNodeOutputAOV', 'HZZ Eye Hair')
        node.aov_name = names['Hair']
        graph.link(graph.math('MULTIPLY', attribute.outputs['Fac'], graph.math('MULTIPLY', alpha, fade)), node.inputs['Color'])


def author(profile, pending, descriptions, head):
    """Use source rest geometry in the calibrated head basis, never face indices."""
    frame, basis = controllers.rest_frame(profile)
    frame = frame @ Matrix.Rotation(profile.head_yaw, 4, 'Z')
    inverse = frame.inverted()
    faces, eyes, irises, rows = [], [], [], []
    for item in pending:
        entry, mesh = item['entry'], item['mesh']
        matrix = inverse @ entry.object.matrix_world
        coords = [matrix @ vertex.co for vertex in mesh.vertices]
        roles = {state.index: descriptions[state.material.as_pointer()].role
                 for state in entry.slots if state.material}
        rows.append((mesh, coords, roles))
        for polygon in mesh.polygons:
            role = roles.get(polygon.material_index)
            target = faces if role == 'FACE' else eyes if role in {'EYE', 'WHITE'} else None
            if target is not None:
                target.extend(coords[i] for i in polygon.vertices)
            if role == 'EYE':
                irises.extend(coords[i] for i in polygon.vertices)
    if not faces or not eyes:
        return {'status': 'unavailable', 'reason': '缺少已识别的脸或眼部，未启用透眼', 'bang_faces': 0}
    low = Vector(tuple(min(p[i] for p in faces) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in faces) for i in range(3)))
    width, height = high.x - low.x, high.z - low.z
    center = (low.x + high.x) * .5
    eye_front = sorted(p.y for p in eyes)[len(eyes) // 2]
    if min(width, height) <= profile.height * .001:
        return {'status': 'unavailable', 'reason': '脸部范围不足，未启用透眼', 'bang_faces': 0}
    if not irises:
        return {'status': 'unavailable', 'reason': '缺少虹膜区域，未启用透眼', 'bang_faces': 0}
    socket_bounds = {'X Min': min(p.x for p in irises) - width * .08,
                     'X Max': max(p.x for p in irises) + width * .08,
                     'Z Min': min(p.z for p in irises) - height * .06,
                     'Z Max': max(p.z for p in irises) + height * .06}
    materials = {material for item in pending for material in item['mesh'].materials if material}
    for material in materials:
        if material.get('hzz_owner') != profile.uid or not material.use_nodes:
            continue
        node = material.node_tree.nodes.get('HZZ Eye Head Coordinates')
        if node:
            node.object = head
            for name, value in socket_bounds.items():
                material.node_tree.nodes['HZZ Eye ' + name].outputs[0].default_value = value
            keys = {item['mesh'].shape_keys for item in pending
                    if material in tuple(item['mesh'].materials) and item['mesh'].shape_keys}
            bind_blink(material, keys)
    total = 0
    for mesh, coords, roles in rows:
        values = []
        for polygon in mesh.polygons:
            centerpoint = sum((coords[i] for i in polygon.vertices), Vector()) / len(polygon.vertices)
            selected = (roles.get(polygon.material_index) == 'HAIR'
                and centerpoint.y > eye_front - width * .04
                and abs(centerpoint.x - center) < width * .56
                and low.z < centerpoint.z < high.z + height * .35)
            values.append(selected)
        attribute = mesh.attributes.get(BANGS) or mesh.attributes.new(BANGS, 'BOOLEAN', 'FACE')
        attribute.data.foreach_set('value', values)
        total += sum(values)
    return {'status': 'ready' if total else 'unavailable', 'bang_faces': total, 'basis': basis,
            'reason': f'已自动识别 {total} 个刘海面；F12 查看完整透眼' if total else '未识别到遮眼前刘海，未启用透眼',
            'method': 'semantic face/eye envelope in calibrated rest head frame', 'socket_bounds': socket_bounds,
            'blink_keys': sorted({key.name for item in pending if item['mesh'].shape_keys
                for key in item['mesh'].shape_keys.key_blocks if blink_side(key.name)})}


def filter_bangs(uid):
    tree = tag(bpy.data.node_groups.new('HZZ • Remove Target Bangs', 'GeometryNodeTree'), uid, 'eye')
    for direction in ('INPUT', 'OUTPUT'):
        tree.interface.new_socket(name='Geometry', in_out=direction, socket_type='NodeSocketGeometry')
    graph = Graph(tree)
    source = graph.node('NodeGroupInput', 'Input')
    output = graph.node('NodeGroupOutput', 'Output')
    attr = graph.node('GeometryNodeInputNamedAttribute', 'Target Bangs')
    attr.data_type = 'BOOLEAN'
    attr.inputs['Name'].default_value = BANGS
    delete = graph.node('GeometryNodeDeleteGeometry', 'Remove Only Target Bangs')
    delete.domain, delete.mode = 'FACE', 'ALL'
    graph.link(source.outputs[0], delete.inputs['Geometry'])
    graph.link(attr.outputs['Attribute'], delete.inputs['Selection'])
    graph.link(delete.outputs[0], output.inputs[0])
    return tree
