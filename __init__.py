"""Dedicated ZZZ PMX look development with reversible native Blender data."""

bl_info = {
    'name': 'Hoyo-ZZZ-Toon',
    'author': 'muchuanhehua',
    'version': (0, 6, 2),
    'blender': (5, 2, 0),
    'location': 'View3D > Sidebar > Hoyo-ZZZ-Toon',
    'description': '绝区零 PMX 简便渲染、FBX 资源自动对应、共享脸影与描边',
    'category': 'Material',
}

from . import properties, operators, panels, scene_models


def register():
    properties.register()
    operators.register()
    panels.register()
    scene_models.register()


def unregister():
    scene_models.unregister()
    panels.unregister()
    operators.unregister()
    properties.unregister()
