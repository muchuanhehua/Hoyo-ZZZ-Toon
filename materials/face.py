"""Shared face SDF sampling and native light reception, with owned node data."""
from pathlib import Path
import bpy
from .graph import Graph
from ..ownership import tag

CURVE_POINTS = ((-4.0978193283081055e-08, 0, 'AUTO'), (.25, .5, 'VECTOR'),
                (.346591055393219, .5125005841255188, 'VECTOR'), (1, 2, 'VECTOR'))
KERNEL_VERSION = 1


def validate_image(image):
    if image is None:
        raise ValueError('SDF 模式需要指定已核对资源对应和 UV 的 Face Lightmap')
    if image.get('hzz_owner'):
        raise ValueError('请选择源 Face Lightmap，不要选择插件生成的图像')
    if image.source not in {'FILE', 'GENERATED'}:
        raise ValueError('Face Lightmap 必须为本地文件图像或生成图像')
    if image.source == 'FILE' and not image.packed_file:
        path = Path(bpy.path.abspath(image.filepath, library=image.library))
        if not path.is_file():
            raise ValueError(f'缺少 Face Lightmap：{path}')
    if min(image.size) <= 0 or image.channels != 4:
        raise ValueError('Face Lightmap 需要可读取的 RGBA 数据，R 和 Alpha 均参与脸影')


def signature(node):
    node.input_items.clear()
    node.output_items.clear()
    node.input_items.new('VECTOR', 'Vector')
    node.output_items.new('RGBA', 'Color')
    node.output_items.new('FLOAT', 'Alpha')


def sampler(graph, image):
    end = graph.node('NodeClosureOutput', 'Face Lightmap Sampler')
    signature(end)
    start = graph.node('NodeClosureInput', 'Face Lightmap Coordinates')
    if not start.pair_with_output(end):
        raise RuntimeError('无法创建 Face Lightmap 采样接口')
    tex = graph.node('ShaderNodeTexImage', 'Face Lightmap Data')
    tex.image, tex.interpolation, tex.extension = image, 'Linear', 'REPEAT'
    graph.link(start.outputs['Vector'], tex.inputs['Vector'])
    graph.link(tex.outputs['Color'], end.inputs['Color'])
    graph.link(tex.outputs['Alpha'], end.inputs['Alpha'])
    return end.outputs['Closure']


def remap(graph, value, limits):
    node = graph.node('ShaderNodeMapRange', 'Face SDF Transition')
    node.clamp, node.interpolation_type = True, 'LINEAR'
    graph.link(value, node.inputs['Value'])
    for name, number in zip(('From Min', 'From Max', 'To Min', 'To Max'), limits):
        node.inputs[name].default_value = number
    return node.outputs['Result']


