"""An owned EEVEE lookdev scene with its own World, camera and Sun."""
from math import radians
import bpy
from mathutils import Vector
from .adapters.pmx import bounds
from .ownership import snapshot, created, tag


def frame_camera(scene, meshes):
    camera = scene.camera
    points = [obj.matrix_world @ Vector(c) for obj in meshes for c in obj.bound_box]
    orientation = camera.rotation_euler.to_matrix()
    right, up = orientation @ Vector((1, 0, 0)), orientation @ Vector((0, 1, 0))
    width = max(point.dot(right) for point in points) - min(point.dot(right) for point in points)
    height = max(point.dot(up) for point in points) - min(point.dot(up) for point in points)
    aspect = scene.render.resolution_x * scene.render.pixel_aspect_x / (scene.render.resolution_y * scene.render.pixel_aspect_y)
    camera.data.ortho_scale = max(height * 1.18, width / aspect * 1.10, .01)


def create_preview(root, context, switch=True):
    p = root.hzz_character
    if not p.uid:
        raise ValueError('请先扫描模型')
    if p.preview:
        if switch and context.window:
            context.window.scene = p.preview
        return p.preview
    before = snapshot()
    old_sun = p.sun
    try:
        scene = tag(bpy.data.scenes.new(root.name + ' • HZZ Preview'), p.uid, 'preview')
        scene.render.engine = 'BLENDER_EEVEE'
        scene.view_settings.view_transform = 'Standard'
        scene.view_settings.look = 'None'
        scene.render.resolution_x, scene.render.resolution_y = 768, 1024
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = True
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.frame_start, scene.frame_end = context.scene.frame_start, context.scene.frame_end
        scene.render.fps, scene.render.fps_base = context.scene.render.fps, context.scene.render.fps_base
        for obj in (root, *root.children_recursive):
            scene.collection.objects.link(obj)
        world = tag(bpy.data.worlds.new(root.name + ' • HZZ World'), p.uid, 'preview')
        world.use_nodes = True
        # Default node names are translated when new data names follow the UI language.
        background = next(node for node in world.node_tree.nodes if node.type == 'BACKGROUND')
        background.inputs['Strength'].default_value = 0
        scene.world = world
        light_data = tag(bpy.data.lights.new(root.name + ' • HZZ Key', 'SUN'), p.uid, 'preview')
        light_data.energy, light_data.angle = 2, radians(4)
        light = tag(bpy.data.objects.new(light_data.name, light_data), p.uid, 'preview')
        scene.collection.objects.link(light)
        light.rotation_euler = (radians(35), radians(-25), radians(-35))
        camera_data = tag(bpy.data.cameras.new(root.name + ' • HZZ Camera'), p.uid, 'preview')
        camera = tag(bpy.data.objects.new(camera_data.name, camera_data), p.uid, 'preview')
        scene.collection.objects.link(camera)
        scene.camera = camera
        low, high = bounds([entry.object for entry in p.meshes])
        center, height = (low + high) * .5, max(high.z - low.z, .01)
        front = p.rig.matrix_world.to_3x3() @ Vector((0, -1, 0))
        camera.location = center + front.normalized() * height * 3
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.type = 'ORTHO'
        frame_camera(scene, [entry.object for entry in p.meshes])
        scene.hzz_model = root
        p.preview, p.sun = scene, light
        scene.frame_set(context.scene.frame_current)
        if switch and context.window:
            context.window.scene = scene
        return scene
    except Exception:
        p.preview, p.sun = None, old_sun
        bpy.data.batch_remove(ids=created(before))
        raise
