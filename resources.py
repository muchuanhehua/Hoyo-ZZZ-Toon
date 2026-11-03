"""Read an FBX package's references and UV topology; never import its geometry."""
import json
import re
from pathlib import Path
import bpy
import numpy as np
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree
from .materials import surface_inputs as inputs


def child(node, key):
    return next((n for n in node.elems if n.id == key), None)


def prop(node, key, default=None):
    item = child(node, key)
    return item.props[0] if item and item.props else default


def name(value):
    text = value.decode('utf8') if isinstance(value, bytes) else str(value)
    # Some resource exporters serialize the FBX namespace delimiter literally.
    return text.split('\x00')[0].split(r'\x00')[0]


def texture_path(folder, reference):
    relative = Path(reference.replace('\\', '/'))
    direct = folder / relative
    if direct.is_file():
        return direct.resolve()
    matches = [p for p in folder.rglob(relative.name) if p.is_file()]
    signatures = {inputs.sha(p) for p in matches}
    if len(signatures) != 1:
        raise ValueError('FBX 引用的贴图缺失或不唯一：' + relative.name)
    return matches[0].resolve()


def triangles(geometry):
    """Return first-UV triangles and material slots, honoring FBX mapping modes."""
    layer = next((n for n in geometry.elems if n.id == b'LayerElementUV'), None)
    indices = prop(geometry, b'PolygonVertexIndex')
    if layer is None or indices is None:
        return []
    vertices = np.asarray(indices, dtype=np.int64)
    polygon_ends = np.flatnonzero(vertices < 0)
    vertex_ids = np.where(vertices < 0, -vertices - 1, vertices)
    values = np.asarray(prop(layer, b'UV'), dtype=np.float64).reshape(-1, 2)
    mapping, reference = prop(layer, b'MappingInformationType'), prop(layer, b'ReferenceInformationType')
    if mapping in {b'ByVertice', b'ByVertex', b'ByControlPoint'}:
        lookup = vertex_ids
    elif mapping == b'ByPolygonVertex':
        lookup = np.arange(len(vertices))
    else:
        raise ValueError('FBX UV 映射不受支持：' + name(mapping))
    if reference == b'IndexToDirect':
        lookup = np.asarray(prop(layer, b'UVIndex'), dtype=np.int64)[lookup]
    elif reference != b'Direct':
        raise ValueError('FBX UV 引用不受支持：' + name(reference))
    uv = values[lookup]
    material_layer = child(geometry, b'LayerElementMaterial')
    slots = prop(material_layer, b'Materials', [0]) if material_layer else [0]
    material_mapping = prop(material_layer, b'MappingInformationType', b'AllSame') if material_layer else b'AllSame'
    if material_mapping not in {b'AllSame', b'ByPolygon'}:
        raise ValueError('FBX 材质映射不受支持：' + name(material_mapping))
    result, start = [], 0
    for index, end in enumerate(polygon_ends):
        slot = int(slots[index] if material_mapping == b'ByPolygon' else slots[0])
        for corner in range(start + 1, end):
            result.append((slot, uv[[start, corner, corner + 1]]))
        start = end + 1
    return result


def face_reference(folder, material_name, declared_lightmaps):
    files = list(folder.rglob(material_name + '.json'))
    if not files:
        return None
    if len(files) != 1:
        raise ValueError('FBX 材质说明不唯一：' + material_name)
    values = json.loads(files[0].read_text('utf-8-sig')).get('m_SavedProperties', {}).get('m_TexEnvs', {})
    record = values.get('_LightTex', {})
    pointer = record.get('m_Texture', {})
    reference = pointer.get('Name', '')
    if not reference:
        # Older exports omit Name even for a non-null texture pointer. Accept
        # only the one face lightmap actually declared inside this FBX, never a
        # gender/name guess or an arbitrary image found beside the model.
        if (not pointer.get('m_PathID') or pointer.get('IsNull', True)
                or not re.search(r'(?:^|[_ .])face(?:[_ .]|$)', material_name, re.I)):
            return None
        if len(declared_lightmaps) != 1:
            return None
        reference = declared_lightmaps[0].stem
    # Only an explicitly referenced face-lightmap is handled by this SDF decoder.
    if 'face' not in reference.casefold() or 'lightmap' not in reference.casefold():
        return None
    scale, offset = record.get('m_Scale', {}), record.get('m_Offset', {})
    if (scale.get('X', 1), scale.get('Y', 1), offset.get('X', 0), offset.get('Y', 0)) != (1, 1, 0, 0):
        raise ValueError('脸影引用包含尚不支持的 UV 缩放／偏移：' + material_name)
    matches = [p for p in folder.rglob(reference + '.*') if p.suffix.lower() in inputs.EXTENSIONS]
    if len({inputs.sha(p) for p in matches}) != 1:
        raise ValueError('脸影贴图缺失或不唯一：' + reference)
    return matches[0]


