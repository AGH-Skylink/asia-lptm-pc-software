"""One-window acoustic transceiver using the standalone TX and RX panels."""
import tkinter as tk
from tkinter import ttk

from receiver import Receiver
from transmitter import Transmitter
from gui_common import ScrollableBody


class VariableLinks:
    """Keep visible TX/RX settings in sync without recursive Tk traces."""
    def __init__(self):
        self.busy = False
        self.traces = []

    def link(self, first, second, changed=None):
        if first is second:
            return
        def copy(source, target):
            if self.busy:
                return
            self.busy = True
            try:
                target.set(source.get())
                if changed is not None:
                    changed()
            finally:
                self.busy = False

        second.set(first.get())
        for source, target in ((first, second), (second, first)):
            token = source.trace_add("write", lambda *_args, s=source, t=target: copy(s, t))
            self.traces.append((source, token))

    def close(self):
        for variable, token in self.traces:
            variable.trace_remove("write", token)
        self.traces.clear()


class Transceiver(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Transceiver akustyczny — czat, pliki, nadawanie i odbiór")
        self.geometry("1320x940")
        self.minsize(1180, 760)
        devices = ttk.Frame(self, padding=(12, 10))
        devices.pack(fill="x")
        transport = ttk.Frame(self, padding=(12, 0, 12, 8))
        transport.pack(fill="x")
        status = ttk.Frame(self, padding=(12, 6))
        status.pack(side="bottom", fill="x")
        columns = ttk.Frame(self)
        columns.pack(fill="both", expand=True, padx=10)
        columns.columnconfigure(0, weight=1, uniform="main")
        columns.columnconfigure(1, weight=1, uniform="main")
        columns.rowconfigure(0, weight=1)
        left = ttk.Frame(columns)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right_scroll = ScrollableBody(columns)
        right_scroll.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right = right_scroll.content
        chat = ttk.Frame(left)
        chat.pack(fill="both", expand=True)
        files = ttk.Frame(left)
        files.pack(fill="x", pady=(6, 0))
        scope = ttk.Frame(right)
        scope.pack(fill="x")
        settings = ttk.Frame(right)
        settings.pack(fill="x")
        advanced = ttk.LabelFrame(right, text="Narzędzia dodatkowe")
        def toggle_advanced():
            if advanced.winfo_manager():
                advanced.pack_forget()
            else:
                advanced.pack(fill="x", pady=6)
        ttk.Button(right, text="Narzędzia dodatkowe: generator, audio, pomiary…",
                   command=toggle_advanced).pack(fill="x", pady=6)
        layout = dict(devices=devices, transport=transport, status=status, chat=chat,
                      files=files, scope=scope, settings=settings, advanced=advanced)
        self.receiver = Receiver(self, layout=layout)
        layout["receiver"] = self.receiver
        self.transmitter = Transmitter(self, layout=layout)
        self.receiver.fsk.baud.set("500")

        self.links = VariableLinks()
        for name in ("zero", "one", "baud", "modulation", "sample_rate", "max_hz", "encoding"):
            self.links.link(getattr(self.receiver.fsk, name), getattr(self.transmitter.fsk, name),
                            self._sync_band_scales if name == "sample_rate" else None)
        self.links.link(self.receiver.chat_level, self.transmitter.level)
        self.links.link(self.receiver.auto_settings, self.transmitter.auto_settings)
        self.links.link(self.receiver.output.value, self.transmitter.output.value)
        self.receiver.chat_send_handler = self._send_chat
        self.receiver.chat_stop_handler = self.transmitter.stop
        self.transmitter.on_text_sent = self.receiver.chat.sent
        self.transmitter.on_audio_event = self.receiver.chat.sent_status
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _sync_band_scales(self):
        for fields in (self.receiver.fsk, self.transmitter.fsk):
            fields.band_scale.configure(to=min(48000, int(fields.sample_rate.get()) // 2 - 100))

    def _send_chat(self, text):
        transmitter = self.transmitter
        if transmitter.player.active:
            raise ValueError("Trwa nadawanie. Poczekaj lub przerwij bieżącą transmisję.")
        transmitter.sweep_mode = False
        transmitter._transmit_text(text, transmitter.fsk.config(), transmitter.output.selected(),
                                   transmitter.level.get() / 100)
        return True

    def _close(self):
        self.links.close()
        self.transmitter.shutdown()
        self.receiver.shutdown()
        self.destroy()


if __name__ == "__main__":
    Transceiver().mainloop()
