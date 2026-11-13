"""Run a repeatable acoustic FSK sweep through the desktop apps and USB audio.

By default the script controls the visible transmitter and receiver through
loopback commands. Headless mode uses a separate receiver process. In either
mode, the message travels through audio and the reference travels locally.
"""

from __future__ import annotations

import argparse
from array import array
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from math import log10
from multiprocessing import get_context
import os
from pathlib import Path
from queue import Empty
from secrets import token_bytes
from tempfile import gettempdir
from time import monotonic, sleep

from audio_runtime import HighPass, OutputPlayer, ReceiverAudio, devices
from ipc_control import RECEIVER_PORT, TRANSMITTER_PORT, send_command
from modem import FSKDecoder, MAX_FREQUENCY, ModemConfig, compare_payload_bits, encode_payload, fsk_chunks


MESSAGE = "Laser Polarisation Modulation Transceiver"
PAYLOAD = MESSAGE.encode("utf-8")
FACTORS = (0.25, 0.5, 0.75)
RATIOS = (2, 3)
COLUMNS = (
    "bit_0_hz", "bit_1_hz", "speed_bps", "speed_factor", "tx_amplitude", "ber_percent",
    "bit_errors", "compared_bits", "signal_rms_dbfs", "noise_rms_dbfs",
    "crc_ok", "status", "attempts", "received_text", "message_id", "measured_at_utc",
)


@dataclass(frozen=True)
class Trial:
    zero_hz: int
    one_hz: int
    speed_bps: float
    factor: float

    @property
    def config(self) -> ModemConfig:
        return ModemConfig(self.zero_hz, self.one_hz, self.speed_bps)

    @property
    def key(self) -> tuple[str, str, str]:
        return str(self.zero_hz), str(self.one_hz), f"{self.speed_bps:g}"


def zero_frequencies():
    base = 100
    while base * 2 <= MAX_FREQUENCY:
        for numerator, denominator in ((1, 1), (3, 2), (3, 1), (7, 1)):
            zero = base * numerator // denominator
            if zero * 2 <= MAX_FREQUENCY:
                yield zero
        base *= 10


def plan() -> list[Trial]:
    trials = []
    for zero in zero_frequencies():
        for ratio in RATIOS:
            one = zero * ratio
            if one > MAX_FREQUENCY:
                continue
            for factor in FACTORS:
                trial = Trial(zero, one, (one - zero) * factor, factor)
                try:
                    trial.config.validate()
                except ValueError:
                    continue
                trials.append(trial)
    return trials


def _dbfs(power: float) -> float | None:
    return 10 * log10(power) if power > 0 else None


def _receiver_process(connection, input_device: int) -> None:
    try:
        while True:
            command = connection.recv()
            if command is None:
                return
            config, message_id, expected, expected_seconds = command
            audio = ReceiverAudio()
            decoder = FSKDecoder(config)
            cutoff = max(20, min(500, min(config.zero_hz, config.one_hz) / 3))
            high_pass = HighPass(cutoff)
            try:
                audio.start(input_device)
                baseline_sum = baseline_count = 0
                baseline_until = monotonic() + 0.25
                while monotonic() < baseline_until:
                    try:
                        chunk = audio.captured.get(timeout=0.05)
                    except Empty:
                        continue
                    samples = array("f")
                    samples.frombytes(chunk)
                    filtered = high_pass.process(samples)
                    baseline_sum += sum(sample * sample for sample in filtered)
                    baseline_count += len(filtered)
                connection.send({"ready": True})
                signal_sum = signal_count = 0
                frames = []
                matched = None
                deadline = monotonic() + expected_seconds + 4
                while monotonic() < deadline:
                    try:
                        chunk = audio.captured.get(timeout=0.2)
                    except Empty:
                        continue
                    samples = array("f")
                    samples.frombytes(chunk)
                    filtered = high_pass.process(samples)
                    signal_sum += sum(sample * sample for sample in filtered)
                    signal_count += len(filtered)
                    for frame in decoder.feed_frames(chunk):
                        frames.append(frame)
                        if frame.message_id == message_id:
                            matched = frame
                    if matched is not None:
                        break
                frame = matched or (frames[0] if frames else None)
                noise_power = baseline_sum / baseline_count if baseline_count else 0.0
                signal_power = signal_sum / signal_count if signal_count else 0.0
                if frame is None:
                    result = {"status": "no_frame", "ber_percent": "", "bit_errors": "",
                              "compared_bits": "", "crc_ok": "", "received_text": ""}
                else:
                    errors, bits = compare_payload_bits(frame.payload, expected)
                    status = "ok" if frame.crc_ok and frame.message_id == message_id else (
                        "bad_crc" if not frame.crc_ok else "id_mismatch")
                    result = {
                        "status": status, "ber_percent": 100 * errors / bits,
                        "bit_errors": errors, "compared_bits": bits,
                        "crc_ok": int(frame.crc_ok),
                        "received_text": frame.payload.decode("utf-8", errors="replace"),
                    }
                result["signal_rms_dbfs"] = _dbfs(signal_power)
                result["noise_rms_dbfs"] = _dbfs(noise_power)
                connection.send(result)
            except Exception as exc:
                connection.send({"error": str(exc)})
            finally:
                audio.stop()
    except EOFError:
        return
    finally:
        connection.close()


