"""Explicit, undoable operations; native Blender owns rendering and output."""
import bpy
from bpy.props import IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from .adapters import pmx
from . import workflow, scene


def object_mode(context):
    if context.mode != 'OBJECT':
        raise ValueError('请先切换到 Object Mode')


class CheckedOperation:
    def execute(self, context):
        try:
            object_mode(context)
            self.run(context)
        except (ValueError, RuntimeError, OSError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class HZZ_OT_import(CheckedOperation, bpy.types.Operator, ImportHelper):
    bl_idname = 'hzz.import_pmx'
    bl_label = '导入 PMX'
    bl_description = '通过 MMD Tools 导入模型并扫描，不修改原文件'
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = '.pmx'
    filter_glob: StringProperty(default='*.pmx', options={'HIDDEN'})

    def run(self, context):
        root = pmx.import_model(self.filepath, context)
        workflow.scan(root, context)
        context.scene.hzz_model = root
        self.report({'INFO'}, root.hzz_character.report)


class HZZ_OT_scan(CheckedOperation, bpy.types.Operator):
    bl_idname = 'hzz.scan'
    bl_label = '扫描当前选择'
    bl_description = '识别所选 MMD 模型并读取源材质用途'
    bl_options = {'REGISTER', 'UNDO'}

    def run(self, context):
        root = pmx.root_of(context.active_object) or pmx.selected_root(context)
        workflow.scan(root, context)
        self.report({'INFO'}, root.hzz_character.report)


class HZZ_OT_apply(CheckedOperation, bpy.types.Operator):
    bl_idname = 'hzz.apply'
    bl_label = '应用材质'
    bl_description = '按当前用途映射装配基础 Toon；重复应用会替换本插件旧资源'
    bl_options = {'REGISTER', 'UNDO'}

    def run(self, context):
        root = pmx.selected_root(context)
        workflow.apply(root, context)
        self.report({'INFO'}, root.hzz_character.report)


class HZZ_OT_restore(CheckedOperation, bpy.types.Operator):
    bl_idname = 'hzz.restore'
    bl_label = '恢复原材质'
    bl_options = {'REGISTER', 'UNDO'}

    def run(self, context):
        root = pmx.selected_root(context)
        workflow.restore(root)
        self.report({'INFO'}, root.hzz_character.report)


class HZZ_OT_surface_defaults(CheckedOperation, bpy.types.Operator):
    bl_idname = 'hzz.surface_defaults'
    bl_label = '重置共用表面参数'
    bl_description = '重置为同一套身体、皮肤与头发默认值，保留资源绑定和脸影模式'
    bl_options = {'REGISTER', 'UNDO'}

    def run(self, context):
        from .properties import SURFACE_CONTROLS
        root = pmx.selected_root(context)
        profile = root.hzz_character
        profile.building = True
        try:
            for name in SURFACE_CONTROLS:
                profile.property_unset(name)
        finally:
            profile.building = False
        workflow.refresh(root)


class HZZ_OT_outline_defaults(CheckedOperation, bpy.types.Operator):
    bl_idname = 'hzz.outline_defaults'
    bl_label = '重置共用描边参数'
    bl_description = '按模型高度重置线宽、材质用途倍率和线色；旧版描边需重新应用材质'
    bl_options = {'REGISTER', 'UNDO'}

    def run(self, context):
        from .properties import OUTLINE_CONTROLS
        from .outlines import DEFAULT_WIDTH_RATIO
        root = pmx.selected_root(context)
        profile = root.hzz_character
        profile.building = True
        try:
            profile.outline_width = profile.height * DEFAULT_WIDTH_RATIO
            for name in OUTLINE_CONTROLS:
                profile.property_unset(name)
        finally:
            profile.building = False
        workflow.refresh(root)


class HZZ_OT_preview(CheckedOperation, bpy.types.Operator):
    bl_idname = 'hzz.preview'
    bl_label = '创建／进入预览场景'
    bl_description = '创建独立 EEVEE 场景、World、太阳光和相机'
    bl_options = {'REGISTER', 'UNDO'}

    def run(self, context):
        root = pmx.selected_root(context)
        scene.create_preview(root, context)


class HZZ_OT_texture(CheckedOperation, bpy.types.Operator, ImportHelper):
    bl_idname = 'hzz.set_base_texture'
    bl_label = '选择基础贴图'
    bl_description = '为当前材质指定本地基础贴图，重新应用后生效'
    bl_options = {'REGISTER', 'UNDO'}
    filter_glob: StringProperty(default='*.png;*.tga;*.bmp;*.jpg;*.jpeg;*.dds;*.tif;*.exr', options={'HIDDEN'})
    index: IntProperty()

    def run(self, context):
        p = pmx.selected_root(context).hzz_character
        if not 0 <= self.index < len(p.materials):
            raise ValueError('材质选择已改变，请重新选择')
        p.materials[self.index].base_override = bpy.data.images.load(self.filepath, check_existing=True)


class HZZ_OT_face_lightmap(CheckedOperation, bpy.types.Operator, ImportHelper):
    bl_idname = 'hzz.set_face_lightmap'
    bl_label = '选择共享脸影图'
    bl_description = '绑定已核对与模型 UV 匹配的 Face Lightmap；源图像设置保持独立'
    bl_options = {'REGISTER', 'UNDO'}
    filter_glob: StringProperty(default='*.png;*.tga;*.dds;*.tif;*.exr', options={'HIDDEN'})

    def run(self, context):
        root = pmx.selected_root(context)
        before = {i.as_pointer() for i in bpy.data.images}
        image = bpy.data.images.load(self.filepath, check_existing=True)
        from .materials.face import validate_image
        try:
            validate_image(image)
        except ValueError:
            if image.as_pointer() not in before and image.users == 0:
                bpy.data.images.remove(image)
            raise
        root.hzz_character.face_lightmap = image
        root.hzz_character.report = '已绑定共享脸影图；选择 SDF 模式后重新应用材质'


class HZZ_OT_render(CheckedOperation, bpy.types.Operator):
    bl_idname = 'hzz.render'
    bl_label = '渲染当前场景'
    bl_description = '调用 Blender 原生渲染，使用当前场景的相机与输出设置'

    def run(self, context):
        target = context.scene
        if not target.camera:
            raise ValueError('当前场景没有相机，请指定相机或创建预览场景')
        if target.render.engine != 'BLENDER_EEVEE':
            raise ValueError('基础 Toon 使用 EEVEE，请进入预览场景或选择 EEVEE')
        result = bpy.ops.render.render('INVOKE_DEFAULT', scene=target.name)
        if result not in ({'FINISHED'}, {'RUNNING_MODAL'}):
            raise RuntimeError('Blender 未启动渲染')


CLASSES = (HZZ_OT_import, HZZ_OT_scan, HZZ_OT_apply, HZZ_OT_restore, HZZ_OT_surface_defaults,
           HZZ_OT_outline_defaults, HZZ_OT_preview, HZZ_OT_texture, HZZ_OT_face_lightmap, HZZ_OT_render)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
