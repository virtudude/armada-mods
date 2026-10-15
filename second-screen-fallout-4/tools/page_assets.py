"""Extract DATA quest timelines from the user's installed Fallout 4 interface.

No ActionScript is executed and no Bethesda assets are distributed. RADIO's
waveform is procedural (RadioWave.as), so only its native placement is exported.
The caller deep-merges this function's additions into the main asset manifest.
"""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import zlib

from assets import (Archive, AssetError, Bits, Movie, atomic_write, inflate,
                    manifest_paths, shape_svg, swf_tags, union_bounds)

SCHEMA = 2
MAX_CLIPS = 256
MAX_FRAMES = 600
MAX_CLIP_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
QUEST_DIRS = ("components/quest vault boys/", "components/faction vault boys/")


def quest_key(path):
    """Same lookup normalization as companion Quests[].SWFFile, no filesystem use."""
    path = path.replace("\\", "/").lower()
    if path.startswith("interface/"):
        path = path[len("interface/"):]
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise AssetError("Invalid quest component path")
    if not path.startswith(QUEST_DIRS) or not path.endswith(".swf"):
        raise AssetError("Not a quest component")
    return path


def quest_duration(movie, ident=-1):
    """The native page watches the first child MovieClip's final frame.

    These movies wrap their actual animation in a one-frame root. Retain that
    root's matrix rather than exporting the child's shapes in the wrong space.
    """
    frames, _ = movie.timelines[ident]
    count = len(frames)
    if count == 1 and frames[0]:
        child = frames[0][0]["id"]
        if child in movie.timelines:
            count = len(movie.timelines[child][0])
    if not 1 <= count <= MAX_FRAMES:
        raise AssetError("Quest timeline exceeds frame budget")
    return count


def export_quest(movie, output, relative, ident=-1, budget=None):
    count = quest_duration(movie, ident)
    rendered, size = [], 0
    for frame in range(count):
        content, bounds = movie.render(ident, frame)
        size += len(content.encode())
        if size > MAX_CLIP_BYTES:
            raise AssetError("Quest timeline exceeds byte budget")
        rendered.append((content, bounds))
    bounds = union_bounds([b for _, b in rendered])
    if not bounds:
        raise AssetError("Empty quest timeline")
    xmin, xmax, ymin, ymax = bounds
    box = [xmin, ymin, xmax - xmin, ymax - ymin]
    unique, frames, blobs = {}, [], []
    for content, _ in rendered:
        if content not in unique:
            path = relative + "/%d.svg" % len(unique)
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%g %g %g %g">%s</svg>'
                   % (*box, content)).encode()
            unique[content] = "assets/" + path
            blobs.append((path, svg))
        frames.append(unique[content])
    byte_count = sum(len(blob) for _, blob in blobs)
    if budget is not None and byte_count > budget[0]:
        raise AssetError("Quest asset cache exceeds total byte budget")
    for path, blob in blobs:
        atomic_write(Path(output) / path, blob)
    if budget is not None:
        budget[0] -= byte_count
    return {"fps": movie.fps, "viewBox": box, "frames": frames,
            "playOnce": True}


def _named_placement(movie, name, ident=-1):
    return list(next(item["matrix"] for item in movie.timelines[ident][0][0]
                     if item.get("name") == name))


def radio_scale_shape(payload):
    """Convert the native ruler's round, scaling LINESTYLE2 to LINESTYLE1.

    This deliberately handles only this lossless subset of DefineShape4. New
    style arrays, fills and different stroke semantics are rejected explicitly.
    """
    reader = Bits(payload, 2)
    reader.rect()
    bounds_end = reader.position // 8
    reader.rect()
    if reader.bytes(1) != b"\x01" or reader.bytes(1) != b"\x00":
        raise AssetError("Unsupported radio ruler fills or stroke scaling")
    count = reader.bytes(1)[0]
    if count == 255:
        raise AssetError("Too many radio ruler styles")
    styles = bytearray(b"\0" + bytes([count]))
    for _ in range(count):
        width = reader.bytes(2)
        if reader.bytes(2) != b"\0\0":
            raise AssetError("Unsupported radio ruler stroke caps or joins")
        styles += width + reader.bytes(4)
    edges_start = reader.position // 8
    fill_bits, line_bits = reader.read(4), reader.read(4)
    while True:
        if reader.read(1):
            straight, size = reader.read(1), reader.read(4) + 2
            if not straight:
                reader.read(4 * size)
            elif reader.read(1):
                reader.read(2 * size)
            else:
                reader.read(1)
                reader.read(size)
        else:
            flags = reader.read(5)
            if not flags:
                break
            if flags & 16:
                raise AssetError("Radio ruler changes style arrays")
            if flags & 1:
                reader.read(reader.read(5) * 2)
            if flags & 2:
                reader.read(fill_bits)
            if flags & 4:
                reader.read(fill_bits)
            if flags & 8:
                reader.read(line_bits)
    return shape_svg(payload[:bounds_end] + styles + payload[edges_start:], 3)


