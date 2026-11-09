"""Local-only reference channel between transmitter and receiver processes."""

from __future__ import annotations

from queue import Queue
import socket
from struct import pack, unpack
from threading import Event, Thread


HOST = "127.0.0.1"
PORT = 51526
ID_BYTES = 8
MAX_REFERENCE_BYTES = 2048


def _read_exact(connection: socket.socket, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        part = connection.recv(count - len(data))
        if not part:
            raise ConnectionError("Przerwane połączenie lokalne.")
        data.extend(part)
    return bytes(data)


def send_reference(message_id: bytes, payload: bytes, port: int = PORT) -> bool:
    """Send the expected data before audio playback; return False if no receiver listens."""
    if len(message_id) != ID_BYTES or not 1 <= len(payload) <= MAX_REFERENCE_BYTES:
        raise ValueError("Nieprawidłowy identyfikator lub długość wiadomości.")
    try:
        with socket.create_connection((HOST, port), timeout=0.5) as connection:
            connection.settimeout(1)
            connection.sendall(message_id + pack(">H", len(payload)) + payload)
            return _read_exact(connection, 1) == b"\x06"
    except OSError:
        return False


class ReferenceServer:
    def __init__(self, port: int = PORT):
        self.port = port
        self.incoming: Queue[tuple[bytes, bytes]] = Queue()
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
                    connection.settimeout(1)
                    header = _read_exact(connection, ID_BYTES + 2)
                    message_id = header[:ID_BYTES]
                    length = unpack(">H", header[ID_BYTES:])[0]
                    if not 1 <= length <= MAX_REFERENCE_BYTES:
                        continue
                    payload = _read_exact(connection, length)
                    self.incoming.put((message_id, payload))
                    connection.sendall(b"\x06")
                except (OSError, ConnectionError):
                    continue

    def stop(self) -> None:
        self.stop_event.set()
        if self.listener is not None:
            self.listener.close()
            self.listener = None
        if self.thread is not None:
            self.thread.join(timeout=1)
            self.thread = None
