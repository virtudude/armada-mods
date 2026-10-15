#!/usr/bin/env bash
# Collects the reference assemblies a Unity mod compiles against, from a copy of the game:
#   ./refs.sh <mod id> <game folder>
# They are the game's own code, so they stay in refs/ on the builder's machine and are
# never committed or packaged.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
source lib/build.sh
(($# == 2)) || { echo "usage: refs.sh <mod id> <game folder>" >&2; exit 1; }
MOD="${1%/}"
game="$(realpath "$2")"
[[ -f "$MOD/mod.json" ]] || die "no such mod"
if [[ "$MOD" == second-screen-stardew-valley ]]; then
    out="$ROOT/refs/$MOD"
    mkdir -p "$out"
    for assembly in 'Stardew Valley' StardewValley.GameData MonoGame.Framework xTile; do
        [[ -f "$game/$assembly.dll" ]] || die "missing $assembly.dll in $game"
        cp "$game/$assembly.dll" "$out/"
    done
    echo "refs: copied Stardew Valley reference assemblies"
    exit 0
fi
data="$(find "$game" -maxdepth 1 -type d -name '*_Data' | head -1)"
[[ -n "$data" ]] || die "$game has no *_Data folder; is it a Unity game?"
out="$ROOT/refs/$MOD"
mkdir -p "$ROOT/build" "$out"

if [[ -d "$data/Managed" ]]; then
    cp "$data"/Managed/*.dll "$out/"
    echo "refs: copied $(find "$out" -maxdepth 1 -name '*.dll' | wc -l) assemblies from $data/Managed"
    exit 0
fi

# IL2CPP: the game has no managed assemblies, so interop assemblies are generated from its binary.
metadata="$data/il2cpp_data/Metadata/global-metadata.dat"
[[ -f "$game/GameAssembly.dll" && -f "$metadata" ]] || die "neither Managed assemblies nor an IL2CPP binary found"
version="$(grep -aoE '[0-9]{4}\.[0-9]+\.[0-9]+[fp][0-9]+' "$data/globalgamemanagers" | head -1)"
short="${version%%[fp]*}"
case "$short" in
    2018.4.24) sum=a2d2c2fe8a15dc873407e11bcf69084564d4a96301c78450b2c46176e33195ee ;;
    *) sum="${UNITY_LIBS_SHA256:?no pinned checksum for the Unity $short libraries; set UNITY_LIBS_SHA256}" ;;
esac
libs="$(unpacked "$(fetch "https://unity.bepinex.dev/libraries/$short.zip" "$sum" "unity-libs-$short.zip")" "unity-libs-$short")"
tool="$ROOT/build/interopgen-host"
(cd lib/unity/interopgen && run_dotnet build -c Release -p:BepInEx="$(bepinex)" -o "$tool" -v q --nologo >"$ROOT/build/dotnet.log" 2>&1) ||
    die "interopgen build failed, see build/dotnet.log"
# the container sees the repository, so the game's two files are copied in for the run
work="$ROOT/build/refs-input/$MOD"
mkdir -p "$work"
cp "$game/GameAssembly.dll" "$metadata" "$work/"
(cd "$ROOT" && run_dotnet "$tool/interopgen.dll" "$work/GameAssembly.dll" "$work/global-metadata.dat" "$version" "$libs" "$out/interop")
rm -rf "$work"
echo "refs: generated $(find "$out/interop" -name '*.dll' | wc -l) interop assemblies for Unity $version"
