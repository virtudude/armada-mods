#!/usr/bin/env python3
"""Convert the user's Fallout 4 assets to browser formats using only Python.

No Bethesda assets belong in the package. This reads the installed BA2 archives
at launch and writes derived images only to the mod's persistent data directory.
BA2 layout: https://github.com/stephen-bunn/bethesda-structs
SWF layout: Adobe SWF File Format Specification, version 19.
"""

import argparse
import binascii
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import zlib


SCHEMA = 5
MAX_PAYLOAD = 64 * 1024 * 1024
MAPS = {
    "commonwealth": ("Fallout4 - Textures6.ba2", "textures/interface/pip-boy/worldmap_d.dds", "worldmap.png"),
    "farHarbor": ("DLCCoast - Textures.ba2", "textures/dlc03/interface/map/mapfarharbor.dds", "far-harbor.png"),
    "nukaWorld": ("DLCNukaWorld - Textures.ba2", "textures/dlc04/interface/map/nukaworldmap.dds", "nuka-world.png"),
}


class AssetError(ValueError):
    """Unsupported or invalid archive data."""


def exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise AssetError("Truncated asset")
    return data


def inflate(data, expected):
    if expected > MAX_PAYLOAD:
        raise AssetError("Asset is too large")
    decoder = zlib.decompressobj()
    result = decoder.decompress(data, expected + 1)
    if len(result) != expected or not decoder.eof or decoder.unused_data:
        raise AssetError("Invalid compressed asset size")
    return result


class Archive:
    """Bounded, seek-based reader for Fallout 4 GNRL and DX10 BA2 archives."""

    def __init__(self, path):
        self.path = Path(path)
        self.entries = {}
        with self.path.open("rb") as stream:
            magic, version, kind, count, names_offset = struct.unpack("<4sI4sIQ", exact(stream, 24))
            if magic != b"BTDX" or version not in (1, 7, 8) or kind not in (b"GNRL", b"DX10"):
                raise AssetError("Unsupported Fallout 4 BA2 header")
            self.kind = kind
            self.size = self.path.stat().st_size
            if count > 1000000 or names_offset > self.size:
                raise AssetError("Invalid BA2 index")
            records = []
            for _ in range(count):
                if kind == b"GNRL":
                    record = struct.unpack("<I4sIIQIII", exact(stream, 36))
                    records.append({"chunks": [(record[4], record[5], record[6], 0, 0)]})
                else:
                    record = struct.unpack("<I4sIBBHHHBBH", exact(stream, 24))
                    if record[5] != 24 or not 1 <= record[4] <= 32:
                        raise AssetError("Invalid texture chunk table")
                    chunks = [struct.unpack("<QIIHHI", exact(stream, 24))[:5] for _ in range(record[4])]
                    records.append({"height": record[6], "width": record[7], "format": record[9], "chunks": chunks})
            if stream.tell() > names_offset:
                raise AssetError("Overlapping BA2 tables")
            stream.seek(names_offset)
            for record in records:
                size = struct.unpack("<H", exact(stream, 2))[0]
                name = exact(stream, size).decode("utf-8").replace("\\", "/").lower()
                self.entries[name] = record

    def read(self, name):
        record = self.entries[name.replace("\\", "/").lower()]
        # For textures we need only the highest-resolution mip, not the full DDS.
        chunks = record["chunks"] if self.kind == b"GNRL" else [c for c in record["chunks"] if c[3] == 0]
        if len(chunks) != 1:
            raise AssetError("Missing or ambiguous base texture mip")
        offset, packed, unpacked, _, _ = chunks[0]
        length = packed or unpacked
        if length > MAX_PAYLOAD or unpacked > MAX_PAYLOAD or offset + length > self.size:
            raise AssetError("Invalid BA2 payload range")
        with self.path.open("rb") as stream:
            stream.seek(offset)
            data = exact(stream, length)
        return record, inflate(data, unpacked) if packed else data


