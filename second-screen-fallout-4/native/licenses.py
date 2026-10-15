#!/usr/bin/env python3
"""Retain notices for the locked native-host dependencies in release packages."""
import json
from pathlib import Path
import shutil
import sys
metadata = json.loads(Path(sys.argv[1]).read_text())
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
items = []
for package in metadata['packages']:
    if package['source'] is None:
        continue
    name, version = package['name'], package['version']
    source = Path(package['manifest_path']).parent
    dest = out / f'{name}-{version}'
    notices = []
    for file in source.iterdir():
        if file.is_file() and file.name.upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'NOTICE')):
            dest.mkdir(exist_ok=True)
            shutil.copyfile(file, dest / (file.name + '.txt'))
            notices.append(file.name + '.txt')
    if package.get('license_file'):
        file = source / package['license_file']
        if file.is_file():
            dest.mkdir(exist_ok=True)
            shutil.copyfile(file, dest / 'declared-license.txt')
            notices.append('declared-license.txt')
    # Some published workspace crates omit their repository-root notices.
    # Keep copies from their exact .cargo_vcs_info.json revision in source.
    supplemental = Path(__file__).parent / 'upstream-licenses' / f'{name}-{version}'
    if supplemental.is_dir():
        dest.mkdir(exist_ok=True)
        for file in supplemental.iterdir():
            if file.is_file():
                shutil.copyfile(file, dest / file.name)
                if file.suffix == '.txt':
                    notices.append(file.name)
    items.append({'name': name, 'version': version, 'license': package.get('license'),
                  'repository': package.get('repository'), 'notices': notices,
                  'source': f'https://crates.io/api/v1/crates/{name}/{version}/download'})
(out / 'dependencies.json').write_text(json.dumps(items, indent=2) + '\n')
(out / 'README.md').write_text('''# Native Pip-Boy dependencies

The native host uses the exact dependency versions listed in dependencies.json.
Each entry links to the corresponding complete upstream source archive; the
native host uses those crates without modifying their source. Original license
and notice files are retained beside this index. This includes MPL-2.0 covered
resvg/usvg/svgtypes source, available through the listed source links.

Game assets are unrelated to these dependencies and are extracted only from
the player’s installed copy. No game artwork, font or shader binary is here.
''')
print(f'Retained notices for {len(items)} native dependencies')
