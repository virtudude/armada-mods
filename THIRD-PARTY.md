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

Nothing derived from a game ships in a package. Patched game files,
generated assemblies and extracted art are produced on the player's device
from their own copy of the game.

## Fallout 4: Pip-Boy

The Fallout 4 package contains an original Python companion bridge and a native
Rust/Vulkan host. Its locked Rust dependency versions, upstream source archive
links and license notices are included in `licenses/`. The principal components
are wgpu (MIT/Apache-2.0), winit (Apache-2.0), resvg/usvg (MPL-2.0), fontdue
(MIT/Apache-2.0), image (MIT/Apache-2.0) and serde_json (MIT/Apache-2.0).

No Bethesda assets, Android app resources or game executable is distributed.
Runtime extraction reads maps, fonts, animation artwork and scan profiles from
the player's own installation into the mod data folder. The GPU shader is an
independent translation of the recovered rendering formula; no original game
shader bytecode is bundled. Protocol documentation references are in the mod's
README.

The companion patch distributes offsets, hashes and a generated jump; original
executable instruction excerpts are not embedded. Release staging uses named
source inputs and a final file allowlist, excluding runtime caches and game
overlays even when their content is stored as JSON. Only the built release
archive should be distributed, never a player's generated mod data directory.
