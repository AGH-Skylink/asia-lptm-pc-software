"""Windows-oriented acoustic receiver GUI with live scope and monitoring."""

from __future__ import annotations

from array import array
from collections import OrderedDict
from codecs import getincrementaldecoder
import csv
from datetime import datetime
from hashlib import sha256
import json
import os
from math import log10
from pathlib import Path
from queue import Empty, Queue
from secrets import token_bytes
import shutil
import subprocess
import sys
from threading import Event, Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from audio_runtime import HighPass, OutputPlayer, ReceiverAudio, ac_metrics
from chat import ChatPanel
from file_sweep import PLAN_RAW_COLUMNS, read_plan, summary_rows
from gui_common import DevicePicker, FSKFields, ScrollableBody
from ipc_control import CommandServer, RECEIVER_PORT, TRANSMITTER_PORT, send_command
from ipc_reference import ID_BYTES, ReferenceServer, send_reference
from modem import FSKDecoder, MAX_TEXT_BYTES, ReceiveProgress, compare_payload_bits, compare_test_bits, encode_payload
from repeat_sweep import SUMMARY_COLUMNS, _write_csv, read_attempts
from sweep import _run_gui_trial
from scope import ScopeView
from text_encoding import ascii_text, convert_ascii_field
from transfers import FILE_MAGIC, NEGOTIATION, FileReceiver, bootstrap_config, packet_audio, read_settings


