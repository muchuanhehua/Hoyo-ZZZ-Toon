"""Whole MMD characters and selection synchronization, without rebuilding rigs."""
import bpy
from bpy.app.handlers import persistent
from .adapters import pmx

_ACTIVE = {}
_BUSY = False


def model_root(obj):
    if not obj or obj.type != 'EMPTY' or getattr(obj, 'mmd_type', '') != 'ROOT':
        return False
    children = [o for o in obj.children_recursive if pmx.root_of(o) == obj]
    return (sum(o.type == 'ARMATURE' for o in children) == 1
            and any(o.type == 'MESH' and getattr(o, 'mmd_type', '') not in {'RIGID_BODY', 'JOINT'} for o in children))


def selected(context):
    obj = context.scene.hzz_model
    root = obj if model_root(obj) else pmx.root_of(context.active_object)
    return root if model_root(root) and root.name in context.scene.objects else None


def armature(root):
    return pmx.model_parts(root)[0] if root else None


def remember_active(context):
    active = context.view_layer.objects.active
    _ACTIVE[context.scene.as_pointer()] = active.as_pointer() if active else 0


def ensure(root, context):
    if not model_root(root) or root.name not in context.scene.objects:
        raise ValueError('请选择完整的 MMD 角色主体')
    if not root.hzz_character.uid or not root.hzz_character.meshes:
        from .workflow import scan
        scan(root, context)
    return root


@persistent
def update_scene(scene, depsgraph=None):
    global _BUSY
    if _BUSY or bpy.app.is_job_running('RENDER'):
        return
    _BUSY = True
    try:
        if bpy.context.scene == scene:
            active = bpy.context.view_layer.objects.active
            key = active.as_pointer() if active else 0
            if _ACTIVE.get(scene.as_pointer()) != key:
                remember_active(bpy.context)
                root = pmx.root_of(active)
                if model_root(root) and root.name in scene.objects and scene.hzz_model != root:
                    scene.hzz_model = root
        from . import gaze
        for root in scene.objects:
            if root.hzz_character.look_camera:
                try:
                    gaze.update_gaze(root, scene)
                    root.hzz_character.preview_error = ''
                except (ValueError, RuntimeError) as exc:
                    root.hzz_character.preview_error = str(exc)
    finally:
        _BUSY = False


@persistent
def on_load(_):
    _ACTIVE.clear()


def register():
    bpy.app.handlers.depsgraph_update_post.append(update_scene)
    bpy.app.handlers.frame_change_post.append(update_scene)
    bpy.app.handlers.load_post.append(on_load)


def unregister():
    for handlers, function in ((bpy.app.handlers.depsgraph_update_post, update_scene),
                               (bpy.app.handlers.frame_change_post, update_scene),
                               (bpy.app.handlers.load_post, on_load)):
        if function in handlers:
            handlers.remove(function)
    _ACTIVE.clear()
