"""Windows-oriented acoustic transmitter GUI."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from queue import Empty
from secrets import token_bytes
from tkinter import filedialog, messagebox, ttk

from audio_runtime import OutputPlayer
from gui_common import DevicePicker, FSKFields
from ipc_control import CommandServer, TRANSMITTER_PORT
from ipc_reference import ID_BYTES, send_reference
from modem import MAX_FREQUENCY, TEST_PAYLOAD, encode_payload, fsk_chunks, live_tone_chunks


class Transmitter(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Nadajnik akustyczny")
        self.geometry("820x680")
        self.minsize(690, 560)
        self.player = OutputPlayer()
        self.control = CommandServer(TRANSMITTER_PORT)
        self.sweep_mode = False
        self.last_audio_error: str | None = None
        self.level = tk.IntVar(value=40)
        self.status = tk.StringVar(value="Gotowy.")
        self.text_source = tk.StringVar(value="field")
        self.text_path = tk.StringVar()
        self.audio_path = tk.StringVar()
        self.tone_hz = tk.IntVar(value=1_000)
        self.live_hz = 1_000
        self.live_level = 0.4
        self.tone_hz.trace_add("write", self._update_generator)
        self.level.trace_add("write", self._update_generator)

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        self.output = DevicePicker(body, "Wyjście dźwięku", "output")
        self.output.pack(fill="x", pady=(0, 12))

        level_box = ttk.LabelFrame(body, text="Poziom sygnału [%]")
        level_box.pack(fill="x", pady=(0, 12))
        tk.Scale(
            level_box, from_=0, to=100, orient="horizontal", variable=self.level,
        ).pack(fill="x", padx=8)
        ttk.Label(
            level_box, text="Wartość w woltach wymaga kalibracji karty dźwiękowej i wzmacniacza."
        ).pack(anchor="w", padx=8, pady=(0, 6))

        tabs = ttk.Notebook(body)
        tabs.pack(fill="both", expand=True)
        self._text_tab(tabs)
        self._generator_tab(tabs)
        self._audio_tab(tabs)

        footer = ttk.Frame(body)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Button(footer, text="Zatrzymaj dźwięk", command=self.stop).pack(side="right")
        ttk.Label(footer, textvariable=self.status, wraplength=620).pack(side="left", fill="x", expand=True)
        self.after(100, self._poll)
        try:
            self.control.start()
        except OSError as exc:
            self.status.set(f"Sterowanie pomiarami niedostępne: {exc}")
        for shortcut in ("<Control-Return>", "<Command-Return>"):
            self.bind_all(shortcut, self._send_text_shortcut)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _send_text_shortcut(self, _event) -> str:
        self.send_text()
        return "break"

    def _text_tab(self, tabs: ttk.Notebook) -> None:
        tab = ttk.Frame(tabs, padding=10)
        tabs.add(tab, text="Tekst FSK")
        self.fsk = FSKFields(tab)
        self.fsk.pack(fill="x", pady=(0, 10))
        source = ttk.Frame(tab)
        source.pack(fill="x")
        ttk.Radiobutton(source, text="Pole tekstowe", variable=self.text_source, value="field").pack(side="left")
        ttk.Radiobutton(source, text="Plik UTF-8", variable=self.text_source, value="file").pack(side="left", padx=12)
        ttk.Button(source, text="Wybierz plik", command=self._choose_text).pack(side="right")
        ttk.Entry(tab, textvariable=self.text_path).pack(fill="x", pady=(6, 8))
        self.text_input = tk.Text(tab, height=7, wrap="word")
        self.text_input.pack(fill="both", expand=True)
        self.text_input.insert("1.0", "Przykładowa wiadomość")
        buttons = ttk.Frame(tab)
        buttons.pack(anchor="e", pady=(10, 0))
        ttk.Button(buttons, text="Wyślij test BER", command=self.send_test).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Wyślij tekst", command=self.send_text).pack(side="left")

    def _generator_tab(self, tabs: ttk.Notebook) -> None:
        tab = ttk.Frame(tabs, padding=12)
        tabs.add(tab, text="Generator")
        ttk.Label(tab, text=f"Częstotliwość sinusa: 0–{MAX_FREQUENCY} Hz").pack(anchor="w")
        tk.Scale(
            tab, from_=0, to=MAX_FREQUENCY, resolution=10, orient="horizontal", variable=self.tone_hz,
        ).pack(fill="x", pady=(5, 16))
        ttk.Button(tab, text="Uruchom generator", command=self.start_tone).pack(anchor="e")

    def _audio_tab(self, tabs: ttk.Notebook) -> None:
        tab = ttk.Frame(tabs, padding=12)
        tabs.add(tab, text="Plik audio")
        ttk.Label(tab, text="Odtwarzanie pliku przez wybrane wyjście").pack(anchor="w", pady=(0, 8))
        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.audio_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Wybierz", command=self._choose_audio).pack(side="left", padx=(8, 0))
        ttk.Button(tab, text="Odtwórz", command=self.play_audio).pack(anchor="e", pady=(12, 0))

    def _choose_text(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Plik tekstowy", "*.txt"), ("Wszystkie", "*.*")])
        if path:
            self.text_path.set(path)
            self.text_source.set("file")

    def _choose_audio(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Pliki audio", "*.wav *.flac *.ogg *.mp3"), ("Wszystkie", "*.*")])
        if path:
            self.audio_path.set(path)

    def send_text(self) -> None:
        self.sweep_mode = False
        try:
            config = self.fsk.config()
            text = (
                Path(self.text_path.get()).read_text(encoding="utf-8")
                if self.text_source.get() == "file" else self.text_input.get("1.0", "end-1c")
            )
            if not text:
                raise ValueError("Wpisz tekst do wysłania.")
            self._transmit_text(text, config, self.output.selected(), self.level.get() / 100)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Nie można wysłać", str(exc))

    def _transmit_text(self, text: str, config, device: int, amplitude: float) -> dict:
        payload = text.encode("utf-8")
        message_id = token_bytes(ID_BYTES)
        bits = encode_payload(payload, message_id)
        reference_sent = send_reference(message_id, payload)
        seconds = len(bits) / config.baud
        self.player.play_chunks(fsk_chunks(bits, config, amplitude), device)
        reference_status = "wzorzec przekazany lokalnie" if reference_sent else "bez lokalnego BER"
        self.status.set(f"Wysyłanie FSK: {len(payload)} bajtów, około {seconds:.1f} s; {reference_status}.")
        return {"message_id": message_id.hex(), "reference_sent": reference_sent,
                "seconds": seconds}

    def _control_command(self, command: dict) -> dict:
        action = command.get("action")
        if action == "send":
            zero = int(command["zero_hz"])
            one = int(command["one_hz"])
            baud = float(command["speed_bps"])
            device = int(command["output_device"])
            amplitude = float(command["amplitude"])
            text = str(command["text"])
            if not 0 < amplitude <= 1:
                raise ValueError("Amplituda musi być w zakresie (0, 1].")
            self.fsk.zero.set(str(zero))
            self.fsk.one.set(str(one))
            self.fsk.baud.set(f"{baud:g}")
            self.fsk.max_hz.set(MAX_FREQUENCY)
            config = self.fsk.config()
            self.output.select(device)
            self.level.set(round(amplitude * 100))
            self.text_source.set("field")
            self.text_input.delete("1.0", "end")
            self.text_input.insert("1.0", text)
            self.sweep_mode = True
            self.last_audio_error = None
            return self._transmit_text(text, config, device, amplitude)
        if action == "status":
            return {"active": self.player.active, "status": self.status.get(),
                    "error": self.last_audio_error}
        raise ValueError("Nieznane polecenie nadajnika.")

    def send_test(self) -> None:
        self.sweep_mode = False
        try:
            config = self.fsk.config()
            device = self.output.selected()
            message_id = token_bytes(ID_BYTES)
            bits = encode_payload(TEST_PAYLOAD, message_id)
            reference_sent = send_reference(message_id, TEST_PAYLOAD)
            self.player.play_chunks(fsk_chunks(bits, config, self.level.get() / 100), device)
            reference_status = "wzorzec przekazany lokalnie" if reference_sent else "bez lokalnego wzorca"
            self.status.set(f"Wysyłanie testu BER: {len(TEST_PAYLOAD) - 4} bajtów danych, "
                            f"około {len(bits) / config.baud:.1f} s; {reference_status}.")
        except ValueError as exc:
            messagebox.showerror("Nie można wysłać testu", str(exc))

    def start_tone(self) -> None:
        self.sweep_mode = False
        try:
            device = self.output.selected()
            hz = self.tone_hz.get()
            self._update_generator()
            self.player.play_chunks(
                live_tone_chunks(lambda: (self.live_hz, self.live_level)), device
            )
            self.status.set(f"Generator: {hz} Hz. Zatrzymaj przyciskiem poniżej.")
        except ValueError as exc:
            messagebox.showerror("Nie można uruchomić generatora", str(exc))

    def _update_generator(self, *_args) -> None:
        self.live_hz = self.tone_hz.get()
        self.live_level = self.level.get() / 100

    def play_audio(self) -> None:
        self.sweep_mode = False
        try:
            self.player.play_file(self.audio_path.get(), self.output.selected(), self.level.get() / 100)
            self.status.set(f"Odtwarzanie: {Path(self.audio_path.get()).name}")
        except ValueError as exc:
            messagebox.showerror("Nie można odtworzyć", str(exc))

    def stop(self) -> None:
        self.player.stop()
        self.status.set("Zatrzymano.")

    def _poll(self) -> None:
        try:
            while True:
                command, response = self.control.incoming.get_nowait()
                try:
                    response.put(self._control_command(command))
                except Exception as exc:
                    response.put({"error": str(exc)})
        except Empty:
            pass
        try:
            while True:
                kind, message = self.player.events.get_nowait()
                self.status.set(message)
                if kind == "error":
                    self.last_audio_error = message
                    if not self.sweep_mode:
                        messagebox.showerror("Błąd audio", message)
        except Empty:
            pass
        self.after(100, self._poll)

    def _close(self) -> None:
        self.player.stop()
        self.control.stop()
        self.destroy()


if __name__ == "__main__":
    Transmitter().mainloop()
