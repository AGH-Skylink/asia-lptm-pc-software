"""Small local VNC client for clicking and typing in the QEMU test VM."""

from __future__ import annotations

import argparse
import os
import socket
import struct
import subprocess
import time

from press_boot import read_exact


KEYS = {
    "enter": 0xFF0D,
    "tab": 0xFF09,
    "space": 0x20,
    "escape": 0xFF1B,
    "backspace": 0xFF08,
    "up": 0xFF52,
    "down": 0xFF54,
    "left": 0xFF51,
    "right": 0xFF53,
    "ctrl": 0xFFE3,
    "alt": 0xFFE9,
    "shift": 0xFFE1,
    "f10": 0xFFC7,
}


def connect() -> socket.socket:
    connection = socket.create_connection(("127.0.0.1", 5901), timeout=5)
    version = read_exact(connection, 12)
    if not version.startswith(b"RFB "):
        raise RuntimeError(f"Unexpected VNC version: {version!r}")
    connection.sendall(b"RFB 003.008\n")
    count = read_exact(connection, 1)[0]
    methods = read_exact(connection, count)
    if 2 in methods:
        connection.sendall(b"\x02")
        challenge = read_exact(connection, 16)
        password = os.environ.get("QEMU_VNC_PASSWORD", "Sound123").encode("latin-1")[:8]
        key = bytes(int(f"{byte:08b}"[::-1], 2) for byte in password.ljust(8, b"\0"))
        encrypted = subprocess.run(
            ["openssl", "enc", "-des-ecb", "-provider", "default", "-provider", "legacy",
             "-nopad", "-nosalt", "-K", key.hex()],
            input=challenge, capture_output=True, check=True,
        ).stdout
        connection.sendall(encrypted)
    elif 1 in methods:
        connection.sendall(b"\x01")
    else:
        raise RuntimeError("Unsupported VNC authentication method")
    if struct.unpack(">I", read_exact(connection, 4))[0] != 0:
        raise RuntimeError("VNC authentication failed")
    connection.sendall(b"\x01")
    header = read_exact(connection, 24)
    read_exact(connection, struct.unpack(">I", header[20:24])[0])
    return connection


def key(connection: socket.socket, symbol: int) -> None:
    shifted = {ord("_"): ord("-"), ord(":"): ord(";")}
    if symbol in shifted:
        connection.sendall(struct.pack(">BBHI", 4, 1, 0, KEYS["shift"]))
        symbol = shifted[symbol]
        connection.sendall(struct.pack(">BBHI", 4, 1, 0, symbol))
        time.sleep(0.03)
        connection.sendall(struct.pack(">BBHI", 4, 0, 0, symbol))
        connection.sendall(struct.pack(">BBHI", 4, 0, 0, KEYS["shift"]))
        return
    connection.sendall(struct.pack(">BBHI", 4, 1, 0, symbol))
    time.sleep(0.03)
    connection.sendall(struct.pack(">BBHI", 4, 0, 0, symbol))


def main() -> None:
    parser = argparse.ArgumentParser()
    operations = parser.add_subparsers(dest="operation", required=True)
    click = operations.add_parser("click")
    click.add_argument("x", type=int)
    click.add_argument("y", type=int)
    press = operations.add_parser("key")
    press.add_argument("name")
    typing = operations.add_parser("type")
    typing.add_argument("text")
    args = parser.parse_args()

    with connect() as connection:
        if args.operation == "click":
            connection.sendall(struct.pack(">BBHH", 5, 0, args.x, args.y))
            connection.sendall(struct.pack(">BBHH", 5, 1, args.x, args.y))
            time.sleep(0.08)
            connection.sendall(struct.pack(">BBHH", 5, 0, args.x, args.y))
        elif args.operation == "key":
            key(connection, KEYS.get(args.name.lower(), ord(args.name) if len(args.name) == 1 else 0))
        else:
            for character in args.text:
                key(connection, ord(character))
                time.sleep(0.04)


if __name__ == "__main__":
    main()
