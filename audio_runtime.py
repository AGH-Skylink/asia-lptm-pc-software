"""PortAudio adapters. Device access is kept outside the modem and UI."""

from __future__ import annotations

from array import array
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import Callable, Iterable

import sounddevice as sd

from modem import SAMPLE_RATE


def devices(direction: str) -> list[tuple[int, str]]:
    key = "max_output_channels" if direction == "output" else "max_input_channels"
    check = sd.check_output_settings if direction == "output" else sd.check_input_settings
    hostapis = sd.query_hostapis()
    available = []
    for index, device in enumerate(sd.query_devices()):
        if device[key] < 1:
            continue
        # PortAudio's Windows WDM-KS backend does not implement blocking output,
        # which is what OutputPlayer and the receiver's monitor use.
        if direction == "output" and hostapis[device["hostapi"]]["name"] == "Windows WDM-KS":
            continue
        try:
            check(device=index, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
        except sd.PortAudioError:
            continue
        available.append((index, f"{index}: {device['name']}"))
    return available


def scale_pcm(chunk: bytes, level: float) -> bytes:
    if level == 1:
        return chunk
    samples = array("f")
    samples.frombytes(chunk)
    for index in range(len(samples)):
        samples[index] *= level
    return samples.tobytes()


class OutputPlayer:
    def __init__(self):
        self.stop_event = Event()
        self.thread: Thread | None = None
        self.events: Queue[tuple[str, str]] = Queue()

    @property
    def active(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

    def _start(self, work: Callable[[Event], None]) -> None:
        self.stop()
        while True:
            try:
                self.events.get_nowait()
            except Empty:
                break
        stop_event = Event()
        self.stop_event = stop_event

        def runner() -> None:
            try:
                work(stop_event)
                self.events.put(("done", "Zatrzymano." if stop_event.is_set() else "Zakończono."))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        self.thread = Thread(target=runner, daemon=True)
        self.thread.start()

    def play_chunks(self, chunks: Iterable[bytes], output_device: int) -> None:
        def work(stop_event: Event) -> None:
            with sd.RawOutputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=output_device,
                blocksize=0, latency="high",
            ) as stream:
                for chunk in chunks:
                    if stop_event.is_set():
                        break
                    stream.write(chunk)

        self._start(work)

    def play_file(self, path: str, output_device: int, level: float) -> None:
        def work(stop_event: Event) -> None:
            import soundfile as sf

            with sf.SoundFile(path) as source:
                info = sd.query_devices(output_device, "output")
                if source.channels > info["max_output_channels"]:
                    raise ValueError("Wybrane wyjście ma za mało kanałów dla tego pliku.")
                with sd.RawOutputStream(
                    samplerate=source.samplerate, channels=source.channels,
                    dtype="float32", device=output_device, blocksize=0, latency="high",
                ) as stream:
                    while not stop_event.is_set():
                        chunk = source.buffer_read(2_048, dtype="float32")
                        if not chunk:
                            break
                        stream.write(scale_pcm(chunk, level))

        if not Path(path).is_file():
            raise ValueError("Wybierz istniejący plik audio.")
        self._start(work)


class ReceiverAudio:
    def __init__(self):
        self.captured: Queue[bytes] = Queue(maxsize=48)
        self.monitor: Queue[bytes] = Queue(maxsize=4)
        self.errors: Queue[str] = Queue()
        self.monitor_stop = Event()
        self.monitor_thread: Thread | None = None
        self.input_stream = None

    @property
    def active(self) -> bool:
        return self.input_stream is not None

    def start(self, input_device: int, output_device: int | None = None) -> None:
        self.stop()
        monitor_stop = Event()
        self.monitor_stop = monitor_stop

        if output_device is not None:
            def monitor_work() -> None:
                try:
                    with sd.RawOutputStream(
                        samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        device=output_device, blocksize=0, latency="high",
                    ) as stream:
                        while not monitor_stop.is_set():
                            try:
                                chunk = self.monitor.get(timeout=0.1)
                            except Empty:
                                continue
                            stream.write(chunk)
                except Exception as exc:
                    self.errors.put(f"Odsłuch: {exc}")

            self.monitor_thread = Thread(target=monitor_work, daemon=True)
            self.monitor_thread.start()

        def callback(indata, frames, time_info, status) -> None:
            if status:
                self.errors.put(str(status))
            chunk = bytes(indata)
            for target in (self.captured, self.monitor) if output_device is not None else (self.captured,):
                try:
                    target.put_nowait(chunk)
                except Full:
                    try:
                        target.get_nowait()
                        target.put_nowait(chunk)
                    except (Empty, Full):
                        pass

        try:
            self.input_stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=input_device,
                blocksize=2_048, callback=callback, latency="high",
            )
            self.input_stream.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if self.input_stream is not None:
            stream = self.input_stream
            self.input_stream = None
            try:
                stream.stop()
            finally:
                stream.close()
        self.monitor_stop.set()
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2)
        self.monitor_thread = None
        for target in (self.captured, self.monitor):
            while True:
                try:
                    target.get_nowait()
                except Empty:
                    break
