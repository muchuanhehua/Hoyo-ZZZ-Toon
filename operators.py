"""Small explicit workflow operations; original assets and native output stay intact."""
import traceback
import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from .adapters import pmx
from . import workflow, scene_models, rendering, lighting, scene_presets, ownership, gaze


class CheckedOperation:
    def execute(self, context):
        try:
            rendering.check_idle()
            if context.mode != 'OBJECT':
                raise ValueError('请先切换到对象模式')
            result = self.run(context)
        except (ValueError, RuntimeError, OSError) as exc:
            traceback.print_exc()
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return result if isinstance(result, set) else {'FINISHED'}


class CharacterOperation(CheckedOperation):
    @classmethod
    def poll(cls, context):
        return not bpy.app.is_job_running('RENDER') and scene_models.selected(context) is not None


class HZZ_OT_import(CheckedOperation, bpy.types.Operator, ImportHelper):
    bl_idname = 'hzz.import_pmx'
    bl_label = '导入模型'
    bl_description = '导入 PMX 主体；保留 MMD 骨架、动作、物理和原材质'
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = '.pmx'
    filter_glob: StringProperty(default='*.pmx', options={'HIDDEN'})

    def run(self, context):
        root = pmx.import_model(self.filepath, context)
        workflow.scan(root, context)
        context.scene.hzz_model = root
        rendering.prepare(context.scene, root)
        self.report({'INFO'}, '已导入角色，点击应用材质即可预览')


def setup_materials(root, context):
    """Resolve the target once, supply missing scene controls and apply atomically."""
    scene_models.ensure(root, context)
    p, scene = root.hzz_character, context.scene
    # Old files retain their source directory; no manual correspondence JSON is needed.
    if not p.fbx_directory and p.get('surface_directory'):
        from pathlib import Path
        folder = Path(bpy.path.abspath(p['surface_directory']))
        p.fbx_directory = str(folder.parent if folder.name.casefold() == 'textures' else folder)
    before = ownership.snapshot()
    old = scene.hzz_light, p.sun, scene.camera
    previous_suns = {obj: obj.hzz_character.sun for obj in scene.objects if obj.hzz_character.uid}
    light_visibility = {obj: (obj.hide_render, obj.hide_viewport) for obj in scene.objects if obj.type == 'LIGHT'}
    old_active, old_selected = scene.hzz_lighting.active, scene.hzz_lighting.selected
    preset_count = len(scene.hzz_lighting.presets)
    try:
        light = scene.hzz_light
        if not light or light.name not in scene.objects:
            light = p.sun if p.sun and p.sun.name in scene.objects else next(
                (o for o in scene.objects if o.type == 'LIGHT' and o.data.type == 'SUN'), None)
            if light:
                scene.hzz_light = light
            else:
                light = lighting.default_light(scene)
        p.sun = light
        rendering.prepare(scene, root)
        workflow.apply(root, context)
    except Exception:
        scene.hzz_light, p.sun, scene.camera = old
        for obj, sun in previous_suns.items():
            obj.hzz_character.sun = sun
        for obj, flags in light_visibility.items():
            obj.hide_render, obj.hide_viewport = flags
        scene.hzz_lighting.active, scene.hzz_lighting.selected = old_active, old_selected
        while len(scene.hzz_lighting.presets) > preset_count:
            scene.hzz_lighting.presets.remove(len(scene.hzz_lighting.presets) - 1)
        bpy.data.batch_remove(ids=ownership.created(before))
        raise
    rendering.configure_material_render(scene)
    rendering.preview_materials(context)


class HZZ_OT_apply(CharacterOperation, bpy.types.Operator):
    bl_idname = 'hzz.apply'
    bl_label = '应用材质'
    bl_description = '接入主体并自动匹配所选 FBX 资源；完成后参数实时预览'
    bl_options = {'REGISTER', 'UNDO'}

    def run(self, context):
        root = scene_models.selected(context)
        setup_materials(root, context)
        self.report({'INFO'}, root.hzz_character.report)


class HZZ_OT_restore(CharacterOperation, bpy.types.Operator):
    bl_idname = 'hzz.restore'
    bl_label = '恢复原材质'
    bl_options = {'REGISTER', 'UNDO'}

    def run(self, context):
        root = scene_models.selected(context)
        if not root.hzz_character.managed:
            raise ValueError('当前角色尚未应用材质')
        workflow.restore(root)


