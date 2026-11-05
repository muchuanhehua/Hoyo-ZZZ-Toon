"""Per-material inverted hulls with original PMX vertex edge multipliers."""
import bpy
from .materials.graph import Graph
from .ownership import tag
from .controllers import set_modifier

DEFAULT_WIDTH_RATIO = .0015
VERSION = 2
SCALES = (('Face Scale', 'outline_face_scale'), ('Skin Scale', 'outline_skin_scale'),
          ('Hair Scale', 'outline_hair_scale'))


def camera_offset(g, geometry, normal, width, inputs):
    """Bound an evaluated hull in camera space; keep PMX widths as authority.

    Camera-plane projection and optical/local caps adapted from RandomPlayToon
    feature_extension.py, commit 87ebc01d (GPL-3.0). Fields evaluate on the
    selected material geometry so edge indices cannot address a different mesh.
    """
    camera = g.node('GeometryNodeInputActiveCamera', 'Render Camera')
    optics = g.node('GeometryNodeCameraInfo', 'Camera Optics')
    g.link(camera.outputs[0], optics.inputs['Camera'])
    info = g.node('GeometryNodeObjectInfo', 'Camera In Mesh Space')
    info.transform_space = 'RELATIVE'
    g.link(camera.outputs[0], info.inputs['Object'])
    axis = g.node('FunctionNodeRotateVector', 'Camera Axis')
    axis.inputs['Vector'].default_value = (0, 0, 1)
    g.link(info.outputs['Rotation'], axis.inputs['Rotation'])
    position = g.node('GeometryNodeInputPosition', 'Deformed Position').outputs[0]
    ray = g.vector('SUBTRACT', info.outputs['Location'], position)
    view = g.node('GeometryNodeSwitch', 'Perspective Or Orthographic')
    view.input_type = 'VECTOR'
    g.link(optics.outputs['Is Orthographic'], view.inputs['Switch'])
    g.link(g.vector('NORMALIZE', ray), view.inputs['False'])
    g.link(axis.outputs[0], view.inputs['True'])
    direction = g.vector('NORMALIZE', view.outputs[0])
    projected = g.vector('SUBTRACT', normal, g.vector('SCALE', direction,
        scale=g.vector('DOT_PRODUCT', normal, direction)))
    edges = g.node('GeometryNodeInputMeshEdgeVertices', 'Local Edge Positions')
    length = g.vector('DISTANCE', edges.outputs['Position 1'], edges.outputs['Position 2'])
    index = g.node('GeometryNodeInputIndex', 'Hull Vertex')
    incident = g.node('GeometryNodeEdgesOfVertex', 'Shortest Incident Edge')
    g.link(index.outputs[0], incident.inputs['Vertex Index'])
    g.link(length, incident.inputs['Weights'])
    sample = g.node('GeometryNodeSampleIndex', 'Local Edge Clearance')
    sample.data_type, sample.domain, sample.clamp = 'FLOAT', 'EDGE', True
    g.link(geometry, sample.inputs['Geometry'])
    g.link(length, sample.inputs['Value'])
    g.link(incident.outputs['Edge Index'], sample.inputs['Index'])
    local_cap = g.math('MULTIPLY', sample.outputs['Value'], .22)
    sensor = g.node('ShaderNodeSeparateXYZ', 'Sensor Size')
    g.link(optics.outputs['Sensor'], sensor.inputs[0])
    depth = g.math('ABSOLUTE', g.vector('DOT_PRODUCT', ray, axis.outputs[0]))
    extent = g.math('MULTIPLY', depth,
        g.math('DIVIDE', sensor.outputs[0], g.math('MAXIMUM', optics.outputs['Focal Length'], .001)))
    self_object = g.node('GeometryNodeSelfObject', 'Hull Object')
    scale = g.node('GeometryNodeObjectInfo', 'World Object Scale')
    scale.transform_space = 'ORIGINAL'
    g.link(self_object.outputs[0], scale.inputs['Object'])
    components = g.node('ShaderNodeSeparateXYZ', 'Object Scale')
    g.link(scale.outputs['Scale'], components.inputs[0])
    ortho = g.math('DIVIDE', optics.outputs['Orthographic Scale'],
        g.math('MAXIMUM', g.math('ABSOLUTE', components.outputs[0]), .0001))
    span = g.node('GeometryNodeSwitch', 'Camera Image Extent')
    span.input_type = 'FLOAT'
    g.link(optics.outputs['Is Orthographic'], span.inputs['Switch'])
    g.link(extent, span.inputs['False'])
    g.link(ortho, span.inputs['True'])
    pixel_cap = g.math('MULTIPLY', inputs['Pixel Cap'],
        g.math('DIVIDE', span.outputs[0], g.math('MAXIMUM', inputs['Render Extent'], 1)))
    bounded = g.math('MINIMUM', width, g.math('MINIMUM', local_cap, pixel_cap))
    switch = g.node('GeometryNodeSwitch', 'Camera Constrained Outline')
    switch.input_type = 'VECTOR'
    g.link(inputs['Camera Bound'], switch.inputs['Switch'])
    g.link(g.vector('SCALE', normal, scale=width), switch.inputs['False'])
    g.link(g.vector('SCALE', projected, scale=bounded), switch.inputs['True'])
    return switch.outputs[0]


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
    for name, kind, default in (('Camera Bound', 'NodeSocketBool', True),
        ('Pixel Cap', 'NodeSocketFloat', profile.outline_pixel_cap)):
        socket = tree.interface.new_socket(name=name, in_out='INPUT', socket_type=kind)
        socket.default_value = default
    graph = Graph(tree)
    source = graph.node('NodeGroupInput', 'Input')
    fields = {socket.name: socket for socket in source.outputs}
    fields['Render Extent'] = graph.value('HZZ Effective Render Extent', 1280)
    driver = fields['Render Extent'].driver_add('default_value').driver
    for key, field in (('x', 'resolution_x'), ('y', 'resolution_y'), ('pct', 'resolution_percentage'),
                       ('ax', 'pixel_aspect_x'), ('ay', 'pixel_aspect_y')):
        variable = driver.variables.new()
        variable.name, variable.type = key, 'SINGLE_PROP'
        variable.targets[0].id_type = 'SCENE'
        variable.targets[0].id = bpy.context.scene
        variable.targets[0].data_path = 'render.' + field
    driver.expression = 'max(x,y*ay/max(ax,0.001))*max(pct,1)/100'
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
        offset = camera_offset(graph, separate.outputs['Selection'], normal.outputs['Normal'], amount, fields)
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
    set_modifier(modifier, 'Camera Bound', profile.outline_camera_bound)
    set_modifier(modifier, 'Pixel Cap', profile.outline_pixel_cap)
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
