"""Shared chat history and composer for the receiver and transceiver."""
from codecs import getincrementaldecoder
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText


@dataclass
class ChatMessage:
    role: str
    text: str
    state: str
    byte_count: int
    expected_bytes: int
    ber: str = ""


class ChatHistory:
    def __init__(self):
        self.messages = OrderedDict()
        self.own_ids = OrderedDict()

    def sent(self, message_id, text, byte_count):
        self.own_ids[message_id] = None
        if len(self.own_ids) > 256:
            self.own_ids.popitem(last=False)
        self.messages[("Ty", message_id)] = ChatMessage("Ty", text, "Nadawanie", byte_count, byte_count)
        self._trim()

    def sent_status(self, message_id, state):
        if (message := self.messages.get(("Ty", message_id))) is not None:
            message.state = state

    def receive(self, snapshot, crc, encoding):
        if snapshot.message_id in self.own_ids:
            return False
        if snapshot.expected_bytes == 132 and snapshot.payload.startswith(b"BER1"):
            return False
        key = ("Rozmówca", snapshot.message_id)
        previous = self.messages.get(key)
        if previous is not None and crc is None:
            if previous.state != "Odbieranie" or len(snapshot.payload) < previous.byte_count:
                return False
        text = getincrementaldecoder(encoding)(errors="replace").decode(snapshot.payload, final=crc is not None)
        state = "Odbieranie" if crc is None else "CRC OK" if crc else "Błędne CRC"
        message = ChatMessage("Rozmówca", text, state, len(snapshot.payload), snapshot.expected_bytes,
                              f"BER wzorca {snapshot.probe_errors / snapshot.probe_bits:.4%}")
        if previous == message:
            return False
        self.messages[key] = message
        self._trim()
        return True

    def _trim(self):
        while len(self.messages) > 200:
            self.messages.popitem(last=False)

    def transcript(self):
        parts = []
        for message in self.messages.values():
            detail = f"{message.byte_count}/{message.expected_bytes} B"
            if message.ber:
                detail += "; " + message.ber
            parts.append(f"{message.role} · {message.state} · {detail}\n{message.text}\n")
        return "\n".join(parts)


class ChatPanel(ttk.LabelFrame):
    def __init__(self, parent, send):
        super().__init__(parent, text="Czat")
        self.history = ChatHistory()
        self.send = send
        self.log = ScrolledText(self, height=8, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)
        self.compose = ScrolledText(self, height=3, wrap="word")
        self.compose.pack(fill="x", padx=6)
        for key in ("<Control-Return>", "<Command-Return>"):
            self.compose.bind(key, self._send)
        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=6, pady=6)
        ttk.Label(actions, text="Ctrl+Enter: wyślij. Enter: nowy wiersz.").pack(side="left")
        ttk.Button(actions, text="Wyślij", command=self._send).pack(side="right")
        ttk.Button(actions, text="Zapisz czat", command=self._save).pack(side="right", padx=6)

    def _send(self, _event=None):
        text = self.compose.get("1.0", "end-1c")
        if text and self.send(text):
            self.compose.delete("1.0", "end")
        return "break"

    def sent(self, message_id, text, byte_count):
        self.history.sent(message_id, text, byte_count)
        self._render()

    def sent_status(self, message_id, state):
        self.history.sent_status(message_id, state)
        self._render()

    def receive(self, snapshot, crc, encoding):
        if self.history.receive(snapshot, crc, encoding):
            self._render()

    def _render(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", self.history.transcript())
        self.log.configure(state="disabled")
        self.log.see("end")

    def _save(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Czat UTF-8", "*.txt")])
        if path:
            try:
                with open(path, "w", encoding="utf-8") as target:
                    target.write(datetime.now().astimezone().isoformat(timespec="seconds") + "\n\n")
                    target.write(self.history.transcript())
            except OSError as exc:
                messagebox.showerror("Nie można zapisać czatu", str(exc))
