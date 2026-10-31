"""Windows-oriented acoustic receiver GUI with live scope and monitoring."""

from __future__ import annotations

from array import array
from queue import Empty
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from audio_runtime import ReceiverAudio
from gui_common import DevicePicker, FSKFields
from modem import FSKDecoder


class Receiver(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Odbiornik akustyczny")
        self.geometry("840x760")
        self.minsize(690, 610)
        self.audio = ReceiverAudio()
        self.decoder: FSKDecoder | None = None
        self.status = tk.StringVar(value="Gotowy.")
        self.listen = tk.BooleanVar(value=False)
        self.latest = array("f")

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
        points = []
        for index in range(min(width, 500)):
            source_index = min(length - 1, index * length // min(width, 500))
            y = middle - max(-1, min(1, self.latest[source_index])) * (height * 0.44)
            points.extend((index * width / min(width, 500), y))
        if len(points) >= 4:
            self.scope.create_line(*points, fill="#52d6c7", width=2)

    def _poll(self) -> None:
        if self.decoder is not None:
            for _ in range(12):
                try:
                    chunk = self.audio.captured.get_nowait()
                except Empty:
                    break
                self.latest = array("f")
                self.latest.frombytes(chunk)
                for text in self.decoder.feed(chunk):
                    previous = self.result.get("1.0", "end-1c")
                    if previous and not previous.endswith("\n"):
                        self.result.insert("end", "\n")
                    self.result.insert("end", text)
                    self.result.see("end")
                    self.status.set(f"Odebrano wiadomość: {len(text.encode('utf-8'))} bajtów.")
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
