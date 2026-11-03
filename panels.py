"""Six independent beginner-facing panels, following the Hoyo-GI-Toon workflow."""
import textwrap
import bpy
from . import scene_models, lighting


def message(layout, text):
    for line in textwrap.wrap(text, width=27, break_long_words=True):
        layout.label(text=line)


def profile(context):
    root = scene_models.selected(context)
    return root.hzz_character if root else None


def ready(layout, context):
    layout.enabled = not bpy.app.is_job_running('RENDER')
    layout.use_property_decorate = False


class HZZ_UL_materials(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.source.name if item.source else '材质已删除',
                     icon='ERROR' if item.role == 'UNKNOWN' else 'MATERIAL')


class HZZPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Hoyo-ZZZ-Toon'


class HZZ_PT_main(HZZPanel, bpy.types.Panel):
    bl_label = '角色管理'
    bl_idname = 'HZZ_PT_main'
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        ready(layout, context)
        row = layout.row(align=True)
        row.operator('hzz.import_pmx', icon='IMPORT')
        row.prop(context.scene, 'hzz_model', text='')
        rig = scene_models.armature(scene_models.selected(context))
        visible = bool(rig and not rig.hide_get())
        row.operator('hzz.toggle_bones', text='', icon='HIDE_OFF' if visible else 'HIDE_ON', depress=visible)


class HZZ_PT_materials(HZZPanel, bpy.types.Panel):
    bl_label = '材质'
    bl_idname = 'HZZ_PT_materials'
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        ready(layout, context)
        p = profile(context)
        if not p:
            layout.label(text='先导入或选择角色主体', icon='OUTLINER_OB_ARMATURE')
            return
        layout.prop(p, 'fbx_directory')
        layout.operator('hzz.apply', text='更新材质' if p.managed else '应用材质', icon='MATERIAL')
        if not p.managed:
            message(layout, p.report or '可直接应用；有原始资源时选择配套 FBX 文件夹。')
            return
        for name in ('shadow_balance', 'shadow_transition', 'reflection_strength', 'outline'):
            layout.prop(p, name, slider=True, **({'text': '衣料光泽'} if name == 'reflection_strength' else {}))
        row = layout.row(align=True)
        row.operator('hzz.reset_materials', icon='LOOP_BACK')
        row.operator('hzz.restore')
        if p.build_version != 8:
            message(layout, '旧版材质：点击更新材质启用统一肤色调节。')
        elif p.resource_report:
            message(layout, p.resource_report)
        if p.preview_error:
            message(layout, p.preview_error)


class HZZ_PT_local_colors(HZZPanel, bpy.types.Panel):
    bl_label = '局部调色'
    bl_idname = 'HZZ_PT_local_colors'
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        ready(layout, context)
        p = profile(context)
        if not p or not p.materials:
            layout.label(text='应用材质后调整局部颜色', icon='MATERIAL')
            return
        box = layout.box()
        row = box.row(align=True)
        row.label(text='统一肤色')
        row.operator('hzz.reset_skin_colors', text='重置', icon='LOOP_BACK')
        if not p.managed or p.build_version < 8:
            message(box, '点击更新材质启用肤色调节。')
        elif not any(b.generated and 'HZZ Skin Color' in b.generated.node_tree.nodes for b in p.materials):
            message(box, '未识别独立皮肤，请在下方按材质调色。')
        else:
            for name in ('skin_tint', 'skin_brightness', 'skin_saturation'):
                box.prop(p, name, slider=name != 'skin_tint')
        layout.label(text='单独材质')
        layout.template_list('HZZ_UL_materials', '', p, 'materials', p, 'active_material', rows=3, maxrows=3)
        binding = p.materials[min(max(p.active_material, 0), len(p.materials) - 1)]
        if binding.role == 'UNKNOWN':
            layout.prop(binding, 'role')
            message(layout, '请选择该材质用途，再点击应用材质。')
        for name in ('tint', 'brightness', 'saturation', 'opacity'):
            layout.prop(binding, name, slider=name != 'tint')
        header, body = layout.panel('hzz_material_details', default_closed=True)
        header.label(text='材质识别')
        if body:
            body.prop(binding, 'role')
            if binding.diagnostic:
                message(body, binding.diagnostic)


class HZZ_PT_scene(HZZPanel, bpy.types.Panel):
    bl_label = '场景'
    bl_idname = 'HZZ_PT_scene'
    bl_order = 3
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        ready(layout, context)
        row = layout.row(align=True)
        row.prop(context.scene, 'hzz_scene_preset', text='')
        row.operator('hzz.load_scene', text='载入', icon='IMPORT')
        row.operator('hzz.remove_scene', text='', icon='X')


class HZZ_PT_lighting(HZZPanel, bpy.types.Panel):
    bl_label = '打光'
    bl_idname = 'HZZ_PT_lighting'
    bl_order = 4
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        ready(layout, context)
        row = layout.row(align=True)
        row.prop(context.scene.hzz_lighting, 'selected', text='')
        row.operator('hzz.apply_light_preset', text='启用', icon='LIGHT_SUN')
        layout.prop(context.scene, 'hzz_light')
        light = context.scene.hzz_light
        if light:
            parameters = lighting.active_parameters(context.scene) if light.get('hzz_scene_light') else None
            if parameters:
                for name in ('energy', 'color', 'azimuth', 'elevation', 'angle'):
                    layout.prop(parameters, name)
            else:
                layout.prop(light.data, 'energy', text='强度')
                layout.prop(light.data, 'color', text='颜色')
                layout.prop(light, 'rotation_euler', text='旋转')


class HZZ_PT_camera(HZZPanel, bpy.types.Panel):
    bl_label = '相机'
    bl_idname = 'HZZ_PT_camera'
    bl_order = 5

    def draw(self, context):
        layout = self.layout
        ready(layout, context)
        layout.prop(context.scene, 'camera', text='相机')
        layout.operator('hzz.align_camera', icon='VIEW_CAMERA')
        p = profile(context)
        layout.operator('hzz.look_camera', depress=bool(p and p.look_camera), icon='HIDE_OFF')
        layout.operator('hzz.render', icon='RENDER_STILL')


CLASSES = (HZZ_UL_materials, HZZ_PT_main, HZZ_PT_materials, HZZ_PT_local_colors, HZZ_PT_scene, HZZ_PT_lighting, HZZ_PT_camera)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
