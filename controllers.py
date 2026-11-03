"""A calibrated head frame and named world-space light/head vectors."""
import bpy
from mathutils import Matrix, Vector
from .materials.graph import Graph
from .adapters.pmx import find_bone
from .ownership import tag


def rest_frame(profile):
    rig = profile.rig
    if profile.head_bone not in rig.data.bones:
        raise ValueError('请在骨架中指定有效的头骨')
    left = find_bone(rig, ('左目', '左眼', 'eye.l', 'eye_l', 'lefteye', 'eye_l_01'))
    right = find_bone(rig, ('右目', '右眼', 'eye.r', 'eye_r', 'righteye', 'eye_r_01'))
    up = (rig.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
    if left and right:
        right_vector = rig.matrix_world.to_3x3() @ (rig.data.bones[right].head_local - rig.data.bones[left].head_local)
        basis = 'EYE_BONES'
    else:
        # MMD Tools converts PMX into a defined rig-local coordinate frame.
        # Keep this explicit and visible for valid rigs without eye bones.
        right_vector = rig.matrix_world.to_3x3() @ Vector((-1, 0, 0))
        basis = 'MMD_RIG_AXES'
    right_vector -= up * right_vector.dot(up)
    if right_vector.length < 1e-6:
        raise ValueError('无法从所选骨架建立有效头部方向')
    right_vector.normalize()
    front = up.cross(right_vector).normalized()
    origin = rig.matrix_world @ rig.data.bones[profile.head_bone].head_local
    frame = Matrix((right_vector, front, up)).transposed().to_4x4()
    frame.translation = origin
    return frame, basis


def create_head(root, context):
    p = root.hzz_character
    frame, basis = rest_frame(p)
    rig = p.rig
    head = tag(bpy.data.objects.new(root.name + ' • HZZ Head', None), p.uid)
    collection = root.users_collection[0] if root.users_collection else context.scene.collection
    collection.objects.link(head)
    if head.name not in context.scene.objects:
        context.scene.collection.objects.link(head)
    head.empty_display_type = 'ARROWS'
    head.empty_display_size = p.height * .05
    head.hide_render = True
    head['hzz_frame_basis'] = basis
    head.parent, head.parent_type, head.parent_bone = rig, 'BONE', p.head_bone
    context.view_layer.update()
    rest = rig.matrix_world @ rig.data.bones[p.head_bone].matrix_local
    pose = rig.matrix_world @ rig.pose.bones[p.head_bone].matrix
    head.matrix_world = pose @ rest.inverted() @ frame
    head['hzz_basis'] = [v for row in head.matrix_basis for v in row]
    update_head(head, p.head_yaw)
    return head


def update_head(head, yaw):
    values = head['hzz_basis']
    basis = Matrix([values[i:i + 4] for i in range(0, 16, 4)])
    head.matrix_basis = basis @ Matrix.Rotation(yaw, 4, 'Z')


def face_group(profile, head):
    tree = tag(bpy.data.node_groups.new('HZZ • Light Directions', 'GeometryNodeTree'), profile.uid)
    tree['hzz_kind'] = 'face'
    for name, direction, kind in (('Geometry', 'INPUT', 'NodeSocketGeometry'),
        ('Sun', 'INPUT', 'NodeSocketObject'), ('Head', 'INPUT', 'NodeSocketObject'),
        ('Positional', 'INPUT', 'NodeSocketBool'),
        ('Geometry', 'OUTPUT', 'NodeSocketGeometry')):
        tree.interface.new_socket(name=name, in_out=direction, socket_type=kind)
    graph = Graph(tree)
    source = graph.node('NodeGroupInput', 'Input')
    output = graph.node('NodeGroupOutput', 'Output')
    geometry = source.outputs['Geometry']
    directions = [('HZZ_SUN', 'Sun', (0, 0, 1))]
    if head:
        directions.extend((('HZZ_RIGHT', 'Head', (1, 0, 0)), ('HZZ_FRONT', 'Head', (0, 1, 0))))
    for name, object_name, axis in directions:
        info = graph.node('GeometryNodeObjectInfo', name + ' Object')
        info.transform_space = 'ORIGINAL'
        graph.link(source.outputs[object_name], info.inputs['Object'])
        rotate = graph.node('FunctionNodeRotateVector', name + ' World Direction')
        rotate.inputs['Vector'].default_value = axis
        graph.link(info.outputs['Rotation'], rotate.inputs['Rotation'])
        direction = rotate.outputs['Vector']
        if name == 'HZZ_SUN':
            origin = graph.node('GeometryNodeObjectInfo', 'Head Light Origin')
            origin.transform_space = 'ORIGINAL'
            graph.link(source.outputs['Head'], origin.inputs['Object'])
            positional = graph.vector('NORMALIZE', graph.vector('SUBTRACT', info.outputs['Location'], origin.outputs['Location']))
            switch = graph.node('GeometryNodeSwitch', 'Light Type')
            switch.input_type = 'VECTOR'
            graph.link(source.outputs['Positional'], switch.inputs['Switch'])
            graph.link(direction, switch.inputs['False'])
            graph.link(positional, switch.inputs['True'])
            direction = switch.outputs[0]
        store = graph.node('GeometryNodeStoreNamedAttribute', name)
        store.data_type, store.domain = 'FLOAT_VECTOR', 'POINT'
        store.inputs['Name'].default_value = name
        graph.link(direction, store.inputs['Value'])
        graph.link(geometry, store.inputs['Geometry'])
        geometry = store.outputs['Geometry']
    graph.link(geometry, output.inputs['Geometry'])
    return tree


def set_modifier(modifier, name, value):
    socket = next(s for s in modifier.node_group.interface.items_tree
                  if s.item_type == 'SOCKET' and s.in_out == 'INPUT' and s.name == name)
    getattr(modifier.properties.inputs, socket.identifier).value = value


def update_modifier(modifier, profile):
    set_modifier(modifier, 'Sun', profile.sun)
    set_modifier(modifier, 'Head', profile.head)
    if any(s.name == 'Positional' for s in modifier.node_group.interface.items_tree):
        set_modifier(modifier, 'Positional', bool(profile.sun and profile.sun.data.type != 'SUN'))
