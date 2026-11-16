"""Fixed voltage scale and sample-rate-aware time axis for the live scope."""
from array import array
import tkinter as tk
from tkinter import ttk


class ScopeView(ttk.Frame):
    def __init__(self, parent, gain_db, gain_label):
        super().__init__(parent)
        self.gain_db = gain_db
        self.gain_label = gain_label
        self.sample_rate = 48000
        self.samples = array("f")
        self.window_ms = tk.StringVar(value="20")
        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=5, pady=5)
        ttk.Label(controls, text="Okno czasu [ms]").pack(side="left")
        window = ttk.Combobox(controls, textvariable=self.window_ms, state="readonly",
                              values=("5", "10", "20", "50", "100"), width=6)
        window.pack(side="left", padx=6)
        window.bind("<<ComboboxSelected>>", lambda _event: self.draw())
        ttk.Label(controls, text="0,5 V/dz.").pack(side="right")
        self.canvas = tk.Canvas(self, width=360, height=235, bg="#101820", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=5, pady=5)
        self.canvas.bind("<Configure>", lambda _event: self.draw())
        ttk.Label(self, text="Założenie: PCM −1…+1 = −1…+1 V. Stała skala, bez normalizacji.",
                  wraplength=420).pack(anchor="w", padx=6, pady=(0, 5))

    def reset(self, sample_rate):
        self.sample_rate = sample_rate
        self.samples = array("f")
        self.draw()

    def feed(self, samples, sample_rate):
        if sample_rate != self.sample_rate:
            self.reset(sample_rate)
        self.samples.extend(samples)
        keep = round(sample_rate * .1)
        if len(self.samples) > keep:
            del self.samples[:-keep]

    def draw(self):
        canvas = self.canvas
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 130 or height < 100:
            return
        left, right, top, bottom = 54, width - 15, 25, height - 38
        plot_width, plot_height = right - left, bottom - top
        window_ms = float(self.window_ms.get())
        gain_db = self.gain_db.get()
        gain = 10 ** (gain_db / 20)
        self.gain_label.set(f"{gain_db:.0f} dB (×{gain:.1f})")
        canvas.create_text(left, 10, text="U [V]", fill="#cbd5df", anchor="w")
        canvas.create_text(right, height - 8, text="t [ms]", fill="#cbd5df", anchor="e")
        for division, voltage in enumerate((1, .5, 0, -.5, -1)):
            y = top + division * plot_height / 4
            canvas.create_line(left, y, right, y, fill="#607785" if voltage == 0 else "#304452")
            canvas.create_text(left - 8, y, text=f"{voltage:+g}" if voltage else "0",
                               fill="#cbd5df", anchor="e")
        for division in range(6):
            x = left + division * plot_width / 5
            canvas.create_line(x, top, x, bottom, fill="#304452")
            canvas.create_text(x, bottom + 13, text=f"{division * window_ms / 5:g}", fill="#cbd5df")
        count = max(1, round(self.sample_rate * window_ms / 1000))
        samples = self.samples[-count:]
        if not samples:
            return

        def y_of(value):
            return top + (1 - max(-1, min(1, value * gain))) * plot_height / 2

        # Preserve peaks when several audio samples fall within one screen pixel.
        points = []
        buckets = min(len(samples), max(1, int(plot_width)))
        padding = count - len(samples)
        for bucket in range(buckets):
            start = bucket * len(samples) // buckets
            end = (bucket + 1) * len(samples) // buckets
            x = left + (padding + start) * plot_width / count
            if end - start == 1:
                points.extend((x, y_of(samples[start])))
            else:
                section = samples[start:end]
                points.extend((x, y_of(min(section)), x, y_of(max(section))))
        if len(points) >= 4:
            canvas.create_line(*points, fill="#52d6c7", width=1)
        if any(abs(sample * gain) > 1 for sample in samples):
            canvas.create_text(right - 4, top + 5, text="Poza skalą ±1 V", anchor="ne", fill="#ffb36b")