def kernel(uid):
    tree = tag(bpy.data.node_groups.new('HZZ • Shared Face SDF', 'ShaderNodeTree'), uid)
    tree['hzz_kind'], tree['hzz_sdf_version'] = 'face_sdf', KERNEL_VERSION
    for name, kind in (('Sampler', 'NodeSocketClosure'), ('UV', 'NodeSocketVector'),
                       ('Front', 'NodeSocketVector'), ('Right', 'NodeSocketVector'), ('Light', 'NodeSocketVector')):
        tree.interface.new_socket(name=name, in_out='INPUT', socket_type=kind)
    for name, kind in (('Lit', 'NodeSocketFloat'), ('R', 'NodeSocketFloat'), ('Alpha', 'NodeSocketFloat'),
                       ('Q', 'NodeSocketFloat'), ('Front Dot', 'NodeSocketFloat'), ('Sample UV', 'NodeSocketVector')):
        tree.interface.new_socket(name=name, in_out='OUTPUT', socket_type=kind)
    graph = Graph(tree)
    source, output = graph.node('NodeGroupInput', 'Inputs'), graph.node('NodeGroupOutput', 'Outputs')
    # Hoyo uses physical front/right; the reference math uses back/left.
    front_dot = graph.vector('DOT_PRODUCT', graph.vector('SCALE', source.outputs['Front'], scale=-1), source.outputs['Light'])
    right_dot = graph.vector('DOT_PRODUCT', graph.vector('SCALE', source.outputs['Right'], scale=-1), source.outputs['Light'])
    sign = graph.math('SUBTRACT', graph.math('MULTIPLY', graph.math('GREATER_THAN', right_dot, 0), 2), 1)
    uv = graph.node('ShaderNodeSeparateXYZ', 'UV Components')
    graph.link(source.outputs['UV'], uv.inputs[0])
    coordinates = graph.combine(graph.math('MULTIPLY', uv.outputs['X'], sign), uv.outputs['Y'], uv.outputs['Z'])
    evaluate = graph.node('NodeEvaluateClosure', 'Evaluate Face Lightmap')
    evaluate.define_signature = True
    signature(evaluate)
    graph.link(source.outputs['Sampler'], evaluate.inputs['Closure'])
    graph.link(coordinates, evaluate.inputs['Vector'])
    separate = graph.node('ShaderNodeSeparateColor', 'Face Lightmap Channels')
    graph.link(evaluate.outputs['Color'], separate.inputs['Color'])
    curve = graph.node('ShaderNodeFloatCurve', 'Shared Face Direction Curve')
    mapping = curve.mapping
    mapping.initialize()
    mapping.extend, mapping.use_clip = 'EXTRAPOLATED', True
    mapping.clip_min_x, mapping.clip_min_y, mapping.clip_max_x, mapping.clip_max_y = -.25, 0, 1, 2
    points = mapping.curves[0].points
    points[0].location, points[-1].location = CURVE_POINTS[0][:2], CURVE_POINTS[-1][:2]
    for x, y, _ in CURVE_POINTS[1:-1]:
        points.new(x, y)
    for point, (_, _, handle) in zip(points, CURVE_POINTS):
        point.handle_type = handle
    mapping.update()
    graph.link(front_dot, curve.inputs['Value'])
    subtract = graph.node('ShaderNodeMath', 'Face SDF Difference')
    subtract.operation, subtract.use_clamp = 'SUBTRACT', True
    graph.link(graph.math('MULTIPLY', separate.outputs['Red'], 2), subtract.inputs[0])
    graph.link(curve.outputs[0], subtract.inputs[1])
    q = graph.math('MULTIPLY', subtract.outputs[0], evaluate.outputs['Alpha'])
    lit = graph.math('MULTIPLY', remap(graph, q, (.35, .4, 0, 1)), remap(graph, q, (.35, 1, .75, 1)))
    for name, value in (('Lit', lit), ('R', separate.outputs['Red']), ('Alpha', evaluate.outputs['Alpha']),
                        ('Q', q), ('Front Dot', front_dot), ('Sample UV', coordinates)):
        graph.link(value, output.inputs[name])
    for i, node in enumerate(tree.nodes):
        node.location = ((i // 6) * 240, -(i % 6) * 180)
    return tree


def lighting(graph, uv, profile, cache):
    if 'face_sdf' not in cache.groups:
        cache.groups['face_sdf'] = kernel(profile.uid)
    node = graph.node('ShaderNodeGroup', 'HZZ Face SDF')
    node.node_tree = cache.groups['face_sdf']
    graph.link(uv, node.inputs['UV'])
    directions = {}
    for socket, name in (('Front', 'HZZ_FRONT'), ('Right', 'HZZ_RIGHT'), ('Light', 'HZZ_SUN')):
        attr = graph.node('ShaderNodeAttribute', name)
        attr.attribute_name = name
        directions[name] = attr.outputs['Vector']
        graph.link(attr.outputs['Vector'], node.inputs[socket])
    image = cache.load(profile.face_lightmap, colorspace='Non-Color', alpha_mode='CHANNEL_PACKED')
    graph.link(sampler(graph, image), node.inputs['Sampler'])
    # Return native reception separately so face and body share visibility and chroma.
    diffuse = graph.node('ShaderNodeBsdfDiffuse', 'Face Sun-facing Receiver')
    diffuse.inputs['Color'].default_value = (1, 1, 1, 1)
    graph.link(directions['HZZ_SUN'], diffuse.inputs['Normal'])
    sample = graph.node('ShaderNodeShaderToRGB', 'Face Received Light')
    graph.link(diffuse.outputs[0], sample.inputs[0])
    return node.outputs['Lit'], sample.outputs['Color']
