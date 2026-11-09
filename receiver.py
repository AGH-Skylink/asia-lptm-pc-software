"""Windows-oriented acoustic receiver GUI with live scope and monitoring."""

from __future__ import annotations

from array import array
from collections import OrderedDict
from math import log10
from queue import Empty
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from audio_runtime import HighPass, ReceiverAudio, ac_metrics
from gui_common import DevicePicker, FSKFields
from ipc_reference import ReferenceServer
from modem import FSKDecoder, compare_payload_bits, compare_test_bits


class Receiver(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Odbiornik akustyczny")
        self.geometry("840x790")
        self.minsize(690, 700)
        self.audio = ReceiverAudio()
        self.decoder: FSKDecoder | None = None
        self.status = tk.StringVar(value="Gotowy.")
        self.listen = tk.BooleanVar(value=False)
        self.latest = array("f")
        self.scope_filter = HighPass(400)
        self.signal_label = tk.StringVar(value="Sygnał: cisza")
        self.scope_label = tk.StringVar(value="Wzmocnienie wykresu: —")
        self.ber_label = tk.StringVar(value="BER: — (po pierwszej odebranej ramce)")
        self.data_ber_label = tk.StringVar(value="BER danych: — (czekam na lokalny wzorzec)")
        self.ber_errors = 0
        self.ber_bits = 0
        self.ber_frames = 0
        self.ber_crc_errors = 0
        self.scope_noise_floor = 0.0001
        self.reference_server = ReferenceServer()
        self.references: OrderedDict[bytes, bytes] = OrderedDict()

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
        self.scope = tk.Canvas(scope_box, height=90, bg="#101820", highlightthickness=0)
        self.scope.pack(fill="x", padx=5, pady=5)
        meter = ttk.Frame(scope_box)
        meter.pack(fill="x", padx=7, pady=(0, 3))
        ttk.Label(meter, text="Siła sygnału").pack(side="left")
        self.signal_meter = ttk.Progressbar(meter, maximum=90, length=200)
        self.signal_meter.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(meter, textvariable=self.signal_label, width=32).pack(side="left")
        ttk.Label(scope_box, textvariable=self.scope_label).pack(anchor="w", padx=7, pady=(0, 6))

        ber_row = ttk.Frame(body)
        ber_row.pack(fill="x", pady=(0, 10))
        ttk.Label(ber_row, textvariable=self.ber_label).pack(side="left", fill="x", expand=True)
        ttk.Button(ber_row, text="Wyzeruj BER", command=self._reset_ber).pack(side="right")
        ttk.Label(body, textvariable=self.data_ber_label).pack(anchor="w", pady=(0, 8))

        expected_box = ttk.LabelFrame(body, text="Wysłano (lokalny wzorzec do porównania)")
        expected_box.pack(fill="x", pady=(0, 10))
        self.expected = tk.Text(expected_box, wrap="word", height=1, state="disabled")
        self.expected.pack(fill="x", padx=5, pady=5)

        text_box = ttk.LabelFrame(body, text="Odebrany tekst")
        text_box.pack(fill="both", expand=True)
        self.result = tk.Text(text_box, wrap="word", height=4)
        self.result.pack(fill="both", expand=True, padx=5, pady=5)
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Zapisz tekst do pliku", command=self.save).pack(side="right")
        ttk.Button(actions, text="Wyczyść", command=lambda: self.result.delete("1.0", "end")).pack(
            side="right", padx=(0, 8)
        )
        ttk.Label(actions, textvariable=self.status, wraplength=560).pack(side="left", fill="x", expand=True)

        try:
            self.reference_server.start()
        except OSError as exc:
            self.status.set(f"Lokalny kanał wzorca niedostępny: {exc}")
        self.after(80, self._poll)
        for shortcut in ("<Control-r>", "<Command-r>"):
            self.bind_all(shortcut, self._toggle_receive)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _toggle_receive(self, _event) -> str:
        if self.decoder is None:
            self.start()
        else:
            self.stop()
        return "break"

    def start(self) -> None:
        try:
            config = self.fsk.config()
            input_device = self.input.selected()
            output_device = self.output.selected() if self.listen.get() else None
            self.decoder = FSKDecoder(config)
            cutoff = max(20, min(500, min(config.zero_hz, config.one_hz) / 3))
            self.scope_filter = HighPass(cutoff)
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
        self.ber_label.set("BER: — (po pierwszej odebranej ramce)")
        self.data_ber_label.set("BER danych: — (czekam na lokalny wzorzec)")

    def _show_expected(self, payload: bytes | None) -> None:
        if payload is None:
            text = "—"
        else:
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                text = f"<ramka testowa BER: {len(payload)} bajtów>"
        self.expected.configure(state="normal")
        self.expected.delete("1.0", "end")
        self.expected.insert("1.0", text)
        self.expected.configure(state="disabled")

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
        offset, _, rms = ac_metrics(self.latest)
        threshold = max(0.00015, 3 * self.scope_noise_floor)
        if rms < threshold:
            self.scope_noise_floor = 0.98 * self.scope_noise_floor + 0.02 * rms
            self.scope_label.set(f"Szum tła ukryty (RMS {rms:.5f} FS)")
            return
        scale = max(1.6 * rms, 1e-5)
        self.scope_label.set(f"Wzmocnienie wykresu AC: ×{1 / scale:.1f} (RMS {rms:.4f} FS)")
        points = []
        for index in range(min(width, 500)):
            source_index = min(length - 1, index * length // min(width, 500))
            normalized = max(-1.0, min(1.0, (self.latest[source_index] - offset) / scale))
            y = middle - normalized * (height * 0.44)
            points.extend((index * width / min(width, 500), y))
        if len(points) >= 4:
            self.scope.create_line(*points, fill="#52d6c7", width=2)

    def _update_signal(self) -> None:
        if not self.latest:
            return
        _, peak, rms = ac_metrics(self.latest)
        peak_db = 20 * log10(peak) if peak > 0 else float("-inf")
        rms_db = 20 * log10(rms) if rms > 0 else float("-inf")
        self.signal_meter["value"] = max(0, min(90, peak_db + 90))
        self.signal_label.set(f"AC: szczyt {peak_db:.1f} · RMS {rms_db:.1f} dBFS")

    def _poll(self) -> None:
        try:
            while True:
                message_id, expected = self.reference_server.incoming.get_nowait()
                self.references[message_id] = expected
                if len(self.references) > 32:
                    self.references.popitem(last=False)
                self._show_expected(expected)
                self.result.delete("1.0", "end")
                self.data_ber_label.set("BER danych: oczekiwanie na ramkę audio")
                self.status.set(f"Nadajnik zgłosił lokalnie {len(expected)} bajtów; trwa odbiór audio.")
        except Empty:
            pass
        if self.decoder is not None:
            for _ in range(12):
                try:
                    chunk = self.audio.captured.get_nowait()
                except Empty:
                    break
                raw = array("f")
                raw.frombytes(chunk)
                self.latest = self.scope_filter.process(raw)
                for frame in self.decoder.feed_frames(chunk):
                    # Each received frame replaces the previous result, including
                    # frames that fail CRC, so stale text cannot look newly received.
                    self.result.delete("1.0", "end")
                    self.ber_errors += frame.probe_errors
                    self.ber_bits += frame.probe_bits
                    self.ber_frames += 1
                    self.ber_crc_errors += not frame.crc_ok
                    expected = self.references.pop(frame.message_id, None)
                    if expected is not None:
                        errors, bits = compare_payload_bits(frame.payload, expected)
                        self._show_expected(expected)
                        self.data_ber_label.set(
                            f"BER danych ostatniej ramki: {errors / bits:.6%} ({errors}/{bits} bitów)"
                        )
                    else:
                        self._show_expected(None)
                        self.data_ber_label.set("BER danych: brak lokalnego wzorca dla tej ramki")
                    test = compare_test_bits(frame.payload)
                    if test is not None:
                        errors, bits = test
                        self.ber_errors += errors
                        self.ber_bits += bits
                        self.status.set("Odebrano ramkę testową BER.")
                    elif frame.crc_ok:
                        try:
                            text = frame.payload.decode("utf-8")
                        except UnicodeDecodeError:
                            self.status.set("Ramka ma poprawne CRC, ale nie zawiera tekstu UTF-8.")
                        else:
                            self.result.insert("1.0", text)
                            self.status.set(f"Odebrano wiadomość: {len(frame.payload)} bajtów.")
                    else:
                        self.status.set("Ramka odebrana z błędnym CRC; tekst pominięty.")
                    self.ber_label.set(
                        f"BER wzorca: {self.ber_errors / self.ber_bits:.6%} "
                        f"({self.ber_errors}/{self.ber_bits} bitów, "
                        f"{self.ber_frames} ramek, CRC błędne: {self.ber_crc_errors})"
                    )
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
        self.reference_server.stop()
        self.destroy()


if __name__ == "__main__":
    Receiver().mainloop()
