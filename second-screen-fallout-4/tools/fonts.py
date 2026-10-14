#!/usr/bin/env python3
"""Convert installed SWF DefineFont3 glyphs into browser TrueType fonts.

The mod ships this converter, never font data. Quadratic outlines, Unicode
mapping, advances and kerning come from the player's Interface BA2. Runtime
uses only Python's standard library. Format references: Adobe SWF 19 and
Microsoft OpenType (glyf, head, hhea, hmtx, cmap, OS/2, maxp, name, post).
"""
import json
from pathlib import Path
import re
import struct

from assets import Archive, AssetError, Bits, MAX_PAYLOAD, atomic_write, inflate, swf_tags

SCHEMA = 1
# Font3's em is 20480. 8192 preserves outlines within 1/16384 em while
# leaving room in signed glyph coordinates for wide controller-button symbols.
EM = 8192
FONTS = {"Roboto Condensed": "main", "Roboto Condensed Bold": "bold",
         "Share-TechMono Regular": "terminal", "Controller  Buttons": "controller"}


def scale(value):
    return round(value * EM / 20480)


def _unpack(fmt, data, offset=0):
    try:
        return struct.unpack_from(fmt, data, offset)
    except struct.error as exc:
        raise AssetError("Truncated font table") from exc


def glyph_contours(data):
    """Read SWF font SHAPE edges and reconnect each fill into closed contours."""
    bits = Bits(data)
    fill_bits, line_bits = bits.read(4), bits.read(4)
    point, fill0, fill1 = (0, 0), 0, 0
    edges = {}
    while True:
        if not bits.read(1):
            flags = bits.read(5)
            if not flags:
                break
            if flags & 1:
                size = bits.read(5)
                point = (bits.read(size, True), bits.read(size, True))
            if flags & 2:
                fill0 = bits.read(fill_bits)
            if flags & 4:
                fill1 = bits.read(fill_bits)
            if flags & 8:
                if bits.read(line_bits):
                    raise AssetError("Font glyph has a stroke")
            if flags & 16:
                raise AssetError("Font glyph has new styles")
            continue
        straight, size = bits.read(1), bits.read(4) + 2
        start, control = point, None
        if straight:
            if bits.read(1):
                dx, dy = bits.read(size, True), bits.read(size, True)
            elif bits.read(1):
                dx, dy = 0, bits.read(size, True)
            else:
                dx, dy = bits.read(size, True), 0
            point = (start[0] + dx, start[1] + dy)
        else:
            control = (start[0] + bits.read(size, True), start[1] + bits.read(size, True))
            point = (control[0] + bits.read(size, True), control[1] + bits.read(size, True))
        if fill0:
            edges.setdefault(start, []).append((control, point))
        if fill1:
            edges.setdefault(point, []).append((control, start))
    contours = []
    while edges:
        start = point = next(iter(edges))
        contour = [(scale(point[0]), -scale(point[1]), 1)]
        while point in edges:
            control, end = edges[point].pop()
            if not edges[point]:
                del edges[point]
            if control is not None:
                contour.append((scale(control[0]), -scale(control[1]), 0))
            point = end
            if point == start:
                break
            contour.append((scale(point[0]), -scale(point[1]), 1))
        if point != start:
            raise AssetError("Open font glyph contour")
        if len(contour) > 1:
            contours.append(contour)
    return contours


def parse_font3(data):
    _, flags, language, length = _unpack("<HBBB", data)
    name = data[5:5 + length].rstrip(b"\0").decode("utf-8")
    position = 5 + length
    count, = _unpack("<H", data, position)
    position += 2
    if not flags & 128 or not 1 <= count < 8192:
        raise AssetError("Font3 requires layout and a bounded glyph count")
    width = 4 if flags & 8 else 2
    offsets = _unpack("<" + ("I" if width == 4 else "H") * (count + 1), data, position)
    if offsets[0] < width * (count + 1) or any(a > b for a, b in zip(offsets, offsets[1:])):
        raise AssetError("Invalid font glyph offsets")
    if position + offsets[-1] > len(data):
        raise AssetError("Truncated glyph table")
    contours = [glyph_contours(data[position+a:position+b]) for a, b in zip(offsets, offsets[1:])]
    position += offsets[-1]
    wide = bool(flags & 4)
    codes = list(_unpack("<" + ("H" if wide else "B") * count, data, position))
    position += count * (2 if wide else 1)
    ascent, descent, leading = _unpack("<HHh", data, position)
    position += 6
    advances = [scale(v) for v in _unpack("<" + "h" * count, data, position)]
    position += count * 2
    bits = Bits(data, position)
    for _ in range(count):
        bits.rect()
    position = bits.position // 8
    kern_count, = _unpack("<H", data, position)
    position += 2
    kerning = []
    fmt = "<HHh" if wide else "<BBh"
    for _ in range(kern_count):
        left, right, adjustment = _unpack(fmt, data, position)
        kerning.append((left, right, scale(adjustment)))
        position += struct.calcsize(fmt)
    if position != len(data):
        raise AssetError("Unexpected trailing font bytes")
    return dict(name=name, bold=bool(flags & 1), italic=bool(flags & 2),
                contours=contours, codes=codes, advances=advances,
                ascent=scale(ascent), descent=-scale(descent), leading=scale(leading), kerning=kerning)


