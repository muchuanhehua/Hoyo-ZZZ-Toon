"""Verify control atlases against the diffuse pixels actually used by PMX faces.

No character catalog, atlas-to-material JSON guess, or source UV modification.
The conservative sampled-region method is informed by RandomPlayToon's
source_asset_match.py (GPL-3.0, 87ebc01de7c6a1ab4796b7da7196b88830d74667).
"""
from pathlib import Path
import hashlib
import json
import re
import bpy
import numpy as np

COVERAGE = 'HZZ_DATA_COVERAGE'
EXTENSIONS = {'.png', '.tga', '.dds', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp'}
BARYCENTRIC = np.array(((1/3, 1/3, 1/3), (.8, .1, .1), (.1, .8, .1),
                        (.1, .1, .8), (.45, .45, .1), (.45, .1, .45), (.1, .45, .45)))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def families(directory):
    folder = Path(bpy.path.abspath(directory)).resolve()
    if not folder.is_dir():
        raise ValueError('原始贴图目录不存在：' + str(folder))
    groups = {}
    for path in sorted(folder.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        match = re.fullmatch(r'(.+)_([DMAN])', path.stem, re.I)
        if match:
            key = (path.parent, match[1].casefold())
            groups.setdefault(key, {}).setdefault(match[2].upper(), []).append(path)
    bundles, seen = [], set()
    for (_parent, name), maps in groups.items():
        if not all(len(maps.get(k, [])) == 1 for k in 'DMAN'):
            continue
        paths = {k: maps[k][0] for k in 'DMAN'}
        hashes = {k: sha(p) for k, p in paths.items()}
        signature = tuple(hashes[k] for k in 'DMAN')
        if signature not in seen:
            bundles.append({'name': name, 'paths': paths, 'sha256': hashes})
            seen.add(signature)
    if not bundles:
        raise ValueError('目录中没有唯一配套的 _D / _M / _A / _N 贴图组')
    return bundles


def raw_pixels(source):
    """A disposable Non-Color copy avoids changing the imported image's state."""
    if isinstance(source, bpy.types.Image):
        image = source.copy()
    else:
        image = bpy.data.images.load(str(source), check_existing=False)
    try:
        image.colorspace_settings.name = 'Non-Color'
        image.alpha_mode = 'CHANNEL_PACKED'
        width, height = image.size
        if not width or not height or image.channels not in {3, 4}:
            raise ValueError('无法读取 RGBA 贴图：' + image.name)
        data = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(data)
        return data.reshape(height, width, 4)[:, :, :3].copy()
    finally:
        bpy.data.images.remove(image)


def sample(pixels, uv):
    height, width = pixels.shape[:2]
    xy = np.mod(uv, 1) * (width, height) - .5
    lower = np.floor(xy).astype(np.int64)
    f = xy - lower
    x, y = lower[..., 0] % width, lower[..., 1] % height
    nx, ny = (x + 1) % width, (y + 1) % height
    a = pixels[y, x] * (1 - f[..., :1]) + pixels[y, nx] * f[..., :1]
    b = pixels[ny, x] * (1 - f[..., :1]) + pixels[ny, nx] * f[..., :1]
    return a * (1 - f[..., 1:2]) + b * f[..., 1:2]


def triangles(profile, source, uv_name):
    parts = []
    for entry in profile.meshes:
        slots = {s.index for s in entry.slots if s.material == source}
        mesh = entry.source
        if not slots:
            continue
        layer = mesh.uv_layers.get(uv_name)
        if layer is None:
            raise ValueError('增强贴图匹配缺少 UV：' + mesh.name)
        mesh.calc_loop_triangles()
        selected = [t for t in mesh.loop_triangles if t.material_index in slots]
        if not selected:
            continue
        loops = np.array([t.loops[:] for t in selected], dtype=np.int32)
        uvs = np.array([v.uv[:] for v in layer.data], dtype=np.float64)[loops]
        points = np.einsum('sv,tvc->tsc', BARYCENTRIC, uvs)
        parts.append((mesh.as_pointer(), loops, points))
    return parts


def uv_identity(profile, source, uv_name):
    points = []
    for entry in profile.meshes:
        slots = {s.index for s in entry.slots if s.material == source}
        layer = entry.source.uv_layers.get(uv_name)
        if not slots or layer is None:
            continue
        points.extend(tuple(round(float(c), 6) for c in layer.data[i].uv)
                      for polygon in entry.source.polygons if polygon.material_index in slots
                      for i in polygon.loop_indices)
    return hashlib.sha256(json.dumps(sorted(set(points)), separators=(',', ':')).encode()).hexdigest()


def evidence_plan(profile, data, pixels, bundles, records):
    pixel_sha = hashlib.sha256(pixels.tobytes()).hexdigest()
    identity = uv_identity(profile, data.source, data.uv)
    matches = [r for r in records if r['base_rgb_sha256'] == pixel_sha and r['uv_sha256'] == identity]
    if not matches:
        return None
    signatures = {json.dumps(r, sort_keys=True) for r in matches}
    if len(signatures) != 1:
        raise ValueError('UV 资产对应证据冲突：' + data.source.name)
    record = matches[0]
    matches = [b for b in bundles if b['sha256'] == record['atlas_sha256']]
    if len(matches) != 1:
        raise ValueError('UV 对应证据中的增强图已改变或不在资源目录：' + data.source.name)
    valid = {tuple(round(float(c), 6) for c in point) for point in record['valid_uv']}
    coverage, total, accepted = {}, 0, 0
    for entry in profile.meshes:
        slots = {s.index for s in entry.slots if s.material == data.source}
        if not slots:
            continue
        mesh = entry.source
        mesh.calc_loop_triangles()
        layer = mesh.uv_layers[data.uv]
        selected = [t for t in mesh.loop_triangles if t.material_index in slots]
        loops = np.array([t.loops[:] for t in selected], dtype=np.int32)
        weights = np.array([all(tuple(round(float(c), 6) for c in layer.data[i].uv) in valid for i in tri)
                            for tri in loops], dtype=np.float32)
        coverage[mesh.as_pointer()] = (loops, weights)
        total += len(weights)
        accepted += int(weights.sum())
    if not accepted:
        raise ValueError('UV 对应证据未覆盖任何三角面：' + data.source.name)
    return dict(matches[0], flip=False, uv=data.uv, coverage=coverage,
        metrics={'triangles': total, 'matched': accepted, 'fraction': accepted / total,
                 'method': 'explicit-verified-uv-correspondence', 'evidence': record['provenance']})


def match(profile, descriptions):
    if not profile.surface_directory:
        return {}, {key: '未指定增强贴图目录，使用 PMX 基础响应' for key, d in descriptions.items()
                    if d.role in {'BODY', 'HAIR'}}
    bundles = families(profile.surface_directory)
    records = []
    if profile.surface_evidence:
        path = Path(bpy.path.abspath(profile.surface_evidence))
        document = json.loads(path.read_text(encoding='utf-8'))
        if document.get('schema') != 1 or document.get('kind') != 'hzz-uv-correspondence':
            raise ValueError('不支持的 UV 资产对应证据文件')
        records = document['records']
    diffuse = {b['name'] + b['sha256']['D']: raw_pixels(b['paths']['D']) for b in bundles}
    plans, messages, source_pixels = {}, {}, {}
    for key, data in descriptions.items():
        if data.role not in {'BODY', 'HAIR'}:
            continue
        if 'base' not in data.textures:
            messages[key] = '无基础贴图，未接入增强图'
            continue
        parts = triangles(profile, data.source, data.uv)
        if not parts:
            messages[key] = '无可验证的材质三角面，未接入增强图'
            continue
        source = data.textures['base']
        identity = source.as_pointer()
        if identity not in source_pixels:
            source_pixels[identity] = raw_pixels(source)
        pixels = source_pixels[identity]
        attested = evidence_plan(profile, data, pixels, bundles, records) if records else None
        if attested:
            plans[key] = attested
            messages[key] = f'增强图：{attested["name"]}；已核对 UV 区域 {attested["metrics"]["fraction"]:.1%}'
            continue
        points = np.concatenate([part[2] for part in parts])
        # Bound candidate ranking cost, then verify every triangle of the winner.
        indices = np.linspace(0, len(points) - 1, min(len(points), 800), dtype=np.int32)
        probe = points[indices]
        source_probe = sample(pixels, probe)
        scores = []
        for bundle in bundles:
            original = diffuse[bundle['name'] + bundle['sha256']['D']]
            exact = pixels.shape == original.shape and np.array_equal(pixels, original)
            for flip in (False, True):
                mapped = probe.copy()
                if flip:
                    mapped[..., 1] = 1 - mapped[..., 1]
                difference = np.abs(source_probe - sample(original, mapped)).mean(axis=-1) * 255
                scores.append((float(difference.mean()), float((difference < 12).mean()),
                               exact and not flip, bundle, flip))
        scores.sort(key=lambda row: row[0])
        best = scores[0]
        varied = float(source_probe.reshape(-1, 3).std(axis=0).max() * 255) > 7
        # Ranking only selects a candidate. The stricter per-triangle gate
        # below still excludes edited islands instead of enabling the atlas.
        valid = best[2] or (varied and best[0] < 8 and best[1] > .75)
        ambiguous = len(scores) > 1 and scores[1][0] < max(best[0] * 1.5, best[0] + 2)
        if not valid or ambiguous:
            messages[key] = (('候选增强图有歧义' if ambiguous else '基础图与原始图的 UV 采样不匹配')
                + f'（误差 {best[0]:.2f}/255，一致区域 {best[1]:.1%}），保留基础响应')
            continue
        bundle, flip = best[3:]
        original = diffuse[bundle['name'] + bundle['sha256']['D']]
        coverage, accepted, total = {}, 0, 0
        for mesh_key, loops, points in parts:
            mapped = points.copy()
            if flip:
                mapped[..., 1] = 1 - mapped[..., 1]
            difference = np.abs(sample(pixels, points) - sample(original, mapped)).mean(axis=-1) * 255
            confidence = ((difference.mean(axis=1) < 7) & (difference.max(axis=1) < 18)).astype(np.float32)
            coverage[mesh_key] = (loops, confidence)
            accepted += int(confidence.sum())
            total += len(confidence)
        if not accepted:
            messages[key] = '没有通过像素核对的三角面，保留基础响应'
            continue
        plans[key] = dict(bundle, flip=flip, uv=data.uv, coverage=coverage,
                          metrics={'triangles': total, 'matched': accepted, 'fraction': accepted / total,
                                   'sample_mean_error_255': best[0], 'sample_inlier_fraction': best[1]})
        messages[key] = f'增强图：{bundle["name"]}；UV 区域 {accepted / total:.1%}'
    return plans, messages


def write_coverage(entry, derived, plans):
    attr = None
    for plan in plans.values():
        part = plan['coverage'].get(entry.source.as_pointer())
        if part is None:
            continue
        if attr is None:
            attr = derived.attributes.new(COVERAGE, 'FLOAT', 'CORNER')
        loops, confidence = part
        values = np.ones(len(derived.loops), dtype=np.float32)
        np.minimum.at(values, loops.ravel(), np.repeat(confidence, 3))
        for index in np.unique(loops):
            attr.data[int(index)].value = float(values[index])
    derived.update()
