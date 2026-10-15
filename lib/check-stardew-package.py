#!/usr/bin/env python3
"""Reject files outside the companion and pinned SMAPI distribution."""
import io
import pathlib
import sys
import zipfile


def check(stage, upstream, source, compiled):
    expected = {}
    with zipfile.ZipFile(upstream) as installer:
        with zipfile.ZipFile(io.BytesIO(installer.read('SMAPI 4.5.2 installer/internal/windows/install.dat'))) as payload:
            for name in payload.namelist():
                if name.endswith('/') or name.startswith('Mods/'):
                    continue
                data = payload.read(name)
                if name == 'smapi-internal/config.json':
                    data = data.replace(b'"FixHarmony": true', b'"FixHarmony": false')
                expected['payload/' + name] = data
    expected['payload/Stardew Valley.exe'] = expected['payload/StardewModdingAPI.exe']
    companion = compiled.read_bytes()
    for private_path in (str(source.parent.resolve()), str(pathlib.Path.home())):
        if any(private_path.encode(encoding) in companion for encoding in ('utf-8', 'utf-16le')):
            raise ValueError('companion binary contains a local build path')
    expected['payload/Mods/ArmadaSecondScreen/ArmadaStardew.dll'] = companion
    expected['payload/Mods/ArmadaSecondScreen/manifest.json'] = (source / 'src/manifest.json').read_bytes()
    for name in ('mod.json', 'hooks/before_launch', 'view/index.html', 'view/app.js',
                 'view/style.css', 'licenses/SMAPI-LGPL-3.0.txt', 'licenses/GPL-3.0.txt'):
        expected[name] = (source / name).read_bytes()
    expected['THIRD-PARTY.md'] = (source.parent / 'THIRD-PARTY.md').read_bytes()
    expected['host/screen-host'] = (source.parent / 'screen-host/screen-host').read_bytes()
    actual = {}
    for path in stage.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'symlink in package: {path}')
        if path.is_file():
            actual[path.relative_to(stage).as_posix()] = path.read_bytes()
    if actual.keys() != expected.keys():
        raise ValueError(f'unexpected files: {sorted(actual.keys() - expected.keys())}; '
                         f'missing files: {sorted(expected.keys() - actual.keys())}')
    for name, data in expected.items():
        if actual[name] != data:
            raise ValueError(f'package file differs from its declared source: {name}')


if __name__ == '__main__':
    try:
        check(*(pathlib.Path(p) for p in sys.argv[1:]))
    except ValueError as error:
        sys.exit(f'Stardew package audit failed: {error}')
    print('Stardew package audit: only companion files and pinned SMAPI payload.')
