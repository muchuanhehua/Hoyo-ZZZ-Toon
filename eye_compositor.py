"""Per-target eye visibility scenes and reversible native compositor insertion.

Auxiliary scenes link the source scene's render-visible objects. Only the
target's mesh objects are replaced by deformed proxies with selected bangs
removed. Other characters remain occluders. No source collection is moved.
"""
import uuid
import json
import bpy
from bpy.app.handlers import persistent
from . import ownership, eye_reveal
from .materials.graph import Graph


def depth_material(source, uid, cache):
    """BLENDED surfaces are absent from EEVEE AOV/depth passes.

    Use an object-slot copy only in visibility scenes, retaining the shader's
    real alpha and animation. Beauty and the shared derived mesh stay intact.
    """
    material = cache.get(source)
    if material is None:
        material = ownership.tag(source.copy(), uid, 'eye')
        material.name = 'HZZ Eye Depth ' + source.name
        material['hzz_eye_material_source'] = source
        cache[source] = material
    material.surface_render_method = 'DITHERED'
    material.use_backface_culling = source.use_backface_culling
    material.use_transparency_overlap = source.use_transparency_overlap
    if not source.use_nodes:
        material.diffuse_color = source.diffuse_color
        return material
    original, copied = source.node_tree, material.node_tree
    if {(n.name, n.bl_idname) for n in original.nodes} != {(n.name, n.bl_idname) for n in copied.nodes}:
        # A user changed the shader structure since the previous render.
        del cache[source]
        return depth_material(source, uid, cache)
    for node in original.nodes:
        target = copied.nodes[node.name]
        for prop in node.bl_rna.properties:
            if prop.is_readonly or prop.identifier in {'name', 'parent', 'select', 'location', 'width', 'height', 'label'}:
                continue
            if prop.type in {'BOOLEAN', 'INT', 'FLOAT', 'ENUM', 'STRING'} or prop.identifier in {'image', 'object', 'node_tree'}:
                setattr(target, prop.identifier, getattr(node, prop.identifier))
        for source_socket, target_socket in zip(node.inputs, target.inputs):
            if hasattr(source_socket, 'default_value'):
                target_socket.default_value = source_socket.default_value
        if node.type in {'VALUE', 'RGB'}:
            target.outputs[0].default_value = node.outputs[0].default_value
    expected = {(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in original.links}
    actual = {(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in copied.links}
    if expected != actual:
        for link in list(copied.links):
            copied.links.remove(link)
        for link in original.links:
            output = next(s for s in copied.nodes[link.from_node.name].outputs if s.identifier == link.from_socket.identifier)
            input_socket = next(s for s in copied.nodes[link.to_node.name].inputs if s.identifier == link.to_socket.identifier)
            copied.links.new(output, input_socket)
    return material


def proxy_transform(proxy, original):
    proxy['hzz_eye_original'] = original
    constraint = proxy.constraints.get('HZZ Eye Follow Source')
    if constraint is None:
        constraint = proxy.constraints.new('COPY_TRANSFORMS')
        constraint.name = 'HZZ Eye Follow Source'
    constraint.target = original


def sync_visibility(aux, visible, target):
    """Make transparent occluders participate in the same visibility pass.

    Target meshes already have a bangs-filter proxy. Other scene objects stay
    linked directly unless their BLENDED materials also require a depth copy.
    """
    uid = aux['hzz_owner']
    proxies = {obj for obj in aux.objects if obj.get('hzz_eye_proxy')}
    # Saved 0.7.0 scenes predate explicit source references on target proxies.
    entries = aux['hzz_eye_root'].hzz_character.meshes
    for index, entry in enumerate(entries):
        stable = 'HZZ Eye Proxy ' + uid[:12] + ' ' + str(index)
        for proxy in proxies:
            if proxy.get('hzz_eye_name') == stable and not proxy.get('hzz_eye_original'):
                proxy_transform(proxy, entry.object)
    by_source = {obj.get('hzz_eye_original'): obj for obj in proxies}
    for original in visible - target:
        if original in by_source or original.hide_render or getattr(original, 'mmd_type', '') in {'RIGID_BODY', 'JOINT'} or not any(slot.material and slot.material.surface_render_method == 'BLENDED'
                                           for slot in original.material_slots):
            continue
        proxy = ownership.tag(original.copy(), uid, 'eye')
        proxy.name = 'HZZ Eye Occluder ' + original.name
        proxy['hzz_eye_name'] = proxy.name
        proxy['hzz_eye_proxy'] = True
        aux.collection.objects.link(proxy)
        if proxy.rigid_body:
            # A visibility copy follows evaluated motion, never joins physics.
            with bpy.context.temp_override(scene=aux, view_layer=aux.view_layers[0], object=proxy,
                                           active_object=proxy, selected_objects=[proxy], selected_editable_objects=[proxy]):
                bpy.ops.rigidbody.object_remove()
        proxy_transform(proxy, original)
        by_source[original] = proxy
        proxies.add(proxy)
    allowed = visible - target - set(by_source)
    for obj in tuple(aux.collection.objects):
        if obj not in allowed and obj not in proxies:
            aux.collection.objects.unlink(obj)
    for obj in allowed:
        if obj.name not in aux.objects:
            aux.collection.objects.link(obj)
    cache = {mat['hzz_eye_material_source']: mat for mat in bpy.data.materials
             if mat.get('hzz_owner') == uid and mat.get('hzz_stage') == 'eye' and mat.get('hzz_eye_material_source')}
    updated = set()
    for original, proxy in by_source.items():
        if original is None:
            bpy.data.objects.remove(proxy, do_unlink=True)
            continue
        proxy.hide_render = original.hide_render or original not in visible
        if proxy.data != original.data:
            proxy.data = original.data
        for source_slot, target_slot in zip(original.material_slots, proxy.material_slots):
            source = source_slot.material
            material = source
            if source and source.surface_render_method == 'BLENDED':
                material = cache.get(source) if source in updated else depth_material(source, uid, cache)
                updated.add(source)
            target_slot.link = 'OBJECT'
            target_slot.material = material
    for material in tuple(bpy.data.materials):
        if material.get('hzz_owner') == uid and material.get('hzz_stage') == 'eye' and material.users == 0:
            bpy.data.materials.remove(material)


def auxiliary_scenes(scene):
    return [item for item in bpy.data.scenes if item.get('hzz_eye_source') == scene]


def render_objects(scene, layer_name):
    layer = scene.view_layers.get(layer_name)
    if layer is None:
        raise ValueError('透眼引用的渲染层已删除，请更新材质')
    objects = set()
    def visit(collection):
        if collection.exclude or collection.collection.hide_render:
            return
        objects.update(collection.collection.objects)
        for child in collection.children:
            visit(child)
    visit(layer.layer_collection)
    return objects


def sync(aux):
    source, root = aux.get('hzz_eye_source'), aux.get('hzz_eye_root')
    if not source or not root:
        raise ValueError('透眼来源场景或角色已删除，请更新材质或恢复')
    target = {entry.object for entry in root.hzz_character.meshes if entry.object}
    sync_visibility(aux, render_objects(source, aux['hzz_eye_layer']), target)
    aux.camera, aux.world = source.camera, source.world
    aux.render.engine = source.render.engine
    for name in ('resolution_x', 'resolution_y', 'resolution_percentage', 'pixel_aspect_x', 'pixel_aspect_y',
                 'film_transparent', 'use_motion_blur', 'motion_blur_shutter', 'fps', 'fps_base',
                 'use_border', 'use_crop_to_border', 'border_min_x', 'border_min_y', 'border_max_x', 'border_max_y'):
        setattr(aux.render, name, getattr(source.render, name))
    # Use all supported EEVEE scalar settings; no private cache or pointer copies.
    for prop in source.eevee.bl_rna.properties:
        if not prop.is_readonly and prop.type in {'BOOLEAN', 'INT', 'FLOAT', 'ENUM'}:
            setattr(aux.eevee, prop.identifier, getattr(source.eevee, prop.identifier))
    aux.unit_settings.scale_length = source.unit_settings.scale_length
    aux.frame_set(source.frame_current, subframe=source.frame_subframe)
    aux.view_layers[0].use_pass_z = True


def prepare(root, context, modifiers):
    p, scene = root.hzz_character, context.scene
    stable_name = 'HZZ Eye ' + p.uid + ' ' + scene.name[:20]
    aux = ownership.tag(bpy.data.scenes.new(stable_name), p.uid, 'eye')
    aux['hzz_eye_name'] = stable_name
    aux['hzz_eye_source'], aux['hzz_eye_root'] = scene, root
    aux['hzz_eye_layer'] = context.view_layer.name
    names = eye_reveal.aov_names(p.uid)
    for name in names.values():
        aov = aux.view_layers[0].aovs.add()
        aov.name, aov.type = name, 'COLOR'
    filter_tree = eye_reveal.filter_bangs(p.uid)
    keep = set(modifiers)
    for index, entry in enumerate(p.meshes):
        obj = entry.object
        proxy = ownership.tag(obj.copy(), p.uid, 'eye')
        stable_proxy_name = 'HZZ Eye Proxy ' + p.uid[:12] + ' ' + str(index)
        proxy.name = stable_proxy_name
        proxy['hzz_eye_name'] = stable_proxy_name
        proxy['hzz_eye_proxy'] = True
        proxy_transform(proxy, obj)
        aux.collection.objects.link(proxy)
        # Remove stale owned modifiers copied from the previous build. Source
        # deformation, constraints and animation references are left intact.
        for original, copied in zip(obj.modifiers, list(proxy.modifiers)):
            if original.type == 'NODES' and original.node_group and original.node_group.get('hzz_owner') == p.uid and original not in keep:
                proxy.modifiers.remove(copied)
        delete = proxy.modifiers.new('HZZ • Remove Selected Bangs', 'NODES')
        delete.node_group = filter_tree
        index = next((i for i, mod in enumerate(proxy.modifiers) if mod.type == 'NODES'
            and mod.node_group and mod.node_group.get('hzz_kind') == 'outline'), len(proxy.modifiers) - 1)
        proxy.modifiers.move(len(proxy.modifiers) - 1, index)
    sync(aux)
    return aux


def root_state(scene):
    current = scene.compositing_node_group
    if current and current.get('hzz_kind') == 'eye_wrapper':
        return current.get('hzz_eye_previous'), current['hzz_eye_previous_use'], current['hzz_owner']
    return current, scene.render.use_compositing, uuid.uuid4().hex


def build_tree(scene, targets):
    previous, used, uid = root_state(scene)
    tree = previous.copy() if previous and used else bpy.data.node_groups.new('HZZ • Eye Composite', 'CompositorNodeTree')
    ownership.tag(tree, uid, 'eye')
    tree['hzz_kind'], tree['hzz_eye_previous_use'] = 'eye_wrapper', used
    if previous:
        tree['hzz_eye_previous'] = previous
    if not previous or not used:
        tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        output = tree.nodes.new('NodeGroupOutput')
        render = tree.nodes.new('CompositorNodeRLayers')
        render.layer = targets[0]['hzz_eye_layer']
        tree.links.new(render.outputs['Image'], output.inputs[0])
    entries = [n for n in tree.nodes if n.type == 'R_LAYERS' and n.scene in {None, scene}
               and n.outputs['Image'].is_linked]
    if not entries:
        raise ValueError('当前合成器没有连接本场景渲染图像，无法接入自动透眼')
    for render in entries:
        layer_name = render.layer or scene.view_layers[0].name
        selected = [aux for aux in targets if aux['hzz_eye_layer'] == layer_name]
        if not selected:
            continue
        g = Graph(tree)
        consumers = [link.to_socket for link in render.outputs['Image'].links]
        color = render.outputs['Image']
        for aux in selected:
            root = aux['hzz_eye_root']
            names = eye_reveal.aov_names(root.hzz_character.uid)
            # RLayers outputs refresh when assigned an existing layer again.
            render.layer = layer_name
            eye = g.node('CompositorNodeRLayers', 'HZZ Visible Eyes ' + root.name)
            eye.scene, eye.layer = aux, aux.view_layers[0].name
            mask = g.math('MULTIPLY', render.outputs[names['Hair']], eye.outputs[names['Eye']])
            behind = g.math('GREATER_THAN', eye.outputs['Depth'], g.math('ADD', render.outputs['Depth'], .00001))
            mask = g.math('MULTIPLY', mask, behind)
            strength = g.value('HZZ Reveal ' + root.hzz_character.uid, root.hzz_character.eye_reveal)
            eye_reveal.drive(strength, root, 'eye_reveal')
            mask = g.math('MULTIPLY', mask, strength)
            straight = g.mix(eye.outputs[names['Color']], g.math('MAXIMUM', eye.outputs[names['Eye']], .00001), mode='DIVIDE')
            color = g.mix(color, straight, mask)
        alpha = g.node('CompositorNodeSeparateColor', 'HZZ Input Alpha')
        g.link(render.outputs['Image'], alpha.inputs[0])
        preserve = g.node('CompositorNodeSetAlpha', 'HZZ Preserve Coverage')
        preserve.inputs['Type'].default_value = 'Replace Alpha'
        g.link(color, preserve.inputs['Image'])
        g.link(alpha.outputs['Alpha'], preserve.inputs['Alpha'])
        for target in consumers:
            g.link(preserve.outputs[0], target)
    return tree


def replace(root, scene, prepared=None):
    """Build before swapping the scene tree; failure leaves the old tree intact."""
    old = [aux for aux in auxiliary_scenes(scene) if aux != prepared and aux.get('hzz_eye_root') == root]
    targets = [aux for aux in auxiliary_scenes(scene) if aux not in old]
    if prepared and prepared not in targets:
        targets.append(prepared)
    layer = scene.view_layers.get(prepared['hzz_eye_layer']) if prepared else None
    current = scene.compositing_node_group
    z_state = json.loads(current['hzz_eye_z_state']) if current and current.get('hzz_kind') == 'eye_wrapper' else {
        layer.name: layer.use_pass_z for layer in scene.view_layers}
    created = []
    old_z = layer.use_pass_z if layer else None
    if layer:
        for name in eye_reveal.aov_names(root.hzz_character.uid).values():
            if layer.aovs.get(name) is None:
                created.append(layer.aovs.add())
                created[-1].name, created[-1].type = name, 'COLOR'
        layer.use_pass_z = True
    try:
        tree = build_tree(scene, targets) if targets else None
        if tree:
            tree['hzz_eye_z_state'] = json.dumps(z_state)
    except Exception:
        for aov in created:
            layer.aovs.remove(aov)
        if layer:
            layer.use_pass_z = old_z
        raise
    current = scene.compositing_node_group
    shared_uid = current.get('hzz_owner') if current and current.get('hzz_kind') == 'eye_wrapper' else None
    if tree:
        scene.compositing_node_group = tree
        scene.render.use_compositing = True
        shared_uid = tree['hzz_owner']
    elif shared_uid:
        previous, used, _uid = root_state(scene)
        scene.compositing_node_group = previous
        scene.render.use_compositing = used
        for name, enabled in z_state.items():
            if scene.view_layers.get(name):
                scene.view_layers[name].use_pass_z = enabled
    for aux in old:
        bpy.data.scenes.remove(aux)
    if not prepared:
        for view_layer in scene.view_layers:
            for name in eye_reveal.aov_names(root.hzz_character.uid).values():
                aov = view_layer.aovs.get(name)
                if aov:
                    view_layer.aovs.remove(aov)
    ownership.remove_unused(root.hzz_character.uid, 'eye')
    if prepared:
        prepared.name = prepared['hzz_eye_name']
        for obj in prepared.objects:
            if obj.get('hzz_eye_proxy'):
                obj.name = obj['hzz_eye_name']
    if shared_uid:
        ownership.remove_unused(shared_uid, 'eye')


def refresh(root):
    for aux in bpy.data.scenes:
        if aux.get('hzz_eye_root') == root:
            sync(aux)


def remove(root):
    scenes = {aux['hzz_eye_source'] for aux in bpy.data.scenes if aux.get('hzz_eye_root') == root}
    for scene in scenes:
        replace(root, scene)


@persistent
def render_pre(scene, *_args):
    if scene.get('hzz_eye_source'):
        return
    for aux in auxiliary_scenes(scene):
        sync(aux)


def register():
    if render_pre not in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.append(render_pre)


def unregister():
    if render_pre in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.remove(render_pre)
