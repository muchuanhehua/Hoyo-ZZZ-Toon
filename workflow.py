"""Character scanning, staged material commits, refresh and exact restoration."""
import uuid
import json
import bpy
from .adapters import pmx
from . import controllers, outlines, ownership
from .materials import basic, face, surface_inputs


def scan(root, context):
    p = root.hzz_character
    if p.managed:
        raise ValueError('请先恢复原材质，再重新扫描源模型')
    rig, meshes = pmx.model_parts(root)
    previous = {b.source.as_pointer(): (b.role, tuple(b.tint), b.base_override, b.use_toon, b.use_sphere)
                for b in p.materials if b.source}
    p.building = True
    try:
        p.uid = p.uid or uuid.uuid4().hex
        p.rig = rig
        p.head_bone = pmx.find_bone(rig, ('頭', '头', 'head', 'Head_M', 'J_Bip_C_Head', 'Bip001 Head', 'DEF-head'))
        p.meshes.clear()
        p.materials.clear()
        seen = set()
        for obj in meshes:
            entry = p.meshes.add()
            entry.object, entry.source = obj, obj.data
            for index, slot in enumerate(obj.material_slots):
                state = entry.slots.add()
                state.index, state.link, state.material = index, slot.link, slot.material
                source = slot.material
                if source is None or source.as_pointer() in seen:
                    continue
                seen.add(source.as_pointer())
                binding = p.materials.add()
                binding.source = source
                binding.role, binding.evidence = pmx.classify(source)
                old = previous.get(source.as_pointer())
                if old:
                    binding.role, binding.tint, binding.base_override, binding.use_toon, binding.use_sphere = old
        low, high = pmx.bounds(meshes)
        p.height = max(high.z - low.z, .01)
        p.outline_width = p.height * outlines.DEFAULT_WIDTH_RATIO
        if p.sun is None:
            suns = [o for o in context.scene.objects if o.type == 'LIGHT' and o.data.type == 'SUN']
            if len(suns) == 1:
                p.sun = suns[0]
        p.report = f'已扫描 {len(meshes)} 个网格、{len(p.materials)} 个材质；未分类 {sum(b.role == "UNKNOWN" for b in p.materials)} 个'
        context.scene.hzz_model = root
        return p
    finally:
        p.building = False


def validate(root):
    p = root.hzz_character
    if not p.uid or not p.meshes:
        raise ValueError('请先扫描模型')
    if p.schema != 1:
        raise ValueError('该角色的配置版本不受支持')
    by_source = {b.source.as_pointer(): b for b in p.materials if b.source}
    descriptions, errors = {}, []
    for entry in p.meshes:
        obj = entry.object
        expected = entry.derived if p.managed else entry.source
        if not obj or obj.data != expected:
            raise ValueError('角色网格引用已改变，请检查后恢复或重新扫描')
        for state in entry.slots:
            if not state.material:
                continue
            binding = by_source[state.material.as_pointer()]
            try:
                layers = entry.source.uv_layers
                data = pmx.resolve(binding, layers.active.name if layers.active else '',
                                   layers[1].name if len(layers) > 1 else '')
                existing = descriptions.get(state.material.as_pointer())
                if existing and (existing.uv, existing.uv_extra) != (data.uv, data.uv_extra):
                    raise ValueError(f'{state.material.name} 共享于 UV 结构不同的网格')
                descriptions[state.material.as_pointer()] = data
                binding.diagnostic = '；'.join(data.warnings)
            except ValueError as exc:
                binding.diagnostic = str(exc)
                errors.append(str(exc))
    if errors:
        raise ValueError('\n'.join(dict.fromkeys(errors)))
    hair = {key for key, data in descriptions.items() if data.role == 'HAIR'}
    if hair:
        coincident = pmx.coplanar_material_faces(p.meshes, hair, p.height)
        for key, count in coincident.items():
            descriptions[key].coplanar_faces = count
            if count:
                descriptions[key].warnings.append(f'检测到 {count} 个重合材质面，透明时保留叠加覆盖')
        for binding in p.materials:
            if binding.source and binding.source.as_pointer() in hair:
                binding.diagnostic = '；'.join(descriptions[binding.source.as_pointer()].warnings)
    has_face = any(data.role == 'FACE' for data in descriptions.values())
    if p.face_mode == 'SDF' and not has_face:
        raise ValueError('SDF 模式需要至少一个指定为 FACE 的材质')
    if any(data.role not in pmx.UNLIT | {'SKIP'} for data in descriptions.values()):
        if not p.sun or p.sun.type != 'LIGHT' or p.sun.data.type != 'SUN':
            raise ValueError('请指定角色主光，或先创建独立预览场景')
    if has_face:
        controllers.rest_frame(p)
        if p.face_mode == 'SDF':
            face.validate_image(p.face_lightmap)
            if any(data.role == 'FACE' and not data.uv for data in descriptions.values()):
                raise ValueError('SDF 模式需要脸部的有效 UV，不能用生成坐标代替')
    return descriptions


