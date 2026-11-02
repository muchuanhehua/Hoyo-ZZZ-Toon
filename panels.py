"""A compact native sidebar with visible mappings and resource diagnostics."""
import textwrap
import bpy
from .adapters.pmx import root_of


def message(layout, text):
    for line in textwrap.wrap(text, width=28, break_long_words=True):
        layout.label(text=line)


class HZZ_UL_materials(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.source.name if item.source else '材质已删除', icon='MATERIAL')
        row.prop(item, 'role', text='')


class HZZ_PT_main(bpy.types.Panel):
    bl_label = 'Hoyo-ZZZ-Toon'
    bl_idname = 'HZZ_PT_main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Hoyo-ZZZ-Toon'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        row = layout.row(align=True)
        row.operator('hzz.import_pmx', icon='IMPORT')
        row.operator('hzz.scan', icon='VIEWZOOM')
        layout.prop(context.scene, 'hzz_model')
        root = context.scene.hzz_model or root_of(context.active_object)
        if not root or not root.hzz_character.uid:
            message(layout, '选择已有 MMD 模型后扫描，或导入新的 PMX。')
            return
        p = root.hzz_character
        layout.separator()
        layout.template_list('HZZ_UL_materials', '', p, 'materials', p, 'active_material', rows=6)
        if p.materials:
            index = max(0, min(p.active_material, len(p.materials) - 1))
            binding = p.materials[index]
            layout.prop(binding, 'tint')
            row = layout.row(align=True)
            row.prop(binding, 'use_toon')
            row.prop(binding, 'use_sphere')
            layout.prop(binding, 'base_override')
            layout.operator('hzz.set_base_texture', icon='IMAGE_DATA').index = index
            if binding.diagnostic:
                message(layout, binding.diagnostic)
            elif binding.role == 'UNKNOWN':
                message(layout, binding.evidence)
        row = layout.row(align=True)
        layout.prop(p, 'surface_directory')
        layout.prop(p, 'surface_evidence')
        message(layout, '增强图按实际 UV 区域核对；空目录使用 PMX 基础响应。')
        row = layout.row(align=True)
        row.operator('hzz.apply', icon='MATERIAL')
        row.operator('hzz.restore', icon='LOOP_BACK')
        if p.report:
            message(layout, p.report)
        layout.separator()
        layout.label(text='阴影与高光')
        for name in ('shadow_position', 'shadow_softness', 'shadow_color', 'specular'):
            layout.prop(p, name)
        layout.label(text='基础描边')
        layout.operator('hzz.outline_defaults', icon='LOOP_BACK')
        for name in ('outline_width', 'outline_face_scale', 'outline_skin_scale', 'outline_hair_scale',
                     'outline_color_mix', 'outline_brightness'):
            layout.prop(p, name)
        layout.label(text='身体与头发')
        layout.operator('hzz.surface_defaults', icon='LOOP_BACK')
        for name in ('surface_threshold', 'surface_softness', 'surface_key_color', 'surface_mid_color',
                     'body_shadow_color', 'skin_key_color', 'skin_shadow_color', 'ambient_tint_strength', 'hair_shadow_shift',
                     'hair_highlights', 'reflection_strength', 'normal_strength', 'surface_data_strength',
                     'scene_shadow_strength', 'light_color_strength', 'rim_strength', 'pmx_toon_strength'):
            layout.prop(p, name)
        layout.separator()
        layout.label(text='脸部与灯光')
        layout.prop(p, 'face_key_color')
        layout.prop(p, 'face_mode')
        if p.face_mode == 'SDF':
            layout.prop(p, 'face_lightmap')
            layout.operator('hzz.set_face_lightmap', icon='IMAGE_DATA')
            message(layout, '绑定与模型 UV 匹配的共享图；模式或图像变更后重新应用。')
        if p.rig:
            layout.prop_search(p, 'head_bone', p.rig.data, 'bones')
        layout.prop(p, 'head_yaw')
        if p.head:
            label = '左右眼骨' if p.head.get('hzz_frame_basis', 'EYE_BONES') == 'EYE_BONES' else 'MMD 骨架方向，可调偏移'
            layout.label(text='方向参照：' + label)
        layout.prop(p, 'sun')
        layout.separator()
        layout.operator('hzz.preview', icon='SCENE_DATA')
        layout.operator('hzz.render', icon='RENDER_STILL')


CLASSES = (HZZ_UL_materials, HZZ_PT_main)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
