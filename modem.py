"""Small, deliberately slow acoustic FSK modem shared by both applications.

The protocol is: alternating preamble, sync word, 16-bit byte count, UTF-8
payload, CRC-16/CCITT-FALSE. All integer fields are sent most-significant bit
first. The sample rate is fixed so transmitter and receiver agree on timing.
"""

from __future__ import annotations

from array import array
from collections import deque
from dataclasses import dataclass
from math import cos, pi, sin
from typing import Callable


SAMPLE_RATE = 48_000
MAX_TEXT_BYTES = 2_048
PREAMBLE = tuple([1, 0] * 16)
SYNC = tuple((0xDDAA96F3 >> shift) & 1 for shift in range(31, -1, -1))
HEADER = PREAMBLE + SYNC


@dataclass(frozen=True)
class ModemConfig:
    zero_hz: int = 1_200
    one_hz: int = 2_200
    baud: int = 25
    max_hz: int = 20_000

    def validate(self) -> None:
        if not 100 <= self.max_hz <= 20_000:
            raise ValueError("Górna granica pasma musi być w zakresie 100–20000 Hz.")
        if not (100 <= self.zero_hz <= self.max_hz):
            raise ValueError("Częstotliwość zera musi mieścić się w wybranym paśmie.")
        if not (100 <= self.one_hz <= self.max_hz):
            raise ValueError("Częstotliwość jedynki musi mieścić się w wybranym paśmie.")
        if abs(self.one_hz - self.zero_hz) < 200:
            raise ValueError("Częstotliwości 0 i 1 muszą różnić się o co najmniej 200 Hz.")
        if not 5 <= self.baud <= 100:
            raise ValueError("Szybkość musi mieścić się w zakresie 5–100 bitów/s.")

    @property
    def samples_per_bit(self) -> int:
        return round(SAMPLE_RATE / self.baud)


def _bits(value: int, count: int) -> list[int]:
    return [(value >> shift) & 1 for shift in range(count - 1, -1, -1)]


def _number(bits: list[int] | tuple[int, ...]) -> int:
    value = 0
    for bit in bits:
        value = (value << 1) | bit
    return value


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode_text(text: str) -> list[int]:
    payload = text.encode("utf-8")
    if not payload:
        raise ValueError("Wpisz tekst do wysłania.")
    if len(payload) > MAX_TEXT_BYTES:
        raise ValueError(f"Tekst może mieć najwyżej {MAX_TEXT_BYTES} bajtów UTF-8.")
    frame = list(HEADER)
    frame += _bits(len(payload), 16)
    for byte in payload:
        frame += _bits(byte, 8)
    frame += _bits(crc16(payload), 16)
    return frame


def estimated_seconds(text: str, config: ModemConfig) -> float:
    return len(encode_text(text)) / config.baud


