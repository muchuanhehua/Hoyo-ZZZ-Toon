"""Scoped data ownership and failure rollback, independent of user preferences."""
import bpy

KINDS = ('objects', 'collections', 'meshes', 'armatures', 'materials', 'node_groups',
         'images', 'actions', 'shape_keys', 'curves', 'lights', 'cameras', 'texts', 'scenes', 'worlds')


def tag(item, uid, stage='render'):
    item['hzz_owner'], item['hzz_stage'] = uid, stage
    return item


def snapshot():
    return {kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in KINDS}


def created(before):
    return {item for kind in KINDS for item in getattr(bpy.data, kind)
            if item.as_pointer() not in before[kind]}


def remove_unused(uid, stage='render'):
    candidates = {item for kind in KINDS for item in getattr(bpy.data, kind)
                  if item.get('hzz_owner') == uid and item.get('hzz_stage') == stage}
    if not candidates:
        return
    users = bpy.data.user_map(subset=candidates)
    def outside(item, refs):
        refs = refs - candidates
        if isinstance(item, bpy.types.Object):
            refs = {ref for ref in refs if not isinstance(ref, (bpy.types.Collection, bpy.types.Scene))}
        return refs
    protected = {item for item, refs in users.items() if outside(item, refs)}
    while True:
        extra = {item for item, refs in users.items() if refs & protected} - protected
        if not extra:
            break
        protected.update(extra)
    discard = candidates - protected
    if discard:
        bpy.data.batch_remove(ids=discard)


def context_state(context):
    scene = context.scene
    paths = ((scene, 'frame_start'), (scene, 'frame_end'), (scene, 'frame_current'),
             (scene.render, 'fps'), (scene.render, 'fps_base'),
             (scene.unit_settings, 'system'), (scene.unit_settings, 'scale_length'))
    return {'fields': [(owner, name, getattr(owner, name)) for owner, name in paths],
            'selection': tuple(context.selected_objects), 'active': context.view_layer.objects.active,
            'physics': scene.rigidbody_world is not None}


def restore_context(context, state):
    for owner, name, value in state['fields']:
        if getattr(owner, name) != value:
            setattr(owner, name, value)
    for obj in tuple(context.selected_objects):
        obj.select_set(False)
    for obj in state['selection']:
        if obj.name in context.view_layer.objects:
            obj.select_set(True)
    context.view_layer.objects.active = state['active']
