"""Shared Tk controls for devices and FSK settings."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import sounddevice as sd

from audio_runtime import devices
from modem import MAX_FREQUENCY, ModemConfig


class DevicePicker(ttk.Frame):
    def __init__(self, parent, title: str, direction: str):
        super().__init__(parent)
        self.direction = direction
        self.entries: list[tuple[int, str]] = []
        ttk.Label(self, text=title).pack(side="left", padx=(0, 8))
        self.combo = ttk.Combobox(self, width=58, state="readonly")
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
    def __init__(self, parent):
        super().__init__(parent, text="Modulacja: FSK")
        self.zero = tk.StringVar(value="1200")
        self.one = tk.StringVar(value="2200")
        self.baud = tk.StringVar(value="25")
        self.max_hz = tk.IntVar(value=MAX_FREQUENCY)

        fields = (
            ("Bit 0 [Hz]", self.zero),
            ("Bit 1 [Hz]", self.one),
            ("Szybkość [bit/s, maks. 10000]", self.baud),
        )
        for column, (label, variable) in enumerate(fields):
            ttk.Label(self, text=label).grid(row=0, column=column, sticky="w", padx=8, pady=(8, 0))
            ttk.Entry(self, textvariable=variable, width=14).grid(
                row=1, column=column, sticky="ew", padx=8, pady=(0, 8)
            )
            self.columnconfigure(column, weight=1)
        ttk.Label(self, text="Pasmo: 0 – górna granica [Hz], poniżej 24 kHz").grid(
            row=2, column=0, columnspan=3, sticky="w", padx=8
        )
        tk.Scale(
            self, from_=0, to=MAX_FREQUENCY, resolution=100, orient="horizontal",
            variable=self.max_hz, showvalue=True,
        ).grid(row=3, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 5))

    def config(self) -> ModemConfig:
        try:
            config = ModemConfig(
                zero_hz=int(self.zero.get()), one_hz=int(self.one.get()),
                baud=float(self.baud.get().replace(",", ".")), max_hz=self.max_hz.get(),
            )
        except ValueError as exc:
            raise ValueError("Częstotliwości muszą być liczbami całkowitymi, a szybkość liczbą.") from exc
        config.validate()
        return config
