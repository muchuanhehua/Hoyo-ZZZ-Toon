"""Dedicated ZZZ PMX look development with reversible native Blender data."""

bl_info = {
    'name': 'Hoyo-ZZZ-Toon',
    'author': 'muchuanhehua',
    'version': (0, 8, 0),
    'blender': (5, 2, 0),
    'location': 'View3D > Sidebar > Hoyo-ZZZ-Toon',
    'description': '绝区零 PMX 简便渲染、FBX 资源自动对应、共享脸影与描边',
    'category': 'Material',
}

from . import properties, operators, panels, scene_models, eye_compositor


def register():
    properties.register()
    operators.register()
    panels.register()
    scene_models.register()
    eye_compositor.register()


def unregister():
    eye_compositor.unregister()
    scene_models.unregister()
    panels.unregister()
    operators.unregister()
    properties.unregister()
