"""Send repeated Space key events through local VNC during Windows ISO boot."""

from __future__ import annotations

import socket
import struct
import sys
import time


def read_exact(connection: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        part = connection.recv(length - len(chunks))
        if not part:
            raise ConnectionError("VNC connection closed")
        chunks.extend(part)
    return bytes(chunks)


def main() -> None:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    with socket.create_connection(("127.0.0.1", 5901), timeout=5) as connection:
        version = read_exact(connection, 12)
        if not version.startswith(b"RFB "):
            raise RuntimeError(f"Unexpected VNC version: {version!r}")
        connection.sendall(b"RFB 003.008\n")
        count = read_exact(connection, 1)[0]
        methods = read_exact(connection, count)
        if 1 not in methods:
            raise RuntimeError(f"VNC server needs unsupported authentication: {methods!r}")
        connection.sendall(b"\x01")
        if struct.unpack(">I", read_exact(connection, 4))[0] != 0:
            raise RuntimeError("VNC authentication failed")
        connection.sendall(b"\x01")
        header = read_exact(connection, 24)
        name_length = struct.unpack(">I", header[20:24])[0]
        read_exact(connection, name_length)
        print("Connected to QEMU VNC; sending Space during boot.", flush=True)
        until = time.monotonic() + duration
        while time.monotonic() < until:
            connection.sendall(struct.pack(">BBHI", 4, 1, 0, 0x20))
            time.sleep(0.04)
            connection.sendall(struct.pack(">BBHI", 4, 0, 0, 0x20))
            time.sleep(0.36)


if __name__ == "__main__":
    main()
