#!/usr/bin/env python3
"""Restore the retained companion service in a private game overlay copy.

No game executable is distributed. Only the exact independently inspected
Steam 1.11.240.0 executable is accepted; future builds fail closed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import tempfile


SOURCE_SHA256 = "fdcef37ac1230af6d0b0050eb2142b139ef3a867b37b9211fb6edfcc646072f8"
SOURCE_SIZE = 55343016
PATCH_OFFSET = 0x9A61E9
PATCH_RVA = 0x9A6DE9
START_RVA = 0x9A6BB0
PATCH_SIZE = 5
# Tail-call the original no-argument initializer after the original stack unwind.
REPLACEMENT = b"\xe9" + struct.pack("<i", START_RVA - (PATCH_RVA + 5))
CONTEXT_OFFSET = 0x9A61C0
CONTEXT_SIZE = 48
# Verify the instruction region without distributing original game bytes.
CONTEXT_SHA256 = "71326d0cd003bcf1b6a2d1825fb02cfd4d90a7602a158c23ef730c795613ba2e"


class UnsupportedExecutable(ValueError):
    pass


def patch_bytes(source: bytes) -> bytes:
    digest = hashlib.sha256(source).hexdigest()
    if len(source) != SOURCE_SIZE or digest != SOURCE_SHA256:
        raise UnsupportedExecutable(
            "Pip-Boy service restoration supports the inspected Steam Fallout 4 "
            f"1.11.240.0 executable only (found SHA-256 {digest}). "
            "The installed game has not been modified."
        )
    context = source[CONTEXT_OFFSET:CONTEXT_OFFSET + CONTEXT_SIZE]
    if hashlib.sha256(context).hexdigest() != CONTEXT_SHA256:
        raise UnsupportedExecutable("Companion update instructions do not match the inspected build.")
    result = bytearray(source)
    result[PATCH_OFFSET:PATCH_OFFSET + PATCH_SIZE] = REPLACEMENT
    return bytes(result)


def prepare_companion(source: Path, output: Path) -> dict:
    """Atomically write the patched executable to an overlay; never edit source."""
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError("Companion output must be a private overlay copy, never the installed game.")
    if output.exists() and os.path.samefile(source, output):
        raise ValueError("Companion output must not be a hard link to the installed game.")
    # Validate before creating/changing the output; unsupported games leave it intact.
    patched = patch_bytes(source.read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(patched).hexdigest()
    if output.is_file() and not output.is_symlink():
        if hashlib.sha256(output.read_bytes()).hexdigest() == digest:
            return {"version": "1.11.240.0", "sha256": digest, "path": str(output), "cached": True}
    fd, temporary = tempfile.mkstemp(prefix=".companion-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(patched)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), stat.S_IMODE(source.stat().st_mode) | stat.S_IXUSR)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"version": "1.11.240.0", "sha256": digest, "path": str(output), "cached": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Installed Fallout4.exe (read only)")
    parser.add_argument("output", type=Path, help="Private overlay Fallout4.exe")
    arguments = parser.parse_args()
    try:
        print(json.dumps(prepare_companion(arguments.source, arguments.output)))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Pip-Boy: {exc}\n")