def _select_device(direction: str, requested: int | None) -> int:
    available = devices(direction)
    allowed = [(index, name) for index, name in available if "teams" not in name.lower()]
    if requested is not None:
        match = next((index for index, _ in allowed if index == requested), None)
        if match is None:
            raise ValueError(f"Urządzenie {requested} nie jest dostępnym {direction} (Teams jest wykluczony).")
        return match
    usb = next((index for index, name in allowed if "usb" in name.lower()), None)
    if usb is None:
        raise ValueError(f"Nie znaleziono urządzenia USB dla {direction}; podaj je jawnie.")
    return usb


def _run_trial(connection, player: OutputPlayer, trial: Trial, output_device: int,
               amplitude: float) -> dict:
    message_id = token_bytes(8)
    bits = encode_payload(PAYLOAD, message_id)
    seconds = len(bits) / trial.speed_bps
    connection.send((trial.config, message_id, PAYLOAD, seconds))
    if not connection.poll(10):
        raise RuntimeError("Proces odbiornika nie odpowiedział przy uruchamianiu pomiaru.")
    ready = connection.recv()
    if not ready.get("ready"):
        raise RuntimeError(f"Nie można uruchomić odbiornika: {ready.get('error', ready)}")
    player.play_chunks(fsk_chunks(bits, trial.config, amplitude), output_device)
    player.thread.join(timeout=seconds + 12)
    if player.active:
        player.stop()
        raise RuntimeError("Nadawanie przekroczyło oczekiwany czas.")
    kind, detail = player.events.get_nowait()
    if kind == "error":
        raise RuntimeError(f"Błąd nadajnika: {detail}")
    if not connection.poll(10):
        raise RuntimeError("Proces odbiornika nie zwrócił wyniku pomiaru.")
    result = connection.recv()
    if result.get("error"):
        raise RuntimeError(f"Błąd odbiornika: {result['error']}")
    return {
        "bit_0_hz": trial.zero_hz, "bit_1_hz": trial.one_hz,
        "speed_bps": f"{trial.speed_bps:g}", "speed_factor": f"{trial.factor:g}",
        "tx_amplitude": f"{amplitude:g}",
        **result, "message_id": message_id.hex(),
        "measured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _gui_command(port: int, command: dict) -> dict:
    try:
        result = send_command(port, command)
    except OSError as exc:
        app = "Nadajnik" if port == TRANSMITTER_PORT else "Odbiornik"
        raise RuntimeError(f"{app} nie odpowiada. Uruchom oba okna z najnowszej wersji: {exc}") from exc
    if result.get("error"):
        raise RuntimeError(f"Aplikacja zgłosiła błąd: {result['error']}")
    return result


def _run_gui_trial(trial: Trial, input_device: int, output_device: int,
                   amplitude: float, message: str = MESSAGE, stop_event=None) -> dict:
    if stop_event is not None and stop_event.is_set():
        raise InterruptedError("Pomiar zatrzymany.")
    settings = {"zero_hz": trial.zero_hz, "one_hz": trial.one_hz,
                "speed_bps": trial.speed_bps}
    _gui_command(RECEIVER_PORT, {"action": "prepare", **settings,
                                 "input_device": input_device})
    sleep(0.25)
    _gui_command(RECEIVER_PORT, {"action": "begin"})
    sent = _gui_command(TRANSMITTER_PORT, {"action": "send", **settings,
                                           "output_device": output_device,
                                           "amplitude": amplitude, "text": message})
    if not sent["reference_sent"]:
        raise RuntimeError("Nadajnik nie przekazał lokalnego wzorca do Odbiornika.")
    deadline = monotonic() + sent["seconds"] + 6
    received = None
    output_done_at = None
    while monotonic() < deadline:
        if stop_event is not None and stop_event.is_set():
            _gui_command(TRANSMITTER_PORT, {"action": "stop"})
            _gui_command(RECEIVER_PORT, {"action": "finish"})
            raise InterruptedError("Pomiar zatrzymany.")
        status = _gui_command(RECEIVER_PORT, {"action": "status"})
        candidate = status.get("result")
        if candidate is not None and candidate.get("message_id") == sent["message_id"]:
            received = candidate
        sender = _gui_command(TRANSMITTER_PORT, {"action": "status"})
        if sender.get("error"):
            raise RuntimeError(f"Błąd wyjścia audio: {sender['error']}")
        if not sender["active"] and output_done_at is None:
            output_done_at = monotonic()
        if received is not None and output_done_at is not None:
            break
        if output_done_at is not None and monotonic() - output_done_at > 2:
            break
        sleep(0.1)
    result = _gui_command(RECEIVER_PORT, {"action": "finish"})
    if result.get("message_id") not in ("", sent["message_id"]):
        result["status"] = "id_mismatch"
    return {
        "bit_0_hz": trial.zero_hz, "bit_1_hz": trial.one_hz,
        "speed_bps": f"{trial.speed_bps:g}", "speed_factor": f"{trial.factor:g}",
        "tx_amplitude": f"{amplitude:g}",
        **result, "message_id": sent["message_id"],
        "measured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _existing_rows(path: Path) -> dict[tuple[str, str, str], dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as source:
        rows = {(row["bit_0_hz"], row["bit_1_hz"], row["speed_bps"]): row
                for row in csv.DictReader(source)}
        for row in rows.values():
            if not row.get("tx_amplitude"):
                row["tx_amplitude"] = "0.4"
            if not row.get("attempts"):
                row["attempts"] = "1"
        return rows


def _save_rows(path: Path, rows: dict[tuple[str, str, str], dict], trials: list[Trial]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    ordered = [rows[trial.key] for trial in trials if trial.key in rows]
    known = {trial.key for trial in trials}
    ordered.extend(row for key, row in rows.items() if key not in known)
    with temporary.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(ordered)
    os.replace(temporary, path)


def _pending_trials(trials: list[Trial], rows: dict, retry_status: set[str] | None) -> list[Trial]:
    if retry_status:
        return [trial for trial in trials if trial.key in rows
                and rows[trial.key]["status"] in retry_status]
    return [trial for trial in trials if trial.key not in rows
            or rows[trial.key]["status"] == "no_frame"]


def make_plots(csv_path: Path, description: str = "") -> tuple[Path, Path]:
    cache = Path(gettempdir()) / "sound_matplotlib_cache"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with csv_path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    amplitudes = {row.get("tx_amplitude", "") for row in rows if row.get("tx_amplitude", "")}
    level = (f" (poziom nadajnika {100 * float(next(iter(amplitudes))):g}%)"
             if len(amplitudes) == 1 else "")
    outputs = []
    zeros = sorted({int(row["bit_0_hz"]) for row in rows})
    columns = min(3, len(zeros))
    rows_count = (len(zeros) + columns - 1) // columns
    for column, ylabel, suffix in (
        ("ber_percent", "BER [%]", "ber_vs_bps.png"),
        ("signal_rms_dbfs", "Siła sygnału, RMS [dBFS]", "signal_vs_bps.png"),
    ):
        figure, grid = plt.subplots(rows_count, columns, squeeze=False,
                                   figsize=(6 * columns, 4.6 * rows_count),
                                   layout="constrained")
        for panel, zero in enumerate(zeros):
            axis = grid.flat[panel]
            selected = [row for row in rows if int(row["bit_0_hz"]) == zero and row[column] != ""]
            positions = {}
            for row in selected:
                key = (float(row["speed_bps"]), float(row[column]))
                positions.setdefault(key, []).append(row)
            for index, ((speed, value), samples) in enumerate(sorted(positions.items())):
                missing_frame = any(sample.get("ber_percent") != ""
                                    and float(sample["ber_percent"]) == 100 for sample in samples)
                color = "#b22222" if missing_frame else "#216a93"
                axis.scatter(speed, value, color=color, marker="x" if missing_frame else "o",
                             s=55 + 20 * (len(samples) - 1), zorder=3)
                label = " / ".join(str(sample["bit_1_hz"]) for sample in samples)
                dx, dy = ((5, 7), (5, -9), (-5, 7), (-5, -9), (5, 13), (-5, -15))[index % 6]
                if column == "ber_percent" and value <= 5:
                    dx, dy = (5 if index % 3 else -5), (7 if index % 2 else 16)
                axis.annotate(label, (speed, value), xytext=(dx, dy),
                              textcoords="offset points", fontsize=8,
                              ha="left" if dx > 0 else "right",
                              va="bottom" if dy > 0 else "top", color=color)
            axis.set_xscale("log")
            axis.set_ylabel(ylabel)
            axis.set_xlabel("Szybkość [bit/s]")
            axis.set_title(f"bit 0 = {zero} Hz", fontsize=11)
            axis.grid(True, which="both", alpha=0.25)
            speeds = [float(row["speed_bps"]) for row in rows if int(row["bit_0_hz"]) == zero]
            axis.set_xlim(min(speeds) * 0.78, max(speeds) * 1.3)
            if column == "ber_percent":
                axis.set_ylim(-5, 115)
            elif selected:
                levels = [float(row[column]) for row in selected]
                padding = max(0.8, (max(levels) - min(levels)) * 0.22)
                axis.set_ylim(min(levels) - padding, max(levels) + padding)
        for panel in range(len(zeros), rows_count * columns):
            grid.flat[panel].set_visible(False)
        detail = f" — {description}" if description else level
        frame_loss_score = any(row.get("ber_percent") != ""
                               and float(row["ber_percent"]) == 100 for row in rows)
        note = "Liczba przy punkcie = bit 1 [Hz]."
        if frame_loss_score:
            note += " Czerwony × = brak ramki (BER 100%)."
        figure.suptitle(f"{ylabel} od szybkości transmisji{detail}\n{note}", fontsize=14)
        target = csv_path.with_name(f"{csv_path.stem}_{suffix}")
        figure.savefig(target, dpi=160)
        plt.close(figure)
        outputs.append(target)
    return tuple(outputs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Automatyczny pomiar BER i siły sygnału przez karty audio.")
    parser.add_argument("--input-device", type=int, help="Numer wejścia audio; domyślnie pierwsze USB.")
    parser.add_argument("--output-device", type=int, help="Numer wyjścia audio; domyślnie pierwsze USB.")
    parser.add_argument("--amplitude", type=float, default=0.4, help="Amplituda cyfrowa 0–1 (domyślnie 0,4).")
    parser.add_argument("--output", type=Path, default=Path("measurements/ber_sweep_gui.csv"))
    parser.add_argument("--max-trials", type=int, help="Wykonaj tylko pierwsze N pomiarów.")
    parser.add_argument("--only", action="append", metavar="ZERO,ONE,BPS",
                        help="Mierz wybrane ustawienie; opcję można powtórzyć.")
    parser.add_argument("--max-attempts", type=int, default=3,
                        help="Maksymalna liczba prób przy braku ramki (domyślnie 3).")
    parser.add_argument("--resume", action="store_true", help="Uzupełnij brakujące próby w istniejącym CSV.")
    parser.add_argument("--retry-status", action="append", help="Powtórz wiersze o podanym statusie (z --resume).")
    parser.add_argument("--dry-run", action="store_true", help="Pokaż plan bez nadawania dźwięku.")
    parser.add_argument("--list-devices", action="store_true", help="Pokaż urządzenia audio.")
    parser.add_argument("--plot-only", action="store_true", help="Utwórz wykresy z istniejącego CSV.")
    parser.add_argument("--headless", action="store_true", help="Mierz bez okien; domyślnie steruj oknami.")
    args = parser.parse_args()
    if args.list_devices:
        for direction in ("output", "input"):
            print(f"{direction}:")
            for index, name in devices(direction):
                print(f"  {index}: {name}")
        return
    if args.plot_only:
        print("Wykresy:", *make_plots(args.output), sep="\n  ")
        return
    trials = plan()
    if args.only:
        requested = set()
        for entry in args.only:
            try:
                zero, one, speed = entry.split(",")
                requested.add((str(int(zero)), str(int(one)), f"{float(speed):g}"))
            except ValueError:
                parser.error(f"Niepoprawne --only: {entry}; użyj ZERO,ONE,BPS.")
        found = {trial.key for trial in trials}
        if requested - found:
            parser.error(f"Ustawienia spoza planu: {sorted(requested - found)}")
        trials = [trial for trial in trials if trial.key in requested]
    if args.dry_run:
        print(f"Liczba pomiarów: {len(trials)}")
        for trial in trials:
            print(f"{trial.zero_hz:5} {trial.one_hz:5} {trial.speed_bps:8g} bit/s "
                  f"({len(encode_payload(PAYLOAD)) / trial.speed_bps:.2f} s)")
        return
    if not 0 < args.amplitude <= 1:
        parser.error("Amplituda musi być w zakresie (0, 1].")
    if args.max_trials is not None and args.max_trials < 1:
        parser.error("--max-trials musi być dodatnie.")
    if args.max_attempts < 1:
        parser.error("--max-attempts musi być dodatnie.")
    if args.retry_status and not args.resume:
        parser.error("--retry-status wymaga --resume.")
    if args.output.exists() and not args.resume:
        parser.error("CSV już istnieje; użyj --resume albo wskaż inny plik.")
    output_device = _select_device("output", args.output_device)
    input_device = _select_device("input", args.input_device)
    rows = _existing_rows(args.output) if args.resume else {}
    remaining = _pending_trials(trials, rows, set(args.retry_status) if args.retry_status else None)
    if args.max_trials is not None:
        remaining = remaining[:args.max_trials]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _save_rows(args.output, rows, trials)
    receiver = None
    connection = None
    player = None
    if args.headless:
        context = get_context("spawn")
        connection, child_connection = context.Pipe()
        receiver = context.Process(target=_receiver_process, args=(child_connection, input_device), daemon=True)
        receiver.start()
        child_connection.close()
        player = OutputPlayer()
    try:
        for index, trial in enumerate(remaining, 1):
            print(f"[{index}/{len(remaining)}] 0={trial.zero_hz} Hz, 1={trial.one_hz} Hz, "
                  f"{trial.speed_bps:g} bit/s", flush=True)
            previous = rows.get(trial.key, {})
            attempts = int(previous.get("attempts") or (1 if previous else 0))
            for repeat in range(1, args.max_attempts + 1):
                row = (_run_trial(connection, player, trial, output_device, args.amplitude)
                       if args.headless else
                       _run_gui_trial(trial, input_device, output_device, args.amplitude))
                attempts += 1
                row["attempts"] = attempts
                rows[trial.key] = row
                _save_rows(args.output, rows, trials)
                print(f"  próba {repeat}/{args.max_attempts}: status={row['status']}, "
                      f"BER={row['ber_percent']}, RMS={row['signal_rms_dbfs']}", flush=True)
                if row["status"] != "no_frame":
                    break
    finally:
        if args.headless:
            player.stop()
            try:
                connection.send(None)
            except (BrokenPipeError, EOFError):
                pass
            connection.close()
            receiver.join(timeout=2)
            if receiver.is_alive():
                receiver.terminate()
                receiver.join(timeout=2)
    print("CSV:", args.output)
    completed = sum(rows.get(trial.key, {}).get("status") not in (None, "no_frame") for trial in trials)
    print(f"Zakończone pomiary: {completed}/{len(trials)}; oczekujące: {len(trials) - completed}")
    print("Wykresy:", *make_plots(args.output), sep="\n  ")


if __name__ == "__main__":
    main()
