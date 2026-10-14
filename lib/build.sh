# Shared steps for the mods' build.sh scripts. Sourced by ../build.sh with
# ROOT (the repository), MOD (the mod id) and STAGE (the package being assembled) set.

DOTNET_IMAGE=mcr.microsoft.com/dotnet/sdk:8.0
BEPINEX_URL='https://builds.bepinex.dev/projects/bepinex_be/788/BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.788%2B5b766a3.zip'
BEPINEX_SHA256=f4cc496bd098a0df4164b81e3737297707f13a47c2478dba2f60eefab784817a

die() {
    echo "build: $MOD: $*" >&2
    exit 1
}

# fetch <url> <sha256> <name>: download once into cache/, verify, print the path
fetch() {
    local file="$ROOT/cache/$3"
    mkdir -p "$ROOT/cache"
    if [[ ! -f "$file" ]]; then
        curl -fsSL --retry 3 -A armada-mods -o "$file.tmp" "$1" || die "download failed: $1"
        mv "$file.tmp" "$file"
    fi
    echo "$2  $file" | sha256sum -c --quiet - >&2 || die "checksum mismatch: $file"
    echo "$file"
}

# unpacked <zip> <name>: unzip once into cache/<name>, print the path
unpacked() {
    local dir="$ROOT/cache/$2"
    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir.tmp"
        unzip -q -o "$1" -d "$dir.tmp"
        mv "$dir.tmp" "$dir"
    fi
    echo "$dir"
}

# The host's dotnet if there is one, otherwise the SDK container.
run_dotnet() {
    if command -v dotnet >/dev/null; then
        dotnet "$@"
    else
        local refs=()
        # refs/<mod> may be a link to a folder outside the repository
        [[ ! -d "$ROOT/refs/$MOD" ]] || refs=(-v "$(realpath "$ROOT/refs/$MOD"):$ROOT/refs/$MOD")
        mkdir -p "$ROOT/cache/nuget"
        podman run --rm -v "$ROOT:$ROOT" "${refs[@]}" -v "$ROOT/cache/nuget:/root/.nuget" \
            -w "$PWD" "$DOTNET_IMAGE" dotnet "$@"
    fi
}

# compile <project folder> <output folder> [msbuild properties...]
compile() {
    local src="$1" out="$2"
    shift 2
    rm -rf "$out"
    (cd "$src" && run_dotnet build -c Release -o "$out" -v q --nologo "$@" >"$ROOT/build/dotnet.log" 2>&1) ||
        { grep -E ' error ' "$ROOT/build/dotnet.log" | sort -u | head -20 >&2; die "compile failed: $src"; }
}

# Reference assemblies taken from the builder's own copy of the game (see refs.sh).
game_refs() {
    [[ -d "$ROOT/refs/$MOD" ]] || die "no game reference assemblies in refs/$MOD; run ./refs.sh $MOD <game folder>"
    echo "$ROOT/refs/$MOD"
}

bepinex() {
    unpacked "$(fetch "$BEPINEX_URL" "$BEPINEX_SHA256" bepinex6-il2cpp-be788.zip)" bepinex6-il2cpp-be788
}

screen_host() {
    install -D -m 0755 "$ROOT/screen-host/screen-host" "$STAGE/host/screen-host"
}

# The native helper a Unity mod's before_launch hook runs on the device. Built once per run of build.sh.
unity_tools() {
    local out="$ROOT/build/interopgen-linux-arm64"
    if [[ ! -x "$out/interopgen" ]]; then
        rm -rf "$out"
        (cd "$ROOT/lib/unity/interopgen" && run_dotnet publish -c Release -r linux-arm64 --self-contained true \
            -p:InvariantGlobalization=true -p:BepInEx="$(bepinex)" -o "$out" -v q --nologo >"$ROOT/build/dotnet.log" 2>&1) ||
            { grep -E ' error ' "$ROOT/build/dotnet.log" | sort -u | head -20 >&2; die "interopgen publish failed"; }
    fi
    mkdir -p "$STAGE/tools"
    cp -r "$out" "$STAGE/tools/interopgen"
    install -m 0644 "$ROOT/THIRD-PARTY.md" "$STAGE/THIRD-PARTY.md"
}

# unity_mono <game data folder name>: boot assembly into the game's Managed folder,
# the provider from src/ next to the game, and the helper the hook patches with.
unity_mono() {
    local refs out="$ROOT/build/out/$MOD"
    refs="$(game_refs)"
    compile "$ROOT/lib/unity/monoboot" "$out/boot" -p:Refs="$refs"
    compile "$ROOT/$MOD/src" "$out/provider" -p:Refs="$refs"
    install -D -m 0644 "$out/boot/ArmadaSecondScreenBoot.dll" "$STAGE/overlay/$1/Managed/ArmadaSecondScreenBoot.dll"
    mkdir -p "$STAGE/overlay/ArmadaSecondScreen"
    cp "$out"/provider/ArmadaSecondScreen*.dll "$STAGE/overlay/ArmadaSecondScreen/"
    unity_tools
}

# What a provider written in Python shares with the others, next to the provider.
provider_lib() {
    install -D -m 0644 "$ROOT/lib/provider.py" "$STAGE/host/armada_provider.py"
}