def export_radio_scale(swf, movie, output, relative):
    length = struct.unpack_from("<I", swf, 4)[0]
    body = inflate(swf[8:], length - 8) if swf[:3] == b"CWS" else swf[8:]
    reader = Bits(body)
    reader.rect()
    reader.bytes(4)
    # The background ruler is the root's unnamed shape, not RadioWave_mc's
    # procedural Graphics content. Discover its ID from its placement.
    candidates = {p["id"] for p in movie.timelines[-1][0][0] if "name" not in p}
    for tag, payload in swf_tags(body[reader.position // 8:]):
        if tag != 83 or struct.unpack_from("<H", payload)[0] not in candidates:
            continue
        content, bounds = radio_scale_shape(payload)
        xmin, xmax, ymin, ymax = bounds
        box = [xmin, ymin, xmax - xmin, ymax - ymin]
        path = relative + "/radio-scale.svg"
        atomic_write(Path(output) / path,
                     ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%g %g %g %g">%s</svg>'
                      % (*box, content)).encode())
        return {"path": "assets/" + path, "viewBox": box}
    raise AssetError("No supported native radio ruler")


def _valid_cache(cache, sources, data):
    if cache.get("schema") != SCHEMA or cache.get("sources") != sources:
        return False
    additions = cache.get("additions")
    if not isinstance(additions, dict):
        return False
    base = (data / "assets/pages").resolve()
    for path in manifest_paths(additions):
        resolved = (data / path).resolve()
        if not resolved.is_relative_to(base) or not resolved.is_file():
            return False
    return True


def prepare_page_assets(game_dir, data_dir):
    """Return animations.quests, pages.radio and pageAssetWarnings additions.

    Quest keys match SWFFile after lowercasing and replacing backslashes with
    slashes (and removing an optional interface/). Bounds/matrices use twips;
    loaded quests use the page's native 0.7 scale. The default is already sized.
    The separate cache avoids changing assets.py's schema or existing manifest.
    """
    game_data, data = Path(game_dir) / "Data", Path(data_dir)
    output = data / "assets"
    paths = sorted(game_data.glob("* - Interface.ba2"))
    # Base archive first, DLC interface files can add/replace quest components.
    paths.sort(key=lambda p: (p.name.lower() != "fallout4 - interface.ba2", p.name.lower()))
    sources = {str(p.resolve()): [p.stat().st_size, p.stat().st_mtime_ns] for p in paths}
    cache_path = output / "pages-manifest.json"
    try:
        cache = json.loads(cache_path.read_text())
        if _valid_cache(cache, sources, data):
            return cache["additions"]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    generation = hashlib.sha256(json.dumps([SCHEMA, sources], sort_keys=True).encode()).hexdigest()[:20]
    relative = "pages/" + generation
    quests = {"byPath": {}, "scale": 0.7}
    additions = {"animations": {"quests": quests}, "pages": {}, "pageAssetWarnings": []}
    warnings = additions["pageAssetWarnings"]
    archives, members = [], {}
    for path in paths:
        try:
            archive = Archive(path)
            archives.append(archive)
            for name in archive.entries:
                try:
                    key = quest_key(name)
                except AssetError:
                    continue
                members[key] = (archive, name)
        except (OSError, ValueError, struct.error) as exc:
            warnings.append("Could not read %s: %s" % (path.name, exc))
    if len(members) > MAX_CLIPS:
        warnings.append("Quest component count exceeds cache limit; remaining components omitted")
    budget = [MAX_TOTAL_BYTES]
    for key in sorted(members)[:MAX_CLIPS]:
        archive, name = members[key]
        try:
            movie = Movie(archive.read(name)[1])
            clip = hashlib.sha256(key.encode()).hexdigest()[:20]
            quests["byPath"][key] = export_quest(movie, output, relative + "/quests/" + clip, budget=budget)
        except (OSError, ValueError, KeyError, IndexError, struct.error, zlib.error) as exc:
            warnings.append("Could not extract quest %s: %s" % (key, exc))
    # These page roots are in the base interface; the reverse traversal follows
    # the same replacement order used for quest members above.
    for member, page in (("interface/pipboy_datapage.swf", "data"), ("interface/pipboy_radiopage.swf", "radio")):
        try:
            archive = next(a for a in reversed(archives) if member in a.entries)
            swf = archive.read(member)[1]
            movie = Movie(swf)
            if page == "data":
                quests["default"] = export_quest(movie, output, relative + "/quest-default", movie.names["Quest_DefaultBoy"], budget)
                quests["holderMatrix"] = _named_placement(movie, "VaultBoyHolder_mc", movie.names["QuestsTab"])
            else:
                additions["pages"]["radio"] = {
                    "waveMatrix": _named_placement(movie, "RadioWave_mc"),
                    "deadWaveMatrix": _named_placement(movie, "DeadWave_mc"),
                    "scale": export_radio_scale(swf, movie, output, relative),
                }
        except (OSError, ValueError, KeyError, IndexError, StopIteration, struct.error, zlib.error) as exc:
            warnings.append("Could not extract %s page metadata: %s" % (page, exc))
    atomic_write(cache_path, json.dumps({"schema": SCHEMA, "sources": sources, "additions": additions}, indent=2).encode())
    # Only generations owned by this extractor are eligible for reclamation.
    for stale in (output / "pages").glob("*"):
        if stale.name != generation and len(stale.name) == 20 and all(c in "0123456789abcdef" for c in stale.name) and stale.is_dir() and not stale.is_symlink():
            shutil.rmtree(stale)
    return additions
