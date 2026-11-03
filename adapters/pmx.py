"""Read MMD base/Sphere/Alpha inputs; preserve source materials for restoration."""
from dataclasses import dataclass, field
from pathlib import Path
import re
import unicodedata
import bpy
from mathutils import Vector
from .. import ownership

UNLIT = {'EYE', 'WHITE', 'BROW', 'EYE_SHADOW', 'HIGHLIGHT', 'MOUTH', 'OVERLAY', 'EMISSION', 'EXPRESSION'}


def normalized(value):
    return unicodedata.normalize('NFKC', value).casefold().strip()


def names(material):
    data = material.mmd_material
    return [normalized(n) for n in (data.name_j, data.name_e, material.name) if n]


def classify(material):
    rules = (
        ('OVERLAY', r'\+$'),
        ('EXPRESSION', r'表情|^(目星|星目|星眼)|expression'),
        ('HIGHLIGHT', r'^(目光|眼光|瞳光|目高光)|highlight|eyegloss|sparkle'),
        ('EYE_SHADOW', r'目影|眼影|二重影|eyeshadow|eye.shadow'),
        ('WHITE', r'白目|目白|眼白|sclera'),
        ('BROW', r'^(?:左|右)?(眉|睫|眼睫毛|二重|口线|口線|目线|眼线)|痣$|eyebrow|eyelash|まつげ'),
        ('EYE', r'^(?:武器)?(目|瞳|虹膜|眼睛|眼瞳)(\d|$)|iris|pupil'),
        ('MOUTH', r'^(口舌|口腔|齿|歯|舌)|^(口|唇)(\d|$)|mouth|teeth|tongue'),
        ('FACE', r'^(颜|顏|顔|脸|臉|面)(\d|$)|face'),
        ('EMISSION', r'^(fx|effect|glow|光环)|emissive|发光|発光'),
        ('BODY', r'^(髮|髪|发)(饰|飾|带|帶)'),
        ('HAIR', r'^(头发|辫|辮|马尾|馬尾)|^(前|后|後|侧|側)?[髮髪发]|^毛(\d|$)|hair'),
        ('BODY', r'^(体|體|身体|肌|皮肤|包|外套|外衣|背心|胸衣|衬衣|衬衫|t恤|服|衣|上衣|贴身|下体|下裙|内裙|裙|皮裤|裤|黑丝|袜|靴|鞋|足|手|首|腕|腿|耳|肩|背饰|后带|后摆|下摆|脖环|护目镜|目镜片|墨镜|镜片|绳|拉链|锁链|蝴蝶结|领带|珠宝|宝石|金属|工具|武器|刀|毛领|面罩|面具|黑边|帽|扣|戒指|屏幕|披|翅膀|翼|穗|熊|狸猫|带|尾|袖|头饰|饰|电池|挂饰|邦布|透明罩|指甲|药丸)|body|cloth|skin|accessory'),
    )
    for role, pattern in rules:
        for name in names(material):
            if re.search(pattern, name):
                return role, f'名称规则：{name}'
    tree = getattr(material, 'node_tree', None)
    texture = tree.nodes.get('mmd_base_tex') if tree else None
    if texture and texture.image:
        stem = normalized(Path(texture.image.filepath or texture.image.name).stem)
        if re.search(r'^(髮|髪|发)(\d|_|$)|(?:^|[_ .-])hair(?:[_ .-]|\d|$)', stem):
            return 'HAIR', f'基础贴图用途：{stem}'
        if re.search(r'^(体|體|身体)(\d|_|$)|(?:^|[_ .-])(body|cloth|skin)(?:[_ .-]|\d|$)', stem):
            return 'BODY', f'基础贴图用途：{stem}'
    return 'UNKNOWN', '未找到明确的材质用途，请手动指定'


def root_of(obj):
    while obj:
        if getattr(obj, 'mmd_type', '') == 'ROOT':
            return obj
        obj = obj.parent
    return None


def selected_root(context):
    target = context.scene.hzz_model
    if target and target.name in context.scene.objects:
        return target
    selected = root_of(context.active_object)
    if selected:
        return selected
    raise ValueError('请选择 MMD 根对象、骨架或角色网格，或先导入 PMX')


def model_parts(root):
    if root.library:
        raise ValueError('请选择本地可编辑的 MMD 模型')
    children = [o for o in root.children_recursive if root_of(o) == root]
    rigs = [o for o in children if o.type == 'ARMATURE']
    meshes = [o for o in children if o.type == 'MESH' and
              getattr(o, 'mmd_type', '') not in {'RIGID_BODY', 'JOINT'}]
    if len(rigs) != 1 or not meshes:
        raise ValueError('模型需要唯一骨架和至少一个角色网格')
    if any(o.library or o.data.library for o in meshes + rigs):
        raise ValueError('请先将链接模型设为本地或创建可编辑覆写')
    return rigs[0], meshes


def find_bone(rig, aliases):
    wanted = {normalized(n) for n in aliases}
    for bone in rig.pose.bones:
        data = bone.mmd_bone
        if any(normalized(n) in wanted for n in (bone.name, data.name_j, data.name_e) if n):
            return bone.name
    return ''


