#!/usr/bin/env python3
"""Build-only release boundary: runtime game data is never a package input."""
import argparse
import json
from pathlib import Path
import shutil
import stat


SOURCE_FILES = frozenset({
    'mod.json',
    'hooks/before_launch', 'host/run',
    'bridge/main.py', 'bridge/protocol.py', 'bridge/actions.py', 'bridge/models.py',
    'tools/assets.py', 'tools/fonts.py', 'tools/effects.py', 'tools/companion.py',
    'tools/page_assets.py', 'tools/model_assets.py',
})


def regular(root, relative):
    path = root / relative
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError(f'Package input is a link: {path}')
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f'Package input is not a plain file: {path}')
    return path


def stage_sources(source, stage):
    source, stage = source.resolve(), stage.resolve()
    if source == stage or source.is_relative_to(stage) or stage.is_relative_to(source):
        raise ValueError('Release stage must be separate from source')
    # Validate every input before replacing the disposable build stage.
    inputs = [(name, regular(source, name)) for name in sorted(SOURCE_FILES)]
    inputs.append(('THIRD-PARTY.md', regular(source.parent, 'THIRD-PARTY.md')))
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for name, path in inputs:
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        target.chmod(path.stat().st_mode & 0o777)


def component(value):
    if not isinstance(value, str) or not value or value in ('.', '..') or '/' in value or '\\' in value:
        raise ValueError('Unsafe dependency notice path')
    return value


def check_package(source, stage):
    expected = set(SOURCE_FILES) | {
        'THIRD-PARTY.md', 'host/pipboy-host',
        'licenses/dependencies.json', 'licenses/README.md',
    }
    # Notices come from the freshly generated dependency index. Only exact
    # notice filenames and checked-in provenance records are accepted.
    dependencies = json.loads(regular(stage, 'licenses/dependencies.json').read_text())
    for dep in dependencies:
        folder = component(dep['name']) + '-' + component(dep['version'])
        for notice in dep['notices']:
            notice = component(notice)
            if not notice.endswith('.txt'):
                raise ValueError('Unexpected dependency notice format')
            expected.add(f'licenses/{folder}/{notice}')
        provenance = source / 'native/upstream-licenses' / folder / 'provenance.json'
        if provenance.is_file():
            relative = f'licenses/{folder}/provenance.json'
            expected.add(relative)
            if regular(stage, relative).read_bytes() != provenance.read_bytes():
                raise ValueError(f'Changed dependency provenance: {relative}')
    actual = set()
    for path in stage.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'Package contains a link: {path}')
        if path.is_dir():
            continue
        relative = path.relative_to(stage).as_posix()
        regular(stage, relative)
        actual.add(relative)
    if actual != expected:
        raise ValueError(f'Package file mismatch: unexpected={sorted(actual - expected)}, missing={sorted(expected - actual)}')
    for name in SOURCE_FILES:
        if regular(stage, name).read_bytes() != regular(source, name).read_bytes():
            raise ValueError(f'Packaged source differs: {name}')
    if (stage / 'THIRD-PARTY.md').read_bytes() != regular(source.parent, 'THIRD-PARTY.md').read_bytes():
        raise ValueError('Packaged third-party notice differs')
    with (stage / 'host/pipboy-host').open('rb') as host:
        header = host.read(20)
    if header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\xb7\x00':
        raise ValueError('Expected the built ARM64 Linux host')
    print(f'Checked {len(actual)} explicitly allowed release files; no runtime asset directory is packaged')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('stage', 'check'))
    parser.add_argument('source', type=Path)
    parser.add_argument('stage', type=Path)
    args = parser.parse_args()
    try:
        (stage_sources if args.action == 'stage' else check_package)(args.source, args.stage)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'Pip-Boy package rejected: {exc}\n')
