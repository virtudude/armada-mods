#!/usr/bin/env bash
# Draws a mod's view to a picture without the game or the device:
#   ./preview.sh <mod id> [state] [--game <folder>] [--data <folder>] [-o <file.png>]
# state is a file, or the name of one in the mod's states/ folder; without one the view
# gets no state, which is its waiting screen. --game is the game's install folder: the
# mod's hooks are run against it once and what they prepare is kept in cache/preview/.
# --data is a data folder already prepared, for instance one copied from a device.
# Needs firefox, which does not draw exactly as the device does: check there before release.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ $# -ge 1 ]] || { sed -n '2,8p' "$0" >&2; exit 1; }
MOD="${1%/}"; shift
state="" game="" data="" out=""
while (($#)); do
    case "$1" in
        --game) game="$(realpath "$2")"; shift 2 ;;
        --data) data="$(realpath "$2")"; shift 2 ;;
        -o) out="$2"; shift 2 ;;
        *) state="$1"; shift ;;
    esac
done
view="$ROOT/$MOD/view/index.html"
[[ -f "$view" ]] || { echo "preview: $MOD has no view/index.html" >&2; exit 1; }
[[ -z "$state" || -f "$state" ]] || state="$ROOT/$MOD/states/${state%.json}.json"
[[ -z "$state" || -f "$state" ]] || { echo "preview: no such state: $state" >&2; exit 1; }
name="$(basename "${state:-waiting}" .json)"
out="${out:-$ROOT/build/preview/$MOD-$name.png}"
work="$ROOT/cache/preview/$MOD"
mkdir -p "$work" "$ROOT/cache/preview/firefox" "$(dirname "$out")"

if [[ -z "$data" ]]; then
    data="$work/data"
    if [[ -n "$game" ]]; then
        mkdir -p "$data"
        # what a launch would run, and at once what its end would: a hook may change a setting of the game's
        for hook in before_launch after_exit; do
            [[ ! -x "$ROOT/$MOD/hooks/$hook" ]] ||
                (cd "$ROOT/$MOD" && ARMADA_MOD_PACKAGE_DIR="$ROOT/$MOD" ARMADA_MOD_DATA_DIR="$data" ARMADA_MOD_GAME_DIR="$game" "hooks/$hook")
        done
    fi
fi

# the page as the screen host would load it, with a stand-in for what the host gives it
python3 - "$view" "$work/page.html" "${state:-}" "$data" "$game" <<'PY'
import json, sys
view, page, state, data, game = sys.argv[1:]
host = {"data": f"file://{data}/", "game": f"file://{game}/" if game else "", "last": json.load(open(state)) if state else None}
stand_in = f"<script>window.armada = Object.assign({json.dumps(host)}, {{ send(o) {{ console.log(JSON.stringify(o)); }}, onState: null }});</script>"
open(page, "w").write(open(view).read().replace("<head>", "<head>" + stand_in, 1))
PY
# the second screen of the dual-screen devices so far
timeout 90 firefox --headless --no-remote --profile "$ROOT/cache/preview/firefox" --window-size=1240,1080 --screenshot "$out" "file://$work/page.html" >/dev/null 2>&1 ||
    { echo "preview: firefox did not produce a picture" >&2; exit 1; }
echo "$out"
