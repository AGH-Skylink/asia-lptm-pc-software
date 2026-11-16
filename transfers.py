"""Acoustic setting announcements and chunked, verified binary file transfers."""
from __future__ import annotations

from array import array
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path, PureWindowsPath

from modem import MAX_TEXT_BYTES, ModemConfig, encode_payload, fsk_chunks

NEGOTIATION = b"LPTN2\x00"
FILE_MAGIC = b"LPTF2\x00"
BLOCK_BYTES = 1024
GUARD_SECONDS = 2


def bootstrap_config(sample_rate=48000):
    return ModemConfig(zero_hz=1200, one_hz=2200, baud=500, sample_rate=sample_rate)


def settings_packet(config: ModemConfig, encoding: str) -> bytes:
    config.validate()
    return NEGOTIATION + json.dumps({"config": asdict(config), "encoding": encoding},
                                    separators=(",", ":")).encode("ascii")


def read_settings(payload: bytes) -> tuple[ModemConfig, str]:
    if not payload.startswith(NEGOTIATION):
        raise ValueError("Nie jest to zapowiedź ustawień.")
    data = json.loads(payload[len(NEGOTIATION):])
    config = ModemConfig(**data["config"])
    config.validate()
    encoding = data["encoding"]
    if encoding not in ("ascii", "utf-8"):
        raise ValueError("Nieobsługiwane kodowanie.")
    return config, encoding


def announcement_chunks(config, encoding, amplitude):
    yield from fsk_chunks(encode_payload(settings_packet(config, encoding)),
                          bootstrap_config(config.sample_rate), amplitude)
    for _ in range(GUARD_SECONDS * config.sample_rate // 2048 + 1):
        yield array("f", [0.0] * 2048).tobytes()


def packet_audio(packets, config, message_id, amplitude, automatic, encoding):
    if automatic:
        yield from announcement_chunks(config, encoding, amplitude)
    for packet in packets:
        yield from fsk_chunks(encode_payload(packet, message_id), config, amplitude)


def file_packets(path: Path):
    """Read the same open file twice, without buffering the whole image in memory."""
    with path.open("rb") as source:
        digest = sha256()
        size = 0
        while chunk := source.read(65536):
            digest.update(chunk)
            size += len(chunk)
        metadata = json.dumps({"name": path.name, "size": size, "sha256": digest.hexdigest(),
                               "block_bytes": BLOCK_BYTES}, ensure_ascii=True).encode("ascii")
        header = FILE_MAGIC + b"H" + metadata
        if len(header) > MAX_TEXT_BYTES:
            raise ValueError("Nazwa pliku jest zbyt długa.")
        yield header
        source.seek(0)
        sequence = 0
        while chunk := source.read(BLOCK_BYTES):
            yield FILE_MAGIC + b"D" + sequence.to_bytes(4, "big") + chunk
            sequence += 1
        yield FILE_MAGIC + b"E"


class FileReceiver:
    def __init__(self):
        self.target = None
        self.message_id = None
        self.path: Path | None = None
        self.final_path: Path | None = None
        self.received = 0
        self.size = 0
        self.sequence = 0
        self.digest = sha256()
        self.expected_digest = ""
        self.completed = False
        self.blocks: set[int] = set()

    def close(self):
        if self.target is not None:
            self.target.close()
            self.target = None

    def _complete(self) -> str:
        self.target.flush()
        self.target.seek(0)
        digest = sha256()
        while chunk := self.target.read(65536):
            digest.update(chunk)
        self.close()
        if digest.hexdigest() != self.expected_digest:
            raise ValueError(f"Błędny SHA-256; niepełny lub uszkodzony plik zachowano: {self.path}")
        # Windows rename is atomic and refuses to overwrite an existing file.
        # On other platforms an exclusive hard link gives the same guarantee.
        import os
        if os.name == "nt":
            self.path.rename(self.final_path)
        else:
            self.final_path.hardlink_to(self.path)
            self.path.unlink()
        self.completed = True
        return f"Zapisano {self.final_path} ({self.size} bajtów, SHA-256 OK)"

    def pending_status(self) -> str:
        total = (self.size + BLOCK_BYTES - 1) // BLOCK_BYTES
        missing = total - len(self.blocks)
        return (f"Odebrano {self.received}/{self.size} bajtów, {len(self.blocks)}/{total} bloków; "
                f"brakuje {missing}. Dane zapisane częściowo: {self.path}")

    def accept(self, payload: bytes, message_id: bytes, directory: Path) -> str:
        if not payload.startswith(FILE_MAGIC):
            raise ValueError("Nieprawidłowy pakiet pliku.")
        kind, content = payload[len(FILE_MAGIC):len(FILE_MAGIC) + 1], payload[len(FILE_MAGIC) + 1:]
        if self.completed and message_id == self.message_id and kind in (b"H", b"D", b"E"):
            return f"Zapisano {self.final_path} ({self.size} bajtów, SHA-256 OK)"
        if kind == b"H":
            metadata = json.loads(content)
            name = PureWindowsPath(metadata["name"]).name
            if name in ("", ".", "..") or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name):
                raise ValueError("Nieprawidłowa nazwa pliku.")
            size = metadata["size"]
            if type(size) is not int or not 0 <= size <= 2**40 or metadata["block_bytes"] != BLOCK_BYTES:
                raise ValueError("Nieprawidłowy rozmiar pliku lub bloku.")
            digest = metadata["sha256"]
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Nieprawidłowa suma SHA-256.")
            if self.message_id == message_id and self.target is not None:
                return "Powtórzony nagłówek pliku."
            self.close()
            directory.mkdir(parents=True, exist_ok=True)
            final = directory / name
            if final.exists() or final.with_name(final.name + ".part").exists():
                final = directory / f"{final.stem}_{message_id.hex()}{final.suffix}"
            part = final.with_name(final.name + ".part")
            self.target = part.open("x+b")
            self.path, self.final_path = part, final
            self.message_id, self.size = message_id, size
            self.received, self.sequence, self.digest = 0, 0, sha256()
            self.expected_digest = digest
            self.completed = False
            self.blocks = set()
            if not self.size:
                return self._complete()
            return f"Odbiór pliku {name}: 0/{size} bajtów"
        if self.target is None or message_id != self.message_id:
            raise ValueError("Brak nagłówka dla tego pliku.")
        if kind == b"D":
            if len(content) < 5:
                raise ValueError("Niepełny blok pliku.")
            sequence, chunk = int.from_bytes(content[:4], "big"), content[4:]
            total_blocks = (self.size + BLOCK_BYTES - 1) // BLOCK_BYTES
            if not 0 <= sequence < total_blocks:
                raise ValueError("Numer bloku wykracza poza rozmiar pliku.")
            if sequence in self.blocks:
                return f"Powtórzony blok {sequence}; pominięto."
            expected = min(BLOCK_BYTES, self.size - sequence * BLOCK_BYTES)
            if len(chunk) != expected:
                raise ValueError("Nieprawidłowa długość bloku.")
            self.target.seek(sequence * BLOCK_BYTES)
            self.target.write(chunk)
            self.target.flush()
            self.blocks.add(sequence)
            self.received += len(chunk)
            while self.sequence in self.blocks:
                self.sequence += 1
            if len(self.blocks) == total_blocks:
                return self._complete()
            return self.pending_status()
        if kind != b"E" or content:
            raise ValueError("Nieznany pakiet pliku.")
        # Keep the file open: a delayed copy can still fill a missing block.
        raise ValueError("Transmisja niepełna. " + self.pending_status())
