"""Extract original Pip-Boy glass/scanline textures, never bundle game pixels."""
import base64
import json
from pathlib import Path
import struct
import zlib

from assets import Archive, AssetError, atomic_write, decode_texture, png_bytes

SOURCES = {
    'dust': ('Fallout4 - Textures1.ba2', 'textures/animobjects/pipboy/pipboyscreendust01_d.dds'),
    'scanlines': ('Fallout4 - Textures5.ba2', 'textures/effects/scanlines_d.dds'),
    'scan': ('Fallout4 - Textures5.ba2', 'textures/animobjects/pipboy/pipboyscan.dds'),
    'verticalScan': ('Fallout4 - Textures5.ba2', 'textures/animobjects/pipboy/pipboyvscan.dds'),
}


def texture_pixels(payload, width, height, pixel_format):
    # The actual Pip-Boy scan profiles are B8G8R8A8_UNORM, not BC textures.
    if pixel_format != 87:
        return decode_texture(payload, width, height, pixel_format)
    if not 1 <= width <= 8192 or not 1 <= height <= 8192 or width * height * 4 > 64 * 1024 * 1024:
        raise AssetError('Invalid effect texture dimensions')
    size = width * height * 4
    if len(payload) < size:
        raise AssetError('Truncated effect texture')
    pixels = bytearray(payload[:size])
    pixels[0::4], pixels[2::4] = payload[2:size:4], payload[0:size:4]
    return pixels


def prepare_effects(game_dir, data_dir):
    game_data, output = Path(game_dir) / 'Data', Path(data_dir) / 'assets/effects'
    fingerprint = {name: [p.stat().st_size, p.stat().st_mtime_ns]
                   for name, _ in SOURCES.values() if (p := game_data / name).is_file()}
    cache = output / 'manifest.json'
    try:
        result = json.loads(cache.read_text())
        if (result.get('schema') == 3 and result.get('sources') == fingerprint
                and all((Path(data_dir) / v['path']).is_file() for v in result['effects'].values())):
            return result
    except (OSError, ValueError, KeyError, TypeError):
        pass
    result = {'schema': 3, 'sources': fingerprint, 'effects': {}, 'warnings': []}
    for key, (name, member) in SOURCES.items():
        try:
            record, payload = Archive(game_data / name).read(member)
            pixels = texture_pixels(payload, record['width'], record['height'], record['format'])
            path = output / (key + '.png')
            png = png_bytes(pixels, record['width'], record['height'])
            atomic_write(path, png)
            result['effects'][key] = {'path': 'assets/effects/' + key + '.png',
                                      'width': record['width'], 'height': record['height']}
            if key in ('scan', 'verticalScan'):
                # WebKit's SVG feImage does not reliably load file: resources.
                # These tiny data URLs are generated from this installation,
                # never stored in source or shipped in a release package.
                result['effects'][key]['dataURI'] = 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')
        except (AssetError, OSError, KeyError, UnicodeError, struct.error, zlib.error) as exc:
            result['warnings'].append('Could not extract Pip-Boy ' + key + ': ' + str(exc))
    atomic_write(cache, json.dumps(result, indent=2).encode())
    return result