def prepare_mesh(entry, profile, replacements, head, descriptions, cache, surface_plans):
    derived = ownership.tag(entry.source.copy(), profile.uid)
    derived.name = entry.source.name + ' • HZZ Render'
    if derived.shape_keys and derived.shape_keys != entry.source.shape_keys:
        ownership.tag(derived.shape_keys, profile.uid)
    needs_light, outline_pairs = False, []
    for state in entry.slots:
        if not state.material:
            continue
        key = state.material.as_pointer()
        data = descriptions[key]
        generated = replacements.get(key)
        if generated is None:
            continue
        derived.materials[state.index] = generated
        needs_light |= data.role not in pmx.UNLIT
        if data.edge and data.edge_weight > 0 and data.alpha > 0 and data.edge_color[3] > 0 and data.role not in pmx.UNLIT:
            outline_pairs.append((generated, basic.build_outline(data, profile, cache), data.edge_weight))
    outlines.edge_attribute(entry.object, derived)
    surface_inputs.write_coverage(entry, derived, surface_plans)
    return {'entry': entry, 'mesh': derived,
            'face': controllers.face_group(profile, head) if needs_light else None,
            'outline': outlines.build(profile, outline_pairs)}


def owned_modifiers(obj, uid):
    return [m for m in obj.modifiers if m.type == 'NODES' and m.node_group and m.node_group.get('hzz_owner') == uid]


def apply(root, context):
    p = root.hzz_character
    descriptions = validate(root)
    before = ownership.snapshot()
    old_head, was_managed = p.head, p.managed
    old_generated = [b.generated for b in p.materials]
    states = [(e, e.object.data, e.derived, [(s.link, s.material) for s in e.object.material_slots]) for e in p.meshes]
    new_modifiers, old_modifiers = [], [(e.object, m) for e in p.meshes for m in owned_modifiers(e.object, p.uid)]
    p.building = True
    try:
        cache = basic.ImageCache(p.uid)
        surface_plans, surface_messages = surface_inputs.match(p, descriptions)
        replacements = {b.source.as_pointer(): basic.build(descriptions[b.source.as_pointer()], b, p, cache,
                        surface_plans.get(b.source.as_pointer()))
                        for b in p.materials if b.role != 'SKIP'}
        for key, material in replacements.items():
            if key in surface_messages:
                material['hzz_surface_inputs'] = surface_messages[key]
            if key in surface_plans:
                plan = surface_plans[key]
                material['hzz_surface_asset'] = json.dumps({'name': plan['name'], 'sha256': plan['sha256'],
                    'uv': plan['uv'], 'flip_v': plan['flip'], 'metrics': plan['metrics']}, ensure_ascii=False)
        head = controllers.create_head(root, context) if any(d.role == 'FACE' for d in descriptions.values()) else None
        pending = [prepare_mesh(e, p, replacements, head, descriptions, cache, surface_plans) for e in p.meshes]
        for item in pending:
            obj = item['entry'].object
            for kind in ('face', 'outline'):
                tree = item[kind]
                if tree is None:
                    continue
                modifier = obj.modifiers.new('HZZ • ' + kind.title(), 'NODES')
                modifier.node_group = tree
                modifier.show_viewport = modifier.show_render = False
                new_modifiers.append((obj, modifier))
                if kind == 'face':
                    controllers.set_modifier(modifier, 'Sun', p.sun)
                    controllers.set_modifier(modifier, 'Head', head)
                else:
                    outlines.update_modifier(modifier, p)
        for item in pending:
            entry = item['entry']
            entry.object.data = entry.derived = item['mesh']
            for state in entry.slots:
                entry.object.material_slots[state.index].link = 'DATA'
        p.head, p.managed = head, True
        for binding in p.materials:
            binding.generated = replacements.get(binding.source.as_pointer())
        for _obj, modifier in old_modifiers:
            modifier.show_viewport = modifier.show_render = False
        for _obj, modifier in new_modifiers:
            modifier.show_viewport = modifier.show_render = True
        refresh(root, modifiers=[m for _obj, m in new_modifiers])
        for obj, modifier in old_modifiers:
            obj.modifiers.remove(modifier)
        label = '共享 SDF' if p.face_mode == 'SDF' else '基础脸影'
        for binding in p.materials:
            key = binding.source.as_pointer()
            binding.diagnostic = '；'.join(descriptions[key].warnings + ([surface_messages[key]] if key in surface_messages else []))
        p.report = f'已应用 {len(replacements)} 个材质；{label}；增强图匹配 {len(surface_plans)} 个材质'
    except Exception:
        for entry, mesh, derived, slots in states:
            entry.object.data, entry.derived = mesh, derived
            for slot, (link, material) in zip(entry.object.material_slots, slots):
                slot.link = link
                if link == 'OBJECT':
                    slot.material = material
        p.head, p.managed = old_head, was_managed
        for binding, generated in zip(p.materials, old_generated):
            binding.generated = generated
        for obj, modifier in new_modifiers:
            obj.modifiers.remove(modifier)
        for _obj, modifier in old_modifiers:
            modifier.show_viewport = modifier.show_render = True
        bpy.data.batch_remove(ids=ownership.created(before))
        raise
    finally:
        p.building = False
    ownership.remove_unused(p.uid)
    return len(replacements)


