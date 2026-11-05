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

SURFACE_CONTROLS = ('body_shadow_color', 'skin_shadow_color', 'light_color_strength',
    'specular', 'surface_threshold', 'surface_softness', 'bias_strength', 'normal_strength',
    'surface_data_strength', 'scene_shadow_strength', 'reflection_strength', 'hair_highlights', 'rim_strength',
    'surface_key_color', 'surface_mid_color', 'skin_key_color', 'face_key_color', 'shadow_color',
    'ambient_tint_strength', 'hair_shadow_shift')

OUTLINE_CONTROLS = ('outline_face_scale', 'outline_skin_scale', 'outline_hair_scale',
                    'outline_color_mix', 'outline_brightness', 'outline_camera_bound', 'outline_pixel_cap')

EYE_CONTROLS = ('eye_reveal', 'eye_brow_strength', 'eye_front_angle', 'eye_side_angle')

SKIN_COLOR_CONTROLS = ('skin_tint', 'skin_brightness', 'skin_saturation')


def update_profile(self, context):
    root = self.id_data
    profile = root.hzz_character
    if profile.managed and not profile.building:
        from .workflow import refresh
        refresh(root)


def update_resources(self, context):
    if self.managed and not self.building:
        self.report = '资源目录已改变，点击应用材质自动匹配'


def update_role(self, context):
    profile = self.id_data.hzz_character
    if not profile.building:
        profile.report = '材质用途已改变，点击应用材质更新'


def outline_get(self):
    from .outlines import DEFAULT_WIDTH_RATIO
    return self.outline_width / max(self.height * DEFAULT_WIDTH_RATIO, 1e-8)


def outline_set(self, value):
    from .outlines import DEFAULT_WIDTH_RATIO
    self.outline_width = self.height * DEFAULT_WIDTH_RATIO * value


def shadow_set(self, value):
    self.building = True
    try:
        self.shadow_position = value
        self.surface_threshold = value - .24
    finally:
        self.building = False
    update_profile(self, bpy.context)


def transition_set(self, value):
    self.building = True
    try:
        self.shadow_softness = .025 * value
        self.surface_softness = .06 * value
    finally:
        self.building = False
    update_profile(self, bpy.context)


def update_model(self, context):
    from .scene_models import remember_active
    remember_active(context)


def update_lighting(self, context):
    from .lighting import update_parameters
    if context and context.scene == self.id_data:
        update_parameters(context.scene, self)


def update_light(self, context):
    from .lighting import select_light
    select_light(self)
    for obj in self.objects:
        if obj.hzz_character.uid:
            obj.hzz_character.sun = self.hzz_light


def sun_poll(self, obj):
    return obj.type == 'LIGHT' and (not isinstance(self, bpy.types.Scene) or obj.name in self.objects)


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
    sdf_enabled: BoolProperty(default=True, options={'HIDDEN'})
    role: EnumProperty(name='材质用途', items=ROLES, update=update_role)
    evidence: StringProperty()
    diagnostic: StringProperty()
    tint: FloatVectorProperty(name='颜色', subtype='COLOR', size=3,
        default=(1, 1, 1), min=0, max=1, update=update_profile)
    brightness: FloatProperty(name='亮度', default=1, min=0, max=3, soft_max=2, update=update_profile)
    saturation: FloatProperty(name='饱和度', default=1, min=0, max=2, update=update_profile)
    opacity: FloatProperty(name='不透明度', default=1, min=0, max=1, update=update_profile)
    use_sphere: BoolProperty(name='使用 PMX Sphere', default=True)


