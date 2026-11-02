"""Dedicated ZZZ PMX look development with reversible native Blender data."""

bl_info = {
    'name': 'Hoyo-ZZZ-Toon',
    'author': 'muchuanhehua',
    'version': (0, 5, 2),
    'blender': (5, 2, 0),
    'location': 'View3D > Sidebar > Hoyo-ZZZ-Toon',
    'description': '绝区零 PMX Toon、共享脸影 SDF、描边与独立预览',
    'category': 'Material',
}

from . import properties, operators, panels


def register():
    properties.register()
    operators.register()
    panels.register()


def unregister():
    panels.unregister()
    operators.unregister()
    properties.unregister()
