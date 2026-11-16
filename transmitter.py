"""Windows-oriented acoustic transmitter GUI."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from secrets import token_bytes
from tkinter import filedialog, messagebox, ttk

from audio_runtime import OutputPlayer
from gui_common import DevicePicker, FSKFields
from ipc_control import CommandServer, TRANSMITTER_PORT
from ipc_reference import ID_BYTES, send_reference
from modem import MAX_FREQUENCY, TEST_PAYLOAD, encode_payload, live_tone_chunks
from transfers import file_packets, packet_audio
from text_encoding import ascii_text, convert_ascii_field


class Transmitter(ttk.Frame):
    def _build_transceiver_view(self, layout):
        receiver = layout["receiver"]
        self.fsk = receiver.fsk
        self.output = receiver.output
        self.auto_settings = receiver.auto_settings
        self.text_input = receiver.chat.compose
        files = ttk.LabelFrame(layout["files"], text="Wyślij plik / zdjęcie")
        files.pack(fill="x", before=receiver.file_box, pady=6)
        path_row = ttk.Frame(files)
        path_row.pack(fill="x", padx=8, pady=8)
        ttk.Entry(path_row, textvariable=self.binary_path).pack(side="left", fill="x", expand=True)
        ttk.Button(path_row, text="Wybierz JPG lub plik…", command=self._choose_binary).pack(side="right", padx=(6, 0))
        options = ttk.Frame(files)
        options.pack(fill="x", padx=8)
        ttk.Label(options, text="Powtórzenia bloków").pack(side="left")
        ttk.Combobox(options, textvariable=self.file_repeats, values=("1", "2", "3"), width=4,
                     state="readonly").pack(side="left", padx=6)
        ttk.Button(options, text="Wyślij plik", command=self.send_file).pack(side="right")
        ttk.Progressbar(files, variable=self.file_progress, maximum=100).pack(fill="x", padx=8, pady=8)
        ttk.Label(files, textvariable=self.file_detail, wraplength=640).pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(layout["transport"], text="Zatrzymaj nadawanie", command=self.stop).pack(side="right")
        extra = layout["advanced"]
        ttk.Separator(extra).pack(fill="x", pady=10)
        ttk.Label(extra, text="Generator i odtwarzanie audio").pack(anchor="w")
        ttk.Label(extra, text="Próbkowanie generatora [Hz]").pack(anchor="w", pady=(6, 0))
        rates = ttk.Combobox(extra, textvariable=self.generator_rate,
                             values=("48000", "96000", "192000"), state="readonly")
        rates.pack(fill="x")
        rates.bind("<<ComboboxSelected>>", self._generator_rate_changed)
        self.tone_scale = tk.Scale(extra, from_=0, to=MAX_FREQUENCY, resolution=10,
                                  orient="horizontal", variable=self.tone_hz)
        self.tone_scale.pack(fill="x")
        ttk.Button(extra, text="Uruchom generator", command=self.start_tone).pack(anchor="w", pady=4)
        ttk.Entry(extra, textvariable=self.audio_path).pack(fill="x")
        ttk.Button(extra, text="Wybierz audio", command=self._choose_audio).pack(anchor="w", pady=4)
        ttk.Button(extra, text="Odtwórz audio", command=self.play_audio).pack(anchor="w", pady=4)
        ttk.Button(extra, text="Wyślij test BER", command=self.send_test).pack(anchor="w", pady=4)
        ttk.Label(layout["status"], textvariable=self.status, wraplength=1200).pack(anchor="w")

    def _build_full_view(self):
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
        self._file_tab(tabs)
        self._generator_tab(tabs)
        self._audio_tab(tabs)

        footer = ttk.Frame(body)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Button(footer, text="Zatrzymaj dźwięk", command=self.stop).pack(side="right")
        ttk.Label(footer, textvariable=self.status, wraplength=620).pack(side="left", fill="x", expand=True)

    def __init__(self, parent=None, layout=None):
        self.owns_window = parent is None
        if parent is None:
            parent = tk.Tk()
        super().__init__(parent)
        self.window = self.winfo_toplevel()
        if self.owns_window:
            self.window.title("Nadajnik akustyczny")
            self.window.geometry("860x850")
            self.window.minsize(730, 800)
            self.pack(fill="both", expand=True)
        self.on_text_sent = None
        self.on_audio_event = None
        self.last_text_id = None
        self.player = OutputPlayer()
        self.control = CommandServer(TRANSMITTER_PORT)
        self.sweep_mode = False
        self.last_audio_error: str | None = None
        self.level = tk.IntVar(value=40)
        self.status = tk.StringVar(value="Gotowy.")
        self.text_source = tk.StringVar(value="field")
        self.text_path = tk.StringVar()
        self.audio_path = tk.StringVar()
        self.binary_path = tk.StringVar()
        self.file_repeats = tk.StringVar(value="2")
        self.file_progress = tk.DoubleVar(value=0)
        self.file_detail = tk.StringVar(value="JPG, PNG i inne pliki: przesyłanie oryginalnych bajtów, bez kodowania tekstowego.")
        self.file_updates = Queue()
        self.auto_settings = tk.BooleanVar(value=True)
        self.tone_hz = tk.IntVar(value=1_000)
        self.generator_rate = tk.StringVar(value="48000")
        self.live_hz = 1_000
        self.live_level = 0.4
        self.tone_hz.trace_add("write", self._update_generator)
        self.level.trace_add("write", self._update_generator)

        if layout is None:
            self._build_full_view()
        else:
            self._build_transceiver_view(layout)
        self.encoding_trace = self.fsk.encoding.trace_add("write", self._encoding_changed)
        self.poll_id = self.after(100, self._poll)
        try:
            self.control.start()
        except OSError as exc:
            self.status.set(f"Sterowanie pomiarami niedostępne: {exc}")
        for shortcut in ("<Control-Return>", "<Command-Return>"):
            if layout is None:
                self.text_input.bind(shortcut, self._send_text_shortcut)
        if self.owns_window:
            self.window.protocol("WM_DELETE_WINDOW", self._close)

    def _send_text_shortcut(self, _event) -> str:
        self.send_text()
        return "break"

    def _encoding_changed(self, *_args):
        if self.fsk.encoding.get() == "ascii" and convert_ascii_field(self.text_input):
            self.status.set("Tekst przekonwertowano na ASCII; znaki bez odpowiednika zastąpiono ?.")

    def _text_tab(self, tabs: ttk.Notebook) -> None:
        tab = ttk.Frame(tabs, padding=10)
        tabs.add(tab, text="Tekst / modulacja")
        self.fsk = FSKFields(tab)
        self.fsk.pack(fill="x", pady=(0, 10))
        ttk.Checkbutton(tab, text="Automatycznie ustaw odbiornik (zapowiedź przez audio)",
                        variable=self.auto_settings).pack(anchor="w")
        source = ttk.Frame(tab)
        source.pack(fill="x")
        ttk.Radiobutton(source, text="Pole tekstowe", variable=self.text_source, value="field").pack(side="left")
        ttk.Radiobutton(source, text="Plik tekstowy", variable=self.text_source, value="file").pack(side="left", padx=12)
        ttk.Button(source, text="Wybierz plik", command=self._choose_text).pack(side="right")
        ttk.Entry(tab, textvariable=self.text_path).pack(fill="x", pady=(6, 8))
        self.text_input = tk.Text(tab, height=7, wrap="word")
        self.text_input.pack(fill="both", expand=True)
        self.text_input.insert("1.0", "Przykładowa wiadomość")
        buttons = ttk.Frame(tab)
        buttons.pack(anchor="e", pady=(10, 0))
        ttk.Button(buttons, text="Wyślij test BER", command=self.send_test).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Wyślij tekst", command=self.send_text).pack(side="left")
        ttk.Label(tab, text="Pomiar z odbiornika używa wiadomości wybranej tutaj (plik lub pole tekstowe)."
                  ).pack(anchor="w", pady=(8, 0))

    def _generator_tab(self, tabs: ttk.Notebook) -> None:
        tab = ttk.Frame(tabs, padding=12)
        tabs.add(tab, text="Generator")
        ttk.Label(tab, text="Próbkowanie generatora [Hz] (wybierz przed uruchomieniem)").pack(anchor="w")
        rates = ttk.Combobox(tab, textvariable=self.generator_rate, values=("48000", "96000", "192000"), state="readonly")
        rates.pack(fill="x")
        rates.bind("<<ComboboxSelected>>", self._generator_rate_changed)
        ttk.Label(tab, text="Częstotliwość sinusa [Hz]").pack(anchor="w")
        self.tone_scale = tk.Scale(
            tab, from_=0, to=MAX_FREQUENCY, resolution=10, orient="horizontal", variable=self.tone_hz,
        )
        self.tone_scale.pack(fill="x", pady=(5, 16))
        ttk.Button(tab, text="Uruchom generator", command=self.start_tone).pack(anchor="e")

    def _generator_rate_changed(self, _event=None) -> None:
        self.stop()
        limit = min(48_000, int(self.generator_rate.get()) // 2 - 100)
        self.tone_hz.set(min(self.tone_hz.get(), limit))
        self.tone_scale.configure(to=limit)

    def _file_tab(self, tabs: ttk.Notebook) -> None:
        tab = ttk.Frame(tabs, padding=12)
        tabs.add(tab, text="Wyślij plik / zdjęcie")
        ttk.Label(tab, text="Przesyłanie pliku jako bajtów; ustawienia modulacji z zakładki Tekst.",
                  wraplength=650).pack(anchor="w", pady=8)
        ttk.Entry(tab, textvariable=self.binary_path).pack(fill="x", pady=8)
        ttk.Button(tab, text="Wybierz plik", command=self._choose_binary).pack(anchor="e")
        ttk.Button(tab, text="Wyślij plik", command=self.send_file).pack(anchor="e", pady=12)
        ttk.Label(tab, text="Odbiornik zapisuje nazwę z rozszerzeniem automatycznie w wybranym folderze.\n"
                  "Nagłówek + numerowane bloki + SHA-256. Błędny transfer pozostaje jako .part.",
                  wraplength=650).pack(anchor="w")

    def _choose_binary(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Zdjęcia JPEG", "*.jpg *.jpeg *.JPG *.JPEG"),
                                                     ("Obrazy", "*.png *.bmp *.gif *.webp"),
                                                     ("Wszystkie pliki", "*.*")])
        if path:
            self.binary_path.set(path)
            try:
                self._file_estimate()
            except (OSError, ValueError) as exc:
                self.file_detail.set(f"Wybrano plik. Sprawdź ustawienia transmisji: {exc}")

    def _file_estimate(self):
        path = Path(self.binary_path.get())
        size = path.stat().st_size
        repeats = int(self.file_repeats.get())
        rate = self.fsk.config().baud
        seconds = (size + ((size + 1023) // 1024 + 2) * 64 + 512) * 8 * repeats / rate
        self.file_detail.set(f"{path.name} · {size:,} B · około {seconds / 60:.1f} min przy {rate:g} bit/s "
                             f"i {repeats} powtórzeniach.")

    def _file_packets(self, path, repeats):
        total = path.stat().st_size
        sent = 0
        for packet in file_packets(path):
            for _ in range(repeats):
                yield packet
            if packet.startswith(b"LPTF2\x00D"):
                sent += len(packet) - 11
                self.file_updates.put((sent, total, f"Nadano {sent:,}/{total:,} B pliku {path.name}"))

    _packet_audio = staticmethod(packet_audio)

    def _prepare_output(self):
        if self.last_text_id is not None and self.on_audio_event is not None:
            self.on_audio_event(self.last_text_id, "Przerwano nadawanie" if self.player.active else "Nadano")
        self.last_text_id = None

    def send_file(self) -> None:
        self.sweep_mode = False
        try:
            path = Path(self.binary_path.get())
            if not path.is_file():
                raise ValueError("Wybierz istniejący plik.")
            if self.player.active:
                raise ValueError("Trwa nadawanie. Poczekaj lub zatrzymaj bieżącą transmisję.")
            config = self.fsk.config()
            repeats = int(self.file_repeats.get())
            if repeats not in (1, 2, 3):
                raise ValueError("Wybierz 1, 2 lub 3 powtórzenia.")
            with path.open("rb"):
                pass
            self._file_estimate()
            self.file_progress.set(0)
            seconds = path.stat().st_size * 8 / config.baud
            self._prepare_output()
            self.player.play_chunks(self._packet_audio(self._file_packets(path, repeats), config, token_bytes(ID_BYTES),
                self.level.get() / 100, self.auto_settings.get(), self.fsk.encoding.get()),
                self.output.selected(), config.sample_rate)
            self.status.set(f"Wysyłanie {path.name}: {path.stat().st_size} bajtów, co najmniej {seconds:.1f} s.")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Nie można wysłać pliku", str(exc))

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
            if self.text_source.get() == "file":
                if Path(self.text_path.get()).suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"):
                    self.binary_path.set(self.text_path.get())
                    self.send_file()
                    return
                try:
                    Path(self.text_path.get()).read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    self.binary_path.set(self.text_path.get())
                    self.send_file()
                    return
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
        if self.fsk.encoding.get() == "ascii":
            text = ascii_text(text)
        payload = text.encode(self.fsk.encoding.get())
        message_id = token_bytes(ID_BYTES)
        bits = encode_payload(payload, message_id)
        reference_sent = send_reference(message_id, payload)
        seconds = len(bits) / config.baud
        self._prepare_output()
        self.player.play_chunks(self._packet_audio([payload], config, message_id, amplitude,
            self.auto_settings.get() and not self.sweep_mode, self.fsk.encoding.get()), device, config.sample_rate)
        self.last_text_id = message_id
        if self.on_text_sent is not None:
            self.on_text_sent(message_id, text, len(payload))
        reference_status = "wzorzec przekazany lokalnie" if reference_sent else "bez lokalnego BER"
        self.status.set(f"Wysyłanie {config.modulation}: {len(payload)} bajtów, około {seconds:.1f} s; {reference_status}.")
        return {"message_id": message_id.hex(), "reference_sent": reference_sent,
                "seconds": seconds}

    def _control_command(self, command: dict) -> dict:
        action = command.get("action")
        if action == "measurement_message":
            text = (Path(self.text_path.get()).read_text(encoding="utf-8")
                    if self.text_source.get() == "file"
                    else self.text_input.get("1.0", "end-1c"))
            if not text:
                raise ValueError("Wybierz plik wiadomości lub wpisz tekst w nadajniku.")
            return {"text": text, "output_device": self.output.selected(),
                    "amplitude": self.level.get() / 100}
        if action == "stop":
            self.stop()
            return {"stopped": True}
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
            self.fsk.modulation.set(command.get("modulation", "2FSK"))
            self.fsk.sample_rate.set(str(command.get("sample_rate", 48000)))
            self.fsk._rate_changed()
            config = self.fsk.config()
            self.output.select(device)
            self.level.set(round(amplitude * 100))
            self.text_source.set("field")
            self.text_input.delete("1.0", "end")
            self.text_input.insert("1.0", text)
            self.sweep_mode = True
            self.fsk.encoding.set("utf-8")
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
            self._prepare_output()
            self.player.play_chunks(self._packet_audio([TEST_PAYLOAD], config, message_id,
                self.level.get() / 100, self.auto_settings.get(), self.fsk.encoding.get()), device, config.sample_rate)
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
            sample_rate = int(self.generator_rate.get())
            self._update_generator()
            self._prepare_output()
            self.player.play_chunks(
                live_tone_chunks(lambda: (self.live_hz, self.live_level), sample_rate=sample_rate),
                device, sample_rate,
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
            self._prepare_output()
            self.player.play_file(self.audio_path.get(), self.output.selected(), self.level.get() / 100)
            self.status.set(f"Odtwarzanie: {Path(self.audio_path.get()).name}")
        except ValueError as exc:
            messagebox.showerror("Nie można odtworzyć", str(exc))

    def stop(self) -> None:
        active = self.player.active
        self.player.stop()
        if self.last_text_id is not None and self.on_audio_event is not None:
            self.on_audio_event(self.last_text_id, "Przerwano nadawanie" if active else "Nadano")
        self.last_text_id = None
        self.status.set("Zatrzymano.")

    def _poll(self) -> None:
        try:
            while True:
                sent, total, detail = self.file_updates.get_nowait()
                self.file_progress.set(100 * sent / max(1, total))
                self.file_detail.set(detail)
        except Empty:
            pass
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
                if self.last_text_id is not None and self.on_audio_event is not None:
                    self.on_audio_event(self.last_text_id, "Błąd nadawania" if kind == "error" else "Nadano")
                self.last_text_id = None
                if kind == "error":
                    self.last_audio_error = message
                    if not self.sweep_mode:
                        messagebox.showerror("Błąd audio", message)
        except Empty:
            pass
        self.poll_id = self.after(100, self._poll)

    def shutdown(self) -> None:
        self.fsk.encoding.trace_remove("write", self.encoding_trace)
        self.after_cancel(self.poll_id)
        self.stop()
        self.control.stop()

    def _close(self) -> None:
        self.shutdown()
        self.destroy()
        if self.owns_window:
            self.window.destroy()


if __name__ == "__main__":
    Transmitter().mainloop()
