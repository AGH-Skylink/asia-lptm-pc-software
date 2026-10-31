"""Record exactly which audio endpoints the GUI will offer on this machine."""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path

import sounddevice as sd

from audio_runtime import devices
from modem import SAMPLE_RATE


def report() -> dict:
    raw_devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    checks = []
    for index, device in enumerate(raw_devices):
        item = {
            "index": index,
            "name": device["name"],
            "hostapi": hostapis[device["hostapi"]]["name"],
            "input_channels": device["max_input_channels"],
            "output_channels": device["max_output_channels"],
        }
        for direction, channel_key in (
            ("input", "input_channels"), ("output", "output_channels"),
        ):
            if item[channel_key]:
                try:
                    checker = sd.check_input_settings if direction == "input" else sd.check_output_settings
                    checker(device=index, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
                    item[f"{direction}_48k_float32"] = "ok"
                except Exception as exc:
                    item[f"{direction}_48k_float32"] = str(exc)
        checks.append(item)
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "portaudio": sd.get_portaudio_version()[1],
        "transmitter_outputs": devices("output"),
        "receiver_inputs": devices("input"),
        "devices": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="Save JSON report to this file")
    args = parser.parse_args()
    result = report()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
