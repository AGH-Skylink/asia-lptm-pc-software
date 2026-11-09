"""Loopback command channel for the automated sweep to drive both GUI apps."""

from __future__ import annotations

import json
from queue import Empty, Queue
import socket
from threading import Event, Thread


HOST = "127.0.0.1"
TRANSMITTER_PORT = 51527
RECEIVER_PORT = 51528
MAX_REQUEST = 16_384


def _line(connection: socket.socket) -> bytes:
    data = bytearray()
    while len(data) < MAX_REQUEST:
        part = connection.recv(1)
        if not part:
            break
        if part == b"\n":
            return bytes(data)
        data.extend(part)
    raise ValueError("Niepełne lub zbyt długie polecenie lokalne.")


def send_command(port: int, command: dict, timeout: float = 5) -> dict:
    with socket.create_connection((HOST, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        connection.sendall(json.dumps(command, ensure_ascii=False).encode("utf-8") + b"\n")
        result = json.loads(_line(connection).decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Nieprawidłowa odpowiedź aplikacji.")
    return result


class CommandServer:
    def __init__(self, port: int):
        self.port = port
        self.incoming: Queue[tuple[dict, Queue[dict]]] = Queue()
        self.stop_event = Event()
        self.listener: socket.socket | None = None
        self.thread: Thread | None = None

    def start(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((HOST, self.port))
            listener.listen(4)
            listener.settimeout(0.2)
        except Exception:
            listener.close()
            raise
        self.listener = listener
        self.thread = Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        assert self.listener is not None
        while not self.stop_event.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                try:
                    connection.settimeout(8)
                    command = json.loads(_line(connection).decode("utf-8"))
                    if not isinstance(command, dict):
                        raise ValueError("Polecenie musi być obiektem JSON.")
                    response: Queue[dict] = Queue(maxsize=1)
                    self.incoming.put((command, response))
                    result = response.get(timeout=5)
                except (OSError, ValueError, json.JSONDecodeError, Empty) as exc:
                    result = {"error": str(exc)}
                try:
                    connection.sendall(json.dumps(result, ensure_ascii=False).encode("utf-8") + b"\n")
                except OSError:
                    pass

    def stop(self) -> None:
        self.stop_event.set()
        if self.listener is not None:
            self.listener.close()
            self.listener = None
        if self.thread is not None:
            self.thread.join(timeout=1)
            self.thread = None
