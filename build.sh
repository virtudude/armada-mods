#!/usr/bin/env bash
# Builds mod packages: ./build.sh [mod id ...]   (all mods when none is named)
# Output: dist/<id>-<version>.tar.gz
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
source lib/build.sh

mods=("$@")
if ((${#mods[@]} == 0)); then
    for manifest in */mod.json; do
        mods+=("${manifest%/mod.json}")
    done
fi

mkdir -p build dist
# shared build output is rebuilt once per run, so a package never carries a stale copy
rm -rf build/interopgen-linux-arm64
for MOD in "${mods[@]}"; do
    MOD="${MOD%/}"
    [[ -f "$MOD/mod.json" ]] || { echo "build: no such mod: $MOD" >&2; exit 1; }
    version="$(python3 -c 'import json, sys; m = json.load(open(sys.argv[1])); assert m["id"] == sys.argv[2], "id must match the folder name"; print(m["version"])' "$MOD/mod.json" "$MOD")"
    STAGE="$ROOT/build/stage/$MOD"
    rm -rf "$STAGE"
    mkdir -p "$STAGE"
    tar -C "$MOD" --exclude=./src --exclude=./build.sh --exclude=./states --exclude=./native/target -cf - . | tar -C "$STAGE" -xf -
    if [[ -f "$MOD/build.sh" ]]; then
        (source "$MOD/build.sh")
    fi
    python3 lib/check-manifest.py "$STAGE"
    archive="dist/$MOD-$version.tar.gz"
    tar -C build/stage --sort=name --owner=0 --group=0 --numeric-owner --mtime=@0 -cf - "$MOD" | gzip -n -9 >"$archive.tmp"
    mv "$archive.tmp" "$archive"
    echo "built $archive ($(du -h "$archive" | cut -f1))"
    # a published version is never replaced: releasing this needs a higher version first
    if git rev-parse -q --verify "refs/tags/$MOD/v$version" >/dev/null; then
        echo "build: warning: $MOD $version is already tagged; raise the version in mod.json before releasing" >&2
    fi
done
