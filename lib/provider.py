"""What a provider written in Python needs besides its game: the link to the screen host,
a keyboard to press keys on, and another process's memory. build.sh copies this file
next to a mod's provider as armada_provider.py.
"""
import fcntl, json, os, socket, struct, time

HELLO, STATE, INPUT = 1, 3, 16
MAX_BODY = 1 << 20


def frame(kind, obj):
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    return b"A2SS" + struct.pack("<HHII", kind, 0, len(body), 0) + body


class Link:
    """The connection to the screen host. Raises ConnectionError once the host has gone."""

    def __init__(self, appid, port=47800):
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port))
                break
            except OSError:
                time.sleep(0.5)
        self.sock.sendall(frame(HELLO, {"appid": appid}))
        self.sock.setblocking(False)
        self.inbox, self.sent = b"", None

    def send(self, state):
        """Sends a state unless it is the one the host already has."""
        data = frame(STATE, state)
        if data != self.sent:
            self.sock.setblocking(True)
            self.sock.sendall(data)
            self.sock.setblocking(False)
            self.sent = data

    def inputs(self):
        """What the view has sent since the last call, each a JSON object."""
        try:
            data = self.sock.recv(65536)
            if data == b"":
                raise ConnectionError("host closed")
            self.inbox += data
        except BlockingIOError:
            pass
        out = []
        while len(self.inbox) >= 16:
            kind, _, size, _ = struct.unpack("<HHII", self.inbox[4:16])
            if self.inbox[:4] != b"A2SS" or size > MAX_BODY:
                raise ConnectionError("bad message")
            if len(self.inbox) < 16 + size:
                break
            body, self.inbox = self.inbox[16:16 + size], self.inbox[16 + size:]
            if kind == INPUT:
                try:
                    obj = json.loads(body)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
        return out


class Keyboard:
    """A keyboard with the given keys (Linux key codes). Presses go to whatever has the keyboard's focus."""

    def __init__(self, codes):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, 0x40045564, 1)                        # key events
        for code in set(codes):
            fcntl.ioctl(self.fd, 0x40045565, code)
        fcntl.ioctl(self.fd, 0x405c5503, struct.pack("<HHHH80sI", 3, 0x1209, 0xa2d5, 1, b"Armada second screen keys", 0))
        fcntl.ioctl(self.fd, 0x5501)

    def press(self, code):
        for value in (1, 0):
            os.write(self.fd, struct.pack("<qqHHi", 0, 0, 1, code, value) + struct.pack("<qqHHi", 0, 0, 0, 0, 0))
            time.sleep(0.05)


class Gone(Exception):
    """The process being read has exited."""


class Process:
    """Another process's memory, read only. A failed read raises LookupError, or Gone once the process has exited."""

    def __init__(self, pid):
        self.pid = pid
        self.mem = open(f"/proc/{pid}/mem", "rb", buffering=0)

    @classmethod
    def find(cls, suffix):
        """The process whose program name ends with suffix, lower case; a Windows game's has backslashes."""
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                try:
                    argv0 = open(f"/proc/{entry}/cmdline", "rb").read().split(b"\0")[0].decode("utf-8", "replace").lower()
                    if argv0.endswith(suffix):
                        return cls(int(entry))
                except OSError:
                    continue
        return None

    def read(self, addr, size):
        try:
            self.mem.seek(addr)
            data = self.mem.read(size)
        except (OSError, ValueError, OverflowError):
            data = b""
        if len(data) != size:
            if not os.path.exists(f"/proc/{self.pid}"):
                raise Gone()
            raise LookupError(hex(addr))
        return data

    def unpack(self, fmt, addr):
        return struct.unpack(fmt, self.read(addr, struct.calcsize(fmt)))