def fsk_chunks(bits: list[int], config: ModemConfig, amplitude: float, chunk_size: int = 2_048):
    """Yield mono float32 PCM chunks with continuous phase and edge fades."""
    config.validate()
    if not 0 <= amplitude <= 1:
        raise ValueError("Poziom sygnału musi być w zakresie 0–100%.")
    phase = 0.0
    out = array("f")
    total = len(bits) * config.samples_per_bit
    fade = min(round(SAMPLE_RATE * 0.01), max(1, total // 4))
    sample_index = 0
    for bit in bits:
        step = 2 * pi * (config.one_hz if bit else config.zero_hz) / SAMPLE_RATE
        for _ in range(config.samples_per_bit):
            envelope = min(1.0, (sample_index + 1) / fade, (total - sample_index) / fade)
            out.append(amplitude * envelope * sin(phase))
            phase = (phase + step) % (2 * pi)
            sample_index += 1
            if len(out) >= chunk_size:
                yield out.tobytes()
                out = array("f")
    if out:
        yield out.tobytes()


def tone_chunks(hz: float, amplitude: float, chunk_size: int = 2_048):
    if not 0 <= hz <= 20_000 or not 0 <= amplitude <= 1:
        raise ValueError("Nieprawidłowa częstotliwość lub poziom generatora.")
    phase = 0.0
    step = 2 * pi * hz / SAMPLE_RATE
    while True:
        out = array("f")
        for _ in range(chunk_size):
            out.append(amplitude * sin(phase))
            phase = (phase + step) % (2 * pi)
        yield out.tobytes()


def live_tone_chunks(settings: Callable[[], tuple[float, float]], chunk_size: int = 2_048):
    """Read new generator settings once per audio block."""
    phase = 0.0
    while True:
        hz, amplitude = settings()
        if not 0 <= hz <= 20_000 or not 0 <= amplitude <= 1:
            raise ValueError("Nieprawidłowa częstotliwość lub poziom generatora.")
        step = 2 * pi * hz / SAMPLE_RATE
        out = array("f")
        for _ in range(chunk_size):
            out.append(amplitude * sin(phase))
            phase = (phase + step) % (2 * pi)
        yield out.tobytes()


def _goertzel(samples: array, hz: int) -> float:
    coefficient = 2 * cos(2 * pi * hz / SAMPLE_RATE)
    previous = 0.0
    before_previous = 0.0
    for sample in samples:
        current = sample + coefficient * previous - before_previous
        before_previous, previous = previous, current
    return previous * previous + before_previous * before_previous - coefficient * previous * before_previous


class _BitParser:
    def __init__(self):
        self.recent = deque(maxlen=len(HEADER))
        self.pending: list[int] | None = None
        self.expected = 16

    def push(self, bit: int) -> bytes | None:
        if self.pending is None:
            self.recent.append(bit)
            if len(self.recent) == len(HEADER):
                candidate = list(self.recent)
                preamble_errors = sum(a != b for a, b in zip(candidate[:32], PREAMBLE))
                sync_errors = sum(a != b for a, b in zip(candidate[32:], SYNC))
                if preamble_errors <= 4 and sync_errors <= 1:
                    self.pending = []
                    self.expected = 16
                    self.recent.clear()
            return None

        self.pending.append(bit)
        if len(self.pending) == 16:
            length = _number(self.pending)
            if not 1 <= length <= MAX_TEXT_BYTES:
                self.pending = None
                return None
            self.expected = 16 + (length + 2) * 8
        if len(self.pending) < self.expected:
            return None
        length = _number(self.pending[:16])
        payload = bytes(_number(self.pending[16 + index * 8:24 + index * 8]) for index in range(length))
        checksum = _number(self.pending[-16:])
        self.pending = None
        if crc16(payload) == checksum:
            return payload
        return None


class FSKDecoder:
    """Incremental decoder tolerant of an unknown symbol boundary.

    Eight parallel timing offsets let the receiver start recording at any
    point in the audio stream. The CRC rejects false detections.
    """

    def __init__(self, config: ModemConfig):
        config.validate()
        self.config = config
        self.samples = array("f")
        self.base = 0
        self.symbol = config.samples_per_bit
        self.next_start = [round(phase * self.symbol / 8) for phase in range(8)]
        self.parsers = [_BitParser() for _ in range(8)]
        self.last_frames: deque[tuple[bytes, int]] = deque(maxlen=8)

    def feed(self, pcm: bytes) -> list[str]:
        incoming = array("f")
        incoming.frombytes(pcm)
        self.samples.extend(incoming)
        end = self.base + len(self.samples)
        found: list[str] = []
        for phase, parser in enumerate(self.parsers):
            while self.next_start[phase] + self.symbol <= end:
                start = self.next_start[phase] - self.base
                window = self.samples[start:start + self.symbol]
                power_zero = _goertzel(window, self.config.zero_hz)
                power_one = _goertzel(window, self.config.one_hz)
                bit = int(power_one > power_zero)
                self.next_start[phase] += self.symbol
                payload = parser.push(bit)
                if payload is None:
                    continue
                frame_end = self.next_start[phase]
                duplicate = any(
                    old_payload == payload and abs(frame_end - old_end) < 2 * self.symbol
                    for old_payload, old_end in self.last_frames
                )
                self.last_frames.append((payload, frame_end))
                if not duplicate:
                    try:
                        found.append(payload.decode("utf-8"))
                    except UnicodeDecodeError:
                        pass
        keep_from = min(self.next_start)
        discard = keep_from - self.base
        if discard > 0:
            del self.samples[:discard]
            self.base = keep_from
        return found
