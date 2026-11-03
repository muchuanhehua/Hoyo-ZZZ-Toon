"""Optional live eye tracking; original eye pose and animation stay intact."""
import math
import bpy
from mathutils import Quaternion, Vector
from . import scene_models

def head_bone(root):
    armature = scene_models.armature(root)
    if armature is None:
        raise ValueError('无法确定唯一 MMD 骨架')
    names = {'head', '頭', '头', 'あたま'}
    values = [bone for bone in armature.pose.bones if not bone.name.startswith('_') and any((name.strip().casefold() in names for name in (bone.name, bone.mmd_bone.name_j, bone.mmd_bone.name_e)))]
    if len(values) != 1:
        raise ValueError('无法确定唯一 MMD 头骨')
    return values[0]

def eye_bones(root):
    armature = scene_models.armature(root)
    if armature is None:
        return []
    aliases = {'左目', '右目', '左眼', '右眼', 'eye_l', 'eye_r', 'left eye', 'right eye'}
    values = [bone for bone in armature.pose.bones if not bone.name.startswith('_') and any((name.strip().casefold() in aliases for name in (bone.name, bone.mmd_bone.name_j, bone.mmd_bone.name_e)))]
    return values if len(values) == 2 else []

def constraint_name(root):
    return 'HZZ Look ' + root.hzz_character.uid

def clear_gaze(root):
    settings = root.hzz_character
    armature = settings.rig
    for item in settings.gaze_bones:
        bone = armature.pose.bones.get(item.bone) if armature else None
        constraint = bone.constraints.get(constraint_name(root)) if bone else None
        if constraint and constraint.type == 'COPY_ROTATION' and (constraint.target == item.helper):
            bone.constraints.remove(constraint)
            bone.constraints.active = bone.constraints.get(item.active_constraint)
        if item.helper and item.helper.users <= 1:
            bpy.data.objects.remove(item.helper, do_unlink=True)
    settings.gaze_bones.clear()
    settings.look_camera = False

def set_gaze(root, scene, enabled):
    if not enabled:
        clear_gaze(root)
        return
    bones = eye_bones(root)
    if not bones:
        raise ValueError('模型没有可识别的一对眼骨')
    head_bone(root)
    settings = root.hzz_character
    if settings.look_camera:
        return
    try:
        for bone in bones:
            helper = bpy.data.objects.new('HZZ • Eye Look', None)
            helper['hzz_owner'], helper['hzz_helper'] = (settings.uid, True)
            helper['hzz_stage'] = 'gaze'
            helper.rotation_mode = 'QUATERNION'
            root.users_collection[0].objects.link(helper)
            helper.hide_set(True)
            item = settings.gaze_bones.add()
            item.bone, item.helper = (bone.name, helper)
            item.active_constraint = bone.constraints.active.name if bone.constraints.active else ''
            constraint = bone.constraints.new('COPY_ROTATION')
            constraint.name = constraint_name(root)
            constraint.target = helper
            constraint.owner_space = constraint.target_space = 'WORLD'
            constraint.mix_mode = 'REPLACE'
        settings.look_camera = True
        update_gaze(root, scene)
    except Exception:
        clear_gaze(root)
        raise

def update_gaze(root, scene):
    settings = root.hzz_character
    if not settings.look_camera:
        return
    camera = scene.camera
    if camera is None:
        raise ValueError('请先选择相机')
    armature = settings.rig
    head = head_bone(root)
    transform = armature.matrix_world @ head.matrix @ head.bone.matrix_local.inverted()
    forward = (transform.to_3x3() @ Vector((0, -1, 0))).normalized()
    for item in settings.gaze_bones:
        bone = armature.pose.bones.get(item.bone)
        if bone is None or item.helper is None:
            raise ValueError('视线引用已改变，请关闭后重新启用')
        base = transform @ bone.bone.matrix_local
        direction = camera.matrix_world.translation - base.translation
        if direction.length < 1e-06:
            raise ValueError('相机与眼睛重合，请调整机位')
        delta = forward.rotation_difference(direction.normalized())
        delta = Quaternion().slerp(delta, min(1, math.radians(30) / max(delta.angle, 1e-06)))
        rotation = delta @ base.to_quaternion()
        if abs(item.helper.rotation_quaternion.dot(rotation)) < 1 - 1e-08:
            item.helper.rotation_quaternion = rotation
