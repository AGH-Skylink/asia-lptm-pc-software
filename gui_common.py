"""Shared Tk controls for devices and FSK settings."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import sounddevice as sd

from audio_runtime import devices
from modem import MAX_FREQUENCY, ModemConfig


class ScrollableBody(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = ttk.Frame(self.canvas, padding=14)
        window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))


class DevicePicker(ttk.Frame):
    def __init__(self, parent, title: str, direction: str):
        super().__init__(parent)
        self.direction = direction
        self.entries: list[tuple[int, str]] = []
        self.value = tk.StringVar()
        ttk.Label(self, text=title).pack(side="left", padx=(0, 8))
        self.combo = ttk.Combobox(self, textvariable=self.value, width=58, state="readonly")
        self.combo.pack(side="left", fill="x", expand=True)
        ttk.Button(self, text="Odśwież", command=self.refresh).pack(side="left", padx=(8, 0))
        self.refresh()

    def refresh(self) -> None:
        old = self.combo.get()
        self.entries = devices(self.direction)
        self.combo["values"] = [name for _, name in self.entries]
        names = [name for _, name in self.entries]
        if old in names:
            self.combo.set(old)
            return
        if not self.entries:
            self.combo.set("")
            return
        default = sd.default.device[1 if self.direction == "output" else 0]
        selected = next((name for index, name in self.entries if index == default), self.entries[0][1])
        self.combo.set(selected)

    def selected(self) -> int:
        chosen = self.combo.get()
        for index, name in self.entries:
            if name == chosen:
                return index
        raise ValueError("Wybierz urządzenie audio.")

    def select(self, index: int) -> None:
        for device_index, name in self.entries:
            if device_index == index:
                self.combo.set(name)
                return
        raise ValueError(f"Urządzenie audio {index} nie jest dostępne.")


class FSKFields(ttk.LabelFrame):
    def __init__(self, parent, compact=False):
        super().__init__(parent, text="Modulacja")
        self.modulation = tk.StringVar(value="2FSK")
        self.sample_rate = tk.StringVar(value="48000")
        self.encoding = tk.StringVar(value="utf-8")
        self.zero = tk.StringVar(value="1200")
        self.one = tk.StringVar(value="2200")
        self.baud = tk.StringVar(value="25")
        self.max_hz = tk.IntVar(value=MAX_FREQUENCY)

        fields = (
            ("Dolna / bit 0 [Hz]", self.zero),
            ("Górna / bit 1 [Hz]", self.one),
            ("Bitrate [bit/s]" if compact else "Szybkość [bit/s, maks. 10000]", self.baud),
        )
        for column, (label, variable) in enumerate(fields):
            ttk.Label(self, text=label).grid(row=0, column=column, sticky="w", padx=8, pady=(8, 0))
            ttk.Entry(self, textvariable=variable, width=14).grid(
                row=1, column=column, sticky="ew", padx=8, pady=(0, 8)
            )
            self.columnconfigure(column, weight=1)
        ttk.Label(self, text="Pasmo: górna granica [Hz] (zależna od próbkowania)").grid(
            row=2, column=0, columnspan=3, sticky="w", padx=8
        )
        self.band_scale = tk.Scale(
            self, from_=0, to=MAX_FREQUENCY, resolution=100, orient="horizontal",
            variable=self.max_hz, showvalue=True,
        )
        self.band_scale.grid(row=3, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 5))
        ttk.Combobox(self, textvariable=self.modulation, values=("2FSK", "4FSK", "16QAM"),
                     state="readonly", width=12).grid(row=4, column=0, padx=8, sticky="ew")
        rates = ttk.Combobox(self, textvariable=self.sample_rate, values=("48000", "96000", "192000"),
                             state="readonly", width=12)
        rates.grid(row=4, column=1, padx=8, sticky="ew")
        rates.bind("<<ComboboxSelected>>", self._rate_changed)
        ttk.Button(self, text="Dobierz górną z bit/s", command=self._auto_upper).grid(row=4, column=2, padx=8)
        ttk.Label(self, text="4FSK: 4 równe tony, 2 bity/symbol. 16QAM: środek pasma, 4 bity/symbol.\n"
                  "Próbkowanie [Hz]: 48000 → pasmo 23,9 kHz; 192000 → pasmo 48 kHz.",
                  wraplength=420 if compact else 650).grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=6)
        self.details = tk.StringVar()
        ttk.Label(self, textvariable=self.details, wraplength=270 if compact else 430).grid(
            row=6, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))
        ttk.Button(self, text="Dobierz bit/s z pasma", command=self._auto_bitrate).grid(
            row=6, column=2, padx=8, pady=(0, 6))
        for variable in (self.zero, self.one, self.baud, self.modulation):
            variable.trace_add("write", self._update_details)
        self._update_details()
        ttk.Label(self, text="Kodowanie tekstu").grid(row=7, column=0, sticky="w", padx=8)
        ttk.Combobox(self, textvariable=self.encoding, values=("ascii", "utf-8"), state="readonly").grid(
            row=7, column=1, sticky="ew", padx=8, pady=(0, 6))

    def _update_details(self, *_args) -> None:
        try:
            config = ModemConfig(zero_hz=int(self.zero.get()), one_hz=int(self.one.get()),
                                 baud=float(self.baud.get().replace(",", ".")),
                                 modulation=self.modulation.get())
            if config.modulation == "16QAM":
                description = f"Nośna: {(config.zero_hz + config.one_hz) / 2:g} Hz"
            else:
                description = "Tony: " + ", ".join(f"{hz:g}" for hz in config.tones) + " Hz"
            self.details.set(f"{description}; {config.symbol_rate:g} symboli/s")
        except ValueError:
            self.details.set("Wpisz częstotliwości i bitrate.")

    def _auto_bitrate(self) -> None:
        from tkinter import messagebox
        try:
            span = int(self.one.get()) - int(self.zero.get())
            factor = {"2FSK": 1, "4FSK": 2 / 3, "16QAM": 4}[self.modulation.get()]
            bitrate = min(10_000, int(abs(span) * factor))
            if self.modulation.get() == "16QAM":
                bitrate = min(bitrate, 2 * int(self.zero.get()))
            if bitrate < 5 or (span < 0 and self.modulation.get() != "2FSK"):
                raise ValueError("Ustaw prawidłową dolną i górną częstotliwość.")
            self.baud.set(str(bitrate))
        except ValueError as exc:
            messagebox.showerror("Dobór bitratu", str(exc))

    def _rate_changed(self, _event=None) -> None:
        limit = min(48_000, int(self.sample_rate.get()) // 2 - 100)
        self.band_scale.configure(to=limit)
        self.max_hz.set(limit)

    def _auto_upper(self) -> None:
        from math import ceil
        from tkinter import messagebox
        try:
            baud = float(self.baud.get().replace(",", "."))
            factor = {"2FSK": 1, "4FSK": 1.5, "16QAM": 0.25}[self.modulation.get()]
            upper = int(self.zero.get()) + ceil(baud * factor)
            if upper > self.max_hz.get() or baud < 5:
                raise ValueError("Szybkość i dolna częstotliwość nie mieszczą się w wybranym paśmie.")
            self.one.set(str(upper))
        except (ValueError, OverflowError) as exc:
            messagebox.showerror("Dobór częstotliwości", str(exc))

    def config(self) -> ModemConfig:
        try:
            config = ModemConfig(
                zero_hz=int(self.zero.get()), one_hz=int(self.one.get()),
                baud=float(self.baud.get().replace(",", ".")), max_hz=self.max_hz.get(),
                modulation=self.modulation.get(), sample_rate=int(self.sample_rate.get()),
            )
        except ValueError as exc:
            raise ValueError("Częstotliwości muszą być liczbami całkowitymi, a szybkość liczbą.") from exc
        config.validate()
        return config