class Receiver(ttk.Frame):
    def _build_transceiver_view(self, layout):
        devices_top = ttk.Frame(layout["devices"])
        devices_top.pack(fill="x")
        self.devices_bottom = ttk.Frame(layout["devices"])
        self.devices_bottom.pack(fill="x", pady=(6, 0))
        self.input = DevicePicker(devices_top, "Wejście", "input")
        self.input.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.output = DevicePicker(devices_top, "Nadawanie", "output")
        self.output.pack(side="left", fill="x", expand=True)
        self.input.combo.configure(width=26)
        self.output.combo.configure(width=26)
        self.monitor_output = DevicePicker(self.devices_bottom, "Odsłuch mikrofonu", "output")
        self.monitor_output.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.monitor_output.combo.configure(width=26)
        self.monitor_output.combo.bind("<<ComboboxSelected>>", self._monitor_settings_changed)
        controls = layout["transport"]
        self.start_button = ttk.Button(controls, text="Rozpocznij odbiór", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(controls, text="Zatrzymaj odbiór", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        ttk.Checkbutton(controls, text="Automatyczne ustawienia", variable=self.auto_settings).pack(side="left", padx=8)
        ttk.Checkbutton(controls, text="Odsłuch", variable=self.listen,
                        command=self._monitor_settings_changed).pack(side="left", padx=8)
        self.chat = ChatPanel(layout["chat"], self._send_chat)
        self.chat.pack(fill="both", expand=True)
        self.chat.log.configure(width=40, height=12)
        self.chat.compose.configure(width=40)
        levels = ttk.Frame(self.chat)
        levels.pack(fill="x", padx=6, pady=6)
        ttk.Label(levels, text="Poziom nadawania [%]").pack(side="left")
        ttk.Scale(levels, from_=0, to=100, variable=self.chat_level).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(levels, text="Przerwij nadawanie", command=self._stop_chat).pack(side="right")

        scope_box = ttk.LabelFrame(layout["scope"], text="Oscyloskop")
        scope_box.pack(fill="both", expand=True)
        self.scope_view = ScopeView(scope_box, self.receive_gain_db, self.scope_label)
        self.scope_view.pack(fill="both", expand=True)
        self.scope = self.scope_view.canvas
        meter = ttk.Frame(scope_box)
        meter.pack(fill="x", padx=6, pady=4)
        self.signal_meter = ttk.Progressbar(meter, maximum=90, length=100)
        self.signal_meter.pack(side="left", fill="x", expand=True)
        ttk.Label(meter, textvariable=self.signal_label).pack(side="left", padx=8)
        gain = ttk.Frame(scope_box)
        gain.pack(fill="x", padx=6, pady=4)
        ttk.Label(gain, text="Wzmocnienie wykresu").pack(side="left")
        ttk.Scale(gain, from_=0, to=60, variable=self.receive_gain_db,
                  command=lambda _value: self._draw_scope()).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Label(gain, textvariable=self.scope_label).pack(side="right")

        self.fsk = FSKFields(layout["settings"], compact=True)
        self.fsk.pack(fill="x", pady=(8, 6))
        ttk.Label(layout["settings"], textvariable=self.ber_label, wraplength=470).pack(anchor="w", pady=3)
        ttk.Label(layout["settings"], textvariable=self.data_ber_label, wraplength=470).pack(anchor="w", pady=3)
        self.record_button = ttk.Button(layout["settings"], text="Nagrywaj WAV", command=self._toggle_recording)
        self.record_button.pack(anchor="w", pady=4)

        self.file_box = ttk.LabelFrame(layout["files"], text="Odbiór plików")
        self.file_box.pack(fill="x", pady=6)
        folder = ttk.Frame(self.file_box)
        folder.pack(fill="x", padx=6, pady=6)
        ttk.Entry(folder, textvariable=self.file_directory).pack(side="left", fill="x", expand=True)
        ttk.Button(folder, text="Folder docelowy…", command=self._choose_file_directory).pack(side="right", padx=(6, 0))
        ttk.Button(folder, text="Otwórz folder", command=self._open_file_directory).pack(side="right", padx=(6, 0))
        ttk.Progressbar(self.file_box, variable=self.file_progress, maximum=100).pack(fill="x", padx=6)
        ttk.Label(self.file_box, textvariable=self.file_status, wraplength=640).pack(fill="x", padx=6, pady=6)

        advanced = layout["advanced"]
        ttk.Checkbutton(advanced, text="Zapisuj tekst i BER na bieżąco", variable=self.autosave).pack(anchor="w")
        ttk.Entry(advanced, textvariable=self.autosave_path).pack(fill="x")
        ttk.Button(advanced, text="Wybierz plik zapisu", command=self._choose_autosave).pack(anchor="w", pady=4)
        self.expected = tk.Text(advanced, height=1, state="disabled", wrap="word", width=40)
        self.expected.pack(fill="x", pady=4)
        self.result = tk.Text(advanced, height=2, wrap="word", width=40)
        self.result.pack(fill="x", pady=4)
        ttk.Label(advanced, textvariable=self.receive_detail, wraplength=440).pack(anchor="w")
        ttk.Button(advanced, text="Zapisz wiadomość + BER", command=self.save).pack(anchor="w", pady=4)
        ttk.Button(advanced, text="Wyzeruj BER", command=self._reset_ber).pack(anchor="w", pady=4)
        for title, variable, command in (("Plan pomiarów CSV", self.scan_plan, self._choose_scan_plan),
                                         ("Wyniki CSV", self.scan_output, self._choose_scan_output)):
            ttk.Label(advanced, text=title).pack(anchor="w")
            row = ttk.Frame(advanced)
            row.pack(fill="x")
            ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="Wybierz", command=command).pack(side="right")
        self.scan_start_button = ttk.Button(advanced, text="Start pomiarów CSV", command=self._start_scan)
        self.scan_start_button.pack(anchor="w", pady=4)
        self.scan_stop_button = ttk.Button(advanced, text="Stop pomiarów", command=self._stop_scan, state="disabled")
        self.scan_stop_button.pack(anchor="w")
        ttk.Button(advanced, text="Zapisz skrót CSV", command=self._save_scan_copy).pack(anchor="w", pady=4)
        ttk.Label(advanced, textvariable=self.scan_status, wraplength=440).pack(anchor="w")
        ttk.Label(layout["status"], textvariable=self.status, wraplength=1200).pack(anchor="w")

    def _build_full_view(self):
        scroll = ScrollableBody(self)
        scroll.pack(fill="both", expand=True)
        body = scroll.content
        self.input = DevicePicker(body, "Mikrofon", "input")
        self.input.pack(fill="x", pady=(0, 8))
        self.output = DevicePicker(body, "Wyjście nadawania czatu", "output")
        self.output.pack(fill="x", pady=(0, 10))
        self.monitor_output = DevicePicker(body, "Wyjście odsłuchu mikrofonu", "output")
        self.monitor_output.pack(fill="x", pady=(0, 10))
        self.monitor_output.combo.bind("<<ComboboxSelected>>", self._monitor_settings_changed)
        self.fsk = FSKFields(body)
        self.fsk.pack(fill="x", pady=(0, 10))

        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=(0, 12))
        ttk.Checkbutton(
            controls, text="Odsłuch mikrofonu na głośniku", variable=self.listen,
            command=self._monitor_settings_changed,
        ).pack(side="left")
        self.start_button = ttk.Button(controls, text="Rozpocznij odbiór", command=self.start)
        self.start_button.pack(side="right")
        self.stop_button = ttk.Button(controls, text="Zatrzymaj", command=self.stop, state="disabled")
        self.stop_button.pack(side="right", padx=(0, 8))
        ttk.Checkbutton(controls, text="Automatyczne ustawienia z nadajnika", variable=self.auto_settings).pack(side="left", padx=8)

        conversation = ttk.Frame(body)
        conversation.pack(fill="both", expand=True, pady=(0, 10))
        conversation.columnconfigure(0, weight=1, uniform="conversation")
        conversation.columnconfigure(1, weight=1, uniform="conversation")
        conversation.rowconfigure(0, weight=1)
        self.chat = ChatPanel(conversation, self._send_chat)
        self.chat.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.chat.log.configure(width=40)
        self.chat.compose.configure(width=40)
        chat_level = ttk.Frame(self.chat)
        chat_level.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Label(chat_level, text="Poziom nadawania czatu [%]").pack(side="left")
        ttk.Scale(chat_level, from_=0, to=100, variable=self.chat_level).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(chat_level, text="Przerwij nadawanie", command=self._stop_chat).pack(side="right")

        scope_box = ttk.LabelFrame(conversation, text="Oscyloskop: sygnał z mikrofonu")
        scope_box.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.scope_view = ScopeView(scope_box, self.receive_gain_db, self.scope_label)
        self.scope_view.pack(fill="both", expand=True)
        self.scope = self.scope_view.canvas
        meter = ttk.Frame(scope_box)
        meter.pack(fill="x", padx=7, pady=3)
        ttk.Label(meter, text="Siła sygnału").pack(side="left")
        self.signal_meter = ttk.Progressbar(meter, maximum=90, length=160)
        self.signal_meter.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(scope_box, textvariable=self.signal_label).pack(anchor="w", padx=7)
        gain_row = ttk.Frame(scope_box)
        gain_row.pack(fill="x", padx=7, pady=6)
        ttk.Label(gain_row, text="Wzmocnienie wykresu [dB]").pack(side="left")
        ttk.Scale(gain_row, from_=0, to=60, variable=self.receive_gain_db,
                  orient="horizontal", command=lambda _value: self._draw_scope()).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(scope_box, textvariable=self.scope_label).pack(anchor="w", padx=7, pady=(0, 6))

        file_row = ttk.Frame(body)
        file_row.pack(fill="x", pady=(0, 6))
        ttk.Label(file_row, text="Folder odebranych plików").pack(side="left")
        ttk.Entry(file_row, textvariable=self.file_directory).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(file_row, text="Wybierz", command=self._choose_file_directory).pack(side="right")
        ttk.Button(file_row, text="Otwórz folder", command=self._open_file_directory).pack(side="right", padx=6)

        scan_box = ttk.LabelFrame(body, text="Pomiary z pliku — jeden wiersz = jedno nadanie")
        scan_box.pack(fill="x", pady=(0, 12))
        plan_row = ttk.Frame(scan_box)
        plan_row.pack(fill="x", padx=6, pady=(5, 2))
        ttk.Label(plan_row, text="Plan CSV", width=12).pack(side="left")
        ttk.Entry(plan_row, textvariable=self.scan_plan).pack(side="left", fill="x", expand=True)
        ttk.Button(plan_row, text="Wybierz", command=self._choose_scan_plan).pack(side="left", padx=(6, 0))
        output_row = ttk.Frame(scan_box)
        output_row.pack(fill="x", padx=6, pady=2)
        ttk.Label(output_row, text="Wyniki CSV", width=12).pack(side="left")
        ttk.Entry(output_row, textvariable=self.scan_output).pack(side="left", fill="x", expand=True)
        ttk.Button(output_row, text="Wybierz", command=self._choose_scan_output).pack(side="left", padx=(6, 0))
        scan_actions = ttk.Frame(scan_box)
        scan_actions.pack(fill="x", padx=6, pady=(3, 6))
        ttk.Label(scan_actions, textvariable=self.scan_status).pack(side="left", fill="x", expand=True)
        ttk.Button(scan_actions, text="Zapisz skrót CSV", command=self._save_scan_copy).pack(side="right")
        self.scan_stop_button = ttk.Button(scan_actions, text="Stop", command=self._stop_scan, state="disabled")
        self.scan_stop_button.pack(side="right", padx=6)
        self.scan_start_button = ttk.Button(scan_actions, text="Start", command=self._start_scan)
        self.scan_start_button.pack(side="right")

        save_row = ttk.Frame(body)
        save_row.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(save_row, text="Zapisuj tekst w trakcie odbioru + bajty i BER",
                        variable=self.autosave).pack(side="left")
        ttk.Entry(save_row, textvariable=self.autosave_path).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(save_row, text="Wybierz", command=self._choose_autosave).pack(side="right")
        self.record_button = ttk.Button(save_row, text="Nagrywaj WAV", command=self._toggle_recording)
        self.record_button.pack(side="right", padx=6)

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
        ttk.Label(text_box, textvariable=self.receive_detail, wraplength=850).pack(anchor="w", padx=5)
        self.result = tk.Text(text_box, wrap="word", height=4)
        self.result.pack(fill="both", expand=True, padx=5, pady=5)
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Zapisz wiadomość + BER", command=self.save).pack(side="right")
        ttk.Button(actions, text="Wyczyść", command=lambda: self.result.delete("1.0", "end")).pack(
            side="right", padx=(0, 8)
        )
        ttk.Label(actions, textvariable=self.status, wraplength=560).pack(side="left", fill="x", expand=True)


    def __init__(self, parent=None, layout=None):
        self.owns_window = parent is None
        if parent is None:
            parent = tk.Tk()
        super().__init__(parent)
        self.window = self.winfo_toplevel()
        if self.owns_window:
            self.window.title("Odbiornik akustyczny")
            self.window.geometry("1200x960")
            self.window.minsize(1040, 650)
            self.pack(fill="both", expand=True)
        self.chat_player = OutputPlayer()
        self.chat_send_handler = None
        self.chat_stop_handler = None
        self.chat_sending_id = None
        self.chat_level = tk.IntVar(value=40)
        self.audio = ReceiverAudio()
        self.decoder: FSKDecoder | None = None
        self.bootstrap_decoder: FSKDecoder | None = None
        self.auto_settings = tk.BooleanVar(value=True)
        self.file_directory = tk.StringVar(value=str(Path.home() / "Downloads" / "LPTM"))
        self.file_progress = tk.DoubleVar(value=0)
        self.file_status = tk.StringVar(value="Pliki są zapisywane automatycznie w folderze powyżej.")
        self.file_receiver = FileReceiver()
        self.file_errors = self.file_bits = 0
        self.showing_file = False
        self.status = tk.StringVar(value="Gotowy.")
        self.listen = tk.BooleanVar(value=False)
        self.latest = array("f")
        self.scope_samples = array("f")
        self.scope_filter = HighPass(400)
        self.signal_label = tk.StringVar(value="Sygnał: cisza")
        self.scope_label = tk.StringVar(value="Wzmocnienie wykresu: —")
        self.ber_label = tk.StringVar(value="BER: — (po pierwszej odebranej ramce)")
        self.data_ber_label = tk.StringVar(value="BER danych: — (czekam na lokalny wzorzec)")
        self.ber_errors = 0
        self.ber_bits = 0
        self.ber_frames = 0
        self.ber_crc_errors = 0
        self.receive_gain_db = tk.DoubleVar(value=0)
        self.reference_server = ReferenceServer()
        self.control = CommandServer(RECEIVER_PORT)
        self.references: OrderedDict[bytes, bytes] = OrderedDict()
        self.measurement_active = False
        self.measurement_result: dict | None = None
        self.measurement_sum_sq = 0.0
        self.measurement_count = 0
        self.measurement_noise_dbfs: float | None = None
        self.autosave_path = tk.StringVar()
        self.autosave = tk.BooleanVar(value=False)
        self.received: ReceiveProgress | None = None
        self.received_crc: bool | None = None
        self.received_ber = "—"
        self.receive_detail = tk.StringVar(value="Odebrano: 0 bajtów; CRC: oczekiwanie")
        self.logged_key = None
        self.logged_text = ""
        self.logged_final = False
        self.scan_plan = tk.StringVar()
        self.scan_output = tk.StringVar()
        self.scan_status = tk.StringVar(value="Wybierz plan i plik wynikowy; wiadomość ustaw w nadajniku.")
        self.scan_stop = Event()
        self.scan_thread: Thread | None = None
        self.scan_updates: Queue[tuple[str, str]] = Queue()

        if layout is None:
            self._build_full_view()
        else:
            self._build_transceiver_view(layout)
        self.encoding_trace = self.fsk.encoding.trace_add("write", self._encoding_changed)
        try:
            self.reference_server.start()
        except OSError as exc:
            self.status.set(f"Lokalny kanał wzorca niedostępny: {exc}")
        try:
            self.control.start()
        except OSError as exc:
            self.status.set(f"Sterowanie pomiarami niedostępne: {exc}")
        self.poll_id = self.after(80, self._poll)
        for shortcut in ("<Control-r>", "<Command-r>"):
            self.window.bind(shortcut, self._toggle_receive)
        if self.owns_window:
            self.window.protocol("WM_DELETE_WINDOW", self._close)

    def _send_chat(self, text: str) -> bool:
        try:
            if self.fsk.encoding.get() == "ascii":
                text = ascii_text(text)
            if self.decoder is None:
                self.start()
                if self.decoder is None:
                    return False
            if self.chat_send_handler is not None:
                return self.chat_send_handler(text)
            if self.chat_player.active:
                raise ValueError("Trwa nadawanie. Poczekaj lub przerwij bieżącą wiadomość.")
            config = self.fsk.config()
            encoding = self.fsk.encoding.get()
            payload = text.encode(encoding)
            message_id = token_bytes(ID_BYTES)
            encode_payload(payload, message_id)
            device = self.output.selected()
            send_reference(message_id, payload)
            self.chat.sent(message_id, text, len(payload))
            self.chat_sending_id = message_id
            self.chat_player.play_chunks(packet_audio([payload], config, message_id,
                self.chat_level.get() / 100, self.auto_settings.get(), encoding), device, config.sample_rate)
            self.status.set(f"Czat: nadawanie {len(payload)} bajtów przez {config.modulation}.")
            return True
        except (ValueError, OSError) as exc:
            messagebox.showerror("Nie można wysłać wiadomości czatu", str(exc))
            return False

    def _encoding_changed(self, *_args):
        if self.fsk.encoding.get() == "ascii" and convert_ascii_field(self.chat.compose):
            self.status.set("Tekst czatu przekonwertowano na ASCII; znaki bez odpowiednika zastąpiono ?.")

    def _stop_chat(self):
        if self.chat_stop_handler is not None:
            self.chat_stop_handler()
            return
        active = self.chat_player.active
        self.chat_player.stop()
        if self.chat_sending_id is not None:
            self.chat.sent_status(self.chat_sending_id, "Przerwano nadawanie" if active else "Nadano")
            self.chat_sending_id = None

    def _toggle_receive(self, _event) -> str:
        if self.decoder is None:
            self.start()
        else:
            self.stop()
        return "break"

    def _monitor_settings_changed(self, _event=None):
        if not self.audio.active:
            return
        try:
            self.audio.set_monitor(self.monitor_output.selected() if self.listen.get() else None)
        except (ValueError, OSError) as exc:
            self.status.set(f"Nie można zmienić odsłuchu: {exc}")

    def _choose_scan_plan(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Plan CSV", "*.csv"), ("Wszystkie", "*.*")])
        if path:
            self.scan_plan.set(path)

    def _choose_scan_output(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                             initialfile="pomiary_raw.csv",
                                             filetypes=[("CSV", "*.csv")])
        if path:
            self.scan_output.set(path)

    def _save_scan_copy(self) -> None:
        output = Path(self.scan_output.get())
        summary = output.with_name(output.stem.replace("_raw", "") + "_summary.csv")
        if not summary.exists():
            messagebox.showinfo("Wyniki", "Skrót CSV powstanie po rozpoczęciu pomiarów.")
            return
        target = filedialog.asksaveasfilename(defaultextension=".csv",
                                              initialfile=summary.name,
                                              filetypes=[("CSV", "*.csv")])
        if target:
            shutil.copyfile(summary, target)
            self.scan_status.set(f"Zapisano kopię: {target}")

    def _start_scan(self) -> None:
        if self.scan_thread is not None and self.scan_thread.is_alive():
            return
        try:
            plan_path = Path(self.scan_plan.get())
            output_path = Path(self.scan_output.get())
            trials = read_plan(plan_path)
            if not self.scan_output.get() or output_path.suffix.lower() != ".csv":
                raise ValueError("Wybierz plik wynikowy CSV w odbiorniku.")
            input_device = self.input.selected()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Nie można rozpocząć pomiarów", str(exc))
            return
        self.scan_stop.clear()
        self.scan_start_button.configure(state="disabled")
        self.scan_stop_button.configure(state="normal")
        self.scan_status.set(f"Przygotowanie {len(trials)} pomiarów…")
        self.scan_thread = Thread(target=self._scan_worker,
                                  args=(plan_path, output_path, trials, input_device), daemon=True)
        self.scan_thread.start()

    def _stop_scan(self) -> None:
        self.scan_stop.set()
        self.scan_status.set("Zatrzymywanie po bieżącym poleceniu audio…")

    def _scan_worker(self, plan_path: Path, output_path: Path, trials, input_device: int) -> None:
        try:
            sender = send_command(TRANSMITTER_PORT, {"action": "measurement_message"})
            if sender.get("error"):
                raise ValueError(sender["error"])
            message = sender["text"]
            payload = message.encode("utf-8")
            if not 1 <= len(payload) <= MAX_TEXT_BYTES:
                raise ValueError(f"Wiadomość musi mieć 1–{MAX_TEXT_BYTES} bajtów UTF-8.")
            output_device = int(sender["output_device"])
            amplitude = float(sender["amplitude"])
            summary_path = output_path.with_name(output_path.stem.replace("_raw", "") + "_summary.csv")
            metadata_path = output_path.with_name(output_path.stem.replace("_raw", "") + "_metadata.json")
            metadata = {"plan_sha256": sha256(plan_path.read_bytes()).hexdigest(),
                        "plan_rows": len(trials), "message": message,
                        "message_sha256": sha256(payload).hexdigest(),
                        "amplitude": amplitude, "input_device": input_device,
                        "output_device": output_device}
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if output_path.exists():
                if not metadata_path.exists() or json.loads(metadata_path.read_text(encoding="utf-8")) != metadata:
                    raise ValueError("Istniejący CSV ma inny plan, wiadomość lub urządzenia. Wybierz nową nazwę.")
            else:
                metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
                _write_csv(output_path, PLAN_RAW_COLUMNS, [])
            attempts = read_attempts(output_path)
            completed = {int(row["plan_line"]) for row in attempts}
            for index, (line_number, trial) in enumerate(trials, 1):
                if self.scan_stop.is_set():
                    break
                if line_number in completed:
                    continue
                self.scan_updates.put(("progress", f"{index}/{len(trials)}: {trial.zero_hz}/{trial.one_hz} Hz, "
                                                    f"{trial.speed_bps:g} bit/s"))
                result = _run_gui_trial(trial, input_device, output_device, amplitude,
                                        message, stop_event=self.scan_stop)
                result["received_text"] = "".join(
                    f"\\u{ord(char):04x}" if ord(char) < 32 else char
                    for char in result["received_text"])
                row = {"plan_line": line_number, **result, "attempt": 1,
                       "input_device": input_device, "output_device": output_device}
                with output_path.open("a", newline="", encoding="utf-8") as target:
                    csv.DictWriter(target, fieldnames=PLAN_RAW_COLUMNS, lineterminator="\n").writerow(row)
                attempts.append(row)
                _write_csv(summary_path, SUMMARY_COLUMNS, summary_rows(trials, attempts))
            _write_csv(summary_path, SUMMARY_COLUMNS, summary_rows(trials, attempts))
            self.scan_updates.put(("done", f"Zapisano {len(attempts)}/{len(trials)} pomiarów: {summary_path}"))
        except InterruptedError:
            self.scan_updates.put(("done", "Pomiar zatrzymany. Zapisane wyniki można wznowić przyciskiem Start."))
        except Exception as exc:
            self.scan_updates.put(("error", str(exc)))
        finally:
            try:
                send_command(RECEIVER_PORT, {"action": "finish"})
            except OSError:
                pass

    def start(self) -> None:
        try:
            config = self.fsk.config()
            if self.autosave.get():
                if not self.autosave_path.get():
                    raise ValueError("Wybierz plik do automatycznego zapisu.")
                with Path(self.autosave_path.get()).open("a", encoding="utf-8"):
                    pass
            input_device = self.input.selected()
            output_device = self.monitor_output.selected() if self.listen.get() else None
            self.decoder = FSKDecoder(config)
            self.bootstrap_decoder = FSKDecoder(bootstrap_config(config.sample_rate))
            cutoff = max(20, min(500, min(config.zero_hz, config.one_hz) / 3))
            self.scope_filter = HighPass(cutoff, config.sample_rate)
            self.scope_view.reset(config.sample_rate)
            self.audio.start(input_device, output_device, config.sample_rate)
            self.status.set(f"Odbieranie {config.modulation}. Ustaw w nadajniku tę samą modulację, częstotliwości, bit/s i próbkowanie.")
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
        except Exception as exc:
            self.decoder = None
            messagebox.showerror("Nie można rozpocząć odbioru", str(exc))

    def stop(self) -> None:
        if self.autosave.get() and self.logged_key is not None and not self.logged_final:
            try:
                with Path(self.autosave_path.get()).open("a", encoding="utf-8") as target:
                    target.write("\n[Przerwano odbiór] " + self._received_report() + "\n")
            except OSError as exc:
                self.status.set(f"Zapis niepełnej wiadomości: {exc}")
            self.logged_key = None
        self.audio.stop()
        self.record_button.configure(text="Nagrywaj WAV")
        self.decoder = None
        self.bootstrap_decoder = None
        self.file_receiver.close()
        self.measurement_active = False
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status.set("Zatrzymano.")

    def _measurement_dbfs(self) -> float | None:
        if not self.measurement_count or self.measurement_sum_sq <= 0:
            return None
        return 10 * log10(self.measurement_sum_sq / self.measurement_count)

    def _control_command(self, command: dict) -> dict:
        action = command.get("action")
        if action == "prepare":
            zero = int(command["zero_hz"])
            one = int(command["one_hz"])
            baud = float(command["speed_bps"])
            self.stop()
            self.fsk.zero.set(str(zero))
            self.fsk.one.set(str(one))
            self.fsk.baud.set(f"{baud:g}")
            self.fsk.modulation.set(command.get("modulation", "2FSK"))
            self.fsk.encoding.set("utf-8")
            self.fsk.sample_rate.set(str(command.get("sample_rate", 48000)))
            self.fsk._rate_changed()
            self.input.select(int(command["input_device"]))
            self.listen.set(False)
            self.references.clear()
            self._show_expected(None)
            self.result.delete("1.0", "end")
            self._reset_ber()
            self.measurement_result = None
            self.measurement_sum_sq = 0.0
            self.measurement_count = 0
            self.measurement_noise_dbfs = None
            self.start()
            if self.decoder is None:
                raise RuntimeError("Odbiornik nie rozpoczął nasłuchu.")
            self.measurement_active = True
            self.status.set("Pomiar automatyczny: czekam na transmisję audio.")
            return {"ready": True}
        if action == "begin":
            self.measurement_noise_dbfs = self._measurement_dbfs()
            self.measurement_sum_sq = 0.0
            self.measurement_count = 0
            return {"noise_rms_dbfs": self.measurement_noise_dbfs}
        if action == "status":
            return {"active": self.measurement_active, "result": self.measurement_result,
                    "signal_rms_dbfs": self._measurement_dbfs()}
        if action == "finish":
            result = self.measurement_result or {
                "status": "no_frame", "ber_percent": "", "bit_errors": "",
                "compared_bits": "", "crc_ok": "", "received_text": "", "message_id": "",
            }
            result = {**result, "signal_rms_dbfs": self._measurement_dbfs(),
                      "noise_rms_dbfs": self.measurement_noise_dbfs}
            self.stop()
            if result["status"] == "no_frame":
                self.status.set("Pomiar: nie rozpoznano ramki audio; BER niedostępny.")
            else:
                self.status.set(f"Pomiar zakończony: {result['status']}, BER {result['ber_percent']}%.")
            return result
        raise ValueError("Nieznane polecenie odbiornika.")

    def _reset_ber(self) -> None:
        self.ber_errors = self.ber_bits = self.ber_frames = self.ber_crc_errors = 0
        self.file_errors = self.file_bits = 0
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

    def _choose_autosave(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Plik tekstowy", "*.txt"), ("Wszystkie", "*.*")]
        )
        if path:
            self.autosave_path.set(path)
            self.autosave.set(True)
            self.logged_key = None

    def _choose_file_directory(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.file_directory.set(path)

    def _open_file_directory(self) -> None:
        try:
            directory = Path(self.file_directory.get()).resolve()
            directory.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(directory))
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(directory)])
        except OSError as exc:
            messagebox.showerror("Nie można otworzyć folderu", str(exc))

    def _apply_settings(self, payload: bytes) -> bool:
        try:
            config, encoding = read_settings(payload)
            old_rate = self.decoder.config.sample_rate
            self.fsk.modulation.set(config.modulation)
            self.fsk.sample_rate.set(str(config.sample_rate))
            self.fsk._rate_changed()
            self.fsk.max_hz.set(config.max_hz)
            self.fsk.zero.set(str(config.zero_hz))
            self.fsk.one.set(str(config.one_hz))
            self.fsk.baud.set(str(config.baud))
            self.fsk.encoding.set(encoding)
            if config.sample_rate != old_rate:
                self.stop()
                self.start()
            else:
                self.decoder = FSKDecoder(config)
                self.bootstrap_decoder = FSKDecoder(bootstrap_config(config.sample_rate))
                self.scope_filter = HighPass(max(20, min(500, config.zero_hz / 3)), config.sample_rate)
            if self.decoder is None:
                raise ValueError("Urządzenie nie obsługuje ustawień nadajnika.")
            self.status.set(f"Ustawiono automatycznie: {config.modulation}, {config.zero_hz}/{config.one_hz} Hz, "
                            f"{config.baud:g} bit/s, {encoding}.")
            return True
        except (ValueError, TypeError, KeyError) as exc:
            self.status.set(f"Nieprawidłowa zapowiedź: {exc}")
            return False

    def _receive_file_frame(self, frame) -> None:
        self.showing_file = True
        self.file_errors += frame.probe_errors
        self.file_bits += frame.probe_bits
        try:
            if not frame.crc_ok:
                state = (self.file_receiver.pending_status() if self.file_receiver.target is not None
                         else "Czekam na poprawny nagłówek pliku.")
                raise ValueError("Błędne CRC bloku; czekam na poprawną kopię. " + state)
            if not self.file_directory.get():
                raise ValueError("Wybierz folder odebranych plików.")
            detail = self.file_receiver.accept(frame.payload, frame.message_id, Path(self.file_directory.get()))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            detail = str(exc)
        if self.file_receiver.completed and frame.message_id == self.file_receiver.message_id:
            detail = (f"Zapisano {self.file_receiver.final_path} "
                      f"({self.file_receiver.size} bajtów, SHA-256 OK)")
        report = (f"{detail} | BER wzorca: {self.file_errors / self.file_bits:.6%} "
                  f"({self.file_errors}/{self.file_bits})")
        self.status.set(detail)
        self.file_status.set(report)
        self.file_progress.set(100 * self.file_receiver.received / max(1, self.file_receiver.size))
        self.receive_detail.set(report)
        self.result.delete("1.0", "end")
        self.result.insert("1.0", report)
        if self.autosave.get():
            try:
                with Path(self.autosave_path.get()).open("a", encoding="utf-8") as target:
                    target.write(report + "\n")
            except OSError as exc:
                self.autosave.set(False)
                self.status.set(f"Nie można zapisać raportu: {exc}")

    def _toggle_recording(self) -> None:
        if self.audio.recorder.active:
            self.audio.recorder.stop()
            self.record_button.configure(text="Nagrywaj WAV")
            self.status.set("Zapisano nagranie WAV.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("Nagranie WAV", "*.wav")])
        if not path:
            return
        try:
            if self.decoder is None:
                self.start()
            if self.decoder is None:
                return
            self.audio.recorder.start(path, self.decoder.config.sample_rate)
            self.record_button.configure(text="Zakończ WAV")
            self.status.set(f"Nagrywanie surowego sygnału do: {path}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Nie można nagrywać WAV", str(exc))

    def _received_report(self) -> str:
        snapshot = self.received
        if snapshot is None or not snapshot.payload:
            return "Brak rozpoznanej wiadomości."
        crc = "oczekiwanie / niepełna" if self.received_crc is None else "OK" if self.received_crc else "BŁĘDNE"
        return (f"ID: {snapshot.message_id.hex()} | Bajty: {len(snapshot.payload)}/{snapshot.expected_bytes} | "
                f"BER wzorca: {snapshot.probe_errors / snapshot.probe_bits:.6%} "
                f"({snapshot.probe_errors}/{snapshot.probe_bits}) | BER danych: {self.received_ber} | CRC: {crc}")

    def _show_progress(self, snapshot: ReceiveProgress | None, crc: bool | None = None) -> None:
        if snapshot is None or not snapshot.payload:
            return
        if snapshot.payload and any(magic.startswith(snapshot.payload) or snapshot.payload.startswith(magic)
                                    for magic in (FILE_MAGIC, NEGOTIATION)):
            return
        if snapshot == self.received and (crc is None or crc == self.received_crc):
            return
        if self.received is not None and snapshot.message_id == self.received.message_id:
            if crc is None and self.received_crc is not None:
                return
            if crc is None and len(snapshot.payload) < len(self.received.payload):
                return
        self.showing_file = False
        self.received = snapshot
        self.received_crc = crc
        # Keep the last incomplete UTF-8 sequence until its remaining bytes arrive.
        text = getincrementaldecoder(self.fsk.encoding.get())(errors="replace").decode(snapshot.payload, final=crc is not None)
        self.result.delete("1.0", "end")
        self.result.insert("1.0", text)
        expected = self.references.get(snapshot.message_id)
        self.received_ber = "brak wzorca"
        if expected is not None and snapshot.payload:
            reference = expected if crc is not None else expected[:len(snapshot.payload)]
            errors, bits = compare_payload_bits(snapshot.payload, reference)
            self.received_ber = f"{errors / bits:.6%} ({errors}/{bits})"
        crc_text = "oczekiwanie / niepełna" if crc is None else "OK" if crc else "BŁĘDNE"
        self.receive_detail.set(f"Bajty: {len(snapshot.payload)}/{snapshot.expected_bytes} | "
                               f"BER wzorca: {snapshot.probe_errors / snapshot.probe_bits:.4%} | "
                               f"BER danych: {self.received_ber} | CRC: {crc_text}")
        if (chat := getattr(self, "chat", None)) is not None:
            chat.receive(snapshot, crc, self.fsk.encoding.get())
        self._log_progress(text, crc)

    def _log_progress(self, text: str, crc: bool | None) -> None:
        if not self.autosave.get():
            return
        try:
            key = (self.autosave_path.get(), self.received.message_id)
            with Path(self.autosave_path.get()).open("a", encoding="utf-8", newline="") as target:
                if key != self.logged_key:
                    target.write(f"\n[{datetime.now().astimezone().isoformat(timespec='seconds')}] {self._received_report()}\n")
                    self.logged_key, self.logged_text, self.logged_final = key, "", False
                if text.startswith(self.logged_text):
                    target.write(text[len(self.logged_text):])
                else:
                    target.write("\n[Korekta dekodowania]\n" + text)
                self.logged_text = text
                if crc is not None and not self.logged_final:
                    target.write("\n" + self._received_report() + "\n")
                    self.logged_final = True
        except OSError as exc:
            self.autosave.set(False)
            messagebox.showerror("Automatyczny zapis wyłączony", str(exc))

    def save(self) -> None:
        text = self.result.get("1.0", "end-1c")
        if self.received is None and not self.showing_file:
            messagebox.showinfo("Zapis", "Nie ma jeszcze odebranego tekstu.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Plik tekstowy", "*.txt"), ("Wszystkie", "*.*")]
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as target:
                    target.write(text if self.showing_file else self._received_report() + "\n\n" + text)
                self.status.set(f"Zapisano: {path}")
            except OSError as exc:
                messagebox.showerror("Nie można zapisać", str(exc))

    def _draw_scope(self) -> None:
        self.scope_view.draw()

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
                kind, detail = self.chat_player.events.get_nowait()
                self.status.set(detail)
                if self.chat_sending_id is not None:
                    self.chat.sent_status(self.chat_sending_id, "Błąd nadawania" if kind == "error" else "Nadano")
                    self.chat_sending_id = None
        except Empty:
            pass
        try:
            while True:
                kind, detail = self.scan_updates.get_nowait()
                self.scan_status.set(detail)
                if kind in ("done", "error"):
                    self.scan_start_button.configure(state="normal")
                    self.scan_stop_button.configure(state="disabled")
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
                message_id, expected = self.reference_server.incoming.get_nowait()
                self.references[message_id] = expected
                if len(self.references) > 32:
                    self.references.popitem(last=False)
                if message_id in self.chat.history.own_ids:
                    continue
                self._show_expected(expected)
                self.result.delete("1.0", "end")
                self.received = None
                self.received_crc = None
                self.receive_detail.set("Czekam na dane z audio.")
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
                self.scope_samples = raw
                self.scope_view.feed(raw, self.decoder.config.sample_rate)
                if self.measurement_active:
                    self.measurement_sum_sq += sum(sample * sample for sample in self.latest)
                    self.measurement_count += len(self.latest)
                if self.auto_settings.get() and not self.measurement_active:
                    announcements = self.bootstrap_decoder.feed_frames(chunk)
                    announcement = next((frame for frame in announcements
                                         if frame.crc_ok and frame.payload.startswith(NEGOTIATION)), None)
                    if announcement is not None:
                        self._apply_settings(announcement.payload)
                        break
                frames = self.decoder.feed_frames(chunk)
                self._show_progress(self.decoder.progress)
                for frame in frames:
                    if frame.payload.startswith(NEGOTIATION):
                        continue
                    if frame.payload.startswith(FILE_MAGIC):
                        self._receive_file_frame(frame)
                        continue
                    self._show_progress(ReceiveProgress(frame.message_id, frame.payload, len(frame.payload),
                                                        frame.probe_errors, frame.probe_bits), frame.crc_ok)
                    self.ber_errors += frame.probe_errors
                    self.ber_bits += frame.probe_bits
                    self.ber_frames += 1
                    self.ber_crc_errors += not frame.crc_ok
                    expected = self.references.pop(frame.message_id, None)
                    matched_id = expected is not None
                    # An automated trial has exactly one local reference. If
                    # its audio ID is damaged, the payload is still comparable.
                    if expected is None and self.measurement_active and len(self.references) == 1:
                        _, expected = self.references.popitem(last=False)
                    if expected is not None:
                        errors, bits = compare_payload_bits(frame.payload, expected)
                        self._show_expected(expected)
                        self.data_ber_label.set(
                            f"BER danych ostatniej ramki: {errors / bits:.6%} ({errors}/{bits} bitów)"
                        )
                    else:
                        self._show_expected(None)
                        self.data_ber_label.set("BER danych: brak lokalnego wzorca dla tej ramki")
                    if self.measurement_active and self.measurement_result is None:
                        self.measurement_result = {
                            "message_id": frame.message_id.hex(),
                            "status": (("ok" if frame.crc_ok else "bad_crc") if matched_id
                                       else "id_mismatch" if expected is not None else "no_reference"),
                            "ber_percent": 100 * errors / bits if expected is not None else "",
                            "bit_errors": errors if expected is not None else "",
                            "compared_bits": bits if expected is not None else "",
                            "crc_ok": int(frame.crc_ok),
                            "received_text": frame.payload.decode("utf-8", errors="replace"),
                        }
                    test = compare_test_bits(frame.payload)
                    if test is not None:
                        errors, bits = test
                        self.ber_errors += errors
                        self.ber_bits += bits
                        self.status.set("Odebrano ramkę testową BER.")
                    elif frame.crc_ok:
                        try:
                            text = frame.payload.decode(self.fsk.encoding.get())
                        except UnicodeDecodeError:
                            self.status.set("CRC poprawne; nieprawidłowe znaki UTF-8 oznaczono symbolem �.")
                        else:
                            self.status.set(f"Odebrano wiadomość: {len(frame.payload)} bajtów.")
                    else:
                        self.status.set("Błędne CRC: pokazano odebrane dane, mogą zawierać błędy.")
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
        self.poll_id = self.after(80, self._poll)

    def shutdown(self) -> None:
        self.fsk.encoding.trace_remove("write", self.encoding_trace)
        self.after_cancel(self.poll_id)
        self.scan_stop.set()
        self.chat_player.stop()
        self.stop()
        self.file_receiver.close()
        self.reference_server.stop()
        self.control.stop()

    def _close(self) -> None:
        self.shutdown()
        self.destroy()
        if self.owns_window:
            self.window.destroy()


if __name__ == "__main__":
    Receiver().mainloop()
