"""Persistent model runtime references and shared material-role state."""
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty
from bpy.props import FloatVectorProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup

ROLES = (
    ('UNKNOWN', '未分类', '请指定用途后应用'),
    ('BODY', '主体／衣装', '接受实际灯光的基础 Toon'),
    ('HAIR', '头发', '独立高光与 Toon'),
    ('FACE', '脸部', '头部坐标与主光控制的基础脸影或共享 SDF'),
    ('EYE', '虹膜／瞳孔', '独立眼部颜色与透明度'),
    ('WHITE', '眼白', '独立眼白'),
    ('BROW', '眉睫／眼线', '保留薄片透明层'),
    ('EYE_SHADOW', '眼影', '保留实际眼影网格与 Alpha'),
    ('HIGHLIGHT', '眼部高光', '原有高光层'),
    ('MOUTH', '口腔／牙齿', '独立口腔颜色'),
    ('OVERLAY', '加亮叠层', '颜色亮度控制叠层覆盖率'),
    ('EMISSION', '发光', '独立发光颜色'),
    ('SKIP', '保留原材质', '不替换该材质'),
    ('EXPRESSION', '表情叠层', '保留实际表情网格、颜色与透明度'),
)

SURFACE_CONTROLS = ('body_shadow_color', 'skin_shadow_color', 'light_color_strength', 'pmx_toon_strength',
    'specular', 'surface_threshold', 'surface_softness', 'bias_strength', 'normal_strength',
    'surface_data_strength', 'scene_shadow_strength', 'reflection_strength', 'hair_highlights', 'rim_strength',
    'surface_key_color', 'surface_mid_color', 'skin_key_color', 'face_key_color', 'shadow_color',
    'ambient_tint_strength', 'hair_shadow_shift')

OUTLINE_CONTROLS = ('outline_face_scale', 'outline_skin_scale', 'outline_hair_scale',
                    'outline_color_mix', 'outline_brightness')


def update_profile(self, context):
    root = self.id_data
    profile = root.hzz_character
    if profile.managed and not profile.building:
        from .workflow import refresh
        refresh(root)


def sun_poll(self, obj):
    return obj.type == 'LIGHT' and obj.data.type == 'SUN'


class HZZSlot(PropertyGroup):
    index: IntProperty()
    link: StringProperty()
    material: PointerProperty(type=bpy.types.Material)


class HZZMesh(PropertyGroup):
    object: PointerProperty(type=bpy.types.Object)
    source: PointerProperty(type=bpy.types.Mesh)
    derived: PointerProperty(type=bpy.types.Mesh)
    slots: CollectionProperty(type=HZZSlot)


class HZZMaterial(PropertyGroup):
    source: PointerProperty(type=bpy.types.Material)
    generated: PointerProperty(type=bpy.types.Material)
    role: EnumProperty(name='材质用途', items=ROLES)
    evidence: StringProperty()
    diagnostic: StringProperty()
    tint: FloatVectorProperty(name='颜色', subtype='COLOR', size=3,
        default=(1, 1, 1), min=0, max=1, update=update_profile)
    base_override: PointerProperty(name='替换基础贴图', type=bpy.types.Image)
    use_toon: BoolProperty(name='使用 PMX Toon', default=True)
    use_sphere: BoolProperty(name='使用 PMX Sphere', default=True)


