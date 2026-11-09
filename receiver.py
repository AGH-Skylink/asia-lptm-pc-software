"""Windows-oriented acoustic receiver GUI with live scope and monitoring."""

from __future__ import annotations

from array import array
from math import log10, sqrt
from queue import Empty
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from audio_runtime import ReceiverAudio
from gui_common import DevicePicker, FSKFields
from modem import FSKDecoder, compare_test_bits


class Receiver(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Odbiornik akustyczny")
        self.geometry("840x820")
        self.minsize(690, 670)
        self.audio = ReceiverAudio()
        self.decoder: FSKDecoder | None = None
        self.status = tk.StringVar(value="Gotowy.")
        self.listen = tk.BooleanVar(value=False)
        self.latest = array("f")
        self.signal_label = tk.StringVar(value="Sygnał: cisza")
        self.scope_label = tk.StringVar(value="Wzmocnienie wykresu: —")
        self.ber_label = tk.StringVar(value="BER: — (wyślij test BER z nadajnika)")
        self.ber_errors = 0
        self.ber_bits = 0
        self.ber_frames = 0
        self.ber_crc_errors = 0

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        self.input = DevicePicker(body, "Mikrofon", "input")
        self.input.pack(fill="x", pady=(0, 8))
        self.output = DevicePicker(body, "Głośnik odsłuchu", "output")
        self.output.pack(fill="x", pady=(0, 10))
        self.fsk = FSKFields(body)
        self.fsk.pack(fill="x", pady=(0, 10))

        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=(0, 12))
        ttk.Checkbutton(
            controls, text="Odsłuch mikrofonu na głośniku", variable=self.listen,
        ).pack(side="left")
        self.start_button = ttk.Button(controls, text="Rozpocznij odbiór", command=self.start)
        self.start_button.pack(side="right")
        self.stop_button = ttk.Button(controls, text="Zatrzymaj", command=self.stop, state="disabled")
        self.stop_button.pack(side="right", padx=(0, 8))

        scope_box = ttk.LabelFrame(body, text="Oscyloskop: sygnał z mikrofonu")
        scope_box.pack(fill="x", pady=(0, 12))
        self.scope = tk.Canvas(scope_box, height=160, bg="#101820", highlightthickness=0)
        self.scope.pack(fill="x", padx=5, pady=5)
        meter = ttk.Frame(scope_box)
        meter.pack(fill="x", padx=7, pady=(0, 3))
        ttk.Label(meter, text="Siła sygnału").pack(side="left")
        self.signal_meter = ttk.Progressbar(meter, maximum=100, length=200)
        self.signal_meter.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(meter, textvariable=self.signal_label, width=32).pack(side="left")
        ttk.Label(scope_box, textvariable=self.scope_label).pack(anchor="w", padx=7, pady=(0, 6))

        ber_row = ttk.Frame(body)
        ber_row.pack(fill="x", pady=(0, 10))
        ttk.Label(ber_row, textvariable=self.ber_label).pack(side="left", fill="x", expand=True)
        ttk.Button(ber_row, text="Wyzeruj BER", command=self._reset_ber).pack(side="right")

        text_box = ttk.LabelFrame(body, text="Odebrany tekst")
        text_box.pack(fill="both", expand=True)
        self.result = tk.Text(text_box, wrap="word", height=8)
        self.result.pack(fill="both", expand=True, padx=5, pady=5)
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Zapisz tekst do pliku", command=self.save).pack(side="right")
        ttk.Button(actions, text="Wyczyść", command=lambda: self.result.delete("1.0", "end")).pack(
            side="right", padx=(0, 8)
        )
        ttk.Label(actions, textvariable=self.status, wraplength=560).pack(side="left", fill="x", expand=True)

        self.after(80, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def start(self) -> None:
        try:
            config = self.fsk.config()
            input_device = self.input.selected()
            output_device = self.output.selected() if self.listen.get() else None
            self.decoder = FSKDecoder(config)
            self.audio.start(input_device, output_device)
            self.status.set("Odbieranie FSK. Nadajnik musi mieć te same ustawienia 0, 1 i bit/s.")
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
        except Exception as exc:
            self.decoder = None
            messagebox.showerror("Nie można rozpocząć odbioru", str(exc))

    def stop(self) -> None:
        self.audio.stop()
        self.decoder = None
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status.set("Zatrzymano.")

    def _reset_ber(self) -> None:
        self.ber_errors = self.ber_bits = self.ber_frames = self.ber_crc_errors = 0
        self.ber_label.set("BER: — (wyślij test BER z nadajnika)")

    def save(self) -> None:
        text = self.result.get("1.0", "end-1c")
        if not text:
            messagebox.showinfo("Zapis", "Nie ma jeszcze odebranego tekstu.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Plik tekstowy", "*.txt"), ("Wszystkie", "*.*")]
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as target:
                    target.write(text)
                self.status.set(f"Zapisano: {path}")
            except OSError as exc:
                messagebox.showerror("Nie można zapisać", str(exc))

    def _draw_scope(self) -> None:
        self.scope.delete("all")
        width = max(1, self.scope.winfo_width())
        height = max(1, self.scope.winfo_height())
        middle = height / 2
        self.scope.create_line(0, middle, width, middle, fill="#3c5660")
        if not self.latest:
            return
        length = len(self.latest)
        peak = max(abs(sample) for sample in self.latest)
        scale = peak if peak >= 1e-5 else 1.0
        self.scope_label.set(f"Wzmocnienie wykresu: ×{1 / scale:.1f} (szczyt {peak:.4f} FS)")
        points = []
        for index in range(min(width, 500)):
            source_index = min(length - 1, index * length // min(width, 500))
            y = middle - self.latest[source_index] / scale * (height * 0.44)
            points.extend((index * width / min(width, 500), y))
        if len(points) >= 4:
            self.scope.create_line(*points, fill="#52d6c7", width=2)

    def _update_signal(self) -> None:
        if not self.latest:
            return
        peak = max(abs(sample) for sample in self.latest)
        rms = sqrt(sum(sample * sample for sample in self.latest) / len(self.latest))
        self.signal_meter["value"] = min(100, peak * 100)
        peak_db = 20 * log10(peak) if peak > 0 else float("-inf")
        rms_db = 20 * log10(rms) if rms > 0 else float("-inf")
        self.signal_label.set(f"szczyt {peak_db:.1f} dBFS · RMS {rms_db:.1f} dBFS")

    def _poll(self) -> None:
        if self.decoder is not None:
            for _ in range(12):
                try:
                    chunk = self.audio.captured.get_nowait()
                except Empty:
                    break
                self.latest = array("f")
                self.latest.frombytes(chunk)
                for frame in self.decoder.feed_frames(chunk):
                    test = compare_test_bits(frame.payload)
                    if test is not None:
                        errors, bits = test
                        self.ber_errors += errors
                        self.ber_bits += bits
                        self.ber_frames += 1
                        self.ber_crc_errors += not frame.crc_ok
                        self.ber_label.set(
                            f"BER: {self.ber_errors / self.ber_bits:.6%} "
                            f"({self.ber_errors}/{self.ber_bits} bitów, "
                            f"{self.ber_frames} ramek, CRC błędne: {self.ber_crc_errors})"
                        )
                        self.status.set("Odebrano ramkę testową BER.")
                    elif frame.crc_ok:
                        try:
                            text = frame.payload.decode("utf-8")
                        except UnicodeDecodeError:
                            continue
                        previous = self.result.get("1.0", "end-1c")
                        if previous and not previous.endswith("\n"):
                            self.result.insert("end", "\n")
                        self.result.insert("end", text)
                        self.result.see("end")
                        self.status.set(f"Odebrano wiadomość: {len(frame.payload)} bajtów.")
            self._update_signal()
            self._draw_scope()
        try:
            while True:
                error = self.audio.errors.get_nowait()
                self.status.set(error)
        except Empty:
            pass
        self.after(80, self._poll)

    def _close(self) -> None:
        self.audio.stop()
        self.destroy()


if __name__ == "__main__":
    Receiver().mainloop()
