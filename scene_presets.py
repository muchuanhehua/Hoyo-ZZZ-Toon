"""Append optional environments without replacing character or output data."""
import json
from pathlib import Path
from uuid import uuid4
import bpy
from . import ownership, rendering

ASSETS = Path(__file__).resolve().parent / 'assets'
PRESETS = {item['id']: item for item in json.loads((ASSETS / 'scenes.json').read_text('utf-8'))['presets']}
PRESET_ITEMS = tuple((key, item['name'], '') for key, item in PRESETS.items())
OWNER = 'hzz_scene_owner'


def _owned(uid):
    return {item for kind in ownership.KINDS for item in getattr(bpy.data, kind)
            if item.get(OWNER) == uid}


def _release(scene, collection, uid):
    """Unlink this preset; keep anything the user has reused or added."""
    if collection:
        for parent in (scene.collection, *scene.collection.children_recursive):
            if collection.name in parent.children:
                parent.children.unlink(collection)
        if collection.users:
            return
    owned = _owned(uid)
    collections = {item for item in owned if isinstance(item, bpy.types.Collection)}
    for parent in collections:
        for child in parent.children:
            if child not in owned and child.name not in scene.collection.children:
                scene.collection.children.link(child)
        for obj in parent.objects:
            if obj not in owned and obj.name not in scene.collection.objects:
                scene.collection.objects.link(obj)
    users = bpy.data.user_map(subset=owned)
    protected = {item for item in owned if users.get(item, set()) - owned}
    while True:
        dependent = {item for item in owned - protected if users.get(item, set()) & protected}
        if not dependent:
            break
        protected.update(dependent)
    removed = {item for item in owned - protected if isinstance(item, (bpy.types.Object, bpy.types.Collection))}
    for item in protected:
        if isinstance(item, bpy.types.Object) and all(parent in removed for parent in item.users_collection):
            scene.collection.objects.link(item)
    bpy.data.batch_remove(ids=removed)
    # Delete unused dependencies in layers, leaving materials/meshes reused elsewhere.
    while True:
        unused = {item for item in _owned(uid) if item.users == 0}
        if not unused:
            break
        bpy.data.batch_remove(ids=unused)


def restore_default_light(scene, force=False):
    state = scene.hzz_scene
    light = state.muted_light
    if light and (force or scene.hzz_light == light):
        if light.hide_render:
            light.hide_render = state.muted_render
        if light.hide_viewport:
            light.hide_viewport = state.muted_viewport
    state.muted_light = None


def _mute_default_light(scene):
    state, light = scene.hzz_scene, scene.hzz_light
    if (light and light.get('hzz_scene_light') and light != state.muted_light
            and tuple(light.users_scene) == (scene,)):
        state.muted_light = light
        state.muted_render, state.muted_viewport = light.hide_render, light.hide_viewport
        light.hide_render = light.hide_viewport = True


def load(context, preset_id):
    rendering.check_idle()
    if context.mode != 'OBJECT':
        raise ValueError('请切换到对象模式后载入场景')
    preset = PRESETS.get(preset_id)
    if preset is None:
        raise ValueError('场景预设不存在')
    path = ASSETS / preset['file']
    if not path.is_file():
        raise ValueError('缺少场景资产：' + preset['name'])
    scene, state = context.scene, context.scene.hzz_scene
    if (state.collection and state.preset == preset_id and state.collection in scene.collection.children_recursive
            and state.collection.get('hgt_city_layout') == preset.get('layout')):
        return state.collection
    before = ownership.snapshot()
    previous = {name: getattr(state, name) for name in state.bl_rna.properties.keys() if name != 'rna_type'}
    pointers = scene.world, scene.camera, scene.hzz_light
    visibility = {light: (light.hide_render, light.hide_viewport)
                  for light in (state.muted_light, scene.hzz_light) if light}
    old_collection, old_uid = state.collection, state.uid
    try:
        with bpy.data.libraries.load(str(path), link=False) as (source, target):
            if preset['collection'] not in source.collections:
                raise ValueError('场景资产缺少预设集合：' + preset['name'])
            target.collections = [preset['collection']]
        collection = target.collections[0]
        camera, light, world = (collection.get('hgt_scene_' + key) for key in ('camera', 'light', 'world'))
        if (collection.get('hgt_scene_asset') != preset_id or not isinstance(camera, bpy.types.Object)
                or camera.type != 'CAMERA' or camera.name not in collection.all_objects
                or not isinstance(light, bpy.types.Object) or light.type != 'LIGHT'
                or light.data.type not in {'SUN', 'AREA', 'POINT', 'SPOT'} or light.name not in collection.all_objects
                or not isinstance(world, bpy.types.World)):
            raise ValueError('场景资产的相机、主光或世界引用无效：' + preset['name'])
        uid = uuid4().hex
        for item in ownership.created(before):
            item[OWNER] = uid
        if not old_uid:
            state.previous_world, state.previous_camera, state.previous_light = pointers
        _mute_default_light(scene)
        scene.collection.children.link(collection)
        scene.world, scene.camera, scene.hzz_light = world, camera, light
        state.collection, state.uid, state.preset = collection, uid, preset_id
        state.world, state.camera, state.light = world, camera, light
    except Exception:
        for name, value in previous.items():
            setattr(state, name, value)
        scene.world, scene.camera, scene.hzz_light = pointers
        for light, flags in visibility.items():
            light.hide_render, light.hide_viewport = flags
        bpy.data.batch_remove(ids=ownership.created(before))
        raise
    if old_uid:
        _release(scene, old_collection, old_uid)
    return collection


def remove(context):
    rendering.check_idle()
    if context.mode != 'OBJECT':
        raise ValueError('请切换到对象模式后移除场景')
    scene, state = context.scene, context.scene.hzz_scene
    collection, uid = state.collection, state.uid
    if not uid:
        raise ValueError('当前没有载入的场景预设')
    for name in ('world', 'camera'):
        if getattr(scene, name) == getattr(state, name):
            setattr(scene, name, getattr(state, 'previous_' + name))
    if scene.hzz_light == state.light:
        scene.hzz_light = state.previous_light
    restore_default_light(scene)
    for name in state.bl_rna.properties.keys():
        if name != 'rna_type':
            state.property_unset(name)
    _release(scene, collection, uid)