class HZZCharacter(PropertyGroup):
    uid: StringProperty()
    schema: IntProperty(default=1)
    managed: BoolProperty()
    building: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})
    source_file: StringProperty(subtype='FILE_PATH')
    fbx_directory: StringProperty(name='FBX 目录', subtype='DIR_PATH', update=update_resources,
        description='可选：选择配套 FBX 资源文件夹，自动读取材质引用与 UV；空目录使用 PMX 基础渲染')
    resource_report: StringProperty()
    build_version: IntProperty(default=0)
    preview_error: StringProperty()
    rig: PointerProperty(type=bpy.types.Object)
    meshes: CollectionProperty(type=HZZMesh)
    materials: CollectionProperty(type=HZZMaterial)
    active_material: IntProperty()
    skin_tint: FloatVectorProperty(name='色调', subtype='COLOR', size=3,
        default=(1, 1, 1), min=0, max=1, update=update_profile,
        description='统一调整脸与已识别的身体皮肤；白色不额外染色')
    skin_brightness: FloatProperty(name='亮度', default=1, min=0, max=3, soft_max=2,
        update=update_profile, description='统一肤色亮度倍率；1 保持原亮度')
    skin_saturation: FloatProperty(name='饱和度', default=1, min=0, max=2,
        update=update_profile, description='统一肤色饱和度；1 保持原饱和度，0 去色')
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
    # Keep old action paths valid when opening 0.8.0 files. New materials do
    # not read these fields, and the removed controls have no panel entry.
    hair_band_width: FloatProperty(default=0, options={'HIDDEN', 'ANIMATABLE'})
    hair_band_softness: FloatProperty(default=0, options={'HIDDEN', 'ANIMATABLE'})
    rim_strength: FloatProperty(name='轮廓光', default=.015, min=0, max=.3, update=update_profile)
    outline_width: FloatProperty(name='描边粗细', default=.0012, min=0, max=.05,
        subtype='DISTANCE', precision=4, update=update_profile)
    outline_camera_bound: BoolProperty(name='相机约束描边', default=True, update=update_profile,
        description='自动按当前相机限制描边投影、像素宽度及局部外扩')
    outline_pixel_cap: FloatProperty(name='最大像素宽度', default=3, min=.25, max=12, update=update_profile)
    eye_reveal: FloatProperty(name='刘海透眼', default=.65, min=0, max=1, update=update_profile,
        description='自动识别前刘海，仅在最终合成中显现实际可见眼部；0关闭')
    eye_brow_strength: FloatProperty(name='眉睫透出', default=.35, min=0, max=1, update=update_profile)
    eye_front_angle: FloatProperty(name='完整透出角度', default=30, min=0, max=70, update=update_profile)
    eye_side_angle: FloatProperty(name='侧面淡出角度', default=75, min=35, max=89, update=update_profile)
    eye_report: StringProperty()
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
    outline: FloatProperty(name='描边粗细', min=0, max=20, soft_max=3, precision=2,
        get=outline_get, set=outline_set, description='相对模型身高的倍率：1 为默认线宽，0 关闭')
    shadow_balance: FloatProperty(name='阴影位置', min=0, max=1,
        get=lambda self: self.shadow_position, set=shadow_set)
    shadow_transition: FloatProperty(name='明暗过渡', min=.1, max=5,
        get=lambda self: self.shadow_softness / .025, set=transition_set)
    look_camera: BoolProperty(default=False)


def model_poll(self, obj):
    from .scene_models import model_root
    return obj.name in self.objects and model_root(obj)


class HZZGazeBone(PropertyGroup):
    bone: StringProperty()
    helper: PointerProperty(type=bpy.types.Object)
    active_constraint: StringProperty()


class HZZScenePresetSettings(PropertyGroup):
    preset: StringProperty()
    uid: StringProperty()
    collection: PointerProperty(type=bpy.types.Collection)
    previous_world: PointerProperty(type=bpy.types.World)
    previous_camera: PointerProperty(type=bpy.types.Object)
    previous_light: PointerProperty(type=bpy.types.Object)
    world: PointerProperty(type=bpy.types.World)
    camera: PointerProperty(type=bpy.types.Object)
    light: PointerProperty(type=bpy.types.Object)
    muted_light: PointerProperty(type=bpy.types.Object)
    muted_render: BoolProperty()
    muted_viewport: BoolProperty()
    key_muted: BoolProperty()
    key_render: BoolProperty()
    key_viewport: BoolProperty()


class HZZLightParameters(PropertyGroup):
    key: StringProperty()
    energy: FloatProperty(name='强度', default=2, min=0, soft_max=10, update=update_lighting)
    color: FloatVectorProperty(name='颜色', subtype='COLOR', size=3, default=(1, 1, 1), min=0, max=1, update=update_lighting)
    azimuth: FloatProperty(name='光向方位', subtype='ANGLE', min=-3.141593, max=3.141593, update=update_lighting)
    elevation: FloatProperty(name='光向高度', subtype='ANGLE', min=-1.570796, max=1.570796, update=update_lighting)
    angle: FloatProperty(name='光源角度', subtype='ANGLE', default=.1, min=0, max=3.141593, update=update_lighting)


class HZZLightingSettings(PropertyGroup):
    selected: EnumProperty(name='打光预设', items=(('DEFAULT', '默认光', ''), ('SOFT', '柔和正面', ''),
                         ('SIDE', '侧面塑形', ''), ('BACK', '背光轮廓', '')))
    active: StringProperty()
    presets: CollectionProperty(type=HZZLightParameters)


HZZCharacter.__annotations__['gaze_bones'] = CollectionProperty(type=HZZGazeBone)
CLASSES = (HZZSlot, HZZMesh, HZZMaterial, HZZGazeBone, HZZCharacter,
           HZZScenePresetSettings, HZZLightParameters, HZZLightingSettings)


def register():
    from .scene_presets import PRESET_ITEMS
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.hzz_character = PointerProperty(type=HZZCharacter)
    bpy.types.Scene.hzz_model = PointerProperty(name='角色主体', type=bpy.types.Object, poll=model_poll, update=update_model)
    bpy.types.Scene.hzz_light = PointerProperty(name='主光', type=bpy.types.Object, poll=sun_poll, update=update_light)
    bpy.types.Scene.hzz_lighting = PointerProperty(type=HZZLightingSettings)
    bpy.types.Scene.hzz_scene = PointerProperty(type=HZZScenePresetSettings)
    bpy.types.Scene.hzz_scene_preset = EnumProperty(name='场景预设', items=PRESET_ITEMS)


def unregister():
    for name in ('hzz_scene_preset', 'hzz_scene', 'hzz_lighting', 'hzz_light'):
        delattr(bpy.types.Scene, name)
    del bpy.types.Scene.hzz_model
    del bpy.types.Object.hzz_character
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