def native_assets(folder):
    from io_scene_fbx import parse_fbx
    paths = sorted(p for p in folder.rglob('*') if p.suffix.casefold() == '.fbx')
    if not paths:
        raise ValueError('所选目录没有 FBX 文件，请选择含 FBX、Textures 和 Materials 的资源文件夹')
    assets = {}
    for path in paths:
        try:
            tree, _version = parse_fbx.parse(str(path))
        except (OSError, ValueError, IOError) as exc:
            raise ValueError('无法读取 FBX：' + path.name + '；' + str(exc)) from exc
        objects = {n.props[0]: n for n in child(tree, b'Objects').elems if n.props}
        declared_lightmaps = {}
        for texture in objects.values():
            if texture.id == b'Texture':
                reference = name(prop(texture, b'RelativeFilename') or prop(texture, b'FileName'))
                if 'face' in reference.casefold() and 'lightmap' in reference.casefold():
                    resolved = texture_path(folder, reference)
                    declared_lightmaps[inputs.sha(resolved)] = resolved
        connections = child(tree, b'Connections').elems
        links = {}
        for c in connections:
            links.setdefault(c.props[2], []).append(c.props[1])
        for oid, geometry in objects.items():
            if geometry.id != b'Geometry' or geometry.props[-1] != b'Mesh':
                continue
            parents = [c.props[2] for c in connections if c.props[1] == oid and c.props[0] == b'OO']
            for parent in parents:
                materials = [objects[i] for i in links.get(parent, ()) if i in objects and objects[i].id == b'Material']
                by_slot = {}
                for slot, material in enumerate(materials):
                    textures = {c.props[1] for c in connections if c.props[2] == material.props[0]
                                and c.props[0] == b'OP' and c.props[-1] in {b'DiffuseColor', b'BaseColor'}}
                    references = {name(prop(objects[i], b'RelativeFilename') or prop(objects[i], b'FileName')) for i in textures}
                    if len(references) != 1:
                        continue
                    diffuse = texture_path(folder, next(iter(references)))
                    sdf = face_reference(folder, name(material.props[1]), list(declared_lightmaps.values()))
                    key = (str(diffuse), str(sdf) if sdf else '')
                    item = assets.setdefault(key, {'D': diffuse, 'sdf': sdf, 'triangles': [], 'materials': set()})
                    item['materials'].add(name(material.props[1]))
                    by_slot[slot] = item
                for slot, uv in triangles(geometry):
                    if slot in by_slot:
                        by_slot[slot]['triangles'].append(uv)
    for item in assets.values():
        item['triangles'] = np.asarray(item['triangles'], dtype=np.float64)
    return [item for item in assets.values() if len(item['triangles'])]


def triangle_key(uv):
    return tuple(sorted(tuple(p) for p in np.rint(uv * 100000).astype(np.int64)))


def source_uv(profile, data, cache):
    parts = []
    for entry in profile.meshes:
        slots = {s.index for s in entry.slots if s.material == data.source}
        if not slots:
            continue
        mesh = entry.source
        key = mesh.as_pointer(), data.uv
        if key not in cache:
            mesh.calc_loop_triangles()
            loops = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
            mesh.loop_triangles.foreach_get('loops', loops)
            slots_array = np.empty(len(mesh.loop_triangles), dtype=np.int32)
            mesh.loop_triangles.foreach_get('material_index', slots_array)
            layer = mesh.uv_layers[data.uv]
            values = np.empty(len(layer.data) * 2, dtype=np.float32)
            layer.data.foreach_get('uv', values)
            cache[key] = loops.reshape(-1, 3), slots_array, values.reshape(-1, 2)
        loops, slots_array, uv = cache[key]
        selected = loops[np.isin(slots_array, list(slots))]
        if len(selected):
            parts.append((mesh.as_pointer(), selected, uv[selected]))
    return parts


