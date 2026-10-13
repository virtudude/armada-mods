# Third-party software in mod packages

The source in this repository contains none of the following. Some built
packages include unmodified copies, downloaded at build time from the
projects' own releases and checked against a pinned checksum, or restored
as build dependencies. A package that includes any of them carries this
file.

## Unity mods (the `tools/interopgen` helper)

| Component | License | Source |
|---|---|---|
| .NET runtime | MIT | https://github.com/dotnet/runtime |
| BepInEx | LGPL-2.1 | https://github.com/BepInEx/BepInEx |
| Il2CppInterop | LGPL-3.0 | https://github.com/BepInEx/Il2CppInterop |
| HarmonyX | MIT | https://github.com/BepInEx/HarmonyX |
| Cpp2IL, LibCpp2IL, StableNameDotNet, WasmDisassembler | MIT | https://github.com/SamboyCoding/Cpp2IL |
| Disarm | MIT | https://github.com/SamboyCoding/Disarm |
| AsmResolver | MIT | https://github.com/Washi1337/AsmResolver |
| AssetRipper.Primitives, AssetRipper.CIL | MIT | https://github.com/AssetRipper |
| Capstone.NET | MIT | https://github.com/9ee1/Capstone.NET |
| Iced | MIT | https://github.com/icedland/iced |
| Mono.Cecil | MIT | https://github.com/jbevain/cecil |
| MonoMod | MIT | https://github.com/MonoMod/MonoMod |
| SemanticVersioning | MIT | https://github.com/adamreeve/semver.net |

## Stardew Valley

This package includes the Windows payload from the pinned
[SMAPI 4.5.2 release](https://github.com/Pathoschild/SMAPI/releases/tag/4.5.2).
SMAPI is LGPL-3.0; its source is available at that tag. The loader binaries
are unmodified; the package sets `FixHarmony` to `false` in its private
configuration. The payload also includes SMAPI's upstream dependencies
(Harmony, MonoMod, Mono.Cecil, Newtonsoft.Json, Markdig, Pintail, TMXTile,
VdfConverter and HTTP client libraries), under their respective licenses.
The SMAPI LGPL and accompanying GPL texts are in `licenses/`. Upstream SMAPI
also embeds its own application icon; that is part of the upstream payload.
The archive's `payload/Stardew Valley.exe` is an unmodified copy of
`StardewModdingAPI.exe`, renamed for Steam launching, not the game's executable.

Map layers, menu panels, font glyphs, item sprites, portraits and title scenery
are exported locally from the player's loaded game assets. Those exported game
assets are not included in this repository or the distributed archive. Game
reference assemblies stay in the ignored `refs/` directory, and extracted
development references must not be committed. The companion contains asset
names, crop coordinates, identifiers and compatibility logic informed by the
game's behavior; it does not bundle decompiled game source files.

Game binaries, generated game interop assemblies and extracted game art do not
ship in packages. Where needed, patched game files and extracted art are
produced on the player's device from their own copy of the game.
