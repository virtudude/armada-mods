screen_host
smapi_zip="$(fetch 'https://github.com/Pathoschild/SMAPI/releases/download/4.5.2/SMAPI-4.5.2-installer.zip' dd01ddca7b566bfe0d3b3d2d03833496abc56c53da976241f2ab443f5484acc4 smapi-4.5.2.zip)"
smapi="$ROOT/build/smapi-4.5.2-windows"
python3 - "$smapi_zip" "$smapi" "$STAGE" <<'PY'
import io,pathlib,shutil,sys,zipfile
archive,out,stage=map(pathlib.Path,sys.argv[1:])
with zipfile.ZipFile(archive) as z:
    with zipfile.ZipFile(io.BytesIO(z.read('SMAPI 4.5.2 installer/internal/windows/install.dat'))) as payload:
        payload.extractall(out)
shutil.copytree(out,stage/'payload',ignore=shutil.ignore_patterns('Mods'),dirs_exist_ok=True)
shutil.copy2(stage/'payload/StardewModdingAPI.exe',stage/'payload/Stardew Valley.exe')
c=stage/'payload/smapi-internal/config.json'
c.write_text(c.read_text().replace('"FixHarmony": true','"FixHarmony": false'))
PY
compile "$ROOT/$MOD/src" "$ROOT/build/out/$MOD" -p:Refs="$(game_refs)" -p:Smapi="$smapi"
mkdir -p "$STAGE/payload/Mods/ArmadaSecondScreen"
cp "$ROOT/build/out/$MOD/ArmadaStardew.dll" "$STAGE/payload/Mods/ArmadaSecondScreen/"
cp "$ROOT/$MOD/src/manifest.json" "$STAGE/payload/Mods/ArmadaSecondScreen/"
cp "$ROOT/THIRD-PARTY.md" "$STAGE/"
python3 "$ROOT/lib/check-stardew-package.py" "$STAGE" "$smapi_zip" "$ROOT/$MOD" "$ROOT/build/out/$MOD/ArmadaStardew.dll"
