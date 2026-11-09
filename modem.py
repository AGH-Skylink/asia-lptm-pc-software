"""Acoustic FSK modem shared by both applications.

The protocol is: alternating preamble, sync word, 128 known BER probe bits,
64-bit message ID, 16-bit byte count, payload, CRC-16/CCITT-FALSE. All integer
fields are sent most-significant bit first. The sample rate is fixed at both ends.
"""

from __future__ import annotations

from array import array
from collections import deque
from dataclasses import dataclass
from math import cos, isfinite, pi, sin
from typing import Callable

from ipc_reference import ID_BYTES


SAMPLE_RATE = 48_000
MAX_FREQUENCY = 23_900  # 24 kHz is the Nyquist limit, not a usable tone.
MAX_TEXT_BYTES = 2_048
PREAMBLE = tuple([1, 0] * 16)
SYNC = tuple((0xDDAA96F3 >> shift) & 1 for shift in range(31, -1, -1))
HEADER = PREAMBLE + SYNC
TEST_PAYLOAD = b"BER1" + bytes((index * 73 + 19) % 256 for index in range(128))
PROBE_BYTES = bytes((index * 97 + 43) % 256 for index in range(16))
PROBE = tuple((byte >> shift) & 1 for byte in PROBE_BYTES for shift in range(7, -1, -1))


@dataclass(frozen=True)
class ModemConfig:
    zero_hz: int = 1_200
    one_hz: int = 2_200
    baud: float = 25
    max_hz: int = MAX_FREQUENCY

    def validate(self) -> None:
        if not 100 <= self.max_hz <= MAX_FREQUENCY:
            raise ValueError(f"Górna granica pasma musi być w zakresie 100–{MAX_FREQUENCY} Hz.")
        if not (100 <= self.zero_hz <= self.max_hz):
            raise ValueError("Częstotliwość zera musi mieścić się w wybranym paśmie.")
        if not (100 <= self.one_hz <= self.max_hz):
            raise ValueError("Częstotliwość jedynki musi mieścić się w wybranym paśmie.")
        if not isfinite(self.baud) or not 5 <= self.baud <= 10_000:
            raise ValueError("Szybkość musi mieścić się w zakresie 5–10000 bitów/s.")
        if self.one_hz == self.zero_hz:
            raise ValueError("Częstotliwości 0 i 1 muszą być różne.")
        if abs(self.one_hz - self.zero_hz) < self.baud:
            raise ValueError("Przy tej szybkości częstotliwości 0 i 1 muszą różnić się co najmniej o liczbę bitów/s.")

    @property
    def samples_per_bit(self) -> int:
        return round(SAMPLE_RATE / self.baud)

    def symbol_boundary(self, index: int) -> int:
        """Rounded cumulative boundary avoids drift when samples/bit is fractional."""
        return round(index * SAMPLE_RATE / self.baud)


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


def encode_text(text: str, message_id: bytes | None = None) -> list[int]:
    payload = text.encode("utf-8")
    if not payload:
        raise ValueError("Wpisz tekst do wysłania.")
    if len(payload) > MAX_TEXT_BYTES:
        raise ValueError(f"Tekst może mieć najwyżej {MAX_TEXT_BYTES} bajtów UTF-8.")
    return encode_payload(payload, message_id)