def _glyph(contours):
    points = [p for contour in contours for p in contour]
    if not points:
        return b"", (0, 0, 0, 0)
    bounds = (min(p[0] for p in points), min(p[1] for p in points),
              max(p[0] for p in points), max(p[1] for p in points))
    result = bytearray(struct.pack(">hhhhh", len(contours), *bounds))
    total = 0
    for contour in contours:
        total += len(contour)
        result += struct.pack(">H", total - 1)
    result += b"\0\0"  # no TrueType bytecode (SWF stores outlines only)
    result += bytes(p[2] for p in points)
    for axis in (0, 1):
        previous = 0
        for point in points:
            result += struct.pack(">h", point[axis] - previous)
            previous = point[axis]
    result += b"\0" * (-len(result) % 4)
    return bytes(result), bounds


def checksum(data):
    data += b"\0" * (-len(data) % 4)
    return sum(struct.unpack(">" + "I" * (len(data) // 4), data)) & 0xffffffff


def build_ttf(font):
    contours = [[]] + font["contours"]  # reserve .notdef glyph zero
    advances = [EM // 2] + font["advances"]
    encoded = [_glyph(c) for c in contours]
    boxes = [v[1] for v in encoded]
    bounds = tuple(fn(b[i] for b in boxes) for i, fn in enumerate((min, min, max, max)))
    offsets, offset = [], 0
    for glyph, _ in encoded:
        offsets.append(offset)
        offset += len(glyph)
    offsets.append(offset)
    tables = {"glyf": b"".join(v[0] for v in encoded),
              "loca": struct.pack(">" + "I" * len(offsets), *offsets),
              "hmtx": b"".join(struct.pack(">Hh", max(0, advance), box[0]) for advance, box in zip(advances, boxes))}
    style = (1 if font["bold"] else 0) | (2 if font["italic"] else 0)
    tables["head"] = struct.pack(">IIIIHHQQhhhhHHhhh", 0x10000, 0x10000, 0, 0x5f0f3cf5,
        3, EM, 0, 0, *bounds, style, 8, 2, 1, 0)
    tables["hhea"] = struct.pack(">IhhhHhhhhhh4hhH", 0x10000, font["ascent"], font["descent"],
        font["leading"], max(advances), min(b[0] for b in boxes),
        min(a-b[2] for a,b in zip(advances,boxes)), max(b[2] for b in boxes),
        1, 0, 0, 0, 0, 0, 0, 0, len(contours))
    max_points = max(sum(map(len,c)) for c in contours)
    tables["maxp"] = struct.pack(">I14H", 0x10000, len(contours), max_points,
        max(map(len,contours)), 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0)
    mapping = {code: i+1 for i,code in enumerate(font["codes"]) if code < 0xffff}
    codes = sorted(mapping)
    segments = codes + [0xffff]
    n = len(segments)
    power = 2 ** (n.bit_length()-1)
    cmap = struct.pack(">7H", 4, 16+8*n, 0, 2*n, 2*power, power.bit_length()-1, 2*(n-power))
    cmap += struct.pack(">"+"H"*n, *segments) + b"\0\0"
    cmap += struct.pack(">"+"H"*n, *segments)
    cmap += struct.pack(">"+"H"*n, *[(mapping[c]-c)&65535 for c in codes], 1)
    cmap += b"\0\0" * n
    tables["cmap"] = struct.pack(">HHHHI", 0, 1, 3, 1, 12) + cmap
    name = font["name"]
    subfamily = "Bold" if font["bold"] else "Regular"
    names = {1:name, 2:subfamily, 3:"Armada-Game-"+name, 4:name, 5:"Version 1.0",
             6:re.sub(r"[^A-Za-z0-9-]", "", name)}
    records, strings = b"", b""
    for ident, value in sorted(names.items()):
        encoded_name = value.encode("utf-16be")
        records += struct.pack(">6H", 3, 1, 0x409, ident, len(encoded_name), len(strings))
        strings += encoded_name
    tables["name"] = struct.pack(">3H", 0, len(names), 6+12*len(names)) + records + strings
    tables["post"] = struct.pack(">IIhhIIIII", 0x30000, 0, -EM//10, EM//20, 0, 0, 0, 0, 0)
    os2 = bytearray(78)
    struct.pack_into(">HhHHH", os2, 0, 0, sum(advances)//len(advances), 700 if font["bold"] else 400, 5, 0)
    os2[58:62] = b"ARMA"
    struct.pack_into(">3H3h2H", os2, 62, (32 if font["bold"] else 64) | (1 if font["italic"] else 0),
        min(codes), max(codes), font["ascent"], font["descent"], font["leading"],
        max(font["ascent"],bounds[3]), max(-font["descent"],-bounds[1]))
    tables["OS/2"] = bytes(os2)
    pairs = sorted({(mapping[a],mapping[b]):v for a,b,v in font["kerning"] if a in mapping and b in mapping}.items())
    if pairs:
        power = 2 ** (len(pairs).bit_length()-1)
        sub = struct.pack(">7H", 0, 14+6*len(pairs), 1, len(pairs), power*6, power.bit_length()-1, (len(pairs)-power)*6)
        tables["kern"] = struct.pack(">HH",0,1)+sub+b"".join(struct.pack(">HHh",*pair,value) for pair,value in pairs)
    tags = sorted(tables)
    n = len(tags)
    power = 2 ** (n.bit_length()-1)
    header = struct.pack(">I4H",0x10000,n,power*16,power.bit_length()-1,(n-power)*16)
    directory, payload, offset, head_offset = b"", b"", 12+16*n, None
    for tag in tags:
        table = tables[tag]
        directory += struct.pack(">4sIII",tag.encode(),checksum(table),offset,len(table))
        if tag == "head":
            head_offset = offset
        padded = table + b"\0"*(-len(table)%4)
        payload += padded
        offset += len(padded)
    result = bytearray(header+directory+payload)
    struct.pack_into(">I",result,head_offset+8,(0xb1b0afba-checksum(bytes(result)))&0xffffffff)
    return bytes(result)


def extract_fonts(data):
    if data[:3] not in (b"FWS",b"CWS"):
        raise AssetError("Unsupported font SWF")
    length, = _unpack("<I",data,4)
    if not 8 < length <= MAX_PAYLOAD:
        raise AssetError("Invalid font SWF length")
    body = inflate(data[8:],length-8) if data[:3] == b"CWS" else data[8:]
    if len(body) != length-8:
        raise AssetError("Invalid font SWF size")
    bits = Bits(body)
    bits.rect()
    bits.bytes(4)
    result = {}
    for tag, payload in swf_tags(body[bits.position//8:]):
        if tag == 75:
            _,_,_,length = _unpack("<HBBB",payload)
            name = payload[5:5+length].rstrip(b"\0").decode("utf-8")
            if name in FONTS:
                font = parse_font3(payload)
                result[FONTS[name]] = {"name":name, "data":build_ttf(font), "glyphs":len(font["codes"])}
    return result


def prepare_fonts(game_dir, data_dir):
    """Return {fonts: role -> {path, name, glyphs}, warnings: []}."""
    source = Path(game_dir)/"Data/Fallout4 - Interface.ba2"
    destination = Path(data_dir)/"assets/fonts"
    cache = destination/"manifest.json"
    try:
        identity = [source.stat().st_size,source.stat().st_mtime_ns]
        try:
            stored = json.loads(cache.read_text())
            if stored.get("schema") == SCHEMA and stored.get("source") == identity and stored.get("fonts") and all(
                (Path(data_dir)/font["path"]).is_file() for font in stored["fonts"].values()):
                return stored
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            pass
        _,data = Archive(source).read("interface/fonts_en.swf")
        fonts = extract_fonts(data)
        result = {"schema":SCHEMA,"source":identity,"fonts":{},"warnings":[]}
        for role,font in fonts.items():
            path = "assets/fonts/"+role+".ttf"
            atomic_write(Path(data_dir)/path,font["data"])
            result["fonts"][role] = {"path":path,"name":font["name"],"glyphs":font["glyphs"]}
        if "main" not in fonts:
            result["warnings"].append("Installed game SWF did not contain the expected native Pip-Boy font")
        atomic_write(cache,json.dumps(result,indent=2).encode())
        return result
    except (OSError,ValueError,KeyError,IndexError,struct.error) as exc:
        return {"fonts":{},"warnings":["Could not convert installed Pip-Boy fonts: "+str(exc)]}
