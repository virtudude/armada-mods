#!/usr/bin/env python3
"""Lazily decode original static inventory meshes from the player's installation.

Runtime output only: no NIF, mesh, material, or texture belongs in the package.
Supported: base Fallout4.esm records and FO4 stream-130 static BSTriShape meshes.
Modular dummy receivers, skinned meshes, plugin load-order resolution and runtime
OMOD instance assembly are intentionally unsupported. Material shading is a
preview approximation, not the game's complete lighting shader.

Format references: https://github.com/niftools/nifxml/blob/develop/nif.xml
https://github.com/ousnius/Material-Editor/tree/master/MaterialLib
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import zlib

from assets import Archive, AssetError, MAX_PAYLOAD, atomic_write, decode_texture, exact, inflate, png_bytes

SCHEMA = 3
RECORD_TYPES = {b'WEAP', b'ARMO', b'ALCH', b'MISC', b'AMMO', b'KEYM', b'BOOK', b'NOTE'}


class ModelError(AssetError):
    pass


class Reader:
    def __init__(self, data):
        self.data, self.position = data, 0

    def take(self, count):
        if count < 0 or self.position + count > len(self.data):
            raise ModelError('Truncated model data')
        result = self.data[self.position:self.position + count]
        self.position += count
        return result

    def unpack(self, fmt):
        values = struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))
        return values[0] if len(values) == 1 else values

    def string(self, count):
        if count > 65536:
            raise ModelError('Model string is too long')
        return self.take(count).rstrip(b'\0').decode('utf-8', errors='strict')

    def sized_string(self):
        return self.string(self.unpack('I'))


def asset_path(name, prefix):
    value = name.replace('\\', '/').lower()
    if not value.startswith(prefix + '/'):
        value = prefix + '/' + value
    if any(part in ('', '.', '..') for part in value.split('/')) or ':' in value:
        raise ModelError('Invalid game asset path')
    return value


def signature(path):
    st = Path(path).stat()
    return [st.st_size, st.st_mtime_ns]


def subrecords(data):
    r = Reader(data)
    extended = None
    while r.position < len(data):
        kind, length = r.unpack('4sH')
        if kind == b'XXXX':
            if length != 4 or extended is not None:
                raise ModelError('Invalid extended ESM field')
            extended = r.unpack('I')
            continue
        yield kind, r.take(extended if extended is not None else length)
        extended = None
    if extended is not None:
        raise ModelError('Unterminated extended ESM field')


def model_index(game_dir, data_dir):
    esm = Path(game_dir) / 'Data/Fallout4.esm'
    cache = Path(data_dir) / 'assets/models/index.json'
    source = signature(esm)
    try:
        saved = json.loads(cache.read_text())
        if saved.get('schema') == SCHEMA and saved.get('source') == source:
            return saved['records']
    except (OSError, ValueError, KeyError):
        pass
    records = {}
    size = esm.stat().st_size
    with esm.open('rb') as stream:
        while stream.tell() < size:
            offset = stream.tell()
            header = exact(stream, 24)
            kind, length, flags, form_id = struct.unpack_from('<4sIII', header)
            if kind == b'GRUP':
                if length < 24 or offset + length > size:
                    raise ModelError('Invalid ESM group')
                continue
            if offset + 24 + length > size:
                raise ModelError('Invalid ESM record')
            if kind not in RECORD_TYPES:
                stream.seek(length, 1)
                continue
            if length > MAX_PAYLOAD:
                raise ModelError('ESM record too large')
            data = exact(stream, length)
            if flags & 0x40000:
                expected = struct.unpack_from('<I', data)[0]
                data = inflate(data[4:], expected)
            fields = list(subrecords(data))
            model_tag = b'MOD2' if kind == b'ARMO' else b'MODL'
            model = next((v.rstrip(b'\0').decode('utf-8') for k, v in fields
                          if k == model_tag and v.lower().endswith(b'.nif\0')), None)
            if model:
                records[str(form_id)] = {
                    'mesh': asset_path(model, 'meshes'), 'type': kind.decode(),
                    'editorID': next((v.rstrip(b'\0').decode('utf-8') for k, v in fields if k == b'EDID'), ''),
                    'objectTemplate': any(k == b'OBTE' for k, _ in fields),
                    'materialSwap': any(k in (b'MODS', b'MO2S', b'MO4S') for k, _ in fields), 'recordOffset': offset}
    atomic_write(cache, json.dumps({'schema': SCHEMA, 'source': source, 'records': records}).encode())
    return records


def ni_av(r, strings):
    name = r.unpack('i')
    count = r.unpack('I')
    if count > 10000:
        raise ModelError('Excessive NIF extra data')
    r.take(count * 4)
    r.unpack('i')  # controller
    flags = r.unpack('I')
    translation = r.unpack('3f')
    rotation = r.unpack('9f')
    scale = r.unpack('f')
    r.unpack('i')  # collision
    values = (*translation, *rotation, scale)
    if not all(math.isfinite(v) and abs(v) < 1e9 for v in values):
        raise ModelError('Invalid NIF transform')
    return {'name': strings[name] if 0 <= name < len(strings) else '', 'flags': flags,
            'translation': translation, 'rotation': rotation, 'scale': scale}


def transform(vector, node, normal=False):
    m = node['rotation']
    rotated = [sum(m[row * 3 + col] * vector[col] for col in range(3)) for row in range(3)]
    if normal:
        return rotated
    return [rotated[i] * node['scale'] + node['translation'][i] for i in range(3)]


def parse_nif(data):
    r = Reader(data)
    newline = data.find(b'\n', 0, 128)
    if newline < 0 or not data.startswith(b'Gamebryo File Format, Version 20.2.0.7'):
        raise ModelError('Unsupported NIF header')
    r.take(newline + 1)
    version, endian, user, count, stream = r.unpack('IBIII')
    if (version, endian, user, stream) != (0x14020007, 1, 12, 130) or count > 100000:
        raise ModelError('Only Fallout 4 stream-130 NIF is supported')
    for _ in range(4):
        r.string(r.unpack('B'))
    num_types = r.unpack('H')
    types = [r.sized_string() for _ in range(num_types)]
    type_ids = [r.unpack('H') for _ in range(count)]
    sizes = [r.unpack('I') for _ in range(count)]
    num_strings, _ = r.unpack('II')
    if num_strings > 100000:
        raise ModelError('Excessive NIF string table')
    strings = [r.sized_string() for _ in range(num_strings)]
    r.take(r.unpack('I') * 4)
    blocks = []
    for type_id, size in zip(type_ids, sizes):
        if type_id >= len(types):
            raise ModelError('Invalid NIF block type')
        blocks.append((types[type_id], r.take(size)))
    roots = [r.unpack('i') for _ in range(r.unpack('I'))]
    nodes, parents, shapes = {}, {}, []
    for i, (kind, block) in enumerate(blocks):
        if kind in ('NiNode', 'BSFadeNode', 'BSOrderedNode'):
            b = Reader(block)
            nodes[i] = ni_av(b, strings)
            for _ in range(b.unpack('I')):
                child = b.unpack('i')
                if child < 0:
                    continue
                if child >= len(blocks) or child in parents:
                    raise ModelError('Invalid or shared NIF scene node')
                parents[child] = i
        elif kind in ('BSTriShape', 'BSSubIndexTriShape'):
            b = Reader(block)
            node = ni_av(b, strings)
            nodes[i] = node
            b.take(16)  # bounding sphere; derive our own bounds after transforms
            skin, shader, alpha = b.unpack('3i')
            desc, triangles, vertices, data_size = b.unpack('QIHI')
            stride, attrs = (desc & 15) * 4, desc >> 44
            if not vertices or not triangles or not data_size or node['flags'] & 1:
                continue
            if skin >= 0 or attrs & 0x40:
                raise ModelError('Skinned inventory model needs the game skeleton')
            if not attrs & 1 or stride < 8 or data_size != stride * vertices + triangles * 6:
                raise ModelError('Unsupported NIF vertex layout')
            if triangles > 500000:
                raise ModelError('Mesh exceeds preview limit')
            raw = b.take(stride * vertices)
            indices = list(b.unpack('H' * (triangles * 3)))
            if max(indices) >= vertices:
                raise ModelError('Invalid NIF triangle index')
            positions, normals, uvs = [], [], []
            uv_offset = ((desc >> 8) & 15) * 4
            normal_offset = ((desc >> 16) & 15) * 4
            if (attrs & 2 and uv_offset + 4 > stride) or (attrs & 8 and normal_offset + 3 > stride):
                raise ModelError('Invalid NIF vertex attribute offset')
            for v in range(vertices):
                offset = v * stride
                pos = struct.unpack_from('<3f' if attrs & 0x400 else '<3e', raw, offset)
                if not all(math.isfinite(x) and abs(x) < 1e9 for x in pos):
                    raise ModelError('Invalid NIF vertex position')
                positions.append(list(pos))
                uv = list(struct.unpack_from('<2e', raw, offset + uv_offset)) if attrs & 2 else [0., 0.]
                if not all(math.isfinite(x) for x in uv):
                    raise ModelError('Invalid NIF texture coordinate')
                uvs.append(uv)
                normals.append([(x / 127.5 - 1) for x in raw[offset + normal_offset:offset + normal_offset + 3]] if attrs & 8 else [0., 0., 1.])
            shapes.append({'node': i, 'name': node['name'], 'positions': positions, 'normals': normals,
                           'uvs': uvs, 'indices': indices, 'shader': shader, 'alphaProperty': alpha})
        elif 'TriShape' in kind or 'TriStrips' in kind:
            raise ModelError('Unsupported NIF geometry: ' + kind)
    visible = []
    for shape in shapes:
        chain, seen, current = [], set(), shape['node']
        while current in nodes:
            if current in seen:
                raise ModelError('Cyclic NIF scene graph')
            seen.add(current)
            chain.append(nodes[current])
            if current not in parents:
                break
            current = parents[current]
        if any(node['flags'] & 1 for node in chain) or current not in roots:
            continue
        for node in chain:
            shape['positions'] = [transform(v, node) for v in shape['positions']]
            shape['normals'] = [transform(v, node, True) for v in shape['normals']]
        shape['normals'] = [[x / (math.sqrt(sum(y*y for y in v)) or 1) for x in v] for v in shape['normals']]
        shader = shape.pop('shader')
        shape.pop('node')
        shape['material'], shape['diffuseSource'] = '', ''
        shape['alpha'] = 1.
        if 0 <= shader < len(blocks) and blocks[shader][0] == 'BSLightingShaderProperty':
            b = Reader(blocks[shader][1])
            b.unpack('I')  # shader type precedes NiObjectNET in this class
            name = b.unpack('i')
            shape['material'] = strings[name] if 0 <= name < len(strings) else ''
            b.take(b.unpack('I') * 4)
            b.take(4 + 8 + 16)  # controller, flags1/2, UV offset/scale
            texture_set = b.unpack('i')
            b.take(16 + 4 + 4)  # emissive RGB/multiplier, root material string, clamp mode
            shape['alpha'] = b.unpack('f')
            if 0 <= texture_set < len(blocks) and blocks[texture_set][0] == 'BSShaderTextureSet':
                t = Reader(blocks[texture_set][1])
                texture_count = t.unpack('I')
                if texture_count:
                    shape['diffuseSource'] = t.sized_string()
        visible.append(shape)
    if not visible:
        raise ModelError('No supported visible static triangles in this model')
    all_positions = [p for shape in visible for p in shape['positions']]
    return {'schema': SCHEMA, 'coordinateSystem': 'Fallout4 Z-up',
            'bounds': {'min': [min(p[i] for p in all_positions) for i in range(3)],
                       'max': [max(p[i] for p in all_positions) for i in range(3)]}, 'primitives': visible}


def parse_bgsm(data):
    r = Reader(data)
    magic, version = r.unpack('4sI')
    if magic != b'BGSM' or version not in (1, 2):
        raise ModelError('Only Fallout 4 BGSM versions 1/2 are supported')
    tile = r.unpack('I')
    offset, scale = r.unpack('2f'), r.unpack('2f')
    alpha = r.unpack('f')
    blend, src, dst = r.unpack('BII')
    alpha_ref, alpha_test = r.unpack('BB')
    zwrite, ztest, ssr, wet, decal, two_sided, nofade, nonoccluder = r.unpack('8B')
    r.take(2 + 4 + 1 + 4 + 1)  # refraction, power, envmap, scale, grayscale
    return {'diffuseSource': r.sized_string(), 'alpha': alpha, 'twoSided': bool(two_sided),
            'alphaTest': alpha_ref / 255 if alpha_test else 0, 'alphaBlend': bool(blend),
            'uvOffset': offset, 'uvScale': scale, 'tileFlags': tile}


class GameAssets:
    def __init__(self, game_dir):
        self.data = Path(game_dir) / 'Data'
        self.archives = {}

    def archive(self, filename):
        if filename not in self.archives:
            self.archives[filename] = Archive(self.data / filename)
        return self.archives[filename]

    def read(self, name, archive):
        loose = self.data / name
        if loose.is_file():
            if loose.stat().st_size > MAX_PAYLOAD:
                raise ModelError('Loose game asset too large')
            return loose.read_bytes()
        return self.archive(archive).read(name)[1]

    def texture(self, name, output):
        name = asset_path(name, 'textures')
        for archive_path in sorted(self.data.glob('Fallout4 - Textures*.ba2')):
            archive = self.archive(archive_path.name)
            record = archive.entries.get(name)
            if not record:
                continue
            texture_key = json.dumps([name, signature(archive_path)]).encode()
            filename = 'texture-' + hashlib.sha256(texture_key).hexdigest()[:20] + '.png'
            target = output / filename
            if target.exists():
                return 'assets/models/' + filename
            width, height, fmt = record['width'], record['height'], record['format']
            if fmt not in (71, 72, 77, 78):
                raise ModelError('Unsupported diffuse texture format ' + str(fmt))
            mip = 0
            while max(width >> mip, height >> mip) > 512:
                mip += 1
            chunk = next((c for c in record['chunks'] if c[3] <= mip <= c[4]), None)
            if chunk is None:
                # Some UI/shared textures store only their base mip.
                available = [(n, c) for c in record['chunks'] for n in range(c[3], c[4] + 1)]
                if not available:
                    raise ModelError('Missing diffuse mip')
                mip, chunk = min(available, key=lambda entry: abs(entry[0] - mip))
            offset, packed, unpacked, first, last = chunk
            if unpacked > MAX_PAYLOAD or packed > MAX_PAYLOAD or offset + (packed or unpacked) > archive.size:
                raise ModelError('Invalid texture chunk')
            with archive.path.open('rb') as stream:
                stream.seek(offset)
                raw = exact(stream, packed or unpacked)
            if packed:
                raw = inflate(raw, unpacked)
            block_size = 8 if fmt in (71, 72) else 16
            skip = sum(((max(1, width >> n) + 3) // 4) * ((max(1, height >> n) + 3) // 4) * block_size for n in range(first, mip))
            w, h = max(1, width >> mip), max(1, height >> mip)
            pixels = decode_texture(raw[skip:], w, h, fmt)
            if max(w, h) > 512:
                factor = 1
                while max(w // factor, h // factor) > 512:
                    factor *= 2
                nw, nh = max(1, w // factor), max(1, h // factor)
                pixels = b''.join(pixels[(y * factor * w + x * factor) * 4:(y * factor * w + x * factor) * 4 + 4]
                                  for y in range(nh) for x in range(nw))
                w, h = nw, nh
            atomic_write(target, png_bytes(pixels, w, h))
            return 'assets/models/' + filename
        raise ModelError('Diffuse texture is not present in installed base archives')


def prepare_model(game_dir, data_dir, form_id):
    """Return a ready/unsupported descriptor; safe to call in a background worker.

    Calls should be serialized by one asset worker. Paths are relative to data_dir.
    A ready result uses the original base mesh; instanceExact explicitly identifies
    records whose runtime OMOD attachments cannot be recovered from companion data.
    """
    form_id = int(form_id)
    output = Path(data_dir) / 'assets/models'
    output.mkdir(parents=True, exist_ok=True)
    descriptor = {'status': 'unsupported', 'formID': form_id}
    try:
        if not 0 <= form_id < 0x01000000:
            raise ModelError('Plugin and generated FormIDs need load-order-aware resolution')
        records = model_index(game_dir, data_dir)
        record = records.get(str(form_id))
        if not record:
            raise ModelError('This base form has no supported inventory model')
        if record['materialSwap']:
            raise ModelError('This form requires an ESM material-swap record that is not yet decoded')
        mesh = record['mesh']
        if 'dummy' in mesh:
            raise ModelError('This weapon requires runtime attachment assembly; companion data does not include attachment IDs')
        key = hashlib.sha256(json.dumps([SCHEMA, record, signature(Path(game_dir) / 'Data/Fallout4.esm'),
            [(p.name, signature(p)) for p in sorted((Path(game_dir) / 'Data').glob('Fallout4 - *.ba2'))
             if any(kind in p.name for kind in ('Meshes', 'Materials', 'Textures'))]], sort_keys=True).encode()).hexdigest()
        target = output / (str(form_id) + '.json')
        try:
            saved = json.loads(target.read_text())
            if saved.get('cacheKey') == key:
                return saved['descriptor']
        except (OSError, ValueError, KeyError):
            pass
        game = GameAssets(game_dir)
        model = parse_nif(game.read(mesh, 'Fallout4 - Meshes.ba2'))
        warnings = []
        for primitive in model['primitives']:
            material = primitive['material']
            if material.lower().endswith('.bgsm'):
                try:
                    primitive.update(parse_bgsm(game.read(asset_path(material, 'materials'), 'Fallout4 - Materials.ba2')))
                except (OSError, KeyError, ValueError) as exc:
                    warnings.append('Material override unavailable: ' + str(exc))
            diffuse = primitive.get('diffuseSource')
            primitive['diffuse'] = None
            if diffuse:
                try:
                    primitive['diffuse'] = game.texture(diffuse, output)
                except (OSError, KeyError, ValueError) as exc:
                    warnings.append('Diffuse texture unavailable: ' + str(exc))
        instance_exact = not record['objectTemplate']
        if not instance_exact:
            warnings.append('Base form mesh only; runtime attachment and material modifications are unavailable')
        descriptor = {'status': 'ready', 'formID': form_id, 'path': 'assets/models/' + target.name,
                      'source': mesh, 'recordType': record['type'], 'instanceExact': instance_exact,
                      'triangles': sum(len(p['indices']) // 3 for p in model['primitives']),
                      'bounds': model['bounds'], 'warnings': sorted(set(warnings))}
        model.update({'cacheKey': key, 'descriptor': descriptor})
        atomic_write(target, json.dumps(model, separators=(',', ':'), allow_nan=False).encode())
    except (OSError, KeyError, ValueError, struct.error) as exc:
        descriptor['reason'] = str(exc)
    return descriptor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', required=True)
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--form-id', action='append', type=lambda text: int(text, 0), required=True)
    args = parser.parse_args()
    result = {str(form): prepare_model(args.game_dir, args.data_dir, form) for form in args.form_id}
    target = Path(args.data_dir) / 'assets/models/manifest.json'
    try:
        manifest = json.loads(target.read_text())
    except (OSError, ValueError):
        manifest = {'schema': SCHEMA, 'models': {}}
    manifest['models'].update(result)
    atomic_write(target, json.dumps(manifest, indent=2).encode())
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