def _rgb565(value):
    r, g, b = value >> 11, value >> 5 & 63, value & 31
    return (r * 255 // 31, g * 255 // 63, b * 255 // 31)


def decode_texture(data, width, height, pixel_format):
    """Decode BC1/BC3 (DXGI 71/72/77/78) into RGBA, clipping edge blocks."""
    if pixel_format not in (71, 72, 77, 78):
        raise AssetError("Unsupported map texture format: %s" % pixel_format)
    if not 1 <= width <= 8192 or not 1 <= height <= 8192 or width * height * 4 > MAX_PAYLOAD:
        raise AssetError("Invalid texture dimensions")
    bc3 = pixel_format in (77, 78)
    block_size = 16 if bc3 else 8
    expected = ((width + 3) // 4) * ((height + 3) // 4) * block_size
    if len(data) < expected:
        raise AssetError("Truncated texture blocks")
    result = bytearray(width * height * 4)
    offset = 0
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            alpha_values = [255] * 8
            alpha_bits = 0
            if bc3:
                a, b = data[offset:offset + 2]
                alpha_values = [a, b]
                if a > b:
                    alpha_values += [((7 - i) * a + i * b) // 7 for i in range(1, 7)]
                else:
                    alpha_values += [((5 - i) * a + i * b) // 5 for i in range(1, 5)] + [0, 255]
                alpha_bits = int.from_bytes(data[offset + 2:offset + 8], "little")
                offset += 8
            c0, c1, indices = struct.unpack_from("<HHI", data, offset)
            offset += 8
            a, b = _rgb565(c0), _rgb565(c1)
            colors = [a + (255,), b + (255,)]
            if c0 > c1 or bc3:
                colors += [tuple((2 * x + y) // 3 for x, y in zip(a, b)) + (255,),
                           tuple((x + 2 * y) // 3 for x, y in zip(a, b)) + (255,)]
            else:
                colors += [tuple((x + y) // 2 for x, y in zip(a, b)) + (255,), (0, 0, 0, 0)]
            for i in range(16):
                x, y = bx + i % 4, by + i // 4
                color = colors[(indices >> (2 * i)) & 3]
                if bc3:
                    color = color[:3] + (alpha_values[(alpha_bits >> (3 * i)) & 7],)
                if x < width and y < height:
                    dest = (y * width + x) * 4
                    result[dest:dest + 4] = bytes(color)
    return result


def png_bytes(rgba, width, height):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xffffffff)
    rows = b"".join(b"\0" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".asset-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Bits:
    def __init__(self, data, position=0):
        self.data = data
        self.position = position * 8

    def read(self, count, signed=False):
        result = 0
        for _ in range(count):
            if self.position >= len(self.data) * 8:
                raise AssetError("Truncated SWF bit field")
            result = result * 2 + ((self.data[self.position // 8] >> (7 - self.position % 8)) & 1)
            self.position += 1
        if signed and count and result & (1 << (count - 1)):
            result -= 1 << count
        return result

    def align(self):
        self.position = (self.position + 7) // 8 * 8

    def bytes(self, count):
        self.align()
        start = self.position // 8
        self.position += count * 8
        value = self.data[start:start + count]
        if len(value) != count:
            raise AssetError("Truncated SWF bytes")
        return value

    def rect(self):
        count = self.read(5)
        values = tuple(self.read(count, True) for _ in range(4))
        self.align()
        return values

    def matrix(self):
        a = d = 1
        b = c = 0
        if self.read(1):
            count = self.read(5)
            a, d = (self.read(count, True) / 65536 for _ in range(2))
        if self.read(1):
            count = self.read(5)
            b, c = (self.read(count, True) / 65536 for _ in range(2))
        count = self.read(5)
        x, y = (self.read(count, True) for _ in range(2))
        self.align()
        return a, b, c, d, x, y


def swf_tags(data):
    position = 0
    while position < len(data):
        if position + 2 > len(data):
            raise AssetError("Truncated SWF tag")
        header = struct.unpack_from("<H", data, position)[0]
        position += 2
        size = header & 63
        if size == 63:
            if position + 4 > len(data):
                raise AssetError("Truncated SWF tag length")
            size = struct.unpack_from("<I", data, position)[0]
            position += 4
        if position + size > len(data):
            raise AssetError("Truncated SWF tag body")
        yield header >> 6, data[position:position + size]
        position += size
        if header >> 6 == 0:
            break


def shape_svg(data, version):
    """Convert solid vector DefineShape records, preserving both fill sides."""
    bits = Bits(data, 2)
    bounds = bits.rect()
    fills, lines = [None], [None]

    def styles():
        fill_offset, line_offset = len(fills) - 1, len(lines) - 1
        count = bits.bytes(1)[0]
        if count == 255 and version > 1:
            count = struct.unpack("<H", bits.bytes(2))[0]
        for _ in range(count):
            if bits.bytes(1) != b"\0":
                raise AssetError("Component contains a non-solid fill")
            color = bits.bytes(4 if version == 3 else 3)
            fills.append("#" + color.hex())
        count = bits.bytes(1)[0]
        if count == 255 and version > 1:
            count = struct.unpack("<H", bits.bytes(2))[0]
        for _ in range(count):
            width = struct.unpack("<H", bits.bytes(2))[0]
            color = bits.bytes(4 if version == 3 else 3)
            lines.append((width, "#" + color.hex()))
        return fill_offset, line_offset

    fill_offset, line_offset = styles()
    fill_bits, line_bits = bits.read(4), bits.read(4)
    fill0 = fill1 = line = 0
    point = (0, 0)
    edges, strokes = {}, {}
    while True:
        if not bits.read(1):
            flags = bits.read(5)
            if not flags:
                break
            if flags & 1:
                count = bits.read(5)
                point = (bits.read(count, True), bits.read(count, True))
            if flags & 2:
                fill0 = bits.read(fill_bits)
                fill0 = fill0 + fill_offset if fill0 else 0
            if flags & 4:
                fill1 = bits.read(fill_bits)
                fill1 = fill1 + fill_offset if fill1 else 0
            if flags & 8:
                line = bits.read(line_bits)
                line = line + line_offset if line else 0
            if flags & 16:
                bits.align()
                fill_offset, line_offset = styles()
                fill_bits, line_bits = bits.read(4), bits.read(4)
            continue
        straight = bits.read(1)
        count = bits.read(4) + 2
        start = point
        control = None
        if straight:
            if bits.read(1):
                dx, dy = bits.read(count, True), bits.read(count, True)
            elif bits.read(1):
                dx, dy = 0, bits.read(count, True)
            else:
                dx, dy = bits.read(count, True), 0
            point = (start[0] + dx, start[1] + dy)
        else:
            control = (start[0] + bits.read(count, True), start[1] + bits.read(count, True))
            point = (control[0] + bits.read(count, True), control[1] + bits.read(count, True))
        if fill0:
            edges.setdefault(fill0, []).append((start, control, point))
        if fill1:
            edges.setdefault(fill1, []).append((point, control, start))
        if line:
            strokes.setdefault(line, []).append((start, control, point))
    paths = []
    for is_stroke, style, segments in [(False, s, e) for s, e in edges.items()] + [(True, s, e) for s, e in strokes.items()]:
        if style >= len(lines if is_stroke else fills):
            raise AssetError("Invalid marker fill index")
        # SWF edges are stored in drawing order, possibly interleaving contours.
        # SVG needs contiguous contours so a hole retains its proper winding.
        remaining = {}
        for edge in segments:
            remaining.setdefault(edge[0], []).append(edge)
        commands = []
        while remaining:
            start = next(iter(remaining))
            point = start
            commands.append("M%s %s" % start)
            while point in remaining:
                edge = remaining[point].pop()
                if not remaining[point]:
                    del remaining[point]
                _, control, point = edge
                if control is None:
                    commands.append("L%s %s" % point)
                else:
                    commands.append("Q%s %s %s %s" % (*control, *point))
                if point == start:
                    commands.append("Z")
                    break
        paint = ('fill="none" stroke="%s" stroke-width="%s" stroke-linecap="round" stroke-linejoin="round"'
                 % (lines[style][1], lines[style][0])) if is_stroke else 'fill="%s"' % fills[style]
        paths.append('<path %s d="%s"/>' % (paint, " ".join(commands)))
    return "".join(paths), bounds


def extract_markers(data, include_root=False, components=None):
    """Export named map markers (or a component's root); no ActionScript runs.

    The first frame is the game's Discovered frame. Unsupported drawing types
    are skipped individually rather than manufacturing replacement game art.
    """
    if len(data) < 9 or data[:3] not in (b"CWS", b"FWS"):
        raise AssetError("Unsupported marker SWF")
    length = struct.unpack_from("<I", data, 4)[0]
    if not 8 <= length <= MAX_PAYLOAD:
        raise AssetError("Invalid SWF length")
    body = inflate(data[8:], length - 8) if data[:3] == b"CWS" else data[8:]
    if len(body) != length - 8:
        raise AssetError("Invalid SWF length")
    header = Bits(body)
    header.rect()
    header.bytes(4)
    shapes, sprites, names = {}, {}, {}
    root_placements = []
    first_frame = True
    for tag, payload in swf_tags(body[header.position // 8:]):
        if tag in (2, 22, 32):
            ident = struct.unpack_from("<H", payload)[0]
            try:
                shapes[ident] = shape_svg(payload, {2: 1, 22: 2, 32: 3}[tag])
            except AssetError:
                continue
        elif tag == 39:
            ident = struct.unpack_from("<H", payload)[0]
            placements = []
            for child_tag, child in swf_tags(payload[4:]):
                if child_tag == 1:
                    break
                if child_tag == 26 and len(child) >= 5:
                    flags = child[0]
                    if flags & 2:
                        character = struct.unpack_from("<H", child, 3)[0]
                        matrix = Bits(child, 5).matrix() if flags & 4 else (1, 0, 0, 1, 0, 0)
                        placements.append((character, matrix))
            sprites[ident] = placements
        elif tag in (56, 76):
            position = 2
            count = struct.unpack_from("<H", payload)[0]
            for _ in range(count):
                ident = struct.unpack_from("<H", payload, position)[0]
                position += 2
                end = payload.index(0, position)
                name = payload[position:end].decode("utf-8")
                position = end + 1
                if re.fullmatch(r"[A-Za-z0-9_]+Marker", name):
                    names[name] = ident
        elif tag == 1:
            first_frame = False
        elif tag == 26 and first_frame and len(payload) >= 5:
            flags = payload[0]
            if flags & 2:
                character = struct.unpack_from("<H", payload, 3)[0]
                reader = Bits(payload, 5)
                matrix = reader.matrix() if flags & 4 else (1, 0, 0, 1, 0, 0)
                # Condition_Body deliberately contains an empty Head_mc sprite;
                # the game loads Condition_Head into this named slot at runtime.
                if components and flags & 32 and not flags & 8:
                    name = payload[reader.position // 8:].split(b"\0", 1)[0].decode("utf-8")
                    if name in components:
                        svg = components[name].decode("utf-8")
                        match = re.search(r'viewBox="([^"]+)"', svg)
                        if not match:
                            raise AssetError("Missing component SVG bounds")
                        x, y, w, h = map(float, match.group(1).split())
                        content = svg.split(">", 1)[1].rsplit("</svg>", 1)[0]
                        shapes[character] = content, (x, x + w, y, y + h)
                root_placements.append((character, matrix))
    if include_root:
        sprites[-1] = root_placements
        names["root"] = -1

    def render(ident, stack=()):
        if ident in stack or len(stack) > 16:
            raise AssetError("Recursive marker sprite")
        if ident in shapes:
            return shapes[ident]
        if ident not in sprites or not sprites[ident]:
            raise AssetError("Unsupported marker sprite")
        parts, points = [], []
        for child, matrix in sprites[ident]:
            content, (xmin, xmax, ymin, ymax) = render(child, stack + (ident,))
            a, b, c, d, tx, ty = matrix
            points += [(a * x + c * y + tx, b * x + d * y + ty)
                       for x in (xmin, xmax) for y in (ymin, ymax)]
            parts.append('<g transform="matrix(%s)">%s</g>' % (" ".join(str(v) for v in matrix), content))
        return "".join(parts), (min(p[0] for p in points), max(p[0] for p in points),
                                min(p[1] for p in points), max(p[1] for p in points))

    result = {}
    for name, ident in names.items():
        try:
            content, (xmin, xmax, ymin, ymax) = render(ident)
            if xmax > xmin and ymax > ymin:
                result[name] = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%g %g %g %g">%s</svg>'
                                % (xmin, ymin, xmax - xmin, ymax - ymin, content)).encode()
        except AssetError:
            continue
    return result


def union_bounds(bounds):
    values = [b for b in bounds if b]
    if not values:
        return None
    return (min(b[0] for b in values), max(b[1] for b in values),
            min(b[2] for b in values), max(b[3] for b in values))


def transform_bounds(bounds, matrix):
    a, b, c, d, tx, ty = matrix
    points = [(a * x + c * y + tx, b * x + d * y + ty)
              for x in bounds[:2] for y in bounds[2:]]
    return (min(p[0] for p in points), max(p[0] for p in points),
            min(p[1] for p in points), max(p[1] for p in points))


class Movie:
    """Read-only vector timeline renderer for the game's condition components.

    Evaluates SWF display-list operations, not executable ActionScript. Position
    updates preserve the previous character, and RemoveObject2 clears its depth.
    Imported assets, filters, masks and non-solid shapes remain unsupported.
    """
    def __init__(self, data):
        if len(data) < 9 or data[:3] not in (b"CWS", b"FWS"):
            raise AssetError("Unsupported component SWF")
        length = struct.unpack_from("<I", data, 4)[0]
        if not 8 <= length <= MAX_PAYLOAD:
            raise AssetError("Invalid component SWF length")
        body = inflate(data[8:], length - 8) if data[:3] == b"CWS" else data[8:]
        if len(body) != length - 8:
            raise AssetError("Invalid component SWF length")
        reader = Bits(body)
        self.stage = reader.rect()
        rate, count = struct.unpack("<HH", reader.bytes(4))
        self.fps = rate / 256
        self.shapes, self.timelines, self.names = {}, {}, {}
        tags = list(swf_tags(body[reader.position // 8:]))
        for tag, payload in tags:
            if tag in (2, 22, 32):
                ident = struct.unpack_from("<H", payload)[0]
                try:
                    self.shapes[ident] = shape_svg(payload, {2: 1, 22: 2, 32: 3}[tag])
                except AssetError:
                    continue
            elif tag == 39:
                ident = struct.unpack_from("<H", payload)[0]
                try:
                    self.timelines[ident] = self.timeline(list(swf_tags(payload[4:])))
                except AssetError:
                    continue
            elif tag in (56, 76):
                position = 2
                for _ in range(struct.unpack_from("<H", payload)[0]):
                    ident = struct.unpack_from("<H", payload, position)[0]
                    end = payload.index(0, position + 2)
                    self.names[payload[position + 2:end].decode()] = ident
                    position = end + 1
        try:
            self.timelines[-1] = self.timeline(tags)
        except AssetError:
            self.timelines[-1] = ([[]], {})

    @staticmethod
    def timeline(tags):
        frames, display, labels = [], {}, {}
        for tag, payload in tags:
            if tag == 43:
                labels[payload.split(b"\0", 1)[0].decode()] = len(frames)
            elif tag == 28:
                display.pop(struct.unpack_from("<H", payload)[0], None)
            elif tag in (26, 70):
                flags = payload[0]
                extra = payload[1] if tag == 70 else 0
                offset = 2 if tag == 70 else 1
                depth = struct.unpack_from("<H", payload, offset)[0]
                reader = Bits(payload, offset + 2)
                if extra & 8 or extra & 16 and flags & 2:
                    raise AssetError("Unsupported class-based placement")
                item = dict(display.get(depth, {"matrix": (1, 0, 0, 1, 0, 0), "born": len(frames)}))
                if flags & 2:
                    item["id"] = struct.unpack("<H", reader.bytes(2))[0]
                    item["born"] = len(frames)
                if flags & 4:
                    item["matrix"] = reader.matrix()
                if flags & 8:
                    has_add, has_mult, size = reader.read(1), reader.read(1), reader.read(4)
                    if has_mult:
                        reader.read(size * 4)
                    if has_add:
                        reader.read(size * 4)
                    reader.align()
                if flags & 16:
                    reader.bytes(2)
                if flags & 32:
                    item["name"] = payload[reader.position // 8:].split(b"\0", 1)[0].decode()
                if flags & 64 or extra & 1:
                    raise AssetError("Unsupported clipped or filtered placement")
                if "id" in item:
                    display[depth] = item
            elif tag == 1:
                frames.append([dict(display[d]) for d in sorted(display)])
                if len(frames) > 2000:
                    raise AssetError("Component timeline is too long")
        return frames or [[]], labels

    def render(self, ident=-1, frame=0, stack=()):
        if ident in stack or len(stack) > 16:
            raise AssetError("Recursive component sprite")
        if ident in self.shapes:
            content, bounds = self.shapes[ident]
            return content, bounds
        if ident not in self.timelines:
            raise AssetError("Unsupported component character %s" % ident)
        frames, _ = self.timelines[ident]
        parts, bounds = [], []
        for item in frames[frame % len(frames)]:
            content, child_bounds = self.render(item["id"], frame - item["born"], stack + (ident,))
            if child_bounds:
                bounds.append(transform_bounds(child_bounds, item["matrix"]))
                parts.append('<g transform="matrix(%s)">%s</g>' %
                             (" ".join(str(v) for v in item["matrix"]), content))
        return "".join(parts), union_bounds(bounds)

    def export(self, output, relative, ident=-1, head_bounds=None):
        frames, labels = self.timelines[ident]
        rendered = [self.render(ident, i) for i in range(len(frames))]
        slots = [next((p["matrix"] for p in frame if p.get("name") == "Head_mc"), None) for frame in frames]
        bounds = union_bounds([b for _, b in rendered] +
                              [transform_bounds(head_bounds, slot) for slot in slots if slot and head_bounds])
        if not bounds:
            raise AssetError("Empty component")
        xmin, xmax, ymin, ymax = bounds
        box = [xmin, ymin, xmax - xmin, ymax - ymin]
        unique, paths = {}, []
        for content, _ in rendered:
            if content not in unique:
                path = relative + "/%d.svg" % len(unique)
                svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="%g %g %g %g">%s</svg>' % (*box, content)
                atomic_write(Path(output) / path, svg.encode())
                unique[content] = "assets/" + path
            paths.append(unique[content])
        result = {"fps": self.fps, "viewBox": box, "frames": paths}
        if labels:
            result["labels"] = labels
        if any(slots):
            result["headTransforms"] = slots
        return result


def manifest_paths(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from manifest_paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from manifest_paths(child)
    elif isinstance(value, str) and value.startswith("assets/"):
        yield value


def prepare_assets(game_dir, data_dir):
    """Return a manifest; all paths are relative to data_dir for armada.data()."""
    game_data = Path(game_dir) / "Data"
    output = Path(data_dir) / "assets"
    source_paths = [game_data / value[0] for value in MAPS.values()]
    source_paths.append(game_data / "Fallout4 - Interface.ba2")
    sources = {str(path.resolve()): [path.stat().st_size, path.stat().st_mtime_ns]
               for path in source_paths if path.is_file()}
    manifest_path = output / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
        if not isinstance(manifest, dict):
            raise ValueError("Invalid asset cache manifest")
        paths = list(manifest_paths(manifest))
        if manifest.get("schema") == SCHEMA and manifest.get("sources") == sources and paths and all((Path(data_dir) / p).is_file() for p in paths):
            return manifest
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    manifest = {"schema": SCHEMA, "sources": sources, "maps": {}, "markers": {}, "icons": {"special": {}, "status": {}},
                "animations": {"special": {}, "status": {"bodies": {}}}, "warnings": []}
    for key, (archive_name, member, filename) in MAPS.items():
        source = game_data / archive_name
        if not source.is_file():
            if key == "commonwealth":
                manifest["warnings"].append("Commonwealth map archive is missing")
            continue
        try:
            record, data = Archive(source).read(member)
            pixels = decode_texture(data, record["width"], record["height"], record["format"])
            atomic_write(output / filename, png_bytes(pixels, record["width"], record["height"]))
            manifest["maps"][key] = {"path": "assets/" + filename, "width": record["width"], "height": record["height"]}
        except (AssetError, OSError, KeyError, UnicodeError, struct.error, zlib.error) as exc:
            manifest["warnings"].append("Could not extract %s map: %s" % (key, exc))
    try:
        archive = Archive(game_data / "Fallout4 - Interface.ba2")
        _, data = archive.read("interface/pipboy_mappage.swf")
        markers = extract_markers(data)
        for name, svg in markers.items():
            path = "markers/" + name + ".svg"
            atomic_write(output / path, svg)
            manifest["markers"][name] = "assets/" + path
        if not markers:
            manifest["warnings"].append("No supported map markers found in the game interface")
        try:
            _, data = archive.read("interface/components/vaultboys/perks/perkclip_default.swf")
            manifest["animations"]["waiting"] = Movie(data).export(output, "animations/waiting")
        except (ValueError, IndexError, KeyError, struct.error, zlib.error) as exc:
            manifest["warnings"].append("Could not extract waiting Vault Boy: %s" % exc)
        for name in ("strength", "perception", "endurance", "charisma", "intelligence", "agility", "luck"):
            try:
                _, data = archive.read("interface/components/vaultboys/special/" + name + ".swf")
                svg = extract_markers(data, include_root=True).get("root")
                if svg:
                    path = "special/" + name + ".svg"
                    atomic_write(output / path, svg)
                    manifest["icons"]["special"][name] = "assets/" + path
                manifest["animations"]["special"][name] = Movie(data).export(output, "animations/special/" + name)
            except (ValueError, IndexError, KeyError, struct.error, zlib.error):
                continue
        try:
            _, data = archive.read("interface/components/conditionclips/condition_head.swf")
            heads = Movie(data).export(output, "animations/status/head")
            manifest["animations"]["status"]["heads"] = heads
            x, y, w, h = heads["viewBox"]
            head_bounds = (x, x + w, y, y + h)
            head = extract_markers(data, include_root=True).get("root")
            _, data = archive.read("interface/components/conditionclips/condition_body_0.swf")
            status = extract_markers(data, include_root=True, components={"Head_mc": head} if head else {}).get("root")
            if status:
                atomic_write(output / "status/healthy.svg", status)
                manifest["icons"]["status"]["healthy"] = "assets/status/healthy.svg"
            for body_flags in range(17):
                _, data = archive.read("interface/components/conditionclips/condition_body_%d.swf" % body_flags)
                manifest["animations"]["status"]["bodies"][str(body_flags)] = Movie(data).export(
                    output, "animations/status/body-%d" % body_flags, head_bounds=head_bounds)
        except (ValueError, IndexError, KeyError, struct.error, zlib.error):
            pass
        try:
            _, data = archive.read("interface/pipboy_statspage.swf")
            stats = Movie(data)
            damage_id = next(ident for name, ident in stats.names.items() if ".DamageIcons_" in name)
            damage = stats.export(output, "icons/damage", ident=damage_id)
            manifest["icons"]["damage"] = damage["frames"]
            holder_id = next(ident for name, ident in stats.names.items() if ".WeaponArmorHolder_" in name)
            holder_frames, holder_labels = stats.timelines[holder_id]
            for name in ("Weapon", "Armor"):
                # The first child is the shared UI backing panel. The second
                # is the native weapon/apparel pictogram itself.
                character = holder_frames[holder_labels[name]][-1]["id"]
                icon = stats.export(output, "icons/" + name.lower(), ident=character)
                manifest["icons"][name.lower()] = icon["frames"][0]
        except (ValueError, IndexError, KeyError, StopIteration, struct.error, zlib.error):
            pass
    except (ValueError, IndexError, OSError, KeyError, struct.error, zlib.error) as exc:
        manifest["warnings"].append("Could not extract map markers: %s" % exc)
    atomic_write(manifest_path, json.dumps(manifest, indent=2).encode())
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir")
    parser.add_argument("data_dir")
    args = parser.parse_args()
    print(json.dumps(prepare_assets(args.game_dir, args.data_dir), indent=2))
