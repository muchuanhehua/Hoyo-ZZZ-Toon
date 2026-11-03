"""Collect referenced data-map sets and write verified per-loop coverage."""
from pathlib import Path
import hashlib
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
