"""Decode a Windows/QEMU WAV capture with the same modem as the receiver."""

from __future__ import annotations

import argparse
from array import array
import json
from math import floor
from pathlib import Path
import shutil
import struct
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modem import FSKDecoder, ModemConfig, SAMPLE_RATE  # noqa: E402


def readable_wav(path: Path) -> Path:
    """Repair the zero RIFF lengths written by some QEMU WAV backends."""
    with path.open("rb") as source:
        header = source.read(44)
    if len(header) < 44 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise ValueError("Not a WAV capture")
    if struct.unpack_from("<I", header, 4)[0] or struct.unpack_from("<I", header, 40)[0]:
        return path
    if header[36:40] != b"data":
        raise ValueError("Unsupported WAV layout")
    result = path.with_name(f"{path.stem}-fixed.wav")
    with path.open("rb") as source, result.open("wb") as target:
        shutil.copyfileobj(source, target)
    with result.open("r+b") as target:
        size = result.stat().st_size
        target.seek(4)
        target.write(struct.pack("<I", size - 8))
        target.seek(40)
        target.write(struct.pack("<I", size - 44))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=Path(__file__).with_name("guest-output.wav"))
    parser.add_argument("--zero", type=int, default=1200)
    parser.add_argument("--one", type=int, default=2200)
    parser.add_argument("--baud", type=int, default=25)
    args = parser.parse_args()

    decoder = FSKDecoder(ModemConfig(args.zero, args.one, args.baud))
    decoded: list[str] = []
    source_index = 0
    next_output = 0
    last_sample: float | None = None
    peak = 0.0
    readable = readable_wav(args.path)
    with sf.SoundFile(readable) as source:
        for block in source.blocks(blocksize=44_100, dtype="float32", always_2d=True):
            mono = block.mean(axis=1)
            if not len(mono):
                continue
            peak = max(peak, float(np.max(np.abs(mono))))
            if last_sample is not None:
                samples = np.concatenate(([last_sample], mono))
                first = source_index - 1
            else:
                samples = mono
                first = source_index
            last = source_index + len(mono) - 1
            final_output = floor(last * SAMPLE_RATE / source.samplerate)
            if final_output >= next_output:
                positions = np.arange(next_output, final_output + 1) * source.samplerate / SAMPLE_RATE
                resampled = np.interp(positions, np.arange(first, last + 1), samples).astype("float32")
                decoded.extend(decoder.feed(resampled.tobytes()))
                next_output = final_output + 1
            source_index += len(mono)
            last_sample = float(mono[-1])
        decoded.extend(decoder.feed(array("f", [0.0] * decoder.symbol).tobytes()))
        result = {
            "path": str(readable),
            "source_samplerate": source.samplerate,
            "channels": source.channels,
            "duration_seconds": source.frames / source.samplerate,
            "peak": peak,
            "decoded_messages": decoded,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
