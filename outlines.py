"""Per-material inverted hulls with original PMX vertex edge multipliers."""
import bpy
from .materials.graph import Graph
from .ownership import tag
from .controllers import set_modifier

DEFAULT_WIDTH_RATIO = .0015
VERSION = 1
SCALES = (('Face Scale', 'outline_face_scale'), ('Skin Scale', 'outline_skin_scale'),
          ('Hair Scale', 'outline_hair_scale'))


def build(profile, materials):
    if not materials:
        return None
    tree = tag(bpy.data.node_groups.new('HZZ • PMX Outlines', 'GeometryNodeTree'), profile.uid)
    tree['hzz_kind'] = 'outline'
    tree['hzz_outline_version'] = VERSION
    for name, direction, kind in (('Geometry', 'INPUT', 'NodeSocketGeometry'),
        ('Width', 'INPUT', 'NodeSocketFloat'), ('Geometry', 'OUTPUT', 'NodeSocketGeometry')):
        tree.interface.new_socket(name=name, in_out=direction, socket_type=kind)
    for name, property_name in SCALES:
        socket = tree.interface.new_socket(name=name, in_out='INPUT', socket_type='NodeSocketFloat')
        socket.default_value = getattr(profile, property_name)
    graph = Graph(tree)
    source = graph.node('NodeGroupInput', 'Input')
    output = graph.node('NodeGroupOutput', 'Output')
    join = graph.node('GeometryNodeJoinGeometry', 'Base And Hulls')
    graph.link(source.outputs['Geometry'], join.inputs['Geometry'])
    normal = graph.node('GeometryNodeInputNormal', 'Surface Normal')
    attribute = graph.node('GeometryNodeInputNamedAttribute', 'PMX Vertex Edge')
    attribute.data_type = 'FLOAT'
    attribute.inputs['Name'].default_value = 'hzz_edge_scale'
    width = graph.math('MULTIPLY', source.outputs['Width'], attribute.outputs['Attribute'])
    for material, outline, weight in materials:
        selection = graph.node('GeometryNodeMaterialSelection', material.name)
        selection.inputs['Material'].default_value = material
        separate = graph.node('GeometryNodeSeparateGeometry', 'Outlined Faces')
        separate.domain = 'FACE'
        graph.link(source.outputs['Geometry'], separate.inputs['Geometry'])
        graph.link(selection.outputs['Selection'], separate.inputs['Selection'])
        role = material['hzz_role']
        semantic = material.node_tree.get('hzz_surface_semantic')
        scale = 'Face Scale' if role == 'FACE' else 'Skin Scale' if semantic == 'SKIN' else 'Hair Scale' if role == 'HAIR' else None
        amount = graph.math('MULTIPLY', width, weight)
        if scale:
            amount = graph.math('MULTIPLY', amount, source.outputs[scale])
        offset = graph.vector('SCALE', normal.outputs['Normal'], scale=amount)
        position = graph.node('GeometryNodeSetPosition', 'Hull Expansion')
        graph.link(separate.outputs['Selection'], position.inputs['Geometry'])
        graph.link(offset, position.inputs['Offset'])
        flip = graph.node('GeometryNodeFlipFaces', 'Inverted Hull')
        graph.link(position.outputs['Geometry'], flip.inputs['Mesh'])
        assign = graph.node('GeometryNodeSetMaterial', 'Outline Material')
        assign.inputs['Material'].default_value = outline
        graph.link(flip.outputs['Mesh'], assign.inputs['Geometry'])
        graph.link(assign.outputs['Geometry'], join.inputs['Geometry'])
    graph.link(join.outputs['Geometry'], output.inputs['Geometry'])
    return tree


def update_modifier(modifier, profile):
    """Refresh shared controls; saved legacy hulls retain their old interface."""
    set_modifier(modifier, 'Width', profile.outline_width)
    tree = modifier.node_group
    if tree.get('hzz_outline_version') != VERSION:
        return
    for name, property_name in SCALES:
        set_modifier(modifier, name, getattr(profile, property_name))
    for node in tree.nodes:
        if node.bl_idname != 'GeometryNodeSetMaterial':
            continue
        material = node.inputs['Material'].default_value
        nodes = material.node_tree.nodes
        nodes['HZZ Outline Color Mix'].outputs[0].default_value = profile.outline_color_mix
        nodes['HZZ Outline Brightness'].outputs[0].default_value = profile.outline_brightness


def edge_attribute(obj, mesh):
    group = obj.vertex_groups.get('mmd_edge_scale')
    values = [1.0] * len(mesh.vertices)
    if group:
        values = [next((g.weight for g in v.groups if g.group == group.index), 0.0) for v in mesh.vertices]
    attribute = mesh.attributes.new(name='hzz_edge_scale', type='FLOAT', domain='POINT')
    attribute.data.foreach_set('value', values)