def import_model(path, context):
    path = Path(path)
    if path.suffix.lower() != '.pmx' or not path.is_file():
        raise ValueError('请选择存在的 PMX 文件')
    try:
        properties = bpy.ops.mmd_tools.import_model.get_rna_type().properties
    except (AttributeError, RuntimeError, KeyError) as exc:
        raise RuntimeError('请安装并启用适配 Blender 5.2 的 MMD Tools') from exc
    options = dict(filepath=str(path), scale=.08, types={'MESH', 'ARMATURE', 'PHYSICS', 'MORPHS', 'DISPLAY'},
                   clean_model=False, remove_doubles=False, rename_bones=False, fix_bone_order=False,
                   fix_ik_links=False, apply_bone_fixed_axis=False)
    missing = set(options) - set(properties.keys())
    if missing:
        raise RuntimeError('MMD Tools 接口缺失：' + ', '.join(sorted(missing)))
    before, state = ownership.snapshot(), ownership.context_state(context)
    try:
        result = bpy.ops.mmd_tools.import_model('EXEC_DEFAULT', **options)
        if result != {'FINISHED'}:
            raise RuntimeError('MMD Tools 未完成 PMX 导入')
        roots = [o for o in bpy.data.objects if o.as_pointer() not in before['objects'] and
                 getattr(o, 'mmd_type', '') == 'ROOT']
        if len(roots) != 1:
            raise RuntimeError('本次导入未产生唯一 MMD 根对象')
        model_parts(roots[0])
        roots[0].hzz_character.source_file = str(path.resolve())
        return roots[0]
    except Exception:
        if not state['physics'] and context.scene.rigidbody_world:
            result = bpy.ops.rigidbody.world_remove()
            if result != {'FINISHED'}:
                raise RuntimeError('无法移除失败导入创建的物理环境')
        bpy.data.batch_remove(ids=ownership.created(before))
        raise
    finally:
        ownership.restore_context(context, state)


@dataclass
class MaterialInput:
    source: object
    role: str
    textures: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    alpha: float = 1.0
    diffuse: tuple = (1, 1, 1)
    specular: tuple = (0, 0, 0)
    shininess: float = 32
    sphere_mode: str = '0'
    uv: str = 'UVMap'
    uv_extra: str = ''
    double_sided: bool = False
    edge: bool = False
    edge_weight: float = 0
    edge_color: tuple = (0, 0, 0, 1)
    coplanar_faces: int = 0


def coplanar_material_faces(entries, candidates, height):
    """Find later coincident material layers without editing source geometry.

    PMX fur and hair highlights can reuse the body's triangles as decals. A
    depth-writing cutout on those faces competes with its own opaque backing.
    """
    epsilon = max(height * 1e-6, 1e-8)
    owners, candidate_faces = {}, []
    for object_index, entry in enumerate(entries):
        materials = {slot.index: slot.material.as_pointer() for slot in entry.slots if slot.material}
        coordinates = [tuple(round(value / epsilon) for value in entry.object.matrix_world @ vertex.co)
                       for vertex in entry.source.vertices]
        for polygon in entry.source.polygons:
            material = materials.get(polygon.material_index)
            if material is None:
                continue
            signature = tuple(sorted(coordinates[index] for index in polygon.vertices))
            order = (object_index, polygon.material_index)
            if signature not in owners or order < owners[signature][0]:
                owners[signature] = (order, material)
            if material in candidates:
                candidate_faces.append((material, signature, order))
    counts = {material: 0 for material in candidates}
    for material, signature, order in candidate_faces:
        earlier_order, earlier_material = owners[signature]
        if earlier_order < order and earlier_material != material:
            counts[material] += 1
    return counts


def image_path(image):
    return Path(bpy.path.abspath(image.filepath, library=image.library)).resolve()


def available(image):
    return bool(image.packed_file or image.source == 'GENERATED' or image_path(image).is_file())


def resolve(binding, uv, uv_extra):
    source = binding.source
    m = source.mmd_material
    result = MaterialInput(source, binding.role, alpha=m.alpha, diffuse=tuple(m.diffuse_color),
        specular=tuple(m.specular_color), shininess=float(m.shininess),
        sphere_mode=str(m.sphere_texture_type), uv=uv, uv_extra=uv_extra,
        double_sided=m.is_double_sided, edge=m.enabled_toon_edge,
        edge_weight=m.edge_weight, edge_color=tuple(m.edge_color))
    if binding.role == 'UNKNOWN':
        raise ValueError(f'{source.name} 尚未指定材质用途')
    if binding.role == 'SKIP':
        return result
    inputs = {'base': ('mmd_base_tex', True),
              'sphere': ('mmd_sphere_tex', binding.use_sphere and result.sphere_mode != '0')}
    for role, (node_name, enabled) in inputs.items():
        node = source.node_tree.nodes.get(node_name) if source.node_tree else None
        image = node.image if node else None
        if not enabled:
            if image:
                result.warnings.append(f'{role} 已在本材质设置中关闭')
            continue
        if image and not available(image):
            raise ValueError(f'{source.name} 缺少 {role} 贴图：{image_path(image)}')
        if image:
            result.textures[role] = image
    if 'base' in result.textures and not uv:
        raise ValueError(f'{source.name} 使用基础贴图，但网格缺少 UV')
    if result.sphere_mode not in {'0', '1', '2', '3'}:
        raise ValueError(f'{source.name} 的 Sphere 模式无效：{result.sphere_mode}')
    if 'sphere' in result.textures and result.sphere_mode == '3' and not uv_extra:
        raise ValueError(f'{source.name} 的 Sphere 附加 UV 模式缺少对应 UV')
    if result.sphere_mode != '0' and 'sphere' not in result.textures:
        result.warnings.append('Sphere 未参与本次着色')
    return result


def bounds(meshes):
    points = [obj.matrix_world @ Vector(c) for obj in meshes for c in obj.bound_box]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    return low, high