class HZZCharacter(PropertyGroup):
    uid: StringProperty()
    schema: IntProperty(default=1)
    managed: BoolProperty()
    building: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})
    source_file: StringProperty(subtype='FILE_PATH')
    surface_directory: StringProperty(name='原始增强贴图目录', subtype='DIR_PATH',
        description='包含配套 _D / _M / _A / _N 的资源目录；按实际材质 UV 像素核对，重新应用后生效')
    surface_evidence: StringProperty(name='已核对 UV 对应', subtype='FILE_PATH',
        description='可选的共享资产对应 JSON；核对基础图内容、UV 和四张资源图摘要，不含角色风格参数')
    rig: PointerProperty(type=bpy.types.Object)
    meshes: CollectionProperty(type=HZZMesh)
    materials: CollectionProperty(type=HZZMaterial)
    active_material: IntProperty()
    head_bone: StringProperty(name='头骨')
    head: PointerProperty(type=bpy.types.Object)
    sun: PointerProperty(name='角色主光', type=bpy.types.Object, poll=sun_poll, update=update_profile)
    face_mode: EnumProperty(name='脸影模式', items=(
        ('BASIC', '基础脸影', '使用通用方向与实际受光近似'),
        ('SDF', '共享 Lightmap / SDF', '使用已核对资源对应和 UV 的脸影图，变更后重新应用')),
        default='BASIC')
    face_lightmap: PointerProperty(name='Face Lightmap', type=bpy.types.Image,
        description='已核对与本模型 UV 对应的共享资产；不同资产分别绑定，变更后重新应用')
    preview: PointerProperty(type=bpy.types.Scene)
    height: FloatProperty(default=1.7)
    shadow_position: FloatProperty(name='阴影位置', default=.42, min=0, max=1, update=update_profile)
    shadow_softness: FloatProperty(name='阴影过渡', default=.025, min=.001, max=.3, update=update_profile)
    shadow_color: FloatVectorProperty(name='脸部阴影颜色', subtype='COLOR', size=3,
        default=(.88, .66, .68), min=0, max=1, update=update_profile)
    body_shadow_color: FloatVectorProperty(name='主体暗部色调', subtype='COLOR', size=3,
        default=(.42, .36, .57), min=0, max=1, update=update_profile)
    skin_shadow_color: FloatVectorProperty(name='皮肤暗部色调', subtype='COLOR', size=3,
        default=(.76, .44, .54), min=0, max=1, update=update_profile)
    surface_key_color: FloatVectorProperty(name='主体亮面色调', subtype='COLOR', size=3,
        default=(.92, .82, .88), min=0, max=2, update=update_profile)
    surface_mid_color: FloatVectorProperty(name='主体浅影色调', subtype='COLOR', size=3,
        default=(.65, .58, .73), min=0, max=1, update=update_profile)
    skin_key_color: FloatVectorProperty(name='皮肤亮面色调', subtype='COLOR', size=3,
        default=(1.02, .77, .79), min=0, max=2, update=update_profile)
    face_key_color: FloatVectorProperty(name='脸部受光色调', subtype='COLOR', size=3,
        default=(1.02, .97, .87), min=0, max=2, update=update_profile)
    ambient_tint_strength: FloatProperty(name='暗部环境染色', default=1, min=0, max=2,
        description='共用冷色环境补偿；受原色亮度、饱和度与明暗区域约束', update=update_profile)
    light_color_strength: FloatProperty(name='灯光颜色影响', default=.35, min=0, max=1, update=update_profile)
    pmx_toon_strength: FloatProperty(name='PMX 色带混合', default=0, min=0, max=1, update=update_profile)
    hair_shadow_shift: FloatProperty(name='头发明暗偏移', default=.33, min=-1, max=1, update=update_profile)
    specular: FloatProperty(name='表面高光', default=.2, min=0, max=1, update=update_profile)
    surface_threshold: FloatProperty(name='表面阴影位置', default=.18, min=-1, max=1, update=update_profile)
    surface_softness: FloatProperty(name='表面阴影过渡', default=.06, min=.005, max=.5, update=update_profile)
    bias_strength: FloatProperty(name='贴图阴影偏置', default=.2, min=0, max=1, update=update_profile)
    normal_strength: FloatProperty(name='法线细节', default=.7, min=0, max=1, update=update_profile)
    surface_data_strength: FloatProperty(name='增强图影响', default=1, min=0, max=1, update=update_profile)
    scene_shadow_strength: FloatProperty(name='场景遮挡影响', default=.65, min=0, max=1, update=update_profile)
    reflection_strength: FloatProperty(name='宽反射与衣料光泽', default=.35, min=0, max=1,
        description='依据金属、高光遮罩、光滑度与实际主光方向构造风格化宽反射', update=update_profile)
    hair_highlights: FloatProperty(name='发束高光', default=.45, min=0, max=1, update=update_profile)
    rim_strength: FloatProperty(name='轮廓光', default=.015, min=0, max=.3, update=update_profile)
    outline_width: FloatProperty(name='描边粗细', default=.0012, min=0, max=.05,
        subtype='DISTANCE', precision=4, update=update_profile)
    outline_face_scale: FloatProperty(name='脸部线宽倍率', default=.4, min=0, max=2, update=update_profile)
    outline_skin_scale: FloatProperty(name='独立皮肤线宽倍率', default=.55, min=0, max=2,
        description='作用于识别为独立皮肤的材质；混合图集仍按主体用途处理', update=update_profile)
    outline_hair_scale: FloatProperty(name='头发线宽倍率', default=.85, min=0, max=2, update=update_profile)
    outline_color_mix: FloatProperty(name='描边跟随底色', default=.9, min=0, max=1,
        description='在 PMX 边线色与基础贴图原色之间混合，再施加共用冷暖色调与亮度', update=update_profile)
    outline_brightness: FloatProperty(name='描边亮度', default=.18, min=0, max=1,
        description='降低时描边更深；脸和皮肤使用暖色，衣装和头发使用冷色', update=update_profile)
    head_yaw: FloatProperty(name='脸部方向偏移', default=0, subtype='ANGLE',
        min=-3.141593, max=3.141593, update=update_profile)
    report: StringProperty()


def model_poll(self, obj):
    return getattr(obj, 'mmd_type', '') == 'ROOT' and obj.name in self.objects


CLASSES = (HZZSlot, HZZMesh, HZZMaterial, HZZCharacter)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.hzz_character = PointerProperty(type=HZZCharacter)
    bpy.types.Scene.hzz_model = PointerProperty(name='模型', type=bpy.types.Object, poll=model_poll)


def unregister():
    del bpy.types.Scene.hzz_model
    del bpy.types.Object.hzz_character
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