def encode_payload(payload: bytes, message_id: bytes | None = None) -> list[int]:
    if not 1 <= len(payload) <= MAX_TEXT_BYTES:
        raise ValueError(f"Dane muszą mieć 1–{MAX_TEXT_BYTES} bajtów.")
    message_id = message_id if message_id is not None else bytes(ID_BYTES)
    if len(message_id) != ID_BYTES:
        raise ValueError("Identyfikator ramki musi mieć 8 bajtów.")
    frame = list(HEADER)
    frame += PROBE
    for byte in message_id:
        frame += _bits(byte, 8)
    frame += _bits(len(payload), 16)
    for byte in payload:
        frame += _bits(byte, 8)
    frame += _bits(crc16(message_id + payload), 16)
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
    total = config.symbol_boundary(len(bits))
    fade = min(round(SAMPLE_RATE * 0.01), 2 * config.samples_per_bit, max(1, total // 4))
    sample_index = 0
    for bit_index, bit in enumerate(bits):
        step = 2 * pi * (config.one_hz if bit else config.zero_hz) / SAMPLE_RATE
        count = config.symbol_boundary(bit_index + 1) - config.symbol_boundary(bit_index)
        for _ in range(count):
            envelope = min(1.0, (sample_index + 1) / fade, (total - sample_index) / fade)
            out.append(amplitude * envelope * sin(phase))
            phase = (phase + step) % (2 * pi)
            sample_index += 1
            if len(out) >= chunk_size:
                yield out.tobytes()
                out = array("f")
    if out:
        yield out.tobytes()
    # Give every timing offset enough samples to complete the final symbol.
    yield array("f", [0.0] * (4 * config.samples_per_bit)).tobytes()


def tone_chunks(hz: float, amplitude: float, chunk_size: int = 2_048):
    if not 0 <= hz <= MAX_FREQUENCY or not 0 <= amplitude <= 1:
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
        if not 0 <= hz <= MAX_FREQUENCY or not 0 <= amplitude <= 1:
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


@dataclass(frozen=True)
class DecodedFrame:
    message_id: bytes
    payload: bytes
    crc_ok: bool
    probe_errors: int
    probe_bits: int


def compare_test_bits(payload: bytes) -> tuple[int, int] | None:
    """Compare a received test payload, including a damaged marker, bit by bit."""
    if len(payload) != len(TEST_PAYLOAD):
        return None
    marker_errors = sum((left ^ right).bit_count() for left, right in zip(payload[:4], TEST_PAYLOAD[:4]))
    if marker_errors > 4:
        return None
    errors = sum((left ^ right).bit_count() for left, right in zip(payload[4:], TEST_PAYLOAD[4:]))
    return errors, (len(TEST_PAYLOAD) - 4) * 8


def compare_payload_bits(received: bytes, expected: bytes) -> tuple[int, int]:
    """Count wrong or missing bits against the local expected message."""
    errors = sum((left ^ right).bit_count() for left, right in zip(received, expected))
    errors += 8 * abs(len(received) - len(expected))
    return errors, 8 * max(len(received), len(expected))


class _BitParser:
    def __init__(self):
        self.recent = deque(maxlen=len(HEADER))
        self.pending: list[int] | None = None
        self.expected = len(PROBE) + ID_BYTES * 8 + 16

    def push(self, bit: int) -> DecodedFrame | None:
        if self.pending is None:
            self.recent.append(bit)
            if len(self.recent) == len(HEADER):
                candidate = list(self.recent)
                preamble_errors = sum(a != b for a, b in zip(candidate[:32], PREAMBLE))
                sync_errors = sum(a != b for a, b in zip(candidate[32:], SYNC))
                if preamble_errors <= 4 and sync_errors <= 1:
                    self.pending = []
                    self.expected = len(PROBE) + ID_BYTES * 8 + 16
                    self.recent.clear()
            return None

        self.pending.append(bit)
        length_start = len(PROBE) + ID_BYTES * 8
        if len(self.pending) == length_start + 16:
            length = _number(self.pending[length_start:length_start + 16])
            if not 1 <= length <= MAX_TEXT_BYTES:
                self.pending = None
                return None
            self.expected = length_start + 16 + (length + 2) * 8
        if len(self.pending) < self.expected:
            return None
        probe_errors = sum(a != b for a, b in zip(self.pending[:len(PROBE)], PROBE))
        message_id = bytes(_number(self.pending[len(PROBE) + index * 8:len(PROBE) + (index + 1) * 8])
                           for index in range(ID_BYTES))
        length = _number(self.pending[length_start:length_start + 16])
        data_start = length_start + 16
        payload = bytes(_number(self.pending[data_start + index * 8:data_start + (index + 1) * 8])
                        for index in range(length))
        checksum = _number(self.pending[-16:])
        self.pending = None
        return DecodedFrame(message_id, payload, crc16(message_id + payload) == checksum,
                            probe_errors, len(PROBE))


class FSKDecoder:
    """Incremental decoder tolerant of an unknown symbol boundary.

    Parallel timing offsets let the receiver start recording at any point in
    the audio stream. Invalid checksums are exposed for BER test frames.
    """

    def __init__(self, config: ModemConfig):
        config.validate()
        self.config = config
        self.samples = array("f")
        self.base = 0
        self.symbol = config.samples_per_bit
        offsets = sorted(set(round(phase * self.symbol / 8) for phase in range(8)))
        self.offsets = offsets
        self.symbol_indices = [0] * len(offsets)
        self.next_start = offsets.copy()
        self.parsers = [_BitParser() for _ in offsets]
        self.candidates: list[tuple[int, DecodedFrame]] = []
        self.last_frames: deque[tuple[bytes, int]] = deque(maxlen=16)

    def feed(self, pcm: bytes) -> list[str]:
        return [frame.payload.decode("utf-8") for frame in self.feed_frames(pcm)
                if frame.crc_ok and compare_test_bits(frame.payload) is None
                and _is_utf8(frame.payload)]

    def feed_frames(self, pcm: bytes) -> list[DecodedFrame]:
        incoming = array("f")
        incoming.frombytes(pcm)
        self.samples.extend(incoming)
        end = self.base + len(self.samples)
        found: list[DecodedFrame] = []
        for phase, parser in enumerate(self.parsers):
            while self.offsets[phase] + self.config.symbol_boundary(self.symbol_indices[phase] + 1) <= end:
                start = self.next_start[phase] - self.base
                frame_end = self.offsets[phase] + self.config.symbol_boundary(self.symbol_indices[phase] + 1)
                window = self.samples[start:frame_end - self.base]
                power_zero = _goertzel(window, self.config.zero_hz)
                power_one = _goertzel(window, self.config.one_hz)
                bit = int(power_one > power_zero)
                self.symbol_indices[phase] += 1
                self.next_start[phase] = frame_end
                payload = parser.push(bit)
                if payload is not None:
                    self.candidates.append((frame_end, payload))
        cutoff = min(self.next_start) - 2 * self.symbol
        ready = [candidate for candidate in self.candidates if candidate[0] <= cutoff]
        self.candidates = [candidate for candidate in self.candidates if candidate[0] > cutoff]
        while ready:
            frame_end, frame = ready.pop(0)
            group = [(frame_end, frame)]
            remaining = []
            for candidate in ready:
                (group if abs(candidate[0] - frame_end) < 2 * self.symbol else remaining).append(candidate)
            ready = remaining
            best = max(group, key=lambda item: (item[1].crc_ok, -item[1].probe_errors, -sum(
                (a ^ b).bit_count() for a, b in zip(item[1].payload, TEST_PAYLOAD)
            ) if len(item[1].payload) == len(TEST_PAYLOAD) else 0))
            if not any(old_payload == best[1].payload and abs(best[0] - old_end) < 2 * self.symbol
                       for old_payload, old_end in self.last_frames):
                self.last_frames.append((best[1].payload, best[0]))
                found.append(best[1])
        keep_from = min(self.next_start)
        discard = keep_from - self.base
        if discard > 0:
            del self.samples[:discard]
            self.base = keep_from
        return found


def _is_utf8(payload: bytes) -> bool:
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