class HZZ_OT_reset(CharacterOperation, bpy.types.Operator):
    bl_idname = 'hzz.reset_materials'
    bl_label = '重置参数'
    bl_options = {'REGISTER', 'UNDO'}

    def run(self, context):
        from .properties import SURFACE_CONTROLS, OUTLINE_CONTROLS
        from .outlines import DEFAULT_WIDTH_RATIO
        root = scene_models.ensure(scene_models.selected(context), context)
        p = root.hzz_character
        p.building = True
        try:
            for name in (*SURFACE_CONTROLS, *OUTLINE_CONTROLS, 'shadow_position', 'shadow_softness'):
                p.property_unset(name)
            p.outline_width = p.height * DEFAULT_WIDTH_RATIO
        finally:
            p.building = False
        workflow.refresh(root)


class HZZ_OT_toggle_bones(CharacterOperation, bpy.types.Operator):
    bl_idname = 'hzz.toggle_bones'
    bl_label = '骨骼显示'
    bl_description = '切换当前角色骨架的视口显示'
    bl_options = {'REGISTER', 'UNDO'}

    def run(self, context):
        rig = scene_models.armature(scene_models.selected(context))
        rig.hide_set(not rig.hide_get())


class HZZ_OT_load_scene(CheckedOperation, bpy.types.Operator):
    bl_idname = 'hzz.load_scene'
    bl_label = '载入场景'
    bl_description = '载入布景、主光、相机与世界，不移动角色'
    bl_options = {'REGISTER', 'UNDO'}

    def run(self, context):
        scene_presets.load(context, context.scene.hzz_scene_preset)


class HZZ_OT_remove_scene(CheckedOperation, bpy.types.Operator):
    bl_idname = 'hzz.remove_scene'
    bl_label = '移除场景'
    bl_description = '移除本插件布景并恢复原引用；保留用户添加与复用的数据'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.hzz_scene.uid and not bpy.app.is_job_running('RENDER'))

    def run(self, context):
        scene_presets.remove(context)


class HZZ_OT_light(CheckedOperation, bpy.types.Operator):
    bl_idname = 'hzz.apply_light_preset'
    bl_label = '启用打光'
    bl_options = {'REGISTER', 'UNDO'}

    def run(self, context):
        lighting.apply_preset(context.scene, context.scene.hzz_lighting.selected)


class HZZ_OT_align_camera(CheckedOperation, bpy.types.Operator):
    bl_idname = 'hzz.align_camera'
    bl_label = '相机对齐当前视角'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(not bpy.app.is_job_running('RENDER') and context.area and context.area.type == 'VIEW_3D'
                    and context.space_data.region_3d.view_perspective != 'CAMERA')

    def run(self, context):
        rendering.prepare(context.scene, scene_models.selected(context))
        region = next(r for r in context.area.regions if r.type == 'WINDOW')
        with context.temp_override(region=region):
            return bpy.ops.view3d.camera_to_view()


class HZZ_OT_look_camera(CharacterOperation, bpy.types.Operator):
    bl_idname = 'hzz.look_camera'
    bl_label = '看向相机'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        root = scene_models.selected(context)
        return bool(root and not bpy.app.is_job_running('RENDER') and context.scene.camera and gaze.eye_bones(root))

    def run(self, context):
        root = scene_models.ensure(scene_models.selected(context), context)
        gaze.set_gaze(root, context.scene, not root.hzz_character.look_camera)


class HZZ_OT_render(CheckedOperation, bpy.types.Operator):
    bl_idname = 'hzz.render'
    bl_label = '渲染'
    bl_description = '使用 Blender 当前场景、相机和原生输出设置'

    @classmethod
    def poll(cls, context):
        return bool(context.scene.camera and not bpy.app.is_job_running('RENDER'))

    def run(self, context):
        return rendering.start(context.scene, invoke=not bpy.app.background)


CLASSES = (HZZ_OT_import, HZZ_OT_apply, HZZ_OT_restore, HZZ_OT_reset, HZZ_OT_toggle_bones,
           HZZ_OT_load_scene, HZZ_OT_remove_scene, HZZ_OT_light, HZZ_OT_align_camera, HZZ_OT_look_camera, HZZ_OT_render)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
