"""Persistent optional lighting presets, adapted from Hoyo-GI-Toon."""
import math
import bpy
from mathutils import Vector

PRESETS = {
    'DEFAULT': ('默认光', 2.0, (1, 1, 1), .35, .35, .1),
    'SOFT': ('柔和正面', 1.5, (1, .96, .92), .05, .25, .45),
    'SIDE': ('侧面塑形', 2.5, (1, .91, .8), 1.15, .5, .12),
    'BACK': ('背光轮廓', 2.8, (.82, .9, 1), 2.75, .4, .18),
}


def active_parameters(scene):
    state = scene.hzz_lighting
    return next((item for item in state.presets if item.key == state.active), None)


def select_light(scene):
    selected = scene.hzz_light
    if (selected and selected.get('hzz_scene_light') and selected.type == 'LIGHT'
            and tuple(selected.users_scene) == (scene,)):
        from .scene_presets import restore_default_light
        restore_default_light(scene)
        selected.hide_render = selected.hide_viewport = False
    for light in scene.objects:
        if (light.get('hzz_scene_light') and light.type == 'LIGHT' and light != scene.hzz_light
                and tuple(light.users_scene) == (scene,)):
            light.hide_render = light.hide_viewport = True
    state, selected = scene.hzz_scene, scene.hzz_light
    key = state.light
    if not key or key.get('hzz_scene_owner') != state.uid:
        return
    if selected == key or selected is None:
        restore_scene_key(scene)
    elif tuple(key.users_scene) == (scene,) and not state.key_muted:
        state.key_render, state.key_viewport = key.hide_render, key.hide_viewport
        state.key_muted = True
        key.hide_render = key.hide_viewport = True


def restore_scene_key(scene):
    state, key = scene.hzz_scene, scene.hzz_scene.light
    if key and state.key_muted:
        if key.hide_render:
            key.hide_render = state.key_render
        if key.hide_viewport:
            key.hide_viewport = state.key_viewport
    state.key_muted = False


def update_parameters(scene, parameters):
    light = scene.hzz_light
    if (scene.hzz_lighting.active != parameters.key or light is None
            or not light.get('hzz_scene_light') or light.type != 'LIGHT'
            or tuple(light.users_scene) != (scene,)):
        return
    light.data.energy, light.data.color, light.data.angle = parameters.energy, parameters.color, parameters.angle
    azimuth, elevation = parameters.azimuth, parameters.elevation
    direction = Vector((math.sin(azimuth) * math.cos(elevation),
                        -math.cos(azimuth) * math.cos(elevation), math.sin(elevation)))
    light.rotation_euler = (-direction).to_track_quat('-Z', 'Y').to_euler()


def apply_preset(scene, key):
    if key not in PRESETS:
        raise ValueError('打光预设不存在')
    from .scene_presets import restore_default_light
    restore_default_light(scene, force=True)
    state = scene.hzz_lighting
    parameters = next((item for item in state.presets if item.key == key), None)
    if parameters is None:
        parameters = state.presets.add()
        parameters.key = key
        name, parameters.energy, parameters.color, parameters.azimuth, parameters.elevation, parameters.angle = PRESETS[key]
    light = next((obj for obj in scene.objects if obj.get('hzz_scene_light') and obj.type == 'LIGHT'
                  and tuple(obj.users_scene) == (scene,) and obj.data.users == 1), None)
    if light is None:
        data = bpy.data.lights.new('HZZ • 默认光', 'SUN')
        light = bpy.data.objects.new(data.name, data)
        light['hzz_scene_light'] = True
        scene.collection.objects.link(light)
    state.active = key
    state.selected = key
    light.name = 'HZZ • ' + PRESETS[key][0]
    light.hide_render = light.hide_viewport = False
    scene.hzz_light = light
    update_parameters(scene, parameters)
    bpy.context.view_layer.update()
    return light


def default_light(scene):
    return apply_preset(scene, 'DEFAULT')