def uv_coverage(profile, data, asset, size, parts=None):
    # Compare the native sampling grid without ever changing the model's UVs.
    native = asset['triangles'].astype(np.float16).astype(np.float64)
    if 'lookup' not in asset:
        points = np.unique(native.reshape(-1, 2), axis=0)
        kd = KDTree(len(points))
        for i, point in enumerate(points):
            kd.insert((float(point[0]), float(point[1]), 0), i)
        kd.balance()
        asset['lookup'] = points, kd, {triangle_key(t) for t in native}
        vertices = native.reshape(-1, 2) * size
        asset['surface'] = BVHTree.FromPolygons(
            [(float(v[0]), float(v[1]), 0) for v in vertices],
            [(i, i + 1, i + 2) for i in range(0, len(vertices), 3)], all_triangles=True)
    points, kd, valid_triangles = asset['lookup']
    coverage, accepted, total, close_total, exact_total = {}, 0, 0, 0, 0
    for mesh_key, loops, uv in parts if parts is not None else source_uv(profile, data, {}):
        unique, inverse = np.unique(uv.reshape(-1, 2), axis=0, return_inverse=True)
        nearest = np.asarray([kd.find((float(v[0]), float(v[1]), 0))[1] for v in unique])
        close = np.linalg.norm((unique - points[nearest]) * size, axis=1) <= .8
        snapped = points[nearest][inverse].reshape(uv.shape)
        point_valid = close[inverse].reshape(-1, 3).all(axis=1)
        weights = np.asarray([bool(valid and triangle_key(tri) in valid_triangles)
            for valid, tri in zip(point_valid, snapped)], dtype=np.float32)
        exact_total += int(weights.sum())
        # PMX conversion may change the diagonal of a UV quad. In that case
        # require all original corners AND seven interior/edge samples to lie
        # on the same referenced native UV surface within the texel tolerance.
        for index in np.flatnonzero(point_valid & (weights == 0)):
            probes = inputs.BARYCENTRIC @ uv[index] * size
            hits = [asset['surface'].find_nearest((float(v[0]), float(v[1]), 0), .8) for v in probes]
            weights[index] = float(all(hit[0] is not None for hit in hits))
        coverage[mesh_key] = (loops, weights)
        accepted += int(weights.sum())
        close_total += int(close[inverse].reshape(-1, 3).all(axis=1).sum())
        total += len(weights)
    return coverage, {'triangles': total, 'matched': accepted, 'fraction': accepted / max(total, 1),
                      'within_texel_tolerance_fraction': close_total / max(total, 1),
                      'exact_triangle_fraction': exact_total / max(total, 1),
                      'method': 'fbx-material-reference-and-uv-triangles'}


def match(profile, descriptions):
    directory = profile.fbx_directory
    if not directory:
        profile.face_mode = 'BASIC'
        profile.resource_report = '使用 PMX 基础渲染'
        return {}, {}
    folder = Path(bpy.path.abspath(directory)).resolve()
    if not folder.is_dir():
        raise ValueError('FBX 目录不存在：' + str(folder))
    assets = native_assets(folder)
    bundles = inputs.families(str(folder))
    bundle_by_d = {b['sha256']['D']: b for b in bundles}
    for asset in assets:
        asset['bundle'] = bundle_by_d.get(inputs.sha(asset['D']))
        image = bpy.data.images.load(str(asset['D']), check_existing=False)
        try:
            asset['size'] = np.asarray(image.size[:], dtype=np.float64)
        finally:
            bpy.data.images.remove(image)
    plans, messages, face_matches, uv_cache = {}, {}, {}, {}
    for data in descriptions.values():
        if data.role not in {'BODY', 'HAIR', 'FACE'}:
            continue
        scores = []
        parts = source_uv(profile, data, uv_cache)
        for asset in assets:
            bundle = asset['bundle']
            if (data.role == 'FACE' and not asset['sdf']) or (data.role != 'FACE' and not bundle):
                continue
            coverage, metrics = uv_coverage(profile, data, asset, asset['size'], parts)
            scores.append((metrics['fraction'], asset, bundle, coverage, metrics))
        scores.sort(key=lambda item: item[0], reverse=True)
        best = scores[0] if scores else None
        ambiguous = bool(len(scores) > 1 and scores[1][0] > best[0] - .2
                         and (scores[1][1]['D'] != best[1]['D'] or scores[1][1]['sdf'] != best[1]['sdf']))
        if not best or best[0] < (.9 if data.role == 'FACE' else .8) or ambiguous:
            messages[data.source.as_pointer()] = ('FBX 候选有歧义' if ambiguous else 'FBX 的材质／UV 未对应') + (
                f'（最佳 UV 覆盖 {best[0]:.1%}）' if best else '') + '，保留基础渲染'
            if data.role == 'FACE':
                face_matches[data.source.as_pointer()] = None
            continue
        _score, asset, bundle, coverage, metrics = best
        if data.role == 'FACE':
            face_matches[data.source.as_pointer()] = asset['sdf']
        else:
            plans[data.source.as_pointer()] = dict(bundle, flip=False, uv=data.uv, coverage=coverage, metrics=metrics)
        messages[data.source.as_pointer()] = 'FBX 自动对应：' + ', '.join(sorted(asset['materials'])) + f'；UV 区域 {best[0]:.1%}'
    matched_faces = [path for path in face_matches.values() if path]
    for binding in profile.materials:
        if binding.role == 'FACE':
            binding.sdf_enabled = bool(face_matches.get(binding.source.as_pointer()))
    if matched_faces:
        hashes = {inputs.sha(path) for path in matched_faces}
        if len(hashes) != 1:
            raise ValueError('当前模型的多个脸部材质引用了不同脸影资源，无法共用一个脸影控制')
        from .materials.face import validate_image
        image = bpy.data.images.load(str(matched_faces[0]), check_existing=True)
        validate_image(image)
        profile.face_lightmap, profile.face_mode = image, 'SDF'
    else:
        profile.face_mode = 'BASIC'
    profile.resource_report = f'自动匹配 {len(plans)} 个材质；' + (f'SDF 脸部 {len(matched_faces)}/{len(face_matches)}' if profile.face_mode == 'SDF' else '使用基础脸影')
    return plans, messages
