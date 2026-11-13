"""Windows-oriented acoustic receiver GUI with live scope and monitoring."""

from __future__ import annotations

from array import array
from collections import OrderedDict
import csv
from hashlib import sha256
import json
from math import log10
from pathlib import Path
from queue import Empty, Queue
import shutil
from threading import Event, Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from audio_runtime import HighPass, ReceiverAudio, ac_metrics
from file_sweep import PLAN_RAW_COLUMNS, read_plan, summary_rows
from gui_common import DevicePicker, FSKFields
from ipc_control import CommandServer, RECEIVER_PORT, TRANSMITTER_PORT, send_command
from ipc_reference import ReferenceServer
from modem import FSKDecoder, MAX_FREQUENCY, MAX_TEXT_BYTES, compare_payload_bits, compare_test_bits
from repeat_sweep import SUMMARY_COLUMNS, _write_csv, read_attempts
from sweep import _run_gui_trial


class Receiver(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Odbiornik akustyczny")
        self.geometry("900x920")
        self.minsize(720, 790)
        self.audio = ReceiverAudio()
        self.decoder: FSKDecoder | None = None
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
        self.scan_plan = tk.StringVar()
        self.scan_output = tk.StringVar()
        self.scan_status = tk.StringVar(value="Wybierz plan i plik wynikowy; wiadomość ustaw w nadajniku.")
        self.scan_stop = Event()
        self.scan_thread: Thread | None = None
        self.scan_updates: Queue[tuple[str, str]] = Queue()

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
        gain_row = ttk.Frame(scope_box)
        gain_row.pack(fill="x", padx=7, pady=(0, 6))
        ttk.Label(gain_row, text="Wzmocnienie odbioru [dB]").pack(side="left")
        ttk.Scale(gain_row, from_=0, to=60, variable=self.receive_gain_db,
                  orient="horizontal", command=lambda _value: self._draw_scope()).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(gain_row, textvariable=self.scope_label).pack(side="left")

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
        try:
            self.control.start()
        except OSError as exc:
            self.status.set(f"Sterowanie pomiarami niedostępne: {exc}")
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
            self.fsk.max_hz.set(MAX_FREQUENCY)
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
        if not self.scope_samples:
            return
        length = len(self.scope_samples)
        gain_db = self.receive_gain_db.get()
        gain = 10 ** (gain_db / 20)
        self.scope_label.set(f"{gain_db:.0f} dB (×{gain:.1f})")
        offset, peak, _ = ac_metrics(self.scope_samples)
        scale = max(peak, 1e-9)
        points = []
        for index in range(min(width, 500)):
            source_index = min(length - 1, index * length // min(width, 500))
            normalized = max(-1.0, min(1.0, (self.scope_samples[source_index] - offset) / scale))
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
                gain = 10 ** (self.receive_gain_db.get() / 20)
                amplified = array("f", (max(-1.0, min(1.0, sample * gain)) for sample in self.latest))
                self.scope_samples = amplified
                if self.measurement_active:
                    self.measurement_sum_sq += sum(sample * sample for sample in self.latest)
                    self.measurement_count += len(self.latest)
                for frame in self.decoder.feed_frames(amplified.tobytes()):
                    # Each received frame replaces the previous result, including
                    # frames that fail CRC, so stale text cannot look newly received.
                    self.result.delete("1.0", "end")
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
        self.scan_stop.set()
        self.audio.stop()
        self.reference_server.stop()
        self.control.stop()
        self.destroy()


if __name__ == "__main__":
    Receiver().mainloop()
