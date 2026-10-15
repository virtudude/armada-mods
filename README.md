# armada-mods

Game mods for [Armada](https://github.com/armada-os/armada): folders of files
that Armada applies to a Steam game at launch without changing its install.
The ones here put a companion view on the second screen of dual-screen
devices.

| Mod | Game | Second screen |
|---|---|---|
| `second-screen-hollow-knight` | Hollow Knight | The live map, charms (change them by touch at a bench) and inventory |
| `second-screen-balatro` | Balatro | The blinds ahead, jokers with their current values, remaining deck, hand levels |
| `second-screen-crosscode` | CrossCode | Status, element switching and consumables by touch, quests |
| `second-screen-duke-nukem-3d` | Duke Nukem 3D: 20th Anniversary World Tour | Health, armor and ammo moved off the game screen, weapons and inventory items by touch |
| `second-screen-marathon` | Classic Marathon | The suit display moved off the game screen: shield, oxygen, motion sensor, weapons by touch |
| `second-screen-stardew-valley` | Stardew Valley (Proton) | Map, touch backpack management, skills, friendships, animals, collections, bundles and quests, using the game's art |

A mod reaches into its game's code, so a game update can break it. A mod
that stops understanding its game is meant to let go of the second screen,
so that the game runs as usual.

[FORMAT.md](FORMAT.md) describes what a mod is and how to write one:
the folder layout, `mod.json`, hooks, the second-screen program, how
mod files reach the game, the ways to reach a game and what a mod owes
the player.

## Writing one

Start from `starter/my-mod`, the smallest working mod, and from the one of
the mods here that reaches its game the way the new mod will:

| Example | How it reaches the game |
|---|---|
| `second-screen-marathon` | The game's own plugin interface |
| `second-screen-balatro` | A Lua script added to the game's own |
| `second-screen-crosscode` | A JavaScript file the game is told to load |
| `second-screen-hollow-knight` | C# loaded into the game's engine, with a picture streamed from it |
| `second-screen-duke-nukem-3d` | The game's memory read from outside, keys pressed on a virtual keyboard |

The starter, from nothing to the device, for a game with Steam app id 1234:

    cp -r starter/my-mod second-screen-mygame

In `second-screen-mygame/mod.json` set `id` to `second-screen-mygame` and
`steam_appids` to `[1234]`; in `host/provider` set `APPID = 1234`. Then:

    ./preview.sh second-screen-mygame hello
    ./build.sh second-screen-mygame

The first draws the page with the state in `states/hello.json`. The second
makes `dist/second-screen-mygame-0.1.0.tar.gz`, with the screen host and
`lib/provider.py` added. Unpack it into `~/.local/share/armada-mods/mods/`
on a device with a second screen and start the game from Steam: the bottom
screen counts seconds, and its button counts taps. The `link.send` line in
`host/provider` is where a real mod sends what it read from its game, and
`~/.cache/armada-mods/1234/mods.log` on the device says what went wrong
when nothing shows.

## Layout

    <mod id>/            one folder per mod, named by its id
      mod.json           the manifest
      overlay/ hooks/ view/ ...   what ships as it is
      src/               source for compiled parts, not shipped
      states/            states for previewing the view, not shipped
      build.sh           how the rest of the package is produced, not shipped
    screen-host/         the second-screen program the mods here use
    lib/                 code and build steps shared by the mods
    starter/my-mod/      the smallest working mod, to copy
    build.sh             builds packages
    preview.sh           draws a mod's view without the game
    refs.sh              collects game reference assemblies for Unity mods
    FORMAT.md            the mod format, for writing a mod

## Installing a mod

In Armada Store, open Game Mods. The mods here are listed under Featured;
"Add local .tar.gz" installs any other package.

By hand: unpack a release archive into
`~/.local/share/armada-mods/mods/` on the device. It contains one folder
named by the mod id. Delete that folder, and
`~/.local/share/armada-mods/data/<mod id>/`, to remove it.

## Building

    ./build.sh                     every mod
    ./build.sh second-screen-balatro

Packages land in `dist/<id>-<version>.tar.gz`.

A package is the mod's folder without `src/`, `states/` and `build.sh`, plus whatever
its `build.sh` adds: the screen host, compiled code, and pinned third-party
software that is downloaded and checked against a checksum.
[THIRD-PARTY.md](THIRD-PARTY.md) lists what packages can contain.

Every build needs `bash`, `python3`, `curl` and `unzip`. Beyond that:

| Mod | Needs |
|---|---|
| Hollow Knight | `dotnet` 8 or `podman`, and the game's assemblies (below) |
| Balatro, CrossCode, Duke Nukem 3D, Marathon | Nothing more |
| Stardew Valley | `dotnet` 8 or `podman`, and reference assemblies from the Windows game |

A Unity mod compiles against the game's own assemblies. Those are not in
this repository. Collect them once from a copy of the game you own:

    ./refs.sh second-screen-hollow-knight "/path/to/Hollow Knight"

They go to `refs/<mod id>/`, which is ignored by git.

## Previewing a view

    ./preview.sh second-screen-duke-nukem-3d loadout --game "/path/to/Duke Nukem 3D"
    ./preview.sh second-screen-duke-nukem-3d

draws a mod's view to `build/preview/` without the game running, at the size
of the second screen. The first form runs the mod's hooks against the game's
install folder once, so the view has the game's art, and gives the view a
state from the mod's `states/` folder. Without a state the view shows its
waiting screen. `--data` takes a data folder copied from a device instead.

A file in `states/` is one state as the mod's provider sends it. Record them
from a real game where possible: with `~/.local/share/armada-mods/dev`
present, the screen host keeps every state it is sent in
`$XDG_RUNTIME_DIR/armada-second-screen-debug/states.jsonl`.

The picture comes from Firefox, which does not draw exactly as the device
does. It is for working on a layout; look at the device before a release.

## Releasing

Each mod is released on its own, under a tag named `<mod id>/v<version>`
with its one package attached. Armada Store does not look for releases: its
catalog names one build of each mod by URL, version and SHA-256, and installs
nothing else. A release reaches players when the catalog in Armada is
changed to name it.

- Raise `version` in the mod's `mod.json` for any change that should reach
  players, including a fix in `lib/` or `screen-host/` that the mod needs.
  Shared changes that do not matter to a mod wait for its next release.
- A published version is never replaced: the store refuses a package whose
  checksum is not the one in its catalog. A bad release is followed by a
  higher version.

      ./build.sh second-screen-balatro
      sha256sum dist/second-screen-balatro-0.1.1.tar.gz
      git tag second-screen-balatro/v0.1.1
      git push origin second-screen-balatro/v0.1.1
      gh release create second-screen-balatro/v0.1.1 --verify-tag \
          --title "second-screen-balatro 0.1.1" --notes "What changed" \
          dist/second-screen-balatro-0.1.1.tar.gz

Install and try the built package before tagging, and release that same
file: builds are not byte-for-byte repeatable, and its checksum is what
goes into the catalog.

## License

GPL-2.0-or-later, like Armada. See [LICENSE.md](LICENSE.md). Third-party
software in built packages keeps its own licenses.
