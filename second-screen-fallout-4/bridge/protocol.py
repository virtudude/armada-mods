"""Fallout 4 companion wire format. Independent implementation; see README sources."""
import math
import struct
import zlib

MAX_PACKET = 16 * 1024 * 1024


class ProtocolError(ValueError):
    pass


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def read(self, fmt):
        size = struct.calcsize('<' + fmt)
        if self.pos + size > len(self.data):
            raise ProtocolError('Truncated data update')
        values = struct.unpack_from('<' + fmt, self.data, self.pos)
        self.pos += size
        return values[0] if len(values) == 1 else values

    def string(self):
        end = self.data.find(b'\0', self.pos)
        if end < 0 or end - self.pos > 65536:
            raise ProtocolError('Invalid string')
        value = self.data[self.pos:end].decode('utf-8', 'replace')
        self.pos = end + 1
        return value


class Database:
    def __init__(self):
        self.nodes = {}

    def update(self, payload):
        # Commit only after a complete packet parses; malformed updates never
        # leave half-applied inventory state eligible for actions.
        r, changes = Reader(payload), {}
        while r.pos < len(payload):
            typ, ident = r.read('BI')
            if typ <= 5:
                value = r.read(('B', 'b', 'B', 'i', 'I', 'f')[typ])
                if typ == 0:
                    value = bool(value)
                if typ == 5 and not math.isfinite(value):
                    value = None
            elif typ == 6:
                value = r.string()
            elif typ == 7:
                value = [r.read('I') for _ in range(r.read('H'))]
            elif typ == 8:
                previous = changes.get(ident, self.nodes.get(ident))
                value = dict(previous[1]) if previous and previous[0] == 8 else {}
                for _ in range(r.read('H')):
                    ref = r.read('I')
                    value[r.string()] = ref
                removed = {r.read('I') for _ in range(r.read('H'))}
                value = {key: ref for key, ref in value.items() if ref not in removed}
            else:
                raise ProtocolError('Unknown data type: ' + str(typ))
            changes[ident] = (typ, value)
        if len(self.nodes) + len(changes.keys() - self.nodes.keys()) > 250000:
            raise ProtocolError('Database too large')
        self.nodes.update(changes)

    def resolve(self, ident=0):
        budget = [250000]
        def visit(key, path):
            budget[0] -= 1
            if budget[0] < 0 or len(path) > 64 or key in path:
                raise ProtocolError('Invalid data graph')
            if key not in self.nodes:
                return None  # References can arrive in the next update.
            typ, value = self.nodes[key]
            if typ == 7:
                return [visit(ref, path | {key}) for ref in value]
            if typ == 8:
                obj = {name: visit(ref, path | {key}) for name, ref in value.items()}
                obj['_id'] = key
                return obj
            return value
        return visit(ident, set())


def packet(channel, body=b''):
    if len(body) > MAX_PACKET:
        raise ProtocolError('Packet too large')
    return struct.pack('<IB', len(body), channel) + body


class Framer:
    """Incremental framing tolerates split headers/bodies without blocking UI."""
    def __init__(self, host=False):
        self.buf = bytearray()
        self.host = host

    def feed(self, data):
        self.buf.extend(data)
        head = 16 if self.host else 5
        packets = []
        while len(self.buf) >= head:
            if self.host:
                magic, channel, flags, size, seq = struct.unpack_from('<4sHHII', self.buf)
                if magic != b'A2SS' or size > 1024 * 1024:
                    raise ProtocolError('Invalid screen-host frame')
            else:
                size, channel = struct.unpack_from('<IB', self.buf)
            if size > MAX_PACKET:
                raise ProtocolError('Packet too large')
            if len(self.buf) < head + size:
                break
            packets.append((channel, bytes(self.buf[head:head + size])))
            del self.buf[:head + size]
        return packets


def local_map(payload):
    if len(payload) < 32:
        raise ProtocolError('Truncated local map')
    w, h, nwx, nwy, nex, ney, swx, swy = struct.unpack_from('<II6f', payload)
    if not (0 < w <= 4096 and 0 < h <= 4096) or len(payload) != 32 + w * h:
        raise ProtocolError('Invalid local map dimensions')
    if not all(math.isfinite(v) for v in (nwx, nwy, nex, ney, swx, swy)):
        raise ProtocolError('Invalid map extents')
    # PNG grayscale, supplied by the live game, never bundled.
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data))
    pixels = payload[32:]
    rows = b''.join(b'\0' + pixels[y*w:(y+1)*w] for y in range(h))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')
    return png, {'width': w, 'height': h, 'extents': dict(zip(
        ('NWX', 'NWY', 'NEX', 'NEY', 'SWX', 'SWY'), (nwx,nwy,nex,ney,swx,swy)))}