def refresh(root, modifiers=None):
    p = root.hzz_character
    if not p.managed:
        return
    for binding in p.materials:
        if binding.generated:
            basic.refresh(binding.generated, binding, p)
    legacy_body = any(b.generated and b.role in {'BODY', 'HAIR'} and b.generated.node_tree.get('hzz_body_version') != 3 for b in p.materials)
    if legacy_body:
        p.report = '当前为旧版主体材质；请重置共用表面参数并重新应用以启用 0.5 配色与反射'
    if p.head:
        controllers.update_head(p.head, p.head_yaw)
    if modifiers is None:
        modifiers = [m for entry in p.meshes for m in owned_modifiers(entry.object, p.uid)]
    legacy_outline = False
    for modifier in modifiers:
        if modifier.node_group['hzz_kind'] == 'face':
            controllers.update_modifier(modifier, p)
        else:
            outlines.update_modifier(modifier, p)
            if modifier.node_group.get('hzz_outline_version') != outlines.VERSION:
                legacy_outline = True
            modifier.show_viewport = modifier.show_render = p.outline_width > 0
    if legacy_outline:
        p.report = p.report + '；重新应用同时更新描边' if legacy_body else '当前为旧版描边；请重新应用材质以启用 0.5.1 共用线宽倍率和线色控制'
    for entry in p.meshes:
        entry.object.update_tag()


def restore(root):
    p = root.hzz_character
    if not p.managed:
        raise ValueError('该角色尚未应用本插件材质')
    for entry in p.meshes:
        if not entry.object or entry.object.data != entry.derived:
            raise ValueError('角色网格引用已改变，请检查后再恢复')
    p.building = True
    try:
        for entry in p.meshes:
            obj = entry.object
            for modifier in owned_modifiers(obj, p.uid):
                obj.modifiers.remove(modifier)
            obj.data = entry.source
            for state in entry.slots:
                slot = obj.material_slots[state.index]
                slot.link = state.link
                if state.link == 'OBJECT':
                    slot.material = state.material
            entry.derived = None
        for binding in p.materials:
            binding.generated = None
        p.head, p.managed = None, False
        p.report = '已恢复源网格和原材质；独立预览场景可继续使用'
    finally:
        p.building = False
    ownership.remove_unused(p.uid)


def export_profile(root):
    p = root.hzz_character
    return {'schema': 1, 'source_format': 'pmx', 'face_mode': p.face_mode,
            'face_lightmap': p.face_lightmap.name if p.face_lightmap else None,
            'head_bone': p.head_bone, 'head_yaw': p.head_yaw,
            'materials': [{'name': b.source.name, 'role': b.role, 'evidence': b.evidence,
                           'use_toon': b.use_toon, 'use_sphere': b.use_sphere,
                           'diagnostic': b.diagnostic} for b in p.materials]}
